"""MT5 适配层：连接、行情采集、持仓视图、下单执行。

按 docs/01-mt5-adapter.md 契约实现。MetaTrader5 是同步 C 扩展，
所有调用经由 executor 包装（docs/00 §2）。
"""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import pandas as pd

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import log_error, log_warn

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - 环境无 MT5 时仅 doctor 报错
    mt5 = None


class Mt5Error(RuntimeError):
    """MT5 操作失败（fail-closed，主循环捕获后跳过本轮）。"""


TF_MAP: dict[str, int] = {}
if mt5 is not None:
    TF_MAP = {
        "1m": mt5.TIMEFRAME_M1,
        "2m": mt5.TIMEFRAME_M2,
        "5m": mt5.TIMEFRAME_M5,
        "10m": mt5.TIMEFRAME_M10,
        "15m": mt5.TIMEFRAME_M15,
        "30m": mt5.TIMEFRAME_M30,
        "1h": mt5.TIMEFRAME_H1,
        "4h": mt5.TIMEFRAME_H4,
        "8h": mt5.TIMEFRAME_H8,
        "1d": mt5.TIMEFRAME_D1,
    }

TF_SECONDS = {"1m": 60, "2m": 120, "5m": 300, "10m": 600, "15m": 900, "30m": 1800,
              "1h": 3600, "4h": 14400, "8h": 28800, "1d": 86400}

_COLUMNS = ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]


@dataclass
class TickSnapshot:
    bid: float
    ask: float
    last: float
    spread_points: int
    time: float


@dataclass
class OHLCVBundle:
    symbol: str
    fetched_at: float
    frames: dict[str, pd.DataFrame]
    tick: TickSnapshot | None
    quality: dict[str, str] = field(default_factory=dict)


@dataclass
class PositionRow:
    ticket: int
    symbol: str
    type: str          # LONG | SHORT
    volume: float
    price_open: float
    sl: float
    tp: float
    profit: float
    swap: float
    time: float
    comment: str
    magic: int


@dataclass
class OrderRow:
    ticket: int
    symbol: str
    type: str
    volume: float
    price_open: float
    sl: float
    tp: float
    time_setup: float
    comment: str
    magic: int


@dataclass
class PositionsView:
    positions: list[PositionRow] = field(default_factory=list)
    pending_orders: list[OrderRow] = field(default_factory=list)

    @property
    def total_volume(self) -> float:
        return sum(p.volume for p in self.positions)


@dataclass
class AccountInfo:
    login: int
    balance: float
    equity: float
    margin_free: float
    margin: float
    margin_level: float
    leverage: int
    currency: str


class MT5Client:
    """线程安全包装：行情可并行，交易串行。"""

    def __init__(self) -> None:
        self._io_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mt5-io")
        self._trade_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mt5-trade")
        self._connected = False

    # ---------- 连接 ----------
    async def initialize(self) -> None:
        if self._connected:
            return
        await asyncio.get_running_loop().run_in_executor(self._io_pool, self._initialize_sync)
        self._connected = True

    def _initialize_sync(self) -> None:
        cfg = CFG.mt5
        kwargs: dict = {"path": cfg.terminal_path}
        if cfg.login:
            kwargs.update(login=cfg.login, password=cfg.password, server=cfg.server)
        if mt5 is None:
            raise Mt5Error("MetaTrader5 package not installed")
        if not mt5.initialize(**kwargs):
            raise Mt5Error(f"initialize failed: {mt5.last_error()}")
        if not mt5.symbol_select(cfg.symbol, True):
            raise Mt5Error(f"symbol_select({cfg.symbol}) failed: {mt5.last_error()}")

    async def doctor(self) -> dict:
        """启动自检（docs/01 §1），返回结构化报告。"""
        return await asyncio.get_running_loop().run_in_executor(self._io_pool, self._doctor_sync)

    def _doctor_sync(self) -> dict:
        report: dict = {"ok": False, "checks": {}}
        try:
            self._initialize_sync()
        except Mt5Error as e:
            report["checks"]["initialize"] = str(e)
            return report
        ti = mt5.terminal_info()
        report["checks"]["terminal"] = {
            "connected": bool(ti.connected) if ti else None,
            "build": ti.build if ti else None,
        }
        ai = mt5.account_info()
        report["checks"]["account"] = (
            {"login": ai.login, "balance": ai.balance, "equity": ai.equity,
             "currency": ai.currency, "leverage": ai.leverage} if ai else "account_info None"
        )
        si = mt5.symbol_info(CFG.mt5.symbol)
        report["checks"]["symbol"] = (
            {"name": si.name, "visible": si.visible, "point": si.point,
             "digits": si.digits, "volume_min": si.volume_min, "volume_step": si.volume_step,
             "stops_level": si.trade_stops_level, "tick_value": si.trade_tick_value,
             "tick_size": si.trade_tick_size, "filling": si.filling_mode}
            if si else "symbol_info None"
        )
        report["ok"] = bool(ti and ti.connected and ai and si)
        return report

    def symbol_info(self):
        return mt5.symbol_info(CFG.mt5.symbol)

    # ---------- 行情 ----------
    async def get_ohlcv(self, bars_per_tf: int | None = None) -> OHLCVBundle:
        """并发拉取全部周期（线程池 IO）；未连接时自动 initialize。"""
        await self.initialize()
        n = bars_per_tf or CFG.mt5.bars_per_tf
        loop = asyncio.get_running_loop()
        sym = CFG.mt5.symbol
        futures = {
            tf: loop.run_in_executor(self._io_pool, self._copy_rates_sync, sym, tf_code, n)
            for tf, tf_code in TF_MAP.items()
        }
        results = await asyncio.gather(*futures.values())
        frames = dict(zip(futures.keys(), results))
        tick = await loop.run_in_executor(self._io_pool, self._tick_sync, sym)
        return self._validate(frames, tick)

    def _copy_rates_sync(self, symbol: str, tf_code: int, n: int) -> pd.DataFrame | None:
        rates = mt5.copy_rates_from_pos(symbol, tf_code, 0, n)
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df[_COLUMNS]

    def _tick_sync(self, symbol: str) -> TickSnapshot | None:
        t = mt5.symbol_info_tick(symbol)
        if t is None:
            return None
        spread = int(t.ask - t.bid) if t.ask and t.bid else 0
        return TickSnapshot(bid=t.bid, ask=t.ask, last=t.last, spread_points=spread, time=t.time)

    def _validate(self, frames: dict, tick) -> OHLCVBundle:
        quality: dict[str, str] = {}
        cleaned: dict[str, pd.DataFrame] = {}
        for tf, df in frames.items():
            if df is None or df.empty:
                quality[tf] = "bad:empty"
                continue
            if not df["time"].is_monotonic_increasing:
                quality[tf] = "bad:not_monotonic"
                continue
            if df[["open", "high", "low", "close"]].isna().any().any():
                quality[tf] = "bad:nan"
                continue
            if ((df["close"] > df["high"]) | (df["close"] < df["low"])).any():
                quality[tf] = "bad:close_out_of_range"
                continue
            quality[tf] = "ok"
            cleaned[tf] = df
        if not cleaned:
            raise Mt5Error("all timeframes failed quality gate")
        return OHLCVBundle(symbol=CFG.mt5.symbol, fetched_at=time.time(),
                           frames=cleaned, tick=tick, quality=quality)

    # ---------- 持仓 ----------
    async def get_positions(self) -> PositionsView:
        await self.initialize()
        return await asyncio.get_running_loop().run_in_executor(self._io_pool, self._positions_sync)

    def _positions_sync(self) -> PositionsView:
        sym = CFG.mt5.symbol
        positions = []
        for p in mt5.positions_get(symbol=sym) or []:
            positions.append(PositionRow(
                ticket=p.ticket, symbol=p.symbol,
                type="LONG" if p.type == 0 else "SHORT",
                volume=p.volume, price_open=p.price_open, sl=p.sl, tp=p.tp,
                profit=p.profit, swap=p.swap, time=p.time, comment=p.comment or "", magic=p.magic))
        orders = []
        for o in mt5.orders_get(symbol=sym) or []:
            orders.append(OrderRow(
                ticket=o.ticket, symbol=o.symbol,
                type=str(o.type), volume=o.volume_current, price_open=o.price_open,
                sl=o.sl, tp=o.tp, time_setup=o.time_setup, comment=o.comment or "", magic=o.magic))
        return PositionsView(positions=positions, pending_orders=orders)

    async def get_account(self) -> AccountInfo:
        await self.initialize()
        return await asyncio.get_running_loop().run_in_executor(self._io_pool, self._account_sync)

    async def get_deals(self, since_ts: float) -> list[dict]:
        """读取交割单（history_deals_get），用于胜率/盈亏闭环校准。"""
        await self.initialize()
        return await asyncio.get_running_loop().run_in_executor(
            self._io_pool, self._deals_sync, since_ts)

    def _deals_sync(self, since_ts: float) -> list[dict]:
        deals = mt5.history_deals_get(since_ts, time.time() + 3600) or []
        out = []
        for d in deals:
            if d.entry in (1, 2):  # DEAL_EXIT / DEAL_INOUT 只取离场方向
                out.append({
                    "ticket": d.ticket, "order": d.order, "position_id": d.position_id,
                    "time": d.time, "type": int(d.type), "volume": d.volume,
                    "price": d.price, "profit": d.profit, "swap": d.swap,
                    "commission": d.commission, "fee": d.fee,
                    "symbol": d.symbol, "comment": d.comment or "", "magic": d.magic})
        return out

    def _account_sync(self) -> AccountInfo:
        ai = mt5.account_info()
        if ai is None:
            raise Mt5Error(f"account_info failed: {mt5.last_error()}")
        return AccountInfo(login=ai.login, balance=ai.balance, equity=ai.equity,
                           margin_free=ai.margin_free, margin=ai.margin,
                           margin_level=ai.margin_level, leverage=ai.leverage,
                           currency=ai.currency)

    # ---------- 交易（串行线程池） ----------
    async def send_order(self, request: dict) -> dict:
        return await asyncio.get_running_loop().run_in_executor(self._trade_pool, self._send_sync, request)

    def _send_sync(self, request: dict) -> dict:
        result = mt5.order_send(request)
        if result is None:
            raise Mt5Error(f"order_send returned None: {mt5.last_error()}")
        return {"retcode": result.retcode, "deal": result.deal, "order": result.order,
                "volume": result.volume, "price": result.price,
                "comment": result.comment, "request_id": result.request_id,
                "retcode_external": result.retcode_external}

    # 关闭
    def shutdown(self) -> None:
        if self._connected and mt5 is not None:
            mt5.shutdown()
        self._io_pool.shutdown(wait=False)
        self._trade_pool.shutdown(wait=False)
