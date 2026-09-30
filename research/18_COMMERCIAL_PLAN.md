# GoldAgent 商用化方案

> 基于 `research/09`–`17` 的全部实测证据。每条改动都标注了依据与验收标准。
> **本文不承诺盈利** —— 理由是：全部证据显示当前系统**没有可检出的方向 alpha**。
> 本方案的目标是：① 修掉正在造成亏损的缺陷 ② 把系统搬到数学上尚有可能的位置
> ③ 建立能真正判别「有没有边际」的验证能力。做不到 ③，任何调参都是自欺。

---

## 0. 诊断：一句话

**当前实盘系统不是在择时，是在结构性做多黄金。**

证据（`research/16_live_audit.txt`，881 轮实盘日志）：

| 信号源 | 权重占比 | score 均值 | **score 为正** | 贡献 |
|---|---|---|---|---|
| chanlun | 35.4% | +0.1181 | 52.4% | +0.0418 |
| **openmobius_smc** | **35.4%** | **+1.2604** | **88.0%** | **+0.4460** |
| classic_indicators | 24.6% | +0.1416 | 63.3% | +0.0348 |
| kalman_persist | **4.7%** | +0.0313 | 50.3% | +0.0015 |

- 融合分 **80.2% 为正**，均值 +0.5241
- `|S| ≥ 1.3` 的 38 轮开仓信号：**38 轮做多，0 轮做空**
- 实盘 3 笔交割单：**全部 LONG**（1 胜 2 负，PF 1.15）

反事实验算：把 mobius 的常数偏移减掉后，`|S|≥1.3` 的 6 轮变成 **2 多 / 4 空** —— 系统才开始双向。

---

## 1. P0：三个必须立刻修的缺陷

### P0-1 信号源未去均值 → 结构性方向偏置

**问题**：`_score_fn`（`skills/mobius_adapter.py`）对 SMC 结构做**有符号累加但不减基准**。
黄金长期上行 → bull 结构持续累积、bear 结构很快被覆盖 → 88% 为正、均值 +1.26。
这个 +1.26 **不是预测，是偏置**。

**修法**（最小改动、最大收益）：在 `fusion/engine.py` 中，每个源进入融合前做**滚动 z-score 去均值**：

```python
# fusion/engine.py —— 新增源归一化
class SourceNormalizer:
    """按源维护滚动均值/标准差，消除结构性常数偏移。"""
    def __init__(self, win: int = 1440, min_periods: int = 240):
        self.win, self.min_p = win, min_periods
        self._buf: dict[str, list[float]] = {}

    def normalize(self, name: str, x: float) -> float:
        b = self._buf.setdefault(name, [])
        b.append(float(x))
        if len(b) > self.win:
            del b[: len(b) - self.win]
        if len(b) < self.min_p:
            return 0.0                      # 预热期不给方向，宁可空仓
        arr = np.asarray(b, dtype=float)
        sd = float(arr.std())
        if sd < 1e-9:
            return 0.0
        return float(np.clip((x - arr.mean()) / sd, -3.0, 3.0))
```

然后在 `fuse_all` 里对每个 `SourceView.score` 先过 `normalize` 再构造。

**验收**：连续运行 ≥ 3 天后，各源 `score` 均值 ∈ [−0.3, +0.3]，为正比例 ∈ [40%, 60%]；
融合分做多/做空轮数均 > 0。

**已在真实数据上验证**（`research/19_demean_check.py`）：构造一个「kalman_z + 1.2604 偏移」
的模拟源（复刻 mobius 的行为），对比去偏前后：

| 方案 | 笔数 | 做多 | 做空 | 净均值 | 总净盈亏 | 净NW-t |
|---|---|---|---|---|---|---|
| 有偏源，原样 | 59999 | 54975 | **5024** | −0.5156 | −30938 | −26.21 |
| 有偏源，去均值 | 59879 | 29699 | **30180** | −0.4606 | −27578 | −25.69 |

加上 `open_threshold=1.3` 门槛后差距放大：

| 方案 | 触发 | 做多 | 做空 | 净均值 | 总净盈亏 | 净NW-t |
|---|---|---|---|---|---|---|
| 有偏源，原样 | 29218 | 28607 | **611** | −0.4895 | −14303 | **−17.94** |
| 有偏源，去均值 | 9561 | 4867 | **4694** | −0.4275 | **−4087** | **−8.62** |

→ 总亏损 **−14303 → −4087（减少 71%）**，净 NW-t **−17.94 → −8.62（改善 2.1 倍）**。

机制说明：去偏源与有偏源**只差一个常数**，所以差异**全部**落在
`kalman_z ∈ (−1.26, 0)` 这一段（占 41.9%）—— 这段「弱看空」被系统性误判为「看多」。
去偏不是把噪声搬到负半轴，是**把方向判据从「> −1.26」修正回「> 0」**。

⚠️ **但去偏后仍然亏损**（净均值 −0.4606）。P0-1 是**必要不充分**条件。

---

### P0-2 权重与实测 skill 脱钩 → 未被验证的源主导决策

**问题**：`gaussian.fuse` 用 `w = 1/sigma²`，而 sigma 是**手填常数**：

| 源 | sigma 来源 | 权重 |
|---|---|---|
| kalman_persist | `max(k.sigma*0.8, 0.2)`（唯一随数据变） | 0.526 |
| chanlun | **硬编码 0.5** | 4.000 |
| openmobius_smc | **硬编码 0.5** | 4.000 |
| classic_indicators | **硬编码 0.6** | 2.778 |

→ **谁影响力大，取决于当初敲了哪个数字。** mobius 拿到 kalman 的 **7.6 倍**权重。

而本仓库擂台的实测结论是（`05_arena_1m.txt` + `11_mechanism.txt`）：
- `kalman_trend` 毛 NW-t = **+3.31**，三种对照设计（随机方向 / 匹配多头比例 / 块置换）**全部确认有效**
- mobius/SMC **从未在本仓库被验证过**

**唯一被验证有效的源被降权到 4.7%，未被验证的源占 35.4%。**

**修法**：权重改为按**实测 IR（信息比率）**分配，并设「未验证 → 0 权重」的硬规则：

```python
# fusion/engine.py
SOURCE_IR = {                    # 由 research/ 校准脚本产出，禁止手填
    "kalman_persist":    0.28,   # 依据 11_mechanism：毛 NW-t=+3.31
    "chanlun":           0.05,   # 04_report：57 变体族未通过 WRC
    "classic_indicators": 0.03,  # 17_fusion_predictive：IC≈0.002
    "openmobius_smc":    0.00,   # 未验证 → 0 权重，直到补上校准
}
# 权重 = IR²（与 1/sigma² 同形，但 sigma 换成实测标准误）
```

**验收**：任何源的权重变更必须附一个 `research/` 脚本产出的 IR 数字；无数字 = 0 权重。

---

### P0-3 验证测试是空转 → 无法发现「融合分无效」

**问题**：`tests/test_fusion_replay.py:90`

```python
assert ic > -0.05, f"融合分 IC 异常: {ic:.3f}（需要权重校准）"
```

**IC = −0.04 也能通过。** 这个测试在过去所有运行里都不可能失败。

**修法**：

```python
# 改为有意义的双侧下限 + 命中率下限
assert ic > 0.01, f"融合分 IC 过低: {ic:.4f}（需重新校准源权重）"
assert hit > 0.50, f"命中率不足: {hit:.3f}"
```

并把 `tests/test_fusion_replay.py` 的 `fuse_all(..., None)` 补上 mobius 的离线桩，
否则测试覆盖不到实际主导决策的那个源。

**验收**：`pytest tests/test_fusion_replay.py` 在当前代码上**应当失败** —— 这是它第一次真正起作用。

---

## 2. P1：结构性重构 —— 搬到数学上尚有可能的位置

### P1-1 决策周期从 1m 迁到 1h

**依据**（`15_alternatives.py` B 段，stride=1 修正后）：

| 周期 | σ/根(USD) | 成本/σ | **盈亏平衡 IC** | 现实模型 IC |
|---|---|---|---|---|
| 1m | 1.329 | 0.391 | **>0.50** | 0.02~0.05 |
| 5m | 3.422 | 0.152 | 0.40 | 0.02~0.05 |
| 15m | 5.875 | 0.089 | 0.30 | 0.02~0.05 |
| **1h** | 14.003 | 0.037 | **0.10** | 0.02~0.05 |
| 4h | 24.138 | 0.022 | ⚠ 基准污染 | — |

**成本结构**（`10_verify.py` D 段，纯算术，不需要任何模型）：

| 周期 | 总成本(每根都交易) | 市场总位移 | **总成本/位移** |
|---|---|---|---|
| 1m | 31,200 | 313.5 | **99.5x** |
| 1h | 522 | 316.6 | 1.6x |
| 4h | 141 | 306.7 | **0.5x** |

> 1m 上，即使每根 K 线只交易一次，全窗口成本是「市场能提供的全部方向性收益」的 **100 倍**。

**修法**：
1. `config.toml`: `loop_interval_s` 60 → **3600**（1h 决策一次）
2. `decision.machine` 的 `exit_persist_rounds` 3 → **2**（1h 一轮 = 3 小时，3 轮太慢）
3. `risk.sl_atr_mult` / `tp_atr_mult` 用 **1h ATR**（当前用 15m ATR）
4. 主信号源权重表改为 1h/4h 为主，1m 降为执行择时（不参与方向）

**验收**：`research/12_levers.py` L3 实测显示同一模型 1h 净 NW-t = −0.29（vs 1m −25.69），
净均值 −0.261（vs −0.461）。**仍是负的**，但已从「绝望」进入「可讨论」。

---

### P1-2 高波动 regime 过滤（唯一不依赖方向预测的杠杆）

**依据**（`12_levers.py` C1）：成本固定 0.52，障碍宽度 = 2σ 随波动变。

| 波动分位门槛 | 笔数 | 成本/2σ | 毛均值 | 净NW-t |
|---|---|---|---|---|
| ≥0% | 59760 | 19.5% | +0.0596 | −25.63 |
| ≥50% | 29286 | 15.9% | +0.0862 | −13.57 |
| **≥90%** | 5494 | **11.5%** | **+0.1617** | **−3.56** |

毛边际 **+171%**，净 NW-t 改善 **7 倍**。

**修法**：在 `decision.machine._decide_flat` 开仓前加一道闸：

```python
# 波动分位过滤：只在 σ 位于滚动高分位时开仓
vol_pct = ctx.vol_percentile          # 由 fusion 提供：当前 σ 在近 N 根的滚动分位
if vol_pct < CFG.decision.vol_pct_min:      # 新增配置，默认 0.5
    return Proposal(kind="hold",
                    reasons=[f"low-vol regime {vol_pct:.2f} < {CFG.decision.vol_pct_min}"])
```

**验收**：过滤后单笔毛边际应上升 ≥ 50%，且总笔数下降不应超过 70%。

---

### P1-3 移除「结构性做多」的隐性来源

**问题**：`decision.machine` 用 `abs(s) < open_threshold` 判断，
但**融合分的零点不在 0**（均值 +0.52）。S=+0.52 的「中性」被当成「偏多」。

**修法**：阈值判断前先减去滚动均值（与 P0-1 同源，但这里是第二道保险）：

```python
# decision/machine.py
s_eff = s - ctx.score_baseline      # 滚动均值，由 fusion 提供
if abs(s_eff) < thr:
    return Proposal(kind="hold", reasons=[f"|S-S0| {abs(s_eff):.2f} < {thr}"])
```

**验收**：实盘 `|S|≥threshold` 的触发中，做多与做空轮数均 > 20%。

---

## 3. P2：验证纪律（决定这套系统能否长期存活）

### P2-1 建立「先验证、后上线」的硬流程

当前 `config.toml` 的调参记录显示：
```
2026-09-18  open_threshold 1.6 → 1.2：64 轮全 hold，峰值仅 1.29
2026-09-19  3 笔交割单复盘（1胜2负）：S=1.16~1.24 的入场全部亏损 → 阈值回提 1.2 → 1.3
```

**这是用 3 笔交易调参。** 3 笔样本的胜率置信区间是 [6%, 79%] —— 它不能支持任何结论。

**修法**：新增 `research/18_param_gate.py`，任何参数变更必须：
1. 在 ≥ 60,000 根历史 bar 上回放
2. 通过 **Purged K-Fold**（`labeling.purged_kfold_indices` 已有）
3. 报告 **Deflated Sharpe**（`labeling.deflated_sharpe` 已有）
4. 试验族规模 N 必须显式记录（每试一个参数 +1）

**验收**：`config.toml` 的每条调参记录后面必须跟一个 DSR 数字。没有 = 回滚。

### P2-2 实盘熔断加「方向偏置」监控

```python
# risk/position.py CircuitBreakers
if self.direction_bias_window > 0.85:      # 近 100 笔同向占比
    return "direction_bias_halt"           # 触发即停机复查
```

**验收**：连续 100 笔中单向占比 > 85% 时自动停机。

### P2-3 交割单样本量门槛

`position_lots` 已用 `win_rate` 做 Half-Kelly，但 `deal_feedback.current_win_rate()`
在样本 < 10 时返回 0.5 冷启动。**3 笔就参与 Kelly 计算是危险的。**

**修法**：`win_rate` 的置信下界（Wilson score lower bound）而非点估计：

```python
def wilson_lower(wins: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    ph = wins / n
    d = 1 + z*z/n
    c = ph + z*z/(2*n)
    r = z * math.sqrt(ph*(1-ph)/n + z*z/(4*n*n))
    return max(0.0, (c - r) / d)
```

3 笔 1 胜 → Wilson 下界 = **0.061**，而非 0.333。仓位会自动缩到最小。

---

## 4. 明确不要做的事（已被实测证伪）

| 想法 | 实测结果 | 依据 |
|---|---|---|
| **按信号反买** | 净均值 −0.4606 → **−0.5559**（更差） | `15_alternatives.py` |
| **止损止盈互换** | 胜率 33%→67%，净均值 −0.4606 → **−0.5098**（更差） | 同上 |
| 降低成本（挂单） | 亏损收窄 56%，**不能转正** | `12_levers.py` L1 |
| 降低频率 | 单笔经济性**不变**（−0.44~−0.57） | `12_levers.py` L2 |
| 换几何（TP/SL/持有期） | 不改变符号，仅改善 t 值 | `12_levers.py` L4 |
| 时段过滤 | 全部时段净均值为负 | `15_alternatives.py` C2 |
| 多模型一致性 | −0.4570 vs −0.4606，几乎无改善 | `15_alternatives.py` C3 |
| 波动率目标化「提升盈利」 | 回撤 −25% 是**缩放效应**，Calmar 不变 | `13_voltarget_check.py` |

**反买的算术**：`E[净_反买] = −E[净_原] − 2×成本`。成本与方向无关，取反不省一分钱。

---

## 5. 落地路线图

| 阶段 | 内容 | 工期 | 验收 |
|---|---|---|---|
| **W1** | P0-1 去均值 + P0-3 测试断言 | 2 天 | 各源 score 均值 ∈ [−0.3,0.3]；测试首次能失败 |
| **W2** | P0-2 权重改 IR 分配 | 2 天 | mobius 权重 → 0（未验证）；kalman → 最高 |
| **W3** | P1-1 迁 1h + P1-2 波动过滤 | 3 天 | 回放净 NW-t 从 −25.7 改善到 ≥ −1 |
| **W4** | P2-1 参数门 + P2-3 Wilson | 2 天 | 参数变更全部带 DSR |
| **W5–W8** | **纸面交易 4 周**，不动真实资金 | 4 周 | 累计 ≥ 100 笔，净 NW-t > 0 才进下一步 |
| **W9+** | 小仓位实盘（0.01 手），P2-2 偏置熔断开启 | — | 逐月复核 |

**关键决策点**：W5–W8 结束后，若净 NW-t 仍 ≤ 0，**应停止实盘**而非继续调参。
理由：`15_alternatives.py` 已证明 1h 的盈亏平衡 IC = 0.10，而现实模型 IC = 0.02~0.05 ——
如果纸面交易达不到，说明这个品种+周期上确实没有可用边际。

---

## 6. 诚实的预期管理

**这套方案能把系统从「结构性做多 + 未被验证的源主导」修成「双向、权重有据、成本可控」。**

**但它不能保证盈利**，因为：

1. 本仓库全部实测中，**没有任何方向源达到盈亏平衡所需的 IC**
   （1m 需 >0.50，1h 需 0.10；实测 kalman IC = +0.0124，classic IC = +0.0021）
2. 唯一有统计证据的 `kalman_trend`，毛边际 +0.049 USD vs 成本 0.520 USD，**差 10.6 倍**
3. 全部 10 个模型在 1m 上净 NW-t 都 < 0

**真正可能改变结论的只有两件事**：
- **换到成本/位移比合理的周期**（1m 99.5x → 4h 0.5x）—— 本方案 P1-1
- **找到 IC ≥ 0.10 的新信息源**（当前所有源都远不达标）—— 这需要新数据，不是新参数

在拿到第 2 条之前，正确的期望是**「不亏」而非「盈利」**。

---

## 附：本方案的证据索引

| 结论 | 脚本 | 输出 |
|---|---|---|
| 实盘结构性做多、权重脱钩 | `research/16_live_audit.py` | `16_live_audit.txt` |
| 融合分 IC、mobius 偏置成因 | `research/17_fusion_predictive.py` | `17_fusion_predictive.txt` |
| **P0-1 去偏有效性验证** | `research/19_demean_check.py` | `19_demean_check.txt` |
| 各周期盈亏平衡 IC、反买/互换 | `research/15_alternatives.py` | `15_alternatives.txt` |
| 毛收益构造性偏误、校准后排名 | `research/11_mechanism.py` | `11_mechanism.txt` |
| 四条杠杆实测 | `research/12_levers.py` | `12_levers.txt` |
| 波动率目标化复核 | `research/13_voltarget_check.py` | `13_voltarget_check.txt` |
| 成本结构算术 | `research/10_verify.py` | `10_verify.txt` |
| 模型擂台原始数据 | `research/05_arena_1m.txt` | — |
