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
    #: 用到的压力/支撑位
    used_sl_level: float | None = None
    used_tp_level: float | None = None
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


def _structure_levels(ev) -> tuple[list[float], list[float]]:
    """从本地 skill 结构里取支撑/压力候选（交叉验证用）。

    缠论：中枢 zg（上沿=压力）/ zd（下沿=支撑）
    SMC ：bear OB 上沿=压力；bull OB 下沿=支撑
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
    return sup, res


def _nearest_below(levels: list[float], price: float) -> float | None:
    c = [x for x in levels if x < price]
    return max(c) if c else None


def _nearest_above(levels: list[float], price: float) -> float | None:
    c = [x for x in levels if x > price]
    return min(c) if c else None


def _target_beyond(levels: list[float], price: float, need_dist: float,
                   direction: str) -> float | None:
    """选**最近且距离足够**的压力/支撑位作止盈目标。

    只取"最近的压力位"会让盈亏比频繁不达标 —— 近处常有小压力位，
    但它太近、不够赔率。正确做法是：在满足最小盈亏比的前提下取**最近**的
    那个结构位，这样既尊重压力位结构，又不会因为一个小压力位放弃整笔交易。
    """
    if direction == "LONG":
        cands = sorted(x for x in levels if x > price)
        for x in cands:
            if x - price >= need_dist:
                return x
    else:
        cands = sorted((x for x in levels if x < price), reverse=True)
        for x in cands:
            if price - x >= need_dist:
                return x
    return None


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
                 ev=None, atr: float | None = None) -> TradeLevels:
    """按 LLM 判断的压力位/支撑位算止损止盈。

    做多：止损 = 下方最近**支撑**位再让开一点；止盈 = 上方最近**压力**位
    做空：止损 = 上方最近**压力**位再让开一点；止盈 = 下方最近**支撑**位
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
    s_sup, s_res = _structure_levels(ev) if ev is not None else ([], [])
    if s_sup or s_res:
        out.notes.append(
            f"本地结构位并入: 支撑x{len(s_sup)} 压力x{len(s_res)}")

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
    pad = (CFG.risk.level_pad_atr * atr) if atr else 0.0

    if direction == "LONG":
        # 止损：下方最近支撑，再让开 pad
        lv = _nearest_below(sup_all, entry)
        if lv is not None:
            out.sl = round(lv - pad, 3)
            out.sl_source = _pick_src(lv, sup, s_sup, "support")
            out.used_sl_level = lv
        elif hint_sl is not None and hint_sl < entry:
            out.sl = round(hint_sl, 3)
            out.sl_source = "llm_hint"
            out.used_sl_level = hint_sl
    else:
        lv = _nearest_above(res_all, entry)
        if lv is not None:
            out.sl = round(lv + pad, 3)
            out.sl_source = _pick_src(lv, res, s_res, "resistance")
            out.used_sl_level = lv
        elif hint_sl is not None and hint_sl > entry:
            out.sl = round(hint_sl, 3)
            out.sl_source = "llm_hint"
            out.used_sl_level = hint_sl

    # ---- 先定止损，再据此选"够赔率"的止盈压力位 ----
    if out.sl is None:
        out.reason = "no_support_below" if direction == "LONG" else "no_resistance_above"
        return out
    sl_dist = abs(entry - out.sl)
    if sl_dist <= 0:
        out.reason = "sl_at_entry"
        return out
    if min_d and sl_dist < min_d:
        # 贴脸 → 按 ATR 下限外扩（保持方向不变）
        out.notes.append(f"止损距离 {sl_dist:.3f} < 下限 {min_d:.3f} → 外扩")
        out.sl = round(entry - min_d if direction == "LONG" else entry + min_d, 3)
        sl_dist = min_d
        out.sl_source += "+atr_floor"

    need = sl_dist * CFG.risk.min_rr
    if direction == "LONG":
        cands = [x for x in res_all if x > entry]
        lv2 = _target_beyond(res_all, entry, need, "LONG")
        if lv2 is not None:
            out.tp = round(lv2, 3)
            out.tp_source = _pick_src(lv2, res, s_res, "resistance")
            out.used_tp_level = lv2
        elif hint_tp is not None and hint_tp - entry >= need:
            out.tp = round(hint_tp, 3)
            out.tp_source = "llm_hint"
            out.used_tp_level = hint_tp
        elif not cands and hint_tp is None:
            out.reason = "no_resistance_above"
            return out
    else:
        cands = [x for x in sup_all if x < entry]
        lv2 = _target_beyond(sup_all, entry, need, "SHORT")
        if lv2 is not None:
            out.tp = round(lv2, 3)
            out.tp_source = _pick_src(lv2, sup, s_sup, "support")
            out.used_tp_level = lv2
        elif hint_tp is not None and entry - hint_tp >= need:
            out.tp = round(hint_tp, 3)
            out.tp_source = "llm_hint"
            out.used_tp_level = hint_tp
        elif not cands and hint_tp is None:
            out.reason = "no_support_below"
            return out

    # ---- 校验 ----
    if out.tp is None:
        # 有候选位但都不够赔率 —— 与"根本没有位"区分开，便于排查
        out.reason = f"rr_below_{CFG.risk.min_rr}"
        return out

    out.sl_dist = round(abs(entry - out.sl), 3)
    out.tp_dist = round(abs(out.tp - entry), 3)
    if out.tp_dist < out.sl_dist * CFG.risk.min_rr - 1e-9:
        out.reason = f"rr_below_{CFG.risk.min_rr}"
        return out

    out.ok = True
    return out
