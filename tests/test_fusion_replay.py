"""融合引擎真实历史回放校准（docs/08 L5）。

优先用 data/cache/XAUUSDm_15m.parquet（MT5 拉取的长历史），
退回 D:\DDDDDDDDD\XAUUSD_1min_kline.parquet。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gold_agent.common.config import CFG
from gold_agent.fusion.engine import FusionEngine
from gold_agent.skills.chanlun_adapter import analyze_tf

HIST_15M = CFG.data_dir / "XAUUSDm_15m.parquet"
HIST_FALLBACK = Path(r"D:\DDDDDDDDD\XAUUSD_1min_kline.parquet")


def _load_15m() -> pd.DataFrame | None:
    if HIST_15M.exists():
        df = pd.read_parquet(HIST_15M)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        return df.sort_values("time").reset_index(drop=True).set_index("time")
    if HIST_FALLBACK.exists():
        df = pd.read_parquet(HIST_FALLBACK)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.sort_values("time").reset_index(drop=True).set_index("time")
        return df.resample("15min").agg({"open": "first", "high": "max", "low": "min",
                                         "close": "last", "volume": "sum"}).dropna()
    return None


@pytest.fixture(scope="module")
def hist_15m() -> pd.DataFrame:
    df = _load_15m()
    if df is None:
        pytest.skip("无可用历史数据")
    return df


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    vol_col = "tick_volume" if "tick_volume" in df.columns else "volume"
    r = df.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                               "close": "last", vol_col: "sum"}).dropna()
    return r


def _frame_like(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["spread"] = 0
    out["real_volume"] = 0
    if "tick_volume" not in out.columns:
        out["tick_volume"] = out.get("volume", 0)
    return out[["open", "high", "low", "close", "tick_volume", "spread", "real_volume"]]


def test_fusion_replay_calibration(hist_15m):
    engine = FusionEngine()
    df = hist_15m
    if len(df) < 500:
        pytest.skip(f"历史数据不足 500 根: {len(df)}")
    step, warm = 4, 400        # 15m × 4 = 1h 决策间隔；预热 400 根（约 4 天）
    points = range(warm, len(df) - 32, step)
    scores, actuals = [], []
    for i in points:
        window = df.iloc[i - warm:i]
        frames = {"1m": _frame_like(_resample(window, "1min")),
                  "5m": _frame_like(_resample(window, "5min")),
                  "15m": _frame_like(window),
                  "1h": _frame_like(_resample(window, "1h"))}
        cl = {tf: analyze_tf(frames[tf], tf) for tf in ("5m", "15m", "1h")}
        ev = engine.fuse_all(frames, cl, None)
        s = ev.result.score
        if s == 0:
            continue
        future_close = df["close"].iloc[i + 32] if i + 32 < len(df) else None
        if future_close is None:
            continue
        scores.append(s)
        actuals.append(np.sign(future_close - df["close"].iloc[i - 1]))
    assert len(scores) >= 20, f"决策点过少: {len(scores)}"
    scores = np.array(scores)
    actuals = np.array(actuals)
    hit = float(np.mean(np.sign(scores) == actuals))
    ic = float(np.corrcoef(scores, actuals)[0, 1]) if np.std(actuals) > 0 else 0.0
    print(f"replay(15m long-history): n={len(scores)} hit_rate={hit:.3f} IC={ic:.3f}")
    assert ic > -0.05, f"融合分 IC 异常: {ic:.3f}（需要权重校准）"
