"""MT5 真实下单执行器（docs/01 §4）。

live 模式直接真实下单（用户确认）；风控门在 risk 模块，本层只负责
正确的请求构造、幂等、串行与成交对账。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import log_error, trade_log
from gold_agent.mt5.client import MT5Client, Mt5Error

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None


@dataclass
class OrderPlan:
    kind: str                 # open_market | close_position | modify_sltp | place_pending | cancel_pending
    direction: str | None = None   # LONG|SHORT
    lots: float | None = None
    entry: float | None = None     # pending price
    tp: float | None = None
    sl: float | None = None
    position_ticket: int | None = None
    expiration_s: int | None = None
    comment: str = "goldagent"
    idempotency_key: str = ""
    #: 下单品种。None = 用 `CFG.mt5.symbol`（单品种兼容，行为不变）。
    #: 多品种下必须显式带上 —— 否则所有品种的单都会发到默认品种上。
    symbol: str | None = None


@dataclass
class ExecutionResult:
    ok: bool
    retcode: int | None = None
    deal: int = 0
    order: int = 0
    price: float | None = None
    volume: float | None = None
    error: str = ""


_RETRYABLE = set()
#: `10025 TRADE_RETCODE_NO_CHANGES` —— 请求的目标状态**已经就是当前状态**。
#: 这不是失败，而是**幂等成功**：MT5 明确告诉我们"无需改动"。
#: 原实现把它和其他错误一起丢进 `order_rejected` 并返回 `ok=False`，
#: 于是：① 移损被记为失败（实测 375 次）；② 决策层下一轮看到目标 SL
#: 仍未生效，就再提一次，形成无限重试；③ 真正的失败（Invalid stops）
#: 被淹没在 375 条噪音里。归入成功是唯一语义正确的处理。
_IDEMPOTENT_OK = set()
if mt5 is not None:
    _RETRYABLE = {mt5.TRADE_RETCODE_REQUOTE, mt5.TRADE_RETCODE_PRICE_CHANGED,
                  mt5.TRADE_RETCODE_PRICE_OFF}
    _IDEMPOTENT_OK = {mt5.TRADE_RETCODE_NO_CHANGES}


class Executor:
    def __init__(self, client: MT5Client) -> None:
        self.client = client
        self._seen_keys: set[str] = set()

    async def execute(self, plan: OrderPlan) -> ExecutionResult:
        if CFG.trade_mode == "dry_run":
            return ExecutionResult(ok=True, price=plan.entry, volume=plan.lots,
                                   error="dry_run mode: not sent")
        if plan.idempotency_key and plan.idempotency_key in self._seen_keys:
            return ExecutionResult(ok=False, error=f"duplicate idempotency_key: {plan.idempotency_key}")
        try:
            for attempt in range(3):
                request = self._build_request(plan)
                result = await self.client.send_order(request)
                if result["retcode"] == 10009:  # TRADE_RETCODE_DONE
                    if plan.idempotency_key:
                        self._seen_keys.add(plan.idempotency_key)
                    trade_log({"event": "order_done", "plan": plan.__dict__, "result": result})
                    return ExecutionResult(ok=True, retcode=result["retcode"],
                                           deal=result["deal"], order=result["order"],
                                           price=result["price"], volume=result["volume"])
                if result["retcode"] in _IDEMPOTENT_OK:
                    # 目标状态已是当前状态 —— 记成功，但用独立事件名，
                    # 以便在日志里把"真的改了"与"本来就对"区分开。
                    if plan.idempotency_key:
                        self._seen_keys.add(plan.idempotency_key)
                    trade_log({"event": "order_unchanged", "plan": plan.__dict__,
                               "result": result})
                    return ExecutionResult(ok=True, retcode=result["retcode"],
                                           price=result["price"])
                if result["retcode"] in _RETRYABLE and attempt < 2:
                    await self.client.get_ohlcv(bars_per_tf=2)  # 触发一次报价刷新
                    continue
                trade_log({"event": "order_rejected", "plan": plan.__dict__, "result": result})
                return ExecutionResult(ok=False, retcode=result["retcode"],
                                       error=result["comment"] or f"retcode={result['retcode']}")
            return ExecutionResult(ok=False, error="retries exhausted")
        except Mt5Error as e:
            log_error(f"执行器异常: {e}")
            return ExecutionResult(ok=False, error=str(e))

    def _symbol_info(self, symbol: str | None = None):
        """按品种取 symbol_info，兼容旧的无参签名（测试桩/研究脚本）。"""
        try:
            return self.client.symbol_info(symbol)
        except TypeError:
            return self.client.symbol_info()

    def _build_request(self, plan: OrderPlan) -> dict:
        # ⚠️ 多品种：必须按 plan 的品种取 symbol_info 与填 "symbol" 字段，
        #    否则所有品种的单都会发到默认品种（CFG.mt5.symbol）上。
        sym = plan.symbol or CFG.mt5.symbol
        si = self._symbol_info(sym)
        if si is None:
            raise Mt5Error(f"symbol_info None during order build（{sym}）")
        # ⚠️ 所有价格必须**按 symbol 的 digits 规整**后才发出去。
        # 事故（2026-09-30 实测）：`modify_sltp` 提交 `sl=4178.211333333333`，
        # MT5 存回的是 `4178.211`（digits=3）。决策层下一轮拿 `pos.sl`
        # 与**未规整的**原值比较（LONG: `pos.sl < locked_sl`），
        # `4178.211 < 4178.211333` 恒为真 → 每轮重发同一个值，
        # MT5 每次都回 `10025 No changes`。
        # 实测：同一持仓最高重复提交 **83 次**，375 拒 / 35 成（91.5% 纯浪费）。
        # 在**发单边界**统一规整，使「提交值 == MT5 可能存回的值」，
        # 幂等判定才能收敛（只在 executor 一层做，避免各处漏改）。
        digits = int(getattr(si, "digits", 3) or 3)
        px = lambda v: (round(float(v), digits) if v else v)  # noqa: E731
        for _k in ("entry", "tp", "sl"):
            _v = getattr(plan, _k, None)
            if _v:
                setattr(plan, _k, px(_v))
        # filling mode 协商（docs/01 §4）：按 symbol_info.filling_mode 位掩码选择
        # 1=FOK, 2=IOC, 3=RETURN（MT5: SYMBOL_FILLING_FOK=1, SYMBOL_FILLING_IOC=2）
        fm = si.filling_mode
        if fm & 2:
            filling = mt5.ORDER_FILLING_IOC
        elif fm & 1:
            filling = mt5.ORDER_FILLING_FOK
        else:
            filling = mt5.ORDER_FILLING_RETURN
        base = {
            "symbol": sym,
            "magic": CFG.mt5.magic,
            "deviation": CFG.mt5.deviation,
            "comment": plan.comment,
            "type_filling": filling,
        }
        if plan.kind == "open_market":
            base.update(
                action=mt5.TRADE_ACTION_DEAL,
                type=mt5.ORDER_TYPE_BUY if plan.direction == "LONG" else mt5.ORDER_TYPE_SELL,
                volume=plan.lots,
                price=si.ask if plan.direction == "LONG" else si.bid,
                tp=plan.tp or 0.0,
                sl=plan.sl or 0.0,
            )
        elif plan.kind == "close_position":
            # 平仓必须带 volume —— 缺失时 MT5 返回
            # (-2, 'Invalid "volume" argument')，平仓会 100% 失败。
            if not plan.lots:
                raise Mt5Error(
                    f"close_position 缺少手数（position={plan.position_ticket}）")
            base.update(
                action=mt5.TRADE_ACTION_DEAL,
                position=plan.position_ticket,
                type=mt5.ORDER_TYPE_SELL if plan.direction == "LONG" else mt5.ORDER_TYPE_BUY,
                volume=plan.lots,
                price=si.bid if plan.direction == "LONG" else si.ask,
            )
        elif plan.kind == "modify_sltp":
            # ⚠️ TRADE_ACTION_SLTP 是**整体覆盖**：tp 传 0.0 = 删除止盈，
            # 且 MT5 会因此报 'Invalid stops'。
            # 原实现无条件 `tp=plan.tp or 0.0`，把止盈抹掉了。
            req = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": plan.position_ticket,
                "sl": plan.sl or 0.0,
            }
            if plan.tp:
                req["tp"] = plan.tp
            base.update(req)
        elif plan.kind == "place_pending":
            order_type = (mt5.ORDER_TYPE_BUY_LIMIT if plan.direction == "LONG"
                          else mt5.ORDER_TYPE_SELL_LIMIT)
            req = {
                "action": mt5.TRADE_ACTION_PENDING,
                "type": order_type,
                "volume": plan.lots,
                "price": plan.entry,
                "tp": plan.tp or 0.0,
                "sl": plan.sl or 0.0,
            }
            if plan.expiration_s:
                req["type_time"] = mt5.ORDER_TIME_SPECIFIED
                req["expiration"] = int(time.time() + plan.expiration_s)
            base.update(req)
        elif plan.kind == "cancel_pending":
            base.update(action=mt5.TRADE_ACTION_REMOVE, order=plan.position_ticket)
        else:
            raise Mt5Error(f"unknown plan kind: {plan.kind}")
        return base

    async def verify_filled(self, ticket: int) -> bool:
        """成交对账：position_get 确认存在。"""
        view = await self.client.get_positions()
        return any(p.ticket == ticket for p in view.positions)

    async def verify_pending(self, ticket: int) -> bool:
        """挂单对账：order 仍**在册**返回 True（未被撤、未成交、未过期）。"""
        view = await self.client.get_positions()
        return any(o.ticket == ticket for o in view.pending_orders)

    async def verify_sl(self, ticket: int, want_sl: float,
                        digits: int = 3) -> bool:
        """移损对账：读回持仓，确认 broker **实际**持有的 SL 等于目标值。

        ⚠️ 这是原先完全缺失的一环：`modify_sltp` 只看返回码，从不回读。
        实测事故：同一持仓对同一个 SL 值重复提交 83 次，因为系统无法知道
        "我提交的值"与"MT5 存下的值"是否一致（digits=3 四舍五入造成的
        3.3e-4 差异让比较永远为真）。回读比对是唯一能收敛的判据。
        """
        view = await self.client.get_positions()
        for p in view.positions:
            if p.ticket == ticket:
                if p.sl is None:
                    return False
                return abs(round(float(p.sl), digits) - round(float(want_sl), digits)) < 1e-9
        # 持仓已不在（已平仓）—— 视为"无需再改"，返回 True 以免无限重试
        return True
