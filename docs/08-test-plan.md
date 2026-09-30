# 08 — 测试计划（无 mock，真实数据）

原则：用户明确要求"尽可能不使用 mock 进行全流程全模块全方法函数的测试验证"。

> ⚠️ **2026-09-20 修正**：测试计划的通过标准有两处是"空转"的，已修正。
> 见 §3。
>
> ⚠️ **2026-09-21 v3 修正**：决策周期回滚到 1m（60s），并修掉两个
> "静默不开仓"的 bug（权重全 0、归一化器未预热）。**一个不交易的交易系统
> 是失败状态，不是安全状态** —— 旧测试 `test_production_ir_file_has_no_verified_source`
> 把这个 bug 断言成了预期行为，已删除并替换。见 §3.1.1、§3.1.2、§5。

## 1. 测试资产

- **历史真实数据**：`data/cache/XAUUSDm_15m.parquet`（MT5 拉取的长历史，回放主资产）；
  `D:\DDDDDDDDD\XAUUSD_1min_kline.parquet`（金十 1m，备用）。
  `data/cache/XAUUSDm_{1m,2m,5m,10m,15m,30m,1h,4h,8h,1d}.parquet` 全周期缓存。
- **实时只读通道**：MT5 行情/持仓、Mobius API、金十 MCP、runninghub LLM —— 全部真实调用。
- **临时目录**：`tests/conftest.py` 用仓库内 `.pytest_tmp/`
  （系统 TEMP 在沙箱下不可写）。

## 2. 分层测试

| 层 | 对象 | 方法 | 无 mock 方式 |
|---|---|---|---|
| L1 | mt5.collector | 真实 initialize + 全周期拉取 + 校验门 | 真实终端（已运行） |
| L2 | mt5.executor | `--allow-live-order` 手动触发最小手数真实下单+立即平仓 | 真实账户，0.01 lot |
| L3 | skills.chanlun | 真实 XAUUSD 数据 analyze；quality=pass 断言；**8 门 audit 断言** | 已实测通过 |
| L4 | skills.openmobius | 真实 API + 限速器行为（403/429 处理）；**7 步字段采集断言** | 已实测通过 |
| L5 | fusion | parquet 回放：每源 IC/命中率校准、S/σ 合理性；**去均值验收、零权重验收、双向性验收** | 真实历史 |
| L6 | llm | 真实 key 调 glm-5.3-flash 结构化输出 + 超时降级路径 | 真实 endpoint |
| L7 | news | 金十真实拉取 + LLM-B 真实调用 | 真实服务 |
| L8 | risk | 用真实回放序列驱动熔断/网格/马丁逻辑断言；**Wilson 下界、方向偏置熔断** | 真实历史状态序列 |
| L9 | decision+agent | 全图在回放模式（喂 parquet、executor 置 DRY——**唯一允许的"模拟"是执行层切到 dry_run**） | 混合：真实数据 + 执行层 dry |
| L10 | 全流程 live | live 模式跑 1 轮完整决策，实际下单 0.01 lot，复盘日志核对 | 真实账户 |

## 3. 通过标准

- L1–L8 全绿；L9 回放期决策日志完整可追溯（每个 Proposal 能回放证据链）。
- L10 前：风控门单元断言（拒绝路径覆盖 ≥8 种 REJECT reason）。
- **回放校准指标**：融合 S 与未来方向 IC > **0.01** 且命中率 > **0.50**。

### 3.1 P0-3 修正：旧断言是空转的

旧版 `tests/test_fusion_replay.py` 写的是：

```python
assert ic > -0.05      # ← 实测 IC = −0.04，照样通过
```

`IC = −0.04` 意味着融合分与未来方向**轻微负相关**，但断言仍然通过 ——
**这个测试在过去所有运行里都不可能失败**，它对系统没有任何保护作用。

修正后：`IC_MIN = 0.01`、`HIT_MIN = 0.50`（双侧有意义的下限）。

> ⚠️ 需要区分两件事：
> - `test_fusion_replay_calibration` 用 `_plumbing_engine()` 注入一组 IR 权重，
>   验证的是**融合机器**（去均值 → IR 加权 → 融合 → IC）是否正常。
>   实测 IC = **0.0367**、命中率 **0.515**（n=893）。
> - **生产路径**读 `data/source_ir.json`，其中所有源都未通过更严的
>   **非重叠检验**（`research/21_source_ir.txt`）→ 权重**退回
>   `weights.BASELINE_IR`**（`research/18 §P0-2` 的 IR 表），
>   只有 `openmobius_smc` 保持 0 → **系统会正常开仓**。
>   由 `test_production_weight_table_can_trade` 覆盖。
>
> 两者不可混淆：前者证明链路可用，后者证明**生产权重表确实能开仓**，
> 同时守住"未验证的源拿不到权重"这条不变量。

### 3.1.1 旧测试 `test_production_ir_file_has_no_verified_source` 已删除

该测试断言"**没有任何源通过验证 → 权重全 0 → S≡0 → 不开仓**"，
并把「不开仓」当作**正确的预期行为**。**这个断言是错的**，原因：

1. `research/18 §P0-2` **原文就逐条列出了 IR 表**（kalman 0.28 / chanlun 0.05 /
   classic 0.03 / openmobius_smc 0.00）—— 只有 `openmobius_smc` 是 0。
   把全部源打成 0 是对该条的**过度应用**。
2. 一个不交易的交易系统是**失败状态**，不是安全状态。
   实盘证据：`effective_weight=0.0` → `score=0.0` → 永远 `hold`。
3. 用测试把一个 bug 固化成"预期行为"，会让它永远不会被修。

替换为 `test_production_weight_table_can_trade`：断言总权重 > 0、
`σ_S ≤ sigma_max`（否则决策层永远 hold）、`openmobius_smc` 仍为 0、
且每个有权重的源都必须有 `research/` 出处。

### 3.1.2 新增：启动预热必须真的让系统可交易

`norm_min_periods=240` 的单位是**决策轮数**。1m 决策周期下 = **4 小时**，
不预热则启动后 4 小时内所有源归一化分都是 0.0 → 融合分恒 0 → 永不开仓。
`FusionEngine.prime_history()` 在启动时回放 `fusion.prime_steps = 300` 轮
真实 bar 把缓冲灌满（实测约 7 秒）。四个测试把这条链路固化：

| 测试 | 断言 |
|---|---|
| `test_normalizer_is_cold_without_priming` | 不预热 → 首轮 `score == 0.0`（**复现 bug 的因果链**，防止有人把 prime 去掉） |
| `test_prime_history_makes_system_tradeable` | 预热后 `normalizer.warm()` 为真、`score != 0`、`effective_weight > 0` |
| `test_primed_score_spread_crosses_open_threshold` | 预热后非零分占比 > 50%，且 `max|S| ≥ open_threshold` —— 分数分布**真的能越过开仓阈值**，不是"有分但永远不够" |
| `test_warmup_windows_match_decision_cycle` | 预热时长 ∈ [0.02, 7] 天，`prime_steps ≥ min_periods`，引擎装配值与 config 一致 |

> ⚠️ 这类"单位错配"不会抛异常，只会**静默让系统长期空仓** ——
> 必须有测试兜住，否则下次改周期时同样的 bug 会再犯一次。

### 3.2 每项验收对应的测试

| 商用方案项 | 测试 |
|---|---|
| P0-1 去均值 | `test_source_normalizer_demeans_bias`、`test_fusion_score_is_two_sided`、`test_normalizer_warmup_returns_zero`、`test_normalizer_obs_id_idempotent` |
| P0-2 零权重 | `test_unverified_source_gets_zero_weight`、`test_negative_ir_gets_zero_weight`、`test_fuse_all_returns_neutral_when_no_verified_source`、**`test_production_weight_table_can_trade`** |
| P0-3 可失败断言 | `test_fusion_replay_calibration` |
| P1-1 周期（**已回滚到 1m**） | `config.toml` 的 `loop_interval_s=60`、**`risk.atr_tf="1h"`**、**`fusion.prime_steps=300`**（配置断言 + `test_warmup_windows_match_decision_cycle`）。平仓判据自 2026-09-30 起为 `exit_adverse_window=20` / `exit_adverse_rate=0.80`（原 `exit_persist_rounds` 已删除，见 `test_holding_exit_streak`） |
| P1-1 启动预热 | `test_normalizer_is_cold_without_priming`、`test_prime_history_makes_system_tradeable`、`test_primed_score_spread_crosses_open_threshold` |
| P1-2 波动分位 | `test_vol_regime_gate_blocks_low_percentile` |
| P1-3 基线校正 | `test_effective_score_subtracts_baseline`、`test_baseline_correction_shifts_decision` |
| P2-1 参数门 | `research/22_param_gate.py`（DSR + PBO + MinBTL + Purged K-Fold） |
| P2-2 方向偏置 | `test_direction_bias_halts_on_structural_long`、`test_direction_bias_allows_balanced_book`、`test_direction_bias_clear` |
| P2-3 Wilson 下界 | `test_wilson_lower_is_conservative_for_small_samples`、`test_conservative_win_rate_uses_fallback_below_threshold` |
| LLM 主路径 | `test_decision_*`（LLM opposed / unavailable / neutral 三条路径） |
| skill 契约 | `test_skills_real.py`（8 门 audit、7 步 SMC 字段） |

## 4. 运行

```powershell
$py = "C:\Users\admin\AppData\Local\Programs\Python\Python312\python.exe"
& $py -m pytest tests/ -q --no-header -p no:cacheprovider     # L1..L9（108 个测试，全绿）
& $py research/21_source_ir.py --bars 60000 --write           # 权重表（P0-2）
& $py research/22_param_gate.py                               # 参数门（P2-1）
& $py research/23_kalman_tb.py                                # 止损宽度实测（P1-1 修正依据）
& $py -m tests.live_smoke --allow-live-order                  # L10 人工确认后跑
```

## 5. 已知的诚实结论（不是 bug）

- **系统现在会正常开仓** —— 这是硬性验收，不是"可选状态"。
  预热后实测（100 轮，LLM 不可用时走本地路径）：
  **58% 的轮次产出 `place_grid`**，方向 LONG 51.7% / SHORT 48.3%，
  融合分 **100% 非零**，σ = 0.489 ≤ `sigma_max` = 0.8。
  （更早的实盘观测是 100% `hold`：`effective_weight=0.0` → `score=0.0`。
  那是 bug，不是"安全"。）
- **但源的预测技能仍未被独立证实。** `research/21_source_ir.py` 升级为
  `triple_barrier` + **非重叠校正**后，现有源没有一个通过
  （非重叠毛 NW-t：kalman +0.37 / classic −0.10 / chanlun −0.20）。
  所以权重退回 `research/18 §P0-2` 的基线表 —— 这不是"已验证"，
  而是**在拿到更好的信息源之前不让系统瘫痪**。
- **重叠会把噪声伪装成 alpha**（本次最重要的方法论发现）：
  chanlun 信号在 15 根 1m 上重复，46,559 笔"交易"实际只对应 **261 个
  独立决策**（重叠 178 倍）；不校正时毛 NW-t = **+3.32**（看起来是强 alpha），
  校正后塌到 **−0.20**。凡是"毛收益"数字，都必须先做非重叠校正。
- **`openmobius_smc` 的 IR 由离线桩产出**（Mobius API 只返回当前快照，
  无历史回放），因此 `verified` 恒为 `false`（`research/21` 写文件时**强制**置 false）。
  它的非重叠毛 NW-t = +2.66 看着最好，但**不是证据**；补齐真实历史校准前
  其权重必须为 0。
- **阈值调参没有统计支撑**（`research/22_param_gate.py`）：60,000 根真实 1m bar 上
  对 `[1.0..1.6]` 全部候选做 DSR + PBO + MinBTL + Purged K-Fold，
  **没有一个通过**（DSR 全 0、PBO = 1.0、数据仅 0.17 年 < 所需 2.13 年）。
  下一步是**找有真实 IC 的新信息源**，不是继续调阈值。
- `research/11` 的 `kalman_trend`（毛 NW-t=+3.31）与线上 `kalman_persist`
  是**两个不同实现**（前者 `quant.models.kalman_dynamic_beta` 手写递推 +
  自适应 R；后者 `fusion.kalman.KalmanTrend` 用 filterpy + 固定 R）。
  `research/23_kalman_tb.py` 用 triple_barrier 复核了**线上实现**：
  毛 NW-t = +1.74，约为文献值的 0.53x，方向一致率 89.3%（同一信号族）。
  P0-2 只认**线上实现**的成绩，不能用另一个实现的数字给线上源发权重。

> **当前测试状态**：`tests/` 共 **108 个测试，全部通过**
> （`python -m pytest tests/ -q`）。
>
> 其中 17 个是 **2026-09-21 新增的"静默故障"回归测试**。
> 这些 bug 的共同点是**运行时不报错**，只是让系统安静地失效或崩溃：
>
> | 回归测试 | 锁住的故障 |
> |---|---|
> | `test_primed_baseline_is_on_normalized_scale` | 基线用原始分标定 → `S_eff` 恒正 → 每轮做多 |
> | `test_primed_engine_has_no_directional_bias` | 同上（端到端） |
> | `test_primed_series_actually_varies` | 预热每步取同一窗口 → 301 个相同分数 |
> | `test_prime_does_not_double_count` | 同批样本灌两遍（301 步 → 602 样本） |
> | `test_prime_history_never_uses_future_bars` | 预热前视（篡改尾部数据不得改变早期样本） |
> | `test_prime_windows_end_at_or_before_step` | 各周期按索引比例映射 → 时间轴错位 |
> | `test_prime_slice_is_monotonic_in_time` | 窗口未随步前进 |
> | `test_oos_open_rate_is_acceptable` | **开仓率 < 10% = 失败的改动**（用户验收线） |
> | `test_console_output_never_crashes_on_gbk` | `✓` 在 GBK 控制台崩溃 → **一开仓就死** |
> | `test_runner_console_format_is_ascii` | 同上（源头禁止非 ASCII） |
> | `test_runner_console_shows_action_on_trade_rounds` | 下单轮次显示 `-> ?` |
> | `test_graph_sets_action_for_every_proposal_kind` | `action` 只在 hold 分支赋值 |
> | `test_research_replay_does_not_pollute_live_logs` | 研究回放往实盘日志灌伪造轮次 |
> | `test_research_scripts_silence_logging` | 同上（源码扫描防漏） |
> | `test_order_direction_mapping_is_exhaustive` | 挂单类型码未穷举 → **所有挂单被判成 SHORT** |
> | `test_holding_management_not_blocked_by_pending` | 有挂单就跳过持仓管理 → **止损失效** |
> | `test_pending_cancel_uses_correct_direction` | 撤单方向判反 |
> | `test_single_instance_lock_blocks_second_runner` | 两个 runner 同时交易同一账户 |
>
> 每一项都做过**证伪**：把 bug 注入回去，测试必须失败。
> 例如把 `open_threshold` 抬到 99 → `test_oos_open_rate_is_acceptable`
> 报 `开仓率 0.0% < 10%`；把 `_score_from_raw` 改回用原始分 →
> 基线尺度测试报 `AssertionError`；把 `_pid_alive` 判断去掉 →
> 单实例测试报 `第二个 runner 未被拦住`。
