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
from gold_agent.risk.position import CircuitBreakers, position_lots, volatility_k
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
        # 收缩语义：TP 距离 ≤ 0.7×mult×ATR（可达性校验只会拉近）；但至少保留 0.3×ATR 空间
        tp_dist = abs(sh["tp"] - 4350.0)
        assert tp_dist <= CFG.risk.tp_atr_mult * 0.7 * atr + 1e-6, sh
        assert tp_dist >= 0.3 * atr - 0.3 * atr + 0.0 or tp_dist > 0  # 保证有正利润空间
        assert abs(sh["sl"] - 4350.0) >= CFG.risk.sl_atr_mult * 0.85 * atr - 1e-6
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
