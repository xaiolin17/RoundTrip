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
    model: str = os.getenv("RUNNINGHUB_MODEL", "glm/glm-5.3-flash")
    timeout_s: float = _TOML.get("llm", {}).get("timeout_s", 60.0)
    review_timeout_s: float = _TOML.get("llm", {}).get("review_timeout_s", 60.0)
    news_timeout_s: float = _TOML.get("llm", {}).get("news_timeout_s", 30.0)
    #: 评审（LLM-A）每小时预算。与新闻面分开计账——research/20 显示
    #: 两者共用 24 次/小时的池子时，news 会把 review 的额度吃光。
    per_hour_budget: int = _TOML.get("llm", {}).get("per_hour_budget", 24)
    #: 新闻面（LLM-B）每小时预算，独立于 review。
    news_per_hour_budget: int = _TOML.get("llm", {}).get("news_per_hour_budget", 24)
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
    grid_layers: int = _TOML.get("risk", {}).get("grid_layers", 3)
    grid_layer_decay: float = _TOML.get("risk", {}).get("grid_layer_decay", 0.7)
    grid_atr_mult: float = _TOML.get("risk", {}).get("grid_atr_mult", 0.8)
    martin_atr_mult: float = _TOML.get("risk", {}).get("martin_atr_mult", 1.5)
    max_group_lots_mult: float = _TOML.get("risk", {}).get("max_group_lots_mult", 3.0)
    # 用户规则：每仓固定 0.01 手，同向最多加仓次数
    max_adds_per_position: int = _TOML.get("risk", {}).get("max_adds_per_position", 5)
    # 用户指定：市价单 TP 缩 40%、SL 缩 （与挂单一致）
    market_tp_shrink: float = _TOML.get("risk", {}).get("market_tp_shrink", 0.6)
    market_sl_shrink: float = _TOML.get("risk", {}).get("market_sl_shrink", 0.65)
    daily_loss_stop_pct: float = _TOML.get("risk", {}).get("daily_loss_stop_pct", 0.03)
    consecutive_loss_cooloff_h: float = _TOML.get("risk", {}).get("consecutive_loss_cooloff_h", 4.0)
    consecutive_loss_n: int = _TOML.get("risk", {}).get("consecutive_loss_n", 4)
    max_drawdown_halt_pct: float = _TOML.get("risk", {}).get("max_drawdown_halt_pct", 0.12)
    max_drawdown_deleverage_pct: float = _TOML.get("risk", {}).get("max_drawdown_deleverage_pct", 0.08)
    margin_use_cap: float = _TOML.get("risk", {}).get("margin_use_cap", 0.60)
    news_blackout_min: int = _TOML.get("risk", {}).get("news_blackout_min", 15)
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


@dataclass
class DecisionConfig:
    open_threshold: float = _TOML.get("decision", {}).get("open_threshold", 1.6)
    exit_threshold: float = _TOML.get("decision", {}).get("exit_threshold", 1.2)
    exit_persist_rounds: int = _TOML.get("decision", {}).get("exit_persist_rounds", 3)
    # 利润回吐检测（用户要求：超短期有利润回吐时主动平仓）
    reserve_min_profit: float = _TOML.get("decision", {}).get("reserve_min_profit", 5.0)
    reserve_drop_score: float = _TOML.get("decision", {}).get("reserve_drop_score", 0.6)
    loop_interval_s: float = _TOML.get("decision", {}).get("loop_interval_s", 60.0)
    disagreement_lot_mult: float = _TOML.get("decision", {}).get("disagreement_lot_mult", 0.5)
    # ---- P1-2 波动 regime 闸：只在 σ 位于滚动高分位时开仓 ----
    vol_pct_min: float = _TOML.get("decision", {}).get("vol_pct_min", 0.0)
    # ---- LLM 一致性要求：aligned 时的最低 confidence ----
    llm_align_conf: float = _TOML.get("decision", {}).get("llm_align_conf", 0.6)
    #: 持仓时 LLM 反向 verdict 触发平仓的 confidence 门槛
    llm_adverse_conf: float = _TOML.get("decision", {}).get("llm_adverse_conf", 0.7)
    #: 未对齐 LLM 时是否仍允许挂网格（False = 直接 hold，等 LLM 明确表态）
    allow_grid_without_llm: bool = _TOML.get("decision", {}).get("allow_grid_without_llm", True)


@dataclass
class Config:
    trade_mode: str = os.getenv("TRADE_MODE", "live")          # live | dry_run
    max_lot: float = float(os.getenv("MAX_LOT", "0.01"))
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
