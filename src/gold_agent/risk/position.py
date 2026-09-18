"""仓位管理（docs/05 §1-2）与熔断器（§5）。"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import log_warn


@dataclass
class CircuitBreakers:
    """硬风控熔断（不可被 LLM/状态机绕过，docs/05 §5）。"""
    consecutive_losses: int = 0
    cooloff_until: float = 0.0
    day_pnl: float = 0.0
    day_key: str = ""
    peak_equity: float = 0.0
    martin_disabled_today: bool = False
    extra: dict = field(default_factory=dict)

    def check(self, account_equity: float, margin_used: float,
              high_risk_window: bool) -> str | None:
        """返回 REJECT 原因；None = 允许开仓。"""
        now = time.time()
        today = time.strftime("%Y-%m-%d")
        if self.day_key and self.day_key != today:
            self.day_key = today
            self.day_pnl = 0.0
            self.martin_disabled_today = False
        elif not self.day_key:
            self.day_key = today
        if now < self.cooloff_until:
            return f"cooloff_until {time.strftime('%H:%M', time.localtime(self.cooloff_until))}"
        if self.consecutive_losses >= CFG.risk.consecutive_loss_n:
            return f"consecutive_losses>={CFG.risk.consecutive_loss_n}"
        if self.day_pnl <= -CFG.risk.daily_loss_stop_pct * account_equity:
            return "daily_loss_stop"
        dd = (self.peak_equity - account_equity) / max(self.peak_equity, 1e-9) if self.peak_equity else 0.0
        if dd >= CFG.risk.max_drawdown_halt_pct:
            return f"max_drawdown {dd:.1%}"
        if margin_used > CFG.risk.margin_use_cap * account_equity:
            return "margin_cap"
        if high_risk_window:
            return "news_high_risk_window"
        # 周五深夜不开新仓
        if time.localtime().tm_wday == 4 and time.localtime().tm_hour >= 23 and time.localtime().tm_min >= 30:
            return "friday_late"
        return None

    def deleverage_k(self, account_equity: float) -> float:
        dd = (self.peak_equity - account_equity) / max(self.peak_equity, 1e-9) if self.peak_equity else 0.0
        if dd >= CFG.risk.max_drawdown_halt_pct:
            return 0.0
        if dd >= CFG.risk.max_drawdown_deleverage_pct:
            return 0.5
        return 1.0

    def on_trade_closed(self, pnl: float, equity: float) -> None:
        today = time.strftime("%Y-%m-%d")
        if self.day_key and self.day_key != today:
            self.day_key = today
            self.day_pnl = 0.0
            self.martin_disabled_today = False
        elif not self.day_key:
            self.day_key = today
        self.day_pnl += pnl
        if pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= CFG.risk.consecutive_loss_n:
                self.cooloff_until = time.time() + CFG.risk.consecutive_loss_cooloff_h * 3600
        else:
            self.consecutive_losses = 0
        self.peak_equity = max(self.peak_equity, equity)

    # ---------- 持久化 ----------
    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "CircuitBreakers":
        obj = cls()
        for k, v in d.items():
            if hasattr(obj, k):
                setattr(obj, k, v)
        return obj

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "CircuitBreakers":
        if path.exists():
            try:
                return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except Exception as e:
                log_warn(f"breakers load failed: {e}")
        return cls()


def half_kelly(p: float, b: float) -> float:
    """f* = (p·b − q)/b，返回一半（Half-Kelly）。p=胜率, b=盈亏比。"""
    q = 1 - p
    f = (p * b - q) / b
    return max(0.0, f) * 0.5


def position_lots(equity: float, atr: float, point_value_per_lot: float,
                  win_rate: float, vol_k: float = 1.0,
                  volume_min: float = 0.01, volume_step: float = 0.01,
                  volume_max: float = 10.0) -> tuple[float, str | None]:
    """ATR 风险预算 + Half-Kelly 上限 + 波动率目标系数。

    返回 (lots, reject_reason)。
    """
    if atr is None or atr <= 0:
        return 0.0, "no_atr"
    risk_usd = equity * CFG.risk.risk_pct
    # Half-Kelly 上限
    b = CFG.risk.tp_atr_mult / CFG.risk.sl_atr_mult
    f_half = half_kelly(win_rate, b)
    kelly_cap_usd = equity * f_half * 0.10     # 保守：Kelly 折 10% 上限
    risk_usd = min(risk_usd, kelly_cap_usd) if kelly_cap_usd > 0 else risk_usd
    # 波动率目标系数（外部传入 vol_k）
    risk_usd *= vol_k
    sl_points = CFG.risk.sl_atr_mult * atr / 0.001      # XAUUSDm point=0.001
    per_lot_risk = sl_points * point_value_per_lot
    if per_lot_risk <= 0:
        return 0.0, "bad_point_value"
    raw_lots = risk_usd / per_lot_risk
    lots = math.floor(raw_lots / volume_step) * volume_step
    lots = round(lots, 2)
    if lots < volume_min:
        return 0.0, "risk_budget_below_min_lot"
    lots = min(lots, volume_max, CFG.max_lot if CFG.trade_mode == "live" else volume_max)
    return lots, None


def volatility_k(realized_vol_daily: float | None, atr_daily_ratio: float | None) -> float:
    """docs/05 §2：目标波动 / 实际波动，clamp [0.25, 1.5]，黄金高波动日再 ×0.6。"""
    k = 1.0
    if realized_vol_daily and realized_vol_daily > 0:
        k = CFG.risk.target_vol_daily / realized_vol_daily
        k = float(np.clip(k, 0.25, 1.5))
    if atr_daily_ratio and atr_daily_ratio > 0.02:
        k *= 0.6
    return k
