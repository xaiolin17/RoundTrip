"""融合编排器：把 chanlun / mobius SMC / kalman / 指标分数汇成 FusionResult。

本模块承担 research/18_COMMERCIAL_PLAN.md 的三项 P0/P1 修正：

- **P0-1 源去均值**：每个源进融合前过 `SourceNormalizer`（滚动 z-score），
  消除结构性常数偏移。mobius 原始分 88% 为正、均值 +1.2604 是**偏置不是预测**。
- **P0-2 权重按实测 IR**：`weights.WeightTable` 从 `data/source_ir.json` 读取，
  未验证的源权重为 0。手填 sigma 不再决定影响力。
- **P1-3 融合分基线**：`RollingBaseline` 提供 S0，决策层用 `S - S0` 判阈值。

周期权重（P1-1）：决策周期迁到 1h 后，方向判据以 1h/4h 为主，
1m 降为执行择时（**不参与方向**，权重 0）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from gold_agent.common.config import CFG
from gold_agent.fusion.bayes import BayesianPool
from gold_agent.fusion.gaussian import FusionResult, SourceView, fuse
from gold_agent.fusion.kalman import KalmanTrend
from gold_agent.fusion.normalize import RollingBaseline, RollingPercentile, SourceNormalizer
from gold_agent.fusion.weights import WeightTable
from gold_agent.skills.chanlun_adapter import ChanlunResult
from gold_agent.skills.mobius_adapter import MobiusResult, _score_fn


def _mobius_score(res: MobiusResult, last_price: float) -> float:
    return _score_fn(res, last_price)


# ---------------------------------------------------------------------------
# 周期权重（P1-1：1h/4h 主导方向，1m 不参与方向）
# ---------------------------------------------------------------------------
#: chanlun 各周期权重。1m 权重 0 —— 1m 只用于执行择时，不产生方向。
CL_TF_WEIGHTS: dict[str, float] = {
    "1h": 1.00, "4h": 0.60, "15m": 0.40, "5m": 0.20, "1m": 0.00,
}
#: openmobius SMC 各周期权重（同上原则）
MB_TF_WEIGHTS: dict[str, float] = {
    "1h": 1.00, "4h": 0.50, "15m": 0.40, "5m": 0.20, "1m": 0.00,
}

#: 各周期一根 bar 等于多少分钟（预热时按等时长切窗口用）
_TF_MINUTES: dict[str, int] = {
    "1m": 1, "2m": 2, "5m": 5, "10m": 10, "15m": 15, "30m": 30,
    "1h": 60, "4h": 240, "8h": 480, "1d": 1440,
}

#: 各周期指标的**最小历史 bar 数**（预热切片不得低于此值）。
#: 低于这个数指标会返回常数/中性值 → 归一化器拿到零方差序列 → 预热失效。
#: - 15m：`_vol_percentile` 要 `len(df) >= 80` 且滚动波动率窗口 60，
#:        所以至少 80（取 90 留余量）。
#: - 1h/4h：`_raw_scores_at` 里的经典指标与 chanlun 结构需要一定历史。
#: - 1m：指标窗口最长约 30 根，取 60。
MIN_BARS: dict[str, int] = {
    "1m": 60, "2m": 60, "5m": 60, "10m": 60, "15m": 90, "30m": 90,
    "1h": 120, "4h": 120, "8h": 120, "1d": 120,
}


def _slice_frames_at(frames: dict[str, pd.DataFrame], end: int, total: int,
                     win_bars: int) -> dict[str, pd.DataFrame]:
    """取「时刻 `end` 为止」的多周期窗口（预热用）。**无前视**。

    `end` 是 1m 轴上的索引（0..total），各周期按**时间**换算：

    - ⚠️ 必须按时间对齐，不能按索引比例。
      各周期 bar 数相同（MT5 每周期都给 600 根）但**时长不同**：
      600 根 1m = 10 小时，600 根 15m = 150 小时。
      若用 `int(len(df)*end/total)` 做比例映射，15m 会 1:1 映射 →
      预热第 300 步取到的是 75 小时**之后**的 15m 数据（前视错位）。
    - ⚠️ 每步必须取**不同的**尾部窗口。
      若用 `df.iloc[-k:]`，每轮都取同样的最后 k 根 → 301 步算出 301 个
      **完全相同**的分数（实测 std=0.000），归一化器拿到常数序列 → 预热失效。

    返回：各周期的尾部 DataFrame（可能缺少样本不足的周期）。
    """
    lo = max(0, end - win_bars)
    span = end - lo
    if span < 60:
        return {}
    sub: dict[str, pd.DataFrame] = {}
    for tf, df in frames.items():
        ratio = max(1, _TF_MINUTES.get(tf, 1))
        # 该周期中「时间 ≤ end 对应时刻」的 bar 数
        cut = len(df) - (total - end) // ratio
        cut = max(2, min(len(df), cut))
        # 需要的 bar 数：覆盖窗口时长，且不低于指标的最小历史
        k = max(MIN_BARS.get(tf, 0), max(30, span // ratio))
        take = min(cut, k)
        if take >= 2:
            sub[tf] = df.iloc[cut - take:cut]
    return sub


@dataclass
class IndicatorScores:
    """前瞻性指标（替换滞后的 MACD/RSI，取有前瞻含义的量价结构）。

    - momentum_accel（动量加速度）：一阶动量（ROC5）的二阶差分——趋势「正在变快/变慢」。
    - tick_imbalance（tick 量不对称）：近 10 根上涨 bar 的 tick_volume 占比。
    - vol_pressure（量价背离压力）：价升量缩=趋势衰竭（负），价涨量增=健康（正）。
    - range_compression（波动收缩）：当前 bar 范围 / 近 14 根 ATR。
    - atr / realized_vol_daily：保留（用于仓位与波动目标，非方向性）。
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


def _lead_score(ind: IndicatorScores) -> float:
    """前瞻指标合成分：加速度 0.35 + tick 不对称 0.30 + 量价压力 0.20 + 收缩 0.15。

    方向约定：accel>0 加速上行、tick_imbalance>0 买盘占优、vol_pressure>0 健康上涨、
    range_compression>0 收缩蓄势（配合 accel/tick 同向才有意义，单独给弱分）。
    """
    return (0.35 * ind.momentum_accel + 0.30 * ind.tick_imbalance * 2.0
            + 0.20 * ind.vol_pressure
            + 0.15 * ind.range_compression * np.sign(ind.momentum_accel + 0.01))


def _rolling_realized_vol(close: pd.Series, win: int = 60) -> pd.Series:
    """滚动已实现波动率（收益率标准差），用于波动分位。"""
    rets = close.pct_change()
    return rets.rolling(win).std()


@dataclass
class FusedEvidence:
    result: FusionResult = field(default_factory=FusionResult)
    chanlun: dict[str, ChanlunResult] = field(default_factory=dict)
    mobius: MobiusResult | None = None
    indicators: IndicatorScores | None = None
    kalman: object | None = None
    computed_at: float = 0.0
    #: 各源原始分（去均值前）与归一化分，供审计与验收（P0-1）
    raw_scores: dict[str, float] = field(default_factory=dict)
    norm_scores: dict[str, float] = field(default_factory=dict)
    #: 权重表快照（哪些源被排除、为什么）
    weight_table: dict = field(default_factory=dict)
    #: 预热状态（未预热的源不给方向）
    warmed: dict[str, bool] = field(default_factory=dict)


class FusionEngine:
    def __init__(self, weight_table: WeightTable | None = None,
                 normalizer: SourceNormalizer | None = None) -> None:
        self.bayes = BayesianPool()
        self.kalman = KalmanTrend()
        # P0-2：权重来自实测 IR 文件；文件缺失 → 全 0（未验证不得参与方向决策）
        self.weights = weight_table or WeightTable.load()
        # P0-1：按源滚动去均值
        self.normalizer = normalizer or SourceNormalizer(
            win=CFG.fusion.norm_window, min_periods=CFG.fusion.norm_min_periods)
        self.vol_pct = RollingPercentile(
            win=CFG.fusion.vol_pct_window,
            min_periods=CFG.fusion.vol_pct_min_periods)
        self.baseline = RollingBaseline(
            win=CFG.fusion.baseline_window,
            min_periods=CFG.fusion.baseline_min_periods)

    # ---------- 权重快照 ----------
    def _weight_of(self, name: str) -> float:
        """返回该源的实测 IR² 权重。

        ⚠️ **必须返回 0.0 而不是 None**：`gaussian.fuse` 里 `weight is None`
        的语义是"没有权重表，退回逆方差"，而 P0-2 要的是"**未验证 → 权重 0**"。
        两者混淆会让未验证的源通过 `1/sigma²` 回退拿到权重 ——
        那就完全违背了 P0-2 的硬规则。
        """
        return float(self.weights.weight(name))

    def _raw_scores_at(self, frames: dict[str, pd.DataFrame],
                       chanlun_results: dict[str, ChanlunResult] | None,
                       mobius_result: MobiusResult | None):
        """算各源的**原始**分（未归一化）。fuse_all 与 prime_history 共用，
        保证预热与实盘走同一条评分路径。"""
        chanlun_results = chanlun_results or {}
        raws: dict[str, float] = {}

        # 1) 卡尔曼（趋势背景；实测唯一有 research 出处的源）
        k = self.kalman.fit(frames["1m"]["close"].to_numpy(dtype=float))
        raws["kalman_persist"] = float(
            np.clip(k.trend * min(k.slope_persist / 10.0, 1.5), -3.0, 3.0))

        # 2) chanlun 多周期
        parts, wsum = [], 0.0
        for tf, w in CL_TF_WEIGHTS.items():
            r = chanlun_results.get(tf)
            if w > 0 and r is not None and r.status == "ok":
                parts.append(w * r.score)
                wsum += abs(w)
        raws["chanlun"] = float(np.clip(sum(parts) / (wsum / 3.0), -3.0, 3.0)) if wsum > 0 else 0.0

        # 3) mobius SMC 多周期
        parts = []
        last_1m = float(frames["1m"]["close"].iloc[-1])
        last_15m = float(frames["15m"]["close"].iloc[-1])
        if isinstance(mobius_result, dict):
            for tf, w in MB_TF_WEIGHTS.items():
                r = mobius_result.get(tf)
                if w > 0 and r is not None and r.status != "unavailable":
                    parts.append(w * _mobius_score(r, last_1m if tf == "1m" else last_15m))
        elif mobius_result is not None and mobius_result.status != "unavailable":
            parts.append(MB_TF_WEIGHTS["15m"] * _mobius_score(mobius_result, last_15m))
        raws["openmobius_smc"] = float(np.clip(sum(parts), -3.0, 3.0)) if parts else 0.0

        # 4) 经典指标
        raws["classic_indicators"] = float(
            0.5 * _lead_score(compute_indicators(frames["1m"]))
            + 0.5 * _lead_score(compute_indicators(frames["15m"])))
        return raws, chanlun_results, mobius_result

    def _score_from_raw(self, raws: dict[str, float]) -> float:
        """把原始分合成标量 —— **仅供预热基线使用**。

        ⚠️ 单位必须与 `fuse_all` 喂给基线的量一致。
        `fuse_all` 里 `baseline.update(result.score)`，而 `result.score`
        是**归一化后**分数的加权平均（见 `gaussian.fuse`）。
        所以这里也必须先过 `normalizer` 再合成 —— 否则基线会落在
        完全不同的尺度上。

        实测过的 bug：预热时用**原始分**的加权平均（kalman 原始分均值
        约 +1.3），而运行时基线对齐的是**归一化分**（均值约 0）。
        结果 `score_baseline` 被拉到 −2.8 左右，`S_eff = S − S_baseline`
        恒为 +2.7~+5.8 → **每一轮都做多**（7/7 轮 S_eff > 0）。
        这是比"不开仓"更危险的失败：系统性单边押注。
        """
        num = 0.0
        den = 0.0
        for name, raw in raws.items():
            w = self._weight_of(name)
            if w > 0:
                num += w * self.normalizer.peek(name, raw)
                den += w
        return float(num / den) if den > 0 else 0.0

    def fuse_all(self, frames: dict[str, pd.DataFrame],
                 chanlun_results: dict[str, ChanlunResult],
                 mobius_result: MobiusResult | None,
                 record_feedback: dict[str, tuple[int, int]] | None = None,
                 news_score: float = 0.0,
                 horizon: str = "8h",
                 obs_id: int | None = None) -> FusedEvidence:
        """record_feedback: {source: (predicted_sign, actual_sign)} 用于在线校准。

        obs_id: 观测编号（实盘 = round_id，回放 = bar 序号）。
                同一 obs_id 重复调用 fuse_all 时归一化器幂等（不重复入缓冲）。
        """
        ev = FusedEvidence(computed_at=time.time())
        ev.chanlun = chanlun_results
        ev.mobius = mobius_result
        sources: list[SourceView] = []

        def _mk(name: str, raw: float, sigma: float, status: str = "ok") -> SourceView:
            """构造 SourceView：先去均值，再挂实测 IR 权重。"""
            raw = float(raw) if np.isfinite(raw) else 0.0
            z = self.normalizer.normalize(name, raw, obs_id=obs_id)
            ev.raw_scores[name] = raw
            ev.norm_scores[name] = z
            ev.warmed[name] = self.normalizer.warm(name)
            return SourceView(name, z, sigma, status=status,
                              weight=self._weight_of(name), raw_score=raw,
                              ir=self.weights.get(name).ir)

        # 1) 卡尔曼（1h 决策周期下作为趋势背景；实测唯一有效的源）
        k = self.kalman.fit(frames["1m"]["close"].to_numpy(dtype=float))
        ev.kalman = k
        kalman_persist = float(np.clip(k.trend * min(k.slope_persist / 10.0, 1.5), -3.0, 3.0))
        sources.append(_mk("kalman_persist", kalman_persist, max(k.sigma * 0.8, 0.2)))

        # 2) chanlun 多周期：1h/4h 主导方向，1m 不参与（P1-1）
        parts, wsum = [], 0.0
        for tf, w in CL_TF_WEIGHTS.items():
            r = chanlun_results.get(tf)
            if w > 0 and r is not None and r.status == "ok":
                parts.append(w * r.score)
                wsum += abs(w)
        cl_score = float(np.clip(sum(parts) / (wsum / 3.0), -3.0, 3.0)) if wsum > 0 else 0.0
        any_ok = any(r is not None and r.status == "ok" for r in chanlun_results.values())
        sources.append(_mk("chanlun", cl_score, 0.5,
                           status="ok" if any_ok else "unavailable"))

        # 3) mobius SMC 多周期：1h/4h 主导（P1-1）
        parts, statuses = [], []
        last_1m = float(frames["1m"]["close"].iloc[-1])
        last_15m = float(frames["15m"]["close"].iloc[-1])
        if isinstance(mobius_result, dict):
            for tf, w in MB_TF_WEIGHTS.items():
                r = mobius_result.get(tf)
                if w > 0 and r is not None and r.status != "unavailable":
                    px = last_1m if tf == "1m" else last_15m
                    parts.append(w * _mobius_score(r, px))
                    statuses.append(r.status)
        elif mobius_result is not None and mobius_result.status != "unavailable":
            parts.append(MB_TF_WEIGHTS["15m"] * _mobius_score(mobius_result, last_15m))
            statuses.append(mobius_result.status)
        mb_score = float(np.clip(sum(parts), -3.0, 3.0)) if parts else 0.0
        mb_status = "ok" if "ok" in statuses else ("stale" if "stale" in statuses else "unavailable")
        sources.append(_mk("openmobius_smc", mb_score, 0.5, status=mb_status))

        # 4) 经典指标：1h 为主（P1-1：1m 不参与方向）
        ind_1m = compute_indicators(frames["1m"])
        ind_15m = compute_indicators(frames["15m"])
        ev.indicators = ind_15m     # ATR/波动率仍取 15m（更稳）
        classic = 0.5 * _lead_score(ind_1m) + 0.5 * _lead_score(ind_15m)
        sources.append(_mk("classic_indicators", classic, 0.6))

        # 5) 新闻面（同样受"未验证 → 0 权重"约束；其风控用途在 decision 层独立生效）
        if news_score != 0.0:
            sources.append(_mk("news", float(np.clip(news_score, -2, 2)), 0.8))

        # 贝叶斯贡献
        contrib = {}
        for s in sources:
            contrib[s.name] = self.bayes.evidence(s.name, s.score,
                                                  strength=min(abs(s.score) / 3.0, 1.0))
        if record_feedback:
            for src, (pred, actual) in record_feedback.items():
                self.bayes.record_outcome(src, pred, actual)
            self.bayes.save()

        closes_1m = frames["1m"]["close"].to_numpy(dtype=float)
        result = fuse(sources, contrib, closes_1m,
                      hurst_window=CFG.fusion.hurst_window)

        # ---- P1-2 波动分位（唯一不依赖方向预测的杠杆）----
        vp = self._vol_percentile(frames, obs_id=obs_id)
        result.vol_percentile = vp

        # ---- P1-3 融合分滚动基线（阈值零点校正）----
        result.score_baseline = self.baseline.update(result.score, obs_id=obs_id)

        # ---- 动量-结构矛盾闸（复盘：结构多+动量空的入场全是亏损）----
        # 在**归一化后**的分数上判定，且仅当 kalman 源有权重时生效
        # （权重 0 = 未验证，不应以它的方向否决其他源）。
        if abs(result.score) >= CFG.decision.open_threshold and sources:
            kal = sources[0]
            kal_w = kal.weight if kal.weight is not None else 0.0
            if kal_w > 0 and kal.score * result.score < 0 and abs(kal.score) >= 2.0:
                result.score *= 0.55
                result.disagreement = True
                result.reasons = getattr(result, "reasons", None) or []
                result.reasons.append("momentum_struct_conflict")
        ev.result = result
        ev.weight_table = self.weights.describe(
            [s.name for s in sources])
        return ev

    # ---------- 波动分位 ----------
    def _realized_vol_at(self, frames: dict[str, pd.DataFrame]) -> float | None:
        """当前 15m 已实现波动率（**原始值**，未取分位）。数据不足返回 None。"""
        df = frames.get("15m")
        if df is None or len(df) < 80:
            return None
        rv = _rolling_realized_vol(df["close"], win=60).dropna()
        if len(rv) < 2:
            return None
        return float(rv.iloc[-1])

    def _vol_percentile(self, frames: dict[str, pd.DataFrame],
                        obs_id: int | None = None) -> float:
        """当前波动率在近 N 根中的滚动分位。

        取 15m 已实现波动率序列（比 1m 稳），用最后一根的值算分位。
        预热期返回 0.5（中性）→ 不误杀。
        """
        x = self._realized_vol_at(frames)
        if x is None:
            return 0.5
        return self.vol_pct.update(x, obs_id=obs_id)

    # ---------- 启动预热（1m 短线：不预热 = 前 4 小时瘫痪） ----------
    def prime_history(self, frames: dict[str, pd.DataFrame],
                      chanlun_results: dict[str, ChanlunResult] | None = None,
                      mobius_result: MobiusResult | None = None,
                      n_steps: int | None = None,
                      step_bars: int | None = None) -> dict[str, int]:
        """回放最近的历史 bar，预热归一化器/波动分位/基线。

        ⚠️ 为什么必须做：`norm_min_periods` 的单位是**决策轮数**。
        1m 周期下 240 轮 = 4 小时；不预热则启动后 4 小时内
        **所有源都返回 0.0** → 融合分恒 0 → 永不开仓（实盘已复现）。

        做法：把 `frames` 尾部按 step_bars 切片，逐片调用与实盘
        **完全相同**的评分路径（`_raw_scores_at`），把结果灌进
        `normalizer.prime` / `vol_pct` / `baseline`。

        无前视保证：第 k 片只使用 `frames[:k]`，与实盘当轮可见数据一致。
        """
        n_steps = int(n_steps if n_steps is not None else CFG.fusion.prime_steps)
        step_bars = int(step_bars if step_bars is not None else CFG.fusion.prime_step_bars)
        n_steps = max(n_steps, 0)
        if n_steps <= 0 or not frames:
            return {}
        base = frames.get("1m")
        if base is None or len(base) < 60:
            return {}
        need = self.normalizer.min_periods + 5
        n_steps = max(n_steps, need)

        # ⚠️ 用**尾部固定窗口**而不是从头累积切片。
        #    从头切片时每步都要在近全量历史上重算指标 → 300 步要 217s，
        #    启动太慢。尾部窗口与实盘每轮看到的 bar 数一致，每步成本恒定。
        #
        # ⚠️ 窗口必须**按可用数据自适应**：MT5 默认只给 600 根 1m bar，
        #    若把 win_bars 固定成 600，则 start = max(600, 600-300) = 600，
        #    循环只跑 1 次 → 预热静默失败（count=1 → 仍不 warm → 不开仓）。
        #    正确做法：留出 n_steps 步的空间，窗口取剩余部分。
        total = len(base)
        avail = max(total - 1, 1)
        # 每步前进 step_bars，需要 (n_steps-1)*step_bars 根 + 一个窗口
        want_win = max(600, int(CFG.mt5.bars_per_tf))
        win_bars = min(want_win, max(60, avail - (n_steps - 1) * step_bars))
        if win_bars < 60:
            # 数据太少：退化为"每步 1 根、窗口尽量大"
            win_bars = max(60, avail // 2)
            step_bars = 1
        start = max(win_bars, total - n_steps * step_bars)
        hist: dict[str, list[float]] = {}
        raw_seq: list[dict[str, float]] = []
        vols: list[float] = []
        for end in range(start, total + 1, step_bars):
            # ⚠️ 每步必须取**不同的**尾部窗口。
            #    `df.iloc[-k:]` 每轮都取同样的最后 k 根 → 301 步算出 301 个
            #    **完全相同**的分数（实测 std=0.000），归一化器拿到常数序列
            #    → z-score 恒为 0 或除零 → 预热形同虚设。
            #    正确做法：把窗口右端锚在 `end`（随步前进），
            #    并且只使用 `end` 之前的 bar（无前视）。
            sub = _slice_frames_at(frames, end, total, win_bars)
            if "1m" not in sub or len(sub["1m"]) < 30:
                continue
            try:
                raws, _, _ = self._raw_scores_at(sub, chanlun_results, mobius_result)
            except Exception:
                continue
            for k2, v in raws.items():
                hist.setdefault(k2, []).append(v)
            raw_seq.append(raws)
            # ⚠️ 收**原始波动率**，不是分位。
            #    `vol_pct.prime()` 需要的是观测值本身；若塞分位进去，
            #    缓冲里就是一堆 0.5，分位数永远算不对。
            try:
                rv = self._realized_vol_at(sub)
                if rv is not None:
                    vols.append(rv)
            except Exception:
                continue

        # ⚠️ 零方差序列不得灌入归一化器。
        #    若某源在预热期恒为常数（如 chanlun 无信号时恒 0），
        #    灌进去会让该源缓冲 std=0 → 运行时 z-score 永远 0/除零保护，
        #    等于把该源**永久静音**，比不预热更糟。
        #    实测：chanlun 预热 301 个全 0 → 唯一值 1 个。
        #    正确处理：丢弃常数序列，让该源在运行时按正常路径累积。
        dropped: list[str] = []
        clean: dict[str, list[float]] = {}
        for name, vals in hist.items():
            if len(vals) >= 2 and float(np.std(vals)) > 1e-9:
                clean[name] = vals
            else:
                dropped.append(name)
        if dropped:
            from gold_agent.common.logging_util import log_info as _li
            _li(f"fusion prime: 丢弃零方差源 {dropped}（不灌入归一化器）")

        # ⚠️ 顺序很重要：**先**灌归一化器，**再**用 peek 把历史原始分
        #    转成与运行时同尺度的分数喂给基线。
        #    若反过来（先用原始分算基线），基线会落在完全不同的尺度上：
        #    实测把 score_baseline 拉到 −2.8，而运行时 S≈0 →
        #    S_eff = S − S_baseline 恒为 +2.7~+5.8 → 每轮都做多。
        primed = self.normalizer.prime_from(clean)
        scores: list[float] = []
        for raws in raw_seq:
            try:
                scores.append(float(self._score_from_raw(raws)))
            except Exception:
                continue
        # vol_pct 同理：常数序列（窗口太短时恒 0.5）不得灌入
        if vols and float(np.std(vols)) > 1e-9:
            self.vol_pct.prime(vols)
        if scores and float(np.std(scores)) > 1e-9:
            self.baseline.prime(scores)
        from gold_agent.common.logging_util import log_info
        log_info(f"fusion prime: {primed} "
                 f"vol_pct={self.vol_pct.count()} baseline={self.baseline.count()} "
                 f"baseline_value={self.baseline.value:+.4f}")
        return primed

    # ---------- 持久化（实盘重启保留预热） ----------
    def state_path(self, name: str):
        return CFG.state_path.parent / name

    def save_state(self) -> None:
        try:
            self.normalizer.save(self.state_path("source_normalizer.json"))
            self.vol_pct.save(self.state_path("vol_percentile.json"))
            self.baseline.save(self.state_path("score_baseline.json"))
        except Exception as e:      # 持久化失败不应中断交易循环
            from gold_agent.common.logging_util import log_warn
            log_warn(f"fusion state save failed: {e}")

    def load_state(self) -> None:
        try:
            self.normalizer = SourceNormalizer.load(self.state_path("source_normalizer.json"))
            self.vol_pct = RollingPercentile.load(self.state_path("vol_percentile.json"))
            self.baseline = RollingBaseline.load(self.state_path("score_baseline.json"))
        except Exception as e:
            from gold_agent.common.logging_util import log_warn
            log_warn(f"fusion state load failed: {e}")
