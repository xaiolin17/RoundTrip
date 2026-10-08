# 00 — 总体架构与数据流

状态：定稿 v1（2026-09-18）· **v2 修正（2026-09-20，`research/18_COMMERCIAL_PLAN.md`）** ·
**v3 回滚（2026-09-21，`research/23_kalman_tb.py` 实测）**

> ⚠️ **v2 的三项结构性修正**（第 1 项已被 v3 实测推翻 —— 决策周期保持 1m，
> 真正要改的是**止损宽度**）
> 1. ~~**决策周期 60s → 3600s（1h）**~~ **→ v3 回滚：周期保持 1m（60s）**。
>    当时的理由是"1m 上每根都交易的成本是市场全部方向性收益的 99.5 倍"，
>    但那个论证的前提是**用 1m 的波动去定止损**。`research/23_kalman_tb.py`
>    在 60,000 根真实 1m bar 上（成本 0.52 USD 往返）实测：
>
>    | 止损基准 | 止损(USD) | 成本/止损 | 净NW-t |
>    |---|---|---|---|
>    | 1m ATR ×1.2 | 1.13 | **46.0%** | −30.00 |
>    | 15m 尺度 ×1.2 | 4.74 | 11.0% | −4.38 |
>    | **1h ATR ×1.2** | **20.80** | **2.5%** | **−1.40** |
>
>    成本是固定的，止损越窄成本占比越高。→ 真正的杠杆是**止损宽度**：
>    `loop_interval_s` 保持 **60**，新增 `risk.atr_tf = "1h"`（由
>    `graph._decision_atr` 读取），把成本/止损从 **46% 压到 2.5%**。
>    见 §2、`docs/09 §0`。
> 2. **LLM 从"触发式慢路径"改为"每轮主路径"**。实测 review 覆盖率仅 **4.3%**
>    （881 轮 38 次），导致 30 次 place_grid vs 16 次 open_market ——
>    系统绝大多数时候只能挂限价单。见 §2、`docs/03 §0`。
> 3. **信号源权重不再用手填 sigma**。改为实测 IR（`data/source_ir.json`），
>    **未验证的源权重为 0**。见 `docs/04 §0`。
>    （v3 补充：`WeightTable.load()` 在文件缺失时退回 `weights.BASELINE_IR`
>    —— 即 `research/18 §P0-2` 原文的 IR 表，其中只有 `openmobius_smc` 是 0。
>    把**全部**源打成 0 会让系统永不开仓，那是失败状态而非安全状态。）

## 1. 系统边界

```
┌──────────────────────────── 本机 (Windows) ────────────────────────────┐
│                                                                        │
│  MetaTrader5 Terminal (D:\MT5\terminal64.exe, 已运行)                   │
│      ↑ python API (MetaTrader5 pkg)                                    │
│  ┌──────────────────────────────────────────────────────────────┐      │
│  │                GoldAgent 主进程 (asyncio)                     │      │
│  │                                                              │      │
│  │  [Collector]  MT5 多周期行情 (1m..1d) + 账户/持仓              │      │
│  │       │  parquet 缓存 (data/cache)                             │      │
│  │  [Analysts 并发]                                               │      │
│  │    ├─ chanlun 引擎 (本地, 含 8 门严格原文自检)                  │      │
│  │    ├─ openmobius SMC (Mobius API, 限速 10/min + 缓存, 7 步字段) │      │
│  │    ├─ fusion (卡尔曼/贝叶斯 + **去均值 + IR 权重**)              │      │
│  │    └─ news (金十快讯, 独立预算)                                 │      │
│  │  [LLM 编排] runninghub deepseek-v4.1-flash (每轮主路径, 按 skill 流程) │      │
│  │  [Decision] 状态机 (S_eff = S−S0 判阈, 波动分位闸)              │      │
│  │  [Risk] 仓位(Half-Kelly/**Wilson 下界**/ATR预算) + 熔断         │      │
│  │         + **方向偏置监控**                                      │      │
│  │  [Executor] MT5 下单/平仓/修改SLTP (live)                      │      │
│  │  [Persistence] logs/*.jsonl, data/*.json                       │      │
│  └──────────────────────────────────────────────────────────────┘      │
└────────────────────────────────────────────────────────────────────────┘
        │                                  │
        ▼                                  ▼
 https://llm.runninghub.cn/v1      https://mcp.jin10.com/mcp
 (deepseek-v4.1-flash)             (快讯, token 见 .env)
        ▼
 https://api.mobiusquant.ai (openmobius, 匿名 10 req/min)
```

## 2. 主循环与并发模型

- **事件循环**：`asyncio`。所有外部 IO（MT5 API 除外——它本身是同步 C 扩展，用 `loop.run_in_executor` 包装；HTTP 调用用 `aiohttp`）均为异步。
- **周期心跳**：**默认每 60s（1m）一轮决策**（`decision.loop_interval_s = 60`）。
  v2 曾按 `research/18 §P1-1` 改成 3600s，v3 已回滚：`research/23_kalman_tb.py`
  实测表明 1m **入场**没有问题，问题是**用 1m 的波动定止损**（成本占止损 46%）。
  现在止损改由 `risk.atr_tf = "1h"` 定尺度（成本/止损 → **2.5%**），
  1m 负责**入场择时**，高级别负责**风险尺度**。
- **启动预热（必需）**：`norm_min_periods=240` 的单位是**决策轮数**，
  1m 周期下 = **4 小时**。不预热则启动后 4 小时内所有源归一化分都是 0.0
  → 融合分恒 0 → 永不开仓（实盘已复现）。`FusionEngine.prime_history()`
  在启动时回放最近 `fusion.prime_steps = 300` 轮真实 bar（`prime_step_bars = 1`）
  把缓冲灌满（实测约 7 秒），第一轮即可正常决策。
  见 `docs/04 §0 P1-1`。
- **1m 数据的双重角色**：既是决策心跳，也是执行择时的输入；
  但**方向判据仍不在 1m**（周期权重 0，`CL_TF_WEIGHTS["1m"] = 0`），
  1m 提供的是**入场时点**而非方向。
- **LLM 在主路径上**：每轮决策都执行 LLM 双 skill 评审
  （`llm.min_interval_min = 0`），review 与 news **分开计账预算**。
  仅在明显无信号的轮次跳过以省预算。
  LLM 缺失时**不默认放网格**（`decision.allow_grid_without_llm`），
  因为那正是旧版"30 次挂单 vs 16 次市价"的成因。
- **LLM 并发**：openmobius/chanlun 评审与新闻面 LLM 并发；两者都有独立超时
  （默认 60s / 30s）与降级路径。**任何 LLM 请求都带 `timeout` 与重试上限，
  失败即降级，不阻塞主循环**。
- **MT5 同步调用**：MetaTrader5 包是同步的；所有调用经 `run_in_executor` 进入线程池，避免阻塞事件循环。下单/改单串行化（单 worker executor），行情查询可并行。

## 3. 数据流（一轮决策）

```
t0  MT5 刷新: 多周期 OHLCV + tick + 账户 + 持仓
t0b 交割单反馈: 胜率(Wilson 下界) → 贝叶斯池 + 熔断器 + **方向序列**
t2  本地分析 (并发):
      chanlun.analyze_tf(1m/5m/15m/1h/4h) → 结构/中枢/背驰 + **8 门自检**
      mobius SMC(1m/5m/15m/1h)            → **7 步字段全采**
t2b fusion.fuse_all(obs_id=round_id):
      **各源滚动 z-score 去均值(P0-1)** → **实测 IR² 权重(P0-2)**
      → S / σ / regime / **S0 基线(P1-3)** / **波动分位(P1-2)**
      ⚠️ 仅未验证源（`openmobius_smc`）权重为 0；其余源用 IR 表 → S ≠ 0
t2b' 启动首轮前: prime_history() 回放 300 轮历史 bar 预热归一化器
      （否则前 4 小时各源归一化分恒 0.0 → S ≡ 0 → 永不开仓）
t2c 信号详情落日志 (含 raw_scores / norm_scores / weight_table / audit gates)
t4  LLM 主路径 (need_llm): LLM-A 双 skill 评审 + LLM-B 新闻面（独立预算）
      评审 prompt 强制走 chanlun 8 门 + SMC 7 步，输出 skill_audit
t5  LLM 新闻面并入融合（重算，obs_id 幂等）→ S_eff = S − S0
t6  Decision 状态机:
      **波动分位闸(P1-2)** → **|S_eff| ≥ 阈值(P1-3)** → LLM 一致性/反对
      → open_market / place_grid / hold
t7  Risk 门: 单笔风险 ≤ risk_pct × equity；Half-Kelly 用 **Wilson 下界**；
             **方向偏置熔断**；连亏 ≥ K → 冷却 T；拒绝则降级为观望
t8  Executor: MT5 order_send (live) / position_close / modify SLTP
t9  持久化: 决策日志 JSONL + 状态文件（含 fusion 滚动统计量，重启不丢预热）
```

## 4. 模块契约总表

| 模块 | 输入 | 输出 | 失败行为 |
|---|---|---|---|
| mt5.collector | symbol, timeframes | `OHLCVBundle`, `AccountInfo`, `PositionsView` | 抛 Mt5Error；主循环跳过本轮 |
| mt5.executor | `OrderPlan` | `ExecutionResult` | 抛 Mt5Error；状态机回滚不记账 |
| skills.chanlun | OHLCV bars (任一周期) | 结构+信号 JSON + **8 门 audit 结果** | 标记 unavailable，融合权重 0 |
| skills.openmobius | symbol, interval | SMC **7 步字段** JSON（Mobius API） | 限速/缓存降级，标记 stale |
| fusion | 各路信号分数+历史命中 | S, σ, S0, vol_pct, 分项贡献（含 raw/norm/权重） | 全部源权重 0 → S=0（中性）；启动时 `prime_history()` 预热 |
| llm.orchestrator | 分析上下文包（按 skill 契约组织） | `{verdict, confidence, rationale, skill_audit}` JSON | 超时/解析失败→无 LLM 分量（重试后降级） |
| news.collector | — | 快讯列表+情绪分 | 金十失败→无新闻分量 |
| risk | ActionProposal + 账户 | `ApprovedOrder` 或 REJECT(reason) | 熔断触发→强制 REJECT |
| decision | 全部证据 | ActionProposal / HOLD | 内部异常→安全态(持有+告警) |

## 5. 状态机（概览，详见 06）

`IDLE →(gate)→ PROPOSE →(risk)→ OPEN_LIVE → HOLDING ⇄ GRID_LADDER / MARTIN_ADD → EXIT →(cooldown)→ IDLE`
任一环节异常 → `SAFE_HOLD`（只管理不平仓不加仓，直到人工或条件恢复）。

## 6. 配置与可观测性

- 所有阈值集中在 `config.toml`；`.env` 只放密钥。
- **参数变更纪律**（`research/18 §P2-1`）：任何变更必须附 `research/22_param_gate.py`
  产出的 **DSR 数字**，且试验族规模 N 显式记录在 `data/trials.csv`。
  **没有 DSR = 回滚。** 现有调参记录（1.6→1.2→1.3）是用 3 笔交易调的，无统计支撑。
- 每轮写 `logs/decision_YYYYMMDD.jsonl`（完整证据包，含 P0-1/P0-2 验收字段）；
  交易写 `logs/trades.jsonl`。
- 异常分级：`WARN`（降级继续）/ `FATAL`（进入 SAFE_HOLD 并推送）。

## 7. 明确不做的事

- 不使用模拟/合成数据做测试（chanlun 引擎内置 demo 函数禁用于生产路径）。
- 不绕过风控门直接下单；任何手动干预必须在状态文件中留痕。
- 不在 LLM 回复中直接给出下单手数——仓位只由 risk 模块计算，LLM 只输出方向/置信度/理由。
- **不用未验证的信号源交易**：没有实测 IR 的源权重为 0。
  这比"用未验证信号赌方向"更符合"不亏"的目标（`research/18 §6`）。
  ⚠️ 但**这条只适用于真正没有出处的源** —— 当前唯一这样的源是
  `openmobius_smc`（Mobius API 无历史回放，`verified` 恒为 false）。
  其余源（`kalman_persist` / `chanlun` / `classic_indicators`）用的是
  `research/18 §P0-2` 的 IR 表，**系统会正常开仓**。
  该原则要守的不变量是"未验证的源拿不到权重"，不是"系统不开仓"。
  "权重全 0 → 永不开仓"不是安全态，而是**失败状态**（实盘已复现：
  `effective_weight=0.0` → `score=0.0` → 永远 hold）——
  一个不交易的交易系统没有任何价值。
  另外，权重表要在**启动预热之后**才有意义：`prime_history()` 未跑
  → 归一化器未 warm → 所有源归一化分为 0 → 同样永不开仓
  （见 §2 启动预热）。
- **不按信号反买、不互换止损止盈**：两者均已被实测证伪
  （净均值 −0.4606 → −0.5559 / −0.5098，见 `research/18 §4`）。
