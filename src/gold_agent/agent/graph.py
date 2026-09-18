"""LangGraph 状态图（docs/06 §4）。

节点：collect → analyze(parallel) → fuse → gate → [llm_review] → propose
     → risk → execute → persist → loop
异常 → safe_hold。
LLM 节点有 TTL 与预算；执行节点含成交对账。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, TypedDict

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import decision_log, log_error, log_warn, trade_log
from gold_agent.decision.machine import DecisionContext, DecisionEngine, Proposal
from gold_agent.fusion.engine import FusionEngine, _mobius_score
from gold_agent.llm.orchestrator import Orchestrator
from gold_agent.mt5.client import MT5Client, Mt5Error
from gold_agent.mt5.executor import ExecutionResult, Executor, OrderPlan
from gold_agent.news.collector import Jin10Collector
from gold_agent.risk.gate import Approved, RiskGate
from gold_agent.risk.grid import GridState
from gold_agent.risk.position import CircuitBreakers
from gold_agent.skills.chanlun_adapter import analyze_tf
from gold_agent.skills.mobius_adapter import MobiusClient


class GraphState(TypedDict, total=False):
    round_id: int
    error: str
    bundle: Any
    account: Any
    positions: Any
    chanlun: dict
    mobius: Any
    fused: Any
    news: Any
    llm: dict
    proposal: Any
    approved: Any
    execution: Any
    safe_hold: bool


_PRED_PATH = None  # lazy


@dataclass
class Graph:
    client: MT5Client
    executor: Executor
    mobius: MobiusClient
    news: Jin10Collector
    fusion: FusionEngine
    engine: DecisionEngine
    gate: RiskGate
    llm: Orchestrator | None
    breakers: CircuitBreakers
    grid_state: GridState
    deal_feedback: Any = None
    _pending_pred: dict = field(default_factory=dict)
    _position_adds: dict = field(default_factory=dict)   # {position_ticket_str: 加仓次数}   # position_id -> 融合分符号

    @classmethod
    def build(cls) -> "Graph":
        CFG.ensure_dirs()
        client = MT5Client()
        executor = Executor(client)
        mobius = MobiusClient()
        news = Jin10Collector()
        fusion = FusionEngine()
        breakers = CircuitBreakers.load(CFG.state_path.parent / "breakers.json")
        grid_state = GridState.load(CFG.state_path.parent / "grid_state.json")
        orchestrator: Orchestrator | None = None
        try:
            from gold_agent.llm.client import RunningHubClient
            orchestrator = Orchestrator(RunningHubClient())
        except Exception as e:
            # LLM 缺 key 时禁用（本地降级路径照常决策），首次成功调用前重试初始化
            orchestrator = Orchestrator(None)
            orchestrator._init_error = str(e)
        gate = RiskGate(breakers, grid_state)
        engine = DecisionEngine(gate, orchestrator)
        fb = None
        try:
            from gold_agent.fusion.deal_feedback import DealFeedback
            fb = DealFeedback(fusion.bayes, breakers)
        except Exception as e:
            log_warn(f"deal_feedback init failed: {e}")
        return cls(client=client, executor=executor, mobius=mobius, news=news,
                   fusion=fusion, engine=engine, gate=gate, llm=orchestrator,
                   breakers=breakers, grid_state=grid_state, deal_feedback=fb)

    async def run_round(self, round_id: int) -> dict:
        """一轮完整决策（docs/00 §3 t0..t9）。返回本轮摘要。"""
        st: GraphState = {"round_id": round_id}
        summary: dict = {"round": round_id, "ts": time.time()}
        try:
            # t0 collect
            if not self.client._connected:
                await self.client.initialize()
            st["bundle"] = await self.client.get_ohlcv()
            st["account"] = await self.client.get_account()
            st["positions"] = await self.client.get_positions()
            summary["last_close"] = float(st["bundle"].frames["1m"]["close"].iloc[-1])

            # t0b 交割单反馈闭环（胜率/盈亏 → 贝叶斯池 + 熔断器）
            if self.deal_feedback is not None:
                closed = await self.deal_feedback.poll(self.client)
                if closed:
                    # 用开仓时刻存下的融合分符号做贝叶斯 outcome 回填
                    for d in closed:
                        pred_sign = self._pending_pred.pop(str(d.get("position_id")), 0)
                        actual = 1 if d.get("pnl", 0) > 0 else (-1 if d.get("pnl", 0) < 0 else 0)
                        for src in ("kalman_persist", "chanlun", "openmobius_smc",
                                    "classic_indicators"):
                            self.fusion.bayes.record_outcome(src, pred_sign, actual)
                        self.fusion.bayes.save()
                    summary["deals_closed"] = len(closed)

            # t2 analyze (chanlun 本地 + mobius) 并发
            # 周期选择（用户要求：1 分钟线为主，15 分钟内研判权重更大，1d 最小）：
            #   短周期 1m/5m/15m 为主 + 1h/4h 作趋势背景，1d 只做超长线参考
            cl_tasks = {tf: asyncio.to_thread(analyze_tf, st["bundle"].frames[tf], tf)
                        for tf in ("1m", "5m", "15m", "1h", "4h")}
            mob_tasks = {
                "1m": asyncio.create_task(self.mobius.get_smc("XAUUSD", "1m", limit=200)),
                "5m": asyncio.create_task(self.mobius.get_smc("XAUUSD", "5m", limit=200)),
                "15m": asyncio.create_task(self.mobius.get_smc("XAUUSD", "15m", limit=200)),
                "1h": asyncio.create_task(self.mobius.get_smc("XAUUSD", "1h", limit=200)),
            }
            news_task = asyncio.create_task(self.news.fetch())
            cl_vals = await asyncio.gather(*cl_tasks.values())
            st["chanlun"] = dict(zip(cl_tasks.keys(), cl_vals))
            mob_vals = await asyncio.gather(*mob_tasks.values())
            st["mobius"] = dict(zip(mob_tasks.keys(), mob_vals))
            st["news"] = await news_task

            # t2/t3 fuse（先本地融合；LLM 之后若有效再融合一次）
            st["fused"] = self.fusion.fuse_all(st["bundle"].frames, st["chanlun"],
                                               st["mobius"])
            atr = (st["fused"].indicators.atr if st["fused"].indicators
                   and st["fused"].indicators.atr else None)

            # t2c 信号详情日志（用户要求：把影响分析的重要信号打印到日志）
            ind = st["fused"].indicators
            kal = st["fused"].kalman
            mob_last = float(st["bundle"].frames["15m"]["close"].iloc[-1])
            decision_log({
                "event": "signals",
                "round": round_id,
                "score": round(st["fused"].result.score, 3),
                "sigma": round(st["fused"].result.sigma, 3),
                "regime": st["fused"].result.regime,
                "hurst": round(st["fused"].result.hurst, 3) if st["fused"].result.hurst else None,
                "disagreement": st["fused"].result.disagreement,
                "per_source": st["fused"].result.per_source,
                "chanlun": {tf: {"score": r.score, "status": r.status}
                            for tf, r in st["chanlun"].items()},
                "mobius_score": {tf: (None if r is None else _mobius_score(r, mob_last))
                                 for tf, r in st["mobius"].items()},
                "mobius_status": {tf: (r.status if r is not None else None)
                                  for tf, r in st["mobius"].items()},
                "indicators": {
                    "momentum_accel": round(ind.momentum_accel, 3) if ind else None,
                    "tick_imbalance": round(ind.tick_imbalance, 3) if ind else None,
                    "vol_pressure": round(ind.vol_pressure, 3) if ind else None,
                    "range_compression": (round(ind.range_compression, 3) if ind else None),
                    "atr": round(ind.atr, 3) if ind and ind.atr else None,
                    "realized_vol_daily": (round(ind.realized_vol_daily, 5)
                                           if ind and ind.realized_vol_daily else None),
                },
                "kalman": (None if kal is None else {
                    "trend": round(kal.trend, 3), "slope_raw": round(kal.slope_raw, 5),
                    "persist": kal.slope_persist, "sigma": round(kal.sigma, 3)}),
                "news_count": len(st["news"].items) if st["news"] and hasattr(st["news"], "items") else 0,
                "high_risk": bool(getattr(st["news"], "high_risk_window", False)),
            })

            # t4 gate
            ev = st["fused"]
            need_llm = (abs(ev.result.score) >= CFG.decision.open_threshold - 0.4
                        or st["positions"].positions)
            ctx = DecisionContext(ev=ev, positions=st["positions"], news=st["news"],
                                  llm=None, last_close=summary["last_close"],
                                  atr=atr, realized_vol=st["fused"].indicators.realized_vol_daily
                                  if st["fused"].indicators else None,
                                  round_id=round_id,
                                  position_adds=self._position_adds,
                                  point_value_per_lot=self._point_value())
            if need_llm and self.llm is not None:
                st["llm"] = await self.llm.review_and_news(ev, st["news"],
                                                           summary["last_close"])
                ctx.llm = st["llm"]
                # LLM 评审结果重新融合（news_score 粗粒度：sentiment→分数）
                na = (st["llm"] or {}).get("news_assessment") or {}
                ns = {"bullish": 1.5, "bearish": -1.5, "neutral": 0.0}.get(na.get("sentiment"), 0.0)
                if ns:
                    ns *= float(na.get("impact", 0.5))
                    st["fused"] = self.fusion.fuse_all(st["bundle"].frames, st["chanlun"],
                                                       st["mobius"], news_score=ns)
                    ctx.ev = st["fused"]
                    ev = st["fused"]

            # t6 decide
            prop = self.engine.decide(ctx)
            st["proposal"] = prop
            summary["proposal"] = {"kind": prop.kind, "direction": prop.direction,
                                   "reasons": prop.reasons}
            summary["score"] = ev.result.score
            summary["sigma"] = ev.result.sigma
            if prop.kind == "hold":
                summary["action"] = "hold"
                return summary

            # t7 risk
            wr = self.deal_feedback.current_win_rate() if self.deal_feedback is not None else 0.5
            approved: Approved = self.gate.evaluate(
                Proposal(kind=prop.kind, direction=prop.direction, entry=prop.entry,
                         tp_struct=prop.tp_struct, reasons=prop.reasons, evidence_ids=[]),
                ev, st["account"], st["positions"],
                point_value_per_lot=self._point_value(),
                df_5m=st["bundle"].frames["5m"], atr=atr,
                realized_vol=st["fused"].indicators.realized_vol_daily
                if st["fused"].indicators else None,
                win_rate=wr,
                position_adds=self._position_adds)
            st["approved"] = approved
            summary["risk"] = {"ok": approved.ok, "reason": approved.reason}
            if not approved.ok:
                trade_log({"event": "risk_reject", "round": round_id,
                           "kind": prop.kind, "reason": approved.reason,
                           "proposal": prop.__dict__})
                return summary

            # t8 execute
            exec_res = await self._execute(approved.plan, st)
            st["execution"] = exec_res
            summary["execution"] = {"ok": exec_res.ok, "error": exec_res.error}
            trade_log({
                "event": "round_exec",
                "round": round_id,
                "plan": approved.plan,
                "ok": exec_res.ok,
                "retcode": exec_res.retcode,
                "price": exec_res.price,
                "lots": exec_res.volume,
            })
            # t9 persist
            decision_log({"event": "round_complete", "round": round_id,
                          "summary": {k: summary.get(k) for k in
                                      ("last_close", "proposal", "risk", "execution")}})
            self.breakers.save(CFG.state_path.parent / "breakers.json")
            self.grid_state.save(CFG.state_path.parent / "grid_state.json")
            self._save_position_adds()
            return summary
        except Mt5Error as e:
            log_error(f"round {round_id}: MT5 {e}")
            summary["error"] = str(e)
            summary["action"] = "skip_round"
            return summary
        except Exception as e:
            log_error(f"round {round_id}: {type(e).__name__}: {e}")
            summary["error"] = f"{type(e).__name__}: {e}"
            summary["action"] = "safe_hold"
            return summary

    async def _execute(self, plan: dict, st: GraphState) -> ExecutionResult:
        kind = plan.get("kind")
        if kind == "open_market":
            si = self.client.symbol_info()
            if plan["direction"] == "LONG":
                entry = si.ask if si else None
            else:
                entry = si.bid if si else None
            req = OrderPlan(kind="open_market", direction=plan["direction"],
                            lots=plan["lots"], tp=plan["tp"], sl=plan["sl"],
                            comment="goldagent-open",
                            idempotency_key=f"open-{int(time.time())}")
            res = await self.executor.execute(req)
            if res.ok:
                # 记录开仓时的融合分符号，平仓后用于贝叶斯反馈
                score = st.get("fused")
                s = float(score.result.score) if score is not None and getattr(score, "result", None) else 0.0
                # deal Feedback 需 position_id：成交后从 positions 查最新仓
                try:
                    view = await self.client.get_positions()
                    for p in view.positions:
                        if p.magic == CFG.mt5.magic:
                            self._pending_pred[str(p.ticket)] = (1 if s > 0 else -1 if s < 0 else 0)
                except Exception:
                    pass
            return res
        if kind == "close_position":
            req = OrderPlan(kind="close_position", direction=plan.get("direction"),
                            position_ticket=int(plan["position_ticket"]),
                            comment="goldagent-close",
                            idempotency_key=f"close-{plan['position_ticket']}-{int(time.time())}")
            return await self.executor.execute(req)
        if kind == "modify_sltp":
            # 保护性移损：TP 保持原位（None = 不动），SL 推到锁盈位（tp_struct 携带新 SL）
            req = OrderPlan(kind="modify_sltp", direction=plan.get("direction"),
                            position_ticket=int(plan["position_ticket"]),
                            sl=float(plan["new_sl"]), tp=None,
                            comment="goldagent-lock",
                            idempotency_key=f"lock-{plan['position_ticket']}-{int(time.time())}")
            res = await self.executor.execute(req)
            if res.ok:
                trade_log({"event": "sl_locked", "position": plan["position_ticket"],
                           "new_sl": plan["new_sl"],
                           "direction": plan.get("direction")})
            return res
        if kind == "add_layer":
            # 顺势加仓：固定 0.01 手，同向市价；成功后计数+1、记录分数/置信/基础差值（指数阶梯）
            req = OrderPlan(kind="open_market", direction=plan["direction"],
                            lots=float(plan["lots"]), tp=plan.get("tp"),
                            sl=plan.get("sl"), comment="goldagent-add",
                            idempotency_key=f"add-{plan['position_ticket']}-{int(time.time())}")
            res = await self.executor.execute(req)
            if res.ok:
                key = str(plan["position_ticket"])
                rec = self._position_adds.get(key)
                rec = rec if isinstance(rec, dict) else {"count": int(rec or 0)}
                prev_score = rec.get("last_score")
                fused = st.get("fused")
                llm = st.get("llm") or {}
                cur_score = float(fused.result.score) if fused and getattr(fused, "result", None) else None
                rec["count"] = int(rec.get("count", 0)) + 1
                rec["last_score"] = cur_score
                rec["last_conf"] = float((llm.get("review") or {}).get("confidence") or 0) or None
                # base_gap = 本次相对上次加仓的分数差（第 3 次起作指数增长基数）
                if prev_score is not None and cur_score is not None:
                    rec["base_gap"] = max(abs(cur_score) - abs(prev_score), 0.05)
                elif "base_gap" not in rec:
                    rec["base_gap"] = 0.1
                self._position_adds[key] = rec
                self._save_position_adds()
                trade_log({"event": "layer_added", "position": key,
                           "add_no": rec["count"],
                           "max": CFG.risk.max_adds_per_position,
                           "score": rec["last_score"], "conf": rec["last_conf"],
                           "base_gap": rec["base_gap"],
                           "lots": plan["lots"], "direction": plan["direction"]})
            return res
        if kind == "cancel_pending":
            # 行情反转撤挂单（docs/06 状态机：PENDING_GRID → IDLE）
            req = OrderPlan(kind="cancel_pending", position_ticket=int(plan["order_ticket"]),
                            comment="goldagent-cancel",
                            idempotency_key=f"cancel-{plan['order_ticket']}-{int(time.time())}")
            res = await self.executor.execute(req)
            if res.ok:
                trade_log({"event": "pending_cancelled", "ticket": plan["order_ticket"],
                           "direction": plan.get("direction")})
            return res
        if kind == "place_grid":
            # 逐层挂单
            last = ExecutionResult(ok=True)
            for layer in plan.get("grid_plan", []):
                req = OrderPlan(kind="place_pending", direction=plan["direction"],
                                lots=layer["lots"], entry=layer["level"],
                                tp=layer["tp"], sl=layer["sl"],
                                expiration_s=layer["expiration_s"],
                                comment="goldagent-grid",
                                idempotency_key=f"grid-{layer['level']}-{int(time.time())}")
                last = await self.executor.execute(req)
                if not last.ok:
                    break
            return last
        return ExecutionResult(ok=True, error=f"noop kind {kind}")

    def _save_position_adds(self) -> None:
        path = CFG.state_path.parent / "position_adds.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._position_adds), encoding="utf-8")

    def __post_init__(self) -> None:
        # 加仓计数跨进程持久
        try:
            path = CFG.state_path.parent / "position_adds.json"
            if path.exists():
                self._position_adds = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log_warn(f"position_adds load failed: {e}")

    def _point_value(self) -> float:
        si = self.client.symbol_info()
        if si is None:
            return 1.0
        # XAUUSDm: 1 lot = 100oz; point=0.001 → tick_value 已是每 tick 每 lot 美元
        return float(si.trade_tick_value) * (0.001 / max(si.trade_tick_size, 1e-9))

    async def close(self) -> None:
        await self.mobius.close()
        if self.llm and self.llm.client:
            await self.llm.client.close()
        self.client.shutdown()
