"""卡尔曼滤波：局部线性趋势模型（level+slope），docs/04 §1。"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from filterpy.kalman import KalmanFilter


@dataclass
class KalmanOutput:
    trend: float            # 标准化 slope ∈ [-3,3]
    slope_raw: float
    slope_persist: int      # slope 连续同号 bars 数
    sigma: float            # 后验不确定度（P[1,1] 开方，标准化）
    level: float


class KalmanTrend:
    """对 close 序列做匀速模型滤波；Δt=1（bar 序号）。"""

    def __init__(self, r_mult: float = 1.0) -> None:
        self.r_mult = r_mult

    def fit(self, closes: np.ndarray) -> KalmanOutput:
        if len(closes) < 30:
            return KalmanOutput(0.0, 0.0, 0, 3.0, float(closes[-1]) if len(closes) else 0.0)
        kf = KalmanFilter(dim_x=2, dim_z=1)
        kf.x = np.array([closes[0], 0.0])
        kf.F = np.array([[1.0, 1.0], [0.0, 1.0]])
        kf.H = np.array([[1.0, 0.0]])
        # 观测噪声: 滚动 ATR 比例
        diffs = np.diff(closes)
        atr_like = np.mean(np.abs(diffs[-50:])) if len(diffs) >= 50 else (np.std(diffs) or 1.0)
        kf.R[0, 0] = max((atr_like * self.r_mult) ** 2, 1e-6)
        # 过程噪声: 自适应（经验: slope 噪声 ~ R 的 1%）
        kf.Q = np.eye(2) * (kf.R[0, 0] * 0.01)
        kf.P = np.eye(2) * atr_like * 10
        slopes = []
        for z in closes:
            kf.predict()
            kf.update([z])
            slopes.append(float(kf.x[1]))
        slopes = np.array(slopes)
        # 标准化: slope / (ATR/8) 截断到 ±3
        scale = max(atr_like / 8.0, 1e-6)
        trend = float(np.clip(slopes[-1] / scale, -3.0, 3.0))
        # 持续性
        persist = 0
        for s in slopes[::-1]:
            if s * slopes[-1] > 0:
                persist += 1
            else:
                break
        sigma = float(np.sqrt(max(kf.P[1, 1], 1e-9)) / scale)
        return KalmanOutput(trend=trend, slope_raw=float(slopes[-1]),
                            slope_persist=int(min(persist, 999)), sigma=min(sigma, 3.0),
                            level=float(kf.x[0]))

    def fit_series(self, closes: np.ndarray) -> np.ndarray:
        """单遍滤波，返回**逐点**标准化 trend 序列（无前视，O(n)）。

        为什么需要它：`research/21_source_ir.py` 要为每个 bar 取一次源分。
        若逐点调用 `fit(closes[:i+1])`，总复杂度是 O(n²)（60000 根要跑几十分钟）。
        本方法一遍滤波即可得到每个时点的 trend —— 且**天然无前视**，
        因为 t 时刻的滤波状态只由 closes[:t+1] 决定。

        返回与 closes 等长的数组；预热期（<30 根）填 0。
        """
        n = len(closes)
        out = np.zeros(n, dtype=float)
        if n < 30:
            return out
        kf = KalmanFilter(dim_x=2, dim_z=1)
        kf.x = np.array([closes[0], 0.0])
        kf.F = np.array([[1.0, 1.0], [0.0, 1.0]])
        kf.H = np.array([[1.0, 0.0]])
        diffs = np.diff(closes)
        atr_like = np.mean(np.abs(diffs[:50])) if len(diffs) >= 50 else (np.std(diffs) or 1.0)
        kf.R[0, 0] = max((atr_like * self.r_mult) ** 2, 1e-6)
        kf.Q = np.eye(2) * (kf.R[0, 0] * 0.01)
        kf.P = np.eye(2) * atr_like * 10
        scale = max(atr_like / 8.0, 1e-6)
        # 滚动 ATR 尺度（用扩展窗口，无前视）
        for i in range(n):
            kf.predict()
            kf.update([closes[i]])
            if i >= 30:
                out[i] = float(np.clip(kf.x[1] / scale, -3.0, 3.0))
        return out
