# GoldAgent — 自动交易智能体

> ⚠️ live 模式会对 MT5 账户**真实下单**，市场风险自负。

LangGraph 编排的交易智能体：多周期行情 → 两个 vendor skill 并发分析 →
本地数学融合 → LLM 主路径确认 → 风控门 → MT5 真实下单。

## 启动

```
py main.py
```

- `.env` 中 `TRADE_MODE=live` 即真实下单；`--dry` 演练不下单；`--rounds N` 限轮次

## 日志

`logs/` 下 JSONL：`decision_日期.jsonl`（信号分解 / 决策 / LLM 评审）、
`trades.jsonl`（风控与成交）、`llm_日期.jsonl`、`news_日期.jsonl`。

## 设计要点（v2，2026-09-20）

依据 `research/18_COMMERCIAL_PLAN.md`，本版修正了三处结构性缺陷。
完整推导见 `research/16`–`research/22`。

### 1. 决策周期 1m，止损用高级别

**1m 入场是用户明确要求，也是短线定位。** 曾一度改成 1h，理由是
"1m 上每根都交易的成本是全部方向性收益的 99.5 倍，盈亏平衡 IC 需 >0.50"。
**那个论证的前提错了** —— 它假设用 **1m 的波动**去定止损。

`research/23_kalman_tb.py` 实测（60,000 根真实 1m bar）：

```
止损基准        止损(USD)   成本/止损   净NW-t
1m ATR x1.2       1.13      46.0%     -30.00
15m 尺度 x1.2     4.74      11.0%      -4.38
1h ATR x1.2      20.80       2.5%      -1.40
```

成本 0.52 USD 是固定的；止损越窄，成本占比越高。用 1h ATR 定止损后，
成本只占 2.5%，净 NW-t 从 −30 改善到 −1.4。

→ **1m 负责入场择时，高级别负责风险尺度**（`risk.atr_tf = "1h"`）。
  1m 数据仍参与执行择时；方向级别链仍以 1h/15m 为主（避免 1m 噪声定方向）。

> ⚠️ 改周期会牵连滚动窗口参数：`norm_window` / `norm_min_periods` /
> `vol_pct_*` / `baseline_*` 的单位是**决策轮数**，不是分钟。
> 1m 下 `norm_min_periods=240` = 4 小时才预热 —— 若靠实盘干等，
> 启动后 4 小时内系统**永不开仓**（实盘已复现）。因此必须配合
> `fusion.prime_steps`（启动回放预热）。两条约束都由
> `test_warmup_windows_match_decision_cycle` 守住。

### 2. LLM 在主路径上，且按 skill 流程执行

实测（`research/20_llm_audit.txt`，881 轮实盘日志）：LLM review 覆盖率仅 **4.3%**。
根因是 15 分钟节流 + review/news 共用 24/h 预算 + `|S|>=0.9` 前置条件。
后果：`place_grid` 30 次 vs `open_market` 16 次 —— 系统绝大多数时候只能挂限价单。

现在：`min_interval_min = 0`、review 与 news **分开计账**、触发条件放宽；
LLM 明确反对 → **直接 hold**；LLM 缺失 → **不默认放网格**。
评审 prompt 强制走完 chanlun 的 **8 门严格原文自检** 与 SMC 的 **7 步咨询顺序**，
输出 `skill_audit`。

### 3. 权重来自实测 IR，不是手填常数

旧版 `gaussian.fuse` 用 `w = 1/sigma²`，而 sigma 是硬编码常数
（chanlun/mobius 都填 0.5）→ **谁影响力大取决于当初敲了哪个数字**：
未被验证的 mobius 拿到被验证的 kalman 的 **7.6 倍**权重。

现在：`w = IR²`，IR 由 `research/21_source_ir.py` 在 60,000 根真实 bar 上产出，
写入 `data/source_ir.json`。**硬规则：没有实测 IR 的源 = 0 权重，不做兜底猜测。**

### 4. 源去均值 + 融合分基线校正

实测各源方向分布（`research/16_live_audit.txt`）：mobius SMC **88% 为正**、
均值 **+1.2604**；融合分 **80.2% 为正**，`|S|≥1.3` 的 38 轮**全部做多**。
→ 这不是预测，是**结构性做多黄金**的偏置。

现在：每源过滚动 z-score 去均值（P0-1），决策层用 `S_eff = S − S0`（P1-3）。
实测总亏损 **−14303 → −4087（减少 71%）**，净 NW-t 改善 2.1 倍。

### 5. 风控：Wilson 下界 + 方向偏置熔断

- 胜率用 **Wilson 置信下界**（3 笔 1 胜：点估计 0.333，下界 **0.0615**）→ 小样本自动缩仓
- 近 100 笔同向占比 > 85% → **停机复查**（P2-2，防止单边押注）
- 参数变更必须附 **DSR 数字**（`research/22_param_gate.py`），
  试验族规模记录在 `data/trials.csv`。**没有 DSR = 回滚。**

## 当前状态：1m 短线可用

**决策周期 = 1m（`loop_interval_s = 60`）。** 这是用户明确要求，也是本系统的定位。

### 十一个曾经的失败点（已修复）

| 问题 | 症状 | 修复 |
|---|---|---|
| **权重全 0** | `effective_weight=0.0` → `score=0.0` → 永远 hold | research/18 §P0-2 原文只要求 `openmobius_smc` 为 0；其余源用其给定的 IR 表 |
| **归一化器不预热** | 启动后 240 轮（1m 下 = **4 小时**）所有源返回 0.0 | 新增 `prime_history()`：启动时回放历史 bar 灌满缓冲（7 秒完成） |
| **止损用 1m 波动** | 成本 0.52 USD 占止损 46% → 数学上不可能盈利 | `risk.atr_tf = "1h"`：成本占比降到 **4.4%** |
| **基线尺度错配** | 预热用**原始分**、运行时用**归一化分**喂基线 → `score_baseline≈−2.8`，`S_eff` 恒为 +2.7~+5.8 → **每轮都做多** | `_score_from_raw()` 先过 `normalizer.peek()` 再合成 |
| **预热窗口不前进** | `df.iloc[-k:]` 每步取同一窗口 → 301 步算出 301 个**相同**分数（std=0.000）→ 预热形同虚设 | 窗口右端锚在 `end`，按**时间**对齐各周期（`_slice_frames_at`） |
| **控制台编码崩溃** | `✓`(U+2713) 在 GBK 控制台抛 `UnicodeEncodeError`；该字符**只在执行成功时**拼接 → 进程恰好在**第一次开仓**那一轮死掉 | `_format_summary()` 纯 ASCII + `_safe_print()` 三级兜底 |
| **下单轮次显示 `?`** | `summary["action"]` 只在 hold/skip/safe_hold 分支赋值 → 真正下单的轮次打印 `-> ?`，**恰好最重要的轮次看不出发生了什么** | `decide()` 之后立即 `summary["action"] = prop.kind`，并带上方向 |
| **研究回放污染实盘日志** | `DecisionEngine.decide()` 内部会 `decision_log()` → 回放往 `logs/` 灌 **5900 条伪造轮次**（R14847/R29915…），占该文件 95% | `logging_util.set_silent(True)` + 研究脚本源码扫描测试 |
| **挂单方向判反** | `OrderRow.type` 存整数码（`"2"`），而代码用 `"buy" in str(type)` 猜 → **恒为 False** → 所有挂单都被当成 SHORT。实盘 34 次 `cancel_pending` **全是 SHORT**，从无 LONG，尽管挂的是 `BUY_LIMIT` | `_order_direction()` 穷举 MT5 类型码 0–8 |
| **持仓管理被挂单挡住** | `if pending: ... elif not holding: ... else: holding` → 只要挂着网格单，**止损/平仓/加仓永不执行**。实测持仓浮亏、`S_eff=−1.50` 越过 `exit_threshold=1.2` **连续 12 轮**，日志一直是 `pending x1 waiting fill` | 持仓管理优先；挂单撤单降为持仓不动时的补充动作（`_pending_cancel`） |
| **可重复启动两个 runner** | 两个 main.py 共用同一 MT5 账号与 magic，各自下单 → 网格单翻倍、撤单互相打断、`grid_state.json` 互相覆盖 | `_acquire_single_instance_lock()`：`O_CREAT\|O_EXCL` + pid 存活检测（stale 锁自动接管） |

> ⚠️ 后八项都是**"看起来能跑"**的静默故障：
> 第 4 项让系统单边押注，第 5 项让预热完全无效，第 6 项让进程一交易就崩，
> 第 7 项让日志无法诊断，第 8 项让实盘日志混入伪造轮次，
> **第 9、10 项让止损失效**（方向判反 + 持仓管理被跳过），
> 第 11 项让两个进程同时交易同一账户。
> 全部已用**证伪测试**锁住（注入 bug 后测试必须失败）。
>
> 实盘日志已清理：`logs/decision_20260921.jsonl` 从 6172 行降到 272 行
> （备份在 `logs/_backup/`）。

### 关键数据（`research/23_kalman_tb.py`，60,000 根真实 1m bar）

```
止损基准              止损(USD)   成本/止损   净NW-t
1m ATR x1.2             1.13      46.0%     -30.00
15m 尺度 x1.2           4.74      11.0%      -4.38
1h ATR x1.2            20.80       2.5%      -1.40
实盘当前(x1.2 x0.65)    11.90       4.4%       n/a
```

→ **1m 入场没问题，问题是用 1m 的波动去定止损。**
  1m 负责**入场择时**（精度高、机会多），高级别负责**风险尺度**（成本占比低）。

### 实测交易频率（`research/24_oos_open_rate.py`，4 个预热点 × 600 轮样本外）

| 预热点 | 开仓率 | LONG 占比 |
|---|---|---|
| t0=14847 | 16.7% | 19.0% |
| t0=29695 | 19.0% | 37.7% |
| t0=44542 | 23.2% | 49.6% |
| t0=59390 | 24.0% | 53.5% |
| **合计** | **均值 20.7%** | **41.9%（LONG 208 / SHORT 289）** |

- 开仓率稳定在 **16.7%~24.0%**（不是"开不了仓"，也不是过度交易）
- 方向**随行情变化**（下跌段偏空、上涨段偏多），合计无结构性偏置
- 融合分 100% 非零，`sigma = 0.489` ≤ `sigma_max = 0.8`

复跑：`& $py research/24_oos_open_rate.py`（验收线：每个预热点开仓率 ≥10%、
合计 LONG 占比 25%~75%、各窗口占比有变化）。

### 实盘已验证

重启后第一轮即 `place_grid LONG` 并**成功下单**，MT5 上可见 2 张真实挂单：

```
#2546777755 XAUUSDm buy_limit 0.01 @4353.518  SL 4341.621  TP 4371.820
#2546777770 XAUUSDm buy_limit 0.01 @4341.316  SL 4329.420  TP 4359.618
```

止损距离 ≈ **11.9 USD**（1h ATR 定尺度），而非 1m 方案的 1.13 USD。
**该轮正是旧代码崩溃的那一轮** —— 编码修复已被实盘验证。

### 仍未解决的部分（诚实披露）

`research/21_source_ir.py` 用 **triple_barrier + 非重叠** 复核后，
现有信号源的**预测技能都无法证实**（非重叠毛 NW-t 均在 0 附近）。
即：**系统会开仓，但边际优势尚未被独立证据确认。**

另外一个重要发现：**重叠会把噪声伪装成 alpha**。
chanlun 信号在 15 根 1m 上重复 → 46,559 笔"交易"实际只对应少量独立决策；
不校正重叠时毛 NW-t=+3.32（看似强 alpha），校正后跌到 0 附近。

> 下一步该做的是**找有真实 IC 的信息源**，而不是继续调阈值
> （`research/22_param_gate.py` 已判定：DSR 全 0、PBO=1.0，阈值微调无统计支撑）。

## 文档

| 文件 | 内容 |
|---|---|
| `docs/00-architecture.md` | 总体架构、主循环、模块契约 |
| `docs/02-skills-integration.md` | 两个 skill 的集成协议、8 门自检、7 步字段、降级矩阵 |
| `docs/03-llm-orchestration.md` | LLM 主路径、skill 流程强制、预算分离 |
| `docs/04-signals-fusion.md` | 卡尔曼/贝叶斯/高斯融合、去均值、IR 权重 |
| `docs/05-position-risk.md` | 仓位、Wilson 下界、方向偏置熔断、参数纪律 |
| `docs/06-decision-machine.md` | 状态机、阈值判定、验收指标 |
| `docs/08-test-plan.md` | 分层测试、每项验收对应的测试 |
| `docs/compliance/2026-commercial-trading-system-standards.md` | 商用合规标准（SR 26-2 / DSR / PBO / MinBTL） |
| `docs/compliance/README.md` | 合规资料索引 + 证据目录说明（移动目录时如何校验引用） |

## 复现

```powershell
$py = "C:\Users\admin\AppData\Local\Programs\Python\Python312\python.exe"
& $py -m pytest tests/ -q --no-header -p no:cacheprovider   # 测试套件
& $py research/21_source_ir.py --bars 60000 --write         # 权重表（P0-2）
& $py research/22_param_gate.py                             # 参数门（P2-1）
```
