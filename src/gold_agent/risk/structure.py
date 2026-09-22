"""0.618 回调入场 + 压力位止损止盈（用户纠正后的语义）。

概念纠正记录（2026-09-22）
==========================
**第一版实现是错的**，把两个概念搞反了：

    错误理解：0.618 回调位 -> 止损    1.618 扩展位 -> 止盈
    正确理解：0.618 回调位 -> **入场点**（回调到位、反弹概率大）
              压力位/支撑位 -> **止损止盈**（由 LLM 读 skill 输出判断）

用户原话：

> 要考虑分型 现在是处于哪个周期的回调 那么到了0.618之后反弹几率大
> 这应该是入场点位  止盈止损得看压力位可以把skill得输出给LLM来判断

本模块负责两件事：
1. 算 0.618 回调**入场位**（`pullback_entry`）
2. 压力位/支撑位 -> 止损止盈在 `levels.py`

为什么要自己写检测（用户要求：非严格缠论要加上我们直接的处理）
================================================================
实测（现价 4343，1h ATR 16.8）：**缠论代理引擎在 1m 图上返回的是
15m 级别的段**——它在 1m 报的段 `4348.322->4365.234`（幅度 16.9）
与 15m 报的**完全相同**，说明它没有真正下沉到该图自己的级别。

后果：入场位离现价 12~32 点，挂单几乎不可能成交。

    周期   缠论代理 0.618位距现价    我们自己的摆动检测
    1m          +11.706                +0.589
    15m         +11.860               +11.860

所以本模块**自己算摆动**（分型式左右确认 + 同向合并），
缠论结果降为**第一层参考**（方向/中枢/背驰交给 LLM）。

自适应小周期
------------
用户要求"参考的周期大了，需要小周期判断，加大入场次数"。
做法：在小周期集合里，选**段幅度够大（>= min_leg_atr x ATR，滤噪音）
且 0.618 位离现价最近**的那个周期。

实测 1m k=1 会给出 2.787 点的段（纯噪音），门槛 0.25xATR=4.2 点
能正确把它滤掉。

0.5~0.618 挂单带
----------------
用户选定"0.5~0.618 挂单带，带内挂一单"。实测成交率提升：

    周期    0.618 单点    0.5~0.618 带    增益
    2m       79.6%         86.7%        +7.1
    15m      73.8%         86.2%        +12.4

挂单价取**带内离现价最近的那条边**（即 0.5 位一侧），以最大化成交；
仍只挂一张单，不恢复网格。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from gold_agent.common.config import CFG

#: 回调带的两条边（黄金分割）
RETRACE_NEAR = 0.5      #: 靠近趋势方向的一条边（更浅的回调，先被触及）
RETRACE_FAR = 0.618     #: 深回调边
#: 向后兼容别名
RETRACE = RETRACE_FAR


@dataclass
class PullbackEntry:
    """0.618 回调入场位及其状态。"""
    ok: bool = False
    reason: str = ""
    #: 挂单价（带内离现价最近的边；做多挂买入限价，做空挂卖出限价）
    entry: float | None = None
    #: 回调带两条边：near 靠趋势方向（浅），far 是 0.618（深）
    band_near: float | None = None
    band_far: float | None = None
    #: 现价相对入场带的关系：waiting（还没到）/ at_level（带内）/ passed（已越过）
    state: str = "unknown"
    #: 现价到挂单价的距离（正数）
    distance: float = 0.0
    #: 用的走势段
    leg: dict = field(default_factory=dict)
    #: 用哪个周期
    tf: str = ""
    #: 摆动确认根数
    swing_k: int = 0
    #: 定价来源：own_swing（我们自己的检测）| chanlun_segment | chanlun_stroke
    source: str = ""
    #: 分型区间（供参考/审计）
    fractal_range: float = 0.0
    notes: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════
# 我们自己的摆动检测（不依赖缠论代理引擎）
# ══════════════════════════════════════════════════════════════════
def find_swings(df: pd.DataFrame, k: int = 2) -> list[list]:
    """分型式摆动点：某根的高点是左右各 k 根的最高 -> 顶；低点同理 -> 底。

    返回 [[位置, "H"|"L", 价格], ...]，按时间递增。
    """
    if df is None or len(df) < 2 * k + 1:
        return []
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    out: list[list] = []
    for i in range(k, len(df) - k):
        w = slice(i - k, i + k + 1)
        if hi[i] == hi[w].max():
            out.append([i, "H", float(hi[i])])
        elif lo[i] == lo[w].min():
            out.append([i, "L", float(lo[i])])
    return out


def alternate_swings(sw: list[list]) -> list[list]:
    """把连续同类摆动合并成交替的高低点序列（同类取更极端的那个）。

    摆动检测会连续给出多个顶（或底），必须先合并，否则"一段"
    可能只是同一个顶附近的两根，幅度虚高。
    """
    alt: list[list] = []
    for i, kind, price in sw:
        if alt and alt[-1][1] == kind:
            better = (price > alt[-1][2]) if kind == "H" else (price < alt[-1][2])
            if better:
                alt[-1] = [i, kind, price]
        else:
            alt.append([i, kind, price])
    return alt


def last_leg(df: pd.DataFrame, k: int = 2) -> dict | None:
    """最近一段走势（交替序列的最后两个点）。"""
    alt = alternate_swings(find_swings(df, k))
    if len(alt) < 2:
        return None
    a, b = alt[-2], alt[-1]
    rng = abs(b[2] - a[2])
    if rng <= 0:
        return None
    return {"start": a[2], "end": b[2], "range": rng,
            "direction": "up" if b[1] == "H" else "down",
            "start_i": a[0], "end_i": b[0]}


def band_of(leg: dict, direction: str) -> tuple[float, float]:
    """由一段走势算出回调带两条边 (near, far)。

    做多：上行段 -> 从段高点回撤 near% / far%
    做空：下行段 -> 从段低点反弹 near% / far%

    两条边取自配置（用户选定 0.5~0.618 挂单带）。
    """
    r_near = getattr(CFG.risk, "pullback_band_near", RETRACE_NEAR)
    r_far = getattr(CFG.risk, "pullback_band_far", RETRACE_FAR)
    if direction == "LONG":
        return (leg["end"] - r_near * leg["range"],
                leg["end"] - r_far * leg["range"])
    return (leg["end"] + r_near * leg["range"],
            leg["end"] + r_far * leg["range"])


def own_candidates(frames: dict, direction: str, atr: float | None,
                   tfs: tuple[str, ...] | None = None,
                   ks: tuple[int, ...] | None = None) -> list[dict]:
    """扫描小周期，返回**同向**且幅度过噪音门槛的候选段。

    用户要求"小周期判断，加大入场次数"：把 1m~30m 全扫一遍，
    由调用方挑离现价最近的。
    """
    tfs = tfs or tuple(getattr(CFG.risk, "pullback_tfs",
                               ("1m", "2m", "5m", "10m", "15m", "30m")))
    ks = ks or tuple(getattr(CFG.risk, "pullback_swing_k", (1, 2, 3)))
    min_rng = (getattr(CFG.risk, "pullback_min_leg_atr", 0.25) * atr) if atr else 0.0
    want = "up" if direction == "LONG" else "down"
    out: list[dict] = []
    for tf in tfs:
        df = (frames or {}).get(tf)
        if df is None or len(df) < 10:
            continue
        for k in ks:
            leg = last_leg(df, k)
            if leg is None or leg["direction"] != want:
                continue
            if min_rng and leg["range"] < min_rng:
                continue        # 噪音：幅度太小，结构不可信
            near, far = band_of(leg, direction)
            out.append({"tf": tf, "k": k, "leg": leg,
                        "band_near": round(near, 3), "band_far": round(far, 3),
                        "source": "own_swing"})
    return out


# ══════════════════════════════════════════════════════════════════
# 缠论结果（第一层参考，作为自研检测的兜底）
# ══════════════════════════════════════════════════════════════════
def _legs(cl, prefer: str = "segments") -> list[dict]:
    if cl is None:
        return []
    raw = getattr(cl, "raw", None) or {}
    return list((raw.get("layers") or {}).get(prefer) or [])


def pick_leg(cl, direction: str) -> tuple[dict | None, str]:
    """挑最近一段**同向**走势：线段优先，没有则退到笔。

    LONG 用上行段（bottom->top），SHORT 用下行段（top->bottom）。
    """
    want = "up" if direction == "LONG" else "down"
    for key, tag in (("segments", "chanlun_segment"), ("strokes", "chanlun_stroke")):
        for item in reversed(_legs(cl, key)):
            if item.get("direction") != want:
                continue
            try:
                a = float(item["start_price"])
                b = float(item["end_price"])
            except (KeyError, TypeError, ValueError):
                continue
            if b == a:
                continue
            return ({"id": item.get("id"), "start": a, "end": b,
                     "range": abs(b - a), "direction": want}, tag)
    return None, ""


def fractal_range(cl, n: int = 2) -> float:
    """最近 n 个分型的价格区间。"""
    if cl is None:
        return 0.0
    raw = getattr(cl, "raw", None) or {}
    fracs = (raw.get("layers") or {}).get("fractals") or []
    recent = fracs[-n:] if len(fracs) >= n else fracs
    prices = []
    for f in recent:
        try:
            prices.append(float(f["price"]))
        except (KeyError, TypeError, ValueError):
            continue
    if len(prices) < 2:
        return 0.0
    return max(prices) - min(prices)


# ══════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════
def _entry_from_band(band_near: float, band_far: float, last_close: float | None,
                     direction: str) -> tuple[float, str, float]:
    """由回调带推出挂单价 + 状态 + 距离。

    挂单价始终取**带内离现价最近的、且在市价正确一侧**的边：
      - waiting（还没回踩到带内）→ 取近端边（0.5），最大化成交概率
      - at_level（现价已在带内）→ 取远端边（0.618），既能成交又拿到更好的价
      - passed（已越过整条带）→ 结构可能已破，调用方应拒绝挂单

    ⚠️ 必须保证限价单在市价的正确一侧（做多在市价下方、做空在上方），
    否则 MT5 会以 `Invalid price` 拒单。`at_level` 尤其危险：若直接拿
    现价当挂单价，就变成了"限价单挂在市价上"，必然被拒。
    """
    lo, hi = min(band_near, band_far), max(band_near, band_far)
    if last_close is None or last_close <= 0:
        return round(band_far, 3), "unknown", 0.0
    if direction == "LONG":
        if last_close > hi:                      # 还没回踩到带内 -> 近端边
            return round(hi, 3), "waiting", round(last_close - hi, 3)
        if last_close >= lo:                     # 带内 -> 远端边(0.618)，在市价下方
            return round(lo, 3), "at_level", round(last_close - lo, 3)
        return round(lo, 3), "passed", round(lo - last_close, 3)
    if last_close < lo:                          # 还没反弹到带内 -> 近端边
        return round(lo, 3), "waiting", round(lo - last_close, 3)
    if last_close <= hi:                         # 带内 -> 远端边(0.618)，在市价上方
        return round(hi, 3), "at_level", round(hi - last_close, 3)
    return round(hi, 3), "passed", round(last_close - hi, 3)


def pullback_entry(direction: str, last_close: float,
                   chanlun_results: dict | None = None,
                   atr: float | None = None,
                   frames: dict | None = None,
                   tf: str | None = None) -> PullbackEntry:
    """算 0.618 回调入场位（**这是入场点，不是止损**）。

    优先级（用户选定"缠论作第一层参考，自研检测决定入场位"）：
      1. **我们自己的摆动检测**：扫小周期，选「幅度过噪音门槛 且
         入场带离现价最近」的那个 —— 点位精度高，入场次数多。
      2. 缠论结果兜底（自研检测拿不到候选时），用 `structure_tf` 周期。

    参数
    ----
    direction       : "LONG" | "SHORT"
    last_close      : 当前价（判断是否已回踩到带内）
    chanlun_results : {周期: ChanlunResult}（第一层参考 / 兜底）
    atr             : 用于噪音门槛
    frames          : {周期: DataFrame}（自研检测需要）
    tf              : 兜底用哪个缠论周期，默认 CFG.risk.structure_tf
    """
    out = PullbackEntry()
    cl_tf = tf or getattr(CFG.risk, "structure_tf", "15m")

    # ---- 1) 我们自己的检测：自适应小周期 ----
    if frames:
        cands = own_candidates(frames, direction, atr)
        if cands and last_close and last_close > 0:
            # 按"入场带离现价最近"排序；passed 的排最后（不该挂）
            def _key(c: dict):
                _e, st, dist = _entry_from_band(c["band_near"], c["band_far"],
                                                last_close, direction)
                return (st == "passed", dist)
            cands.sort(key=_key)
            best = cands[0]
            entry, state, dist = _entry_from_band(best["band_near"],
                                                  best["band_far"],
                                                  last_close, direction)
            out.ok = True
            out.entry = entry
            out.band_near = best["band_near"]
            out.band_far = best["band_far"]
            out.state = state
            out.distance = dist
            out.tf = best["tf"]
            out.swing_k = best["k"]
            out.source = "own_swing"
            out.leg = dict(best["leg"], id="swing:%s:k%d" % (best["tf"], best["k"]),
                           source="own_swing")
            if state == "passed":
                out.notes.append(
                    "现价已越过 %.3f~%.3f 回调带，回调过深" % (
                        min(best["band_near"], best["band_far"]),
                        max(best["band_near"], best["band_far"])))
            elif state == "at_level":
                out.notes.append(
                    "现价已在 %.3f~%.3f 回调带内，挂远端边（%.3f）拿更好价" % (
                        min(best["band_near"], best["band_far"]),
                        max(best["band_near"], best["band_far"]), out.entry))
            # 分型区间（审计用）
            cl = (chanlun_results or {}).get(cl_tf)
            if cl is not None:
                out.fractal_range = fractal_range(cl, 2)
            return out

    # ---- 2) 缠论兜底（第一层参考）----
    cl = (chanlun_results or {}).get(cl_tf)
    if cl is None or getattr(cl, "status", "") != "ok":
        out.reason = f"no_pullback_data_{cl_tf}"
        return out

    leg, tag = pick_leg(cl, direction)
    if leg is None:
        out.reason = f"no_{direction}_leg"
        return out

    out.leg = dict(leg, source=tag)
    out.fractal_range = fractal_range(cl, 2)
    near, far = band_of(leg, direction)
    out.band_near = round(near, 3)
    out.band_far = round(far, 3)
    out.tf = cl_tf
    out.source = tag
    entry, state, dist = _entry_from_band(out.band_near, out.band_far,
                                          last_close, direction)
    out.entry = entry
    out.state = state
    out.distance = dist
    if state == "passed":
        out.notes.append("现价已越过 %.3f~%.3f 回调带，回调过深" % (
            min(out.band_near, out.band_far), max(out.band_near, out.band_far)))
    out.ok = True
    return out
