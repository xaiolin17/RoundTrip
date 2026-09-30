# 05 — 仓位管理与风控（risk/）：Half-Kelly · 波动率目标 · ATR 预算 · 网格/马丁 · 熔断

> ⚠️ **2026-09-20 修正**（`research/18_COMMERCIAL_PLAN.md` §P2-2 / §P2-3）：
> 胜率估计与熔断器有两处缺陷，已修复。见 §1.1、§5.1。

用户未指定仓位模型；以下为检索到的广泛认可方案（引证见 README 与调研记录）：
- Half-Kelly（f/2，教科书与量化社区共识上限）
- 波动率目标（vol targeting，目标年化波动反推杠杆/手数）
- ATR 风险预算（单笔风险 = 账户的 risk_pct，ATR 定 SL 距离 → 反推手数；手数不足最小步长则拒绝交易）
- 回撤降杠杆（drawdown-based de-risking）
- 网格/马丁必须带硬性敞口与连亏熔断（社区共识：裸马丁必爆仓）

## 1. 单笔仓位（首仓）

```
sl_distance = sl_atr_mult × ATR(决策周期)      # 默认 1.2；P1-1：用 1h ATR，不是 15m
risk_usd    = equity × risk_pct               # 默认 0.5%， Half-Kelly 上限时 = 0.5×f*
f*          = (p·b - q)/b   (b=盈亏比=tp_atr_mult/sl_atr_mult≈1.67, p=Wilson 下界胜率)
lots        = risk_usd / (sl_distance_points × point_value_per_lot)
lots        = clamp(lots, volume_min, volume_max), round to volume_step
若 lots < volume_min → REJECT("risk_budget_below_min_lot")   # 绝不超风险开单
```

> **P1-1**：`sl_distance` 必须用**决策周期（1h）**的 ATR（`graph._decision_atr`）。
> 旧版用 15m ATR —— 1h 级别的仓位在 15m 的止损宽度下会被正常波动打掉。

### 1.1 P2-3 胜率用 Wilson 置信下界，不用点估计

**问题**：`deal_feedback.current_win_rate()` 在样本 ≥10 时返回**点估计**。
3 笔 1 胜的点估计是 **0.333**，看起来"还行"；
但 3 笔样本的 95% 置信区间是 **[6%, 79%]** —— 它不能支持任何结论。

**修法**：样本 ≥ `risk.min_deals_for_kelly`（默认 10）时返回 **Wilson score 置信下界**：

```python
def wilson_lower(wins, n, z=1.96) -> float: ...
# wilson_lower(1, 3) = 0.0615   ← 而非点估计 0.3333
```

→ 小样本自动缩仓。样本 < 门槛时返回 `fallback`（0.5 冷启动），
因为此时任何估计都不可信。

## 2. 波动率目标叠加

- `target_vol_daily = 1.0%`（默认）； realized_vol(20d 年化) 高于目标 → 全局仓位系数 `k = target_vol/realized_vol`（上限 1.5，下限 0.25）。
- 黄金高波动日（ATR(1d)/close > 2%）→ k 再 ×0.6。

## 3. 有限网格（同向加仓）

- 触发：首仓后浮亏 ≥ 0.8×ATR 且融合分仍支持原方向（S_eff 同号且 |S_eff|≥1.3）。
- 网格层数 N=2（默认，`grid_layers`），每层间距 = 0.8×ATR，每层手数 = 首仓 × 0.7^i（**不翻倍，非马丁式倍投**）。
- 每层独立 SL（组内总风险预算仍 ≤ risk_pct×1.5）；任一层 SL 触发 → 全组重新评估。
- 组总敞口上限：`total_lots ≤ max_group_lots`（默认 = 3×首仓）。

## 3b. 挂单止盈止损收缩规则（用户要求：点位空挡不可达问题）

挂单（pending / 网格限价单）与极值测算的差异处理：

| 项 | 市价单 | 挂单 |
|---|---|---|
| TP | `2.0×ATR`（可分批：1×ATR 平半仓 + 余量 2×ATR） | `0.6 × 2.0×ATR = 1.2×ATR` |
| SL | `1.2×ATR` | `0.65 × 1.2×ATR ≈ 0.78×ATR` |
| 入场位 | 当前 bid/ask | 结构关键位**内侧**（OB/FVG 边界向当前价收 0.15×ATR），不追极值边界 |
| 可达性校验 | — | 若目标 TP 价位在近 600 根 K 内从未触及（无高低点支撑），自动收缩到最近 swing 位 |

实现于 `risk/shrink.py::shrink_for_pending()`；所有 place_pending / add_layer 路径必须经过该函数。

## 4. 反向马丁（对冲摊平，受限）

- 触发：网格满层后仍逆行 ≥ 1.5×ATR 且融合分反号且 |S_eff|≥1.5 → 关闭旧网格组，可反向开一组**反向网格**（3 层，间距 1.0×ATR）。
- 硬限制：**同一时段最多 1 组网格 + 1 组反向网格**；反向马丁单日累计亏损 > 账户 1.5% → 当日禁用马丁（仅单仓位）。

## 5. 熔断与降杠杆（硬规则，不可被 LLM/状态机绕过）

| 触发 | 动作 |
|---|---|
| 当日已亏 ≥ 3% equity | 停止新开仓，仅允许平仓 |
| 连续 4 笔亏损 | 冷却 4 小时（cooldown） |
| 回撤自高点 ≥ 8% | 仓位系数 k ×0.5；≥12% → 全停+告警 |
| 保证金占用 > 60% | 拒绝新仓 |
| 周五 23:30 后（服务器时区） | 不开新仓（周末跳空风险） |
| 新闻 impact ≥ 0.9（非农/CPI 类） | 决策前 15min 内禁开仓 |
| **近 N 笔同向占比 > 85%** | **方向偏置停机，需人工复查**（见 §5.1） |

### 5.1 P2-2 方向偏置熔断

**问题**（`research/16_live_audit.txt`）：实盘 3 笔交割单**全部 LONG**，
融合分 **80.2% 为正**，`|S|≥1.3` 的 38 轮**全部做多**。
系统不是在择时，而是在**结构性做多黄金**。

**修法**：`CircuitBreakers.record_direction()` 维护近期平仓方向序列
（由 `deal_feedback._deal_direction` 从交割单推断），
当近 `direction_bias_window`（默认 100）笔中同向占比 >
`direction_bias_max`（默认 85%）且样本 ≥ `direction_bias_min_samples`（默认 20）
→ `direction_bias_halt = True`，`check()` 返回
`direction_bias_halt: <原因>`，**拒绝所有新开仓**。

人工复查后调 `clear_direction_bias()` 解除。

> 这是 P0-1 之外的**第二道保险**：即使去均值失效（例如新源又引入偏移），
> 系统也不会在无人察觉的情况下持续单边押注。

## 6. 止盈止损与移动

- 初始：TP = 2.0×ATR、SL = 1.2×ATR（盈亏比 1.67；大盈亏比路线的默认起步）。
- 移动止损：盈利 > $10 后 SL 移至**盈利 $2** 处（用户规则：锁底搏上限）。
- 分批止盈：1×ATR 处平 50%，其余让利润奔跑（runner）。
- 全部通过 MT5 `TRADE_ACTION_SLTP` 执行，不依赖程序在线。

## 7. 仓位状态持久化

- `data/state.json`：网格组/马丁组、冷却截止、连亏计数、当日亏损、组层级结构。
- `data/breakers.json`：熔断器全量（含 `recent_directions` 与 `direction_bias_halt`）。
- 崩溃恢复：重启后先用 MT5 实际持仓对账（magic 过滤），再恢复组结构。

## 8. 参数变更纪律（P2-1）

`config.toml` 的调参记录显示历史上曾用 **3 笔交易**调整 `open_threshold`
（1.6→1.2→1.3）。按 `research/18 §P2-1`：

> 任何参数变更必须附一个 `research/22_param_gate.py` 产出的 **DSR 数字**。
> 没有 = 回滚。

`22_param_gate.py` 实现三件套（对齐 `docs/compliance/2026-commercial-trading-system-standards.md §2`）：

- **Purged K-Fold**（`quant.labeling.purged_kfold_indices`）：训练集选阈值、
  测试集评估，避免标签重叠泄漏
- **Deflated Sharpe Ratio**（`quant.labeling.deflated_sharpe`）：惩罚多次试验
- **PBO / CSCV**：IS 选出的最优配置在 OOS 跑输中位数的概率，**> 0.05 即拒绝**
- **MinBTL**：纯噪声下 N 次试验的期望最大 Sharpe；
  数据长度不足 MinBTL 时，任何 Sharpe≈1.0 的结果都不可信

试验族规模 N 显式记录在 `data/trials.csv`（每试一个参数 +1 行）。
