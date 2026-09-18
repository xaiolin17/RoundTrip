"""决策状态机真实数据回放测试（无 mock）：空仓/持仓/熔断安全态。"""
from __future__ import annotations

import pytest

from gold_agent.common.config import CFG
from gold_agent.decision.machine import DecisionContext, DecisionEngine, State
from gold_agent.fusion.engine import FusedEvidence, FusionResult
from gold_agent.mt5.client import PositionRow, PositionsView
from gold_agent.news.collector import NewsView
from gold_agent.risk.gate import RiskGate
from gold_agent.risk.grid import GridState
from gold_agent.risk.position import CircuitBreakers


def _ctx(score: float, sigma: float = 0.3, holding: list[PositionRow] | None = None,
         llm: dict | None = None, high_risk: bool = False) -> DecisionContext:
    ev = FusedEvidence(result=FusionResult(score=score, sigma=sigma, regime="trending"))
    pos = PositionsView(positions=holding or [])
    news = NewsView(high_risk_window=high_risk)
    return DecisionContext(ev=ev, positions=pos, news=news, llm=llm,
                           last_close=4350.0, atr=5.0, realized_vol=0.008, round_id=1)


def test_flat_hold_low_score():
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    p = e.decide(_ctx(score=0.7))
    assert p.kind == "hold"
    assert any("1.6" in r for r in p.reasons)


def test_flat_hold_high_sigma():
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    p = e.decide(_ctx(score=2.0, sigma=1.5))
    assert p.kind == "hold"
    assert any("sigma" in r for r in p.reasons)


def test_flat_hold_news_high_risk():
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    p = e.decide(_ctx(score=2.0, high_risk=True))
    assert p.kind == "hold"
    assert any("news" in r for r in p.reasons)


def test_flat_open_market_aligned_llm():
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    p = e.decide(_ctx(score=2.0, llm={"review": {"verdict": "bullish", "confidence": 0.75}}))
    assert p.kind == "open_market"
    assert p.direction == "LONG"


def test_flat_grid_when_not_aligned():
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    p = e.decide(_ctx(score=-2.0, llm={"review": {"verdict": "bullish", "confidence": 0.6}}))
    assert p.kind == "place_grid"
    assert p.direction == "SHORT"


def test_holding_exit_streak():
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    pos = PositionRow(ticket=111, symbol="XAUUSDm", type="LONG", volume=0.01,
                      price_open=4350, sl=0, tp=0, profit=0, swap=0, time=0,
                      comment="", magic=CFG.mt5.magic)
    # 需要连续 3 轮反向
    for _ in range(CFG.decision.exit_persist_rounds - 1):
        p = e.decide(_ctx(score=-1.5, holding=[pos]))
        assert p.kind == "hold"
    p = e.decide(_ctx(score=-1.5, holding=[pos]))
    assert p.kind == "close_position"


def test_holding_llm_adverse_close():
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    pos = PositionRow(ticket=222, symbol="XAUUSDm", type="SHORT", volume=0.01,
                      price_open=4350, sl=0, tp=0, profit=0, swap=0, time=0,
                      comment="", magic=CFG.mt5.magic)
    p = e.decide(_ctx(score=-0.5, holding=[pos],
                      llm={"review": {"verdict": "bullish", "confidence": 0.8}}))
    assert p.kind == "close_position"


def test_safe_hold_on_error():
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    # 触发异常：positions 里放非法对象
    p = e.decide(_ctx(score=2.0, holding=["bad-object"]))
    assert p.kind == "hold"
    assert e.state == State.SAFE_HOLD
