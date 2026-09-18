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
from gold_agent.risk.position import CircuitBreakers, position_lots, volatility_k
from gold_agent.risk.shrink import shrink_for_pending


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

    def evaluate(self, prop: Proposal, ev: FusedEvidence, account: AccountInfo,
                 positions: PositionsView, point_value_per_lot: float,
                 df_5m, atr: float | None, realized_vol: float | None,
                 win_rate: float | None = None) -> Approved:
        reasons = prop.reasons or []
        # ---------- 平仓/修改类直接放行（风控永不阻止离场） ----------
        if prop.kind in ("close_position", "modify_sltp"):
            return Approved(ok=True, plan={"kind": prop.kind,
                                           "direction": prop.direction,
                                           "position_ticket": prop.entry})
        if prop.kind == "hold":
            return Approved(ok=True, plan={"kind": "hold"})

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
            lots, rej = position_lots(account.equity, atr, point_value_per_lot,
                                      win_rate, vol_k=vol_k)
            if rej:
                decision_log({"event": "risk_reject", "kind": prop.kind,
                              "reason": rej, "win_rate": round(win_rate, 3)})
                return Approved(ok=False, reason=rej)
            sl_dist = CFG.risk.sl_atr_mult * atr
            tp_dist = CFG.risk.tp_atr_mult * atr
            entry = prop.entry   # 市价由 executor 取当前 bid/ask
            tp = entry + tp_dist if prop.direction == "LONG" else entry - tp_dist
            sl = entry - sl_dist if prop.direction == "LONG" else entry + sl_dist
            plan = {"kind": "open_market", "direction": prop.direction, "lots": lots,
                    "tp": round(tp, 3), "sl": round(sl, 3), "reasons": reasons}
            trade_log({
                "event": "risk_decision", "kind": prop.kind,
                "direction": prop.direction, "lots": lots,
                "entry_ref": round(entry, 3), "tp": plan["tp"], "sl": plan["sl"],
                "vol_k": round(vol_k, 3), "win_rate": round(win_rate, 3),
                "disagreement": r.disagreement, "score": round(r.score, 3),
                "reasons": reasons,
            })
            decision_log({"event": "risk_approve", "proposal": prop.__dict__, "plan": plan})
            return Approved(ok=True, plan=plan)

        if prop.kind == "place_grid":
            # 挂单：全部走 shrink_for_pending（docs/05 §3b）
            if atr is None:
                return Approved(ok=False, reason="no_atr")
            layers = []
            base_lots, rej = position_lots(account.equity, atr, point_value_per_lot, 0.5)
            if rej:
                return Approved(ok=False, reason=f"grid base: {rej}")
            for i in range(CFG.risk.grid_layers):
                gap = CFG.risk.grid_atr_mult * atr * (i + 1)
                level = prop.entry - gap if prop.direction == "LONG" else prop.entry + gap
                lots = round(base_lots * (CFG.risk.grid_layer_decay ** i), 2)
                if lots < 0.01:
                    break
                sh = shrink_for_pending(prop.direction, level, atr, df_5m,
                                        tp_raw=prop.tp_struct)
                layers.append({"level": sh["entry"], "lots": lots,
                               "tp": sh["tp"], "sl": sh["sl"],
                               "expiration_s": 4 * 3600})
            if not layers:
                return Approved(ok=False, reason="grid_layers_empty")
            total = sum(l["lots"] for l in layers)
            if total > CFG.risk.max_group_lots_mult * base_lots:
                return Approved(ok=False, reason="grid_exposure_cap")
            plan = {"kind": "place_grid", "direction": prop.direction,
                    "grid_plan": layers, "reasons": reasons}
            trade_log({"event": "risk_decision", "kind": "place_grid",
                       "direction": prop.direction, "score": round(r.score, 3),
                       "disagreement": r.disagreement, "layers": layers,
                       "reasons": reasons})
            decision_log({"event": "risk_approve_grid", "plan": plan})
            return Approved(ok=True, plan=plan)

        return Approved(ok=False, reason=f"unhandled kind {prop.kind}")
