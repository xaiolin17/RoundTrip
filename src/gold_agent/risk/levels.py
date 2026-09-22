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
2. **本地配套计算** —— LLM 给的是"位置"，不是"订单参数"。
   架构规则：订单参数只出自 risk 模块（docs/05）。所以这里做：
     · 取 LLM 给的最近有效压力位/支撑位
     · 与入场价一起换算成 sl / tp
     · 方向校验（止损必须在正确一侧）
     · 最小距离校验（防贴脸，用 ATR 兜底下限）
     · 盈亏比校验
     · 回落到 skill 结构位（缠论中枢/SMC OB）做交叉验证

LLM 不可用时
------------
用户选定：**不开仓**，等 LLM 可用。
理由：止损止盈必须基于压力位判断，猜点位比不交易更危险。
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

    if not sup and not res and hint_sl is None and hint_tp is None:
        out.reason = "llm_no_levels"
        return out

    # 本地结构位并入候选（交叉验证 + LLM 漏给时兜底）
    s_sup, s_res = _structure_levels(ev) if ev is not None else ([], [])
    if s_sup or s_res:
        out.notes.append(
            f"本地结构位并入: 支撑x{len(s_sup)} 压力x{len(s_res)}")
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
            out.sl_source = "llm_support"
            out.used_sl_level = lv
        elif hint_sl is not None and hint_sl < entry:
            out.sl = round(hint_sl, 3)
            out.sl_source = "llm_hint"
            out.used_sl_level = hint_sl
    else:
        lv = _nearest_above(res_all, entry)
        if lv is not None:
            out.sl = round(lv + pad, 3)
            out.sl_source = "llm_resistance"
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
            out.tp_source = "llm_resistance"
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
            out.tp_source = "llm_support"
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
