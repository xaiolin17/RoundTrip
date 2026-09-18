"""决策状态机（docs/06）。

状态: IDLE → PROPOSING → OPEN_LIVE/PENDING_GRID → HOLDING ⇄ GRID_LADDER/MARTIN_REVERSE
     → EXIT → IDLE；异常 → SAFE_HOLD。
LLM 只提供 verdict/confidence 作为证据；订单参数只出自 risk 模块。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import decision_log
from gold_agent.fusion.engine import FusedEvidence
from gold_agent.llm.orchestrator import Orchestrator
from gold_agent.mt5.client import PositionsView
from gold_agent.news.collector import NewsView
from gold_agent.risk.gate import Proposal, RiskGate


class State(str, Enum):
    IDLE = "IDLE"
    PROPOSING = "PROPOSING"
    OPEN_LIVE = "OPEN_LIVE"
    PENDING_GRID = "PENDING_GRID"
    HOLDING = "HOLDING"
    GRID_LADDER = "GRID_LADDER"
    MARTIN_REVERSE = "MARTIN_REVERSE"
    EXIT = "EXIT"
    SAFE_HOLD = "SAFE_HOLD"


@dataclass
class DecisionContext:
    ev: FusedEvidence
    positions: PositionsView
    news: NewsView
    llm: dict | None                       # review/news_assessment 结果
    last_close: float
    atr: float | None
    realized_vol: float | None
    round_id: int = 0


class DecisionEngine:
    def __init__(self, risk_gate: RiskGate, llm: Orchestrator | None = None) -> None:
        self.gate = risk_gate
        self.llm = llm
        self.state = State.IDLE
        self._exit_streak: dict[str, int] = {}   # direction -> 连续反向轮数

    def decide(self, ctx: DecisionContext) -> Proposal:
        """纯函数式判定一轮行为；执行与对账在 runner。"""
        r = ctx.ev.result
        try:
            holding = [p for p in ctx.positions.positions if p.magic == CFG.mt5.magic]
            if not holding:
                prop = self._decide_flat(ctx, r.score, r.sigma)
            else:
                prop = self._decide_holding(ctx, holding, r.score, r.sigma)
        except Exception as e:
            decision_log({"event": "decision_error", "error": str(e),
                          "round": ctx.round_id})
            self.state = State.SAFE_HOLD
            return Proposal(kind="hold", reasons=[f"error: {e}"])
        self.state = State.PROPOSING if prop.kind != "hold" else State.IDLE
        if holding:
            self.state = State.HOLDING if prop.kind == "hold" else self.state
        decision_log({"event": "decision", "round": ctx.round_id,
                      "score": r.score, "sigma": r.sigma, "proposal": prop.__dict__})
        return prop

    # ---------- 空仓 ----------
    def _decide_flat(self, ctx: DecisionContext, s: float, sigma: float) -> Proposal:
        thr = CFG.decision.open_threshold
        if sigma > CFG.fusion.sigma_max:
            return Proposal(kind="hold", reasons=[f"sigma {sigma:.2f} > {CFG.fusion.sigma_max}"])
        if ctx.news.high_risk_window:
            return Proposal(kind="hold", reasons=["news_high_risk_window"])
        if abs(s) < thr:
            return Proposal(kind="hold", reasons=[f"|S| {abs(s):.2f} < {thr}"])
        direction = "LONG" if s > 0 else "SHORT"
        # LLM 一致性加成：同向且 confidence 高 → 直接市价开仓
        review = (ctx.llm or {}).get("review") or {}
        verdict = review.get("verdict")
        conf = float(review.get("confidence") or 0)
        aligned = (verdict == ("bullish" if direction == "LONG" else "bearish")) and conf >= 0.6
        reasons = [f"S={s:+.2f} sigma={sigma:.2f}", f"llm={verdict}/{conf:.2f} aligned={aligned}"]
        if ctx.ev.result.regime == "mean_reverting":
            # 均值回归 regime → 只做网格限价
            return Proposal(kind="place_grid", direction=direction, entry=ctx.last_close,
                            reasons=reasons + ["regime=mean_reverting -> grid"])
        if aligned:
            return Proposal(kind="open_market", direction=direction, reasons=reasons)
        # 未对齐 → 先放网格限价（内侧挂单），等回踩
        return Proposal(kind="place_grid", direction=direction, entry=ctx.last_close,
                        reasons=reasons + ["llm not aligned -> grid first"])

    # ---------- 持仓 ----------
    def _decide_holding(self, ctx: DecisionContext, holding, s: float, sigma: float) -> Proposal:
        pos = holding[0]
        direction = pos.type
        review = (ctx.llm or {}).get("review") or {}
        verdict = review.get("verdict")
        conf = float(review.get("confidence") or 0)
        adverse = (direction == "LONG" and s <= -CFG.decision.exit_threshold) or \
                  (direction == "SHORT" and s >= CFG.decision.exit_threshold)
        adverse_llm = (direction == "LONG" and verdict == "bearish" or
                       direction == "SHORT" and verdict == "bullish") and conf >= 0.7
        key = direction
        if adverse:
            self._exit_streak[key] = self._exit_streak.get(key, 0) + 1
        else:
            self._exit_streak[key] = 0
        if self._exit_streak.get(key, 0) >= CFG.decision.exit_persist_rounds:
            return Proposal(kind="close_position", direction=direction,
                            entry=pos.ticket,
                            reasons=[f"adverse S x{self._exit_streak[key]} rounds"])
        if adverse_llm:
            return Proposal(kind="close_position", direction=direction, entry=pos.ticket,
                            reasons=[f"llm adverse {verdict}/{conf:.2f}"])
        # 新闻反向减仓
        na = (ctx.llm or {}).get("news_assessment") or {}
        if na.get("impact", 0) >= 0.8:
            na_dir = {"bullish": "LONG", "bearish": "SHORT", "neutral": None}.get(na.get("sentiment"))
            if na_dir and na_dir != direction:
                return Proposal(kind="close_position", direction=direction, entry=pos.ticket,
                                reasons=[f"news adverse impact={na['impact']}"])
        # 持有期检查
        age_h = (time.time() - pos.time) / 3600
        if age_h > CFG.risk.max_holding_h and pos.profit < 0:
            return Proposal(kind="close_position", direction=direction, entry=pos.ticket,
                            reasons=[f"holding {age_h:.1f}h and losing"])
        return Proposal(kind="hold", reasons=[f"holding {direction} {age_h:.1f}h S={s:+.2f}"])
