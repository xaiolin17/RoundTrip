"""高斯融合（docs/04 §3）：逆方差加权 + 分歧检测 + Hurst regime。"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class SourceView:
    name: str
    score: float        # μ
    sigma: float        # 不确定度
    status: str = "ok"  # ok | stale | unavailable


@dataclass
class FusionResult:
    score: float = 0.0
    sigma: float = 3.0
    disagreement: bool = False
    regime: str = "unknown"          # trending | mean_reverting | transition
    hurst: float | None = None
    per_source: list[dict] = field(default_factory=list)
    bayes_log_odds: float = 0.0


def _hurst_rs(series: np.ndarray, min_chunk: int = 8) -> float | None:
    """R/S 分析估计 Hurst 指数。>0.5 趋势（持续性），<0.5 均值回归。"""
    n = len(series)
    if n < min_chunk * 4:
        return None
    log_ret = np.diff(np.log(series[np.abs(series) > 1e-9] + 0.0)) if n > 1 else None
    if log_ret is None or len(log_ret) < 32:
        return None
    sizes = []
    rs_values = []
    for size in (16, 32, 64, 128, 256):
        if size > len(log_ret) // 2:
            continue
        m = len(log_ret) // size
        if m < 1:
            continue
        chunks = log_ret[:m * size].reshape(m, size)
        means = chunks.mean(axis=1, keepdims=True)
        dev = np.cumsum(chunks - means, axis=1)
        r = dev.max(axis=1) - dev.min(axis=1)
        s = chunks.std(axis=1, ddof=1)
        valid = s > 1e-12
        if valid.sum() >= 2:
            sizes.append(size)
            rs_values.append(float(np.mean(r[valid] / s[valid])))
    if len(sizes) < 3:
        return None
    x = np.log(np.array(sizes, dtype=float))
    y = np.log(np.array(rs_values, dtype=float))
    slope, _ = np.polyfit(x, y, 1)
    return float(np.clip(slope, 0.0, 1.0))


def fuse(sources: list[SourceView], bayes_contrib: dict[str, float],
         closes_1m: np.ndarray) -> FusionResult:
    """逆方差加权融合。

    bayes_contrib: {source: log_odds 证据}（来自 BayesianPool.evidence）
    """
    out = FusionResult()
    usable = [s for s in sources if s.status != "unavailable" and np.isfinite(s.score)]
    if not usable:
        return out

    # Hurst regime
    h = _hurst_rs(closes_1m[-CFG_HURST:] if len(closes_1m) > CFG_HURST else closes_1m)
    out.hurst = h
    if h is None:
        out.regime = "unknown"
    elif h > 0.55:
        out.regime = "trending"
    elif h < 0.45:
        out.regime = "mean_reverting"
    else:
        out.regime = "transition"

    inv_vars, weighted = [], []
    for s in usable:
        sigma = max(s.sigma, 0.05)
        w = 1.0 / (sigma * sigma)
        if s.status == "stale":
            w *= 0.7
        bc = bayes_contrib.get(s.name, 0.0)
        mu = s.score + bc          # 贝叶斯证据并入该源
        inv_vars.append(w)
        weighted.append(w * mu)
        out.per_source.append({"name": s.name, "score": round(s.score, 3),
                               "sigma": round(s.sigma, 3), "bayes": round(bc, 3),
                               "status": s.status, "w": round(w, 4)})
    total_w = sum(inv_vars)
    out.score = float(np.clip(sum(weighted) / total_w, -3.0, 3.0))
    out.sigma = float(min(3.0, 1.0 / np.sqrt(total_w)))
    out.bayes_log_odds = float(sum(bayes_contrib.values()))
    # 分歧检测
    for s in usable:
        if abs(s.score - out.score) > 2.0 * max(out.sigma, 0.3):
            out.disagreement = True
            break
    return out


CFG_HURST = 500   # 由 config 提供；这里取模块级默认，runner 会覆写
