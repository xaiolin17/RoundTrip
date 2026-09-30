# 06 — 决策状态机（decision/）+ LangGraph 编排（agent/）

> ⚠️ **2026-09-20 修正**（`research/18_COMMERCIAL_PLAN.md`）：本模块的阈值判定
> 有两处结构性缺陷，已修复。见 §3.0。

## 1. 状态定义

```
IDLE          无持仓无挂单
PROPOSING     已生成候选，等待风控门
OPEN_LIVE     下单中（市价）
PENDING_GRID  网格挂单已放（等待成交）
HOLDING       持仓管理中（移动止损/分批止盈）
GRID_LADDER   网格加仓中
MARTIN_REVERSE 反向马丁组激活
EXIT          平仓执行中
SAFE_HOLD     异常安全态：只允许平仓/收紧，禁止新开仓
```

转移条件由"证据包"驱动（融合 S/S0/vol_pct、σ、chanlun 信号与 audit 门、
SMC 结构、新闻、账户状态、熔断器）。

## 2. 每轮决策输出（ActionProposal）

```python
@dataclass
class Proposal:
    kind: str        # open_market | place_grid | add_layer | close_position | modify_sltp | hold
    direction: str   # LONG|SHORT
    entry: float|None      # 限价/挂单价；close/modify 时为 ticket
    tp_struct: float|None  # 结构位 TP / 新 SL
    reasons: list[str]
    evidence_ids: list[str]      # 追溯到融合日志
```

## 3. 关键判定逻辑

### 3.0 商用方案修正（P1-2 / P1-3 / LLM 主路径）

**P1-3 阈值零点校正**：`abs(s) < open_threshold` 的判据是错的 ——
融合分的零点不在 0（实测均值 **+0.52**，`research/16_live_audit.txt`）。
S=+0.52 的"中性"被当成"偏多"。修法：

```python
s_eff = effective_score(r.score, r.score_baseline)   # S_eff = S − S0
# 所有阈值判定（开仓/平仓/加仓/撤单）统一用 s_eff
```

**P1-2 波动 regime 闸**：`vol_percentile < decision.vol_pct_min` → hold。
这是**唯一不依赖方向预测的杠杆**（`research/12_levers.py` C1：
≥90% 分位时毛边际 +171%、净 NW-t 改善 7 倍）。默认关闭（0.0），
需先用回放确认再启用。

**LLM 主路径**（`research/20_llm_audit.txt`）：旧版 `ctx.llm = None` 时
`aligned = False` → **永远走 place_grid**（实测 30 次挂单 vs 16 次市价）。
现在：

- `opposed`（verdict 与信号反向且 `conf ≥ llm_adverse_conf`）→ **hold，不开仓**
  （这是**单轮**行为：LLM 明确反对时才放弃这一轮，不代表系统不开仓 ——
  预热 + 权重表修好后实测 58% 的轮次会产出 `place_grid`）
- `llm_available=False` 且 `allow_grid_without_llm=False` → **hold**（不默认挂网格）
- LLM 参与但说中性 → 仍可走网格（正常降级，不是缺失）

### 3.1 空仓开仓门

按顺序过闸：

1. `σ ≤ σ_MAX`（`fusion.sigma_max`）
2. 新闻无高危窗口
3. **`vol_percentile ≥ decision.vol_pct_min`**（P1-2）
4. **`|S_eff| ≥ open_threshold`**（P1-3）
5. **LLM 未明确反对**（`opposed` → hold）
6. regime 匹配：`mean_reverting` → 只允许网格限价单
7. LLM 对齐（`verdict == 方向` 且 `conf ≥ llm_align_conf`）→ `open_market`；
   否则 → `place_grid`（或 LLM 缺失时 hold）

### 3.2 持仓平仓评判（主动平仓）

> **2026-09-30 变更（用户要求）**：「除非行情和持仓方向不一致率**非常高**，
> 否则不轻易主动平仓，只修改止损和止盈位置（新止损止盈缩小时**不受
> 1.2 倍的比例影响**）」。因此**信号类**触发不再直接平仓，改为收窄 SL/TP；
> **保护性**触发仍保留平仓。

1. **行情与持仓方向不一致率**：尾部 `exit_adverse_window`（=20）轮里，
   逆向轮占比 ≥ `exit_adverse_rate`（=0.80）→ 平仓。
   - 取代原「`S_eff` 反号 ≥ `exit_threshold` 且**连续**
     `exit_persist_rounds` 轮」规则。原因见 §3.2.1。
   - 窗口 20 轮 ≈ 25 分钟（实测轮间隔中位 76s），足够构成"持续"。
2. LLM 反向 verdict 且 `conf ≥ llm_adverse_conf` → 平仓（保护性，保留）。
3. 新闻 `impact ≥ news_impact_close`（默认 0.8，**已走配置**）且与持仓反向
   → 平仓评估（保护性，保留）。
4. **移动止损锁盈**（取代原「利润回吐 50% 就平仓」）：浮盈 ≥
   `lock_profit_min_usd` 后把 SL 推到开仓价上方 `lock_profit_gap_usd`，
   让利润奔跑；仅当浮盈从峰值回落到保本线以下才离场。
   **信号回吐**（顺向信号峰值 ≥ `z_min` 后回落 ≥ `reserve_drop_z`）
   → **收窄止损止盈，不平仓**：把 SL 收到更紧处、TP 按
   `signal_exit_tp_rr` 同步收近，让仓位在下一次真实反向波动中自然离场。
   收窄是**一次性**的（`_tightened` 去重，防棘轮 —— 否则每轮 ×0.7 会
   几何收敛到点差以内，等于用几十轮慢刀把仓位磨死）。
5. 持仓 > `max_holding_h`（1m 短线设定为 **4h**；代码默认 48h）且浮亏 → 平仓换仓。
6. 浮盈 > $10 且 SL 仍在成本外侧 → 移损至盈利 $2 处（锁底搏上限）。

#### 3.2.1 为什么用「窗口不一致率」取代「连续 N 轮」

实测 09-23~09-30 共 **2283 个持仓决策轮，46% 是逆向轮**（逐日 29%~69%）。
在这种基础发生率下，逆向轮在随机游走下极易连续出现 —— 原「连续 3 轮」
规则实测触发 **129 次**（按连续段去重），属噪声驱动的过度交易，不是风控。
换成尾部窗口的**比例**后，同一批数据只触发 **7 次**（降 95%）。

> ⚠️ 上述数字是在**清除日志中的伪造轮次后**重算的。此前 09-30 的日志里
> 混有 19824 行 `round=1` 的合成记录（测试夹具 `round_id=1` + 一次性回放
> 脚本直接调用 `DecisionEngine.decide()`，而它内部会写 `decision_log`），
> 会把统计整体带偏。现已加结构性防护：`logging_util.jlog` **默认拒绝**
> 非实盘进程写生产 `logs/`，只有 `runner.main_async()` 调过
> `logging_util.set_live(True)` 之后才允许。

### 3.3 加仓（用户规则：每仓固定 0.01 手，同向最多 5 次）

阶梯式：分数与 LLM 置信**均须高于上一次**；第 3 次起门槛指数递增
（`last + base_gap × 2^(count−1)`），避免在震荡里连续加仓。

### 3.4 网格/马丁判定

见 `docs/05`。

### 3.5 LLM 角色

提供 `verdict` / `confidence` / `rationale` / `skill_audit` 作为
**主路径确认环节**与贝叶斯证据；**不产生订单参数**（架构规则）。

## 4. LangGraph 图

```
collect → analyze(parallel: chanlun×5 + mobius×4 + news) → fuse(去均值+IR权重)
   → llm_review(主路径: LLM-A 双 skill + LLM-B 新闻, 独立预算)
   → fuse(rev, obs_id 幂等) → propose(S_eff 判阈)
   → risk_check → execute → persist → (loop back)
异常路径 --> safe_hold
```

节点均为 asyncio 协程；`llm_review` 带预算器（review/news 分离）；
`execute` 节点内含对账（下单后 position_get 校验成交）。

## 5. 状态持久化与恢复

- 每次转移写 `state.json` + `decision_log.jsonl`。
- **融合滚动统计量持久化**（P0-1/P1-2/P1-3）：`source_normalizer.json` /
  `vol_percentile.json` / `score_baseline.json`。**重启不丢预热** ——
  否则每次重启都要空仓等 `norm_min_periods` 轮
  （1m 周期下 = **4 小时**）。
- **启动预热**：state 文件缺失或 `normalizer` 未 warm 时，
  `graph` 启动阶段自动调用 `FusionEngine.prime_history(bundle.frames)`，
  回放最近 `fusion.prime_steps = 300` 轮真实 bar（`prime_step_bars = 1`）
  灌满归一化器 / 波动分位 / 基线缓冲（实测约 **7 秒**），
  第一轮即可正常决策。**没有这一步，系统启动后 4 小时内不会开任何仓。**
- 加仓计数 `position_adds.json`、挂单桥接 `pred_orders.json` 同样持久。
- 启动恢复：读 state.json → MT5 实际持仓对账（magic 过滤）→ 不一致以 MT5 为准并告警。

## 6. 验收指标（落 `decision_log`）

| 事件 | 关键字段 | 验收标准 |
|---|---|---|
| `signals` | `raw_scores` / `norm_scores` / `source_warmed` | 各源归一化均值 ∈[−0.3,+0.3]、为正 ∈[40%,60%] |
| `signals` | `weight_table` | 未验证源 `w=0` 且标注 `excluded`；**`effective_weight > 0`**（否则系统永不开仓） |
| `signals` | `score_baseline` / `vol_percentile` | 基线随数据滚动，不恒为 0 |
| `signals` | `chanlun.*.failed_gates` / `confirmed` / `observed` | 未过门的信号必须落在 `observed` |
| `llm_review` | `available` / `review_coverage` | 覆盖率应远高于旧版 4.3% |
| `llm_review` | `chanlun_gates` / `smc_steps` / `caveats_disclosed` | LLM 必须走完两个 skill 的流程 |
| `signals` | `direction_bias` | 同向占比 ≤ 85%，否则熔断 |
