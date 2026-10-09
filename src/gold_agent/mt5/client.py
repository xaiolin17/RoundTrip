"""MT5 适配层：连接、行情采集、持仓视图、下单执行。

按 docs/01-mt5-adapter.md 契约实现。MetaTrader5 是同步 C 扩展，
所有调用经由 executor 包装（docs/00 §2）。
"""
from __future__ import annotations

import asyncio
import threading
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

#: 串行化 `mt5.initialize()` —— 它是**进程级全局**操作，多品种并发初始化
#: 会互相打断（见 `_initialize_sync` 的注释）。
_INIT_LOCK = threading.Lock()


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


def _order_direction(mt5_type) -> str:
    """把 MT5 订单类型码映射成 LONG / SHORT。

    ⚠️ 必须**穷举**映射，不能靠字符串猜。
    实测事故：原实现 `OrderRow.type = str(o.type)` 存的是整数码（如 "2"），
    而 `decision/machine.py` 用 `"buy" in str(type).lower()` 判方向 ——
    `"buy" in "2"` 恒为 False，于是**所有挂单都被当成 SHORT**。

    MT5 常量：
      0 ORDER_TYPE_BUY         1 ORDER_TYPE_SELL
      2 ORDER_TYPE_BUY_LIMIT   3 ORDER_TYPE_SELL_LIMIT
      4 ORDER_TYPE_BUY_STOP    5 ORDER_TYPE_SELL_STOP
      6 ORDER_TYPE_BUY_STOP_LIMIT  7 ORDER_TYPE_SELL_STOP_LIMIT
      8 ORDER_TYPE_CLOSE_BY
    """
    t = int(mt5_type)
    # 买单：BUY / BUY_LIMIT / BUY_STOP / BUY_STOP_LIMIT
    if t in (0, 2, 4, 6):
        return "LONG"
    # 卖单：SELL / SELL_LIMIT / SELL_STOP / SELL_STOP_LIMIT
    if t in (1, 3, 5, 7):
        return "SHORT"
    # CLOSE_BY(8) 及其它：无方向，交给上层按"未知"处理
    return "UNKNOWN"


@dataclass
class OrderRow:
    ticket: int
    symbol: str
    type: str          # LONG | SHORT（与 PositionRow 统一，**不是** MT5 整数码）
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
    """线程安全包装：行情可并行，交易串行。

    ⚠️ `symbol` 是**本实例负责的品种**。多品种时每个品种一个实例，
    所有行情/持仓查询都必须用这个字段，**不能**退回 `CFG.mt5.symbol`。

    事故记录（2026-10-09，多品种试点时发现）：本类的 `get_ohlcv`、
    `_positions_sync`、`_validate` 都写死 `CFG.mt5.symbol`，而
    `MT5Client` 当时**没有 symbol 字段**。于是 5 个品种的 Graph
    虽然各有正确的品种档案，却全部去拉 **XAUUSDm** 的 K 线 ——
    实测 5 个品种的收盘价完全相同（都是 4175.704），融合分也只差
    0.001（+0.1729 ~ +0.1756）。这类错误的危险在于**不报错**：
    每个品种都"正常工作"、都在产出信号，只是所有信号都是黄金的。
    若不是我在多品种实跑后顺手核对收盘价，会一直不被发现。
    """

    def __init__(self, symbol: str | None = None) -> None:
        #: 本实例负责的品种（None = 用 `CFG.mt5.symbol`，单品种兼容）
        self.symbol = symbol
        self._io_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mt5-io")
        self._trade_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mt5-trade")
        self._connected = False

    def _sym(self) -> str:
        """本实例的品种（None 时退回配置默认值）。"""
        return self.symbol or CFG.mt5.symbol

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
        # ⚠️ `mt5.initialize()` 与 `symbol_select()` 是**进程级全局**操作，
        #    而多品种下每个品种一个 `MT5Client`、并发初始化。
        #    用类级锁串行化，避免并发 initialize 互相打断
        #    （实测并发下单/读取都安全，但初始化不是）。
        with _INIT_LOCK:
            if not mt5.initialize(**kwargs):
                raise Mt5Error(f"initialize failed: {mt5.last_error()}")
            # 选入本实例的品种（不是配置里的默认品种）——
            # 不选入 Market Watch 的话 `copy_rates_from_pos` 返回 None。
            sym = self._sym()
            if not mt5.symbol_select(sym, True):
                raise Mt5Error(f"symbol_select({sym}) failed: {mt5.last_error()}")

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
        si = mt5.symbol_info(self._sym())
        report["checks"]["symbol"] = (
            {"name": si.name, "visible": si.visible, "point": si.point,
             "digits": si.digits, "volume_min": si.volume_min, "volume_step": si.volume_step,
             "stops_level": si.trade_stops_level, "tick_value": si.trade_tick_value,
             "tick_size": si.trade_tick_size, "filling": si.filling_mode}
            if si else "symbol_info None"
        )
        report["ok"] = bool(ti and ti.connected and ai and si)
        return report

    def symbol_info(self, symbol: str | None = None):
        """symbol_info。多品种下按品种取 —— 缺省用本实例的品种。"""
        return mt5.symbol_info(symbol or self._sym())

    # ---------- 行情 ----------
    async def get_ohlcv(self, bars_per_tf: int | None = None,
                        symbol: str | None = None) -> OHLCVBundle:
        """并发拉取全部周期（线程池 IO）；未连接时自动 initialize。

        `symbol` 缺省用本实例的品种（多品种时每个 Graph 各取自己的）。
        """
        await self.initialize()
        n = bars_per_tf or CFG.mt5.bars_per_tf
        loop = asyncio.get_running_loop()
        sym = symbol or self._sym()
        futures = {
            tf: loop.run_in_executor(self._io_pool, self._copy_rates_sync, sym, tf_code, n)
            for tf, tf_code in TF_MAP.items()
        }
        results = await asyncio.gather(*futures.values())
        frames = dict(zip(futures.keys(), results))
        tick = await loop.run_in_executor(self._io_pool, self._tick_sync, sym)
        return self._validate(frames, tick, symbol=sym)

    def get_ohlcv_sync(self, bars_per_tf: int | None = None) -> OHLCVBundle | None:
        """同步拉取全部周期 —— 仅供**启动预热**使用（在事件循环启动前调用）。

        预热需要比 `bars_per_tf` 更长的历史（默认 300 轮 + min_periods），
        所以这里会按 `prime_steps + min_periods + 50` 向上取整请求更多 1m bar。
        失败返回 None（预热失败不应阻止启动，只是会晚几小时才开仓）。
        """
        try:
            if not mt5.initialize():
                return None
            n = bars_per_tf or max(
                CFG.mt5.bars_per_tf,
                CFG.fusion.prime_steps + CFG.fusion.norm_min_periods + 50)
            sym = self._sym()
            frames = {tf: self._copy_rates_sync(sym, code, n)
                      for tf, code in TF_MAP.items()}
            tick = self._tick_sync(sym)
            return self._validate(frames, tick, symbol=sym)
        except Exception:
            return None

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

    def _validate(self, frames: dict, tick, symbol: str | None = None) -> OHLCVBundle:
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
        return OHLCVBundle(symbol=symbol or self._sym(), fetched_at=time.time(),
                           frames=cleaned, tick=tick, quality=quality)

    # ---------- 持仓 ----------
    async def get_positions(self) -> PositionsView:
        await self.initialize()
        return await asyncio.get_running_loop().run_in_executor(self._io_pool, self._positions_sync)

    def _positions_sync(self) -> PositionsView:
        # ⚠️ 必须用本实例的品种：多品种下若写死默认品种，每个 Graph 都会
        #    看到**黄金**的持仓，进而按自己的 magic 过滤出空列表 ——
        #    于是各品种都以为"我没有持仓"，可以无限开仓，且看不到
        #    总手数占用（`_used_lots` 恒为 0）、无法加仓/平仓。
        #    `mt5.positions_get(symbol=None)` 返回**全部**品种，
        #    而按 magic 过滤是后续逻辑，故这里按品种收窄是正确做法。
        sym = self._sym()
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
                type=_order_direction(o.type), volume=o.volume_current,
                price_open=o.price_open,
                sl=o.sl, tp=o.tp, time_setup=o.time_setup, comment=o.comment or "",
                magic=o.magic))
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

    # ---------- 出入金（回撤豁免基准） ----------
    async def get_balance_ops(self, since_ts: float) -> list[dict]:
        """读取**出入金**流水（DEAL_TYPE_BALANCE），用于回撤的现金流水校正。

        ⚠️ 为什么必须存在（2026-10-08 用户报告「从9.30号开始 效益就不好」）：
        回撤 `dd = (峰值净值 − 当前净值) / 峰值净值` 把**出入金**也当成了亏损。
        实测本账户 10-01 13:56 一笔 `-100150.57` 出金，净值从 ~100,000
        掉到 100.00，于是紧跟着的 23 轮全部返回
        `circuit: max_drawdown 99.0%` —— 真正亏损只有 -46.43，
        却被自己的风控**误判成爆仓并停止交易**。
        资金进出不是策略表现，必须从回撤里剔除。
        """
        await self.initialize()
        return await asyncio.get_running_loop().run_in_executor(
            self._io_pool, self._balance_ops_sync, since_ts)

    def _balance_ops_sync(self, since_ts: float) -> list[dict]:
        deals = mt5.history_deals_get(since_ts, time.time() + 3600) or []
        out = []
        for d in deals:
            if int(d.type) == 2:  # DEAL_TYPE_BALANCE
                out.append({"time": d.time, "profit": float(d.profit),
                            "comment": d.comment or ""})
        return out

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
