"""LangGraph 状态图（docs/06 §4）。

节点：collect → analyze(parallel) → fuse → gate → [llm_review] → propose
     → risk → execute → persist → loop
异常 → safe_hold。
LLM 节点有 TTL 与预算；执行节点含成交对账。
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, TypedDict

import pandas as pd

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import (decision_log, log_error, log_info,
                                            log_warn, trade_log)
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
    # {position_id / order_id: 预测符号} 成交→贝叶斯反馈桥接（落盘 pred_orders.json）
    # 键统一用 position_id：平仓 deal 的 order 是新 ticket，与开仓时记的永不相等
    _pred_orders: dict = field(default_factory=dict)
    _position_adds: dict = field(default_factory=dict)   # {position_ticket_str: 加仓次数}
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
            log_warn(f"交割单反馈初始化失败：{e}")
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
                closed = await self.deal_feedback.poll(self.client, self._pred_orders)
                if closed:
                    # poll() 已把预测符号写进 rec["pred_sign"]（position_id 键桥接）
                    for d in closed:
                        pred_sign = d.get("pred_sign")
                        actual = 1 if d.get("pnl", 0) > 0 else (-1 if d.get("pnl", 0) < 0 else 0)
                        if pred_sign in (1, -1) and actual != 0:
                            for src in ("kalman_persist", "chanlun", "openmobius_smc",
                                        "classic_indicators"):
                                self.fusion.bayes.record_outcome(src, pred_sign, actual)
                            self.fusion.bayes.save()
                            trade_log({"event": "bayes_feedback", "position": d.get("position_id"),
                                       "pred": pred_sign, "actual": actual, "pnl": d.get("pnl")})
                            log_info(f"贝叶斯反馈: 仓位 {d.get('position_id')} "
                                     f"预测{'做多' if pred_sign > 0 else '做空'} "
                                     f"实际{'盈利' if actual > 0 else '亏损'} "
                                     f"盈亏 {d.get('pnl'):.2f}")
                        else:
                            # 符号为 0 = 开仓那轮融合分恰好为 0；或 pnl 为 0（保本平仓）
                            why = "融合分为 0" if pred_sign == 0 else "盈亏为 0"
                            log_warn(f"交割单 {d.get('position_id')}: 无预测符号（{why}，跳过贝叶斯）")
                        # 清理已平仓位的回吐检测峰值（防旧峰值误触发/泄漏）
                        self.engine._profit_peak.pop(str(d.get("position_id")), None)
                        self.engine._score_peak.pop(str(d.get("position_id")), None)
                    self._save_pred_orders()
                    summary["deals_closed"] = len(closed)

            # t2 analyze (chanlun 本地 + mobius) 并发
            # P1-1：决策周期迁移到 1h 后，方向判据以 1h/4h 为主，
            #       1m 降为执行择时（不参与方向，权重 0）。
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
                                               st["mobius"], obs_id=round_id)
            # P1-1：SL/TP 用 1h ATR（决策周期 ATR），不是 15m
            atr = self._decision_atr(st)

            # t2c 信号详情日志（用户要求：把影响分析的重要信号打印到日志）
            ind = st["fused"].indicators
            kal = st["fused"].kalman
            mob_last = float(st["bundle"].frames["15m"]["close"].iloc[-1])
            decision_log({
                "event": "signals",
                "round": round_id,
                "score": round(st["fused"].result.score, 3),
                "score_baseline": round(st["fused"].result.score_baseline, 3),
                "score_eff": round(st["fused"].result.score
                                   - st["fused"].result.score_baseline, 3),
                "vol_percentile": round(st["fused"].result.vol_percentile, 3),
                "effective_weight": round(st["fused"].result.effective_weight, 4),
                "sigma": round(st["fused"].result.sigma, 3),
                "regime": st["fused"].result.regime,
                "hurst": round(st["fused"].result.hurst, 3) if st["fused"].result.hurst else None,
                "disagreement": st["fused"].result.disagreement,
                "per_source": st["fused"].result.per_source,
                # P0-1 验收：原始分 vs 归一化分（各源均值应 ∈ [-0.3,+0.3]、为正 ≈ [40%,60%]）
                "raw_scores": {k: round(v, 3) for k, v in st["fused"].raw_scores.items()},
                "norm_scores": {k: round(v, 3) for k, v in st["fused"].norm_scores.items()},
                "source_warmed": st["fused"].warmed,
                "weight_table": st["fused"].weight_table,
                "chanlun": {tf: {"score": r.score, "status": r.status,
                                 "audit_mode": r.audit.output_mode,
                                 "failed_gates": r.audit.failed,
                                 "confirmed": len(r.confirmed_signals),
                                 "observed": len(r.observed_signals)}
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
                    "atr_1h": round(atr, 3) if atr else None,
                    "realized_vol_daily": (round(ind.realized_vol_daily, 5)
                                           if ind and ind.realized_vol_daily else None),
                },
                "kalman": (None if kal is None else {
                    "trend": round(kal.trend, 3), "slope_raw": round(kal.slope_raw, 5),
                    "persist": kal.slope_persist, "sigma": round(kal.sigma, 3)}),
                "news_count": len(st["news"].items) if st["news"] and hasattr(st["news"], "items") else 0,
                "high_risk": bool(getattr(st["news"], "high_risk_window", False)),
                "direction_bias": {
                    "ratio": round(self.breakers.direction_bias_ratio, 3),
                    "halt": self.breakers.direction_bias_halt,
                    "n": len(self.breakers.recent_directions)},
            })

            # t4 gate
            ev = st["fused"]
            # research/20 的修正：LLM 评审进入**主路径**。
            # 旧逻辑 need_llm = (|S|>=0.9) or 有持仓 + min_interval 15min
            # → 881 轮只成功 38 次（4.3%），系统绝大多数时候只能挂限价单。
            # 现在：1h 决策周期下每轮都评审（min_interval_min=0），
            # 且只有明显无信号的轮次才跳过以省预算。
            need_llm = (abs(ev.result.score - ev.result.score_baseline)
                        >= CFG.decision.open_threshold - 0.6
                        or bool(st["positions"].positions)
                        or bool(st["positions"].pending_orders)
                        or abs(ev.result.score_baseline) > 0.3)
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
                ctx.llm_available = bool((st["llm"] or {}).get("review"))
                # LLM 评审结果重新融合（news_score 粗粒度：sentiment→分数）
                na = (st["llm"] or {}).get("news_assessment") or {}
                ns = {"bullish": 1.5, "bearish": -1.5, "neutral": 0.0}.get(na.get("sentiment"), 0.0)
                if ns:
                    ns *= float(na.get("impact", 0.5))
                    st["fused"] = self.fusion.fuse_all(st["bundle"].frames, st["chanlun"],
                                                       st["mobius"], news_score=ns,
                                                       obs_id=round_id)
                    ctx.ev = st["fused"]
                    ev = st["fused"]
                # LLM 评审结果落日志（skill 合规审计）
                self._log_llm_review(round_id, st["llm"], ctx.llm_available)

            # t6 decide
            prop = self.engine.decide(ctx)
            st["proposal"] = prop
            summary["proposal"] = {"kind": prop.kind, "direction": prop.direction,
                                   "reasons": prop.reasons}
            summary["score"] = ev.result.score
            summary["sigma"] = ev.result.sigma
            # ⚠️ action 必须**在这里**就设好。
            #    原实现只在 hold / skip_round / safe_hold 三个分支里赋值，
            #    于是 place_grid / open_market / cancel_pending 这些
            #    **真正下单**的轮次没有 action → 控制台打印 `-> ?`。
            #    结果恰好是：越重要的轮次越看不出发生了什么。
            summary["action"] = prop.kind
            if prop.kind == "hold":
                return summary

            # t7 risk
            wr = self.deal_feedback.current_win_rate() if self.deal_feedback is not None else 0.5
            # LLM 判断的压力位/支撑位要传进风控 —— 止损止盈按它算
            _rev = ((st.get("llm") or {}).get("review") or None)
            approved: Approved = self.gate.evaluate(
                Proposal(kind=prop.kind, direction=prop.direction, entry=prop.entry,
                         tp_struct=prop.tp_struct, reasons=prop.reasons, evidence_ids=[]),
                ev, st["account"], st["positions"],
                point_value_per_lot=self._point_value(),
                df_5m=st["bundle"].frames["5m"], atr=atr,
                realized_vol=st["fused"].indicators.realized_vol_daily
                if st["fused"].indicators else None,
                win_rate=wr,
                position_adds=self._position_adds,
                llm_review=_rev,
                # 自研回调检测需要小周期 K 线（缠论代理在小周期上不准）
                frames=st["bundle"].frames)
            st["approved"] = approved
            # plan 必须放进 summary：控制台要靠它显示方向/入场/止损/止盈
            # （只放 ok/reason 的话，显示层读不到价位，会打出 "None手"）
            summary["risk"] = {"ok": approved.ok, "reason": approved.reason,
                               "plan": approved.plan}
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
            # P0-1/P1-2/P1-3：滚动统计量跨进程持久（重启不丢预热）
            self.fusion.save_state()
            return summary
        except Mt5Error as e:
            log_error(f"第 {round_id} 轮：MT5 错误 {e}")
            summary["error"] = str(e)
            summary["action"] = "skip_round"
            return summary
        except Exception as e:
            log_error(f"第 {round_id} 轮：{type(e).__name__}: {e}")
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
                self._record_pred(res, st)
            return res
        if kind == "close_position":
            # 必须带 lots：平仓请求缺 volume 会被 MT5 拒绝
            req = OrderPlan(kind="close_position", direction=plan.get("direction"),
                            lots=float(plan["lots"]),
                            position_ticket=int(plan["position_ticket"]),
                            comment="goldagent-close",
                            idempotency_key=f"close-{plan['position_ticket']}-{int(time.time())}")
            return await self.executor.execute(req)
        if kind == "modify_sltp":
            # 保护性移损：SL 推到锁盈位（tp_struct 携带新 SL）；
            # TP 保持原位（keep_tp 由风控从原持仓带出，None 才不动）
            req = OrderPlan(kind="modify_sltp", direction=plan.get("direction"),
                            position_ticket=int(plan["position_ticket"]),
                            sl=float(plan["new_sl"]), tp=plan.get("keep_tp"),
                            comment="goldagent-lock",
                            idempotency_key=f"lock-{plan['position_ticket']}-{int(time.time())}")
            res = await self.executor.execute(req)
            if res.ok:
                trade_log({"event": "sl_locked", "position": plan["position_ticket"],
                           "new_sl": plan["new_sl"],
                           "direction": plan.get("direction")})
            return res
        if kind == "add_layer":
            # 顺势加仓：固定 0.01 手，同向市价；自带 ATR 算出的 SL/TP
            # （原实现不带 tp/sl → 加仓开成裸仓）
            req = OrderPlan(kind="open_market", direction=plan["direction"],
                            lots=float(plan["lots"]), tp=plan.get("tp"),
                            sl=plan.get("sl"), comment="goldagent-add",
                            idempotency_key=f"add-{plan['position_ticket']}-{int(time.time())}")
            res = await self.executor.execute(req)
            if res.ok:
                # ⚠️ 事故修复：加仓开的是**新仓位**，原先整个分支都没有记录
                # 预测符号 -> 加仓仓位的贝叶斯反馈永远丢失（实测 layer_added
                # 有 10 条，bayes_feedback 有 0 条）。
                self._record_pred(res, st)
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
            # 单张限价挂单（用户要求：取消网格）；挂单成功后记录预测符号，
            # 成交后由 _record_pred 的 position_id 键回填贝叶斯
            last = ExecutionResult(ok=True)
            for layer in plan.get("grid_plan", []):
                req = OrderPlan(kind="place_pending", direction=plan["direction"],
                                lots=layer["lots"], entry=layer["level"],
                                tp=layer["tp"], sl=layer["sl"],
                                expiration_s=layer["expiration_s"],
                                comment="goldagent-pending",
                                idempotency_key=f"pending-{layer['level']}-{int(time.time())}")
                last = await self.executor.execute(req)
                if not last.ok:
                    break
                if last.order:
                    self._record_pred(last, st)
            return last
        return ExecutionResult(ok=True, error=f"noop kind {kind}")

    def _save_position_adds(self) -> None:
        path = CFG.state_path.parent / "position_adds.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._position_adds), encoding="utf-8")

    # ---------- P1-1：决策周期 ATR ----------
    def _decision_atr(self, st: GraphState) -> float | None:
        """SL/TP 用**高级别（默认 1h）**的 ATR，而不是入场周期（1m）。

        ⚠️ 这是 1m 短线能否成立的关键，不是可选项。

        research/23_kalman_tb.py 实测（60,000 根真实 1m bar）：

            止损基准        止损(USD)   成本/止损   净NW-t
            1m ATR x1.2       1.13      46.0%     -30.00
            15m 尺度 x1.2     4.74      11.0%      -4.38
            1h ATR x1.2      20.80       2.5%      -1.40

        成本 0.52 USD 是固定的。用 1m 的波动定止损时，成本吃掉止损的 46% ——
        数学上不可能盈利；用 1h ATR 定止损，成本只占 2.5%。

        **所以"1m 不能交易"这个结论只在"用 1m 波动定止损"的前提下成立。**

        1m 负责**入场择时**（精度高、机会多），高级别负责**风险尺度**（成本占比低）。
        """
        frames = st.get("bundle").frames if st.get("bundle") else {}
        tf = CFG.risk.atr_tf
        df = frames.get(tf)
        if df is None or len(df) < 20:
            ind = st.get("fused").indicators if st.get("fused") else None
            return ind.atr if ind else None
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])
        return atr if atr > 0 else None

    # ---------- LLM 评审日志（skill 合规审计） ----------
    def _log_llm_review(self, round_id: int, llm: dict | None, available: bool) -> None:
        """记录 LLM 是否参与、以及它按 skill 走了哪些检查项。"""
        review = (llm or {}).get("review") or {}
        audit = review.get("skill_audit") or {}
        decision_log({
            "event": "llm_review",
            "round": round_id,
            "available": available,
            "verdict": review.get("verdict"),
            "confidence": review.get("confidence"),
            "chanlun_mode": audit.get("chanlun_mode"),
            "chanlun_gates": audit.get("chanlun_gates"),
            "smc_steps": audit.get("smc_steps"),
            "probability_tier": audit.get("probability_tier"),
            "caveats_disclosed": audit.get("caveats_disclosed"),
            "invalidation": review.get("invalidation"),
            "next_observation": review.get("next_observation"),
            "risk_flags": review.get("risk_flags"),
            # 压力位/支撑位 —— 止损止盈的定价依据，必须留痕可审计
            "support_levels": review.get("support_levels"),
            "resistance_levels": review.get("resistance_levels"),
            "sl_hint": review.get("sl_hint"),
            "tp_hint": review.get("tp_hint"),
            "level_reason": review.get("level_reason"),
            "key_levels": review.get("key_levels"),
            "review_coverage": (round(self.llm.review_coverage, 3)
                                if self.llm is not None else None),
        })

    def _record_pred(self, res, st: GraphState) -> None:
        """记录本次成交的**预测符号**，键为 position_id（成交→贝叶斯反馈桥接）。

        ⚠️ 事故修复（用户报告「无预测符号（未桥接，跳过贝叶斯）」）
        ----------------------------------------------------------
        原实现有三处缺陷，导致这条闭环**从未生效**（实测 17 笔平仓
        pred_sign 全为 None、bayes_feedback 0 条）：

        1. **键不匹配**：`deal_feedback.poll()` 用平仓 deal 的 `order` 去 pop，
           而平仓 order 是新 ticket（开仓 2557969245 / 平仓 2558130417），
           与挂单时记的 order ticket 永远不等。
           -> 统一改用 `position_id`（实测开仓 deal 的 order == position_id）。
        2. **加仓漏记**：`add_layer` 开的是新仓位，但整个分支没有记录预测符号。
        3. **不持久化**：`_pending_pred` 只是内存字典，进程重启后全部丢失；
           而市价开仓**必须**跨轮次（开仓→若干轮后平仓）才能回填。
           -> 统一并入 `_pred_orders` 并落盘 `pred_orders.json`。

        `res.order` 是 MT5 返回的 order ticket；市价单成交后它与 position_id
        相同（实测 6/6 成立），挂单成交时也按 order 键兜底。
        """
        fused = st.get("fused")
        s = 0.0
        if fused is not None and getattr(fused, "result", None) is not None:
            s = float(fused.result.score)
        sign = 1 if s > 0 else (-1 if s < 0 else 0)
        ticket = getattr(res, "order", 0) or 0
        if not ticket:
            log_warn("预测符号记录跳过：成交未返回 order ticket")
            return
        self._pred_orders[str(ticket)] = sign
        self._save_pred_orders()

    def _save_pred_orders(self) -> None:
        path = CFG.state_path.parent / "pred_orders.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        # 只保留最近 200 条（成交反馈用完即弃）
        items = list(self._pred_orders.items())[-200:]
        path.write_text(json.dumps(dict(items)), encoding="utf-8")

    def __post_init__(self) -> None:
        # 加仓计数跨进程持久
        try:
            path = CFG.state_path.parent / "position_adds.json"
            if path.exists():
                self._position_adds = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log_warn(f"加仓记录读取失败：{e}")
        # 挂单→成交预测符号桥接持久
        try:
            path = CFG.state_path.parent / "pred_orders.json"
            if path.exists():
                self._pred_orders = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log_warn(f"预测挂单读取失败：{e}")
        # P0-1/P1-2/P1-3：滚动统计量恢复（重启不丢预热，否则每次重启都要空仓等预热）
        try:
            self.fusion.load_state()
        except Exception as e:
            log_warn(f"融合状态读取失败：{e}")
        # ⚠️ 1m 短线的关键：若归一化器仍未预热（首次启动 / state 丢失），
        #    用历史 bar 回放灌满缓冲。否则启动后 min_periods 轮
        #    （1m 下 = 4 小时）所有源分数都是 0.0 → 融合分恒 0 → 永不开仓。
        try:
            if not self.fusion.normalizer.warm("kalman_persist"):
                bundle = self.client.get_ohlcv_sync()
                if bundle and bundle.frames:
                    n = self.fusion.prime_history(bundle.frames)
                    log_info(f"融合器已用历史数据预热：{n} 步")
                else:
                    log_warn("跳过融合预热：无行情数据")
        except Exception as e:
            log_warn(f"融合预热失败：{e}")

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
