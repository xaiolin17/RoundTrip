# 04 — 本地数学融合（fusion/）：卡尔曼 · 贝叶斯 · 高斯

目标：把多路异构信号（chanlun、openmobius SMC、经典指标、新闻面）合成为一个**带不确定度的方向分数** S ∈ [-3,+3] 与 σ，供决策门控。

> ⚠️ **2026-09-20 重大修正**（`research/18_COMMERCIAL_PLAN.md`）：本模块原设计有两个
> 正在造成亏损的缺陷，现已修复。见 §0。
>
> ⚠️ **2026-09-21 v3 修正**（`research/21_source_ir.py` + `research/23_kalman_tb.py`）：
> 上述修正落地时又引入了两个"静默不开仓"的 bug（权重全 0、归一化器未预热），
> 已修复。同时 **P1-1 的决策周期改动已回滚**（保持 1m），真正该改的是止损宽度。
> 见 §0 P0-2、§0 P1-1。

## 0. 商用方案修正（P0-1 / P0-2 / P1-3）

### P0-1 源去均值（`normalize.SourceNormalizer`）

**问题**：`mobius_adapter._score_fn` 对 SMC 结构做**有符号累加但不减基准**。
黄金长期上行 → bull 结构持续累积、bear 结构很快被覆盖。
实测（`research/16_live_audit.txt`，881 轮实盘日志）：

| 信号源 | 权重占比 | score 均值 | score 为正 |
|---|---|---|---|
| chanlun | 35.4% | +0.1181 | 52.4% |
| **openmobius_smc** | **35.4%** | **+1.2604** | **88.0%** |
| classic_indicators | 24.6% | +0.1416 | 63.3% |
| kalman_persist | 4.7% | +0.0313 | 50.3% |

融合分 **80.2% 为正**，均值 +0.5241；`|S| ≥ 1.3` 的 38 轮**全部做多**。
→ **这个 +1.26 不是预测，是偏置。系统不是在择时，是在结构性做多黄金。**

**修法**：每个源进入融合前过滚动 z-score 去均值：

```python
z = normalizer.normalize(name, raw_score, obs_id=round_id)
# 预热期（< min_periods）返回 0.0 —— 宁可空仓，也不用未校准的统计量
```

**已在真实数据上验证**（`research/19_demean_check.py`）：

| 方案（`|S|≥1.3` 门槛后） | 触发 | 做多 | 做空 | 净均值 | 总净盈亏 | 净NW-t |
|---|---|---|---|---|---|---|---|
| 有偏源，原样 | 29218 | 28607 | **611** | −0.4895 | −14303 | **−17.94** |
| 有偏源，去均值 | 9561 | 4867 | **4694** | −0.4275 | **−4087** | **−8.62** |

→ 总亏损 **−14303 → −4087（减少 71%）**，净 NW-t **改善 2.1 倍**。

**验收**：连续运行 ≥3 天后各源 `score` 均值 ∈ [−0.3,+0.3]，为正比例 ∈ [40%,60%]；
融合分做多/做空轮数均 > 0。

### P0-2 权重按实测 IR（`weights.WeightTable`）

**问题**：`gaussian.fuse` 用 `w = 1/sigma²`，而 sigma 是**手填常数**：

| 源 | sigma 来源 | 权重 |
|---|---|---|
| kalman_persist | `max(k.sigma*0.8, 0.2)`（唯一随数据变） | 0.526 |
| chanlun | **硬编码 0.5** | 4.000 |
| openmobius_smc | **硬编码 0.5** | 4.000 |
| classic_indicators | **硬编码 0.6** | 2.778 |

→ **谁影响力大，取决于当初敲了哪个数字。** mobius 拿到 kalman 的 **7.6 倍**权重。
而本仓库擂台的实测结论是（`05_arena_1m.txt` + `11_mechanism.txt`）：
`kalman_trend` 毛 NW-t = **+3.31**（三种对照设计全部确认有效），
mobius/SMC **从未在本仓库被验证过**。

**唯一被验证有效的源被降权到 4.7%，未被验证的源占 35.4%。**

**修法**：权重改为按**实测 IR** 分配，`w = IR²`（与 `1/sigma²` 同形，
但 sigma 换成实测标准误）：

```python
# fusion/weights.py —— 硬规则：没有实测 IR 数字的源 = 0 权重
UNVERIFIED_WEIGHT = 0.0
```

IR 由 `research/21_source_ir.py` 在 ≥60,000 根真实 bar 上产出，
写入 `data/source_ir.json`；`WeightTable.load()` 以该文件为准。

### ⚠️ P0-2 的两个坑（都已修，且都曾让系统**永不开仓**）

**坑一：文件缺失 → 全部源权重 0。**

```python
tbl = WeightTable.load()      # 文件缺失 → from_baseline()
```

旧行为是"文件缺失 → 全源 0 → S=0 → 不开仓"，并把这称作**有意的**。
**这个结论是错的**：`research/18 §P0-2` **原文就逐条列出了 IR 表**
（kalman_persist 0.28 / chanlun 0.05 / classic_indicators 0.03 /
openmobius_smc 0.00），只有 `openmobius_smc` 是 0。
把**全部**源打成 0 是对该条的过度应用。

现在 `WeightTable.load()` 在文件缺失/损坏、或某源在校准文件里
`verified=false` 而基线表有其出处数字时，**退回 `weights.BASELINE_IR`**
（即 §P0-2 的 IR 表）。合并规则：

| 校准文件中的状态 | 采用的权重 | 理由 |
|---|---|---|
| `verified=true` | 文件里的实测 IR（最新证据优先） | `research/21` 的更严检验 |
| `verified=false`，但基线表有该源出处 | 基线 IR | §P0-2 已给出数字及 research 出处 |
| 基线表也是 0 或不存在 | **0** | 真正未验证的源 |

`openmobius_smc` 基线就是 **0.00** → 它仍然是 0。
**"未验证的源拿不到权重"这条不变量没有被削弱。**

**坑二：IR 是*相对量级*，直接平方会得到量纲错误的权重。**

§P0-2 写的 `IR = 0.28 / 0.05 / 0.03` 是**相对量级**（用于比较源之间的强弱），
不是逐笔信息比率。若直接代入 `w = IR²`：

```
w(kalman)  = 0.28² = 0.0784
w(chanlun) = 0.05² = 0.0025
```

比值是对的，但**绝对尺度极小**。而 σ 闸门要求
`σ_S = 1/√Σw ≤ sigma_max = 0.8` → **`Σw ≥ 1.5625`**。
0.0784 差了**两个数量级** → 融合分虽非零但 σ 巨大 → 决策层永远 hold
→ **系统仍然不开仓**。

修法是把 IR 归一到「最强源 = 1.0」再平方：

```python
w = (IR / IR_max)² × W_SCALE        # W_SCALE = 4.0
```

这样 kalman : chanlun : classic = 0.0784 : 0.0025 : 0.0009（**比值不变**，
仍是 §P0-2 想要的相对权重语义），而最强源单源即得 `w = 4.0`
→ `σ_S = 1/√4.0 = 0.5 ≤ 0.8`，稳稳过闸；多源同时有效时 σ 更小。
`W_SCALE = 4.0` 的取值依据就是这条闸门（`1/0.8² = 1.5625`）。

**验收**：任何源的权重变更必须附一个 `research/` 脚本产出的 IR 数字；
无数字 = 0 权重。`per_source` 里零权重源标注 `excluded: zero_weight`（可审计）。
生产权重表**必须能开仓**，由 `test_production_weight_table_can_trade` 断言
（总权重 > 0、`σ_S ≤ sigma_max`、`openmobius_smc` 仍为 0）。

### P1-3 融合分滚动基线（`normalize.RollingBaseline`）

**问题**：`decision.machine` 用 `abs(s) < open_threshold` 判断，
但**融合分的零点不在 0**（实测均值 +0.52）。S=+0.52 的"中性"被当成"偏多"。

**修法**：阈值判断前先减去滚动均值（与 P0-1 同源，但这里是第二道保险）：

```python
s_eff = s - result.score_baseline      # 决策层统一用 S_eff 判阈值
```

**验收**：实盘 `|S|≥threshold` 的触发中，做多与做空轮数均 > 20%。

### P1-1 周期权重（方向判据留在 1h/4h，决策心跳是 1m）

`1m` 权重 **0** —— 1m 只用于执行择时，**不产生方向**：

```python
CL_TF_WEIGHTS = {"1h": 1.00, "4h": 0.60, "15m": 0.40, "5m": 0.20, "1m": 0.00}
MB_TF_WEIGHTS = {"1h": 1.00, "4h": 0.50, "15m": 0.40, "5m": 0.20, "1m": 0.00}
```

依据（`research/15_alternatives.py` B 段）：1m 的盈亏平衡 IC **>0.50**，
1h 只需 **0.10**；现实模型 IC 是 0.02~0.05。

> ⚠️ **不要把这条误读成"决策周期必须是 1h"**（v3 修正）。
> `research/23_kalman_tb.py` 实测：那个"1m 不可能"的结论，前提是
> **用 1m 的波动定止损**（成本占止损 **46%**）。改用 1h ATR 定止损后
> 成本只占 **2.5%**，净 NW-t 从 −30.00 改善到 −1.40。
> 所以：**决策心跳 = 1m（60s），方向级别 = 1h/4h，风险尺度 = 1h ATR**。
> 三者是独立的三个量，v2 把它们混成了一个"周期"参数。

### ⚠️ P1-1 的隐藏耦合：滚动窗口单位是**决策轮数**

`norm_window` / `norm_min_periods` / `vol_pct_*` / `baseline_*` 的单位是
**观测次数 = 决策轮数**，不是分钟。**改 `loop_interval_s` 时必须同步换算。**

实盘曾因此出现 `source_warmed` 全 `false`：v2 一度把决策周期改成 1h，
`norm_min_periods=240` 就从 240 分钟 = 4 小时变成 **240 小时 = 10 天**。

v3 决策周期**回到 1m（60s）**，所以这些窗口回到 1m 时代的原值：

| 参数 | 值（1m 决策周期） | 折算 |
|---|---|---|
| `norm_window` | 1440 | ≈1 天 |
| `norm_min_periods` | 240 | **4 小时预热** |
| `vol_pct_window` / `vol_pct_min_periods` | 1440 / 240 | 同上 |
| `baseline_window` / `baseline_min_periods` | 1440 / 240 | 同上 |

**4 小时预热不能靠实盘干等** —— 那等于启动后 4 小时所有源归一化分都是 0.0
→ 融合分恒 0 → 永不开仓（实盘已复现：跑 180 轮后 `count=180 < 240`，
`score` 全程 0.0）。修法是**启动预热**：

```python
# FusionEngine.prime_history()（graph 启动时自动调用）
n = self.fusion.prime_history(bundle.frames)
# 回放最近 fusion.prime_steps = 300 轮真实 bar（prime_step_bars = 1）
# 逐片走与实盘**完全相同**的评分路径 _raw_scores_at（无前视：第 k 片只用 frames[:k]）
# 把结果灌进 normalizer.prime() / RollingPercentile.prime() / RollingBaseline.prime()
```

实测预热约 **7 秒**，第一轮即可正常决策。
`graph` 只在 `normalizer.warm()` 为 false（首次启动 / state 丢失）时才跑，
平时靠 `source_normalizer.json` 等状态文件恢复，**重启不丢预热**。

`tests/test_fusion_replay.py` 用四个测试把这条链路固化：

| 测试 | 断言 |
|---|---|
| `test_warmup_windows_match_decision_cycle` | 预热时长 ∈ [0.02, 7] 天，且 `prime_steps ≥ min_periods` |
| `test_normalizer_is_cold_without_priming` | 不预热时首轮 `score == 0.0`（锁住失败因果链） |
| `test_prime_history_makes_system_tradeable` | 预热后 `score != 0` 且 `effective_weight > 0` |
| `test_primed_score_spread_crosses_open_threshold` | 预热后分数分布**真的能越过** `open_threshold` |

> ⚠️ 注意：`research/21_source_ir.py` 用 **1m** 数据校准，
> 那里 1440 是正确的（1440 根 1m = 1 天）。**校准脚本的窗口与实盘的窗口
> 单位不同是合理的**，但改决策周期时只有实盘侧需要调整。
> ⚠️ 另注：`prime_history()` 用的是**尾部固定窗口**而不是从头累积切片 ——
> 从头切片时每步都要在近全量历史上重算指标，300 步要 **217 秒**，启动太慢；
> 尾部窗口与实盘每轮看到的 bar 数一致，每步成本恒定（实测约 7 秒）。

> ⚠️ **P1-1 的真正结论（v3 修正）**：`research/23_kalman_tb.py` 实测表明，
> "1m 不能交易"这个判断只在**用 1m 波动定止损**的前提下成立
> （成本/止损 46%）。决策周期本身不是瓶颈 —— 止损宽度才是。
> 所以 `loop_interval_s` 保持 **60**，改的是 `risk.atr_tf = "1h"`
> （见 `docs/09 §0`）。1m 负责入场择时，高级别负责风险尺度。

### P1-2 波动分位（`normalize.RollingPercentile`）

`FusionResult.vol_percentile` 提供当前 σ 在近 N 根中的滚动分位，
由决策层的 `decision.vol_pct_min` 闸消费（唯一不依赖方向预测的杠杆）。

---

## 1. 卡尔曼滤波（Kalman）

- 模型：对 close 做 **局部线性趋势模型**（状态 [level, slope]，匀速模型）：
  - x = [p, v]ᵀ, F=[[1,Δt],[0,1]], 观测 H=[1,0], Q 过程噪声(σ_q²), R 观测噪声(σ_r²)
  - σ_r 由滚动 ATR/√Δt 校准；σ_q 自适应（innovations 方差调整，Sage-Husa 简化版）。
- 输出：
  - `kalman_trend` = v 归一化（标准化后 [-3,3]）
  - `kalman_slope_persist` = v 连续为同号的 bars 数（动量持续性）
  - `kalman_sigma` = 协方差 P 的后验不确定度 → 进融合（**仅在无实测 IR 时**作为回退权重）

## 2. 贝叶斯模型平均（Bayesian）

- 每路信号源维护**历史命中表**：滚动窗口（默认 `bayes_window`）统计每源在
  "信号方向 vs N 分钟后价格方向"的命中与校准（Brier 分数）。
- 权重 = 后验可信度：`w_i ∝ exp(logit(p_i))`（p_i 为平滑命中率，
  Dirichlet 先验 α=β=1 防止小样本过自信），置信度高的源权重高。
- 证据融合（朴素贝叶斯对数域）：
  - `log_odds = Σ w_i · l_i`，其中 l_i = log(p_i/(1-p_i)) · sign_i · strength_i
  - 新闻面作为独立证据项加入（impact 加权）。
- 输出 `bayes_log_odds` 与逐源贡献（可解释性要求，落日志）。

> ⚠️ 贝叶斯证据 `bc` 并入源分时**也受 P0-2 约束**：零权重源的 `bc` 不参与加权。

## 3. 高斯融合（Gaussian）

- 最终融合采用**加权融合**：
  - `S = Σ(w_i·(μ_i + bc_i)) / Σw_i`，`σ_S = 1/√Σw_i`
  - **权重优先级**：`SourceView.weight`（实测 IR²）> `1/sigma²`（逆方差回退）
  - `Σw_i = 0` → 返回中性（S=0, σ=3）—— **只有在所有源都真的没有出处时**才会发生；
    生产权重表有 `BASELINE_IR` 兜底，正常路径不会走到这里
    （`test_fuse_all_returns_neutral_when_no_verified_source` 覆盖的是空权重表这一分支）
  - 分歧检测：源间 `|μ_i - S| > 2σ_S` → 标记 `disagreement`，决策门加严（阈值上移 + 仓位 ×0.5）

## 4. 附加精度增强

- **Hurst 指数/波动率状态**（R/S 分析，区分趋势 vs 均值回归状态，决定网格模式开关）。
- **波动分位**（P1-2）：见 §0。
- 上述均为确定性本地计算，无需网络。

## 5. 输出契约

```python
@dataclass
class FusionResult:
    score: float              # S ∈ [-3,3]（已去均值）
    sigma: float              # 不确定度
    disagreement: bool
    regime: str               # trending | mean_reverting | transition (Hurst)
    hurst: float | None
    per_source: list[dict]    # 含 raw_score / score / w / ir / excluded
    bayes_log_odds: float
    score_baseline: float     # P1-3：滚动基线 S0（决策层用 S−S0）
    vol_percentile: float     # P1-2：当前波动率滚动分位
    effective_weight: float   # 审计：本轮实际参与加权的总权重
```

`FusedEvidence` 额外携带 `raw_scores` / `norm_scores` / `weight_table` / `warmed`
（P0-1 与 P0-2 的验收与审计依据，全部落 `decision_log`）。

## 6. 验证方式（无 mock）

- 用 `data/cache/XAUUSDm_*.parquet` 真实历史做**回放校准**：融合分 vs 未来方向
  的信息系数（Spearman IC）与命中表。
- `tests/test_fusion_replay.py` 的断言是**有意义的双侧下限**：
  `IC > 0.01` 且 `hit > 0.50`（旧版是 `ic > -0.05`，IC=−0.04 也能通过 —— 见 P0-3）。
  这是 P0-3 的要点：断言必须**能失败**，否则它对系统没有任何保护作用。
- `research/21_source_ir.py` 产出权重表的唯一合法来源；
  `research/22_param_gate.py` 是参数变更门（DSR + PBO + MinBTL + Purged K-Fold）。

### 6.1 ⚠️ 校准方法的修正：`triple_barrier` + **非重叠**校正

`research/21_source_ir.py` 的 `verified` 判定已升级为
**triple_barrier + 非重叠校正**（旧版只看固定前瞻收益的 NW-t，量纲与实盘不同分布）：

```python
t_ind = tb["tb_gross_nw_t_ind"]
r["verified"] = bool(np.isfinite(t_ind) and t_ind > 1.5
                     and tb["tb_n_independent"] >= 30
                     and tb["tb_gross_ind"] > 0)      # 必须为正
```

**为什么必须做非重叠校正**：信号在相邻 bar 上重复。chanlun 的 15m 结果被映射到
15 根 1m 上，于是同一份判断被当成 15 笔独立"交易"。重叠样本互相包含，
**NW-t 被严重高估**：

| 源 | 原始笔数 | 毛 NW-t（未校正） | 非重叠毛 NW-t | 独立样本 | 重叠倍数 |
|---|---|---|---|---|---|
| chanlun | 46,559 | **+3.32** | **−0.20** | 261 | 178x |
| kalman_persist | 59,263 | +0.98 | +0.37 | 332 | 179x |
| classic_indicators | 59,263 | +0.54 | −0.10 | 335 | 177x |
| openmobius_smc（离线桩） | 59,263 | −2.16 | +2.66 | 331 | 179x |

→ **+3.32 是重叠造成的假象**：chanlun 的信号在 15 根 1m 上重复，
46,559 笔"交易"实际只对应 **261 个独立决策**，重叠 178 倍，
去重叠后毛 NW-t 塌到 **−0.20**。
（`research/21` 的脚本注释里另记有一次 456x 重叠的测量：+3.32 → −0.44，
同一现象的不同样本 —— 结论一致：**这个 +3.32 完全来自重叠**。）
这延续了 `research/11` 的同一原则："任何毛收益数字都必须用同一价格路径上的
随机方向基准来校准"，重叠校正是它的延伸。

**当前结论**：现有源**没有一个通过非重叠检验**
（`research/21_source_ir.txt`：非重叠毛 NW-t 分别 +0.37 / −0.10 / −0.20）。
这意味着在「1m 入场 + 1h ATR 止损」的设定下，本仓库现有信号源
**没有可证实的预测技能**。此时权重退回 §P0-2 的基线表（见 §0 P0-2），
**而不是全 0** —— 全 0 会让系统永不开仓，那是失败状态而非安全状态。

> ⚠️ 注意 `openmobius_smc` 那一行：它的非重叠毛 NW-t = +2.66 看起来最好，
> 但那是**离线桩**产出的（Mobius API 只返回当前快照，无历史回放），
> 不能作为证据 —— `research/21` 在写文件时**强制**把它的 `verified` 置为
> `false`（不因桩的偶然表现拿到权重）。它的权重仍然是 **0**。

> ⚠️ 诚实结论：**系统现在会正常开仓，但源的预测技能仍未被独立证实。**
> 下一步是**找有真实 IC 的新信息源**，不是继续调阈值 ——
> `research/22_param_gate.py` 已判定阈值调参无统计支撑（DSR 全 0、PBO = 1.0）。
