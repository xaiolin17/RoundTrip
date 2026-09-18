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
    """经典指标分数（MACD/RSI/均线/ATR），从 15m/1h 计算。"""
    macd_score: float = 0.0
    rsi_score: float = 0.0
    ma_score: float = 0.0
    atr: float | None = None
    realized_vol_daily: float | None = None


def compute_indicators(df: pd.DataFrame) -> IndicatorScores:
    out = IndicatorScores()
    close = df["close"]
    if len(close) < 60:
        return out
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    out.macd_score = float(np.clip((dif.iloc[-1] - dea.iloc[-1]) / max(close.iloc[-1] * 0.0005, 1e-9), -2, 2))
    # RSI14
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    r = rsi.iloc[-1]
    out.rsi_score = float(np.clip((50 - r) / 20, -2, 2))   # 超买回拉看空、超卖回抽看多
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    s = 0.0
    if close.iloc[-1] > ma20.iloc[-1]:
        s += 1
    else:
        s -= 1
    if ma20.iloc[-1] > ma60.iloc[-1]:
        s += 1
    else:
        s -= 1
    out.ma_score = s
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - close.shift()).abs(),
        (df["low"] - close.shift()).abs(),
    ], axis=1).max(axis=1)
    out.atr = float(tr.rolling(14).mean().iloc[-1])
    rets = close.pct_change().dropna()
    if len(rets) >= 100:
        out.realized_vol_daily = float(rets.tail(1440 if len(rets) >= 1440 else len(rets)).std() * np.sqrt(1440))
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

        # 1) 卡尔曼（1m 顺势，8h 前瞻 IC=+0.028；持续性加权 +0.043 更强）
        k = self.kalman.fit(frames["1m"]["close"].to_numpy(dtype=float))
        ev.kalman = k
        kalman_persist = float(np.clip(k.trend * min(k.slope_persist / 10.0, 1.5), -3.0, 3.0))
        sources.append(SourceView("kalman_persist", kalman_persist, max(k.sigma * 0.8, 0.2)))

        # 2) chanlun：15m 顺势 + 高周期反转修正（回放结论）
        cl15 = chanlun_results.get("15m")
        cl1h = chanlun_results.get("1h")
        if horizon == "8h":
            parts = []
            if cl15 and cl15.status == "ok":
                parts.append(0.6 * cl15.score)           # 顺势 +0.042
            if cl1h and cl1h.status == "ok":
                parts.append(-0.25 * cl1h.score)         # 1h 反转修正 -0.038
            cl_score = sum(parts)
        else:
            cl_scores = [r.score for r in chanlun_results.values() if r.status == "ok"]
            cl_score = float(np.mean(cl_scores)) if cl_scores else 0.0
        sources.append(SourceView("chanlun", cl_score, 0.5,
                                  status="ok" if cl15 and cl15.status == "ok" else "unavailable"))

        # 3) mobius SMC
        if mobius_result is not None and mobius_result.status != "unavailable":
            last = float(frames["15m"]["close"].iloc[-1])
            s = _mobius_score(mobius_result, last)
            sources.append(SourceView("openmobius_smc", s, 0.5,
                                      status=mobius_result.status))
        else:
            sources.append(SourceView("openmobius_smc", 0.0, 3.0, status="unavailable"))

        # 4) 经典指标（15m，8h 前瞻 IC=+0.078 最强单源）
        ind = compute_indicators(frames["15m"])
        ev.indicators = ind
        classic = 0.4 * ind.macd_score + 0.3 * ind.rsi_score + 0.3 * ind.ma_score
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
