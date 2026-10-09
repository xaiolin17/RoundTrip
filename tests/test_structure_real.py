# -*- coding: utf-8 -*-
"""0.618 回调入场 + 压力位止损止盈 测试。

概念纠正（2026-09-22）
=====================
第一版把 0.618 当【止损】、1.618 当【止盈】—— **方向性错误**。
用户原话：

> 要考虑分型 现在是处于哪个周期的回调 那么到了0.618之后反弹几率大
> 这应该是入场点位  止盈止损得看压力位可以把skill得输出给LLM来判断

正确语义：
    0.618 回调带 -> **入场点**
    压力位/支撑位 -> **止损止盈**（LLM 判断 + 本地配套计算）

自研检测（2026-09-22 第二轮）
=============================
用户原话：

> 非严格缠论 要加上我们直接的处理  缠论结果只是第一层数据
> 然后根据最新的挂单来看 参考的周期大了啊  我需要小周期判断
> 加大入场次数

实测缠论代理引擎在 **1m 图上返回 15m 级别的段**，入场位离现价 12~32 点，
挂单几乎不成交。所以自己算摆动，并在小周期里选自适应周期。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gold_agent.common.config import CFG
from gold_agent.risk.levels import (_levels, _nearest_above, _nearest_below,
                                    _structure_levels, trade_levels)
from gold_agent.risk.structure import (RETRACE_FAR, RETRACE_NEAR, alternate_swings,
                                       band_of, find_swings, fractal_range,
                                       last_leg, own_candidates, pick_leg,
                                       pullback_entry)


class _CL:
    """最小 ChanlunResult 替身。"""
    def __init__(self, segments=(), strokes=(), fractals=(), status="ok", center=None):
        self.status = status
        self.center = center
        self.raw = {"layers": {"segments": list(segments), "strokes": list(strokes),
                               "fractals": list(fractals)}}


def _seg(a, b, direction, sid="segment:15m:11"):
    return {"id": sid, "direction": direction, "start_price": a, "end_price": b}


def _frac(price, kind="top", fid="f"):
    return {"id": fid, "kind": kind, "price": price}


def _df(highs, lows):
    return pd.DataFrame({"high": highs, "low": lows,
                         "close": [(h + l) / 2 for h, l in zip(highs, lows)]})


def _zigzag(pivots, pad=2, tail=2):
    """由枢轴点生成锯齿形 K 线：(highs, lows)。

    pivots 形如 [("L", 8.0), ("H", 20.0), ("L", 10.0), ("H", 25.0)]。
    **最后一段的方向决定 LONG/SHORT 候选**：做多必须以 H 收尾（上行段），
    做空必须以 L 收尾（下行段）。相邻枢轴间线性插值，末端补反向小实体，
    保证末枢轴仍是该窗口极值（能被摆动检测识别）。
    """
    highs, lows = [], []
    n = len(pivots)
    for i, (kind, price) in enumerate(pivots):
        if kind == "H":
            highs.append(price); lows.append(price - 0.5)
        else:
            highs.append(price + 0.5); lows.append(price)
        if i + 1 < n:
            nxt = pivots[i + 1][1]
            for j in range(1, pad + 1):
                v = price + (nxt - price) * j / (pad + 1)
                highs.append(v + 0.3); lows.append(v - 0.3)
        else:
            for j in range(1, tail + 1):
                if kind == "H":
                    highs.append(price - 0.3 * j); lows.append(price - 0.6 * j)
                else:
                    highs.append(price + 0.6 * j); lows.append(price + 0.3 * j)
    return highs, lows


def _df_zz(pivots, **kw):
    return _df(*_zigzag(pivots, **kw))


#: 做多 fixture：最后一段上行 10 -> 25（幅度 15）
_ZZ_LONG = [("L", 8.0), ("H", 20.0), ("L", 10.0), ("H", 25.0)]
#: 做空 fixture：最后一段下行 20 -> 6（幅度 14）
_ZZ_SHORT = [("H", 25.0), ("L", 10.0), ("H", 20.0), ("L", 6.0)]


#: 实测真实数据：15m 上行线段 4339.936 -> 4357.059，幅度 17.123
_UP = _seg(4339.936, 4357.059, "up")
_DOWN = _seg(4397.075, 4339.936, "down", "segment:15m:10")
_FRACS = [_frac(4348.322, "bottom"), _frac(4365.234, "top")]


# ══════════════════════════════════════════════════════════════════
# 一、我们自己的摆动检测
# ══════════════════════════════════════════════════════════════════
def test_find_swings_detects_top_and_bottom():
    """分型式摆动：左右各 k 根的最高/最低。"""
    #        0    1    2    3    4    5    6
    highs = [10, 11, 15, 12, 11, 13, 10]
    lows = [8, 9, 12, 10, 7, 11, 8]
    sw = find_swings(_df(highs, lows), k=1)
    kinds = [(k, p) for _, k, p in sw]
    assert ("H", 15.0) in kinds, "位置2是顶"
    assert ("L", 7.0) in kinds, "位置4是底"


def test_find_swings_needs_enough_bars():
    assert find_swings(_df([1, 2], [0, 1]), k=2) == []


def test_alternate_swings_merges_same_kind():
    """连续同类摆动必须合并，同类取更极端的那个。"""
    sw = [[1, "H", 10.0], [3, "H", 12.0], [5, "H", 11.0],
          [7, "L", 5.0], [9, "L", 4.0]]
    alt = alternate_swings(sw)
    assert [a[1] for a in alt] == ["H", "L"]
    assert alt[0][2] == 12.0, "两个顶合并取更高的"
    assert alt[1][2] == 4.0, "两个底合并取更低的"


def test_last_leg_direction_and_range():
    # 底 -> 顶 = up
    highs = [10, 11, 15, 12, 13]
    lows = [8, 9, 12, 7, 11]
    leg = last_leg(_df(highs, lows), k=1)
    assert leg is not None
    assert leg["range"] > 0
    assert leg["direction"] in ("up", "down")


def test_own_candidates_filters_noise():
    """段幅度不足 min_leg_atr×ATR 的必须被滤掉（1m k=1 的纯噪音）。"""
    # 幅度只有 1 点的微小波动
    highs = [10.0, 10.5, 11.0, 10.5, 10.0, 10.5, 11.0, 10.5, 10.0]
    lows = [9.5, 10.0, 10.5, 10.0, 9.5, 10.0, 10.5, 10.0, 9.5]
    frames = {"1m": _df(highs, lows)}
    # ATR=16.98 -> 门槛 4.245，而段幅度仅 1 点 -> 全部滤掉
    assert own_candidates(frames, "LONG", atr=16.98, tfs=("1m",),
                          ks=(1, 2)) == []


def test_own_candidates_keeps_big_leg():
    """最后一段上行 10->25（幅度 15）应被识别为做多候选。"""
    frames = {"5m": _df_zz(_ZZ_LONG)}
    c = own_candidates(frames, "LONG", atr=1.0, tfs=("5m",), ks=(1,))
    assert len(c) >= 1
    assert c[0]["source"] == "own_swing"
    assert c[0]["leg"]["direction"] == "up"
    assert c[0]["band_far"] < c[0]["leg"]["end"], "做多入场带在段高点下方"


def test_own_candidates_skips_missing_tf():
    assert own_candidates({"1m": None}, "LONG", atr=10.0, tfs=("1m",), ks=(1,)) == []


def test_own_candidates_rejects_wrong_direction():
    """上行段不构成做空候选（方向必须匹配）。"""
    frames = {"5m": _df_zz(_ZZ_LONG)}
    assert own_candidates(frames, "SHORT", atr=1.0, tfs=("5m",), ks=(1,)) == []


# ══════════════════════════════════════════════════════════════════
# 二、0.618 = 入场点（不是止损）
# ══════════════════════════════════════════════════════════════════
def test_band_of_long():
    """做多：从段高点回撤 50% / 61.8%。"""
    leg = {"start": 4339.936, "end": 4357.059, "range": 17.123, "direction": "up"}
    near, far = band_of(leg, "LONG")
    assert far == pytest.approx(4357.059 - RETRACE_FAR * 17.123, abs=0.01)   # 4346.477
    assert near == pytest.approx(4357.059 - RETRACE_NEAR * 17.123, abs=0.01)  # 4348.498
    assert near > far, "near 是靠趋势方向的浅回调边"


def test_band_of_short():
    """做空：从段低点反弹 50% / 61.8%。"""
    leg = {"start": 4397.075, "end": 4339.936, "range": 57.139, "direction": "down"}
    near, far = band_of(leg, "SHORT")
    assert far == pytest.approx(4339.936 + RETRACE_FAR * 57.139, abs=0.01)   # 4375.248
    assert near < far


def test_0618_is_entry_not_stop():
    """做多入场位 = 上行段高点回撤 61.8%（实测 4346.477）。"""
    cl = {"15m": _CL(segments=[_UP], fractals=_FRACS)}
    pe = pullback_entry("LONG", 4360.0, cl)
    assert pe.ok
    expected = 4357.059 - RETRACE_FAR * (4357.059 - 4339.936)
    assert pe.band_far == pytest.approx(expected, abs=0.01)
    assert pe.entry < _UP["end_price"], "入场位低于段高点 = 等回踩买入"


def test_entry_is_on_correct_side_of_market():
    """挂单价必须在市价正确一侧，否则 MT5 拒单（Invalid price）。"""
    cl = {"15m": _CL(segments=[_UP], fractals=_FRACS)}
    # 现价远高于带 -> waiting，挂单价应在现价下方
    pe = pullback_entry("LONG", 4400.0, cl)
    assert pe.entry < 4400.0
    # 做空同理
    cl2 = {"15m": _CL(segments=[_DOWN], fractals=_FRACS)}
    pe2 = pullback_entry("SHORT", 4300.0, cl2)
    assert pe2.entry > 4300.0


def test_at_level_entry_is_below_market_for_long():
    """⚠️ 回归：现价在带内时，挂单价**不能**等于现价（否则限价单必被拒）。

    旧实现返回 last_close 当挂单价 —— 那等于把限价单挂在市价上。
    """
    cl = {"15m": _CL(segments=[_UP], fractals=_FRACS)}
    lo = 4357.059 - RETRACE_FAR * 17.123      # 4346.477
    hi = 4357.059 - RETRACE_NEAR * 17.123     # 4348.498
    mid = (lo + hi) / 2
    pe = pullback_entry("LONG", mid, cl)
    assert pe.state == "at_level"
    assert pe.entry < mid, "做多挂单价必须在现价下方"
    assert pe.entry == pytest.approx(lo, abs=0.01), "带内取远端边(0.618)拿更好价"


def test_at_level_entry_is_above_market_for_short():
    cl = {"15m": _CL(segments=[_DOWN], fractals=_FRACS)}
    lo = 4339.936 + RETRACE_NEAR * 57.139     # near
    hi = 4339.936 + RETRACE_FAR * 57.139      # far (0.618)
    mid = (lo + hi) / 2
    pe = pullback_entry("SHORT", mid, cl)
    assert pe.state == "at_level"
    assert pe.entry > mid, "做空挂单价必须在现价上方"
    assert pe.entry == pytest.approx(hi, abs=0.01)


def test_pullback_states():
    """三种状态：等回踩 / 已到位 / 已越过。"""
    cl = {"15m": _CL(segments=[_UP], fractals=_FRACS)}
    hi = 4357.059 - RETRACE_NEAR * 17.123
    lo = 4357.059 - RETRACE_FAR * 17.123
    assert pullback_entry("LONG", hi + 10.0, cl).state == "waiting"
    assert pullback_entry("LONG", (lo + hi) / 2, cl).state == "at_level"
    assert pullback_entry("LONG", lo - 5.0, cl).state == "passed"


def test_passed_marks_structure_broken():
    """已越过整条回调带 -> 回调过深，须带说明（决策层据此不挂单）。"""
    cl = {"15m": _CL(segments=[_UP], fractals=_FRACS)}
    lo = 4357.059 - RETRACE_FAR * 17.123
    pe = pullback_entry("LONG", lo - 5.0, cl)
    assert pe.state == "passed"
    assert any("回调过深" in n for n in pe.notes)


def test_short_passed_is_rebound_too_deep():
    cl = {"15m": _CL(segments=[_DOWN], fractals=_FRACS)}
    hi = 4339.936 + RETRACE_FAR * 57.139
    pe = pullback_entry("SHORT", hi + 5.0, cl)
    assert pe.state == "passed"
    assert any("反弹过深" in n or "回调过深" in n for n in pe.notes)


def test_prefers_segment_over_stroke():
    """缠论兜底路径：线段优先于笔。"""
    cl = {"15m": _CL(segments=[_UP],
                     strokes=[_seg(4339.167, 4376.057, "up", "stroke:15m:37")])}
    leg, tag = pick_leg(cl["15m"], "LONG")
    assert tag == "chanlun_segment"
    assert leg["id"] == "segment:15m:11"


def test_own_swing_preferred_over_chanlun():
    """用户选定：缠论作第一层参考，**自研检测决定入场位**。"""
    frames = {"1m": _df_zz(_ZZ_LONG)}
    cl = {"15m": _CL(segments=[_UP], fractals=_FRACS)}
    pe = pullback_entry("LONG", 30.0, cl, atr=1.0, frames=frames)
    assert pe.ok
    assert pe.source == "own_swing", "应优先用自研检测"
    assert pe.tf == "1m"
    assert pe.swing_k in (1, 2, 3)
    # 自研检测给的带应来自我们自己的段（10->25），而不是缠论那条
    assert pe.band_far < 25.0


def test_falls_back_to_chanlun_when_no_frames():
    """没有小周期数据时退回缠论（第一层参考）。"""
    cl = {"15m": _CL(segments=[_UP], fractals=_FRACS)}
    pe = pullback_entry("LONG", 4360.0, cl)
    assert pe.ok and pe.source == "chanlun_segment"
    assert pe.tf == "15m"


def test_pullback_no_data_fails_cleanly():
    pe = pullback_entry("LONG", 4350.0, {})
    assert not pe.ok and pe.entry is None
    assert "no_pullback_data" in pe.reason


def test_fractal_range():
    cl = _CL(fractals=[_frac(4300.0), _frac(4348.322), _frac(4365.234)])
    assert fractal_range(cl, 2) == pytest.approx(4365.234 - 4348.322, abs=1e-6)


def test_adaptive_tf_picks_nearest():
    """自适应：在多个候选里选入场带离现价最近的那个。"""
    # 1m: 段高点 25（离现价近）；5m: 段高点 130（远）
    near = _df_zz(_ZZ_LONG)                       # 段 10->25
    far = _df_zz([("L", 90.0), ("H", 120.0), ("L", 100.0), ("H", 130.0)])
    frames = {"1m": near, "5m": far}
    pe = pullback_entry("LONG", 27.0, None, atr=1.0, frames=frames)
    assert pe.ok, pe.reason
    assert pe.tf == "1m", "应选离现价最近的周期（1m 段高点 25 比 5m 的 130 近）"
    assert pe.band_far < 25.0


def test_adaptive_prefers_valid_side():
    """挂单价必须落在市价正确一侧（做多在市价下方）。"""
    frames = {"1m": _df_zz(_ZZ_LONG)}
    pe = pullback_entry("LONG", 30.0, None, atr=1.0, frames=frames)
    assert pe.ok and pe.state == "waiting"
    assert pe.entry < 30.0


# ══════════════════════════════════════════════════════════════════
# 三、压力位/支撑位 -> 止损止盈
# ══════════════════════════════════════════════════════════════════
_REV = {"verdict": "bullish", "confidence": 0.7,
        "support_levels": [4342.626, 4322.599],
        "resistance_levels": [4376.057, 4399.687],
        "sl_hint": 4340.0, "tp_hint": 4399.0}


def test_long_stop_below_support_target_at_resistance():
    """做多：止盈取上方压力位并缩到 70%，**止损由止盈反推**（用户 2026-10-09）。

    用户原话：
    > 我们每个品种首仓止盈点数为计算的70% 比如100买入 计算止盈110
    > 那么实际止盈107 止损按照盈亏比1.8计算

    所以止损**不再**基于下方支撑位，而是 `止盈距离 / min_rr`。
    """
    lv = trade_levels("LONG", 4350.0, _REV, None, atr=18.0)
    assert lv.ok, lv.reason
    assert lv.sl < 4350.0 < lv.tp
    # 止盈 = 上方最近压力 4376.057，距离 26.057 缩到 70%
    raw = 4376.057 - 4350.0
    assert lv.tp == pytest.approx(4350.0 + raw * CFG.risk.first_tp_shrink, abs=0.01)
    assert lv.used_tp_level == 4376.057, "止盈应基于上方最近压力位"
    # 止损由缩后的止盈距离按 min_rr 反推
    assert lv.sl_source == "rr_from_tp", lv.sl_source
    assert lv.sl == pytest.approx(
        4350.0 - raw * CFG.risk.first_tp_shrink / CFG.risk.min_rr, abs=0.01)


def test_short_stop_above_resistance_target_at_support():
    """做空：止盈取下方支撑并缩到 70%，止损由止盈反推（用户 2026-10-09）。"""
    rev = {"support_levels": [4300.0], "resistance_levels": [4360.0]}
    lv = trade_levels("SHORT", 4350.0, rev, None, atr=18.0)
    assert lv.ok, lv.reason
    assert lv.tp < 4350.0 < lv.sl
    assert lv.used_tp_level == 4300.0, "止盈应基于下方支撑"
    raw = 4350.0 - 4300.0
    assert lv.tp == pytest.approx(4350.0 - raw * CFG.risk.first_tp_shrink, abs=0.01)
    assert lv.sl_source == "rr_from_tp", lv.sl_source
    assert lv.sl == pytest.approx(
        4350.0 + raw * CFG.risk.first_tp_shrink / CFG.risk.min_rr, abs=0.01)


def test_first_entry_rr_is_exactly_min_rr():
    """首仓实际盈亏比**恒等于** min_rr（用户要求「盈亏比 1.8」）。

    ⚠️ 这是新定价语义的直接推论：止损由止盈反推
    （`sl_dist = tp_dist / min_rr`）。注意方向：
    **先缩止盈、再反推止损**。若顺序反了（先反推再缩），
    实际盈亏比会变成 `first_tp_shrink/min_rr` = 0.7/1.8 ≈ 0.39。
    """
    cases = [
        ("LONG", {"support_levels": [90.0], "resistance_levels": [110.0]}, 100.0),
        ("SHORT", {"support_levels": [90.0], "resistance_levels": [110.0]}, 100.0),
    ]
    for direction, rev, entry in cases:
        lv = trade_levels(direction, entry, rev, None, atr=2.0)
        assert lv.ok, f"{direction} {lv.reason}"
        rr = lv.tp_dist / lv.sl_dist
        assert rr == pytest.approx(CFG.risk.min_rr, abs=0.02), \
            f"{direction} 首仓盈亏比必须等于 min_rr，得到 {rr:.4f}"


def test_user_example_100_entry_110_computed_tp_gives_107():
    """用户原话里的具体例子必须逐字成立。

    > 比如100买入 计算止盈110 那么实际止盈107 止损按照盈亏比1.8计算
    """
    lv = trade_levels("LONG", 100.0,
                      {"resistance_levels": [110.0], "support_levels": [90.0]},
                      None, atr=2.0, digits=3)
    assert lv.ok, lv.reason
    assert lv.tp == pytest.approx(107.0, abs=1e-6), \
        f"100 买入、计算止盈 110 -> 实际止盈应为 107，得到 {lv.tp}"
    assert lv.tp_dist == pytest.approx(7.0, abs=1e-6)
    # 止损 = 100 - 7/1.8 = 96.1111...
    # ⚠️ 钉住 1.8 的**绝对值**：只写 `CFG.risk.min_rr` 是相对断言，
    #    把配置改回 1.2 时两边同时变、测试仍通过（证伪实测过）。
    assert CFG.risk.min_rr == pytest.approx(1.8), "用户指定盈亏比 1.8"
    assert lv.sl == pytest.approx(100.0 - 7.0 / 1.8, abs=1e-3)
    assert lv.sl == pytest.approx(96.111, abs=0.002)
    assert lv.sl_dist == pytest.approx(7.0 / 1.8, abs=1e-3)


def test_no_llm_levels_falls_back_to_local_structure():
    """LLM 没给点位时，**本地结构位兜底**（用户澄清后的正确语义）。

    用户原话：
    > 我的意思是LLM没有相反的预测方向 并且当前距离我们盈利的压力位
    > 也有距离就可以直接市价开仓

    即：**点位的来源不必是 LLM**。LLM 管"方向否决"（decision 层的
    `opposed`），"离盈利压力位有距离"是赔率检查（min_rr）。
    所以只要任一来源能给点位，就不该拦。

    原实现把这个 early-return 放在并入本地结构位**之前**，导致本模块
    注释里写的"LLM 漏给时兜底"是**死代码** —— 线上被 llm_no_levels
    拦掉 7 单。
    """
    cl = {"15m": _CL(center={"zg": 4376.0, "zd": 4342.0,
                             "gg": 4400.0, "dd": 4300.0})}
    ev = type("E", (), {"chanlun": cl, "mobius": None})()
    lv = trade_levels("LONG", 4350.0, {}, ev, atr=18.0)
    assert lv.ok, f"本地有结构位就该能开仓，得到 {lv.reason}"
    assert lv.used_tp_level == 4376.0, "止盈应取本地压力位"
    # 来源必须如实标注为本地结构位，不能冒充 LLM
    assert lv.tp_source == "struct_resistance", lv.tp_source
    # ⚠️ 止损不再取本地支撑位，而是由止盈反推（用户 2026-10-09 统一语义）
    assert lv.sl_source == "rr_from_tp", lv.sl_source
    assert lv.sl == pytest.approx(
        4350.0 - (4376.0 - 4350.0) * CFG.risk.first_tp_shrink / CFG.risk.min_rr,
        abs=0.01)


def test_no_levels_at_all_is_rejected():
    """LLM 没给点位 **且** 本地也没有结构位 -> 才拒绝。"""
    lv = trade_levels("LONG", 4350.0, {}, None, atr=18.0)
    assert not lv.ok
    assert lv.reason == "llm_no_levels"
    assert lv.sl is None and lv.tp is None


def test_none_llm_review_is_rejected_without_structure():
    lv = trade_levels("LONG", 4350.0, None, None, atr=18.0)
    assert not lv.ok and lv.reason == "llm_no_levels"


def test_missing_resistance_rejected():
    """只有支撑位、没有压力位 -> 做多**无法定止盈** -> 拒绝。

    ⚠️ 新语义下（用户 2026-10-09）止损由止盈反推，所以缺的是**止盈来源**
    （做多看压力位），不再是"缺支撑位"。拒绝码随之统一为
    `no_resistance_above`。
    """
    lv = trade_levels("LONG", 4350.0, {"support_levels": [4300.0]}, None, atr=18.0)
    assert not lv.ok
    assert lv.reason == "no_resistance_above"


def test_missing_support_rejected_for_short():
    """只有压力位、没有支撑位 -> 做空**无法定止盈** -> 拒绝。"""
    lv = trade_levels("SHORT", 4350.0, {"resistance_levels": [4400.0]}, None, atr=18.0)
    assert not lv.ok
    assert lv.reason == "no_support_below"


def test_rr_filter_never_fires_on_first_entry():
    """首仓**永远不会**因盈亏比不足被拒 —— 止损是反推出来的，盈亏比恒等于 min_rr。

    这是新语义的必然推论（也是与旧实现最大的行为差异：旧实现会因
    "止盈不够远"而拒单，新实现改为"止盈缩到 70%"再由它反推止损）。
    真正会拒绝的情况只有**根本没有止盈来源**。
    """
    rev = {"support_levels": [4300.0], "resistance_levels": [4370.0]}
    lv = trade_levels("LONG", 4350.0, rev, None, atr=18.0)
    assert lv.ok, f"有压力位就该能定价，得到 {lv.reason}"
    assert lv.tp_dist == pytest.approx(20.0 * CFG.risk.first_tp_shrink, abs=0.01)
    assert lv.tp_dist / lv.sl_dist == pytest.approx(CFG.risk.min_rr, abs=0.02)


def test_no_target_above_distinguished_from_missing_source():
    """「上方根本没有压力位」必须给出可区分的拒绝码（便于排查）。"""
    lv1 = trade_levels("LONG", 4350.0, {"support_levels": [4300.0]}, None, atr=18.0)
    assert lv1.reason == "no_resistance_above"
    # 提示价在对侧（低于入场）也救不了做多 —— 不能当止盈来源
    lv2 = trade_levels("LONG", 4350.0,
                       {"support_levels": [4300.0], "tp_hint": 4340.0},
                       None, atr=18.0)
    assert lv2.reason == "no_resistance_above", lv2.reason


def test_atr_floor_applies_to_tp_then_derives_sl():
    """结构止盈缩后贴脸时，先按 ATR 下限外扩**止盈**，再由它反推止损。

    ⚠️ 新语义下 ATR 下限作用在**止盈距离**上（用户 2026-10-09），
    不再是"外扩止损"。因为止损是止盈的函数，只有止盈有下限才有意义。
    """
    rev = {"support_levels": [4349.5], "resistance_levels": [4351.0]}
    lv = trade_levels("LONG", 4350.0, rev, None, atr=18.0)
    assert lv.ok, lv.reason
    floor = CFG.risk.structure_sl_min_atr * 18.0
    # 结构距离 1.0 缩到 0.7 -> 低于下限 9.0 -> 外扩到 9.0
    assert lv.tp_dist == pytest.approx(floor, abs=0.01), lv.tp_dist
    # 止损 = 9.0 / 1.8 = 5.0（恰为下限/min_rr）
    assert lv.sl_dist == pytest.approx(floor / CFG.risk.min_rr, abs=0.01)
    assert lv.sl_source == "rr_from_tp"


def test_hint_tp_used_as_target_when_no_arrays():
    """LLM 只给了 tp_hint（没给数组）-> 用它当止盈来源，止损仍反推。"""
    rev = {"sl_hint": 4335.0, "tp_hint": 4390.0}
    lv = trade_levels("LONG", 4350.0, rev, None, atr=18.0)
    assert lv.ok, lv.reason
    raw = 4390.0 - 4350.0
    assert lv.tp_source == "llm_hint", lv.tp_source
    assert lv.tp == pytest.approx(4350.0 + raw * CFG.risk.first_tp_shrink, abs=0.01)
    # 止损来自反推，不是 sl_hint（新语义）
    assert lv.sl_source == "rr_from_tp", lv.sl_source
    assert lv.sl == pytest.approx(
        4350.0 - raw * CFG.risk.first_tp_shrink / CFG.risk.min_rr, abs=0.01)


@pytest.mark.parametrize("direction,rev", [
    ("LONG", {"support_levels": [4340.0], "resistance_levels": [4400.0]}),
    ("SHORT", {"support_levels": [4300.0], "resistance_levels": [4360.0]}),
])
def test_levels_always_correct_side(direction, rev):
    """任何情况下止损止盈都必须在入场价正确一侧。"""
    lv = trade_levels(direction, 4350.0, rev, None, atr=18.0)
    assert lv.ok, lv.reason
    if direction == "LONG":
        assert lv.sl < 4350.0 < lv.tp
    else:
        assert lv.tp < 4350.0 < lv.sl


def test_bad_entry_rejected():
    lv = trade_levels("LONG", 0.0, _REV, None, atr=18.0)
    assert not lv.ok and lv.reason == "bad_entry"


def test_levels_helper_filters_garbage():
    """LLM 可能返回字符串/0/负数 -> 必须洗干净。"""
    assert _levels([1.5, "2.5", 0, -3, None, "abc"]) == [1.5, 2.5]


def test_nearest_helpers():
    lv = [10.0, 20.0, 30.0]
    assert _nearest_below(lv, 25.0) == 20.0
    assert _nearest_above(lv, 25.0) == 30.0
    assert _nearest_below(lv, 5.0) is None
    assert _nearest_above(lv, 35.0) is None


def test_structure_levels_pulls_chanlun_center():
    """本地结构位：缠论中枢 zg/gg 作压力、zd/dd 作支撑。"""
    cl = {"15m": _CL(center={"zg": 4376.0, "zd": 4342.0,
                             "gg": 4400.0, "dd": 4300.0})}
    ev = type("E", (), {"chanlun": cl, "mobius": None})()
    sup, res = _structure_levels(ev)
    assert 4342.0 in sup and 4300.0 in sup
    assert 4376.0 in res and 4400.0 in res


def test_structure_levels_survives_bad_mobius():
    """SMC 数据异常不能影响本地结构位提取。"""
    ev = type("E", (), {"chanlun": {}, "mobius": {"15m": object()}})()
    sup, res = _structure_levels(ev)
    assert sup == [] and res == []


def test_tagged_levels_preserve_provenance():
    """来源可审计：聚合后必须能分辨某个位是缠论中枢还是 SMC 给的。

    背景：实测 127 笔真实单子里 `struct_*` 出现 35 次、`chanlun_*` 出现
    **0 次**。根因不是 `_pick_src` 匹配失败（它拿到的正是聚合后的列表，
    能匹配上），而是 `_structure_levels` 返回**裸浮点**，
    `_cluster` 合并后来源信息就没了 —— 无法回答"这一单的止损是谁给的"。
    `_structure_levels_tagged` 保留标签，且**数值与旧实现完全一致**
    （订单参数路径不受影响）。
    """
    from gold_agent.risk.levels import (_structure_levels,
                                        _structure_levels_tagged)
    cl = {"5m": _CL(center={"zg": 4140.02, "zd": 4120.0,
                            "gg": 4145.0, "dd": 4115.0})}
    mob = {
        "5m": type("M", (), {
            "status": "ok",
            "active_order_blocks": lambda s, k: [
                {"bottom": 4110.0, "top": 4112.0, "bias": "bull"}],
            "active_fvgs": lambda s: [],
            "equal_highs": [{"level": 4160.0}],
            "equal_lows": [{"level": 4105.0}],
        })(),
    }
    ev = type("E", (), {"chanlun": cl, "mobius": mob})()
    sup, res = _structure_levels(ev, atr=10.0)
    t_sup, t_res = _structure_levels_tagged(ev, atr=10.0)

    # 1) 数值必须完全一致（不能改变下单用的点位）
    assert sorted(v for v, _ in t_sup) == sorted(sup), (t_sup, sup)
    assert sorted(v for v, _ in t_res) == sorted(res), (t_res, res)
    # 2) 缠论与 SMC 都必须被标出来
    tags = {t for _, t in list(t_sup) + list(t_res)}
    assert any("chanlun" in t for t in tags), f"缺缠论标签: {tags}"
    assert any("smc" in t for t in tags), f"缺 SMC 标签: {tags}"
    # 3) 缠论中枢 zd/dd 必须落在支撑侧、zg/gg 落在压力侧
    ch_sup = [v for v, t in t_sup if "chanlun" in t]
    ch_res = [v for v, t in t_res if "chanlun" in t]
    assert 4120.0 in ch_sup and 4115.0 in ch_sup, ch_sup
    assert 4140.02 in ch_res or 4145.0 in ch_res, ch_res


def test_tagged_levels_mark_merged_clusters():
    """缠论位与 SMC 位靠近被合并时，标签取并集（仍能看出两者都给了）。"""
    from gold_agent.risk.levels import _cluster_tagged
    # 4140.02(缠论) 与 4141.5(SMC) 相差 1.48 < gap 2.5 -> 合并
    out = _cluster_tagged([(4140.02, "chanlun"), (4141.5, "smc")], gap=2.5)
    assert len(out) == 1, out
    val, tag = out[0]
    assert "chanlun" in tag and "smc" in tag, tag
    assert abs(val - 4140.76) < 0.01, val


def test_tagged_levels_notes_are_gbk_safe():
    """来源审计写入 level_notes 时必须 GBK 可编码且不含 '?'。"""
    from gold_agent.risk.levels import trade_levels
    cl = {"5m": _CL(center={"zg": 4310.0, "zd": 4280.0,
                            "gg": 4320.0, "dd": 4270.0})}
    ev = type("E", (), {"chanlun": cl, "mobius": None})()
    lv = trade_levels("LONG", 4300.0, {"support_levels": [4290.0]}, ev, atr=10.0)
    note = [n for n in lv.notes if "结构位来源" in n]
    assert note, lv.notes
    note[0].encode("gbk")          # 必须可编码
    assert "?" not in note[0]
    assert "缠论中枢" in note[0]


def test_config_flags():
    """关键配置必须生效。"""
    # 用户澄清：点位的来源不必是 LLM。LLM 管方向否决，
    # 本地结构位（缠论中枢/SMC）负责兜底给点位。
    assert CFG.risk.min_rr >= 1.0, "必须有赔率下限（'离盈利压力位有距离'）"
    # 自研检测：小周期 + 噪音门槛 + 回调带
    assert "1m" in CFG.risk.pullback_tfs and "2m" in CFG.risk.pullback_tfs
    assert CFG.risk.pullback_min_leg_atr > 0
    assert CFG.risk.pullback_band_near < CFG.risk.pullback_band_far
