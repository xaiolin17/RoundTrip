"""压力位/支撑位 → 止损止盈（用户要求：由 LLM 判断，本地只做配套计算）。

用户原话：

> 止盈止损得看压力位 可以把 skill 的输出给 LLM 来判断
> LLM 输出后修改一下再按照配套计算

分工
----
1. **LLM 判断压力位/支撑位** —— skill 的输出（缠论中枢边界、SMC 的
   Order Block / FVG / equal highs-lows）已经在 `build_review_user()` 里
   喂给 LLM 了。本模块扩展 schema，要求 LLM 显式给出：
     support_levels[]    支撑位（做多的止损放这些下方）
     resistance_levels[] 压力位（做多的止盈放这些下方）
   以及它认为最合适的 `sl_hint` / `tp_hint`。
2. **本地结构位是独立来源，不只是"交叉验证"** —— 缠论中枢的
   zg/zd/gg/dd、SMC 的 OB / FVG / equal HL 由 `_structure_levels()`
   直接从 skill 输出提取，**不需要 LLM**。
3. **本地配套计算** —— LLM 给的是"位置"，不是"订单参数"。
   架构规则：订单参数只出自 risk 模块（docs/05）。所以这里做：
     · 取最近有效压力位/支撑位（LLM 给的 + 本地结构位合并）
     · 与入场价一起换算成 sl / tp
     · 方向校验（止损必须在正确一侧）
     · 最小距离校验（防贴脸，用 ATR 兜底下限）
     · 盈亏比校验

LLM 不给点位时
--------------
**不是**"不开仓"。用户澄清（原话）：

> 我的意思是LLM没有相反的预测方向 并且当前距离我们盈利的压力位
> 也有距离就可以直接市价开仓

分工要分清：
  · LLM 的职责 = **方向否决**（在 decision 层用 `opposed` 实现：
    反向且 confidence >= llm_adverse_conf 才拦）
  · "离盈利压力位还有距离" = **赔率检查**（本模块的 min_rr）
  · 点位来源 = LLM 给的 **或本地结构位**（缠论中枢 / SMC OB / FVG /
    equal HL）—— `_structure_levels()` 直接从 skill 输出提取，
    **不需要 LLM**。

所以 LLM 不给点位**不构成拒绝理由**，只要本地结构位能给出点位即可开仓。
只有"两个来源都没有点位"才返回 `llm_no_levels`。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from gold_agent.common.config import CFG


@dataclass
class TradeLevels:
    """最终的止损止盈（本地配套计算的结果）。"""
    ok: bool = False
    reason: str = ""
    sl: float | None = None
    tp: float | None = None
    sl_dist: float = 0.0
    tp_dist: float = 0.0
    #: llm_resistance | llm_support | llm_hint | chanlun_center | smc_ob | atr
    sl_source: str = ""
    tp_source: str = ""
    #: 用到的止盈目标位（结构位或 LLM 建议值，= 缩放前的"计算值"）
    used_tp_level: float | None = None
    #: 「紧贴反向位」标记：非空时表示结构不利，由 gate 决定降仓（不再硬拒）。
    #: 取值 "resistance"（做多贴压力）| "support"（做空贴支撑）。
    conflict_side: str = ""
    conflict_level: float | None = None
    conflict_dist: float = 0.0
    notes: list[str] = field(default_factory=list)


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _levels(raw) -> list[float]:
    """把 LLM 给的数组洗成有效正数列表。"""
    out = []
    if not isinstance(raw, (list, tuple)):
        return out
    for x in raw:
        v = _num(x)
        if v is not None:
            out.append(v)
    return out


def _structure_levels(ev, atr: float | None = None) -> tuple[list[float], list[float]]:
    """从本地 skill 结构里取支撑/压力候选（交叉验证用）。

    缠论：中枢 zg（上沿=压力）/ zd（下沿=支撑）
    SMC ：bear OB 上沿=压力；bull OB 下沿=支撑

    ⚠️ 聚合去重（用户报告 fusion_vs_levels_conflict 拦得太重）：
    多个 TF（1m/5m/15m/1h/4h）的缠论中枢 + SMC OB/FVG/equal HL 全部
    堆进一个列表 -> 实测 196 支撑 / 195 压力，且 1m 的 SMC 位极密
    （同一区域常有几个位挤在 1 点内）。`_nearest_below` 取最近那个
    会命中 0.3 点外的 1m 噪音位 -> 做空被"紧贴支撑 0.34 点"误拦 13 次。
    这里把间距 < 0.25×ATR 的邻居合并（取均值），只留下**显著位**。

    ⚠️ 来源标签（`_structure_levels_tagged`）
    ----------------------------------------
    `_cluster` 返回裸浮点，聚合后无法分辨某个位来自缠论中枢还是 SMC。
    实测 127 笔真实单子里 `struct_*` 出现 35 次、`chanlun_*` 出现 **0 次**
    —— 不是 `_pick_src` 匹配失败（它拿到的就是聚合后的列表，能匹配上），
    而是来源信息在聚合前就丢了。

    `_structure_levels_tagged` 保留标签（合并簇取并集），数值与
    `_structure_levels` **完全一致**，只用于 `level_notes` 审计。
    实测（5m 走查，仅缠论输入）：被选中的止损位 **13/13 (100%)**
    来自缠论中枢、止盈位 12/13 (92%) 来自缠论中枢 —— 即缠论结构
    其实一直在决定订单的止损止盈，只是日志报不出来。
    """
    sup: list[float] = []
    res: list[float] = []
    for cr in (getattr(ev, "chanlun", None) or {}).values():
        c = getattr(cr, "center", None)
        if not c:
            continue
        for k, bucket in (("zg", res), ("gg", res), ("zd", sup), ("dd", sup)):
            v = _num(c.get(k))
            if v is not None:
                bucket.append(v)
    mob = getattr(ev, "mobius", None)
    items = (mob.items() if isinstance(mob, dict)
             else ((("15m", mob),) if mob is not None else ()))
    for _tf, mr in items:
        if mr is None or getattr(mr, "status", "") == "unavailable":
            continue
        try:
            for o in mr.active_order_blocks("swing"):
                bot, top = _num(o.get("bottom")), _num(o.get("top"))
                bias = str(o.get("bias") or "").lower()
                if bias.startswith("bear") and top is not None:
                    res.append(top)
                elif bias.startswith("bull") and bot is not None:
                    sup.append(bot)
            for f in mr.active_fvgs():
                bot, top = _num(f.get("bottom")), _num(f.get("top"))
                bias = str(f.get("bias") or "").lower()
                if bias.startswith("bear") and top is not None:
                    res.append(top)
                elif bias.startswith("bull") and bot is not None:
                    sup.append(bot)
            for e in getattr(mr, "equal_highs", []) or []:
                v = _num(e.get("level"))
                if v is not None:
                    res.append(v)
            for e in getattr(mr, "equal_lows", []) or []:
                v = _num(e.get("level"))
                if v is not None:
                    sup.append(v)
        except Exception:
            continue
    # ---- 聚合：间距 < 0.25×ATR 的邻居合并（无 ATR 时按 1.0 点保守合并）----
    gap = (0.25 * atr) if atr else 1.0
    if gap > 0:
        sup = _cluster(sup, gap)
        res = _cluster(res, gap)
    return sup, res


def _structure_levels_tagged(
        ev, atr: float | None = None,
        digits: int = 3) -> tuple[list[tuple[float, str]],
                                  list[tuple[float, str]]]:
    """同 `_structure_levels`，但每个位带**来源标签**（缠论 / SMC）。

    返回值 `[(价格, 标签), ...]`，标签形如 `chanlun` / `smc` / `chanlun+smc`
    （合并簇取并集）。用途：`level_notes` 审计 —— 回答"这一单的止损
    到底是缠论中枢给的，还是 SMC 的 OB 给的"。

    刻意与 `_structure_levels` **分开实现**而不是改它的返回类型：
    后者是既有接口（`tests/test_structure_real.py`、
    `tests/test_risk_real.py` 都直接断言 `struct_support` 等标签），
    改签名会破坏契约。本函数只用于审计展示。

    `digits`：该品种价格小数位（见 `trade_levels` 的说明）。
    """
    sup_t: list[tuple[float, str]] = []
    res_t: list[tuple[float, str]] = []
    for cr in (getattr(ev, "chanlun", None) or {}).values():
        c = getattr(cr, "center", None)
        if not c:
            continue
        for k, bucket in (("zg", res_t), ("gg", res_t),
                          ("zd", sup_t), ("dd", sup_t)):
            v = _num(c.get(k))
            if v is not None:
                bucket.append((v, "chanlun"))
    mob = getattr(ev, "mobius", None)
    items = (mob.items() if isinstance(mob, dict)
             else ((("15m", mob),) if mob is not None else ()))
    for _tf, mr in items:
        if mr is None or getattr(mr, "status", "") == "unavailable":
            continue
        try:
            for o in mr.active_order_blocks("swing"):
                bot, top = _num(o.get("bottom")), _num(o.get("top"))
                bias = str(o.get("bias") or "").lower()
                if bias.startswith("bear") and top is not None:
                    res_t.append((top, "smc"))
                elif bias.startswith("bull") and bot is not None:
                    sup_t.append((bot, "smc"))
            for f in mr.active_fvgs():
                bot, top = _num(f.get("bottom")), _num(f.get("top"))
                bias = str(f.get("bias") or "").lower()
                if bias.startswith("bear") and top is not None:
                    res_t.append((top, "smc"))
                elif bias.startswith("bull") and bot is not None:
                    sup_t.append((bot, "smc"))
            for e in getattr(mr, "equal_highs", []) or []:
                v = _num(e.get("level"))
                if v is not None:
                    res_t.append((v, "smc"))
            for e in getattr(mr, "equal_lows", []) or []:
                v = _num(e.get("level"))
                if v is not None:
                    sup_t.append((v, "smc"))
        except Exception:
            continue
    gap = (0.25 * atr) if atr else 1.0
    if gap > 0:
        sup_t = _cluster_tagged(sup_t, gap, digits)
        res_t = _cluster_tagged(res_t, gap, digits)
    return sup_t, res_t


def _cluster(levels: list[float], gap: float,
             digits: int = 3) -> list[float]:
    """把相距 < gap 的位合并为均值簇，只返回**显著位**。

    196 个未聚合位 -> 合并后通常只剩几十个真正独立的位，
    `_nearest_below` 不会再命中 0.3 点外的 1m 噪音位。

    `digits`：该品种价格小数位（见 `trade_levels` 的说明）。
    """
    return [v for v, _ in _cluster_tagged([(x, "") for x in levels], gap, digits)]


def _cluster_tagged(levels: list[tuple[float, str]],
                    gap: float, digits: int = 3) -> list[tuple[float, str]]:
    """同 `_cluster`，但**保留来源标签**（证明某个位是谁给的）。

    ⚠️ 为什么需要它：`_cluster` 返回裸浮点，聚合后无法分辨某个位来自
    缠论中枢还是 SMC。实测 127 笔真实单子里 `struct_*` 出现 35 次、
    `chanlun_*` 出现 0 次 —— 来源信息在聚合前就丢了，导致无法回答
    "这一单的止损是缠论中枢定的吗"。

    合并规则与 `_cluster` 完全一致（间距 < gap 归为一簇、取均值），
    标签取簇内**所有来源的并集**（排序去重后以 `+` 连接），
    这样合并后仍能看出"这个位是缠论和 SMC 共同给出的"。

    `digits`：该品种价格小数位（见 `trade_levels` 的说明）。
    本函数在**聚合前**把价位规整到 digits —— 写死 3 会让 EURUSDm 的
    1m 结构位被截断到同一个值，把**本来独立的位误合并成一簇**，
    进而改变止损/止盈的选取。默认 3 保持单品种黄金行为不变。
    """
    if not levels:
        return []
    vals = sorted(set((round(float(x), digits), str(t)) for x, t in levels))
    out: list[tuple[float, str]] = []
    cur: list[tuple[float, str]] = [vals[0]]
    for v, t in vals[1:]:
        if v - cur[-1][0] < gap:
            cur.append((v, t))
        else:
            out.append(_merge_cluster(cur, digits))
            cur = [(v, t)]
    out.append(_merge_cluster(cur, digits))
    return out


def _merge_cluster(cur: list[tuple[float, str]],
                   digits: int = 3) -> tuple[float, str]:
    """把一簇 (值, 标签) 合成 (均值, 并集标签)。"""
    mean = round(sum(v for v, _ in cur) / len(cur), digits)
    tags = sorted({t for _, t in cur if t})
    return mean, "+".join(tags)


def _nearest_below(levels: list[float], price: float) -> float | None:
    c = [x for x in levels if x < price]
    return max(c) if c else None


def _nearest_above(levels: list[float], price: float) -> float | None:
    c = [x for x in levels if x > price]
    return min(c) if c else None


def _entangled(level: float, opposite_levels: list[float], gap: float) -> bool:
    """判断某个位是否与**反向位**纠缠（同区既有支撑又有压力 = 噪音区）。

    事故：LLM 给的位也有密集噪音（5586 轮入场 4286.141 上方 1.7 点
    压力 4287.87，但下方 0.44 点就有支撑 4287.43 —— 支撑/压力交错
    间距仅 0.26 点）。这种位不可信，用它判"贴脸压力/支撑"会误伤
    （做多被"紧贴压力"误拦，实际价格刚突破纠缠区）。
    判定：level 与 opposite 中任一位置的距离 < gap -> 纠缠。
    """
    for o in opposite_levels:
        if abs(o - level) < gap:
            return True
    return False


def _pick_src(level: float | None, llm_vals: list[float],
              struct_vals: list[float], kind: str) -> str:
    """判断选中的点位来自 LLM 还是本地结构位（决定 sl_source/tp_source）。

    `kind` = `support` | `resistance`。日志必须如实反映来源，
    否则无法判断"这一单的点位到底是谁给的"。
    """
    if level is None:
        return ""
    for x in llm_vals:
        if abs(level - x) < 1e-9:
            return f"llm_{kind}"
    for x in struct_vals:
        if abs(level - x) < 1e-9:
            return f"struct_{kind}"
    return f"llm_{kind}"


def trade_levels(direction: str, entry: float, review: dict | None,
                 ev=None, atr: float | None = None,
                 tp_shrink: float | None = None,
                 digits: int = 3) -> TradeLevels:
    """按 LLM 判断的压力位/支撑位算止损止盈。

    `digits`：该品种的价格小数位（`SymbolProfile.digits`）。
    ⚠️ 本函数内所有 `round(x, digits)` 必须用它，**不能写死 3**。
    `3` 是 XAUUSDm 的位数；对 EURUSDm（digits=5）会把
    `1.12419` 截成 `1.12400`（**偏 19 个 point**），对 USDJPYm 同理。
    与 `machine.py` 的 `_PX_DIGITS=3` 是同一类缺陷（那边已修）。

    `tp_shrink`：止盈**距离**的缩放比例；`None` = 用配置的
    `CFG.risk.first_tp_shrink`（首仓，0.70）。加仓路径显式传
    `CFG.risk.add_tp_shrink`（0.58）。

    ---- 统一定价语义（用户 2026-10-09 合并首仓与加仓）----

    首仓（用户原话）：
    > 我们每个品种首仓止盈点数为计算的70% 比如100买入 计算止盈110
    > 那么实际止盈107 止损按照盈亏比1.8计算
    > （有点和之前的加仓止盈也是百分比减小一样）

    加仓（用户原话，2026-10-08）：
    > 加仓的止损位置应该是按照止盈位置计算来的 盈亏比1.8
    > 然后加仓的单子止盈点不能按照计算的数值来 要对应缩小42% 也就是原值的58%

    步骤（首仓与加仓**完全同形**，只有缩放比例不同）：
      1. 先由结构位算出止盈目标（"计算值"，距离 D）
      2. 止盈距离缩到 `tp_shrink` 倍（首仓 0.70 / 加仓 0.58）
      3. 由**缩后的止盈距离**按 `min_rr` 反推止损
         止损距离 = 止盈距离 / min_rr
    → 止损**不再取自支撑位**，而是由止盈反推（`sl_source=rr_from_tp`）。

    ⚠️ 旧的"止损取支撑位、再找够赔率的压力位当止盈"路径已被用户本次
    要求**取代并删除**（不留双路径死代码）。但**融合分与压力/支撑位
    矛盾检测**（`conflict_side` / `conflict_dist`，供降仓用）仍然保留 ——
    它只依赖结构位、不依赖定价顺序。
    """
    out = TradeLevels()
    if entry is None or entry <= 0:
        out.reason = "bad_entry"
        return out

    review = review or {}
    sup = _levels(review.get("support_levels"))
    res = _levels(review.get("resistance_levels"))
    hint_sl = _num(review.get("sl_hint"))
    hint_tp = _num(review.get("tp_hint"))

    # 本地结构位（缠论中枢 / SMC OB / FVG / equal HL）—— **独立于 LLM 的点位来源**
    # ⚠️ 聚合去重（0.25×ATR）：196 个未聚合位会堆出 0.3 点外的 1m 噪音位，
    #    让"紧贴支撑/压力"误判（用户报告 fusion_vs_levels_conflict 拦太重）。
    s_sup, s_res = _structure_levels(ev, atr) if ev is not None else ([], [])
    if s_sup or s_res:
        out.notes.append(
            f"本地结构位并入: 支撑x{len(s_sup)} 压力x{len(s_res)}")
        # 来源可审计（原先聚合后来源丢失，无法回答"止损是谁给的"）
        try:
            t_sup, t_res = _structure_levels_tagged(ev, atr)
            n_ch = sum(1 for _, t in list(t_sup) + list(t_res) if "chanlun" in t)
            n_sm = sum(1 for _, t in list(t_sup) + list(t_res) if "smc" in t)
            if n_ch or n_sm:
                out.notes.append(
                    f"结构位来源: 缠论中枢x{n_ch} SMCx{n_sm}")
        except Exception:
            pass

    # ⚠️ 概念纠正（用户原话）：
    #     "我的意思是LLM没有相反的预测方向 并且当前距离我们盈利的压力位
    #      也有距离就可以直接市价开仓"
    #   即：**点位的来源不必是 LLM**。LLM 的职责是"方向否决"（在 decision
    #   层用 `opposed` 实现），而"离盈利压力位还有距离"是赔率检查（下面的
    #   min_rr）。所以只要**任一来源**能给出点位，就不该拦。
    #
    #   原实现把这个 early-return 放在并入本地结构位**之前** ——
    #   于是本模块自己注释里写的"LLM 漏给时兜底"成了**死代码**：
    #   实测本地明明能算出 2 支撑 / 2 压力，却仍返回 llm_no_levels
    #   并拒绝开仓（线上被这条拦了 7 单）。
    if not sup and not res and not s_sup and not s_res \
            and hint_sl is None and hint_tp is None:
        out.reason = "llm_no_levels"
        return out

    sup_all = sup + s_sup
    res_all = res + s_res

    # 最小距离（防贴脸）：用 ATR 定下限
    min_d = (CFG.risk.structure_sl_min_atr * atr) if atr else 0.0
    # ⚠️ 冲突判定阈值原为 6 处硬编码 `0.3`，是实测 180 次
    # `fusion_vs_levels_conflict` 拒绝里 159 次的**唯一驱动常数**，
    # 却无法调参（同段的 structure_sl_min_atr 早已走配置）。
    # 收敛到 CFG.risk.conflict_atr_mult，默认 0.3 保持行为不变。
    conf_d = CFG.risk.conflict_atr_mult * atr if atr else 0.0

    if direction == "LONG":
        # ---- 融合分与压力位矛盾检测（用户选定）----
        # 做多但**上方紧贴压力位** -> 进场就是买在压力位下方，随时被压回。
        # ⚠️ 只对 **LLM 给的位** 判定（用户语义：LLM 读 skill 输出判断的
        # 压力位/支撑位）。本地结构位（缠论/SMC）196 个未聚合位太密，
        # 1m 的 SMC 位常距价格 0.3 点——实测 10 轮被拦 8 轮拦错
        # （价格直接穿过"支撑"继续下跌，做空本可获利 0.8~4.1 点）。
        # 阈值 1×ATR：LLM 位 5~17 点间隔，1×ATR(≈15) 下几乎总会命中。
        # 收紧到 0.3×ATR（≈4.4 点）：只挡"真贴脸"（1m 内），
        # 不挡"还有空间"的位。
        near_res = _nearest_above(res, entry)
        if near_res is not None and atr and near_res - entry < conf_d:
            # ⚠️ 纠缠过滤（用户报告"怎么一直在拦截"）：LLM 位也有密集噪音。
            # 若该压力位下方 conf_d 内就有 LLM 支撑位（支撑/压力交错 =
            # 噪音区，实测 5586 轮交错间距仅 0.26 点），位不可信，
            # 跳过冲突判定放行；只有孤立压力位才算"真贴脸"。
            if _entangled(near_res, sup, conf_d):
                out.notes.append(
                    f"压力位 {near_res:.3f} 与支撑纠缠（噪音区），跳过贴脸判定")
            else:
                # ⚠️ 由**硬拒**改为**标记 + 降仓**（用户选定，见 CFG.risk.conflict_lot_mult）。
                # 实证：贴脸组与对照组的远期收益无统计差异（全部 |t|<1.96），
                # 而原实现把 205 个强信号（|z|>=2.66）100% 挡掉 ——
                # 相当于用一条无证据支持的规则否决了全部高分信号。
                # 语义上也讲不通：做多时上方压力位**正是止盈目标**，
                # 只要它在 min_rr 之外就完全不构成冲突（后者在下文照常检查）。
                # 现在：记为不利因素、降仓，但不阻断交易。
                out.conflict_side = "resistance"
                out.conflict_level = near_res
                out.conflict_dist = near_res - entry
                out.notes.append(
                    f"做多但紧贴压力位 {near_res:.3f}（距入场 {near_res - entry:.3f} "
                    f"< {CFG.risk.conflict_atr_mult}×ATR {conf_d:.2f}，LLM位）"
                    f"-> 结构不利，降仓处理（不再硬拒）")
    else:
        # ---- 融合分与压力位矛盾检测（用户选定）----
        # 做空但**下方紧贴支撑位** -> 进场就是卖在支撑位上方，随时被弹回。
        # ⚠️ 只对 LLM 给的位判定（原因见做多分支注释；本地 1m SMC 位
        # 是噪音，实测 8/10 拦错）。
        near_sup = _nearest_below(sup, entry)
        if near_sup is not None and atr and entry - near_sup < conf_d:
            # ⚠️ 纠缠过滤（与做多分支同理）：支撑位与压力位交错=噪音区，
            # 跳过贴脸判定放行；只有孤立支撑位才算"真贴脸"。
            if _entangled(near_sup, res, conf_d):
                out.notes.append(
                    f"支撑位 {near_sup:.3f} 与压力纠缠（噪音区），跳过贴脸判定")
            else:
                # 同做多分支：硬拒 -> 标记 + 降仓（用户选定）
                out.conflict_side = "support"
                out.conflict_level = near_sup
                out.conflict_dist = entry - near_sup
                out.notes.append(
                    f"做空但紧贴支撑位 {near_sup:.3f}（距入场 {entry - near_sup:.3f} "
                    f"< {CFG.risk.conflict_atr_mult}×ATR {conf_d:.2f}，LLM位）"
                    f"-> 结构不利，降仓处理（不再硬拒）")

    # ---- 统一定价：先定止盈 → 缩 N% → 按 min_rr 反推止损 ----
    # 首仓与加仓**同一套顺序**，只有缩放比例不同（0.70 / 0.58）。
    # 用户 2026-10-09 合并二者语义，旧的"止损取支撑位"路径已删除。
    if tp_shrink is None:
        tp_shrink = CFG.risk.first_tp_shrink
    return _levels_from_tp(direction, entry, out, res_all, sup_all,
                           res, sup, s_res, s_sup, hint_tp, min_d,
                           tp_shrink, digits)


def _levels_from_tp(direction: str, entry: float, out: TradeLevels,
                    res_all: list[float], sup_all: list[float],
                    res: list[float], sup: list[float],
                    s_res: list[float], s_sup: list[float],
                    hint_tp: float | None, min_d: float,
                    tp_shrink: float, digits: int = 3) -> TradeLevels:
    """统一定价核心：**由止盈反推止损**（首仓与加仓共用）。

    用户原话（首仓，2026-10-09）：
    > 我们每个品种首仓止盈点数为计算的70% 比如100买入 计算止盈110
    > 那么实际止盈107 止损按照盈亏比1.8计算

    用户原话（加仓，2026-10-08）：
    > 加仓的止损位置应该是按照止盈位置计算来的 盈亏比1.8
    > 然后加仓的单子止盈点不能按照计算的数值来 要对应缩小42% 也就是原值的58%

    步骤（首仓与加仓同形，只有 `tp_shrink` 不同：0.70 / 0.58）：
      1. 由结构位算出"计算值"止盈目标（做多取上方压力、做空取下方支撑）
      2. 止盈**距离**缩到 `tp_shrink` 倍
      3. 止损距离 = 缩后止盈距离 / `min_rr`
         —— 止损不再取自支撑位，而是**由止盈反推**，故 `sl_source="rr_from_tp"`

    为什么先缩止盈再反推止损：若先用未缩的结构距离反推止损、再缩止盈，
    实际盈亏比会掉到 `tp_shrink/min_rr`（首仓 0.70/1.8 ≈ 0.39），与用户
    "盈亏比 1.8"的要求矛盾；先缩止盈再反推才能让实际盈亏比正好等于 1.8。
    """
    # ---- 1. 取"计算值"止盈目标（未缩）----
    is_long = direction == "LONG"
    if is_long:
        raw_tp = _nearest_above(res_all, entry)
        lv_src, s_list = res, s_res
        kind = "resistance"
    else:
        raw_tp = _nearest_below(sup_all, entry)
        lv_src, s_list = sup, s_sup
        kind = "support"

    if raw_tp is None and hint_tp is not None:
        # 结构位没有可用目标时退到 LLM 的 tp_hint（也在正确一侧才算）
        if (is_long and hint_tp > entry) or (not is_long and hint_tp < entry):
            raw_tp = hint_tp
            out.tp_source = "llm_hint"
    if raw_tp is None:
        out.reason = "no_resistance_above" if is_long else "no_support_below"
        return out
    if not out.tp_source:
        out.tp_source = _pick_src(raw_tp, lv_src, s_list, kind)
    out.used_tp_level = raw_tp

    raw_tp_dist = abs(raw_tp - entry)
    if raw_tp_dist <= 0:
        out.reason = "tp_at_entry"
        return out

    # ---- 2. 止盈距离缩到 tp_shrink 倍（首仓 70% / 加仓 58%）----
    tp_dist = raw_tp_dist * tp_shrink
    # 缩后仍要尊重 ATR 防贴脸下限，否则止盈贴脸毫无意义
    if min_d and tp_dist < min_d:
        out.notes.append(
            f"缩短后止盈距离 {tp_dist:.3f} < 下限 {min_d:.3f} → 外扩到下限")
        tp_dist = min_d
    out.notes.append(
        f"止盈按用户要求缩 {1 - tp_shrink:.0%}（系数 {tp_shrink}）："
        f"结构距离 {raw_tp_dist:.3f} -> {tp_dist:.3f}")

    # ---- 3. 由缩后的止盈距离反推止损（盈亏比 = min_rr）----
    sl_dist = tp_dist / CFG.risk.min_rr
    prev_sl = out.sl
    out.sl = round(entry - sl_dist if is_long else entry + sl_dist, digits)
    # ⚠️ 这里**刻意**不使用按支撑/压力位算出的止损：
    #    用户要求止损来自止盈位置（首仓与加仓统一），不是支撑位。
    out.sl_source = "rr_from_tp"
    out.notes.append(
        f"止损由止盈反推：止盈距离 {tp_dist:.3f} / 盈亏比 "
        f"{CFG.risk.min_rr} = 止损距离 {sl_dist:.3f}"
        + (f"（原支撑位止损 {prev_sl} 已弃用）" if prev_sl else ""))

    out.tp = round(entry + tp_dist if is_long else entry - tp_dist, digits)
    if sl_dist <= 0:
        out.reason = "sl_at_entry"
        return out
    # ⚠️ 赔率校验用**未规整**的距离：sl_dist 恰好等于 tp_dist/min_rr，
    #    规整到 digits 位小数后会引入误差，若拿规整后的值比较，
    #    本应恰好等于 min_rr 的赔率会被误判为"低于 min_rr"而拒绝。
    if tp_dist < sl_dist * CFG.risk.min_rr - 1e-9:
        out.reason = f"rr_below_{CFG.risk.min_rr}"
        return out
    out.sl_dist = round(abs(entry - out.sl), digits)
    out.tp_dist = round(abs(out.tp - entry), digits)

    out.ok = True
    return out
