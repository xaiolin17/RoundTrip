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
from gold_agent.common.symbols import get_profile
from gold_agent.common.logging_util import (decision_log, log_error, log_info,
                                            log_warn, trade_log)
from gold_agent.decision.machine import DecisionContext, DecisionEngine, Proposal
from gold_agent.fusion.engine import (MB_TF_WEIGHTS, FusionEngine,
                                      _mobius_score)
from gold_agent.fusion.weights import DECISION_SOURCES
from gold_agent.llm.orchestrator import Orchestrator
from gold_agent.mt5.client import MT5Client, Mt5Error
from gold_agent.mt5.executor import ExecutionResult, Executor, OrderPlan
from gold_agent.news.collector import Jin10Collector
from gold_agent.risk.gate import Approved, RiskGate
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
    deal_feedback: Any = None
    #: 本实例负责的品种（多品种时每品种一个 Graph 实例）。
    #: None = 用 `CFG.mt5.symbol`（单品种兼容，行为与改造前一致）。
    symbol: str | None = None
    #: 组合级风险闸（跨品种，多品种时由 runner 注入**同一个**实例）。
    #: None = 不做组合检查（单品种/测试场景）。
    portfolio: Any = None
    # {position_id / order_id: 预测符号} 成交→贝叶斯反馈桥接（落盘 pred_orders.json）
    # 键统一用 position_id：平仓 deal 的 order 是新 ticket，与开仓时记的永不相等
    _pred_orders: dict = field(default_factory=dict)
    _position_adds: dict = field(default_factory=dict)   # {position_ticket_str: 加仓次数}
    @classmethod
    def build(cls, symbol: str | None = None) -> "Graph":
        """构建一个品种的完整决策图。

        `symbol=None` -> 用 `CFG.mt5.symbol`（单品种兼容，与改造前一致）。
        多品种时为**每个品种**各建一个实例：各自的 Mobius 映射、新闻关键词、
        LLM 提示词品种名、状态目录、magic 全部独立。
        """
        CFG.ensure_dirs()
        prof = get_profile(symbol or CFG.mt5.symbol)
        sym = prof.broker_symbol
        sdir = CFG.state_path_for(sym)
        # ⚠️ 必须把品种传给 client：否则本类的 get_ohlcv/_positions_sync
        #    会退回配置里的默认品种，5 个 Graph 全部去拉黄金的行情与持仓
        #    （实测 5 品种收盘价完全相同、都是 4175.704）。
        client = MT5Client(symbol=sym)
        executor = Executor(client)
        mobius = MobiusClient()
        news = Jin10Collector(symbol=sym)
        fusion = FusionEngine(symbol=sym)
        breakers = CircuitBreakers.load(sdir / "breakers.json")
        orchestrator: Orchestrator | None = None
        try:
            from gold_agent.llm.client import RunningHubClient
            # 多品种：LLM 每小时预算按品种数**平分**（每品种一个独立池）。
            # 单品种时平分结果 == 原配置（60/24/24），行为不变。
            _caps = CFG.per_symbol_budgets(len(CFG.trade_symbols))
            orchestrator = Orchestrator(RunningHubClient(budgets=_caps), symbol=sym)
        except Exception as e:
            # LLM 缺 key 时禁用（本地降级路径照常决策），首次成功调用前重试初始化
            orchestrator = Orchestrator(None, symbol=sym)
            orchestrator._init_error = str(e)
        gate = RiskGate(breakers)
        engine = DecisionEngine(gate, orchestrator)
        fb = None
        try:
            from gold_agent.fusion.deal_feedback import DealFeedback
            fb = DealFeedback(fusion.bayes, breakers, state_dir=sdir,
                              magic=prof.magic, symbol=sym)
        except Exception as e:
            log_warn(f"交割单反馈初始化失败：{e}")
        return cls(client=client, executor=executor, mobius=mobius, news=news,
                   fusion=fusion, engine=engine, gate=gate, llm=orchestrator,
                   breakers=breakers, deal_feedback=fb, symbol=sym)

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
                # ⚠️ 必须传**真实净值**：原实现让熔断器拿自己的 peak_equity
                #    当输入喂回自己（自引用），峰值永远钉在 10000，
                #    真实净值 ~100,000 从未被学到；10-01 出金后净值跌到 100，
                #    回撤被算成 99% → 连续 23 轮风控误停机。
                closed = await self.deal_feedback.poll(
                    self.client, self._pred_orders,
                    account_equity=float(st["account"].equity))
                if closed:
                    # poll() 已把预测符号写进 rec["pred_sign"]（position_id 键桥接）
                    for d in closed:
                        pred_sign = d.get("pred_sign")
                        # ⚠️ 事故修复：actual 是**实际价格走势方向**，不是"盈利=方向对"。
                        #    原实现 `actual = 1 if pnl > 0 else -1`：做空单盈利时
                        #    pnl>0 → actual=+1，但价格实际**下跌**（方向=-1），
                        #    pred=-1 ≠ actual=+1 → 盈利做空单全被误判"未命中"。
                        #    实测最近 5 笔盈利做空单（+2.22/+9.04/+2.50/+4.36/+6.61）
                        #    全部被记成未命中 → 贝叶斯池 p 被压到 0.31 → 反向压分。
                        #    正确：actual = 持仓方向 × 盈亏符号
                        #    （做空盈利=价格下跌=-1；做多盈利=价格上涨=+1）
                        pnl = d.get("pnl", 0)
                        direction = d.get("direction") or 0
                        if pnl > 0:
                            actual = direction
                        elif pnl < 0:
                            actual = -direction
                        else:
                            actual = 0
                        if pred_sign in (1, -1) and actual != 0:
                            # ---- 按源调权重（用户选定方案）----
                            # 各源优先用**自己开仓时的分数符号**记账（src_preds）。
                            #
                            # 源名取自 fusion.weights.DECISION_SOURCES（单一出处），
                            # 不要硬编码：漏掉某个源 -> 它进了快照却永远不被记账。
                            #
                            # ⚠️ 快照为空 vs 快照缺键，语义完全不同，不能混为一谈：
                            #   · src_preds 为空 = **旧数据**（新格式上线前开仓，无 src 快照）
                            #     -> 退回融合分符号，保证历史记录也能记账、不丢数据。
                            #   · src_preds 非空但缺某源 = 该源**当轮没参与**（未验证/被
                            #     excluded/status=unavailable，gaussian.fuse 会把它整个
                            #     移出 per_source；news 更是只在 news_score!=0 时才加入）。
                            #     -> 必须跳过：它当轮没有方向判断，拿融合分顶替等于
                            #        把别的源的方向算到它头上，会污染它的命中率。
                            src_preds = d.get("src_preds") or {}
                            hit_map = {}
                            if src_preds:
                                # 新格式：各源用**自己**的符号，缺键即未参与 -> 跳过
                                preds = {s: src_preds.get(s) for s in DECISION_SOURCES}
                            else:
                                # 旧数据兜底：**只喂有 IR 权重的源**。
                                # ⚠️ 不能把 DECISION_SOURCES 整个喂进去：`news` 未验证、
                                #    IR 表权重为 0，但它一旦在本池攒够 min 样本，
                                #    `bayes.evidence()`（用的是池内权重，不是 IR 表权重）
                                #    就会开始给它产生证据 —— 那就违背了
                                #    weights.py 的硬规则"没有实测 IR 的源 = 0 权重"。
                                #    用融合分兜底时更要守这条：兜底填的是别人的方向。
                                preds = {s: pred_sign for s in DECISION_SOURCES
                                         if self.fusion.weights.weight(s) > 0}
                            for src, p_src in preds.items():
                                if p_src in (1, -1):
                                    self.fusion.bayes.record_outcome(src, p_src, actual)
                                    hit_map[src] = 1 if p_src == actual else 0
                            self.fusion.bayes.save()
                            trade_log({"event": "bayes_feedback", "position": d.get("position_id"),
                                       "pred": pred_sign, "actual": actual, "pnl": d.get("pnl"),
                                       "src_preds": src_preds, "src_hits": hit_map})
                            log_info(f"贝叶斯反馈: 仓位 {d.get('position_id')} "
                                     f"预测{'做多' if pred_sign > 0 else '做空'} "
                                     f"实际{'做多' if actual > 0 else '做空'} "
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
            #
            # ⚠️ mobius 抓取的周期**从 MB_TF_WEIGHTS 派生**，不再手写字典。
            #    事故：原先手写 4 个周期，漏了 4h，而 MB_TF_WEIGHTS 里
            #    `4h: 0.50` 占 23.8% 权重预算 —— 声明了却永远拿不到数据，
            #    醒来就是把「1h/4h 主导方向」悄悄降级成「1h 主导」。
            #    派生后权重表与抓取列表不可能再漂移。
            # ⚠️ 多品种：SMC 的 venue/symbol 与支持的周期都随品种变化。
            #    get_smc 内部按 (symbol, interval) 缓存，所以这里必须传
            #    **Mobius 侧**的符号（BTCUSDm -> BTCUSDT），不是券商符号。
            #    且各 venue 支持的周期差别极大（forex/commodity:futures 只有
            #    1h/1d），请求不支持的周期会返回 **400 而非降级**，
            #    所以必须按 `profile.smc_intervals` 裁剪。
            _prof = self.profile
            if _prof.has_smc:
                mob_tfs = _prof.smc_intervals(
                    tuple(tf for tf, w in MB_TF_WEIGHTS.items() if w > 0))
                mob_sym = _prof.mobius_symbol
            else:
                mob_tfs, mob_sym = (), None
                log_warn(f"{_prof.label} 无 SMC 数据源，本品种只融合缠论/本地指标")
            # ⚠️ 传入本品种名：`df` 来自各自的 bundle（数据本身已按品种隔离），
            #    但 symbol 会进缠论内部记录，传错会让日志/自检里出现别的品种名。
            cl_tasks = {tf: asyncio.to_thread(
                            analyze_tf, st["bundle"].frames[tf], tf,
                            _prof.mobius_symbol)
                        for tf in ("1m", "5m", "15m", "1h", "4h")}
            mob_tasks = {
                tf: asyncio.create_task(
                    self.mobius.get_smc(mob_sym, tf, limit=200,
                                        exchange=_prof.mobius_exchange,
                                        market=_prof.mobius_market))
                for tf in mob_tfs
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
                                 "observed": len(r.observed_signals),
                                 # ⚠️ 中枢边界必须落盘（原先这里被白名单丢掉）。
                                 #    用户反馈"单子经常挂在中枢中部"，但实测
                                 #    全量日志里 zg/zd 命中 0 次 —— 中枢**算了
                                 #    却没写**，导致事后无法回算是谁的问题。
                                 #    只写边界值，不写整条中枢列表（控制日志体积）。
                                 "center": (None if not r.center else {
                                     "zg": r.center.get("zg"),
                                     "zd": r.center.get("zd"),
                                     "gg": r.center.get("gg"),
                                     "dd": r.center.get("dd"),
                                     "id": r.center.get("id")})}
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
            # ⚠️ 门槛用 **z 尺度**（与 decision 层一致）：绝对阈值会让
            #    "要不要叫 LLM"的频率随权重漂移。留 0.6 的绝对余量
            #    作为"提前叫"的缓冲，同样换算成 z。
            _sig_l = float(ev.result.sigma)
            _z_l = (abs(ev.result.score - ev.result.score_baseline) / _sig_l
                    if _sig_l > 1e-9 else 0.0)
            need_llm = (_z_l >= CFG.decision.z_min - 0.6
                        or bool(st["positions"].positions)
                        or bool(st["positions"].pending_orders)
                        or abs(ev.result.score_baseline) > 0.3)
            ctx = DecisionContext(ev=ev, positions=st["positions"], news=st["news"],
                                  llm=None, last_close=summary["last_close"],
                                  atr=atr, realized_vol=st["fused"].indicators.realized_vol_daily
                                  if st["fused"].indicators else None,
                                  round_id=round_id,
                                  position_adds=self._position_adds,
                                  point_value_per_lot=self._point_value(),
                                  used_lots=self._used_lots(st["positions"]),
                                  max_lots_cap=self._max_lots_cap(st["account"]),
                                  profile=self.profile)
            if need_llm and self.llm is not None:
                st["llm"] = await self.llm.review_and_news(ev, st["news"],
                                                           summary["last_close"])
                ctx.llm = st["llm"]
                ctx.llm_available = bool((st["llm"] or {}).get("review"))
                # ⚠️ 这里**曾经**把 LLM 的新闻情绪当成方向分再融合一次：
                #     na = ...; ns = {"bullish": 1.5, "bearish": -1.5}.get(...)
                #     if ns: st["fused"] = fuse_all(..., news_score=ns)
                # 实测（7874 轮 + 定向实验）这是**纯空操作**：
                #     news 的 IR 权重 = 0 -> gaussian.fuse 把它标 excluded
                #     并排除出加权，融合分一字不变。
                #     实验：news_score 0 → +1.5 → -1.5，融合分恒为 +1.438195。
                # 代价却是每轮多跑一次完整 fuse_all（含 Kalman/Hurst 重算）。
                # 现在 news 改走「独立证据」通道（decision 层事件闸 +
                # risk 层手数降级），不再假装它能影响方向，故删除该重融合。
                self._log_llm_review(round_id, st["llm"], ctx.llm_available)

            # t6 decide
            prop = self.engine.decide(ctx)
            st["proposal"] = prop
            summary["proposal"] = {"kind": prop.kind, "direction": prop.direction,
                                   "reasons": prop.reasons}
            summary["score"] = ev.result.score
            summary["sigma"] = ev.result.sigma
            # 控制台要打**实测真的会动**的量，而不是恒定的标准差：
            #   · vol_percentile：波动率滚动分位（959 个取值，sd=0.31）
            #   · regime        ：Hurst 判定的行情（3 态，按天迁移）
            #   · disagreement  ：源间方向分歧（会触发手数 ×0.5）
            #   · per_source    ：逐源分数/权重（"这轮预测有多可信"的真实来源）
            # ⚠️ effective_weight / n_sources 实测是常数（4.1735 / 恒 3），
            #    刻意不打 —— 见 runner._format_summary 的说明。
            summary["vol_percentile"] = ev.result.vol_percentile
            summary["regime"] = ev.result.regime
            summary["disagreement"] = ev.result.disagreement
            summary["per_source"] = ev.result.per_source
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
                         tp_struct=prop.tp_struct, new_tp=prop.new_tp,
                         reasons=prop.reasons, evidence_ids=[]),
                ev, st["account"], st["positions"],
                point_value_per_lot=self._point_value(),
                df_5m=st["bundle"].frames["5m"], atr=atr,
                realized_vol=st["fused"].indicators.realized_vol_daily
                if st["fused"].indicators else None,
                win_rate=wr,
                position_adds=self._position_adds,
                llm_review=_rev,
                # 自研回调检测需要小周期 K 线（缠论代理在小周期上不准）
                frames=st["bundle"].frames,
                point=self.profile.point,
                magic=self.profile.magic)
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

            # ---- t7b 加仓复核：算好的加仓点位再让 LLM 评判一次 ----
            # 用户原话（2026-10-08）：
            #   > 要注意计算了新的加仓位置和止盈止损点 让大模型再评判
            #   > 这个单子是否还值得加仓 如果被否决就不加仓了
            # ⚠️ 必须在**执行之前**，且只对 add_layer 生效（用户选定：
            #    首仓/挂单不受影响）。LLM 不可用时**不加仓**（用户选定：
            #    严格，宁可不加）—— 故障不得当成 approve。
            if (approved.plan or {}).get("kind") == "add_layer" \
                    and CFG.risk.add_llm_review:
                rev_ok, rev_info = await self._review_add_layer(
                    approved.plan, st, ev, summary["last_close"])
                summary["add_review"] = rev_info
                if not rev_ok:
                    trade_log({"event": "risk_reject", "round": round_id,
                               "kind": "add_layer",
                               "reason": f"add_review: {rev_info.get('reason')}",
                               "proposal": prop.__dict__})
                    return summary

            # ---- t7c 组合级风险闸（多品种）----
            # ⚠️ 逐品种风控**结构上无法**覆盖组合风险。最关键的一条：
            #    各品种的 CircuitBreakers 只看自己的盈亏序列，
            #    组合整体回撤 12% 时若各品种各自都没到线，就**无人熔断**。
            #    另有风险预算倍数放大（5 品种 × 0.5% = 2.5%）与保证金集中。
            # 单品种时 `PortfolioRisk.check_for` 直接放行（空操作），
            # 所以黄金实盘行为不变。
            if self.portfolio is not None and (approved.plan or {}).get("kind") \
                    in ("open_market", "place_grid"):
                _verdict = self._portfolio_check(approved.plan, st, prop.direction)
                if not _verdict.ok:
                    summary["risk"] = {"ok": False,
                                       "reason": _verdict.reason,
                                       "plan": approved.plan}
                    trade_log({"event": "risk_reject", "round": round_id,
                               "kind": prop.kind,
                               "reason": f"portfolio: {_verdict.reason}",
                               "proposal": prop.__dict__})
                    return summary
                if _verdict.lot_mult < 1.0:
                    # 按组合预算缩手数（信号本身有效，只是总风险超额）
                    _p = approved.plan
                    _p["lots"] = round(float(_p.get("lots") or 0.0)
                                       * _verdict.lot_mult, 2)
                    summary["portfolio"] = {"lot_mult": _verdict.lot_mult,
                                            "reason": _verdict.reason}
                    trade_log({"event": "portfolio_scale", "round": round_id,
                               "lot_mult": _verdict.lot_mult,
                               "lots": _p["lots"], "reason": _verdict.reason})

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
            self.breakers.save(self.state_dir() / "breakers.json")
            self._prune_position_adds(st.get("positions"))
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

    async def _review_add_layer(self, plan: dict, st: GraphState,
                                ev, last_close: float) -> tuple[bool, dict]:
        """让 LLM 复核算好的加仓点位。返回 (是否放行, 复核信息)。

        用户原话（2026-10-08）：
        > 要注意计算了新的加仓位置和止盈止损点 让大模型再评判这个单子
        > 是否还值得加仓 如果被否决就不加仓了

        放行条件 = LLM 明确返回 `decision == "approve"`。
        其余情况（reject / 超时 / 接口 503 / 返回格式不对）一律**不加仓** ——
        用户选定"严格"：复核不了就不加，故障不得当成默认放行。
        """
        info: dict = {"decision": None, "reason": "", "confidence": None}
        if self.llm is None:
            info["reason"] = "LLM 不可用（未初始化）"
            return False, info
        lc = float(last_close or 0.0)
        if lc <= 0:
            # 现价缺失时无法给 LLM 判断"还剩多少空间"
            info["reason"] = "缺少现价，无法复核"
            return False, info
        # 该持仓的加仓进度（让 LLM 知道已经加了几层）
        tid = str(plan.get("position_ticket", ""))
        rec = (self._position_adds or {}).get(tid) or {}
        pos_ctx = {
            "adds_count": int(rec.get("count", 0)) if isinstance(rec, dict) else int(rec or 0),
            "max_adds": CFG.risk.max_adds_per_position,
            "price_open": plan.get("entry"),
        }
        try:
            res = await self.llm.review_add_layer(
                plan["direction"], float(plan["entry"]), float(plan["sl"]),
                float(plan["tp"]), float(plan.get("sl_dist") or 0.0),
                abs(float(plan["tp"]) - float(plan["entry"])), lc,
                ev=ev, position=pos_ctx)
        except Exception as e:
            info["reason"] = f"复核异常: {type(e).__name__}: {e}"
            log_warn(f"加仓复核异常，按用户选定策略不加仓: {e}")
            return False, info
        if not isinstance(res, dict):
            info["reason"] = "复核无结果（大模型不可用）"
            return False, info
        info.update({k: res.get(k) for k in ("decision", "confidence", "reason")})
        info["risk_flags"] = res.get("risk_flags") or []
        trade_log({"event": "add_review", "round": st.get("round_id"),
                   "plan": plan, "result": info})
        if res.get("decision") != "approve":
            return False, info
        return True, info

    async def _execute(self, plan: dict, st: GraphState) -> ExecutionResult:
        kind = plan.get("kind")
        # ⚠️ 幂等键**不能含挂钟时间**（`int(time.time())`）。
        #    原实现四个分支都拼了时间戳，于是每次调用都产生一个全新键，
        #    `Executor._seen_keys` 的查重**永不命中** —— 这个"幂等"机制
        #    实际上从未生效过。实测后果：撤单重复提交（38 次执行 / 35 个不同
        #    ticket），第二次必被 MT5 回 `10025 No changes`，而系统无法区分
        #    "已经撤掉了"和"第一次根本没发出去"（这正是风险最高的一类盲区）。
        #    改为**内容寻址**：同一轮内对同一标的的同一动作 → 同一个键。
        #    跨轮不重复是**有意**的：加仓/移损本来就需要在新价格上重新提交。
        _rid = st.get("round_id", 0)
        if kind == "open_market":
            si = self.client.symbol_info(self.symbol)
            if plan["direction"] == "LONG":
                entry = si.ask if si else None
            else:
                entry = si.bid if si else None
            req = OrderPlan(kind="open_market", direction=plan["direction"],
                            lots=plan["lots"], tp=plan["tp"], sl=plan["sl"],
                            comment="goldagent-open", symbol=self.symbol,
                            idempotency_key=f"open-{_rid}-{plan['direction']}")
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
                            comment="goldagent-close", symbol=self.symbol,
                            idempotency_key=f"close-{plan['position_ticket']}")
            return await self.executor.execute(req)
        if kind == "modify_sltp":
            # 保护性移损 / 信号转弱收窄：SL 与 TP 一起改（tp_struct 携带新 SL，
            # new_tp 携带新 TP；TP 未给则由风控从原持仓带出）
            # 幂等键带上**目标 SL 与 TP**：同一对值在同一轮内不会重复提交。
            # ⚠️ 必须同时含 TP：收窄场景下 SL 可能不变而只动 TP，若键里没有 TP，
            #    两次不同的止盈会被当成同一个动作而被幂等表吞掉。
            req = OrderPlan(kind="modify_sltp", direction=plan.get("direction"),
                            position_ticket=int(plan["position_ticket"]),
                            sl=float(plan["new_sl"]), tp=plan.get("keep_tp"),
                            comment="goldagent-lock", symbol=self.symbol,
                            idempotency_key=(f"lock-{plan['position_ticket']}"
                                             f"-{plan['new_sl']}-{plan.get('keep_tp')}"))
            res = await self.executor.execute(req)
            if res.ok:
                # 回读对账：broker 实际持有的 SL 才算数（原先只看返回码）
                want = float(plan["new_sl"])
                if not await self.executor.verify_sl(int(plan["position_ticket"]), want):
                    log_warn(f"移损对账失败：持仓 {plan['position_ticket']} "
                             f"目标 SL {want:.3f} 与 broker 实际值不一致")
                    trade_log({"event": "sl_verify_failed",
                               "position": plan["position_ticket"], "want_sl": want})
                else:
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
                            symbol=self.symbol,
                            idempotency_key=f"add-{plan['position_ticket']}-{st.get('round_id', 0)}")
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
                            comment="goldagent-cancel", symbol=self.symbol,
                            idempotency_key=f"cancel-{plan['order_ticket']}")
            res = await self.executor.execute(req)
            if res.ok:
                # 回读对账：确认挂单**真的不在册**了。
                # ⚠️ 原实现只在本地记一笔"已撤"就往前走。若撤单其实没生效，
                # 下一轮 `positions.pending_orders` 里那张单还在 → 决策层再次
                # 提议撤同一张（实测 38 次撤单执行只对应 35 个不同 ticket，
                # 3 次是重复撤同一张并拿到 10025）。
                still = await self.executor.verify_pending(int(plan["order_ticket"]))
                if still:
                    log_warn(f"撤单对账失败：挂单 {plan['order_ticket']} 仍在册")
                    trade_log({"event": "cancel_verify_failed",
                               "ticket": plan["order_ticket"]})
                else:
                    trade_log({"event": "pending_cancelled",
                               "ticket": plan["order_ticket"],
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
                                symbol=self.symbol,
                                # `level` 是价格不是身份：同一价位在**后续轮次**
                                # 重新挂单是合法意图（撤了又挂），所以键要带轮次，
                                # 只在**同一轮内**防重复提交。
                                idempotency_key=f"pending-{layer['level']}-{_rid}")
                last = await self.executor.execute(req)
                if not last.ok:
                    break
                if last.order:
                    self._record_pred(last, st)
            return last
        return ExecutionResult(ok=True, error=f"noop kind {kind}")

    def _prune_position_adds(self, positions) -> None:
        """删掉已平仓的加仓计数，只保留当前在场持仓的条目。

        ⚠️ **这是真实缺陷，不是洁癖**：`position_adds.json` 原先只增不减，
        实测已累积 85 个 ticket 而真实在场只有 1~2 个。
        危害在 **MT5 ticket 会回收**：若某个新仓位拿到一个旧 ticket，
        它会直接继承旧条目的 `count`（例如 3），于是
          · `adds_count < CFG.risk.max_adds_per_position` 一开始就被吃掉几次；
          · 第 3 次起门槛按 `base_gap × 2^(count−1)` 指数抬升，
            新仓会被要求一个**畸高的分数**才能加仓 —— 等于静默禁用了加仓。
        与 `machine._prune_closed`（清理浮盈/信号峰值）是同一个根因，
        这里补上持久化层面的对应处理。
        """
        live = {str(p.ticket) for p in (positions.positions if positions else [])}
        stale = [k for k in self._position_adds if k not in live]
        for k in stale:
            del self._position_adds[k]
        if stale:
            log_info(f"加仓计数清理：删除 {len(stale)} 个已平仓条目，"
                     f"保留 {len(self._position_adds)} 个在场持仓")

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

        ⚠️ 按源调权重（用户选定方案）：
        原实现只存融合分符号，平仓时 4 源喂同一个 pred_sign -> 4 源 stats
        永远相同 -> 权重永远相同，贝叶斯只是"整体信任度"。
        现在同时快照**各源自己开仓时的分数符号**（per_source），
        平仓时各源用**自己的预测方向**记账 -> 命中率独立 ->
        权重自动偏向表现好的源。
        值格式: {"fused": 融合分符号, "src": {源名: 该源分数符号(0=无方向)}}
        """
        fused = st.get("fused")
        s = 0.0
        per_source: list[dict] = []
        if fused is not None and getattr(fused, "result", None) is not None:
            s = float(fused.result.score)
            per_source = getattr(fused.result, "per_source", None) or []
        fused_sign = 1 if s > 0 else (-1 if s < 0 else 0)
        src_preds: dict[str, int] = {}
        for ps in per_source:
            name = ps.get("name")
            if not name:
                continue
            # 被排除的源（zero_weight / 未验证）不给方向 -> 符号 0 -> 不计入贝叶斯
            if ps.get("excluded"):
                src_preds[name] = 0
                continue
            try:
                sc = float(ps.get("score") or 0.0)
            except (TypeError, ValueError):
                sc = 0.0
            src_preds[name] = 1 if sc > 0 else (-1 if sc < 0 else 0)
        ticket = getattr(res, "order", 0) or 0
        if not ticket:
            log_warn("预测符号记录跳过：成交未返回 order ticket")
            return
        self._pred_orders[str(ticket)] = {"fused": fused_sign, "src": src_preds}
        self._save_pred_orders()

    def _save_pred_orders(self) -> None:
        path = self.state_dir() / "pred_orders.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        # 只保留最近 200 条（成交反馈用完即弃）
        items = list(self._pred_orders.items())[-200:]
        path.write_text(json.dumps(dict(items)), encoding="utf-8")

    def __post_init__(self) -> None:
        # 加仓计数跨进程持久
        try:
            path = self.state_dir() / "position_adds.json"
            if path.exists():
                self._position_adds = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log_warn(f"加仓记录读取失败：{e}")
        # 挂单→成交预测符号桥接持久
        try:
            path = self.state_dir() / "pred_orders.json"
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

    def _portfolio_check(self, plan: dict, st: GraphState,
                         this_direction: str | None = None):
        """构造组合快照并做组合级判定（多品种）。

        `this_direction`：**本笔要开的方向**，必须显式传入。

        ⚠️ 不能拿"该品种已有持仓的方向"当本笔方向 —— 正在开新仓时
        该品种还没有持仓（方向为 None），同向集中闸会在**最需要它的
        时刻**静默失效。初版就是犯了这个错（测试当场抓住：
        3 个品种已做多，第 4 个再做多仍被放行）。

        ⚠️ 单品种时 `PortfolioRisk.check_for` 内部直接放行 —— 本方法
        仍会被调用，但结果恒为 ok（不改变黄金实盘行为）。
        """
        from gold_agent.risk.portfolio import PortfolioState

        sym = self.symbol or CFG.mt5.symbol

        # 本实例只按 magic 看得到**自己**的持仓；其它品种的方向由
        # 共享的 `PortfolioRisk.directions` 登记表提供（各品种每轮上报）。
        # 所以这里必须**先上报自己、再读全局**，否则自己永远是 None。
        mine = None
        for p in st["positions"].positions:
            if p.magic == self.profile.magic:
                mine = "LONG" if int(getattr(p, "type", 0)) == 0 else "SHORT"
                break
        self.portfolio.report_direction(sym, mine)
        dirs = self.portfolio.direction_map()

        account = st["account"]
        equity = float(getattr(account, "equity", 0.0) or 0.0)
        # 组合纯交易盈亏：用净值 − 净出入金（与 CircuitBreakers 同口径）
        pnl_now = equity - float(getattr(self.breakers, "net_deposits", 0.0) or 0.0)
        self.portfolio.update_pnl(pnl_now)

        # 已持仓品种的风险预算（**不含本笔**，本笔由 check_for 的
        # this_risk 单独给 —— 否则同一品种旧仓与本笔会被重复计入）。
        risk_now = {s: self.profile.risk_pct
                    for s, d in dirs.items() if d and s != sym}
        pstate = PortfolioState(
            risk_by_symbol=risk_now,
            direction_by_symbol=dirs,
            margin_by_symbol={},
            equity=equity, pnl_now=pnl_now)
        # 本笔风险：单品种单笔预算（满额近似，保守方向）
        return self.portfolio.check_for(sym, self.profile.risk_pct, pstate,
                                        this_direction=this_direction)

    def _used_lots(self, positions) -> float:
        """本品种当前**已用**总手数（加仓额度判定用）。

        ⚠️ 必须按本品种 magic 过滤。多品种共用 magic 时会把所有品种的
        持仓手数加在一起，加仓额度判定全错（A 品种占了 B 品种的额度）。
        """
        _m = self.profile.magic
        try:
            return sum(float(p.volume) for p in positions.positions
                       if p.magic == _m)
        except Exception:
            return 0.0

    def _max_lots_cap(self, account) -> float:
        """**总敞口**上限（加仓额度判定用）。

        ⚠️ 必须与 `RiskGate.add_layer` 里的 `room = CFG.max_lot − my_lots`
        用**同一个口径**。决策层若按别的口径算（例如按 broker 的单笔上限
        `volume_max=200`），就会持续提出风控必然拒掉的加仓 ——
        两处口径不一致正是实测 259 次"总手数上限"拒绝的成因。
        """
        return float(CFG.max_lot)

    def _point_value(self, symbol: str | None = None) -> float:
        """每手每 **point** 的美元值（与 `SymbolProfile.point` 配套）。

        ⚠️ 必须与 `position_lots` 里的 `sl_points = sl_dist / point` 及
        `machine._point(ctx)` **同源**。历史上三处各自硬编码 0.001，
        乘起来正好自消（实测 5 品种下 per_lot_risk 与正确公式一致）——
        那是**脆弱的巧合**：任何一处单独改成按 point 计算，
        立刻产生成百倍的手数误差（EURUSDm 是 100 倍）。
        """
        sym = symbol or self.symbol or CFG.mt5.symbol
        try:
            point = get_profile(sym).point
        except KeyError:
            point = 0.001          # 未注册品种退回旧默认（单品种兼容）
        si = self._symbol_info(sym)
        if si is None:
            return 1.0
        return float(si.trade_tick_value) * (point / max(si.trade_tick_size, 1e-9))

    def _symbol_info(self, symbol: str | None = None):
        """按品种取 symbol_info（多品种下单定位用）。"""
        sym = symbol or self.symbol or CFG.mt5.symbol
        try:
            return self.client.symbol_info(sym)
        except TypeError:
            # 旧签名（无参数）
            return self.client.symbol_info()

    @property
    def profile(self):
        """本实例的品种档案。"""
        return get_profile(self.symbol or CFG.mt5.symbol)

    def state_dir(self):
        """本品种的**隔离**状态目录（多品种下每品种一份统计状态）。"""
        return CFG.state_path_for(self.symbol or CFG.mt5.symbol)

    async def close(self) -> None:
        await self.mobius.close()
        if self.llm and self.llm.client:
            await self.llm.client.close()
        self.client.shutdown()
