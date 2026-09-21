"""决策状态机（docs/06）。

状态: IDLE → PROPOSING → OPEN_LIVE/PENDING_GRID → HOLDING ⇄ GRID_LADDER/MARTIN_REVERSE
     → EXIT → IDLE；异常 → SAFE_HOLD。
LLM 只提供 verdict/confidence 作为证据；订单参数只出自 risk 模块。

research/18_COMMERCIAL_PLAN.md 的三项修正落在本模块：

- **P1-2 波动 regime 闸**：只在 σ 位于滚动高分位时开仓。这是唯一不依赖方向
  预测的杠杆（`12_levers.py` C1：毛边际 +171%，净 NW-t 改善 7 倍）。
- **P1-3 阈值零点校正**：融合分的零点不在 0（实测均值 +0.52）。阈值判断前先减去
  滚动基线 S0，否则 S=+0.52 的"中性"会被当成"偏多"。
- **P1-1 决策周期**：`exit_persist_rounds` 在 1h 周期下 = 2（一轮 = 3 小时）。

LLM 在主路径上（research/20 的修正）
-----------------------------------
`20_llm_audit.txt` 显示实盘 LLM review 覆盖率仅 **4.3%**（881 轮中 38 次），
后果是 30 次 place_grid vs 16 次 open_market —— 系统绝大多数时候只能挂限价单。
根因有三：① `min_interval_min=15` 节流 ② 预算被 news 挤占 ③ `|S|>=0.9` 前置条件。

修正后：LLM 评审在每轮决策（1h 周期）都执行，且 **LLM 缺失时不再默认放网格** ——
`allow_grid_without_llm=False` 时直接 hold，等 LLM 明确表态。这使 LLM 从
"罕见的加分项"变成"主路径的确认环节"，同时保留完整的降级路径。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import decision_log
from gold_agent.common.zh import direction_label, verdict_label
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
    #: LLM 是否真的被调用并返回了 review（用于区分"LLM 说中性"与"LLM 没参与"）
    llm_available: bool = False


def effective_score(s: float, baseline: float) -> float:
    """P1-3：融合分零点校正。S_eff = S − S0。"""
    return float(s) - float(baseline)


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
            # P1-3：所有阈值判定都用校正后的分数
            s_eff = effective_score(r.score, r.score_baseline)
            # ⚠️ **持仓管理优先于挂单**。
            #    原实现是 `if pending: ... elif not holding: ... else: holding`，
            #    于是只要还挂着网格单，`_decide_holding` 就**永远不会执行** ——
            #    止损、利润回吐平仓、顺势加仓全部被挂单挡住。
            #    实测：持仓 LONG 浮亏 −2.59，S_eff=−1.50 已越过
            #    exit_threshold=1.2 连续 12 轮，却一直显示
            #    "pending x1 waiting fill"，**该平的仓一直没平**。
            #    安全逻辑（止损）绝不能被"还在等成交"掩盖。
            if holding:
                prop = self._decide_holding(ctx, holding, s_eff, r.sigma)
                # 持仓不动时，仍要按行情撤掉方向不对的挂单
                if prop.kind == "hold" and pending:
                    cancel = self._pending_cancel(pending, s_eff, r.sigma)
                    if cancel is not None:
                        prop = cancel
            elif pending:
                cancel = self._pending_cancel(pending, s_eff, r.sigma)
                prop = cancel if cancel is not None else Proposal(
                    kind="hold", reasons=[f"已有 {len(pending)} 张挂单等待成交"])
            else:
                prop = self._decide_flat(ctx, s_eff, r.sigma)
        except Exception as e:
            decision_log({"event": "decision_error", "error": str(e),
                          "round": ctx.round_id})
            self.state = State.SAFE_HOLD
            return Proposal(kind="hold", reasons=[f"error: {e}"])
        self.state = State.PROPOSING if prop.kind != "hold" else State.IDLE
        if holding:
            self.state = State.HOLDING if prop.kind == "hold" else self.state
        decision_log({"event": "decision", "round": ctx.round_id,
                      "score": r.score, "score_baseline": r.score_baseline,
                      "score_eff": effective_score(r.score, r.score_baseline),
                      "sigma": r.sigma, "proposal": prop.__dict__})
        return prop

    # ---------- 挂单撤单 ----------
    def _pending_cancel(self, pending, s: float, sigma: float) -> Proposal | None:
        """行情对挂单不利 → 撤单；否则返回 None（继续等待成交）。

        用户要求：**行情不对要删除挂单**。

        ⚠️ 方向必须用 `OrderRow.type`（已由 `client._order_direction`
        映射成 LONG/SHORT）。原实现用 `"buy" in str(type).lower()` 猜，
        而当时 `type` 存的是整数码（"2"），恒为 False →
        **所有挂单都被当成 SHORT** → 一个做多挂单在 S_eff 为正（看涨）时
        反而被判为"不利"而撤掉，方向完全颠倒。
        """
        if not pending:
            return None
        pdir = pending[0].type
        if pdir not in ("LONG", "SHORT"):
            # 方向未知（CLOSE_BY 等）→ 保守起见不撤，交给上层
            return None
        adverse = (pdir == "LONG" and s <= -CFG.decision.exit_threshold) or \
                  (pdir == "SHORT" and s >= CFG.decision.exit_threshold)
        if adverse or sigma > CFG.fusion.sigma_max:
            why = (f"S_eff={s:+.2f} 标准差={sigma:.2f}"
                   if adverse else f"标准差={sigma:.2f}>{CFG.fusion.sigma_max}")
            return Proposal(kind="cancel_pending", direction=pdir,
                            entry=pending[0].ticket,
                            reasons=[f"挂单 {direction_label(pdir)} 转不利：{why}"])
        return None

    # ---------- 空仓 ----------
    def _decide_flat(self, ctx: DecisionContext, s: float, sigma: float) -> Proposal:
        """空仓开仓门。

        s 是**已做零点校正**的有效融合分（P1-3）。
        """
        thr = CFG.decision.open_threshold
        if sigma > CFG.fusion.sigma_max:
            return Proposal(kind="hold",
                            reasons=[f"标准差 {sigma:.2f} > 上限 {CFG.fusion.sigma_max}"])
        if ctx.news.high_risk_window:
            return Proposal(kind="hold", reasons=["新闻高危窗口"])

        # ---- P1-2 波动 regime 闸（唯一不依赖方向预测的杠杆）----
        vol_pct = getattr(ctx.ev.result, "vol_percentile", 0.5)
        if vol_pct < CFG.decision.vol_pct_min:
            return Proposal(kind="hold",
                            reasons=[f"低波动区间 {vol_pct:.2f} < {CFG.decision.vol_pct_min}"])

        if abs(s) < thr:
            return Proposal(kind="hold", reasons=[f"|S_eff| {abs(s):.2f} < 阈值 {thr}"])
        direction = "LONG" if s > 0 else "SHORT"

        # ---- LLM 一致性（主路径确认环节）----
        review = (ctx.llm or {}).get("review") or {}
        verdict = review.get("verdict")
        conf = float(review.get("confidence") or 0)
        want = "bullish" if direction == "LONG" else "bearish"
        aligned = (verdict == want) and conf >= CFG.decision.llm_align_conf
        opposed = (verdict is not None and verdict != "neutral" and verdict != want
                   and conf >= CFG.decision.llm_adverse_conf)
        reasons = [f"S_eff={s:+.2f} 标准差={sigma:.2f}",
                   f"波动分位={vol_pct:.2f}",
                   f"LLM={verdict_label(verdict)}/{conf:.2f} "
                   f"一致={'是' if aligned else '否'} 可用={'是' if ctx.llm_available else '否'}"]

        # LLM 明确反对且高置信 → 不开仓（这是 LLM 作为确认环节的实质权力）
        if opposed:
            return Proposal(kind="hold",
                            reasons=reasons + [f"LLM 反对 {verdict_label(verdict)}/{conf:.2f}"])

        if ctx.ev.result.regime == "mean_reverting":
            # 均值回归 regime → 只做网格限价
            return Proposal(kind="place_grid", direction=direction, entry=ctx.last_close,
                            reasons=reasons + ["行情为均值回归 -> 改用网格挂单"])
        if aligned:
            return Proposal(kind="open_market", direction=direction, reasons=reasons)
        # 未对齐：LLM 没参与 / 说中性 / 置信不足
        if not ctx.llm_available and not CFG.decision.allow_grid_without_llm:
            # LLM 缺失时不默认放网格（research/20 的教训：那会让系统几乎只挂单）
            return Proposal(kind="hold",
                            reasons=reasons + ["LLM 不可用 -> 观望（不默认放网格）"])
        # 先放网格限价（内侧挂单），等回踩
        return Proposal(kind="place_grid", direction=direction, entry=ctx.last_close,
                        reasons=reasons + ["LLM 未确认 -> 先挂网格"])

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
                       direction == "SHORT" and verdict == "bullish") and conf >= CFG.decision.llm_adverse_conf
        key = direction
        if adverse:
            self._exit_streak[key] = self._exit_streak.get(key, 0) + 1
        else:
            self._exit_streak[key] = 0
        if self._exit_streak.get(key, 0) >= CFG.decision.exit_persist_rounds:
            return Proposal(kind="close_position", direction=direction,
                            entry=pos.ticket,
                            reasons=[f"连续 {self._exit_streak[key]} 轮信号不利"])
        if adverse_llm:
            return Proposal(kind="close_position", direction=direction, entry=pos.ticket,
                            reasons=[f"LLM 反向 {verdict_label(verdict)}/{conf:.2f}"])
        # 顺势加仓（用户规则：每仓固定 0.01 手，同向最多加 5 次）
        # 阶梯式：分数与置信均须高于上一次；第 3 次起门槛指数递增
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
                            reasons=[f"加仓 第{adds_count + 1}/{CFG.risk.max_adds_per_position}次 "
                                     f"S_eff={s:+.2f} (需>={required:.2f} 上次={last_score}) "
                                     f"置信={conf_cur:.2f} (上次={last_conf})"])
        # ---- 超短期利润回吐检测（用户要求：识别到利润会回吐就主动平仓）----
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
            why = (f"利润回吐：峰值 ${self._profit_peak[key_pos]:.2f} -> ${cur_profit:.2f}"
                   if profit_giveback else
                   f"信号回吐：峰值 S={self._score_peak[key_pos]:+.2f} -> {same_dir_score:+.2f}")
            return Proposal(kind="close_position", direction=direction, entry=pos.ticket,
                            reasons=[why])
        # 新闻反向减仓
        na = (ctx.llm or {}).get("news_assessment") or {}
        if na.get("impact", 0) >= 0.8:
            na_dir = {"bullish": "LONG", "bearish": "SHORT", "neutral": None}.get(na.get("sentiment"))
            if na_dir and na_dir != direction:
                return Proposal(kind="close_position", direction=direction, entry=pos.ticket,
                                reasons=[f"新闻不利 影响={na['impact']}"])
        # 持有期检查
        age_h = (time.time() - pos.time) / 3600
        if age_h > CFG.risk.max_holding_h and pos.profit < 0:
            return Proposal(kind="close_position", direction=direction, entry=pos.ticket,
                            reasons=[f"持仓 {age_h:.1f} 小时且亏损"])
        # ---- 保护性移损（用户规则：利润 > $10 时，把 SL 推到盈利 $2 处，锁底搏上限）----
        point_value = getattr(ctx, "point_value_per_lot", 1.0) * pos.volume
        profit_locked_sl = (pos.price_open + 2.0 / max(point_value, 1e-9) if direction == "LONG"
                            else pos.price_open - 2.0 / max(point_value, 1e-9))
        sl_still_open = (pos.sl is not None and pos.sl > 0 and
                         ((direction == "LONG" and pos.sl < pos.price_open) or
                          (direction == "SHORT" and pos.sl > pos.price_open)))
        if pos.profit > 10.0 and sl_still_open:
            return Proposal(kind="modify_sltp", direction=direction, entry=pos.ticket,
                            tp_struct=profit_locked_sl, reasons=[
                                f"保本锁盈：利润 ${pos.profit:.2f} > $10，"
                                f"止损上移至 {profit_locked_sl:.3f}（锁定 $2）"])
        return Proposal(kind="hold",
                        reasons=[f"持仓 {direction_label(direction)} {age_h:.1f} 小时 "
                                 f"S_eff={s:+.2f}"])
