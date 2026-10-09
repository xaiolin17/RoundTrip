"""风控门：从 ActionProposal 到 ApprovedOrder（docs/05 + 06 §propose→risk）。

这是唯一能放行真实下单的模块。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import decision_log, trade_log
from gold_agent.common.zh import sentiment_label
from gold_agent.fusion.engine import FusedEvidence
from gold_agent.mt5.client import AccountInfo, PositionsView
from gold_agent.risk.levels import trade_levels
from gold_agent.risk.position import CircuitBreakers, position_lots, volatility_k
from gold_agent.risk.structure import pullback_entry


@dataclass
class Proposal:
    kind: str                      # open_market | place_grid | add_layer | close_position | modify_sltp | hold
    direction: str | None = None
    entry: float | None = None     # 市价 None；挂单给定
    tp_struct: float | None = None # 结构位 TP（可空）
    #: `modify_sltp` 专用的**新止盈**。
    #: ⚠️ 命名说明：`tp_struct` 在 `modify_sltp` 语境下承载的是**新止损**
    #: （历史原因，见 gate 的 modify 分支）。两者必须分开，否则"同时收窄
    #: 止损与止盈"无处表达。为 None 表示**保持原止盈不动**。
    new_tp: float | None = None
    reasons: list[str] | None = None
    evidence_ids: list[str] | None = None


@dataclass
class Approved:
    ok: bool
    reason: str = ""
    plan: dict | None = None       # {kind, direction, lots, entry, tp, sl, grid_plan}


def _news_impact(llm_review: dict | None) -> tuple[float, str]:
    """从 LLM 评审结果里取新闻影响度与情绪。

    返回 `(impact, sentiment)`；缺失时 `(0.0, "")`。

    ⚠️ news **不参与方向投票**（无实测 IR → 0 权重，见 `fusion/weights.py`
    硬规则）。它只按 LLM 给出的事件影响度调整**仓位大小**：
    影响度 >= `news_impact_reduce` → 手数降级；
    >= `news_impact_block` → 已在 `decision.machine` 直接 hold（不开新仓）。
    """
    na = (llm_review or {}).get("news_assessment") or {}
    try:
        imp = float(na.get("impact") or 0.0)
    except (TypeError, ValueError):
        imp = 0.0
    return max(0.0, min(1.0, imp)), str(na.get("sentiment") or "")


class RiskGate:
    def __init__(self, breakers: CircuitBreakers) -> None:
        self.breakers = breakers

    @staticmethod
    def _current_price(frames, df_5m=None) -> float | None:
        """取**当前市价**（最新 1m 收盘），供加仓定价用。

        优先 1m（与 `open_market` 的 `ctx.last_close` 同源，口径一致），
        其次 5m，都拿不到返回 None 由调用方降级。
        加仓是市价成交，用**当前价**算止损止盈才与真实成交价一致；
        用首仓的 `price_open` 会让赔率校验失真（见 `add_layer` 分支注释）。
        """
        for df in ((frames or {}).get("1m"), df_5m):
            if df is None:
                continue
            try:
                if len(df) == 0:
                    continue
                px = float(df["close"].iloc[-1])
            except Exception:
                continue
            if px > 0:
                return px
        return None

    def _levels(self, direction: str, entry: float, ev, atr: float | None,
                llm_review: dict | None = None,
                sl_from_tp: bool = False):
        """按 LLM 判断的压力位/支撑位算止损止盈（用户要求的正确语义）。

        ⚠️ 概念纠正：0.618 回调位是**入场点**，不是止损。
        止损止盈看**压力位/支撑位** —— 由 LLM 读 skill 输出判断，
        本地只做配套计算（方向/最小距离/盈亏比校验）。

        `sl_from_tp=True` 走**加仓专用**路径：先定止盈、缩 58%、
        再按 min_rr 反推止损（用户 2026-10-08 指定）。首仓/挂单不受影响。
        """
        return trade_levels(direction, entry, llm_review, ev, atr,
                            tp_shrink=CFG.risk.add_tp_shrink if sl_from_tp else 1.0,
                            sl_from_tp=sl_from_tp)

    def evaluate(self, prop: Proposal, ev: FusedEvidence, account: AccountInfo,
                 positions: PositionsView, point_value_per_lot: float,
                 df_5m, atr: float | None, realized_vol: float | None,
                 win_rate: float | None = None,
                 position_adds: dict | None = None,
                 llm_review: dict | None = None,
                 frames: dict | None = None,
                 point: float = 0.001,
                 magic: int | None = None) -> Approved:
        """`point`：该品种的最小价格变动单位（`SymbolProfile.point`）。

        ⚠️ 必须与 `point_value_per_lot` 同源。默认 0.001 保持 XAUUSDm
        行为不变；多品种下由调用方传入实际值（见 `position_lots` docstring
        关于"两处必须一起改"的说明）。

        `magic`：该品种的 magic。持仓/挂单过滤**必须**按它 —— 全仓库原先
        只按 `CFG.mt5.magic` 过滤、没有任何一处按 symbol 过滤，多品种共用
        magic 会让每个品种认领别人的持仓。默认 None = `CFG.mt5.magic`。
        """
        magic = int(magic if magic is not None else CFG.mt5.magic)
        reasons = prop.reasons or []
        # ---------- 平仓/修改类直接放行（风控永不阻止离场） ----------
        if prop.kind == "modify_sltp":
            # 锁盈移损：把新 SL 放进 plan（executor 消费 new_sl）
            # ⚠️ 必须带上原持仓的 TP：TRADE_ACTION_SLTP 是**整体覆盖**，
            # tp 传 0.0 等于把止盈删掉（且 MT5 会因此报 Invalid stops）。
            #
            # ⚠️ 改单**永不受 `min_rr` 约束**（用户 2026-09-30 明确要求：
            #    「新止损止盈缩小时不受 1.2 倍的比例影响」）。
            #    收窄 SL/TP 是**降低**风险敞口，用开仓的赔率门去卡它在语义上
            #    就是错的；且本分支在 evaluate 里**早返回**，本来也到不了
            #    levels 的赔率校验。`new_tp` 为 None 时沿用原止盈。
            pos = next((p for p in positions.positions
                        if getattr(p, "ticket", None) == int(prop.entry)), None)
            if pos is None:
                return Approved(ok=False, reason=f"position {prop.entry} not found")
            return Approved(ok=True, plan={"kind": "modify_sltp",
                                           "direction": prop.direction,
                                           "position_ticket": prop.entry,
                                           "new_sl": prop.tp_struct,
                                           "keep_tp": (prop.new_tp
                                                       if prop.new_tp is not None
                                                       else pos.tp)})
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
        # --- 新闻高危窗口：原为硬编码 False，等于**永久禁用**这条熔断 ---
        # 实测：`high_risk_window=False` 写死后，`CircuitBreakers` 里
        # `news_high_risk_window` 分支从未触发过一次；配套的
        # `CFG.risk.news_blackout_min` 也成了无人读取的死配置。
        # 注释说「news 高危由 decision 传入 flags」，但 decision 层只把新闻
        # 影响度做成 hold/降手数（machine.py），并不回传任何熔断标志 ——
        # 也就是说这条熔断实际上被静默摘掉了，而不是"由别处接管"。
        # 现改为按配置驱动，默认仍为 false，保持行为不变，但**可被显式打开**。
        reject = self.breakers.check(account.equity, margin_used,
                                     high_risk_window=CFG.risk.news_high_risk_window)
        if reject:
            return Approved(ok=False, reason=f"circuit: {reject}")
        # ---------- 分歧加严 ----------
        if r.disagreement:
            reasons.append(f"disagreement: lots x{CFG.decision.disagreement_lot_mult}")

        if prop.kind == "open_market":
            vol_k = volatility_k(realized_vol, None)
            if r.disagreement:
                vol_k *= CFG.decision.disagreement_lot_mult
            # ---- 未校准模式：低置信度 → 小仓位 ----
            # `weights.py` 的 DL 收缩若给出 lambda < LAMBDA_CALIBRATED，
            # 说明当前样本分辨不出源的高下（等权先验）。这**不是**
            # 不开仓的理由（把统计功效不足做成开关，正是被修掉的缺陷），
            # 而是**降仓**的理由：置信度低 → 仓位小。
            # 该系数随 lambda 自动失效：数据足以排序后不再降仓。
            if getattr(ev, "uncalibrated", False):
                vol_k *= CFG.decision.uncalibrated_lot_mult
                reasons.append(
                    f"权重未校准（收缩系数 {ev.weight_lambda:.3f}）"
                    f" -> lots x{CFG.decision.uncalibrated_lot_mult}")
            # ---- news「独立证据」通道：重大事件 → 手数降级 ----
            # news 不影响方向（无实测 IR，不投票），只按 LLM 给出的
            # 事件影响度收缩仓位。影响度更高的档位已在 decision 层直接 hold。
            na_imp, na_senti = _news_impact(llm_review)
            if na_imp >= CFG.decision.news_impact_reduce:
                vol_k *= CFG.decision.news_impact_lot_mult
                reasons.append(
                    f"新闻事件影响度 {na_imp:.2f}（{sentiment_label(na_senti)}）"
                    f" -> lots x{CFG.decision.news_impact_lot_mult}")
            win_rate = (win_rate if win_rate is not None
                        else CFG.risk.cold_start_win_rate)   # 冷启动先验胜率（可配）
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
            # ---- 紧贴反向位：**降仓**而非硬拒（用户选定）----
            # 实证不支持硬拦（research/26_conflict_gate_test.py）：
            # 贴脸组与对照组远期收益无统计差异；而原实现把 205 个强信号
            # （|z|>=2.66）100% 挡掉。改为按 conflict_lot_mult 降仓。
            # `CFG.risk.conflict_lot_mult = 0.0` 即恢复原硬拒行为。
            if lv.conflict_side:
                if CFG.risk.conflict_lot_mult <= 0:
                    decision_log({"event": "risk_reject", "kind": prop.kind,
                                  "reason": "fusion_vs_levels_conflict",
                                  "levels_notes": lv.notes})
                    return Approved(ok=False, reason="levels: fusion_vs_levels_conflict")
                vol_k *= CFG.risk.conflict_lot_mult
                reasons.append(
                    f"紧贴{('压力' if lv.conflict_side == 'resistance' else '支撑')}位"
                    f" {lv.conflict_level:.3f}（距 {lv.conflict_dist:.3f}）"
                    f" -> lots x{CFG.risk.conflict_lot_mult}")
            # 仓位按**实际**止损距离反推，锁死单笔 risk_pct 风险；
            # 同时为后续加仓预留额度（否则首仓吃满总上限 → 加仓永久不可达）
            reserve = CFG.add_layer_lots * CFG.risk.max_adds_per_position
            lots, rej = position_lots(account.equity, atr, point_value_per_lot,
                                      win_rate, vol_k=vol_k, sl_dist=lv.sl_dist or None,
                                      reserve_lots=reserve, point=point)
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
            my_lots = sum(p.volume for p in positions.positions
                          if p.magic == magic)
            # --- 加仓手数：原为硬编码 0.01，且上限判定也用同一个字面量 ---
            # 实测问题（153 次 `max_lot cap` 全部来自这里）：
            # `max_adds_per_position = 5` 声明允许加 5 层，但每层固定 0.01、
            # 上限 `MAX_LOT = 0.06`，于是第 6 层起必然 `my_lots+0.01 > 0.06`。
            # 实际成功加仓 106 次，add_no 最高只到 3，**4/5 两层永远不可达**；
            # 09-29 当天 109 次判定全部失败、0 次成功 —— 加仓路径沦为
            # 每轮空转并消耗一次决策。
            # 改为按**剩余额度**推导本次可加手数：只有剩余确实不足
            # 最小手数时才算"加无可加"（真正的资金上限），而不是固定拿 0.01
            # 去比。这样 add_no 的 5 层阶梯重新可达。
            room = CFG.max_lot - my_lots
            add_lots = round(min(CFG.add_layer_lots, room), 2)
            if add_lots < CFG.min_lot:
                return Approved(
                    ok=False,
                    reason=f"max_lot cap: 已用 {my_lots:.2f} 上限 {CFG.max_lot} "
                           f"剩余 {room:.2f} < 最小手数 {CFG.min_lot}")
            # ⚠️ 加仓必须自带 SL/TP。
            # 原实现 plan 里没有 tp/sl，executor 用 `plan.tp or 0.0` →
            # 加仓仓位开出来就是 SL=0 TP=0 的**裸仓**（实测 3 个裸仓全来自加仓）。
            # MT5 对冲账户下加仓是独立持仓，"沿用原持仓"在物理上不存在。
            # 定价改用缠论结构（与 open_market 同一套）。
            pos = next((p for p in positions.positions
                        if getattr(p, "ticket", None) == int(prop.entry)), None)
            # ⚠️ 定价锚点必须是**当前市价**，不是首仓的 `price_open`。
            #
            # 事故（2026-10-08 用户发现「止盈和止损点位差距这么大 盈亏比都拉成
            # 什么比列了」）：原实现 `ref = pos.price_open` —— 拿**第一笔**的
            # 入场价给加仓定价。但 MT5 对冲账户下加仓是**独立新持仓**，成交在
            # **当时市价**，两者可以差很远（实测 293 笔加仓：差中位 3.13、
            # 最大 36.06）。于是 `min_rr=1.2` 是在**错误的价格**上校验的：
            #     日志记录盈亏比中位 1.58、<1.2 的 0 笔
            #     按各自实际成交价重算   中位 1.23、<1.2 的 141 笔（48.1%）
            # 即赔率门在加仓路径上**形同虚设**。实测这批低赔率加仓确实亏钱：
            #     真实盈亏比 <1.2 共 136 笔 净 -136.26（每笔 -1.00）
            #     真实盈亏比 >=1.2 共 149 笔 净 +146.71（每笔 +0.98）
            # 现价取 1m 最新收盘（与 `open_market` 用的 `ctx.last_close` 同源，
            # 保证两个入口的赔率口径一致）；取不到再退 5m；再取不到才退回
            # `price_open`（旧行为，仅供无行情的单测/降级路径）。
            ref = self._current_price(frames, df_5m)
            if ref is None:
                ref = pos.price_open if pos is not None else prop.entry
            lv = self._levels(prop.direction, ref, ev, atr, llm_review,
                              sl_from_tp=True)
            if not lv.ok and not CFG.risk.allow_trade_without_llm_levels:
                return Approved(ok=False, reason=f"levels: {lv.reason}")
            plan = {"kind": "add_layer", "direction": prop.direction,
                    "lots": add_lots, "position_ticket": prop.entry,
                    "entry": round(ref, 3),
                    "tp": lv.tp, "sl": lv.sl, "reasons": reasons,
                    "sl_source": lv.sl_source, "tp_source": lv.tp_source,
                    "sl_dist": lv.sl_dist, "tp_dist": lv.tp_dist}
            trade_log({"event": "risk_decision", "kind": "add_layer",
                       "direction": prop.direction, "lots": add_lots,
                       "position": position_id, "score": round(r.score, 3),
                       "entry_ref": plan["entry"], "tp": plan["tp"], "sl": plan["sl"],
                       "sl_source": lv.sl_source, "tp_source": lv.tp_source,
                       "sl_dist": lv.sl_dist, "tp_dist": lv.tp_dist,
                       # 实际盈亏比（止盈距离/止损距离）。加仓按用户 2026-10-08
                       # 的新语义恒等于 min_rr，记下来便于事后核对。
                       "rr": (round(lv.tp_dist / lv.sl_dist, 4)
                              if lv.sl_dist else None),
                       "notes": lv.notes,
                       "reasons": reasons})
            return Approved(ok=True, plan=plan)

        if prop.kind == "place_grid":
            # 单张限价挂单（用户要求：取消网格，只挂预测的那一单）
            # ⚠️ 概念纠正：入场价 = **0.618 回调位**（回调到位、反弹概率大），
            #    不再是"收盘价回踩 0.8×ATR"。见 risk/structure.py。
            if atr is None:
                return Approved(ok=False, reason="no_atr")
            # 防重复：已有本策略挂单 → 不再放（决策层已拦，此处是第二道闸）
            my_pending = [o for o in positions.pending_orders if o.magic == magic]
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

            # 手数：与 open_market **用同一个 vol_k**（用户选定：统一风险尺度）。
            # 原实现漏传 vol_k -> 默认 1.0，于是同一个 20 点止损，
            # place_grid 开 0.03 手而 open_market 直接被拦，两边风险尺度不一致。
            vol_k_grid = volatility_k(realized_vol, None)
            if r.disagreement:
                vol_k_grid *= CFG.decision.disagreement_lot_mult
            # 未校准模式与 open_market 同口径（见上）：只降仓，不开/关闸。
            if getattr(ev, "uncalibrated", False):
                vol_k_grid *= CFG.decision.uncalibrated_lot_mult
                reasons.append(
                    f"权重未校准（收缩系数 {ev.weight_lambda:.3f}）"
                    f" -> lots x{CFG.decision.uncalibrated_lot_mult}")
            # ⚠️ 这里原为硬编码 `0.5`，**与 open_market 分支的口径不一致**：
            #    open_market 用真实交割单胜率（样本≥min_deals_for_kelly），
            #    挂单却恒用 0.5 —— 同一套 Kelly 仓位公式，两个入口给不同答案。
            #    现统一走 cold_start_win_rate（默认 0.5，行为不变，但可调）。
            win_rate_grid = (win_rate if win_rate is not None
                             else CFG.risk.cold_start_win_rate)
            base_lots, rej = position_lots(account.equity, atr, point_value_per_lot,
                                           win_rate_grid,
                                           vol_k=vol_k_grid, sl_dist=lv.sl_dist or None,
                                           point=point)
            if rej:
                return Approved(ok=False, reason=f"grid base: {rej}")
            order = {"level": pe.entry, "lots": base_lots,
                     "tp": lv.tp, "sl": lv.sl,
                     "expiration_s": int(CFG.risk.pending_expiry_h * 3600)}
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
