# 02 — 两个 Skill 的集成协议与降级矩阵（skills/）

> ⚠️ **2026-09-20 修正**：旧适配器**跳过了 skill 的强制流程**（见 §1.2、§2.2），
> 现按 SKILL.md 原文契约重写。

## 1. chanlun-trading-system（本地引擎）

### 1.1 基础调用

- 路径：`vendor/skills/chanlun-trading-system/src`（`sys.path` 注入，import `chanlun_visual.engine`）。
- 调用：`analyze_tf(df, timeframe, symbol=..., levels=...)`。
- 输入 bars：`[{date: ISO-8601 UTC, open, high, low, close, volume}]`；**时间必须严格递增**（引擎 DataQualityError fail-closed）。
- 输出（已实测 schema）：`meta` / `quality` / `bars` / `indicators` / `layers` / `state`
  - `meta.definition_mode="research_proxy"`（永远如实记录，不冒充严格缠论）
  - `state.structure` ∈ {trend_up, trend_down, center_oscillation, center_extension, center_breakout, transition_zhongyin, insufficient_history, unknown}
  - `state.candidate_signals[]`：`kind ∈ {B1,B2,B3,S1,S2,S3}_candidate`
  - `state.invalidation`（实测为 `list[str]`，适配器 join 成字符串）
  - `layers.{merged_bars, fractals, strokes, segments, centers, divergences}`
  - `centers[]` 含 `zg/zd/gg/dd`、`definition_mode`、`approximation_loss`
- 并发：纯 CPU 线性计算，多周期在线程池并发。
- 降级：异常 → `status=unavailable`，融合时权重 0，不阻塞。

### 1.2 严格原文自检门（Strict Original Audit Gate）——**新增，这是 skill 的核心契约**

SKILL.md 规定"任何操作性结论之前，过这道门"，共 8 门。适配器
（`chanlun_adapter._audit_gates`）逐门执行并把结果放进 `ChanlunResult.audit`：

| 门 | 判定依据 |
|---|---|
| `level_gate` | `trade_level` / `confirm_level` / `trigger_level` 均已点名 |
| `structure_gate` | `fractals` / `strokes` / `segments` 均有产物（结构链完整） |
| `type_gate` | `structure` ∉ {None, unknown, insufficient_history} |
| `comparison_gate` | 有背驰声明时，`compared_ids` ≥2 段且 `unit_type` 一致（同级别）；无声明则本门不适用 |
| `buy_sell_gate` | structure_gate ∧ type_gate |
| `trigger_gate` | 低级别触发；**我们无更低级别数据 → 恒为 False 并标注 `trigger_missing`** |
| `risk_gate` | `state.invalidation` 非空（**先写失效点，再谈收益**） |
| `downgrade_gate` | 任一门不过 → `output_mode ∈ {structure_proxy, observe}`，**绝不输出 buy_confirmed** |

**不可妥协规则 11/12/13 的逐信号校验**（`_confirm_signal`）：

- **规则 11（一买/一卖）**：需要 ≥3 个同级别段 + 存在背驰 + 背驰方向与信号同向
  + `baseline.supports_candidate` 为真（背驰须由**结构**支撑，
  不能只靠 MACD —— 规则 6）。否则 → `observe`，**不计分**。
- **规则 12（二买/二卖）**：需要点名"一买候选 + 它的第一次回抽测试"。
  引擎无 `signal_history` 时退回段结构近似（≥3 段且最近段方向匹配）。
- **规则 13（三买/三卖）**：需要有效中枢（`zg`/`zd` 存在）+ 价格确实离开中枢
  （三买 `close > zg` / 三卖 `close < zd`）+ 回拉状态有段结构支撑。

**旧版的问题**：直接把 `*_candidate` 映射成 ±1/±2/±3（仅乘 0.6 降权），
**完全跳过这些门** —— 这是对 skill 契约的违反。现在未过门的信号一律降为
`observe`（`score` 贡献 0），只有过门的才计分。

**输出新增字段**：`levels` / `audit`（8 门结果 + `output_mode` + `chain`）/
`confirmed_signals` / `observed_signals`（含 `audit_reason`）/
`compared_movements` / `next_observation` / `approximation_loss`。

**级别链**（1m 决策周期下的短线级别链 —— 注意：级别链说的是**分析级别**，
与决策心跳周期是两件事；决策周期保持 1m 不变，见 `docs/09 §0`）：
`review_level=4h`（方向）/ `trade_level=4h`（交易级别）/
`confirm_level=1h`（确认）/ `trigger_level=15m`（触发）。
（`DEFAULT_LEVEL_CHAIN`；`level_gate` 检查的是后三项。）

### 1.3 分数映射（通过 audit gate 后才生效）

- 结构分：`trend_up=+1 / trend_down=−1 / center_breakout=±0.5（按突破方向）/ 其余 0`
  （`type_gate` 未过则不给结构方向）
- 买卖点：`B3=+3 / B2=+2 / B1=+1`，`S3=−3 / S2=−2 / S1=−1`，
  `*_candidate` 后缀 ×0.6（候选未确认降权）
- **`risk_gate` 未过 → 整体 score 归零**（先写失效点，再谈收益）

## 2. openmobius-skill（Mobius Quant API + 知识库）

### 2.1 基础调用

- 路径：`vendor/skills/openmobius-skill/scripts/kb_klines.py`。
- 用法：进程内 aiohttp `POST /api/indicators`
  body `{exchange:"commodity", market:"spot", symbol:"XAUUSD", interval, limit, calc:[{name:"smc"}]}`。
- 限速与缓存：本地 LRU 缓存 TTL 60s；全局限速器 10 req/min 令牌桶，
  排队上限 5s，超时用上一份缓存（标记 stale）。

### 2.2 字段采集对齐 SKILL.md 的 7 步咨询顺序——**这是本次修正的重点**

SKILL.md 规定按 7 步顺序使用 SMC 字段。**旧版 `_fill` 只取了 3 个字段**
（`swing_structures` / `order_blocks_swing` / `fair_value_gaps`），
并把 `premium_zone` / `discount_zone` **硬置 None** ——
导致第 3、6、7 步**完全无法执行**。

实测 API 返回的完整 `objects` 字段（14 个）：

| # | SKILL.md 步骤 | API 字段 | 旧版 | 新版 |
|---|---|---|---|---|
| ① | Trend bias | `swing_structures` / `internal_structures`（取 bias） | 部分 | ✅ `trend_bias()` |
| ② | 最近结构事件（CHoCH > BOS） | 同上，取 `kind` | ✅ | ✅ `last_swing_event` / `last_internal_event` |
| ③ | Trailing extremes 标签 | `trailing_extremes`（Strong/Weak High/Low） | ❌ | ✅ `extreme_labels()` |
| ④ | Active Order Blocks | `order_blocks_swing` + `order_blocks_internal` | 部分 | ✅ `active_order_blocks()` |
| ⑤ | Active FVG | `fair_value_gaps` | ✅ | ✅ `active_fvgs()` |
| ⑥ | Equal highs / lows | `equal_highs` / `equal_lows` | ❌ | ✅ |
| ⑦ | Premium/eq/discount 位置 | `premium_zone` / `equilibrium_zone` / `discount_zone` | ❌（硬置 None） | ✅ `zone_of()` |
| — | 最近一根告警 | `alerts_last_bar` | ❌ | ✅ |
| — | swing/internal pivots | `swing_pivots` / `internal_pivots` | ❌ | ✅ |
| — | 数据新鲜度 | `data_meta.data_as_of_ms` → `last_bar_age_s` | ❌ | ✅ |

**打分按 7 步加权**（`_score_fn`）：

- 第②步：最近 3 条结构事件，**近端加权**（×1.0 / ×0.7 / ×0.5），
  CHoCH=±2.0（反转，优先级高于 BOS）、BOS=±1.5（延续）
- 第③步：`Strong High + Weak Low` → 确认看跌（−0.5）；反之看涨（+0.5）
- 第④⑤步：active OB / FVG 与现价的位置关系（±1.0）；
  **OB 与 FVG 同向交汇额外 ±0.5**（docs/02 §4）
- 第⑦步：premium 区做空加成（−0.5）、discount 区做多加成（+0.5）

> ⚠️ **本函数是"有符号累加"，天然带有标的漂移方向的常数偏移**：
> 黄金长期上行 → bull 结构持续累积 → 实测 88% 为正、均值 +1.2604。
> 这个偏移**必须**由 `fusion/normalize.SourceNormalizer` 的滚动 z-score 消除
> （research/18 P0-1）。`_score_fn` 只负责把结构映射到方向分，**不做去偏**。

### 2.3 降级矩阵

| 情形 | 行为 |
|---|---|
| Mobius 429/403 | 用缓存（≤`stale_max_age_s` 旧）+ 标记 stale，权重 ×0.7 |
| Mobius 超时/网络错 | 同上；无可用缓存 → `unavailable`（权重 0） |
| `smc` 返回空结构 | 视为"结构无信号"，`_score_fn` 返回 0.0，正常路径 |
| **无历史回放** | Mobius API 只提供**当前**结构快照 → `research/21_source_ir.py` 只能用离线桩，因此 **`openmobius_smc` 的 `verified` 恒为 false、权重 0**，直到补齐真实历史校准 |

### 2.4 必须在 prompt 中披露的 caveats（SKILL.md 要求）

- Swing pivots 只在形成后约 `swing_size` 根（典型 ~50 根）才确认，近期 pivot 可能仍会调整
- Order Blocks 是事后反推的，新形成的 OB 可能被后续 bar 修订
- 低波动 regime 下 FVG 触发频繁，需谨慎对待 FVG 数量
- **所有事件都是结构信号，不是入场触发器**；它们补充但不替代风控

## 3. 并发编排（分析阶段）

```
async gather:
  t1..t5: chanlun(1m/5m/15m/1h/4h)   (线程池；1m 权重 0，仅执行择时)
  t6..t9: openmobius smc(1m/5m/15m/1h)  # 限速器内
  t10:    news (金十)
all → fuse_all(obs_id=round_id) → LLM review（主路径）→ decision
```

## 4. 输出统一接口

两 skill 输出都映射到统一 `SignalEvidence`：

```python
@dataclass
class SignalEvidence:
    source: str            # "chanlun" | "openmobius_smc"
    timeframe: str
    score: float           # [-3, +3]，方向化（多正空负）；**已过 audit gate**
    confidence: float      # [0,1]
    invalidation: str|None # 失效点描述（risk_gate 要求非空）
    raw: dict              # 原始输出存档
    status: str            # ok | stale | unavailable
    # 新增（P0-1/P0-2 审计）
    raw_score: float       # 去均值前的原始分
    weight: float|None     # 实测 IR² 权重；None → 融合层按 0 处理
    ir: float|None         # 实测 IR
```

`ChanlunResult` 额外携带 skill 契约字段：`levels` / `audit` /
`confirmed_signals` / `observed_signals` / `compared_movements` /
`next_observation` / `approximation_loss`。
