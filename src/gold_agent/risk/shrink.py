"""挂单止盈止损收缩（docs/05 §3b，用户要求）。

问题：按最大 ATR 测算挂单 TP/SL 会导致点位空挡过大，极值点不可到达。
规则：
- 挂单 TP = 0.7 × tp_atr_mult × ATR
- 挂单 SL = 0.85 × sl_atr_mult × ATR（收紧）
- 挂单入场位 = 结构关键位内侧（向当前价收 0.15×ATR）
- 可达性校验：目标价位近 lookback 根 K 内从未触及 → 收缩到最近 swing 位
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from gold_agent.common.config import CFG


def shrink_tp(atr: float) -> float:
    # 用户指定：挂单 TP 缩 40%（系数 0.6）
    return CFG.risk.tp_atr_mult * 0.6 * atr


def shrink_sl(atr: float) -> float:
    # 用户指定：挂单 SL 缩
    return CFG.risk.sl_atr_mult * 0.65 * atr


def pull_entry_inside(level: float, direction: str, atr: float) -> float:
    """把挂单价从结构边界向当前价方向收 0.15×ATR。direction 为挂单方向。"""
    pad = 0.15 * atr
    return level - pad if direction == "LONG" else level + pad


def reachable_tp(price_target: float, direction: str, df: pd.DataFrame,
                 lookback: int = 600) -> float:
    """可达性校验：近 lookback 根内是否有 K 线触及目标价。

    - LONG：TP 为上方价 → 检查 max(high)；SHORT：检查 min(low)。
    - 未触及 → 用窗口内最近 swing 极值收缩。
    """
    if df is None or df.empty:
        return price_target
    w = df.tail(lookback)
    if direction == "LONG":
        best = float(w["high"].max())
        if best < price_target:
            # 从未触及 → 收缩到窗口最高价；但至少保留 0.3×ATR 利润空间，避免 TP 贴脸
            return max(best, price_target - 0.3 * _last_atr(df))
        return price_target
    else:
        best = float(w["low"].min())
        if best > price_target:
            return min(best, price_target + 0.3 * _last_atr(df))
        return price_target


def _last_atr(df: pd.DataFrame) -> float:
    """窗口 ATR（14 期），用于可达性收缩的下限。"""
    close = df["close"]
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - close.shift()).abs(),
        (df["low"] - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return float(tr.rolling(14).mean().iloc[-1] or 0.0)


def shrink_for_pending(direction: str, entry: float, atr: float,
                       df: pd.DataFrame, tp_raw: float | None = None) -> dict:
    """统一入口：返回 {entry, tp, sl}，全部经过收缩与可达性校验。"""
    atr = max(atr, 1e-9)
    if entry is None:
        entry = pull_entry_inside(entry or 0.0, direction, atr)
    tp_dist = shrink_tp(atr)
    sl_dist = shrink_sl(atr)
    if tp_raw is not None:
        # 结构位 TP（如对侧 OB/FVG），也做收缩：取 min(结构距离, 收缩距离)
        struct_dist = abs(tp_raw - entry)
        tp_dist = min(tp_dist, struct_dist)
    tp = entry + tp_dist if direction == "LONG" else entry - tp_dist
    sl = entry - sl_dist if direction == "LONG" else entry + sl_dist
    tp = reachable_tp(tp, direction, df)
    tp = round(tp, 3)
    sl = round(sl, 3)
    entry = round(entry, 3)
    return {"entry": entry, "tp": tp, "sl": sl}
