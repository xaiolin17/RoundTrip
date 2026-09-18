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
    position_adds: dict | None = None      # {position_ticket_str: 已加仓次数}（Graph 持久）
    point_value_per_lot: float = 1.0       # 每手每点美元值（移损计算用）


class DecisionEngine:
    def __init__(self, risk_gate: RiskGate, llm: Orchestrator | None = None) -> None:
        self.gate = risk_gate
        self.llm = llm
        self.state = State.IDLE
        self._exit_streak: dict[str, int] = {}   # direction -> 连续反向轮数
        self._profit_peak: dict[str, float] = {}  # ticket -> 持仓期间浮盈峰值（回吐检测）
        self._score_peak: dict[str, float] = {}   # ticket -> 持仓期间顺向信号峰值

    def decide(self, ctx: DecisionContext) -> Proposal:
        """纯函数式判定一轮行为；执行与对账在 runner。"""
        r = ctx.ev.result
        try:
            holding = [p for p in ctx.positions.positions if p.magic == CFG.mt5.magic]
            pending = [o for o in ctx.positions.pending_orders if o.magic == CFG.mt5.magic]
            if pending:
                # 行情反转 → 撤挂单（用户要求：行情不对要删除挂单）
                # 判定：融合分与挂单方向相反且越过平仓阈值，或信号分歧度爆表
                s, sigma = r.score, r.sigma
                pdir = "LONG" if "buy" in str(pending[0].type).lower() else "SHORT"
                adverse = (pdir == "LONG" and s <= -CFG.decision.exit_threshold) or \
                          (pdir == "SHORT" and s >= CFG.decision.exit_threshold)
                if adverse or sigma > CFG.fusion.sigma_max:
                    prop = Proposal(kind="cancel_pending", direction=pdir,
                                    entry=pending[0].ticket,
                                    reasons=[f"pending {pdir} adverse: S={s:+.2f} sigma={sigma:.2f}"])
                else:
                    # 同向或中性 → 继续等待成交，不重复放单
                    prop = Proposal(kind="hold", reasons=[f"pending x{len(pending)} waiting fill"])
            elif not holding:
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
        # 顺势加仓（用户规则：每仓固定 0.01 手，同向最多加 5 次）
        # 阶梯式：分数与置信均须高于上一次；第 3 次起门槛指数递增
        # （指数基数 = 上一次加仓时的分数差值：gap = |S_now| − |S_last|，
        #   第 N 次加仓要求 |S| ≥ last + gap × 2^(N−3)，N=3 时即翻倍于上次差值）
        same_side = (direction == "LONG" and s > 0) or (direction == "SHORT" and s < 0)
        adds = getattr(ctx, "position_adds", None) or {}
        rec = adds.get(str(pos.ticket)) or {}
        if isinstance(rec, dict):
            adds_count = int(rec.get("count", 0))
            last_score = rec.get("last_score")
            last_conf = rec.get("last_conf")
        else:                                   # 兼容旧格式 {ticket: n}
            adds_count, last_score, last_conf = int(rec or 0), None, None
        conf_cur = float(review.get("confidence") or 0)
        cur = abs(s)
        if last_score is None:
            score_ok = True                     # 首次加仓：只需过开仓阈值
            required = cur
        else:
            last = float(last_score)
            gap = max(cur - last, 0.0)          # 本次相对上次的提升量
            if adds_count < 2:
                required = last + min(gap, 0.1) if gap > 0 else None
                score_ok = required is not None
            else:
                # 第 3 次起：要求 ≥ last + gap×2^(count−1)，gap 取上次差值与 0.1 的大者
                base_gap = max(rec.get("base_gap") or 0.1, 0.1)
                required = last + base_gap * (2 ** (adds_count - 1))
                score_ok = cur >= required
        conf_ok = last_conf is None or conf_cur > float(last_conf)
        if (same_side and abs(s) >= CFG.decision.open_threshold
                and sigma <= CFG.fusion.sigma_max
                and adds_count < CFG.risk.max_adds_per_position
                and score_ok and conf_ok):
            return Proposal(kind="add_layer", direction=direction, entry=pos.ticket,
                            reasons=[f"add #{adds_count + 1}/{CFG.risk.max_adds_per_position} "
                                     f"S={s:+.2f} (need>={required:.2f} last={last_score}) "
                                     f"conf={conf_cur:.2f} (last={last_conf})"])
        # ---- 超短期利润回吐检测（用户要求：识别到利润会回吐就主动平仓）----
        # 信号面：持仓期间信号从峰值回落超过 reserve_drop 分数即视为「回吐启动」；
        # 盈利面：浮盈曾达 peak_profit 后回落超过一半且当前仍为正 → 保住大部分利润离场。
        # 两者任一触发即平仓（优先级高于加仓/锁盈）。
        key_pos = str(pos.ticket)
        peak = self._profit_peak.get(key_pos, 0.0)
        cur_profit = pos.profit
        self._profit_peak[key_pos] = max(peak, cur_profit)
        score_peak = self._score_peak.get(key_pos, 0.0)
        same_dir_score = s if direction == "LONG" else -s     # 顺持仓方向的信号分
        self._score_peak[key_pos] = max(score_peak, same_dir_score)
        reserve_drop = CFG.decision.reserve_drop_score
        profit_giveback = (self._profit_peak[key_pos] > CFG.decision.reserve_min_profit
                           and cur_profit < 0.5 * self._profit_peak[key_pos])
        signal_giveback = (self._score_peak[key_pos] >= CFG.decision.open_threshold
                           and same_dir_score <= self._score_peak[key_pos] - reserve_drop)
        if profit_giveback or signal_giveback:
            why = (f"profit giveback: peak ${self._profit_peak[key_pos]:.2f} -> ${cur_profit:.2f}"
                   if profit_giveback else
                   f"signal giveback: peak S={self._score_peak[key_pos]:+.2f} -> {same_dir_score:+.2f}")
            return Proposal(kind="close_position", direction=direction, entry=pos.ticket,
                            reasons=[why])
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
        # ---- 保护性移损（用户规则：利润 > $10 时，把 SL 推到盈利 $2 处，锁底搏上限）----
        # 仅当当前 SL 还在开仓价不利一侧（即还没锁过）时执行一次
        point_value = getattr(ctx, "point_value_per_lot", 1.0) * pos.volume
        profit_locked_sl = (pos.price_open + 2.0 / max(point_value, 1e-9) if direction == "LONG"
                            else pos.price_open - 2.0 / max(point_value, 1e-9))
        sl_still_open = (pos.sl is not None and pos.sl > 0 and
                         ((direction == "LONG" and pos.sl < pos.price_open) or
                          (direction == "SHORT" and pos.sl > pos.price_open)))
        if pos.profit > 10.0 and sl_still_open:
            return Proposal(kind="modify_sltp", direction=direction, entry=pos.ticket,
                            tp_struct=profit_locked_sl, reasons=[
                                f"breakeven+ lock: profit ${pos.profit:.2f} > $10, "
                                f"SL -> {profit_locked_sl:.3f} (profit $2 floor)"])
        return Proposal(kind="hold", reasons=[f"holding {direction} {age_h:.1f}h S={s:+.2f}"])
