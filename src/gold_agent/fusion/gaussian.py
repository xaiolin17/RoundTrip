"""高斯融合（docs/04 §3）：IR 加权 + 分歧检测 + Hurst regime。

权重语义（research/18 P0-2）
---------------------------
`SourceView.weight` 显式给出时**优先使用**该权重（来自实测 IR），否则退回
`1/sigma²` 逆方差加权。这样"谁影响力大"由 `research/21_source_ir.py` 产出的
数字决定，而不是代码里手填的 sigma 常数。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class SourceView:
    name: str
    score: float        # μ（已去均值）
    sigma: float        # 不确定度
    status: str = "ok"  # ok | stale | unavailable
    weight: float | None = None   # 实测 IR² 权重；None → 用 1/sigma²
    raw_score: float | None = None  # 去均值前的原始分（审计用）
    ir: float | None = None         # 实测 IR（审计用）


@dataclass
class FusionResult:
    score: float = 0.0
    sigma: float = 3.0
    disagreement: bool = False
    regime: str = "unknown"          # trending | mean_reverting | transition
    hurst: float | None = None
    per_source: list[dict] = field(default_factory=list)
    bayes_log_odds: float = 0.0
    # P1-3：融合分滚动基线（阈值零点校正用）
    score_baseline: float = 0.0
    # P1-2：当前波动率在滚动窗口中的分位
    vol_percentile: float = 0.5
    # 审计：本轮实际参与加权的源数与总权重
    effective_weight: float = 0.0


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
         closes_1m: np.ndarray, hurst_window: int = 500) -> FusionResult:
    """加权融合。

    权重优先级：`SourceView.weight`（实测 IR²）> `1/sigma²`（逆方差回退）。
    总权重为 0 时返回中性结果（S=0, σ=3）—— 没有任何已验证的源能给出方向。
    """
    out = FusionResult()
    usable = [s for s in sources
              if s.status != "unavailable" and np.isfinite(s.score)]
    if not usable:
        return out

    # Hurst regime
    win = min(int(hurst_window), len(closes_1m))
    h = _hurst_rs(closes_1m[-win:] if win > 0 else closes_1m)
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
        w = float(s.weight) if s.weight is not None else 1.0 / (sigma * sigma)
        if not np.isfinite(w) or w <= 0:
            # 0 权重源：记录但不参与加权（未验证的源不得影响方向）
            out.per_source.append({"name": s.name, "score": round(s.score, 3),
                                   "raw_score": (None if s.raw_score is None
                                                 else round(s.raw_score, 3)),
                                   "sigma": round(s.sigma, 3), "bayes": 0.0,
                                   "status": s.status, "w": 0.0,
                                   "ir": s.ir, "excluded": "zero_weight"})
            continue
        if s.status == "stale":
            w *= 0.7
        bc = bayes_contrib.get(s.name, 0.0)
        mu = s.score + bc          # 贝叶斯证据并入该源
        inv_vars.append(w)
        weighted.append(w * mu)
        out.per_source.append({"name": s.name, "score": round(s.score, 3),
                               "raw_score": (None if s.raw_score is None
                                             else round(s.raw_score, 3)),
                               "sigma": round(s.sigma, 3), "bayes": round(bc, 3),
                               "status": s.status, "w": round(w, 4),
                               "ir": s.ir})
    total_w = float(sum(inv_vars))
    out.effective_weight = total_w
    if total_w <= 0:
        # 没有已验证的源 → 不给方向（宁可空仓，也不用未验证信号交易）
        out.score = 0.0
        out.sigma = 3.0
        out.bayes_log_odds = float(sum(bayes_contrib.values()))
        return out
    out.score = float(np.clip(sum(weighted) / total_w, -3.0, 3.0))
    out.sigma = float(min(3.0, 1.0 / np.sqrt(total_w)))
    out.bayes_log_odds = float(sum(bayes_contrib.values()))
    # 分歧检测
    for s in usable:
        if abs(s.score - out.score) > 2.0 * max(out.sigma, 0.3):
            out.disagreement = True
            break
    return out


CFG_HURST = 500   # 兼容旧引用；实际窗口由 fuse_all 传入 config 值
