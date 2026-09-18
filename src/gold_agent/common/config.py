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
    per_hour_budget: int = _TOML.get("llm", {}).get("per_hour_budget", 24)
    min_interval_min: float = _TOML.get("llm", {}).get("min_interval_min", 15.0)


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


@dataclass
class RiskConfig:
    risk_pct: float = _TOML.get("risk", {}).get("risk_pct", 0.005)
    target_vol_daily: float = _TOML.get("risk", {}).get("target_vol_daily", 0.01)
    sl_atr_mult: float = _TOML.get("risk", {}).get("sl_atr_mult", 1.2)
    tp_atr_mult: float = _TOML.get("risk", {}).get("tp_atr_mult", 2.0)
    grid_layers: int = _TOML.get("risk", {}).get("grid_layers", 3)
    grid_layer_decay: float = _TOML.get("risk", {}).get("grid_layer_decay", 0.7)
    grid_atr_mult: float = _TOML.get("risk", {}).get("grid_atr_mult", 0.8)
    martin_atr_mult: float = _TOML.get("risk", {}).get("martin_atr_mult", 1.5)
    max_group_lots_mult: float = _TOML.get("risk", {}).get("max_group_lots_mult", 3.0)
    daily_loss_stop_pct: float = _TOML.get("risk", {}).get("daily_loss_stop_pct", 0.03)
    consecutive_loss_cooloff_h: float = _TOML.get("risk", {}).get("consecutive_loss_cooloff_h", 4.0)
    consecutive_loss_n: int = _TOML.get("risk", {}).get("consecutive_loss_n", 4)
    max_drawdown_halt_pct: float = _TOML.get("risk", {}).get("max_drawdown_halt_pct", 0.12)
    max_drawdown_deleverage_pct: float = _TOML.get("risk", {}).get("max_drawdown_deleverage_pct", 0.08)
    margin_use_cap: float = _TOML.get("risk", {}).get("margin_use_cap", 0.60)
    news_blackout_min: int = _TOML.get("risk", {}).get("news_blackout_min", 15)
    max_holding_h: float = _TOML.get("risk", {}).get("max_holding_h", 48.0)


@dataclass
class DecisionConfig:
    open_threshold: float = _TOML.get("decision", {}).get("open_threshold", 1.6)
    exit_threshold: float = _TOML.get("decision", {}).get("exit_threshold", 1.2)
    exit_persist_rounds: int = _TOML.get("decision", {}).get("exit_persist_rounds", 3)
    loop_interval_s: float = _TOML.get("decision", {}).get("loop_interval_s", 60.0)
    disagreement_lot_mult: float = _TOML.get("decision", {}).get("disagreement_lot_mult", 0.5)


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
