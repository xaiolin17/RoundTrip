"""风控模块测试：真实历史数据驱动仓位/收缩/熔断。"""
from __future__ import annotations

import time

import pandas as pd
import pytest

from gold_agent.common.config import CFG
from gold_agent.fusion.engine import FusionResult
from gold_agent.mt5.client import AccountInfo
from gold_agent.risk.gate import Proposal, RiskGate
from gold_agent.risk.grid import GridState
from gold_agent.risk.position import (CircuitBreakers, conservative_win_rate,
                                      position_lots, volatility_k, wilson_lower)
from gold_agent.risk.shrink import reachable_tp, shrink_for_pending, shrink_sl, shrink_tp
from gold_agent.risk.structure import RETRACE_FAR, RETRACE_NEAR


def test_position_lots_bounds():
    equity, atr, pv = 10000.0, 5.0, 1.0
    lots, rej = position_lots(equity, atr, pv, win_rate=0.5, vol_k=1.0,
                              volume_min=0.01, volume_step=0.01)
    if rej is None:
        assert lots >= 0.01
        # 风险不超 0.5% + Kelly cap
        risk = CFG.risk.sl_atr_mult * atr / 0.001 * pv * lots
        assert risk <= equity * 0.055   # 0.5% 与 Kelly cap 较小者再放宽边界
    else:
        assert rej == "risk_budget_below_min_lot"


def test_min_lot_fallback_when_vol_k_shrinks_budget():
    """回归（用户实测事故）：缩仓系数把预算压到最小手数以下时，**仍按 0.01 手开仓**。

    实测：vol_k=0.125（波动下限 0.25 × 分歧 0.5）→ 预算 8.64 USD
    → 止损上限仅 8.6 点，而实际止损 7.5~20.8 点 → 强信号轮次被连续拦截
    （3514/3515），用户反馈"现在没有开仓"。

    但 0.01 手 + 20 点止损 = 20.82 USD = 权益 0.145%，
    **远低于** risk_pct 允许的 0.500%（69.10 USD）——
    系统在拒绝一个风险只有自设上限 29% 的仓位。
    0.01 手是交易所下限，不能再往下取整，所以缩仓系数不该变成"禁止交易"。
    """
    equity, pv = 13820.89, 0.1
    nominal = equity * CFG.risk.risk_pct          # 69.10 USD
    # 被拦的轮次：止损 16.49 / 19.87 / 20.82 点
    for sl_dist in (16.49, 19.87, 20.82):
        lots, rej = position_lots(equity, 17.0, pv, 0.5,
                                  vol_k=0.125, sl_dist=sl_dist)
        assert rej is None, f"止损 {sl_dist} 点不该被拦（得到 {rej}）"
        assert lots == pytest.approx(0.01), "应按最小手数开仓"
        # 实际风险必须仍在**名义**预算内
        risk = sl_dist * 0.01 * pv / 0.001
        assert risk <= nominal, f"实际风险 {risk:.2f} 超出名义预算 {nominal:.2f}"


def test_min_lot_fallback_still_respects_nominal_budget():
    """兜底不得突破硬风控：0.01 手风险超出**名义**预算时仍须拦截。"""
    equity, pv = 13820.89, 0.1
    nominal = equity * CFG.risk.risk_pct
    over = nominal / (0.01 * pv / 0.001) + 1.0    # 刚好超出名义预算的止损宽度
    lots, rej = position_lots(equity, 17.0, pv, 0.5, vol_k=1.0, sl_dist=over)
    assert rej == "risk_budget_below_min_lot", (
        f"止损 {over:.1f} 点已超名义预算，必须拦截（得到 {lots} 手）")
    # 刚好在预算内 -> 放行
    under = nominal / (0.01 * pv / 0.001) - 1.0
    lots2, rej2 = position_lots(equity, 17.0, pv, 0.5, vol_k=1.0, sl_dist=under)
    assert rej2 is None and lots2 == pytest.approx(0.01)


def test_position_lots_consistent_across_paths():
    """回归：open_market 与 place_grid 必须用**同一个** vol_k。

    原实现 place_grid 漏传 vol_k（默认 1.0），于是同一个 20 点止损，
    place_grid 开 0.03 手而 open_market 直接被拦 —— 两边风险尺度不一致。
    """
    equity, pv = 13820.89, 0.1
    for sl_dist in (9.28, 16.49, 20.82, 54.5):
        a = position_lots(equity, 17.0, pv, 0.5, vol_k=0.125, sl_dist=sl_dist)
        b = position_lots(equity, 17.0, pv, 0.5, vol_k=0.125, sl_dist=sl_dist)
        assert a == b, f"同一 vol_k 下两条路径结果必须一致：{a} vs {b}"


def test_volatility_k_bounds():
    assert 0.25 <= volatility_k(0.02, None) <= 1.5
    assert volatility_k(None, None) == 1.0
    assert volatility_k(0.005, 0.03) < 1.5   # 高波动日 ×0.6


def test_circuit_breakers_paths():
    b = CircuitBreakers()
    # 全零基线
    assert b.check(10000, 0.0, False) is None
    # 连亏（先达 cooloff 或 consecutive_losses 均为合法熔断）
    for _ in range(4):
        b.on_trade_closed(-50, 10000)
    r = b.check(10000, 0.0, False)
    assert r and ("consecutive_losses" in r or "cooloff" in r)
    # 日亏熔断
    b2 = CircuitBreakers()
    b2.on_trade_closed(-350, 10000)   # > 3% of 10000
    r = b2.check(10000, 0.0, False)
    assert r == "daily_loss_stop"
    # 高危新闻窗口
    b3 = CircuitBreakers()
    r = b3.check(10000, 0.0, True)
    assert r == "news_high_risk_window"
    # 保证金
    b4 = CircuitBreakers()
    r = b4.check(10000, 6500.0, False)
    assert r == "margin_cap"


def test_shrink_for_pending_real_df():
    df = pd.read_parquet(r"D:\DDDDDDDDD\XAUUSD_1min_kline.parquet")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").set_index("time")
    atr = 5.0
    for direction in ("LONG", "SHORT"):
        sh = shrink_for_pending(direction, 4350.0, atr, df)
        # 收缩语义（用户指定）：TP 缩 40% → 距离 ≤ 0.6×mult×ATR；SL 缩 20% → 距离 ≤ 0.8×mult×ATR
        tp_dist = abs(sh["tp"] - 4350.0)
        assert tp_dist <= CFG.risk.tp_atr_mult * 0.6 * atr + 1e-6, sh
        assert tp_dist > 0                       # 保证有正利润空间
        assert abs(sh["sl"] - 4350.0) <= CFG.risk.sl_atr_mult * 0.8 * atr + 1e-6
    # 不可达 TP 收缩：远超历史极值的 TP 必须被拉近
    far_tp = 4350.0 + 100.0
    got = reachable_tp(far_tp, "LONG", df)
    assert got < far_tp


def test_risk_gate_reject_paths():
    gate = RiskGate(CircuitBreakers(), GridState())
    ev = type("E", (), {"result": FusionResult(score=2.0, sigma=0.3)})()
    acc = AccountInfo(login=1, balance=10000, equity=10000, margin_free=10000,
                      margin=0, margin_level=0, leverage=2000, currency="USD")
    # 熔断拒绝
    b = CircuitBreakers()
    b.on_trade_closed(-350, 10000)
    gate2 = RiskGate(b, GridState())
    res = gate2.evaluate(Proposal(kind="open_market", direction="LONG"),
                         ev, acc, type("V", (), {"positions": []})(), 1.0, None, 5.0, None)
    assert not res.ok and "circuit" in res.reason


# ══════════════════════════════════════════════════════════════════
# 单张限价挂单（用户要求：取消网格）
# ══════════════════════════════════════════════════════════════════
def _llm_rev(support, resistance):
    """构造一个最小可用的 LLM review（压力位/支撑位）。"""
    return {"verdict": "bullish", "confidence": 0.7,
            "support_levels": list(support), "resistance_levels": list(resistance),
            "level_reason": "测试用"}


def test_place_grid_now_emits_single_pending_order():
    """取消网格：`place_grid` 只产出**一张**挂单，入场价 = 0.618 回调带。

    实测问题：原实现按 `CFG.risk.grid_layers`（=2）挂多层，是网格行为。
    用户要求只挂预测的那一单；入场价改为回调带（回调到位反弹概率大）。
    """
    gate = RiskGate(CircuitBreakers(), GridState())
    ev = type("E", (), {"result": FusionResult(score=2.0, sigma=0.3)})()
    acc = AccountInfo(login=1, balance=10000, equity=10000, margin_free=10000,
                      margin=0, margin_level=0, leverage=2000, currency="USD")
    views = type("V", (), {"positions": [], "pending_orders": []})()
    atr, close = 12.339, 4350.0
    df5 = pd.DataFrame({"high": [close] * 10, "low": [close] * 10,
                        "close": [close] * 10})
    # 缠论兜底路径（不传 frames → 走缠论）
    up = {"id": "segment:15m:1", "direction": "up",
          "start_price": close - 30.0, "end_price": close - 5.0}
    ev.chanlun = {"15m": type("C", (), {
        "status": "ok", "center": None,
        "raw": {"layers": {"segments": [up], "strokes": [], "fractals": []}}})()}
    rev = _llm_rev([close - 25.0], [close + 40.0])
    res = gate.evaluate(Proposal(kind="place_grid", direction="LONG", entry=close),
                        ev, acc, views, 0.1, df5, atr, None, llm_review=rev)
    assert res.ok, f"应放行: {res.reason}"
    layers = res.plan["grid_plan"]
    assert len(layers) == 1, f"应只有一张挂单，实际 {len(layers)} 张（网格未取消）"
    # 入场价落在回调带内（0.5~0.618），且在市价下方（做多限价单必须如此）
    lo = up["end_price"] - RETRACE_FAR * (up["end_price"] - up["start_price"])
    hi = up["end_price"] - RETRACE_NEAR * (up["end_price"] - up["start_price"])
    assert min(lo, hi) <= layers[0]["level"] <= max(lo, hi), "入场价应在回调带内"
    assert layers[0]["level"] < close, "做多限价单必须在市价下方"
    assert res.plan["entry_source"] == "chanlun_segment"
    assert res.plan["pullback_tf"] == "15m"
    # 必须带止损止盈，否则控制台看不到点位
    assert layers[0]["sl"] and layers[0]["tp"]


def test_max_lot_allows_configured_adds():
    """配置一致性：`max_lot` 必须容得下「基础仓 + max_adds_per_position 次加仓」。

    实测事故：`.env` 的 `MAX_LOT=0.01`，而 `max_adds_per_position=5`。
    基础仓 0.01 手 + 加仓 0.01 手 = 0.02 > 0.01 → **加仓永远被拦**，
    "最多加仓 5 次"这条规则是死代码（实盘 21 次 risk_reject 全是 max_lot cap）。
    """
    need = 0.01 * (1 + CFG.risk.max_adds_per_position)
    assert CFG.max_lot >= need - 1e-9, (
        f"max_lot={CFG.max_lot} 容不下基础仓 0.01 + "
        f"{CFG.risk.max_adds_per_position} 次加仓（需要 {need:.2f}）——"
        "加仓会被 max_lot 永久拦截")


def test_add_layer_passes_risk_gate_with_configured_max_lot():
    """方案 A 验收：持 1 笔 0.01 手时，第 1 次加仓应能通过风控。

    注意 `add_layer` 的 `prop.entry` 装的是**持仓 ticket**（不是价格），
    gate 靠它找到持仓、再用 `price_open` 作定价锚点。
    """
    gate = RiskGate(CircuitBreakers(), GridState())
    ev = type("E", (), {"result": FusionResult(score=2.0, sigma=0.3)})()
    acc = AccountInfo(login=1, balance=10000, equity=10000, margin_free=10000,
                      margin=0, margin_level=0, leverage=2000, currency="USD")
    pos = type("P", (), {"ticket": 123456, "volume": 0.01, "price_open": 4350.0,
                         "magic": CFG.mt5.magic})()
    views = type("V", (), {"positions": [pos], "pending_orders": []})()
    # 加仓也要有 LLM 压力位才能算止损止盈（用户要求）
    res = gate.evaluate(Proposal(kind="add_layer", direction="LONG", entry=123456),
                        ev, acc, views, 0.1, None, 5.0, None,
                        llm_review=_llm_rev([4340.0], [4420.0]))
    assert res.ok, f"第 1 次加仓不应被拦: {res.reason}"
    assert res.plan["sl"] < 4350.0 < res.plan["tp"], "止损止盈必须在入场价正确一侧"


def test_add_layer_rejected_without_llm_levels():
    """**两个来源都没有点位**时加仓 → 拒绝（不得开裸仓）。

    ⚠️ 语义澄清：这不是"LLM 没给就不开仓"。用户原话：
      "我的意思是LLM没有相反的预测方向 并且当前距离我们盈利的压力位
       也有距离就可以直接市价开仓"
    LLM 没给点位、但**本地结构位有**时，`lv.ok` 已是 True，不会走到这个闸。
    本测试构造的是最坏情况：LLM 没给 **且** ev 里没有任何缠论/SMC 结构
    （`ev` 只有 result，没有 chanlun/mobius）→ 无任何点位依据 → 拒绝。
    实测过裸仓事故：加仓开出 SL=0 TP=0 的仓位。
    """
    gate = RiskGate(CircuitBreakers(), GridState())
    ev = type("E", (), {"result": FusionResult(score=2.0, sigma=0.3)})()
    acc = AccountInfo(login=1, balance=10000, equity=10000, margin_free=10000,
                      margin=0, margin_level=0, leverage=2000, currency="USD")
    pos = type("P", (), {"ticket": 123456, "volume": 0.01, "price_open": 4350.0,
                         "magic": CFG.mt5.magic})()
    views = type("V", (), {"positions": [pos], "pending_orders": []})()
    res = gate.evaluate(Proposal(kind="add_layer", direction="LONG", entry=123456),
                        ev, acc, views, 0.1, None, 5.0, None)
    assert not res.ok
    assert "levels" in res.reason


def test_add_layer_allowed_with_local_structure_only():
    """LLM 没给点位，但**本地结构位有** → 加仓放行（用户澄清的核心）。

    这是 `test_add_layer_rejected_without_llm_levels` 的对照面：
    点位来源不必是 LLM，本地缠论中枢/SMC 结构位同样有效。
    """
    gate = RiskGate(CircuitBreakers(), GridState())
    cl = {"15m": type("C", (), {"center": {"zg": 4400.0, "zd": 4300.0,
                                           "gg": 4420.0, "dd": 4280.0}})()}
    ev = type("E", (), {"result": FusionResult(score=2.0, sigma=0.3),
                        "chanlun": cl, "mobius": None})()
    acc = AccountInfo(login=1, balance=10000, equity=10000, margin_free=10000,
                      margin=0, margin_level=0, leverage=2000, currency="USD")
    pos = type("P", (), {"ticket": 123456, "volume": 0.01, "price_open": 4350.0,
                         "magic": CFG.mt5.magic})()
    views = type("V", (), {"positions": [pos], "pending_orders": []})()
    res = gate.evaluate(Proposal(kind="add_layer", direction="LONG", entry=123456),
                        ev, acc, views, 0.1, None, 5.0, None,
                        llm_review={})   # LLM 什么都没给
    assert res.ok, f"本地有结构位就该放行，得到 {res.reason}"
    assert res.plan["sl"] < 4350.0 < res.plan["tp"], "止损止盈必须在入场价正确一侧"
    assert res.plan["sl_source"] == "struct_support", res.plan["sl_source"]
    assert res.plan["tp_source"] == "struct_resistance", res.plan["tp_source"]


# ══════════════════════════════════════════════════════════════════
# 执行层回归（4 个实测事故）
# ══════════════════════════════════════════════════════════════════
def _pos(ticket=123456, vol=0.01, sl=0.0, tp=0.0, price_open=4350.0):
    from gold_agent.mt5.client import PositionRow
    return PositionRow(ticket=ticket, symbol="XAUUSDm", type="LONG", volume=vol,
                       price_open=price_open, sl=sl, tp=tp, profit=15.0,
                       swap=0.0, time=0, comment="", magic=CFG.mt5.magic)


def _views(poss):
    return type("V", (), {"positions": poss, "pending_orders": []})()


def _acc():
    return AccountInfo(login=1, balance=10000, equity=10000, margin_free=10000,
                       margin=0, margin_level=0, leverage=2000, currency="USD")


def _ev():
    return type("E", (), {"result": FusionResult(score=2.0, sigma=0.3)})()


class _FakeSI:
    filling_mode = 2
    ask, bid = 4350.00, 4349.80


class _FakeClient:
    def symbol_info(self):
        return _FakeSI()


def test_close_position_request_carries_volume():
    """事故：平仓请求缺 volume → MT5 `(-2, 'Invalid "volume" argument')`。

    实测后果：连续 100+ 轮平仓 100% 失败，信号翻空后仓位仍挂着。
    """
    from gold_agent.mt5.executor import Executor, OrderPlan

    ex = Executor(_FakeClient())
    req = ex._build_request(OrderPlan(kind="close_position", direction="LONG",
                                      position_ticket=123456, lots=0.01))
    assert req.get("volume") == 0.01, "平仓请求必须带 volume，否则 MT5 拒绝"
    # 缺手数必须显式报错，而不是发出无效请求
    with pytest.raises(Exception):
        ex._build_request(OrderPlan(kind="close_position", direction="LONG",
                                    position_ticket=123456))


def test_close_position_plan_includes_lots():
    """风控层必须把持仓手数带进 plan（executor 才有 volume 可用）。"""
    gate = RiskGate(CircuitBreakers(), GridState())
    res = gate.evaluate(Proposal(kind="close_position", direction="LONG", entry=123456),
                        _ev(), _acc(), _views([_pos(vol=0.02)]), 0.1, None, 12.0, None)
    assert res.ok, res.reason
    assert res.plan["lots"] == 0.02, "plan 必须带原持仓手数"


def test_modify_sltp_keeps_existing_tp():
    """事故：TRADE_ACTION_SLTP 是整体覆盖，tp 传 0.0 = 删掉止盈 + 报 Invalid stops。"""
    from gold_agent.mt5.executor import Executor, OrderPlan

    ex = Executor(_FakeClient())
    req = ex._build_request(OrderPlan(kind="modify_sltp", direction="LONG",
                                      position_ticket=123456, sl=4330.0, tp=4360.0))
    assert req.get("tp") == 4360.0, "移损不得抹掉原有止盈"
    # 原持仓本来就没有 TP → 不带该键（不动），而不是写 0.0
    req2 = ex._build_request(OrderPlan(kind="modify_sltp", direction="LONG",
                                       position_ticket=123456, sl=4330.0, tp=None))
    assert "tp" not in req2, "原持仓无 TP 时不应传 tp=0.0"

    gate = RiskGate(CircuitBreakers(), GridState())
    res = gate.evaluate(Proposal(kind="modify_sltp", direction="LONG", entry=123456,
                                 tp_struct=4352.0),
                        _ev(), _acc(), _views([_pos(tp=4360.0)]), 0.1, None, 12.0, None)
    assert res.plan["keep_tp"] == 4360.0, "plan 必须带出原持仓的 TP"


def test_add_layer_carries_atr_sl_tp():
    """事故：加仓 plan 不含 tp/sl → 新仓位是 SL=0 TP=0 的裸仓。

    实测 3 个裸仓全部来自加仓（magic 相同，comment='goldagent-add'）。
    现在 SL/TP 来自 LLM 判断的压力位/支撑位。
    """
    gate = RiskGate(CircuitBreakers(), GridState())
    atr = 12.339
    res = gate.evaluate(Proposal(kind="add_layer", direction="LONG", entry=123456),
                        _ev(), _acc(), _views([_pos(price_open=4350.0)]),
                        0.1, None, atr, None,
                        llm_review=_llm_rev([4340.0], [4420.0]))
    assert res.ok, res.reason
    pl = res.plan
    assert pl.get("sl") and pl.get("tp"), "加仓必须自带止损止盈，否则是裸仓"
    assert pl["sl"] < pl["entry"] < pl["tp"], "做多加仓：SL < 入场 < TP"
    # 止损 = 下方支撑位让开 pad；止盈 = 上方压力位
    pad = CFG.risk.level_pad_atr * atr
    assert pl["sl"] == pytest.approx(4340.0 - pad, abs=0.01)
    assert pl["tp"] == pytest.approx(4420.0, abs=0.01)
    assert pl["sl_source"].startswith("llm_support")
    assert pl["tp_source"] == "llm_resistance"


def test_profit_lock_sl_distance_is_sane():
    """事故：移损 SL 算成 开仓价+2000（漏除 point），MT5 报 Invalid stops。

    point_value_per_lot=0.1（每 point/手），point=0.001 →
    每 1.0 价格单位/本仓位 = 0.1/0.001*0.01 = $1.0。
    锁定 $2 → 距离 2.0 个价格单位（旧实现是 2000.0）。
    """
    _POINT = 0.001
    pv_per_lot, volume, price_open = 0.1, 0.01, 4350.0
    usd_per_unit = pv_per_lot / _POINT * volume
    new_sl = price_open + 2.0 / usd_per_unit
    assert usd_per_unit == pytest.approx(1.0, abs=1e-9)
    assert new_sl - price_open == pytest.approx(2.0, abs=1e-6), (
        f"锁定 $2 的距离应为 2.0 个价格单位，实际 {new_sl - price_open}")


def test_summary_exposes_plan_for_console():
    """回归：graph 必须把 plan 放进 summary['risk']，否则控制台打出 'None手'。"""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]
           / "src" / "gold_agent" / "agent" / "graph.py").read_text(encoding="utf-8")
    assert '"plan": approved.plan' in src, (
        "graph.py 未把 approved.plan 放进 summary['risk'] —— "
        "控制台会显示 'None手' 且看不到止损止盈")


# ══════════════════════════════════════════════════════════════════
# P2-3 Wilson 置信下界
# ══════════════════════════════════════════════════════════════════
def test_wilson_lower_is_conservative_for_small_samples():
    """3 笔 1 胜：点估计 0.333，Wilson 下界应约 0.061。

    research/18 §P2-3：3 笔样本的胜率置信区间是 [6%, 79%]，
    它不能支持任何结论 —— 仓位必须自动缩到最小。
    """
    assert wilson_lower(1, 3) == pytest.approx(0.0615, abs=0.005)
    assert wilson_lower(1, 3) < 1 / 3, "Wilson 下界必须低于点估计"
    # 样本越大，下界越接近点估计
    small = wilson_lower(50, 100)
    large = wilson_lower(5000, 10000)
    assert small < large < 0.5
    assert wilson_lower(0, 0) == 0.0
    # 全胜的极端情形
    assert wilson_lower(3, 3) < 1.0


def test_conservative_win_rate_uses_fallback_below_threshold():
    """样本 < min_deals_for_kelly 时返回 fallback（冷启动）。"""
    assert conservative_win_rate(1, 3, fallback=0.5) == 0.5
    # 样本足够时返回 Wilson 下界（而非点估计）
    got = conservative_win_rate(60, 100, fallback=0.5)
    assert got == pytest.approx(wilson_lower(60, 100))
    assert got < 0.6, "必须低于点估计 0.60"


# ══════════════════════════════════════════════════════════════════
# P2-2 方向偏置熔断
# ══════════════════════════════════════════════════════════════════
def test_direction_bias_halts_on_structural_long():
    """P2-2：近 N 笔同向占比 > 85% → 停机复查。

    research/16 实测：3 笔交割单全为 LONG、融合分 80.2% 为正 ——
    系统不是在择时，而是在结构性做多黄金。
    """
    b = CircuitBreakers()
    # 样本不足时不应触发
    for _ in range(5):
        b.on_trade_closed(10.0, 10000, direction="LONG")
    assert not b.direction_bias_halt, "样本不足时不得触发偏置熔断"

    # 补足样本：全部 LONG
    for _ in range(CFG.risk.direction_bias_min_samples):
        b.on_trade_closed(10.0, 10000, direction="LONG")
    assert b.direction_bias_halt, "100% 单向应触发偏置熔断"
    r = b.check(10000, 0.0, False)
    assert r and "direction_bias_halt" in r


def test_direction_bias_allows_balanced_book():
    """双向均衡不应触发偏置熔断。"""
    b = CircuitBreakers()
    for i in range(40):
        b.on_trade_closed(10.0, 10000, direction="LONG" if i % 2 == 0 else "SHORT")
    assert not b.direction_bias_halt
    assert b.direction_bias_ratio <= CFG.risk.direction_bias_max


def test_direction_bias_clear():
    """人工复查后可解除偏置停机。"""
    b = CircuitBreakers()
    for _ in range(30):
        b.on_trade_closed(10.0, 10000, direction="SHORT")
    assert b.direction_bias_halt
    b.clear_direction_bias()
    assert not b.direction_bias_halt
    assert b.check(10000, 0.0, False) is None
    assert b.recent_directions == []


def test_direction_bias_records_string_and_int():
    """方向可用 LONG/SHORT 字符串或 ±1 整数记录。"""
    b = CircuitBreakers()
    b.record_direction("LONG")
    b.record_direction(1)
    b.record_direction(-1)
    b.record_direction("SHORT")
    b.record_direction(None)      # 未知方向不计入
    assert len(b.recent_directions) == 4
    assert b.recent_directions == [1, 1, -1, -1]
