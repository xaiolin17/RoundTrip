"""配置加载：config.toml（阈值）+ .env（密钥）。

所有可调参数集中于此，绝不散落常量（docs/00 §6）。
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]

load_dotenv(PROJECT_ROOT / ".env")


def _load_toml() -> dict:
    path = PROJECT_ROOT / "config.toml"
    if path.exists():
        with open(path, "rb") as f:
            return tomllib.load(f)
    return {}


_TOML = _load_toml()


@dataclass
class MT5Config:
    terminal_path: str = os.getenv("MT5_TERMINAL_PATH", r"D:\MT5\terminal64.exe")
    symbol: str = os.getenv("MT5_SYMBOL", "XAUUSDm")
    login: int | None = int(os.getenv("MT5_LOGIN")) if os.getenv("MT5_LOGIN") else None
    password: str = os.getenv("MT5_PASSWORD", "")
    server: str = os.getenv("MT5_SERVER", "")
    timeframes: tuple[str, ...] = ("1m", "2m", "5m", "10m", "15m", "30m", "1h", "4h", "8h", "1d")
    bars_per_tf: int = _TOML.get("mt5", {}).get("bars_per_tf", 600)
    magic: int = _TOML.get("mt5", {}).get("magic", 20260918)
    deviation: int = _TOML.get("mt5", {}).get("deviation", 20)


@dataclass
class LLMConfig:
    base_url: str = os.getenv("RUNNINGHUB_BASE_URL", "https://llm.runninghub.cn/v1")
    api_key: str = os.getenv("RUNNINGHUB_API_KEY", "")
    # ⚠️ 兜底默认值必须与 .env 一致。原默认为 glm/glm-5.3-flash ——
    #    那是**强制思考且关不掉**的旧模型（实测白天 review 中位 60.7 秒超时、
    #    成功率仅 22.9%）。而 `.env` 被 .gitignore 忽略、不入库，
    #    于是只要 .env 缺失或漏了这一行，项目就会**静默退回**旧模型，
    #    症状是"每轮凭空多耗 120 秒"，极难排查。
    model: str = os.getenv("RUNNINGHUB_MODEL", "deepseek/deepseek-v4.1-flash")
    #: 推理等级。界面上叫 off，**线上参数值是 "none"**（传 "off" 会 400
    #: InvalidParameter）。实测 deepseek/deepseek-v4.1-flash：
    #:   none -> 无 reasoning_content，completion 106 tok
    #:   low  -> reasoning_content 1506 字符，completion 560 tok
    #: ⚠️ 默认值由 "" 改为 "none"：留空 = 不带该参数 = 模型默认 = **开启思考**，
    #:    与"关闭推理"的要求相反。改默认值后，即使 .env 漏了这一行也仍然关闭。
    reasoning_effort: str = os.getenv("RUNNINGHUB_REASONING_EFFORT", "none")
    timeout_s: float = _TOML.get("llm", {}).get("timeout_s", 60.0)
    review_timeout_s: float = _TOML.get("llm", {}).get("review_timeout_s", 60.0)
    news_timeout_s: float = _TOML.get("llm", {}).get("news_timeout_s", 30.0)
    #: 评审（LLM-A）每小时预算。与新闻面分开计账——research/20 显示
    #: 两者共用 24 次/小时的池子时，news 会把 review 的额度吃光。
    per_hour_budget: int = _TOML.get("llm", {}).get("per_hour_budget", 24)
    #: 新闻面（LLM-B）每小时预算，独立于 review。
    news_per_hour_budget: int = _TOML.get("llm", {}).get("news_per_hour_budget", 24)
    #: 加仓复核（LLM-C）每小时预算，独立于 review/news。
    #: ⚠️ 必须独立：加仓复核是"每笔加仓一次"，若与 review 共用池子，
    #:    会在加仓活跃时把主评审的额度吃光（research/20 已记录过同类事故：
    #:    news 挤占 review 导致 review 覆盖率跌到 4.3%）。
    #:    默认 24 与 review 同级；复核失败只是"不加仓"，不会影响主流程。
    add_review_per_hour_budget: int = _TOML.get("llm", {}).get(
        "add_review_per_hour_budget", 24)
    #: 评审最小间隔（分钟）。1h 决策周期下应为 0（每轮都评审）。
    min_interval_min: float = _TOML.get("llm", {}).get("min_interval_min", 0.0)
    #: review 失败重试次数（换温度 0）
    retry: int = _TOML.get("llm", {}).get("retry", 1)


@dataclass
class MobiusConfig:
    base_url: str = _TOML.get("mobius", {}).get("base_url", "https://api.mobiusquant.ai")
    cache_ttl_s: float = _TOML.get("mobius", {}).get("cache_ttl_s", 60.0)
    rate_per_min: int = _TOML.get("mobius", {}).get("rate_per_min", 10)
    stale_max_age_s: float = _TOML.get("mobius", {}).get("stale_max_age_s", 300.0)


@dataclass
class Jin10Config:
    base_url: str = os.getenv("JIN10_BASE_URL", "https://mcp.jin10.com/mcp")
    token: str = os.getenv("JIN10_TOKEN", "")
    cache_ttl_s: float = _TOML.get("news", {}).get("jin10_cache_ttl_s", 30.0)


@dataclass
class FusionConfig:
    hurst_window: int = _TOML.get("fusion", {}).get("hurst_window", 500)
    bayes_window: int = _TOML.get("fusion", {}).get("bayes_window", 300)
    sigma_max: float = _TOML.get("fusion", {}).get("sigma_max", 0.8)
    #: 贝叶斯证据**负向钳制**（用户选定：表现差的源不能无限反打）。
    #: 事故背景：贝叶斯池 9胜20负（p=0.32）-> evidence() 的 logit=-0.74
    #: -> 分数为正时每个源被压 -0.94，4 源叠加把融合分拉低 0.3~0.5，
    #:    加上信号源本身走弱，508 轮无一达到开仓阈值 1.3。
    #: 现在：负证据最多压到 -evidence_floor，避免"越亏越反向"的自我强化。
    #: 正证据不钳制（表现好的源应充分投票）。
    bayes_evidence_floor: float = _TOML.get("fusion", {}).get("bayes_evidence_floor", 0.3)
    # ---- P0-1 源去均值（滚动 z-score）----
    norm_window: int = _TOML.get("fusion", {}).get("norm_window", 1440)
    norm_min_periods: int = _TOML.get("fusion", {}).get("norm_min_periods", 240)
    # ---- P1-2 波动分位 ----
    vol_pct_window: int = _TOML.get("fusion", {}).get("vol_pct_window", 1440)
    vol_pct_min_periods: int = _TOML.get("fusion", {}).get("vol_pct_min_periods", 240)
    # ---- P1-3 融合分滚动基线 ----
    baseline_window: int = _TOML.get("fusion", {}).get("baseline_window", 1440)
    baseline_min_periods: int = _TOML.get("fusion", {}).get("baseline_min_periods", 240)
    # ---- 启动预热（1m 短线：不预热则前 min_periods 轮永不开仓）----
    # prime_steps = 回放多少轮；prime_step_bars = 每轮跨多少根 1m
    prime_steps: int = _TOML.get("fusion", {}).get("prime_steps", 300)
    prime_step_bars: int = _TOML.get("fusion", {}).get("prime_step_bars", 1)


@dataclass
class RiskConfig:
    risk_pct: float = _TOML.get("risk", {}).get("risk_pct", 0.005)
    target_vol_daily: float = _TOML.get("risk", {}).get("target_vol_daily", 0.01)
    sl_atr_mult: float = _TOML.get("risk", {}).get("sl_atr_mult", 1.2)
    tp_atr_mult: float = _TOML.get("risk", {}).get("tp_atr_mult", 2.0)
    # 止损用哪个周期的 ATR（research/23：1m 短线必须用高级别，否则成本吃掉止损）
    atr_tf: str = _TOML.get("risk", {}).get("atr_tf", "1h")
    # ---- 已删除的死配置（2026-09-30，用户要求「不能放没有作用的死代码」）----
    # `grid_layers` / `grid_layer_decay` / `grid_atr_mult` / `martin_atr_mult` /
    # `max_group_lots_mult`：网格已按用户要求取消（只挂预测的那一张限价单），
    # 这 5 个键全项目**零真实引用**（网格状态机 risk/grid.py 已整体删除）。
    # `structure_enabled` / `structure_sl_max_atr` / `structure_frac_lo` /
    # `structure_frac_hi`：同样是零引用；且经实测（position_lots 反推）
    # 止损宽度本身已被风险预算自然约束 —— sl_dist 从 5 放大到 300 点时，
    # 实际风险恒在名义预算内（最大 0.500%），再宽则直接 `risk_budget_below_min_lot`
    # 拒单。所以"止损上限"这个安全阀是冗余的，删掉不降低任何保护。
    # `decision.reserve_drop_score`：已被 z 尺度的 `reserve_drop_z` 取代
    # （0.6 绝对分 ÷ 旧 σ 0.4895 ≈ 1.23 z，两者等价）。
    # 用户规则：每仓固定 0.01 手，同向最多加仓次数
    max_adds_per_position: int = _TOML.get("risk", {}).get("max_adds_per_position", 5)
    # 用户指定：市价单 TP 缩 40%、SL 缩 （与挂单一致）
    market_tp_shrink: float = _TOML.get("risk", {}).get("market_tp_shrink", 0.6)
    market_sl_shrink: float = _TOML.get("risk", {}).get("market_sl_shrink", 0.65)
    # ---- 缠论结构定价（用户要求：用 0.618 回调 / 分型两倍 / 1.618 扩展）----
    # 用哪个周期的结构定 SL/TP。用户选定 15m（实测分型两倍≈33.8，
    # 1h 是 73.8、4h 是 149.0，差 4.4 倍）。
    structure_tf: str = _TOML.get("risk", {}).get("structure_tf", "15m")
    # 结构止损的**下限**宽度（×ATR）：防贴脸止损（实测 15m 笔只给 0.243）。
    # 在 levels.py:397 真实生效。上限/占比区间已删除，理由见上。
    structure_sl_min_atr: float = _TOML.get("risk", {}).get("structure_sl_min_atr", 0.5)
    # ---- 压力位/支撑位定价（用户要求：止损止盈看压力位，由 LLM 判断）----
    # 止损放在支撑/压力位之外时额外让开的距离（×ATR），防贴边被扫
    level_pad_atr: float = _TOML.get("risk", {}).get("level_pad_atr", 0.25)
    # 最小盈亏比：止盈距离 < 止损距离 × 该值 → 不开仓
    min_rr: float = _TOML.get("risk", {}).get("min_rr", 1.2)
    # ---- 加仓专用定价（用户 2026-10-08 指定）----
    # 用户原话：
    #   > 加仓的止损位置应该是按照止盈位置计算来的 盈亏比1.2
    #   > 然后加仓的单子止盈点不能按照计算的数值来 要对应缩小42% 也就是原值的58%
    # 语义：加仓先由结构位算出止盈目标，其**距离**缩到 add_tp_shrink 倍，
    #       再由缩后的止盈距离按 min_rr 反推止损（止损不再取自支撑位）。
    # 0.58 = 缩 42%。设为 1.0 即关闭缩放（退回"止盈不缩"的行为）。
    add_tp_shrink: float = _TOML.get("risk", {}).get("add_tp_shrink", 0.58)
    # 加仓定价后是否再让 LLM 复核这一单是否值得加（用户 2026-10-08 指定）：
    #   > 要注意计算了新的加仓位置和止盈止损点 让大模型再评判这个单子
    #   > 是否还值得加仓 如果被否决就不加仓了
    # LLM 不可用（超时/接口故障）时**不加仓**（用户选定：严格）。
    add_llm_review: bool = _TOML.get("risk", {}).get("add_llm_review", True)
    # LLM 没给出可用压力位时是否仍允许开仓
    # 用户选定 False：**不开仓，等 LLM 可用**（猜点位比不交易更危险）
    allow_trade_without_llm_levels: bool = _TOML.get("risk", {}).get(
        "allow_trade_without_llm_levels", False)
    # ---- 自研回调检测（用户要求：非严格缠论要加上我们直接的处理）----
    # 实测缠论代理引擎在 1m 图上返回的是 15m 级别的段（1m 报的段与 15m
    # 完全相同），导致入场位离现价 12~32 点、几乎不成交。所以自己算摆动。
    # 扫这些小周期，选"入场带离现价最近"的那个（用户要求小周期判断、
    # 加大入场次数）。
    pullback_tfs: tuple[str, ...] = tuple(_TOML.get("risk", {}).get(
        "pullback_tfs", ["1m", "2m", "5m", "10m", "15m", "30m"]))
    #: 摆动确认根数（左右各 k 根）；多试几个 k 提高候选覆盖
    pullback_swing_k: tuple[int, ...] = tuple(_TOML.get("risk", {}).get(
        "pullback_swing_k", [1, 2, 3]))
    #: 段幅度噪音门槛（×ATR）：实测 1m k=1 会给出 2.8 点的纯噪音段，
    #: 0.25×ATR 能正确滤掉
    pullback_min_leg_atr: float = _TOML.get("risk", {}).get(
        "pullback_min_leg_atr", 0.25)
    #: 回调带两条边（用户选定"0.5~0.618 挂单带，带内挂一单"）
    #: 实测成交率提升：2m 79.6%->86.7%，15m 73.8%->86.2%
    pullback_band_near: float = _TOML.get("risk", {}).get(
        "pullback_band_near", 0.5)
    pullback_band_far: float = _TOML.get("risk", {}).get(
        "pullback_band_far", 0.618)
    # ---- 中枢位置闸（用户反馈"单子经常挂在中枢中部"）----
    #: 是否禁止在中枢**中部**开新仓（用户选定：先加硬闸）
    zhongshu_gate: bool = _TOML.get("risk", {}).get("zhongshu_gate", True)
    #: 判定"贴边"的归一化带宽（两端各此值，中间为禁止区）
    #: 0.30 -> 中部 40% 为禁区。放宽到 0.5 会等于禁止一切非突破入场。
    zhongshu_edge_band: float = _TOML.get("risk", {}).get(
        "zhongshu_edge_band", 0.30)
    #: 优先取哪个周期的中枢（用户选定：5m 为主，1m 兜底）
    zhongshu_tfs: tuple = tuple(_TOML.get("risk", {}).get(
        "zhongshu_tfs", ["5m", "1m"]))
    #: 中枢宽度下限（×ATR）；低于此值视为退化/噪音中枢，不作为判据
    zhongshu_min_width_atr: float = _TOML.get("risk", {}).get(
        "zhongshu_min_width_atr", 0.25)
    daily_loss_stop_pct: float = _TOML.get("risk", {}).get("daily_loss_stop_pct", 0.03)
    consecutive_loss_cooloff_h: float = _TOML.get("risk", {}).get("consecutive_loss_cooloff_h", 4.0)
    consecutive_loss_n: int = _TOML.get("risk", {}).get("consecutive_loss_n", 4)
    max_drawdown_halt_pct: float = _TOML.get("risk", {}).get("max_drawdown_halt_pct", 0.12)
    max_drawdown_deleverage_pct: float = _TOML.get("risk", {}).get("max_drawdown_deleverage_pct", 0.08)
    margin_use_cap: float = _TOML.get("risk", {}).get("margin_use_cap", 0.60)
    news_blackout_min: int = _TOML.get("risk", {}).get("news_blackout_min", 15)
    #: 新闻高危窗口熔断是否生效。
    #: ⚠️ 原实现把 `high_risk_window=False` 写死在 gate.py 的调用处，于是
    #: `CircuitBreakers` 里的 `news_high_risk_window` 分支**从未触发过**，
    #: 上面的 `news_blackout_min` 也成了无人读取的死配置。注释声称
    #: 「news 高危由 decision 传入 flags」，但 decision 层只做 hold/降手数，
    #: 并不回传熔断标志 —— 这条熔断实际是被静默摘掉的。
    #: 改为可配置，**默认仍为 false**（保持既有行为，不在本次顺手改变风控松紧），
    #: 但至少可被显式打开、且这个"关着"的事实是可观测的。
    news_high_risk_window: bool = _TOML.get("risk", {}).get(
        "news_high_risk_window", False)
    #: 缠论/结构冲突判定的"贴脸"阈值（ATR 倍数）。
    #: ⚠️ 原为 levels.py 里 6 处硬编码 `0.3 * atr`，是实测 180 次
    #: `fusion_vs_levels_conflict` 拒绝里 159 次的**唯一驱动常数**，
    #: 却无法调参。同等地位的 structure_sl_min_atr / level_pad_atr
    #: 早已走配置，此处补齐。
    conflict_atr_mult: float = _TOML.get("risk", {}).get("conflict_atr_mult", 0.3)
    #: 「紧贴反向位」不再是**硬拒**，而是降仓（用户选定：证据不支持硬拦）。
    #: 实证（research/26_conflict_gate_test.py，13879 样本 / 61 天 / 5 个前瞻窗口）：
    #: 贴脸组的远期收益与对照组**统计上无差异**（全部 |t| < 1.96，
    #: 日块自助 20/20 格不显著，k=10 一致），点估计还有 6/10 格**反向**。
    #: 即"贴脸就被压回"这一机制没有得到数据支持。
    #: 但该研究对 h=60 的检出力只到约 2~3 点，**不足以证明安全**，
    #: 所以也不删掉这条风控 —— 改为按此系数降仓：
    #: 保留"结构不利就少下注"的审慎，同时不再把 205 次强信号（|z|>=2.66）
    #: 全部挡在门外。设为 0.0 即等价于原硬拒行为。
    conflict_lot_mult: float = _TOML.get("risk", {}).get("conflict_lot_mult", 0.5)
    max_holding_h: float = _TOML.get("risk", {}).get("max_holding_h", 48.0)
    # ---- P2-2 方向偏置熔断：近 N 笔同向占比超阈值 → 停机复查 ----
    direction_bias_window: int = _TOML.get("risk", {}).get("direction_bias_window", 100)
    direction_bias_max: float = _TOML.get("risk", {}).get("direction_bias_max", 0.85)
    #: 生效所需的最少样本（样本不足时该熔断不触发）
    direction_bias_min_samples: int = _TOML.get("risk", {}).get(
        "direction_bias_min_samples", 20)
    # ---- P2-3 交割单样本量门槛 ----
    #: 胜率参与 Kelly 计算所需的最少交割单样本
    min_deals_for_kelly: int = _TOML.get("risk", {}).get("min_deals_for_kelly", 10)
    #: Kelly 冷启动胜率（交割单样本不足时用）。原为 gate.py 两处硬编码 `0.5`。
    #: 它直接进 half_kelly -> 手数上限，是**真实影响仓位**的参数，
    #: 却无法调整（不同品种/策略的先验胜率并不都是 0.5）。补齐为真配置。
    cold_start_win_rate: float = _TOML.get("risk", {}).get("cold_start_win_rate", 0.5)
    #: 限价挂单有效期（小时）。原为 gate.py 硬编码 `4 * 3600` 秒。
    #: MT5 挂单到期即自动撤销，该值决定"挂单能等多久行情"。
    pending_expiry_h: float = _TOML.get("risk", {}).get("pending_expiry_h", 4.0)


@dataclass
class DecisionConfig:
    # ---- 开/平仓阈值：**z 尺度**（尺度无关），不是融合分的绝对值 ----
    #
    # ⚠️ 2026-09-29 第四次修正（用户指出的隐蔽耦合）：
    #   融合分 S 是**加权平均** S = Σwμ/Σw，故其尺度恰好是
    #       sd(S) = 1/√Σw = `FusionResult.sigma`
    #   而旧实现用**绝对常数**去比它：`abs(S) >= open_threshold`。
    #   于是同一行代码的含义随权重漂移：
    #       Σw = 4.17（旧冻结基线）→ σ=0.4895 → |S|≥1.3 实为 |z|≥2.66
    #       Σw = 12.0（等权收缩）  → σ=0.2887 → |S|≥1.3 实为 |z|≥4.50
    #   即**权重越大（越有把握）→ 越难开仓**，方向正好反了。
    #   用户原话：「本来要改的就是权重影响开仓 但是权重即会增大也会减小才对」。
    #
    #   改成 z 尺度后，权重对开仓的影响变成**双向且方向正确**：
    #       源越多/越确定 → Σw 大 → σ 小 → 同样强度的信号 z 更大 → 更容易开；
    #       源被剔除/不确定 → Σw 小 → σ 大 → 更难开。
    #   这正是"权重影响开仓"应有之义，且 `z_min` 从此与权重解耦，
    #   不会再被下一次权重改动静默改掉入场松紧。
    #
    #   标定：取当前**实际生效**的 z（1.3/0.4895 = 2.66）为默认值，
    #   故本次改动不改变当前入场松紧，只把耦合去掉。
    #   6.5 年回放：z_min=2.66 → 开仓率 14.0%/17.0%（旧绝对阈值下为 12.3%/21.3%）。
    z_min: float = _TOML.get("decision", {}).get("z_min", 2.66)
    #: 兼容字段：**仅供日志/参数门显示**的等效绝对阈值，不参与判定。
    #: 真实判定一律走 `z_min`（`machine.py`）。
    open_threshold: float = _TOML.get("decision", {}).get("open_threshold", 1.3)
    #: 平仓的 z 门槛。原 `exit_threshold` 的等效 z ≈ 1.2/0.4895 = 2.45。
    z_exit: float = _TOML.get("decision", {}).get("z_exit", 2.45)
    exit_threshold: float = _TOML.get("decision", {}).get("exit_threshold", 1.2)
    # ⚠️ `exit_persist_rounds` 已于 2026-09-30 **删除**：平仓判据改成
    #    「窗口不一致率」后（见下方 `exit_adverse_window`），代码里已无人读它。
    #    留着就是一个"改了没反应"的死配置 —— 用户明确反对
    #    （"不能放一个没有作用的死代码在那吧，我这是商用项目"）。
    # ---- 主动平仓闸（用户 2026-09-30 要求）----
    # 用户原话：「除非行情和持仓方向不一致率非常高，否则不轻易主动平仓，
    #            只修改止损和止盈位置」。
    #
    # 为什么用「窗口不一致率」而不是「连续 N 轮」：
    #   原实现是 `连续 exit_persist_rounds(3) 轮逆向 → 平仓`。实测 09-23 起
    #   2283 个持仓轮里 **46% 是逆向轮**（逐日 29%~69%），噪声很大 —— 3 轮
    #   连续逆向在随机游走下极常见，实测按连续段去重触发 **129 次**，
    #   是过度交易而非风控。改成尾部窗口的**比例**后，同一批数据只触发 **7 次**。
    #   窗口取 20 轮：按实测轮间隔中位 76s ≈ 25 分钟，足够构成"持续"，
    #   又不至于慢到错过真正的反转。
    #   （以上数字在日志清除伪造轮次后重算，见 logging_util 的 `_live` 说明。）
    exit_adverse_window: int = _TOML.get("decision", {}).get("exit_adverse_window", 20)
    exit_adverse_rate: float = _TOML.get("decision", {}).get("exit_adverse_rate", 0.8)
    #: 信号类平仓（连续不利 / 信号回吐）改为**只改止损止盈**时，
    #: 用于**计算**目标 TP 位（新止损距离 × 本值）。
    #: ⚠️ 这**不是**放行门槛：收窄 SL/TP（把止损止盈往里收）**不受 min_rr 限制**
    #: （用户明确要求），因为它降低而非增加风险敞口。
    #: `min_rr` 只约束开仓/挂单时刻的赔率。
    signal_exit_tp_rr: float = _TOML.get("decision", {}).get("signal_exit_tp_rr", 1.2)
    # 利润回吐检测（用户选定：改用移动止损锁盈，不再砍掉浮盈）
    # ⚠️ 事故复盘：旧逻辑「浮盈回吐 50% 就平仓」实测砍掉 30%~75% 浮盈
    #    （2558982555 MFE$11.63 -> 平$2.96），实际 RR 0.64 < 计划 1.28。
    #    现在浮盈达 lock_profit_min_usd 后把 SL 推到保本上方 lock_profit_gap_usd，
    #    让利润奔跑；仅当浮盈从峰值回落到保本线以下才离场。
    lock_profit_min_usd: float = _TOML.get("decision", {}).get("lock_profit_min_usd", 8.0)
    lock_profit_gap_usd: float = _TOML.get("decision", {}).get("lock_profit_gap_usd", 2.0)
    reserve_min_profit: float = _TOML.get("decision", {}).get("reserve_min_profit", 5.0)
    #: 信号回吐平仓的**z 落差**（峰值 z − 当前 z）。
    #: 原 `reserve_drop_score=0.6` 是绝对分落差；在旧尺度（σ=0.4895）上
    #: 等效 z 落差 0.6/0.4895 ≈ 1.23，故取 1.23 保持当前行为不变。
    reserve_drop_z: float = _TOML.get("decision", {}).get("reserve_drop_z", 1.23)
    loop_interval_s: float = _TOML.get("decision", {}).get("loop_interval_s", 60.0)
    #: 权重未校准时的**降仓系数**（用户 2026-09-29 选定）。
    #:
    #: 背景：`fusion/weights.py` 用 DerSimonian-Laird 收缩分配权重——
    #: `w = lambda·实测 + (1−lambda)·等权`。本窗口源间差异不显著于抽样
    #: 噪声（Q≈0.14 < df=2 → tau^2=0 → lambda=0），故三个可测源等权、
    #: 系统照常开仓。但"分不出源的高下"意味着**置信度低**，
    #: 正确的表达位置是**仓位**，不是"开/不开"这个二值开关：
    #: 低置信度 → 小仓位，而不是零交易。
    #:
    #: 取 0.5 的理由：与同层的 `disagreement_lot_mult` / `news_impact_lot_mult`
    #: 同量级（都是"证据不足时减半"）。lambda ≥ LAMBDA_CALIBRATED 后
    #: 数据已能排序，本系数不再生效（自动恢复全仓）。
    uncalibrated_lot_mult: float = _TOML.get("decision", {}).get(
        "uncalibrated_lot_mult", 0.5)
    #: 校准可选的前置条件（见 fusion/weights.py 的收缩估计量）。
    disagreement_lot_mult: float = _TOML.get("decision", {}).get("disagreement_lot_mult", 0.5)
    # ---- P1-2 波动 regime 闸：只在 σ 位于滚动高分位时开仓 ----
    vol_pct_min: float = _TOML.get("decision", {}).get("vol_pct_min", 0.0)
    # ---- LLM 一致性要求：aligned 时的最低 confidence ----
    llm_align_conf: float = _TOML.get("decision", {}).get("llm_align_conf", 0.6)
    #: 持仓时 LLM 反向 verdict 触发平仓的 confidence 门槛
    llm_adverse_conf: float = _TOML.get("decision", {}).get("llm_adverse_conf", 0.7)
    #: 未对齐 LLM 时是否仍允许挂网格（False = 直接 hold，等 LLM 明确表态）
    allow_grid_without_llm: bool = _TOML.get("decision", {}).get("allow_grid_without_llm", True)
    #: 只在均值回归 regime 用挂单，其余一律市价开仓（用户选定）。
    #: 用户原话："现在这种很难下单 我们要考虑用直接按照市价开仓 少用挂单"
    #: 实测：挂单 65.5% 被撤销，且挂单存在期间 `_decide_flat` 不执行
    #: -> 强信号被挂单阻塞 167 轮。
    pending_only_in_mean_revert: bool = _TOML.get("decision", {}).get(
        "pending_only_in_mean_revert", True)
    # ---- news「独立证据」通道（用户选定：不抢方向权重，做事件风险闸）----
    #
    # ⚠️ 为什么不是给 news 加方向权重：`weights.py` 的硬规则是
    #    「没有实测 IR 数字的源 = 0 权重」。news 从未做过 IR 校准，
    #    给它方向权重等于用未验证信号做方向 —— 正是该规则要禁止的。
    #
    # 但 news 现在**完全没用上**：实测 7874 轮里 news 从未进入 per_source，
    #    因为权重 0 被 gaussian.fuse 排除；LLM 的 news_assessment 拿到后
    #    触发一次 `fuse_all` 重融合，实测融合分一字不变（news_score 从
    #    0 → +1.5 → -1.5，融合分恒为 +1.438195），纯空操作。
    #
    # 所以把 news 做成**事件风险闸**：它不影响方向，只影响"要不要开/开多大"。
    #    这与它「未验证」的定位一致，且立刻产生实际作用。
    #: LLM 新闻影响度 >= 此值 → 不开新仓（等事件过去）
    news_impact_block: float = _TOML.get("decision", {}).get("news_impact_block", 0.70)
    #: LLM 新闻影响度 >= 此值 → 新仓手数 × news_impact_lot_mult
    news_impact_reduce: float = _TOML.get("decision", {}).get("news_impact_reduce", 0.40)
    #: LLM 新闻影响度 >= 此值 **且与持仓反向** → 立即平仓评估（docs/06 §3.2 / docs/07）。
    #: ⚠️ 原为 `machine.py` 里的硬编码 `0.8`，是三个新闻档位（0.40 降仓 /
    #: 0.70 不开新仓 / 0.8 反向平仓）中**唯一不可调**的一个 ——
    #: 调 `news_impact_block` 对已持仓的反向平仓**毫无影响**，属于
    #: "看起来能调、实际调不动"的假参数。现补齐为真配置，默认 0.8 保持不变。
    news_impact_close: float = _TOML.get("decision", {}).get("news_impact_close", 0.80)
    #: 事件降级时的手数系数
    news_impact_lot_mult: float = _TOML.get("decision", {}).get(
        "news_impact_lot_mult", 0.5)


@dataclass
class Config:
    trade_mode: str = os.getenv("TRADE_MODE", "live")          # live | dry_run
    max_lot: float = float(os.getenv("MAX_LOT", "0.01"))
    #: 加仓单层手数。原为 gate.py 里 6 处硬编码 0.01（含上限判定），
    #: 与 `MAX_LOT=0.06` 撞车导致 add_no 的 4/5 层永不可达（153 次空转）。
    add_layer_lots: float = float(os.getenv("ADD_LAYER_LOTS", "0.01"))
    #: 交易所最小手数（低于此值无法下单）。用于判定"剩余额度还能不能加"。
    min_lot: float = float(os.getenv("MIN_LOT", "0.01"))
    project_root: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data" / "cache"
    log_dir: Path = PROJECT_ROOT / "logs"
    state_path: Path = PROJECT_ROOT / "data" / "state.json"
    vendor_dir: Path = PROJECT_ROOT / "vendor"
    mt5: MT5Config = field(default_factory=MT5Config)
    llm: LLMConfig = field(default_factory=LLMConfig)
    mobius: MobiusConfig = field(default_factory=MobiusConfig)
    jin10: Jin10Config = field(default_factory=Jin10Config)
    fusion: FusionConfig = field(default_factory=FusionConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    decision: DecisionConfig = field(default_factory=DecisionConfig)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


CFG = Config()
