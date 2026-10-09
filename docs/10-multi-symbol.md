# 10 — 多品种设计与运维

状态：新增（2026-10-09）

> 本文说明如何从单品种（XAUUSDm）扩展到多品种，以及扩之前必须知道的事。
> **默认配置仍是单品种**，`TRADE_SYMBOLS` 不设时行为与改造前逐字节一致。

## 1. 怎么开多品种

在 `.env` 里加一行：

```bash
TRADE_SYMBOLS=XAUUSDm,BTCUSDm
```

留空或删除 = 只交易 `MT5_SYMBOL`（单品种）。

已注册品种见 `src/gold_agent/common/symbols.py` 的 `PROFILES`：
`XAUUSDm` `BTCUSDm` `USOILm` `EURUSDm` `USDJPYm`。
**未注册的品种会启动即报错**（不静默兜底）—— 用一个错的点值开仓
比启动失败危险得多。

> ⚠️ 建议**逐个加**（先只放 `BTCUSDm` 跑通，再加下一个），不要一次全开。

## 2. 单品种 vs 多品种的差异

| | 单品种 | 多品种 |
|---|---|---|
| 进程 | 1 个 | **仍是 1 个**（asyncio 并发各品种） |
| 状态目录 | `data/` | `data/<品种>/` |
| 日志 | 无 `symbol` 字段 | 每条记录带 `symbol` |
| magic | 20260918 | 每品种不同（20260918 + 索引） |
| LLM 预算 | 60 / 24 / 24 每小时 | 按品种数**平分** |
| 组合风险闸 | 全部空操作 | 生效 |
| SMC 周期 | 固定 4 个 | 按 Mobius venue 能力裁剪 |

### 为什么是单进程而不是多进程

用户明确要求日志统一可见（"不同进程日志看不到啊"）。
单进程写同一批日志文件，每条带 `symbol` 标签即可区分归属。

单进程也**不是**受"MT5 只能单连接"所限。实测同一进程内多线程并发
读行情与下单都安全：5 线程 × 8 并发读（40 次调用）无异常；
5 个品种同时 `order_check` 全部 `retcode=0`。

## 3. 品种参数全部来自 `SymbolProfile`

所有品种相关量**只从** `common/symbols.py` 的 `PROFILES` 取。
改造前它们是散落各处的硬编码，其中两处是**真 bug**：

### 3.1 `digits`/`point` 写死会开错价的单

`machine.py` 原为 `_PX_DIGITS = 3` / `_POINT = 0.001`（XAUUSDm 的值）。
对 EURUSDm（digits=5）：

```
真实止损 1.12419  --round(,3)-->  1.12400     偏 19 个 point
```

这与 2026-09-30 那次"同一持仓重复提交 **83 次**"是同一类故障：
提交值与我方记录永不相等 → 幂等判定不收敛 → 每轮重发同一个值
（MT5 每次回 `10025 No changes`）。

### 3.2 手数换算里的 `point` 是"自消"的 —— 改一处就差 100 倍

```python
# position.py
sl_points    = sl_dist / point
per_lot_risk = sl_points * point_value_per_lot
# graph._point_value() 提供
point_value_per_lot = tick_value * (point / tick_size)
```

代入后 `point` **在代数上消掉**：`per_lot_risk = sl_dist × tick_value / tick_size`，
与品种无关。所以原实现两处各自硬编码 `0.001` 是**碰巧正确**的
（实测 5 品种下与正确公式完全一致：1843.99 / 679.36 / 863.23 / 156.69 / 156.59）。

但这是**脆弱的巧合**：只改一处立刻产生成百倍误差 ——
实测 EURUSDm 正确 `0.05` 手 vs 单边改动 `5.0` 手（**100 倍**）。

> ⚠️ 修改时 `position_lots(point=…)`、`gate.evaluate(point=…)`、
> `graph._point_value()`、`machine._point(ctx)` **四处必须同源**。
> `tests/test_multi_symbol_real.py` 已锁死这条不变式。

### 3.3 `CFG.max_lot` 会掩盖换算错误

写这个测试时踩到的坑，值得记下来：
`max_lot = 0.06` 时，正确实现与 100 倍错误的实现**都被封顶到 0.06**，
手数看起来一样（EURUSDm 正确 0.05 vs bug 0.06，仅 20% 差异）。
要验证换算本身必须**临时解除封顶**，否则测试形同虚设。

## 4. Mobius（SMC 信号源）的多品种映射

### 4.1 每个品种的 venue 与符号名不同

| 品种 | Mobius venue | 符号名 | 支持的周期 |
|---|---|---|---|
| XAUUSDm | `commodity:spot` | `XAUUSD` | 5m 15m 30m 1h 4h 1d |
| BTCUSDm | `binance:spot` | `BTCUSDT` | 1m 5m 15m 1h 4h 1d |
| USOILm | `commodity:futures` | `WTIUSD` | **仅 1h 1d** |
| EURUSDm | `forex:spot` | `EURUSD` | **仅 1h 1d** |
| USDJPYm | `forex:spot` | `USDJPY` | **仅 1h 1d** |

两个容易搞错的地方（已实测确认）：
- 油**不在** `commodity:spot`（该 venue 只有 `XAUUSD` 一个品种，实测 404）。
  油在 `commodity:futures`，名字是 `WTIUSD`。
- 比特币用 `BTCUSDT`，`BTCUSD` 返回 404。

### 4.2 必须按 venue 能力裁剪周期

请求 venue 不支持的周期返回 **400，不是降级**。若不裁剪，
forex 品种每轮会发出 3 个必然失败的请求，SMC 静默变成"永远不可用"
（而不是"少一个周期"）。`SymbolProfile.smc_intervals()` 负责裁剪。

**缺周期的后果是可接受的**：`aggregate_tf_scores` 用固定分母
（声明权重之和），缺周期贡献 0 → 总分向 0 **收缩**，
即"证据不足时降低置信度"。这正是缺数据时该有的行为。
（若改成除以"实际到齐权重和"，等于假装没缺数据，会把单周期观点
放大到满量程 —— 危险，别改。）

> 所以 forex/油品种的 SMC 只有 1h 一个周期，其方向分天然更弱。
> 实际影响：这些品种更容易判定为"无信号"，开仓更少。这是**正确**的保守行为。

### 4.3 API token

`.env` 里的 `MOBIUSQUANT_API_TOKEN` 用于把速率档位从匿名
10 req/min 提到 60 req/min。**必须**用 `Authorization: Bearer` 传
（代码已自动带）：

- 放进 `X-API-Key` 之类的自定义头**不报错，但档位静默停留在 10/min**
  （实测 `X-RateLimit-Limit` 仍是 10）；
- token 拼错 / 过期 → `401`，**不降级匿名**（所以配错会直接表现为服务不可用，
  不会被悄悄忽略）。

判断 token 是否真的生效，只能看响应头 `X-RateLimit-Limit`：
`10` = 匿名档，`60` = token 档。

## 5. 风险控制

### 5.1 逐品种（原有）

`CircuitBreakers` 按品种独立：连亏熔断、日亏损、回撤、保证金、
方向偏置。每品种一份状态（`data/<品种>/breakers.json`）。

### 5.2 组合级（新增，`risk/portfolio.py`）

**逐品种风控结构上无法覆盖**这些多品种才有的风险：

1. **回撤熔断口径失效（最关键）**
   各品种只看自己的盈亏序列。组合整体回撤 12% 时，若每个品种各自
   只回撤 2.4%，就**没有任何品种触发熔断** —— 总亏损已经很大，
   系统却认为一切正常。

2. **风险预算被倍数放大**
   每品种各按 0.5% 独立算手数 → 5 品种同时开仓 = 单次总风险 **2.5%**。
   且品种间可能高度相关（黄金/原油/欧元都受美元驱动），
   相关性高时等于**同一个方向下了 5 倍注**。

3. **同向集中** —— "5 个品种都看多"在宏观上是**一个**仓位。
4. **保证金集中** —— 逐品种判断抓不到合计。

⚠️ **同向闸的方向来源有个坑**（初版踩过，测试当场抓住）：
判定必须用**本笔要开的方向**，不能读"该品种已有持仓的方向" ——
正在开新仓时该品种还没有持仓（方向为 `None`），
于是同向闸会在**最需要它的时刻静默失效**。
实测：3 个品种已做多，第 4 个再做多仍被放行。

各品种是 asyncio 并发跑的，每个 `Graph` 只按 magic 看得到**自己**的
持仓，因此需要一张共享方向登记表（`PortfolioRisk.report_direction`
/ `direction_map`）：各品种每轮上报自己观测到的方向，同向闸再读全局视图。
这是**近似**（并发下可能晚一轮，60 秒），但持仓方向不会在 60 秒内
大规模翻转，且该闸本身保守（宁可误判为集中而拒开）。

配置见 `config.toml` 的 `[risk]`：

```toml
portfolio_risk_cap = 0.01            # 组合总风险上限（超限按比例缩手数）
portfolio_drawdown_halt_pct = 0.12   # 组合总回撤熔断
portfolio_max_same_direction = 3     # 同向品种数上限（超限拒开）
portfolio_margin_cap = 0.60          # 组合保证金上限
```

设计原则：**只收紧、不放松**。组合闸只在逐品种风控已通过后
再拒绝或缩仓，绝不会放行本来会被拒的单。
已用风险按**满额** `risk_pct` 计入（高估 → 更早缩仓，保守方向）。

## 6. LLM 预算

**这个"预算"是什么**：`llm.per_hour_budget` 等是**本进程自设的
滚动小时上限**，不是 RunningHub 的配额 —— 你自己的 API key
本身没有这个限制。它纯粹用来防止代码疯狂调用烧钱。

**为什么多品种必须按品种分池**：
单品种时 `per_hour_budget = 60` 恰好等于"60 秒一轮 × 60 分钟 = 60 轮"，
已经 **100% 用满**（实测每小时成功 64~75 次，cap 60 已饱和）。
若 5 个品种共用这 60，每品种只剩 12 次/小时 = 每 5 轮 1 次评审。
LLM 是市价开仓的确认环节，不可用时拿不到压力位就无法开仓
（`llm_no_levels`）→ 5 个品种全部变哑。

`CFG.per_symbol_budgets(n)` 按品种数平分，每池下限 1。
同类事故已有前例：news 曾与 review 共用池子并把额度吃光，
使 review 覆盖率跌到 **4.3%**。

> 想给更多额度就直接改 `config.toml` 的 `[llm]`（是你自己的 key）。
> 真正该关注的是**成本**：5 品种 = 每小时最多 300 次调用。

## 7. 排障

| 现象 | 先查 |
|---|---|
| 某品种完全不开仓 | `logs/llm_*.jsonl` 里该品种的 `budget_exhausted`；`llm_no_levels` |
| 某品种 SMC 一直不可用 | 该 venue 是否 `degraded`（`/api/health`）；周期是否被正确裁剪 |
| 手数异常大/小 | 四个 `point` 是否同源（§3.2） |
| 价格被拒绝 / 重复提交 | `digits` 是否与券商一致（§3.1） |
| 组合回撤已很大但没停 | `portfolio_drawdown_halt_pct`；各品种状态是否隔离 |
| 日志分不清品种 | `symbol` 字段（多品种下每条都有） |

## 8. 未做 / 已知限制

- **品种相关性未建模**：组合风险闸只是把各品种风险**相加**，
  没有估计相关矩阵。所以它防的是"名义总风险"，防不了
  "看似分散实则同向"的实质风险。这也是 `portfolio_risk_cap` 取
  从严值（0.01）的原因。
- **保证金按 0 计入**：`build_state` 的 `margin_by_symbol` 目前为空，
  组合保证金闸因此只在调用方显式提供数据时才生效。
- **`USOILm` 的 SMC 只有 1h**：`commodity:futures` 不支持更细周期。
- **黄金源本身仍是 degraded**：`commodity:spot` 的 status 为 degraded，
  实测 `max_age_secs` 约 20 小时。这不是本项目的问题，
  但会让 XAUUSDm 的 SMC 频繁返回 503。
