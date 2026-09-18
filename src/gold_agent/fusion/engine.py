"""融合编排器：把 chanlun / mobius SMC / kalman / 指标分数汇成 FusionResult。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from gold_agent.common.config import CFG
from gold_agent.fusion.bayes import BayesianPool
from gold_agent.fusion.gaussian import FusionResult, SourceView, fuse
from gold_agent.fusion.kalman import KalmanTrend
from gold_agent.skills.chanlun_adapter import ChanlunResult
from gold_agent.skills.mobius_adapter import MobiusResult, _score_fn


def _mobius_score(res: MobiusResult, last_price: float) -> float:
    return _score_fn(res, last_price)


@dataclass
class IndicatorScores:
    """前瞻性指标（用户要求：替换滞后的 MACD/RSI，取有前瞻含义的量价结构）。

    - momentum_accel（动量加速度）：一阶动量（ROC5）的二阶差分——趋势「正在变快/变慢」。
      MACD 只能看到趋势已经发生，加速度能领先 MACD 一拍看到趋势衰竭/启动
    - tick_imbalance（tick 量不对称）：近 10 根上涨 bar 的 tick_volume 占比——主动买/卖
      力量对比（订单流不平衡 OFI 的 K 线近似，参考 Cont/Kukanov/Stoikov order flow
      imbalance 思想；MT5 无逐笔数据，tick_volume 是最近似代理）
    - vol_pressure（量价背离压力）：价升量缩=趋势衰竭（负），价涨量增=健康（正）
    - range_compression（波动收缩）：当前 bar 范围 / 近 14 根 ATR——收缩后常发生方向
      选择（波动聚集 volatility clustering 的前瞻信号）
    - atr / realized_vol_daily：保留（用于仓位与波动目标，非方向性）
    """
    momentum_accel: float = 0.0
    tick_imbalance: float = 0.0
    vol_pressure: float = 0.0
    range_compression: float = 0.0
    atr: float | None = None
    realized_vol_daily: float | None = None


def compute_indicators(df: pd.DataFrame) -> IndicatorScores:
    out = IndicatorScores()
    close = df["close"]
    if len(close) < 40:
        return out
    rets = close.pct_change()

    # --- 1) 动量加速度（ROC5 的一阶差分）---
    roc5 = close.pct_change(5)
    accel = roc5.diff()
    out.momentum_accel = float(np.clip(accel.iloc[-1] / max(rets.std(), 1e-9), -2, 2))

    # --- 2) tick 量不对称（近 10 根）---
    if "tick_volume" in df.columns:
        tv = df["tick_volume"].astype(float)
        up = (df["close"] > df["open"]).astype(float)
        w = tv.tail(10)
        u = float((up.tail(10) * w).sum())
        tot = float(w.sum())
        if tot > 0:
            out.tick_imbalance = float(np.clip((2 * u - tot) / tot, -1, 1))

    # --- 3) 量价背离压力（近 20 根价格/量的一阶关系）---
    if "tick_volume" in df.columns:
        tv = df["tick_volume"].astype(float)
        pr = close.tail(20).pct_change()
        vr = tv.tail(20).pct_change().replace([np.inf, -np.inf], np.nan)
        corr = pr.corr(vr)
        dp = float(pr.iloc[-1]) if len(pr) else 0.0
        dv = float(vr.iloc[-1]) if len(vr) and not np.isnan(vr.iloc[-1]) else 0.0
        # 价涨量缩（corr<0 或 dv<0）→ 衰竭压力；价涨量增 → 健康支撑
        div = (1 if dp > 0 else -1 if dp < 0 else 0) * (-dv if (not np.isnan(corr) and corr < 0) else dv)
        out.vol_pressure = float(np.clip(div, -1, 1))

    # --- 4) 波动收缩 + ATR ---
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - close.shift()).abs(),
        (df["low"] - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()
    out.atr = float(atr14.iloc[-1])
    rc = float(tr.iloc[-1] / max(out.atr, 1e-9))   # <1 收缩，>1 扩张
    out.range_compression = float(np.clip(1.0 - rc, -1, 1))

    # --- 日化波动率 ---
    r = rets.dropna()
    if len(r) >= 100:
        out.realized_vol_daily = float(r.tail(1440 if len(r) >= 1440 else len(r)).std() * np.sqrt(1440))
    return out


@dataclass
class FusedEvidence:
    result: FusionResult = field(default_factory=FusionResult)
    chanlun: dict[str, ChanlunResult] = field(default_factory=dict)
    mobius: MobiusResult | None = None
    indicators: IndicatorScores | None = None
    kalman: object | None = None
    computed_at: float = 0.0


class FusionEngine:
    def __init__(self) -> None:
        self.bayes = BayesianPool()
        self.kalman = KalmanTrend()

    def fuse_all(self, frames: dict[str, pd.DataFrame],
                 chanlun_results: dict[str, ChanlunResult],
                 mobius_result: MobiusResult | None,
                 record_feedback: dict[str, tuple[int, int]] | None = None,
                 news_score: float = 0.0,
                 horizon: str = "8h") -> FusedEvidence:
        """record_feedback: {source: (predicted_sign, actual_sign)} 用于在线校准。

        horizon: "8h"（长回放校准得出：8h 前瞻下各源 IC 最优且部分高周期
        结构呈反转特性，见 tests/test_fusion_replay.py 扫描结果）
        """
        ev = FusedEvidence(computed_at=time.time())
        ev.chanlun = chanlun_results
        ev.mobius = mobius_result
        sources: list[SourceView] = []

        # 1) 卡尔曼（1m 短期趋势；1m 为主战周期，8h 前瞻 IC=+0.028，持续性 +0.043）
        k = self.kalman.fit(frames["1m"]["close"].to_numpy(dtype=float))
        ev.kalman = k
        kalman_persist = float(np.clip(k.trend * min(k.slope_persist / 10.0, 1.5), -3.0, 3.0))
        sources.append(SourceView("kalman_persist", kalman_persist, max(k.sigma * 0.8, 0.2)))

        # 2) chanlun 多周期：短周期权重高（1m 为主战，15m 内为大头），1d 最小（用户要求）
        #    权重：1m×1.0  5m×0.9  15m×0.7  1h×0.3  4h×0.15  1d×0.05（1h+ 反转特性）
        _CL_W = {"1m": 1.00, "5m": 0.90, "15m": 0.70, "1h": -0.30, "4h": -0.15, "1d": -0.05}
        parts = []
        for tf, w in _CL_W.items():
            r = chanlun_results.get(tf)
            if r is not None and r.status == "ok":
                parts.append(w * r.score)
        cl_score = sum(parts) / (sum(abs(w) for w in _CL_W.values()) / 3.0)
        cl_score = float(np.clip(cl_score, -3.0, 3.0))
        any_ok = any(r is not None and r.status == "ok" for r in chanlun_results.values())
        sources.append(SourceView("chanlun", cl_score, 0.5,
                                  status="ok" if any_ok else "unavailable"))

        # 3) mobius SMC 多周期：1m/5m/15m 为主，1h 辅助（限速 10 req/min，缓存下共享）
        #    权重与 chanlun 一致的短周期优先思想
        _MB_W = {"1m": 1.00, "5m": 0.80, "15m": 0.60, "1h": -0.25}
        parts, statuses = [], []
        last_1m = float(frames["1m"]["close"].iloc[-1])
        last_15m = float(frames["15m"]["close"].iloc[-1])
        if isinstance(mobius_result, dict):
            for tf, w in _MB_W.items():
                r = mobius_result.get(tf)
                if r is not None and r.status != "unavailable":
                    px = last_1m if tf == "1m" else last_15m
                    parts.append(w * _mobius_score(r, px))
                    statuses.append(r.status)
        elif mobius_result is not None and mobius_result.status != "unavailable":
            parts.append(_MB_W["15m"] * _mobius_score(mobius_result, last_15m))
            statuses.append(mobius_result.status)
        mb_score = float(np.clip(sum(parts), -3.0, 3.0)) if parts else 0.0
        mb_status = "ok" if "ok" in statuses else ("stale" if "stale" in statuses else "unavailable")
        sources.append(SourceView("openmobius_smc", mb_score, 0.5, status=mb_status))

        # 4) 经典指标：1m 为主（15m IC=+0.078 已验证；1m 上更贴近入场节奏）
        ind_1m = compute_indicators(frames["1m"])
        ind_15m = compute_indicators(frames["15m"])
        ev.indicators = ind_15m     # ATR/波动率仍取 15m（更稳）

        def _lead_score(ind: IndicatorScores) -> float:
            """前瞻指标合成分：加速度 0.35 + tick 不对称 0.30 + 量价压力 0.20 + 收缩 0.15。

            方向约定：accel>0 加速上行、tick_imbalance>0 买盘占优、vol_pressure>0 健康上涨、
            range_compression>0 收缩蓄势（配合 accel/tick 同向才有意义，单独给弱分）。
            """
            return (0.35 * ind.momentum_accel + 0.30 * ind.tick_imbalance * 2.0
                    + 0.20 * ind.vol_pressure + 0.15 * ind.range_compression * np.sign(ind.momentum_accel + 0.01))

        classic = 0.5 * _lead_score(ind_1m) + 0.5 * _lead_score(ind_15m)
        sources.append(SourceView("classic_indicators", classic, 0.6))

        # 5) 新闻面
        if news_score != 0.0:
            sources.append(SourceView("news", float(np.clip(news_score, -2, 2)), 0.8))

        # 贝叶斯贡献
        contrib = {}
        for s in sources:
            contrib[s.name] = self.bayes.evidence(s.name, s.score, strength=min(abs(s.score) / 3.0, 1.0))
        if record_feedback:
            for src, (pred, actual) in record_feedback.items():
                self.bayes.record_outcome(src, pred, actual)
            self.bayes.save()

        hurst_window = CFG.fusion.hurst_window
        closes_1m = frames["1m"]["close"].to_numpy(dtype=float)
        global _HURST_OVERRIDE
        result = fuse(sources, contrib, closes_1m)
        ev.result = result
        return ev
