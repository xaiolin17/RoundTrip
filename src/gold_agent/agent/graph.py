"""LangGraph 鐘舵€佸浘锛坉ocs/06 搂4锛夈€?
鑺傜偣锛歝ollect 鈫?analyze(parallel) 鈫?fuse 鈫?gate 鈫?[llm_review] 鈫?propose
     鈫?risk 鈫?execute 鈫?persist 鈫?loop
寮傚父 鈫?safe_hold銆?LLM 鑺傜偣鏈?TTL 涓庨绠楋紱鎵ц鑺傜偣鍚垚浜ゅ璐︺€?"""
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
    _pending_pred: dict = field(default_factory=dict)
    _pred_orders: dict = field(default_factory=dict)   # {order_id_str: pred_sign} 鎸傚崟鈫掓垚浜ゆˉ鎺?    _position_adds: dict = field(default_factory=dict)   # {position_ticket_str: 鍔犱粨娆℃暟}   # position_id -> 铻嶅悎鍒嗙鍙?
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
            # LLM 缂?key 鏃剁鐢紙鏈湴闄嶇骇璺緞鐓у父鍐崇瓥锛夛紝棣栨鎴愬姛璋冪敤鍓嶉噸璇曞垵濮嬪寲
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
        """涓€杞畬鏁村喅绛栵紙docs/00 搂3 t0..t9锛夈€傝繑鍥炴湰杞憳瑕併€?""
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

            # t0b 浜ゅ壊鍗曞弽棣堥棴鐜紙鑳滅巼/鐩堜簭 鈫?璐濆彾鏂睜 + 鐔旀柇鍣級
            if self.deal_feedback is not None:
                closed = await self.deal_feedback.poll(self.client, self._pred_orders)
                if closed:
                    # 鐢ㄦˉ鎺ユ壘鍥炵殑棰勬祴绗﹀彿鍋氳礉鍙舵柉 outcome 鍥炲～
                    for d in closed:
                        pred_sign = self.deal_feedback.last_pred_by_position.get(
                            str(d.get("position_id")))
                        if pred_sign is None:
                            pred_sign = self._pending_pred.pop(str(d.get("position_id")), 0)
                        else:
                            self._pending_pred.pop(str(d.get("position_id")), None)
                        actual = 1 if d.get("pnl", 0) > 0 else (-1 if d.get("pnl", 0) < 0 else 0)
                        if pred_sign in (1, -1) and actual != 0:
                            for src in ("kalman_persist", "chanlun", "openmobius_smc",
                                        "classic_indicators"):
                                self.fusion.bayes.record_outcome(src, pred_sign, actual)
                            self.fusion.bayes.save()
                            trade_log({"event": "bayes_feedback", "position": d.get("position_id"),
                                       "pred": pred_sign, "actual": actual, "pnl": d.get("pnl")})
                        else:
                            log_warn(f"deal {d.get('position_id')}: no pred sign (鏈ˉ鎺ワ紝璺宠繃璐濆彾鏂?")
                        # 娓呯悊宸插钩浠撲綅鐨勫洖鍚愭娴嬪嘲鍊硷紙闃叉棫宄板€艰瑙﹀彂/娉勬紡锛?                        self.engine._profit_peak.pop(str(d.get("position_id")), None)
                        self.engine._score_peak.pop(str(d.get("position_id")), None)
                    if closed:
                        self._save_pred_orders()
                    summary["deals_closed"] = len(closed)

            # t2 analyze (chanlun 鏈湴 + mobius) 骞跺彂
            # P1-1锛氬喅绛栧懆鏈熻縼鍒?1h 鍚庯紝鏂瑰悜鍒ゆ嵁浠?1h/4h 涓轰富锛?            #       1m 闄嶄负鎵ц鎷╂椂锛堜笉鍙備笌鏂瑰悜锛屾潈閲?0锛夈€?            cl_tasks = {tf: asyncio.to_thread(analyze_tf, st["bundle"].frames[tf], tf)
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

            # t2/t3 fuse锛堝厛鏈湴铻嶅悎锛汱LM 涔嬪悗鑻ユ湁鏁堝啀铻嶅悎涓€娆★級
            st["fused"] = self.fusion.fuse_all(st["bundle"].frames, st["chanlun"],
                                               st["mobius"], obs_id=round_id)
            # P1-1锛歋L/TP 鐢?1h ATR锛堝喅绛栧懆鏈?ATR锛夛紝涓嶆槸 15m
            atr = self._decision_atr(st)

            # t2c 淇″彿璇︽儏鏃ュ織锛堢敤鎴疯姹傦細鎶婂奖鍝嶅垎鏋愮殑閲嶈淇″彿鎵撳嵃鍒版棩蹇楋級
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
                # P0-1 楠屾敹锛氬師濮嬪垎 vs 褰掍竴鍖栧垎锛堝悇婧愬潎鍊煎簲 鈭?[鈭?.3,+0.3]銆佷负姝?鈭?[40%,60%]锛?                "raw_scores": {k: round(v, 3) for k, v in st["fused"].raw_scores.items()},
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
            # research/20 鐨勪慨姝ｏ細LLM 璇勫杩涘叆**涓昏矾寰?*銆?            # 鏃ч€昏緫 need_llm = (|S|>=0.9) or 鏈夋寔浠?+ min_interval 15min
            # 鈫?881 杞彧鎴愬姛 38 娆★紙4.3%锛夛紝绯荤粺缁濆ぇ澶氭暟鏃跺€欏彧鑳芥寕闄愪环鍗曘€?            # 鐜板湪锛?h 鍐崇瓥鍛ㄦ湡涓嬫瘡杞兘璇勫锛坢in_interval_min=0锛夛紝
            # 涓斿彧鏈夋槑鏄炬棤淇″彿鐨勮疆娆℃墠璺宠繃浠ョ渷棰勭畻銆?            need_llm = (abs(ev.result.score - ev.result.score_baseline)
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
                # LLM 璇勫缁撴灉閲嶆柊铻嶅悎锛坣ews_score 绮楃矑搴︼細sentiment鈫掑垎鏁帮級
                na = (st["llm"] or {}).get("news_assessment") or {}
                ns = {"bullish": 1.5, "bearish": -1.5, "neutral": 0.0}.get(na.get("sentiment"), 0.0)
                if ns:
                    ns *= float(na.get("impact", 0.5))
                    st["fused"] = self.fusion.fuse_all(st["bundle"].frames, st["chanlun"],
                                                       st["mobius"], news_score=ns,
                                                       obs_id=round_id)
                    ctx.ev = st["fused"]
                    ev = st["fused"]
                # LLM 璇勫缁撴灉钀芥棩蹇楋紙skill 鍚堣瀹¤锛?                self._log_llm_review(round_id, st["llm"], ctx.llm_available)

            # t6 decide
            prop = self.engine.decide(ctx)
            st["proposal"] = prop
            summary["proposal"] = {"kind": prop.kind, "direction": prop.direction,
                                   "reasons": prop.reasons}
            summary["score"] = ev.result.score
            summary["sigma"] = ev.result.sigma
            # 鈿狅笍 action 蹇呴』**鍦ㄨ繖閲?*灏辫濂姐€?            #    鍘熷疄鐜板彧鍦?hold / skip_round / safe_hold 涓変釜鍒嗘敮閲岃祴鍊硷紝
            #    浜庢槸 place_grid / open_market / cancel_pending 杩欎簺
            #    **鐪熸涓嬪崟**鐨勮疆娆℃病鏈?action 鈫?鎺у埗鍙版墦鍗?`-> ?`銆?            #    缁撴灉鎭板ソ鏄細瓒婇噸瑕佺殑杞瓒婄湅涓嶅嚭鍙戠敓浜嗕粈涔堛€?            summary["action"] = prop.kind
            if prop.kind == "hold":
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
            # P0-1/P1-2/P1-3锛氭粴鍔ㄧ粺璁￠噺璺ㄨ繘绋嬫寔涔咃紙閲嶅惎涓嶄涪棰勭儹锛?            self.fusion.save_state()
            return summary
        except Mt5Error as e:
            log_error(f"第 {round_id} 轮：MT5 错误 {e}")
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
                # 璁板綍寮€浠撴椂鐨勮瀺鍚堝垎绗﹀彿锛屽钩浠撳悗鐢ㄤ簬璐濆彾鏂弽棣?                score = st.get("fused")
                s = float(score.result.score) if score is not None and getattr(score, "result", None) else 0.0
                # deal Feedback 闇€ position_id锛氭垚浜ゅ悗浠?positions 鏌ユ渶鏂颁粨
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
            # 淇濇姢鎬хЩ鎹燂細TP 淇濇寔鍘熶綅锛圢one = 涓嶅姩锛夛紝SL 鎺ㄥ埌閿佺泩浣嶏紙tp_struct 鎼哄甫鏂?SL锛?            req = OrderPlan(kind="modify_sltp", direction=plan.get("direction"),
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
            # 椤哄娍鍔犱粨锛氬浐瀹?0.01 鎵嬶紝鍚屽悜甯備环锛涙垚鍔熷悗璁℃暟+1銆佽褰曞垎鏁?缃俊/鍩虹宸€硷紙鎸囨暟闃舵锛?            req = OrderPlan(kind="open_market", direction=plan["direction"],
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
                # base_gap = 鏈鐩稿涓婃鍔犱粨鐨勫垎鏁板樊锛堢 3 娆¤捣浣滄寚鏁板闀垮熀鏁帮級
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
            # 琛屾儏鍙嶈浆鎾ゆ寕鍗曪紙docs/06 鐘舵€佹満锛歅ENDING_GRID 鈫?IDLE锛?            req = OrderPlan(kind="cancel_pending", position_ticket=int(plan["order_ticket"]),
                            comment="goldagent-cancel",
                            idempotency_key=f"cancel-{plan['order_ticket']}-{int(time.time())}")
            res = await self.executor.execute(req)
            if res.ok:
                trade_log({"event": "pending_cancelled", "ticket": plan["order_ticket"],
                           "direction": plan.get("direction")})
            return res
        if kind == "place_grid":
            # 閫愬眰鎸傚崟锛涙寕鍗曟垚鍔熷悗鎶婇娴嬬鍙疯鍏?_pred_orders锛堟垚浜も啋璐濆彾鏂弽棣堟ˉ鎺ワ級
            fused = st.get("fused")
            pred_sign = 0
            if fused is not None and getattr(fused, "result", None):
                s_ = float(fused.result.score)
                pred_sign = 1 if s_ > 0 else (-1 if s_ < 0 else 0)
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
                if last.order:
                    self._pred_orders[str(last.order)] = pred_sign
            self._save_pred_orders()
            return last
        return ExecutionResult(ok=True, error=f"noop kind {kind}")

    def _save_position_adds(self) -> None:
        path = CFG.state_path.parent / "position_adds.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._position_adds), encoding="utf-8")

    # ---------- P1-1锛氬喅绛栧懆鏈?ATR ----------
    def _decision_atr(self, st: GraphState) -> float | None:
        """SL/TP 鐢?*楂樼骇鍒紙榛樿 1h锛?*鐨?ATR锛岃€屼笉鏄叆鍦哄懆鏈燂紙1m锛夈€?
        鈿狅笍 杩欐槸 1m 鐭嚎鑳藉惁鎴愮珛鐨勫叧閿紝涓嶆槸鍙€夐」銆?
        research/23_kalman_tb.py 瀹炴祴锛?0,000 鏍圭湡瀹?1m bar锛夛細

            姝㈡崯鍩哄噯        姝㈡崯(USD)   鎴愭湰/姝㈡崯   鍑€NW-t
            1m ATR x1.2       1.13      46.0%     -30.00
            15m 灏哄害 x1.2     4.74      11.0%      -4.38
            1h ATR x1.2      20.80       2.5%      -1.40

        鎴愭湰 0.52 USD 鏄浐瀹氱殑銆傜敤 1m 鐨勬尝鍔ㄥ畾姝㈡崯鏃讹紝鎴愭湰鍚冩帀姝㈡崯鐨?46% 鈥斺€?        鏁板涓婁笉鍙兘鐩堝埄锛涚敤 1h ATR 瀹氭鎹燂紝鎴愭湰鍙崰 2.5%銆?
        **鎵€浠?1m 涓嶈兘浜ゆ槗"杩欎釜缁撹鍙湪"鐢?1m 娉㈠姩瀹氭鎹?鐨勫墠鎻愪笅鎴愮珛銆?*
        1m 璐熻矗**鍏ュ満鎷╂椂**锛堢簿搴﹂珮銆佹満浼氬锛夛紝楂樼骇鍒礋璐?*椋庨櫓灏哄害**锛堟垚鏈崰姣斾綆锛夈€?        """
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

    # ---------- LLM 璇勫鏃ュ織锛坰kill 鍚堣瀹¤锛?----------
    def _log_llm_review(self, round_id: int, llm: dict | None, available: bool) -> None:
        """璁板綍 LLM 鏄惁鍙備笌銆佷互鍙婂畠鎸?skill 璧颁簡鍝簺妫€鏌ラ」銆?""
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
            "review_coverage": (round(self.llm.review_coverage, 3)
                                if self.llm is not None else None),
        })

    def _save_pred_orders(self) -> None:
        path = CFG.state_path.parent / "pred_orders.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        # 鍙繚鐣欐渶杩?200 鏉★紙鎴愪氦鍙嶉鐢ㄥ畬鍗冲純锛?        items = list(self._pred_orders.items())[-200:]
        path.write_text(json.dumps(dict(items)), encoding="utf-8")

    def __post_init__(self) -> None:
        # 鍔犱粨璁℃暟璺ㄨ繘绋嬫寔涔?        try:
            path = CFG.state_path.parent / "position_adds.json"
            if path.exists():
                self._position_adds = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log_warn(f"加仓记录读取失败：{e}")
        # 鎸傚崟鈫掓垚浜ら娴嬬鍙锋ˉ鎺ユ寔涔?        try:
            path = CFG.state_path.parent / "pred_orders.json"
            if path.exists():
                self._pred_orders = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log_warn(f"预测挂单读取失败：{e}")
        # P0-1/P1-2/P1-3锛氭粴鍔ㄧ粺璁￠噺鎭㈠锛堥噸鍚笉涓㈤鐑紝鍚﹀垯姣忔閲嶅惎閮借绌轰粨绛夐鐑級
        try:
            self.fusion.load_state()
        except Exception as e:
            log_warn(f"融合状态读取失败：{e}")
        # 鈿狅笍 1m 鐭嚎鐨勫叧閿細鑻ュ綊涓€鍖栧櫒浠嶆湭棰勭儹锛堥娆″惎鍔?/ state 涓㈠け锛夛紝
        #    鐢ㄥ巻鍙?bar 鍥炴斁鐏屾弧缂撳啿銆傚惁鍒欏惎鍔ㄥ悗 min_periods 杞?        #    锛?m 涓?= 4 灏忔椂锛夋墍鏈夋簮鍒嗘暟閮芥槸 0.0 鈫?铻嶅悎鍒嗘亽 0 鈫?姘镐笉寮€浠撱€?        try:
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
        # XAUUSDm: 1 lot = 100oz; point=0.001 鈫?tick_value 宸叉槸姣?tick 姣?lot 缇庡厓
        return float(si.trade_tick_value) * (0.001 / max(si.trade_tick_size, 1e-9))

    async def close(self) -> None:
        await self.mobius.close()
        if self.llm and self.llm.client:
            await self.llm.client.close()
        self.client.shutdown()
