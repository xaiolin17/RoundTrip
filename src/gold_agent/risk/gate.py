"""风控门：从 ActionProposal 到 ApprovedOrder（docs/05 + 06 §propose→risk）。

这是唯一能放行真实下单的模块。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import decision_log, trade_log
from gold_agent.fusion.engine import FusedEvidence
from gold_agent.mt5.client import AccountInfo, PositionsView
from gold_agent.risk.grid import GridGroup, GridLayer, GridState
from gold_agent.risk.levels import trade_levels
from gold_agent.risk.position import CircuitBreakers, position_lots, volatility_k
from gold_agent.risk.structure import pullback_entry


@dataclass
class Proposal:
    kind: str                      # open_market | place_grid | add_layer | close_position | modify_sltp | hold
    direction: str | None = None
    entry: float | None = None     # 市价 None；挂单给定
    tp_struct: float | None = None # 结构位 TP（可空）
    reasons: list[str] | None = None
    evidence_ids: list[str] | None = None


@dataclass
class Approved:
    ok: bool
    reason: str = ""
    plan: dict | None = None       # {kind, direction, lots, entry, tp, sl, grid_plan}


class RiskGate:
    def __init__(self, breakers: CircuitBreakers, grid_state: GridState) -> None:
        self.breakers = breakers
        self.grid_state = grid_state

    def _levels(self, direction: str, entry: float, ev, atr: float | None,
                llm_review: dict | None = None):
        """按 LLM 判断的压力位/支撑位算止损止盈（用户要求的正确语义）。

        ⚠️ 概念纠正：0.618 回调位是**入场点**，不是止损。
        止损止盈看**压力位/支撑位** —— 由 LLM 读 skill 输出判断，
        本地只做配套计算（方向/最小距离/盈亏比校验）。
        """
        return trade_levels(direction, entry, llm_review, ev, atr)

    def evaluate(self, prop: Proposal, ev: FusedEvidence, account: AccountInfo,
                 positions: PositionsView, point_value_per_lot: float,
                 df_5m, atr: float | None, realized_vol: float | None,
                 win_rate: float | None = None,
                 position_adds: dict | None = None,
                 llm_review: dict | None = None,
                 frames: dict | None = None) -> Approved:
        reasons = prop.reasons or []
        # ---------- 平仓/修改类直接放行（风控永不阻止离场） ----------
        if prop.kind == "modify_sltp":
            # 锁盈移损：把新 SL 放进 plan（executor 消费 new_sl）
            # ⚠️ 必须带上原持仓的 TP：TRADE_ACTION_SLTP 是**整体覆盖**，
            # tp 传 0.0 等于把止盈删掉（且 MT5 会因此报 Invalid stops）。
            pos = next((p for p in positions.positions
                        if getattr(p, "ticket", None) == int(prop.entry)), None)
            if pos is None:
                return Approved(ok=False, reason=f"position {prop.entry} not found")
            return Approved(ok=True, plan={"kind": "modify_sltp",
                                           "direction": prop.direction,
                                           "position_ticket": prop.entry,
                                           "new_sl": prop.tp_struct,
                                           "keep_tp": pos.tp})
        if prop.kind == "hold":
            return Approved(ok=True, plan={"kind": "hold"})
        if prop.kind == "cancel_pending":
            # 撤单：风控直接放行（离场动作永不被拦，与平仓同级）
            return Approved(ok=True, plan={"kind": "cancel_pending",
                                           "order_ticket": prop.entry,
                                           "direction": prop.direction})
        if prop.kind == "close_position":
            # ⚠️ 必须带上手数：executor 的 TRADE_ACTION_DEAL 要求 volume 必填。
            # 原实现只传 position_ticket，volume 为 None →
            # MT5 返回 (-2, 'Invalid "volume" argument')，**平仓 100% 失败**。
            # 实测事故：连续 100+ 轮平仓全失败，信号翻空后仓位仍挂着。
            pos = next((p for p in positions.positions
                        if getattr(p, "ticket", None) == int(prop.entry)), None)
            if pos is None:
                return Approved(ok=False, reason=f"position {prop.entry} not found")
            return Approved(ok=True, plan={"kind": prop.kind,
                                           "direction": prop.direction,
                                           "position_ticket": prop.entry,
                                           "lots": pos.volume})

        r = ev.result
        # ---------- 熔断 ----------
        margin_used = (account.margin / max(account.equity, 1e-9))
        reject = self.breakers.check(account.equity, margin_used,
                                     high_risk_window=False)  # news 高危由 decision 传入 flags
        if reject:
            return Approved(ok=False, reason=f"circuit: {reject}")
        # ---------- 分歧加严 ----------
        if r.disagreement:
            reasons.append("disagreement: lots x0.5")

        if prop.kind == "open_market":
            vol_k = volatility_k(realized_vol, None)
            if r.disagreement:
                vol_k *= CFG.decision.disagreement_lot_mult
            win_rate = win_rate if win_rate is not None else 0.5   # 交割单胜率（样本≥10）；否则冷启动 0.5
            entry = prop.entry   # 市价由 executor 取当前 bid/ask
            # ---- 止损止盈看压力位/支撑位（LLM 判断 + 本地配套计算）----
            lv = self._levels(prop.direction, entry, ev, atr, llm_review)
            if not lv.ok:
                # 用户选定：LLM 没给出可用压力位 → **不开仓**，等 LLM 可用
                # （猜点位比不交易更危险）
                if not CFG.risk.allow_trade_without_llm_levels:
                    decision_log({"event": "risk_reject", "kind": prop.kind,
                                  "reason": lv.reason, "levels_notes": lv.notes})
                    return Approved(ok=False, reason=f"levels: {lv.reason}")
            # 仓位按**实际**止损距离反推，锁死单笔 risk_pct 风险
            lots, rej = position_lots(account.equity, atr, point_value_per_lot,
                                      win_rate, vol_k=vol_k, sl_dist=lv.sl_dist or None)
            if rej:
                decision_log({"event": "risk_reject", "kind": prop.kind,
                              "reason": rej, "win_rate": round(win_rate, 3)})
                return Approved(ok=False, reason=rej)
            plan = {"kind": "open_market", "direction": prop.direction, "lots": lots,
                    "tp": lv.tp, "sl": lv.sl, "reasons": reasons,
                    "sl_source": lv.sl_source, "tp_source": lv.tp_source,
                    "sl_dist": lv.sl_dist, "tp_dist": lv.tp_dist,
                    "level_notes": lv.notes}
            trade_log({
                "event": "risk_decision", "kind": prop.kind,
                "direction": prop.direction, "lots": lots,
                "entry_ref": round(entry, 3), "tp": plan["tp"], "sl": plan["sl"],
                "sl_source": lv.sl_source, "tp_source": lv.tp_source,
                "sl_dist": lv.sl_dist, "vol_k": round(vol_k, 3),
                "win_rate": round(win_rate, 3),
                "disagreement": r.disagreement, "score": round(r.score, 3),
                "reasons": reasons,
            })
            decision_log({"event": "risk_approve", "proposal": prop.__dict__, "plan": plan})
            return Approved(ok=True, plan=plan)

        if prop.kind == "add_layer":
            # 用户规则：加仓固定 0.01 手，每仓最多 5 次（风控硬顶，LLM 不可绕过）
            # 第二道闸：阶梯条件（分数+置信均须高于上次加仓）在决策层已查，此处防绕过
            if atr is None:
                return Approved(ok=False, reason="no_atr")
            position_id = str(prop.entry)   # entry 携带 position ticket
            adds = (position_adds or {})
            rec = adds.get(position_id) or {}
            adds_count = int(rec.get("count", 0)) if isinstance(rec, dict) else int(rec or 0)
            if adds_count >= CFG.risk.max_adds_per_position:
                return Approved(ok=False, reason=f"adds capped at {CFG.risk.max_adds_per_position}")
            my_lots = sum(p.volume for p in positions.positions if p.magic == CFG.mt5.magic)
            if my_lots + 0.01 > CFG.max_lot:
                return Approved(ok=False, reason=f"max_lot cap: {my_lots:.2f}+0.01 > {CFG.max_lot}")
            # ⚠️ 加仓必须自带 SL/TP。
            # 原实现 plan 里没有 tp/sl，executor 用 `plan.tp or 0.0` →
            # 加仓仓位开出来就是 SL=0 TP=0 的**裸仓**（实测 3 个裸仓全来自加仓）。
            # MT5 对冲账户下加仓是独立持仓，"沿用原持仓"在物理上不存在。
            # 定价改用缠论结构（与 open_market 同一套）。
            pos = next((p for p in positions.positions
                        if getattr(p, "ticket", None) == int(prop.entry)), None)
            ref = pos.price_open if pos is not None else prop.entry
            lv = self._levels(prop.direction, ref, ev, atr, llm_review)
            if not lv.ok and not CFG.risk.allow_trade_without_llm_levels:
                return Approved(ok=False, reason=f"levels: {lv.reason}")
            plan = {"kind": "add_layer", "direction": prop.direction,
                    "lots": 0.01, "position_ticket": prop.entry,
                    "entry": round(ref, 3),
                    "tp": lv.tp, "sl": lv.sl, "reasons": reasons,
                    "sl_source": lv.sl_source, "tp_source": lv.tp_source,
                    "sl_dist": lv.sl_dist}
            trade_log({"event": "risk_decision", "kind": "add_layer",
                       "direction": prop.direction, "lots": 0.01,
                       "position": position_id, "score": round(r.score, 3),
                       "entry_ref": plan["entry"], "tp": plan["tp"], "sl": plan["sl"],
                       "sl_source": lv.sl_source, "sl_dist": lv.sl_dist,
                       "reasons": reasons})
            return Approved(ok=True, plan=plan)

        if prop.kind == "place_grid":
            # 单张限价挂单（用户要求：取消网格，只挂预测的那一单）
            # ⚠️ 概念纠正：入场价 = **0.618 回调位**（回调到位、反弹概率大），
            #    不再是"收盘价回踩 0.8×ATR"。见 risk/structure.py。
            if atr is None:
                return Approved(ok=False, reason="no_atr")
            # 防重复：已有本策略挂单 → 不再放（决策层已拦，此处是第二道闸）
            my_pending = [o for o in positions.pending_orders if o.magic == CFG.mt5.magic]
            if my_pending:
                return Approved(ok=False, reason=f"pending x{len(my_pending)} already waiting")

            # ---- 入场：0.618 回调位（自研摆动检测，自适应小周期）----
            # 用户要求：非严格缠论要加上我们直接的处理；缠论只是第一层数据。
            # 实测缠论代理在 1m 图返回 15m 级别的段 -> 入场位偏远挂不上，
            # 所以这里用 frames 自己算摆动，挑离现价最近的周期。
            pe = pullback_entry(prop.direction, prop.entry,
                                getattr(ev, "chanlun", None), atr, frames)
            if not pe.ok:
                return Approved(ok=False, reason=f"pullback: {pe.reason}")
            if pe.state == "passed":
                # 已越过回调带（回调过深）→ 结构可能已破，不挂
                return Approved(ok=False,
                                reason=f"pullback passed band ({pe.band_far})")

            # ---- 止损止盈：LLM 判断的压力位/支撑位 ----
            lv = self._levels(prop.direction, pe.entry, ev, atr, llm_review)
            if not lv.ok and not CFG.risk.allow_trade_without_llm_levels:
                return Approved(ok=False, reason=f"levels: {lv.reason}")

            base_lots, rej = position_lots(account.equity, atr, point_value_per_lot, 0.5,
                                           sl_dist=lv.sl_dist or None)
            if rej:
                return Approved(ok=False, reason=f"grid base: {rej}")
            order = {"level": pe.entry, "lots": base_lots,
                     "tp": lv.tp, "sl": lv.sl,
                     "expiration_s": 4 * 3600}
            plan = {"kind": "place_grid", "direction": prop.direction,
                    "grid_plan": [order], "reasons": reasons,
                    "entry_source": pe.source or "pullback",
                    "pullback_tf": pe.tf, "pullback_k": pe.swing_k,
                    "band_near": pe.band_near, "band_far": pe.band_far,
                    "pullback_state": pe.state, "pullback_dist": pe.distance,
                    "sl_source": lv.sl_source, "tp_source": lv.tp_source,
                    "sl_dist": lv.sl_dist}
            trade_log({"event": "risk_decision", "kind": "place_grid",
                       "direction": prop.direction, "score": round(r.score, 3),
                       "disagreement": r.disagreement, "layers": [order],
                       "reasons": reasons})
            decision_log({"event": "risk_approve_grid", "plan": plan})
            return Approved(ok=True, plan=plan)

        return Approved(ok=False, reason=f"unhandled kind {prop.kind}")
