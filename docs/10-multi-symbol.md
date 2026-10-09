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
| **各品种信号几乎一样** | ⚠️ 数据串台 —— 见下面的事故记录 |

### 事故：各品种全都在用黄金的行情（2026-10-09）

开通多品种后实跑一轮，**5 个品种的收盘价完全相同**：

```
品种        收盘价      融合分
XAUUSDm     4175.704    -0.29143
BTCUSDm     4175.704    -0.29163     <- 比特币报价 4175？不可能
EURUSDm     4175.704    -0.29033     <- 欧元报价 4175？不可能
```

根因：`MT5Client` **没有任何 symbol 字段**，其 4 处查询
（`get_ohlcv` / `get_ohlcv_sync` / `_positions_sync` / `_validate`）
全部写死 `CFG.mt5.symbol`。`Graph.build` 建的是无参 `MT5Client()`，
于是 5 个 Graph 各有正确的档案，却共用同一个数据源。

**危险在于完全不报错**：每个品种都"正常工作"、都产出信号，
只是所有信号都是黄金的。持仓侧更糟 —— 每个品种都去读黄金的持仓
再按自己的 magic 过滤 → 滤出空列表 → 每个品种都以为"我没有持仓"，
可以无限开仓、总手数闸恒为 0、无法加仓或平仓。

> **教训**：前面的测试覆盖了档案、点值、magic、venue、状态隔离，
> 但**没有一条断言"客户端绑定了正确品种"** —— 它们验证的是
> "参数是否被正确传递"，而这一环是"参数根本没被传递"。
> 所以新增了 `test_client_has_no_hardcoded_default_symbol_in_queries`
> （**源码级**静态断言，行为测试抓不到这类遗漏）
> 与 `test_multi_symbol_rounds_have_distinct_prices`
> （端到端：收盘价必须互不相同）。
> **"跑通不报错"不等于"跑对"** —— 开多品种后请核对各品种报价是否合理。

顺带修复：`mt5.initialize()` 是进程级全局操作，多品种并发初始化会互相
打断，已加模块级 `_INIT_LOCK` 串行化；`symbol_select` 改为选入本实例
品种（不选入 Market Watch 会让 `copy_rates_from_pos` 返回 None）。

### 事故：下单 magic 写死全局值（2026-10-09，同一天发现）

修掉上面那个缺陷后按同一线索系统排查"还有哪些跨品种共享状态"，
又发现 5 处，其中两处是 HIGH。**它们的共同特征：单品种黄金下完全正常，
只在多品种时才暴露。**

#### 1. 下单 magic 写死 `CFG.mt5.magic`（资金安全）

`OrderPlan` 加了 `symbol` 字段却**漏了 `magic`**，于是 `_build_request`
只能写死 `CFG.mt5.magic`（= 20260918）。而全仓库的"我的持仓/挂单/交割单"
过滤**只按 magic、没有一处按 symbol**：

| 品种 | 档案 magic（过滤用） | 实际写入的 magic | 一致 |
|---|---|---|---|
| XAUUSDm | 20260918 | 20260918 | 是 |
| BTCUSDm | 20260919 | 20260918 | **否** |
| USOILm | 20260920 | 20260918 | **否** |
| EURUSDm | 20260921 | 20260918 | **否** |
| USDJPYm | 20260922 | 20260918 | **否** |

后果：非黄金品种**查不到自己的持仓** → `_used_lots()` 恒为 0（总手数闸
失效、可无限开仓）、每轮重复市价开新仓、止盈止损改不动、
`DealFeedback` 收不到交割单（胜率/熔断/贝叶斯反馈静默失效）。
更糟的是 4 个非黄金品种**互相看见**（实际都带 20260918），
止损/平仓提案可能发到**别的品种**的持仓上。

**这不是推断，账户里有现场证据**（当天测试残留的持仓）：
```
ticket=2659117653  BTCUSDm  magic=20260918   <- 黄金的 magic 挂在比特币上
ticket=2659179879  EURUSDm  magic=20260918   <- 同上
ticket=2659226006  EURUSDm  magic=20260921   <- 12:07 修好之后的，正确
```
前两笔成了**孤儿持仓**：任何品种按自己的 magic 都认领不到，
永远不会被移损/止盈/加仓逻辑管理，只能靠 broker 端 SL/TP。

> 逃过测试的原因：原有测试只断言了 `req["symbol"]`，
> **没有一条断言 `req["magic"]`**。
> 另加一条**源码级**测试断言全部 6 个下单种类都带 `symbol=` 与 `magic=`
> —— 行为测试通常只跑到 1~2 条分支，漏改的分支要等实盘走到才暴露。

#### 2. 日志品种标签并发串台

标签原先用模块级全局变量（`global _symbol`），而 runner 用
`asyncio.gather` **并发**跑各品种：

```
set_symbol(sym) -> await g.run_round(rid)   # 内部大量 await，会让出
```

全局变量在 await 点被**其它品种**覆盖。实测（旧实现，5 品种并发）：
**4 个**品种的日志被贴上最后一个品种的标签：

```
owner=XAUUSDm   记录里的 symbol='USDJPYm'   <- 串台
owner=BTCUSDm   记录里的 symbol='USDJPYm'   <- 串台
```

于是 `logs/*.jsonl` 里绝大部分记录的 `symbol` 字段是错的，
按品种归因/统计/告警全部失真 —— 而这个标签的意义**正是**做归因。
改用 `ContextVar`（asyncio 下天然按任务隔离）后 5/5 正确。

> 逃过测试的原因：原测试是**同步顺序**调用，中间没有 await 点，
> 所以一直是绿的。新测试用真并发。

#### 3. 其余三处（中危）

- **`_save_position_adds()` 写到了共享目录**：写 `data/position_adds.json`
  而读 `data/<品种>/position_adds.json` —— **读写路径不一致**。
  5 个品种都往同一个文件写（互相覆盖），但读的时候那里从来没有文件
  → 每个品种都从 0 开始计数 → `max_adds_per_position` 闸失效。
  这类"写一个地方、读另一个地方"的错**永不报错**，只是数据静默丢失。
- **`levels.py`(11 处) / `shrink.py`(3 处) 定价写死 `round(..., 3)`**：
  `machine.py` 已改成按品种 `digits`，这两处**漏改了**。
  对 EURUSDm（digits=5）会把 `1.12419` 截成 `1.124`（偏 **20 个 point**）。
  危害不止显示 —— `sl_dist`/`tp_dist` 会**进入手数反推**与 `min_rr`
  赔率校验，所以错价会直接改变**实际下单手数与单笔风险**。
- **金十 `search_flash` 上游查询写死 `keyword="黄金"`**：
  `news_keywords` 虽已按品种取值，但只用于**本地筛选**；
  拉取时仍只查黄金快讯，于是比特币的 ETF/监管、原油的 OPEC/EIA 新闻
  根本拉不回来，`news_keywords` 形同虚设。
- **`SymbolProfile.max_lot` 是死配置**：注释写明"覆盖 `CFG.max_lot`"、
  5 个品种都填了值，但全仓库只读 `CFG.max_lot`，零引用。
  今天不产生错值（恰好都等于 0.06），但给某品种单独设上限会完全没反应。

> **方法论教训**：源码 grep 式断言（"`profile.max_lot` 出现在源码里"）
> 会被别处的同名引用**误判为通过**。加强测试时把每一项都退回旧实现跑
> 证伪，第一轮就抓出**两个测试根本锁不住修复**（`shrink` 只验了
> `entry` 没验 `tp`/`sl`；`max_lot` 只做了 grep）。
> **必须驱动真实调用路径并观察行为差异。**

### 事故：测试进程真实下单（2026-10-09，工具链缺陷）

`.env` 里是 `TRADE_MODE=live`，而 `tests/conftest.py` 此前
**只隔离了日志与状态目录，没有碰 `trade_mode`**。`Executor.execute()`
的守卫是 `if CFG.trade_mode == "dry_run": 不发送` —— 于是 live 下
测试进程会**直接 `order_send`**。而端到端测试
（`test_multi_symbol_rounds_have_distinct_prices`）调用的是**真实的**
`Graph.run_round()`，跑完整条「采集→分析→融合→风控→执行」链路。

实测后果（账户里真实存在，非推断）：11:38 / 11:57 / 12:16 三笔
`goldagent-open` 实盘仓位，正是迭代那几条测试的时刻 ——
上面提到的两笔孤儿持仓就是**测试跑出来的**。

**修法**：`conftest.py` 新增两道守卫 ——

1. `_never_trade_live`（session 级 autouse）：把 `trade_mode` 钉成
   `dry_run`，测试结束还原；
2. `_assert_not_live`（function 级 autouse）：每条测试入口再兜一层，
   发现 `live` 立即失败而不是悄悄下单。

**验证**：跑测试前后对比持仓 ticket 集合，完全一致（只有浮盈变化）；
两层守卫都移除后测试进程看到的确是 `live` —— 证明守卫必要而非装饰。

> **教训**：隔离了日志和状态目录**不等于**隔离了副作用。
> 只要测试会调用真实的执行链路，就必须同时钉死"是否真的下单"这个开关。
> 另外：这次是**用户自己发现**账户里多了不认识的持仓才暴露的，
> 测试全绿。**"测试通过"永远不能替代"核对真实世界状态"。**

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
