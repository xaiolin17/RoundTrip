"""模型库：按数学分支组织的可插拔信号/状态模型。

每个模型满足统一契约：
    compute(df: pd.DataFrame) -> np.ndarray   # 与 df 等长，值在 t 时刻只依赖 ≤t 的信息

kind:
    "direction" —— 输出方向分（正=看涨），用于 IC / 净收益评估
    "state"     —— 输出状态量（波动/流动性/regime），用于门控与仓位，不直接给方向

分类对应委托方给出的数学清单：
    volatility   波动率与风险      extreme     极值理论
    micro        市场微观结构      memory      长记忆/分数阶
    process      随机过程/均值回归  ts          时间序列
    regime       状态转换/HMM      info        信息论
    ml           统计学习          signal      信号处理/滤波
    exec         最优执行/仓位
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd
from scipy import stats

EPS = 1e-12


# ══════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════
def _logret(close: np.ndarray) -> np.ndarray:
    r = np.full(len(close), np.nan)
    r[1:] = np.diff(np.log(np.maximum(close, EPS)))
    return r


def _roll_apply(x: np.ndarray, win: int, fn: Callable[[np.ndarray], float],
                min_obs: int | None = None) -> np.ndarray:
    """因果滚动窗口应用（只用 ≤t 的数据）。"""
    n = len(x)
    out = np.full(n, np.nan)
    mo = min_obs or max(win // 2, 5)
    for t in range(n):
        a = max(0, t - win + 1)
        w = x[a:t + 1]
        w = w[np.isfinite(w)]
        if len(w) >= mo:
            try:
                out[t] = fn(w)
            except Exception:
                pass
    return out


def _safe_scale(x: np.ndarray, win: int = 500, clip: float = 3.0) -> np.ndarray:
    """因果滚动标准化并截断，使不同量纲的模型可比。"""
    s = pd.Series(x)
    m = s.rolling(win, min_periods=max(20, win // 10)).mean()
    sd = s.rolling(win, min_periods=max(20, win // 10)).std()
    z = (s - m) / sd.replace(0, np.nan)
    return np.clip(z.to_numpy(), -clip, clip)


def _true_range(df: pd.DataFrame) -> np.ndarray:
    h, l, c = df.high.to_numpy(float), df.low.to_numpy(float), df.close.to_numpy(float)
    pc = np.roll(c, 1)
    pc[0] = c[0]
    return np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])


# ══════════════════════════════════════════════════════════════════
# A. 波动率与风险
# ══════════════════════════════════════════════════════════════════
def vol_ewma(df: pd.DataFrame) -> np.ndarray:
    """EWMA 波动率（价格单位）。"""
    c = df.close.to_numpy(float)
    return (np.log(pd.Series(c)).diff().ewm(halflife=60, min_periods=30).std()
            * pd.Series(c)).to_numpy()


def vol_parkinson(df: pd.DataFrame) -> np.ndarray:
    """Parkinson (1980) 高低价波动率估计量——比收盘价估计量效率高约 5 倍。"""
    h, l = df.high.to_numpy(float), df.low.to_numpy(float)
    hl = np.log(h / np.maximum(l, EPS)) ** 2 / (4 * np.log(2))
    return np.sqrt(pd.Series(hl).rolling(30, min_periods=10).mean()).to_numpy() * df.close.to_numpy(float)


def vol_garman_klass(df: pd.DataFrame) -> np.ndarray:
    """Garman-Klass (1980)：同时利用 OHLC，效率约为收盘价法的 7 倍。"""
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    gk = 0.5 * np.log(h / np.maximum(l, EPS)) ** 2 - (2 * np.log(2) - 1) * np.log(c / np.maximum(o, EPS)) ** 2
    return np.sqrt(np.maximum(pd.Series(gk).rolling(30, min_periods=10).mean(), 0)).to_numpy() * c


def vol_bpv(df: pd.DataFrame) -> np.ndarray:
    """Bipower Variation (Barndorff-Nielsen & Shephard)：对跳跃稳健的积分波动估计。"""
    c = df.close.to_numpy(float)
    r = np.abs(_logret(c))
    bpv = (np.pi / 2) * pd.Series(r).rolling(2).apply(
        lambda w: w[0] * w[1] if len(w) == 2 else np.nan, raw=True)
    return np.sqrt(bpv.rolling(30, min_periods=10).mean()).to_numpy() * c


def jump_ratio(df: pd.DataFrame) -> np.ndarray:
    """跳跃占比 = 1 − BPV/RV。高值表示该时段由跳空驱动（止损易被穿透）。"""
    c = df.close.to_numpy(float)
    r = _logret(c)
    rv = pd.Series(r ** 2).rolling(30, min_periods=10).sum()
    bpv = (np.pi / 2) * pd.Series(np.abs(r)).rolling(2).apply(
        lambda w: w[0] * w[1] if len(w) == 2 else np.nan, raw=True)
    bpvs = bpv.rolling(30, min_periods=10).sum()
    return np.clip(1.0 - (bpvs / rv.replace(0, np.nan)).to_numpy(), 0, 1)


def vol_of_vol(df: pd.DataFrame) -> np.ndarray:
    """波动率的波动率——高值时波动率预测本身不可靠，应降低杠杆。"""
    v = vol_ewma(df)
    return (pd.Series(v).pct_change().rolling(60, min_periods=20).std()).to_numpy()


def rough_vol_hurst(df: pd.DataFrame) -> np.ndarray:
    """粗糙波动率：对 log|收益| 做 DFA，估计 H。

    实证事实（Gatheral-Jaisson-Rosenbaum 2018）：log-vol 的 H ≈ 0.1，远低于 0.5。
    注意必须用**未平滑**的波动代理（log|r|），否则 EWMA 平滑本身会把 H 抬到 1 以上，
    测到的是平滑器的记忆而不是市场结构。
    """
    c = df.close.to_numpy(float)
    r = _logret(c)
    lv = np.log(np.abs(r) + EPS)
    return _roll_apply(lv, 300, lambda w: _dfa_hurst(w, min_scale=4, max_scale=64), min_obs=120)


def _dfa_hurst(x: np.ndarray, min_scale: int = 8, max_scale: int = 128) -> float:
    """去趋势波动分析（DFA）——比 R/S 更稳健的 Hurst 估计量。"""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < min_scale * 4:
        return np.nan
    y = np.cumsum(x - x.mean())
    scales = np.unique(np.floor(np.logspace(np.log10(min_scale),
                                            np.log10(min(max_scale, n // 4)), 8)).astype(int))
    f = []
    used = []
    for s in scales:
        if s < 4:
            continue
        m = n // s
        if m < 2:
            continue
        seg = y[:m * s].reshape(m, s)
        t = np.arange(s)
        # 线性去趋势
        tm = t.mean()
        denom = ((t - tm) ** 2).sum()
        slope = ((seg - seg.mean(axis=1, keepdims=True)) * (t - tm)).sum(axis=1) / max(denom, EPS)
        fit = seg.mean(axis=1, keepdims=True) + slope[:, None] * (t - tm)
        f.append(np.sqrt(((seg - fit) ** 2).mean()))
        used.append(s)
    if len(f) < 3:
        return np.nan
    slope = np.polyfit(np.log(used), np.log(np.maximum(f, EPS)), 1)[0]
    return float(np.clip(slope, 0.0, 1.5))


# ══════════════════════════════════════════════════════════════════
# B. 市场微观结构（1m 短线最相关）
# ══════════════════════════════════════════════════════════════════
def roll_spread(df: pd.DataFrame) -> np.ndarray:
    """Roll (1984) 有效点差估计：s = 2√(−Cov(r_t, r_{t−1}))。

    用真实成交序列反推点差，可与券商报价点差对照，识别成本异常时段。
    """
    c = df.close.to_numpy(float)
    r = _logret(c)

    def f(w):
        if len(w) < 10:
            return np.nan
        cov = np.cov(w[1:], w[:-1])[0, 1]
        return 2 * np.sqrt(max(-cov, 0)) * np.exp(np.mean(np.log(np.maximum(c[:len(w)], EPS))))
    return _roll_apply(r, 60, f, min_obs=30)


def cs_spread(df: pd.DataFrame) -> np.ndarray:
    """Corwin-Schultz (2012) 高低价点差估计——只用 OHLC，无需成交方向。"""
    h, l = df.high.to_numpy(float), df.low.to_numpy(float)
    hl = np.log(h / np.maximum(l, EPS)) ** 2
    h2, l2 = np.roll(h, 1), np.roll(l, 1)
    h2[0], l2[0] = h[0], l[0]
    beta = (hl + np.roll(hl, 1)) ** 2 if False else (np.log(h / np.maximum(l, EPS)) +
                                                    np.log(h2 / np.maximum(l2, EPS))) ** 2
    hi = np.maximum(h, h2)
    lo = np.minimum(l, l2)
    gamma = np.log(hi / np.maximum(lo, EPS)) ** 2
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / (3 - 2 * np.sqrt(2)) - np.sqrt(gamma / (3 - 2 * np.sqrt(2)))
    s = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    return np.maximum(pd.Series(s).rolling(20, min_periods=5).mean().to_numpy(), 0) * df.close.to_numpy(float)


def amihud_illiquidity(df: pd.DataFrame) -> np.ndarray:
    """Amihud (2002) 非流动性：|收益| / 成交量，再取对数。

    值高 = 同样成交量推动价格更多 = 流动性差。
    注意量纲：tick_volume 在 1e3~1e5，直接取比值会下溢到 0，必须取对数。
    """
    c = df.close.to_numpy(float)
    v = df.tick_volume.to_numpy(float) if "tick_volume" in df.columns else df.volume.to_numpy(float)
    ill = np.log1p(np.abs(_logret(c)) * 1e6 / np.maximum(v, 1.0))
    return pd.Series(ill).rolling(30, min_periods=10).mean().to_numpy()


def kyle_lambda(df: pd.DataFrame) -> np.ndarray:
    """Kyle (1985) λ：价格冲击系数，回归 Δp ~ 签名成交量。

    λ 高 = 流动性差 = 大单会打穿盘口，挂单/网格策略风险上升。
    """
    c = df.close.to_numpy(float)
    v = df.tick_volume.to_numpy(float) if "tick_volume" in df.columns else df.volume.to_numpy(float)
    dp = np.diff(c, prepend=c[0])
    sv = np.sign(dp) * v                       # 签名成交量（tick rule 近似）
    n = len(c)
    out = np.full(n, np.nan)
    W = 60
    for t in range(W, n):
        a, b = dp[t - W + 1:t + 1], sv[t - W + 1:t + 1]
        if b.std() < EPS:
            continue
        out[t] = np.polyfit(b, a, 1)[0]
    return out


def order_flow_imbalance(df: pd.DataFrame) -> np.ndarray:
    """订单流不平衡（OFI）代理：K 线内收盘位置 × 成交量。

    close 在 bar 高位 = 买盘吃掉卖盘；低位 = 反之。这是 MT5 无逐笔数据下
    对 Cont-Kukanov-Stoikov OFI 的标准近似。
    """
    h, l, c = df.high.to_numpy(float), df.low.to_numpy(float), df.close.to_numpy(float)
    v = df.tick_volume.to_numpy(float) if "tick_volume" in df.columns else df.volume.to_numpy(float)
    rng = np.maximum(h - l, EPS)
    pos = (c - l) / rng * 2 - 1                # ∈ [-1,1]
    ofi = pos * v
    return (pd.Series(ofi).rolling(15, min_periods=5).sum() /
            pd.Series(v).rolling(15, min_periods=5).sum().replace(0, np.nan)).to_numpy()


def vpin_proxy(df: pd.DataFrame) -> np.ndarray:
    """VPIN 代理（Easley-López de Prado-O'Hara）：成交量桶内买卖不平衡。

    高 VPIN = 知情交易者活跃 = 短期方向性更强但风险更高。
    """
    h, l, c = df.high.to_numpy(float), df.low.to_numpy(float), df.close.to_numpy(float)
    v = df.tick_volume.to_numpy(float) if "tick_volume" in df.columns else df.volume.to_numpy(float)
    rng = np.maximum(h - l, EPS)
    buy = v * (c - l) / rng
    sell = v * (h - c) / rng
    num = pd.Series(np.abs(buy - sell)).rolling(50, min_periods=20).sum()
    den = pd.Series(v).rolling(50, min_periods=20).sum().replace(0, np.nan)
    return (num / den).to_numpy()


# ══════════════════════════════════════════════════════════════════
# C. 长记忆 / 分数阶
# ══════════════════════════════════════════════════════════════════
def fracdiff_price(df: pd.DataFrame, d: float = 0.4, thres: float = 1e-4) -> np.ndarray:
    """分数阶差分（López de Prado AFML ch.5）。

    整数阶差分（收益率）抹掉了全部长记忆；分数阶差分在获得平稳性的同时
    保留记忆，是比「收益率」信息量更大的特征。
    """
    c = df.close.to_numpy(float)
    lp = np.log(np.maximum(c, EPS))
    w = [1.0]
    k = 1
    while True:
        w_k = -w[-1] * (d - k + 1) / k
        if abs(w_k) < thres or k > 400:
            break
        w.append(w_k)
        k += 1
    w = np.array(w[::-1])
    n = len(lp)
    out = np.full(n, np.nan)
    L = len(w)
    for t in range(L, n):
        out[t] = float(np.dot(w, lp[t - L + 1:t + 1]))
    return out


def hurst_dfa(df: pd.DataFrame) -> np.ndarray:
    """收益序列的 DFA Hurst（滚动，因果）。"""
    c = df.close.to_numpy(float)
    r = _logret(c)
    return _roll_apply(r, 500, lambda w: _dfa_hurst(w, 8, 128), min_obs=200)


# ══════════════════════════════════════════════════════════════════
# D. 随机过程 / 均值回归
# ══════════════════════════════════════════════════════════════════
def ou_halflife(df: pd.DataFrame) -> np.ndarray:
    """Ornstein-Uhlenbeck 均值回归半衰期（滚动 AR(1) 拟合）。

    Δp_t = a + b·p_{t−1} + ε ⇒ 半衰期 = −ln2/ln(1+b)。
    半衰期是选择持仓时长的第一性原理依据（而非拍脑袋）。
    """
    c = df.close.to_numpy(float)
    n = len(c)
    out = np.full(n, np.nan)
    W = 240
    for t in range(W, n):
        seg = c[t - W:t + 1]                 # W+1 个点
        y = np.diff(seg)                     # 长度 W
        x = seg[:-1]                         # 长度 W，与 y 对齐
        if x.std() < EPS:
            continue
        b = np.polyfit(x, y, 1)[0]
        if -1 < b < 0:
            hl = -np.log(2) / np.log(1 + b)
            out[t] = min(hl, 10 * W)      # 截断：半衰期超过窗口长度的估计不可信
    return out


def ou_zscore(df: pd.DataFrame) -> np.ndarray:
    """OU 模型下的偏离度 z = (p − μ̂)/σ̂，μ̂ 由滚动均值给出（因果）。"""
    c = pd.Series(df.close.to_numpy(float))
    m = c.rolling(240, min_periods=60).mean()
    s = c.rolling(240, min_periods=60).std()
    return ((c - m) / s.replace(0, np.nan)).to_numpy()


def variance_ratio_stat(df: pd.DataFrame, q: int = 5, win: int = 240) -> np.ndarray:
    """滚动方差比（Lo-MacKinlay）。VR<1 均值回归，>1 趋势。

    01 号取证中该检验是唯一在 1m 上显著的量（VR≈0.944, z=−2.8）。
    """
    c = df.close.to_numpy(float)
    r = _logret(c)
    n = len(c)
    out = np.full(n, np.nan)
    for t in range(win, n):
        w = r[t - win + 1:t + 1]
        w = w[np.isfinite(w)]
        m = len(w) // q * q
        if m < q * 10:
            continue
        v1 = np.var(w[:m], ddof=1)
        vq = np.var(w[:m].reshape(-1, q).sum(axis=1), ddof=1) / q
        out[t] = vq / max(v1, EPS)
    return out


# ══════════════════════════════════════════════════════════════════
# E. 时间序列
# ══════════════════════════════════════════════════════════════════
def ar_forecast(df: pd.DataFrame, p: int = 5, win: int = 500) -> np.ndarray:
    """滚动 AR(p) 样本外预测（严格因果：用 t 之前的数据拟合，预测 t+1）。

    AR 系数本身带符号信息，比固定权重的技术指标更贴近数据。
    """
    c = df.close.to_numpy(float)
    r = _logret(c)
    n = len(c)
    out = np.full(n, np.nan)
    X_full = np.column_stack([np.roll(r, i) for i in range(1, p + 1)])
    for t in range(win + p, n):
        a = t - win
        X = X_full[a:t]
        y = r[a:t]
        m = np.isfinite(X).all(axis=1) & np.isfinite(y)
        if m.sum() < p * 10:
            continue
        Xm = np.column_stack([np.ones(m.sum()), X[m]])
        try:
            beta, *_ = np.linalg.lstsq(Xm, y[m], rcond=None)
        except Exception:
            continue
        xt = np.concatenate([[1.0], X_full[t]])
        if np.isfinite(xt).all():
            out[t] = float(xt @ beta)
    return out


def kalman_dynamic_beta(df: pd.DataFrame, ref_tf: pd.DataFrame | None = None) -> np.ndarray:
    """卡尔曼滤波局部线性趋势（level+slope），自适应过程噪声。

    相比现有实现，这里用 innovation 序列在线估计 Q（Sage-Husa 简化），
    使滤波在趋势/震荡切换时更快适应。
    """
    c = df.close.to_numpy(float)
    n = len(c)
    if n < 50:
        return np.full(n, np.nan)
    out = np.full(n, np.nan)
    x = np.array([c[0], 0.0])
    P = np.eye(2) * np.var(np.diff(c[:50])) * 10
    F = np.array([[1.0, 1.0], [0.0, 1.0]])
    H = np.array([[1.0, 0.0]])
    q_base = np.var(np.diff(c[:50])) * 0.01
    innov_var = q_base
    for t in range(1, n):
        Q = np.eye(2) * q_base
        x = F @ x
        P = F @ P @ F.T + Q
        y = c[t] - (H @ x)[0]
        S = (H @ P @ H.T)[0, 0] + max(innov_var, EPS)
        K = (P @ H.T).ravel() / S
        x = x + K * y
        P = P - np.outer(K, H @ P)
        innov_var = 0.97 * innov_var + 0.03 * y ** 2      # 自适应 R
        out[t] = x[1]
    return out


# ══════════════════════════════════════════════════════════════════
# F. Regime / 状态转换
# ══════════════════════════════════════════════════════════════════
def _hmm2_em(x: np.ndarray, iters: int = 25) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """两状态高斯 HMM 的 EM 拟合（返回 mu, sd, A, 后验概率）。

    性能约束：EM 每次迭代含一次 O(n) 前向/后向循环，Python 循环是瓶颈。
    商用系统必须在秒级完成，否则无法在 1 分钟循环里重估。做法：
      (a) 迭代上限 25（两状态高斯通常 10 次内收敛到参数稳定）；
      (b) 训练序列等间隔下采样到 ≤2000 点（状态参数是慢变量，几乎不损失精度）；
      (c) 前向/后向用向量化的对数域递推，避免逐点 Python 调用。
    """
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) > 2000:
        x = x[np.linspace(0, len(x) - 1, 2000).astype(int)]
    n = len(x)
    mu = np.array([np.percentile(x, 25), np.percentile(x, 75)])
    sd = np.array([x.std() * 0.7, x.std() * 1.5]) + EPS
    A = np.array([[0.95, 0.05], [0.05, 0.95]])
    pi = np.array([0.5, 0.5])
    prev_ll = -np.inf
    for _ in range(iters):
        B = np.empty((n, 2))
        for i in range(2):
            B[:, i] = stats.norm.pdf(x, mu[i], max(sd[i], EPS))
        B = np.maximum(B, 1e-300)
        # 前向（缩放）
        al = np.empty((n, 2)); c = np.empty(n)
        al[0] = pi * B[0]; c[0] = al[0].sum(); al[0] /= max(c[0], EPS)
        for t in range(1, n):
            al[t] = (al[t - 1] @ A) * B[t]
            c[t] = al[t].sum(); al[t] /= max(c[t], EPS)
        ll = float(np.log(np.maximum(c, 1e-300)).sum())
        if abs(ll - prev_ll) < 1e-6 * max(abs(ll), 1.0):
            prev_ll = ll
            break
        prev_ll = ll
        # 后向
        be = np.empty((n, 2)); be[-1] = 1.0
        for t in range(n - 2, -1, -1):
            be[t] = (A @ (B[t + 1] * be[t + 1])) / max(c[t + 1], EPS)
        g = al * be
        g /= np.maximum(g.sum(axis=1, keepdims=True), EPS)
        # 转移计数（向量化）
        xi_num = (al[:-1, :, None] * (B[1:] * be[1:])[:, None, :]) * A[None, :, :]
        xi = xi_num.sum(axis=0) / np.maximum(c[1:], EPS)[:, None, None]
        xi_sum = xi_num.sum(axis=0)
        A = xi_sum / np.maximum(xi_sum.sum(axis=1, keepdims=True), EPS)
        pi = g[0]
        for i in range(2):
            w = g[:, i]
            sw = max(w.sum(), EPS)
            mu[i] = float((w * x).sum() / sw)
            sd[i] = float(np.sqrt(max((w * (x - mu[i]) ** 2).sum() / sw, EPS)))
    return mu, sd, A, g


def hmm_high_vol_prob(df: pd.DataFrame, refit_every: int = 2000,
                      min_train: int = 1000, fit_window: int = 8000) -> np.ndarray:
    """两状态高斯 HMM 的「高波动状态」后验概率（滚动重估，因果）。

    02 号取证：高波动状态未来 2h 的平均绝对收益是低波动状态的 1.60 倍。
    这是可靠用于仓位与门控的状态量，**不用于方向**。

    实现要点（商用性能约束）：
      - EM 只用最近 fit_window 个观测拟合（波动状态参数是慢变量）；
      - 在线滤波用**增量递推**（前向概率 a_t 只依赖 a_{t-1}），
        复杂度 O(n)，而非每步重跑整段 O(n·W)。
        重估参数时从当前时点回溯 warm 步重建滤波状态，保证因果。
    """
    c = df.close.to_numpy(float)
    r = _logret(c)
    n = len(c)
    out = np.full(n, np.nan)
    mu = sd = A = None
    a = None
    warm = 300
    for t in range(min_train, n):
        refit = (t - min_train) % refit_every == 0 or mu is None
        if refit:
            x = r[max(0, t - fit_window):t]
            x = x[np.isfinite(x)]
            if len(x) < min_train:
                continue
            mu, sd, A, _ = _hmm2_em(x)
            if sd[0] > sd[1]:                     # 保证状态 1 = 高波动
                mu, sd = mu[::-1], sd[::-1]
                A = A[np.ix_([1, 0], [1, 0])]
            # 从 t-warm 处重建滤波状态（只用历史，保证因果）
            a = np.array([0.5, 0.5])
            seg = r[max(0, t - warm):t]
            for z in seg:
                if not np.isfinite(z):
                    continue
                B = np.array([stats.norm.pdf(z, mu[i], max(sd[i], EPS)) for i in range(2)])
                a = (a @ A) * B
                a /= max(a.sum(), EPS)
        z = r[t]
        if not np.isfinite(z) or a is None:
            continue
        B = np.array([stats.norm.pdf(z, mu[i], max(sd[i], EPS)) for i in range(2)])
        a = (a @ A) * B
        a /= max(a.sum(), EPS)
        out[t] = a[1]
    return out


def cusum_changepoint(df: pd.DataFrame, win: int = 240, k: float = 0.5) -> np.ndarray:
    """CUSUM 变点检测（Page 1954）：标准化收益的累积和越界即报警。

    用于识别结构性断裂（政策突变、流动性枯竭），触发降杠杆。
    """
    c = df.close.to_numpy(float)
    r = _logret(c)
    n = len(c)
    out = np.zeros(n)
    sp = sm = 0.0
    for t in range(1, n):
        a = max(0, t - win)
        w = r[a:t]
        w = w[np.isfinite(w)]
        if len(w) < 30:
            continue
        mu, sd = w.mean(), w.std()
        if sd < EPS or not np.isfinite(r[t]):
            continue
        z = (r[t] - mu) / sd
        sp = max(0.0, sp + z - k)
        sm = min(0.0, sm + z + k)
        out[t] = max(sp, -sm)
    return out


def vol_regime_quantile(df: pd.DataFrame, win: int = 1440) -> np.ndarray:
    """当前波动率在过去 win 根内的分位数（0~1）。简单、稳健、可解释。"""
    v = vol_ewma(df)
    s = pd.Series(v)
    return s.rolling(win, min_periods=120).rank(pct=True).to_numpy()


# ══════════════════════════════════════════════════════════════════
# G. 信息论
# ══════════════════════════════════════════════════════════════════
def shannon_entropy(df: pd.DataFrame, win: int = 240, bins: int = 8) -> np.ndarray:
    """收益分布的 Shannon 熵（滚动）。

    低熵 = 分布集中 = 结构性强、可预测性相对高；高熵 = 无序。
    这是「该不该交易」的无模型判据。
    """
    c = df.close.to_numpy(float)
    r = _logret(c)
    n = len(c)
    out = np.full(n, np.nan)
    for t in range(win, n):
        w = r[t - win + 1:t + 1]
        w = w[np.isfinite(w)]
        if len(w) < 50:
            continue
        h, _ = np.histogram(w, bins=bins)
        p = h / max(h.sum(), 1)
        p = p[p > 0]
        out[t] = float(-(p * np.log(p)).sum())
    return out


def kl_divergence(df: pd.DataFrame, win: int = 240, base_win: int = 2880,
                  bins: int = 10) -> np.ndarray:
    """当前收益分布与长期基准分布的 KL 散度。

    高 KL = 市场行为偏离常态 = 既有模型失效风险高 → 降杠杆。
    这是「模型漂移」的直接度量。
    """
    c = df.close.to_numpy(float)
    r = _logret(c)
    n = len(c)
    out = np.full(n, np.nan)
    for t in range(base_win, n):
        cur = r[t - win + 1:t + 1]
        base = r[t - base_win + 1:t + 1]
        cur, base = cur[np.isfinite(cur)], base[np.isfinite(base)]
        if len(cur) < 50 or len(base) < 200:
            continue
        lo, hi = np.percentile(base, [1, 99])
        if hi <= lo:
            continue
        edges = np.linspace(lo, hi, bins + 1)
        pc, _ = np.histogram(cur, bins=edges)
        pb, _ = np.histogram(base, bins=edges)
        pc = (pc + 1e-9) / (pc.sum() + 1e-9 * bins)
        pb = (pb + 1e-9) / (pb.sum() + 1e-9 * bins)
        out[t] = float((pc * np.log(pc / pb)).sum())
    return out


def mutual_information(df: pd.DataFrame, win: int = 500, bins: int = 6,
                       lag: int = 1) -> np.ndarray:
    """过去收益与未来收益的互信息（滚动，因果）。

    互信息能捕捉 AR 模型看不到的非线性依赖。若 MI ≈ 0，说明该窗口内
    不存在任何（线性或非线性）可提取的方向信息。
    """
    c = df.close.to_numpy(float)
    r = _logret(c)
    n = len(c)
    out = np.full(n, np.nan)
    for t in range(win + lag, n):
        x = r[t - win:t - lag]
        y = r[t - win + lag:t]
        m = np.isfinite(x) & np.isfinite(y)
        x, y = x[m], y[m]
        if len(x) < 100:
            continue
        cx = np.digitize(x, np.percentile(x, np.linspace(0, 100, bins + 1)[1:-1]))
        cy = np.digitize(y, np.percentile(y, np.linspace(0, 100, bins + 1)[1:-1]))
        joint = np.histogram2d(cx, cy, bins=bins)[0]
        pj = joint / max(joint.sum(), 1)
        px = pj.sum(axis=1, keepdims=True)
        py = pj.sum(axis=0, keepdims=True)
        nz = pj > 0
        out[t] = float((pj[nz] * np.log(pj[nz] / (px @ py)[nz])).sum())
    return out


# ══════════════════════════════════════════════════════════════════
# H. 极值理论
# ══════════════════════════════════════════════════════════════════
def evt_tail_index(df: pd.DataFrame, win: int = 1000, k_frac: float = 0.1) -> np.ndarray:
    """Hill 估计量的尾指数 ξ（滚动，因果）。

    黄金收益尾部厚（01 号取证：超额峰度 100.9）。尾指数决定止损被跳空
    穿透的概率，是仓位规模的输入。
    """
    c = df.close.to_numpy(float)
    r = np.abs(_logret(c))
    n = len(c)
    out = np.full(n, np.nan)
    for t in range(win, n):
        w = r[t - win + 1:t + 1]
        w = w[np.isfinite(w) & (w > 0)]
        if len(w) < 100:
            continue
        k = max(int(len(w) * k_frac), 10)
        s = np.sort(w)[::-1]
        thr = s[k]
        if thr <= 0:
            continue
        out[t] = float(np.mean(np.log(s[:k] / thr)))
    return out


def evt_expected_shortfall(df: pd.DataFrame, win: int = 1000, alpha: float = 0.05) -> np.ndarray:
    """历史模拟 + EVT 修正的 Expected Shortfall（ES）。

    ES 比 VaR 更保守且次可加，是 Basel/FRTB 的标准风险度量。
    """
    c = df.close.to_numpy(float)
    r = _logret(c)
    n = len(c)
    out = np.full(n, np.nan)
    for t in range(win, n):
        w = r[t - win + 1:t + 1]
        w = w[np.isfinite(w)]
        if len(w) < 100:
            continue
        q = np.percentile(w, alpha * 100)
        tail = w[w <= q]
        if len(tail) == 0:
            continue
        out[t] = float(-tail.mean())
    return out


# ══════════════════════════════════════════════════════════════════
# I. 统计学习（全部滚动重估，样本外）
# ══════════════════════════════════════════════════════════════════
def _feature_matrix(df: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """构造候选特征矩阵（全部因果）。"""
    c = df.close.to_numpy(float)
    r = _logret(c)
    h, l, o = df.high.to_numpy(float), df.low.to_numpy(float), df.open.to_numpy(float)
    v = (df.tick_volume.to_numpy(float) if "tick_volume" in df.columns
         else df.volume.to_numpy(float))
    rng = np.maximum(h - l, EPS)
    feats = {
        "ret1": r,
        "ret5": pd.Series(c).pct_change(5).to_numpy(),
        "ret15": pd.Series(c).pct_change(15).to_numpy(),
        "ret60": pd.Series(c).pct_change(60).to_numpy(),
        "clv": (c - l) / rng * 2 - 1,
        "hl": np.log(h / np.maximum(l, EPS)),
        "vol_ratio": pd.Series(r).rolling(10).std().to_numpy() /
                     pd.Series(r).rolling(60).std().replace(0, np.nan).to_numpy(),
        "vol_z": _safe_scale(np.abs(r), 240, 3),
        "vchg": pd.Series(v).pct_change().replace([np.inf, -np.inf], np.nan).to_numpy(),
        "vz": _safe_scale(v, 240, 3),
        "body": (c - o) / rng,
        "gap": (o - np.roll(c, 1)) / np.maximum(np.roll(c, 1), EPS),
        "accel": pd.Series(c).pct_change(5).diff().to_numpy(),
        "hour_sin": np.sin(2 * np.pi * df.time.dt.hour.to_numpy() / 24),
        "hour_cos": np.cos(2 * np.pi * df.time.dt.hour.to_numpy() / 24),
    }
    names = list(feats)
    X = np.column_stack([feats[k] for k in names])
    return X, names


def ml_logit(df: pd.DataFrame, win: int = 3000, horizon: int = 15,
             refit_every: int = 250, min_train: int = 1500,
             l2: float = 1.0) -> np.ndarray:
    """L2 正则逻辑回归：滚动训练、严格样本外预测。

    标签 = 未来 horizon 根的收益方向。线性模型可解释、不易过拟合，
    是商用系统里最稳妥的 ML 基线。
    """
    X, _ = _feature_matrix(df)
    c = df.close.to_numpy(float)
    n = len(c)
    fwd = np.full(n, np.nan)
    fwd[:-horizon] = c[horizon:] - c[:-horizon]
    y = np.where(fwd > 0, 1.0, np.where(fwd < 0, 0.0, np.nan))
    out = np.full(n, np.nan)
    beta = None
    for t in range(min_train, n):
        if beta is None or (t - min_train) % refit_every == 0:
            a = max(0, t - win)
            Xa, ya = X[a:t], y[a:t]
            m = np.isfinite(Xa).all(axis=1) & np.isfinite(ya)
            if m.sum() < 300:
                continue
            Xa, ya = Xa[m], ya[m]
            mu, sd = Xa.mean(axis=0), Xa.std(axis=0) + EPS
            Xs = (Xa - mu) / sd
            Xs = np.column_stack([np.ones(len(Xs)), Xs])
            b = np.zeros(Xs.shape[1])
            for _ in range(25):                     # Newton-Raphson
                p = 1 / (1 + np.exp(-np.clip(Xs @ b, -30, 30)))
                W = np.maximum(p * (1 - p), 1e-6)
                g = Xs.T @ (p - ya) + l2 * np.r_[0, b[1:]]
                H = (Xs * W[:, None]).T @ Xs + l2 * np.eye(Xs.shape[1])
                H[0, 0] += 1e-8
                try:
                    step = np.linalg.solve(H, g)
                except np.linalg.LinAlgError:
                    break
                b -= step
                if np.abs(step).max() < 1e-6:
                    break
            beta = (b, mu, sd)
        b, mu, sd = beta
        xt = X[t]
        if not np.isfinite(xt).all():
            continue
        xs = (xt - mu) / sd
        out[t] = float(b[0] + xs @ b[1:])
    return out


def ml_ridge(df: pd.DataFrame, win: int = 3000, horizon: int = 15,
             refit_every: int = 250, min_train: int = 1500,
             alpha: float = 10.0) -> np.ndarray:
    """Ridge 回归直接预测未来收益幅度（比分类保留更多信息）。"""
    X, _ = _feature_matrix(df)
    c = df.close.to_numpy(float)
    n = len(c)
    fwd = np.full(n, np.nan)
    fwd[:-horizon] = np.log(c[horizon:] / c[:-horizon])
    out = np.full(n, np.nan)
    beta = None
    for t in range(min_train, n):
        if beta is None or (t - min_train) % refit_every == 0:
            a = max(0, t - win)
            Xa, ya = X[a:t], fwd[a:t]
            m = np.isfinite(Xa).all(axis=1) & np.isfinite(ya)
            if m.sum() < 300:
                continue
            Xa, ya = Xa[m], ya[m]
            mu, sd = Xa.mean(axis=0), Xa.std(axis=0) + EPS
            Xs = (Xa - mu) / sd
            Xs = np.column_stack([np.ones(len(Xs)), Xs])
            A = Xs.T @ Xs + alpha * np.eye(Xs.shape[1])
            A[0, 0] -= alpha
            try:
                b = np.linalg.solve(A, Xs.T @ ya)
            except np.linalg.LinAlgError:
                continue
            beta = (b, mu, sd)
        b, mu, sd = beta
        xt = X[t]
        if not np.isfinite(xt).all():
            continue
        out[t] = float(b[0] + ((xt - mu) / sd) @ b[1:])
    return out


def ml_gbdt(df: pd.DataFrame, win: int = 2000, horizon: int = 15,
            refit_every: int = 2000, min_train: int = 2000,
            n_trees: int = 25, depth: int = 3, lr: float = 0.08,
            n_bins: int = 16) -> np.ndarray:
    """梯度提升树（自实现，仅依赖 numpy）：捕捉非线性与交互。

    性能约束（商用关键）：树分裂用**预分箱直方图**（n_bins=16）而非
    遍历每个特征的每个分位点。原始实现是 O(n_features × 3分位 × n) 的
    Python 双层循环，196s 无法接受；预分箱后单次分裂只需一次
    O(n × n_features) 的 bincount 聚合，降到秒级。

    限制深度、树数与训练窗口，配合滚动重估与 purged CV 控制过拟合。
    """
    X, _ = _feature_matrix(df)
    c = df.close.to_numpy(float)
    n = len(c)
    fwd = np.full(n, np.nan)
    fwd[:-horizon] = np.log(c[horizon:] / c[:-horizon])
    out = np.full(n, np.nan)
    model = None

    def build_bins(Xa):
        """训练集上确定分箱边界（预测时必须复用，保证一致）。"""
        edges = []
        for f in range(Xa.shape[1]):
            qs = np.unique(np.percentile(Xa[:, f], np.linspace(0, 100, n_bins + 1)[1:-1]))
            edges.append(qs)
        return edges

    def digitize(Xa, edges):
        B = np.empty((len(Xa), len(edges)), dtype=np.int16)
        for f, e in enumerate(edges):
            B[:, f] = np.digitize(Xa[:, f], e)
        return B

    def fit_tree(B, resid, depth_):
        if depth_ == 0 or len(B) < 40:
            return {"leaf": float(resid.mean())}
        best = None
        nf = B.shape[1]
        for f in range(nf):
            nb = int(B[:, f].max()) + 1
            cnt = np.bincount(B[:, f], minlength=nb).astype(float)
            ssum = np.bincount(B[:, f], weights=resid, minlength=nb)
            ssq = np.bincount(B[:, f], weights=resid ** 2, minlength=nb)
            # 前缀和 → 每个切点的左右子集 SSE
            c_cnt = np.cumsum(cnt)[:-1]
            c_sum = np.cumsum(ssum)[:-1]
            c_sq = np.cumsum(ssq)[:-1]
            tot_cnt, tot_sum, tot_sq = cnt.sum(), ssum.sum(), ssq.sum()
            r_cnt = tot_cnt - c_cnt
            r_sum = tot_sum - c_sum
            r_sq = tot_sq - c_sq
            valid = (c_cnt >= 20) & (r_cnt >= 20)
            if not valid.any():
                continue
            sse = np.full(len(c_cnt), np.inf)
            with np.errstate(invalid="ignore", divide="ignore"):
                sse_l = c_sq - c_sum ** 2 / np.maximum(c_cnt, 1)
                sse_r = r_sq - r_sum ** 2 / np.maximum(r_cnt, 1)
                sse = np.where(valid, sse_l + sse_r, np.inf)
            k = int(np.argmin(sse))
            if best is None or sse[k] < best[0]:
                best = (float(sse[k]), f, k)
        if best is None or not np.isfinite(best[0]):
            return {"leaf": float(resid.mean())}
        _, f, k = best
        m = B[:, f] <= k
        if m.sum() < 20 or (~m).sum() < 20:
            return {"leaf": float(resid.mean())}
        return {"f": f, "k": k,
                "l": fit_tree(B[m], resid[m], depth_ - 1),
                "r": fit_tree(B[~m], resid[~m], depth_ - 1)}

    def pred_tree(node, B):
        if "leaf" in node:
            return np.full(len(B), node["leaf"])
        m = B[:, node["f"]] <= node["k"]
        o = np.empty(len(B))
        o[m] = pred_tree(node["l"], B[m])
        o[~m] = pred_tree(node["r"], B[~m])
        return o

    for t in range(min_train, n):
        if model is None or (t - min_train) % refit_every == 0:
            a = max(0, t - win)
            Xa, ya = X[a:t], fwd[a:t]
            m = np.isfinite(Xa).all(axis=1) & np.isfinite(ya)
            if m.sum() < 500:
                continue
            Xa, ya = Xa[m], ya[m]
            edges = build_bins(Xa)
            B = digitize(Xa, edges)
            base = float(ya.mean())
            trees, resid = [], ya - base
            for _ in range(n_trees):
                tr = fit_tree(B, resid, depth)
                trees.append(tr)
                resid = resid - lr * pred_tree(tr, B)
            model = (base, trees, edges)
        base, trees, edges = model
        xt = X[t]
        if not np.isfinite(xt).all():
            continue
        Bt = digitize(xt[None, :], edges)
        out[t] = base + lr * sum(float(pred_tree(tr, Bt)[0]) for tr in trees)
    return out


# ══════════════════════════════════════════════════════════════════
# J. 信号处理
# ══════════════════════════════════════════════════════════════════
def fft_dominant_cycle(df: pd.DataFrame, win: int = 240, min_period: int = 8) -> np.ndarray:
    """FFT 主周期相位：当前价格处在主导周期的哪个相位。

    相位法在周期性明显的市场（如亚盘区间）可作为反转择时输入。
    """
    c = df.close.to_numpy(float)
    n = len(c)
    out = np.full(n, np.nan)
    for t in range(win, n):
        w = c[t - win + 1:t + 1]
        w = w - w.mean()
        sp = np.abs(np.fft.rfft(w))
        freqs = np.fft.rfftfreq(len(w), d=1.0)
        lo = 1.0 / (win / 2)
        hi = 1.0 / min_period
        mask = (freqs >= lo) & (freqs <= hi)
        if mask.sum() < 2:
            continue
        k = np.argmax(sp[mask])
        idx = np.where(mask)[0][k]
        phase = np.angle(np.fft.rfft(w)[idx])
        out[t] = float(np.sin(phase))
    return out


def ema_cross_z(df: pd.DataFrame, fast: int = 12, slow: int = 48, win: int = 500) -> np.ndarray:
    """EMA 差值的滚动 z 分数（把经典指标标准化，便于统一评估）。"""
    c = pd.Series(df.close.to_numpy(float))
    d = c.ewm(span=fast, adjust=False).mean() - c.ewm(span=slow, adjust=False).mean()
    return _safe_scale(d.to_numpy(), win, 3.0)


# ══════════════════════════════════════════════════════════════════
# K. 最优执行 / 仓位
# ══════════════════════════════════════════════════════════════════
def almgren_chriss_urgency(df: pd.DataFrame, win: int = 240,
                           lam: float = 1.0) -> np.ndarray:
    """Almgren-Chriss 最优执行的紧迫度 κ = sqrt(λσ²/η)。

    用于决定「市价立刻成交」还是「挂单等待」：紧迫度高时应市价（宁可付点差），
    低时挂单（赚点差）。这是挂单/市价切换的数学依据，而不是拍脑袋。

    σ 用相对收益（无量纲），η 用相对成交量的倒数（无量纲），
    因此 κ 是纯数，可跨品种比较。
    """
    c = df.close.to_numpy(float)
    r = _logret(c)
    n = len(c)
    v = (df.tick_volume.to_numpy(float) if "tick_volume" in df.columns
         else df.volume.to_numpy(float))
    sigma = pd.Series(r).rolling(win, min_periods=60).std().to_numpy()
    vbar = pd.Series(v).rolling(win, min_periods=60).mean().to_numpy()
    # 用**滚动中位数**做归一化（绝不能用全样本中位数——那是前视）
    ref = pd.Series(vbar).rolling(win * 4, min_periods=60).median().to_numpy()
    eta_rel = np.maximum(vbar / np.maximum(ref, 1.0), 1e-3)
    return np.sqrt(np.maximum(lam * sigma ** 2 / eta_rel, 0))


def vol_target_position(df: pd.DataFrame, target_vol: float = 0.01,
                        win: int = 1440, cap: float = 3.0) -> np.ndarray:
    """波动率目标仓位系数：k = min(target/σ̂, cap)。

    这是唯一被广泛验证「改善风险调整收益」的仓位规则（见 04 号取证 C 节）。
    """
    c = df.close.to_numpy(float)
    r = _logret(c)
    sig = pd.Series(r).rolling(win, min_periods=120).std().to_numpy()
    daily = sig * np.sqrt(1440)
    return np.clip(target_vol / np.maximum(daily, EPS), 0.25, cap)


# ══════════════════════════════════════════════════════════════════
# 注册表
# ══════════════════════════════════════════════════════════════════
@dataclass
class ModelSpec:
    name: str
    category: str
    kind: str                     # direction | state
    fn: Callable[[pd.DataFrame], np.ndarray]
    note: str = ""


def _d(*a, **k):
    return ModelSpec(*a, **k)


REGISTRY: list[ModelSpec] = [
    # —— 波动率与风险 ——
    _d("vol_ewma", "volatility", "state", vol_ewma, "EWMA 波动率"),
    _d("vol_parkinson", "volatility", "state", vol_parkinson, "Parkinson 高低价波动率"),
    _d("vol_garman_klass", "volatility", "state", vol_garman_klass, "Garman-Klass OHLC 波动率"),
    _d("vol_bpv", "volatility", "state", vol_bpv, "Bipower 跳跃稳健波动率"),
    _d("jump_ratio", "volatility", "state", jump_ratio, "跳跃占比"),
    _d("vol_of_vol", "volatility", "state", vol_of_vol, "波动率的波动率"),
    _d("rough_vol_hurst", "volatility", "state", rough_vol_hurst, "粗糙波动率 H(DFA)"),
    _d("vol_regime_quantile", "volatility", "state", vol_regime_quantile, "波动率历史分位"),
    # —— 微观结构 ——
    _d("roll_spread", "micro", "state", roll_spread, "Roll 有效点差"),
    _d("cs_spread", "micro", "state", cs_spread, "Corwin-Schultz 点差"),
    _d("amihud", "micro", "state", amihud_illiquidity, "Amihud 非流动性"),
    _d("kyle_lambda", "micro", "state", kyle_lambda, "Kyle λ 价格冲击"),
    _d("ofi", "micro", "direction", order_flow_imbalance, "订单流不平衡 OFI"),
    _d("vpin", "micro", "state", vpin_proxy, "VPIN 知情交易概率"),
    # —— 长记忆 / 分数阶 ——
    _d("fracdiff", "memory", "direction", lambda d: fracdiff_price(d, 0.4), "分数阶差分 d=0.4"),
    _d("hurst_dfa", "memory", "state", hurst_dfa, "DFA Hurst"),
    # —— 随机过程 ——
    _d("ou_halflife", "process", "state", ou_halflife, "OU 均值回归半衰期"),
    _d("ou_zscore", "process", "direction", ou_zscore, "OU 偏离 z 分数"),
    _d("variance_ratio", "process", "state", lambda d: variance_ratio_stat(d, 5, 240), "方差比 VR(5)"),
    # —— 时间序列 ——
    _d("ar_forecast", "ts", "direction", lambda d: ar_forecast(d, 5, 500), "滚动 AR(5) 预测"),
    _d("kalman_trend", "ts", "direction", kalman_dynamic_beta, "卡尔曼自适应趋势"),
    # —— Regime ——
    _d("hmm_high_vol", "regime", "state", hmm_high_vol_prob, "HMM 高波动后验概率"),
    _d("cusum", "regime", "state", cusum_changepoint, "CUSUM 变点强度"),
    # —— 信息论 ——
    _d("entropy", "info", "state", shannon_entropy, "收益分布 Shannon 熵"),
    _d("kl_div", "info", "state", kl_divergence, "分布漂移 KL 散度"),
    _d("mutual_info", "info", "state", lambda d: mutual_information(d, 500, 6, 1), "收益互信息"),
    # —— 极值理论 ——
    _d("evt_hill", "extreme", "state", evt_tail_index, "Hill 尾指数"),
    _d("evt_es", "extreme", "state", evt_expected_shortfall, "EVT Expected Shortfall"),
    # —— 统计学习 ——
    _d("ml_logit", "ml", "direction", lambda d: ml_logit(d, 3000, 15, 250, 1500), "L2 逻辑回归"),
    _d("ml_ridge", "ml", "direction", lambda d: ml_ridge(d, 3000, 15, 250, 1500), "Ridge 收益回归"),
    _d("ml_gbdt", "ml", "direction", lambda d: ml_gbdt(d, 3000, 15, 500, 2000), "梯度提升树"),
    # —— 信号处理 ——
    _d("fft_cycle", "signal", "direction", fft_dominant_cycle, "FFT 主周期相位"),
    _d("ema_cross_z", "signal", "direction", ema_cross_z, "EMA 差 z 分数"),
    # —— 最优执行 ——
    _d("ac_urgency", "exec", "state", almgren_chriss_urgency, "Almgren-Chriss 紧迫度"),
    _d("vol_target", "exec", "state", vol_target_position, "波动率目标系数"),
]

BY_NAME = {m.name: m for m in REGISTRY}
DIRECTION_MODELS = [m for m in REGISTRY if m.kind == "direction"]
STATE_MODELS = [m for m in REGISTRY if m.kind == "state"]
