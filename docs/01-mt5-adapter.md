# 01 — MT5 适配层契约（mt5/）

参考：MetaTrader5 Python 官方文档（mql5.com/files/docs/mql5_python.pdf）。

## 1. 连接与初始化

```python
mt5.initialize(path="D:\\MT5\\terminal64.exe", login=..., password=..., server=...)
# 或 attach 已运行终端（不给 login 则用当前登录会话）
mt5.symbol_select("XAUUSDm", True)  # 必须确保符号在 Market Watch
```

- 启动自检 `mt5.doctor`：initialize → terminal_info（connected/build）→ account_info → symbol_info(XAUUSDm) 全通过才放行主循环。
- 符号名 `XAUUSDm`（m 后缀）从配置读取；启动时若 `symbol_info` 返回 None，尝试 `symbol_select` 并列出 `symbols_get("*XAU*")` 报告候选名（fail-closed，不猜名字）。

## 2. 行情采集（collector）

- **周期映射**：MT5 原生支持 `TIMEFRAME_M1 M2 M3 M5 M10 M15 M30 H1 H2 H3 H4 H6 H8 H12 D1`。目标周期 `1m 2m 5m 10m 15m 30m 1h 4h 8h 1d` **全部原生支持**，无需重采样兜底；仍保留重采样校验函数 `validate_resample()` 交叉验证（1m→2m/5m/10m/15m/30m；1h→4h/8h/1d），偏差 > 0.5 点记 WARN。
- `copy_rates_from_pos(symbol, timeframe, start_pos=0, count=N)`：每周期拉 `N = max(600, 5×指标窗口)` 根。时间统一 UTC（`time` 字段为秒级 epoch）。
- `copy_ticks_from_pos`：仅决策瞬间取最近 200 tick 用于滑点/点差统计。
- 校验门（fail-closed，同 chanlun 引擎风格）：时间严格递增、无 NaN、close∈[low,high]；失败周期标记 `quality=bad` 不进入融合。

## 3. 数据结构

```python
@dataclass
class OHLCVBundle:
    symbol: str
    fetched_at: float          # epoch s
    frames: dict[str, pd.DataFrame]   # "1m".."1d" -> columns: time,open,high,low,close,tick_volume,spread,real_volume
    tick: TickSnapshot         # bid/ask/last/time
    quality: dict[str, str]    # per-tf: ok|bad

@dataclass
class PositionsView:
    positions: list[PositionRow]      # MT5 position_get()
    pending_orders: list[OrderRow]    # orders_get()
    total_volume: float
    net_exposure_usd: float           # 经 symbol_info 换算

@dataclass
class AccountInfo:
    balance: float; equity: float; margin_free: float
    margin_level: float; leverage: int; currency: str
```

## 4. 下单执行（executor）——live 模式

- `order_send` 请求构造：`action=TRADE_ACTION_DEAL`（市价）或 `TRADE_ACTION_PENDING`（限价/网格挂单）、`magic=固定值(如 20260918)` 区分本系统单、`deviation=20`（points）、`type_filling` 按 `symbol_info.filling_mode` 选择（IOC→FOK→RETURN 顺序回退）。
- 每笔单必带 SL/TP；SL 距离 ≥ `stops_level + spread×1.5`，否则上移到合法值并记录。
- 平仓：`TRADE_ACTION_DEAL` + `position=ticket` + 反向 `order_type`；部分平仓用 `volume`。
- 修改 SL/TP：`TRADE_ACTION_SLTP` + `position` + `sl/tp`。
- 网格挂单：`TRADE_ACTION_PENDING` + `ORDER_TYPE_BUY_LIMIT/SELL_LIMIT`，附 `expiration=ORDER_TIME_SPECIFIED`（防僵尸单）。
- **串行化**：所有 executor 调用走单线程 executor，杜绝并发重复下单；每次调用幂等键 = (magic, action_hash) 写入 state.json，重启后对账。
- 失败重试：`retcode` 为 `TRADE_RETCODE_REQUOTE/PRICE_CHANGED/PRICE_OFF` → 最多重试 2 次并刷新报价；`TRADE_RETCODE_NO_MONEY/INVALID_VOLUME/INVALID_STOPS` → 不重试，直接上报。

## 5. 单位与手续费

- XAUUSD 点值：1 lot = 100 oz，1 点(0.01) ≈ $1/lot（以 `symbol_info.trade_tick_value/trade_tick_size` 实算，不硬编码）。
- 仓位计算输入：`bid/ask`、`spread`、`stops_level`、`trade_tick_value`、`volume_min/step/max`。

## 6. 测试要求（无 mock）

- 真实 initialize + 行情拉取（10 周期 × 数据完整性断言）。
- `positions_get/orders_get` 只读验证。
- 下单测试在 live 模式下仅允许 `MAX_LOT`（默认 0.01）最小手数、且由人工触发 `--allow-live-order` 标志运行。
