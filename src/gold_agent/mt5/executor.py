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
if mt5 is not None:
    _RETRYABLE = {mt5.TRADE_RETCODE_REQUOTE, mt5.TRADE_RETCODE_PRICE_CHANGED,
                  mt5.TRADE_RETCODE_PRICE_OFF}


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

    def _build_request(self, plan: OrderPlan) -> dict:
        si = self.client.symbol_info()
        if si is None:
            raise Mt5Error("symbol_info None during order build")
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
            "symbol": CFG.mt5.symbol,
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
