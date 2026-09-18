"""chanlun-trading-system skill 适配器（docs/02 §1）。

本地确定性引擎，vendor/skills/chanlun-trading-system/src 注入 path 后
直接 import chanlun_visual.engine.analyze。
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from gold_agent.common.config import CFG

_VENDOR_SRC = CFG.vendor_dir / "skills" / "chanlun-trading-system" / "src"
if str(_VENDOR_SRC) not in sys.path:
    sys.path.insert(0, str(_VENDOR_SRC))

try:
    from chanlun_visual.engine import analyze as _chanlun_analyze
    CHANLUN_AVAILABLE = True
    _IMPORT_ERROR = ""
except Exception as _e:  # pragma: no cover
    CHANLUN_AVAILABLE = False
    _IMPORT_ERROR = str(_e)

# 结构 → 分数映射（docs/02 §4）
_STRUCTURE_SCORE = {
    "trend_up": 1.0,
    "trend_down": -1.0,
    "center_oscillation": 0.0,
    "center_extension": 0.0,
    "center_breakout": 0.5,   # 方向由 breakout 方向细化
    "transition_zhongyin": 0.0,
    "insufficient_history": 0.0,
    "unknown": 0.0,
}
_SIGNAL_SCORE = {"B1": 1.0, "B2": 2.0, "B3": 3.0, "S1": -1.0, "S2": -2.0, "S3": -3.0}


@dataclass
class ChanlunResult:
    status: str = "unavailable"          # ok | unavailable | bad_input
    structure: str | None = None
    score: float = 0.0
    signals: list[dict] = field(default_factory=list)
    center: dict | None = None
    invalidation: str | None = None
    quality: dict = field(default_factory=dict)
    definition_mode: str = "research_proxy"
    raw: dict = field(default_factory=dict)
    error: str = ""
    computed_at: float = 0.0


def df_to_bars(df: pd.DataFrame) -> list[dict]:
    """MT5 DataFrame → chanlun 引擎 bars（时间严格递增、UTC ISO）。

    支持两种形态：time 为列（MT5 collector 输出）或 time 为索引（回放/重采样）。
    """
    out = []
    has_time_col = "time" in df.columns
    for idx, r in df.iterrows():
        ts = r["time"] if has_time_col else idx
        out.append({
            "date": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": float(r["close"]),
            "volume": float(r.get("tick_volume", 0) or r.get("volume", 0) or 0),
        })
    return out


def analyze_tf(df: pd.DataFrame, timeframe: str, symbol: str | None = None) -> ChanlunResult:
    result = ChanlunResult(computed_at=time.time())
    if not CHANLUN_AVAILABLE:
        result.error = f"chanlun engine import failed: {_IMPORT_ERROR}"
        return result
    try:
        bars = df_to_bars(df)
        raw = _chanlun_analyze(bars, symbol=symbol or CFG.mt5.symbol,
                               timeframe=timeframe, source="mt5")
    except Exception as e:
        result.status = "bad_input"
        result.error = str(e)
        return result
    result.status = "ok"
    result.raw = raw
    meta = raw.get("meta", {})
    result.definition_mode = meta.get("definition_mode", "research_proxy")
    state = raw.get("state", {})
    result.structure = state.get("structure")
    result.quality = raw.get("quality", {})
    result.invalidation = state.get("invalidation")

    score = _STRUCTURE_SCORE.get(result.structure or "unknown", 0.0)
    center = None
    centers = raw.get("layers", {}).get("centers", [])
    cid = state.get("current_center_id")
    for c in centers:
        if c.get("id") == cid:
            center = {"zg": c.get("zg"), "zd": c.get("zd"),
                      "direction": c.get("direction"), "status": c.get("status")}
            break
    result.center = center
    for sig in state.get("candidate_signals", []):
        kind = str(sig.get("kind", ""))
        base = _SIGNAL_SCORE.get(kind.rstrip("_candidate"), 0.0)
        if kind.endswith("_candidate"):
            base *= 0.6          # 候选未确认降权
        score += base
    # 突破方向细化
    if result.structure == "center_breakout" and center:
        last = float(df["close"].iloc[-1])
        if center.get("zg") and last > center["zg"]:
            score = abs(score)
        elif center.get("zd") and last < center["zd"]:
            score = -abs(score)
    result.score = max(-3.0, min(3.0, score))
    result.signals = state.get("candidate_signals", [])
    return result
