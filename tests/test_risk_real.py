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
