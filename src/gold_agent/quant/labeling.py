"""标签引擎（用户所说「标注最佳位置」）。

三个层次的标注，全部无前视：

1. **三重障碍标注（Triple Barrier, López de Prado AFML ch.3）**
   在每个候选入场点 t 同时设置：
     - 上障碍：+pt·σ_t（止盈）
     - 下障碍：−sl·σ_t（止损）
     - 时间障碍：t + max_hold（超时平仓）
   标注结果 y ∈ {+1, −1, 0}，以及**首次触达时刻** t1（用于样本唯一性加权）。
   σ_t 用 EWMA 波动率（**只用 t 及以前**），实现波动率自适应障碍。

2. **元标注（Meta-Labeling, AFML ch.3.6）**
   一级模型给方向，二级模型只回答「这个信号该不该执行」。
   标签 y_meta = 1 若该笔按给定几何实际盈利（含成本），否则 0。
   这是**提升精确率（precision）而不牺牲召回**的标准手段，直接对应「提高信号准确度」。

3. **样本唯一性权重（uniqueness）**
   重叠标签会虚增有效样本量。对每个样本计算其标签区间与其它样本的重叠程度，
   权重 w_i ∝ 1/（平均重叠数）。所有统计量（IC、t 值、Sharpe）必须加权计算，
   否则显著性被系统性高估。

**成本模型**：黄金 XAUUSDm 点差 260 points = 0.260 USD/盎司（实测中位数）。
往返成本 = 2 × 点差。挂单入场只付单边点差。所有净收益评估强制扣除。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


# ──────────────────────────────────────────────────────────────────
# 波动率估计（标签与仓位的共同基础，严格无前视）
# ──────────────────────────────────────────────────────────────────
def ewma_vol(close: np.ndarray, halflife: float = 60.0,
             min_periods: int = 30) -> np.ndarray:
    """EWMA 波动率（每根 bar 的绝对价格波动，单位 = 价格）。

    只用 t 及以前的数据（pandas ewm 本身无前视）。
    """
    s = pd.Series(close)
    r = np.log(s).diff()
    v = r.ewm(halflife=halflife, min_periods=min_periods).std()
    return (v * s).to_numpy()


def garch11_vol(r: np.ndarray, refit_every: int = 500,
                min_obs: int = 300) -> np.ndarray:
    """GARCH(1,1) 条件波动率，**滚动重估 + 严格一步预测**（无前视）。

    实现要点（商用级）：
      - 每 refit_every 根用截至当前的历史重新做 MLE；
      - 参数冻结后逐根滤波，输出的是 t 时刻对 t+1 的预测 σ；
      - 失败时回退 EWMA（不抛错，保证主循环不中断）。
    """
    from scipy import optimize

    n = len(r)
    out = np.full(n, np.nan)
    if n < min_obs:
        return out

    def negll(theta, x):
        mu, w, a, b = theta
        if w <= 1e-16 or a < 0 or b < 0 or a + b >= 0.999:
            return 1e12
        s2 = np.empty(len(x))
        s2[0] = np.var(x)
        e = x - mu
        for t in range(1, len(x)):
            s2[t] = max(w + a * e[t - 1] ** 2 + b * s2[t - 1], 1e-16)
        return 0.5 * float(np.sum(np.log(2 * np.pi * s2) + e ** 2 / s2))

    theta = np.array([0.0, np.var(r[:min_obs]) * 0.05, 0.08, 0.90])
    s2_state = np.var(r[:min_obs])
    mu, w, a, b = theta
    for t in range(min_obs, n):
        if (t - min_obs) % refit_every == 0:
            x = r[:t]
            best, bf = None, np.inf
            for a0 in (0.05, 0.12):
                for b0 in (0.80, 0.90):
                    th0 = np.array([x.mean(), np.var(x) * 0.05, a0, b0])
                    try:
                        res = optimize.minimize(negll, th0, args=(x,),
                                                method="Nelder-Mead",
                                                options={"maxiter": 2500,
                                                         "xatol": 1e-8, "fatol": 1e-8})
                    except Exception:
                        continue
                    if res.fun < bf:
                        bf, best = float(res.fun), res.x
            if best is not None:
                mu, w, a, b = best
            # 用新参数把状态推到当前（只用历史）
            s2_state = np.var(x)
            e = x - mu
            for k in range(1, len(x)):
                s2_state = max(w + a * e[k - 1] ** 2 + b * s2_state, 1e-16)
        out[t] = np.sqrt(s2_state)          # t 时刻对 t+1 的预测
        s2_state = max(w + a * (r[t] - mu) ** 2 + b * s2_state, 1e-16)
    return out


# ──────────────────────────────────────────────────────────────────
# 三重障碍标注
# ──────────────────────────────────────────────────────────────────
@dataclass
class TripleBarrierResult:
    label: np.ndarray       # +1 触上障 / -1 触下障 / 0 超时
    t1: np.ndarray          # 标签结束的 bar 序号（用于唯一性权重）
    ret: np.ndarray         # 实际实现收益（价格差，已扣成本）
    bars_held: np.ndarray   # 持有 bar 数
    touch: np.ndarray       # 'tp' | 'sl' | 'time'


def triple_barrier(close: np.ndarray, high: np.ndarray, low: np.ndarray,
                   vol: np.ndarray, side: np.ndarray,
                   pt_mult: float = 2.0, sl_mult: float = 1.0,
                   max_hold: int = 60, cost: float = 0.52,
                   cost_on_entry: bool = False) -> TripleBarrierResult:
    """三重障碍标注。

    side: 每个时点的**假设方向** ∈ {+1,-1,0}（由一级模型或全方向给出）。
    vol : t 时刻的预测波动（价格单位，无前视）。
    障碍宽度 = mult × vol_t，随波动自适应——这是与固定 ATR 倍数的关键区别。

    cost: 往返成本（价格单位）。cost_on_entry=True 表示挂单入场，只付单边。
    """
    n = len(close)
    label = np.zeros(n, dtype=np.int8)
    t1 = np.arange(n)
    ret = np.zeros(n)
    held = np.zeros(n, dtype=np.int32)
    touch = np.array(["none"] * n, dtype=object)

    c = cost if cost_on_entry else cost
    # 方向必须是干净的 ±1/0 整数；NaN/inf 一律视为无方向。
    # （np.sign(nan).astype(int) 会溢出成 INT_MIN，进而污染整段收益序列。）
    side = np.asarray(side, dtype=float)
    side = np.where(np.isfinite(side), side, 0.0)
    side = np.sign(side).astype(np.int8)

    for t in range(n - 1):
        s = int(side[t])
        if s == 0 or not np.isfinite(vol[t]) or vol[t] <= 0:
            continue
        # 障碍必须随方向翻转：多头止盈在上、止损在下；空头相反。
        if s > 0:
            tp_px = close[t] + pt_mult * vol[t]
            sl_px = close[t] - sl_mult * vol[t]
        else:
            tp_px = close[t] - pt_mult * vol[t]
            sl_px = close[t] + sl_mult * vol[t]
        end = min(t + max_hold, n - 1)
        hit = None
        for j in range(t + 1, end + 1):
            hi, lo = high[j], low[j]
            if s > 0:
                touch_tp, touch_sl = hi >= tp_px, lo <= sl_px
            else:
                touch_tp, touch_sl = lo <= tp_px, hi >= sl_px
            if touch_tp and touch_sl:
                # 同一根 bar 双触发：无法判定先后 → 保守判为亏损（商用系统必须保守）
                hit = ("sl", j)
                break
            if touch_tp:
                hit = ("tp", j)
                break
            if touch_sl:
                hit = ("sl", j)
                break
        if hit is None:
            j = end
            exit_px = close[j]
            touch[t] = "time"
        else:
            kind, j = hit
            exit_px = tp_px if kind == "tp" else sl_px
            touch[t] = kind
        pnl = s * (exit_px - close[t]) - c
        # 标签统一由**扣成本后的净盈亏**决定，而不是由触达哪一侧障碍决定。
        # 否则当成本大于障碍宽度时（极端行情/点差扩大）会把亏损单标成盈利单。
        label[t] = 1 if pnl > 0 else (-1 if pnl < 0 else 0)
        t1[t] = j
        ret[t] = pnl
        held[t] = j - t
    return TripleBarrierResult(label=label, t1=t1, ret=ret,
                               bars_held=held, touch=touch)


def uniqueness_weights(t1: np.ndarray, n: int) -> np.ndarray:
    """样本唯一性权重（AFML ch.4）。

    对每个样本 i，统计有多少其它样本的标签区间与其重叠，权重取倒数均值。
    用途：所有显著性检验必须用它加权，否则 t 值被高估 √(平均重叠数) 倍。
    """
    w = np.zeros(n, dtype=float)
    conc = np.zeros(n, dtype=float)
    for i in range(n):
        if t1[i] <= i:
            w[i] = 1.0
            continue
        a, b = i, int(t1[i])
        conc[a:b + 1] += 1.0
    for i in range(n):
        if t1[i] > i:
            a, b = i, int(t1[i])
            w[i] = 1.0 / max(conc[a:b + 1].mean(), 1e-9)
        else:
            w[i] = 1.0
    return w


# ──────────────────────────────────────────────────────────────────
# 元标注
# ──────────────────────────────────────────────────────────────────
def meta_labels(ret: np.ndarray, side: np.ndarray, cost: float = 0.52) -> np.ndarray:
    """元标注：一级方向信号在该点上是否「值得执行」。

    y_meta = 1 若按该方向的实际实现收益（已扣成本）> 0，否则 0。
    注意：这里的 ret 已由 triple_barrier 算出（含成本），直接取符号即可。
    """
    y = np.zeros(len(ret), dtype=np.int8)
    m = (side != 0) & np.isfinite(ret)
    y[m] = (ret[m] > 0).astype(np.int8)
    return y


# ──────────────────────────────────────────────────────────────────
# Purged / Embargo K-Fold（AFML ch.7）
# ──────────────────────────────────────────────────────────────────
def purged_kfold_indices(t1: np.ndarray, n_splits: int = 5,
                         embargo_pct: float = 0.01) -> list[tuple[np.ndarray, np.ndarray]]:
    """Purged K-Fold：训练集剔除与测试集标签区间重叠的样本，并加 embargo。

    普通 K-Fold 在金融时间序列上会因标签重叠造成严重泄漏，
    这是回测虚高的第一大成因。商用系统必须用 purged CV。
    """
    n = len(t1)
    embargo = int(n * embargo_pct)
    idx = np.arange(n)
    folds = np.array_split(idx, n_splits)
    out = []
    for f in folds:
        test = f
        t_start, t_end = test.min(), int(t1[test].max())
        train_mask = np.ones(n, dtype=bool)
        train_mask[t_start:t_end + 1 + embargo] = False
        for i in range(n):
            if t1[i] > t_start and i < t_end:
                train_mask[i] = False
        out.append((np.where(train_mask)[0], test))
    return out


# ──────────────────────────────────────────────────────────────────
# 评估指标
# ──────────────────────────────────────────────────────────────────
def newey_west_t(x: np.ndarray, lags: int = 5) -> float:
    """Newey-West 稳健 t 值。重叠样本必须用它，否则 t 值虚高数倍。"""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 30:
        return float("nan")
    e = x - x.mean()
    var = float(e @ e) / n
    for L in range(1, lags + 1):
        var += 2 * (1 - L / (lags + 1)) * float(e[L:] @ e[:-L]) / n
    return float(x.mean() / np.sqrt(max(var, 1e-18) / n))


def weighted_nw_t(x: np.ndarray, w: np.ndarray, lags: int = 5) -> float:
    """加权 Newey-West t（样本唯一性权重）。"""
    m = np.isfinite(x) & np.isfinite(w) & (w > 0)
    if m.sum() < 30:
        return float("nan")
    x, w = x[m], w[m]
    w = w / w.sum()
    mu = float((w * x).sum())
    e = x - mu
    var = float((w * e ** 2).sum())
    n_eff = 1.0 / float((w ** 2).sum())
    for L in range(1, lags + 1):
        num = float((w[L:] * e[L:] * e[:-L]).sum())
        var += 2 * (1 - L / (lags + 1)) * num
    return float(mu / np.sqrt(max(var, 1e-18) / n_eff))


def spearman_ic(x: np.ndarray, y: np.ndarray, w: np.ndarray | None = None) -> float:
    """Spearman 信息系数（可加权）。"""
    m = np.isfinite(x) & np.isfinite(y)
    if w is not None:
        m &= np.isfinite(w) & (w > 0)
    if m.sum() < 30:
        return float("nan")
    xa, ya = x[m], y[m]
    rx = pd.Series(xa).rank().to_numpy()
    ry = pd.Series(ya).rank().to_numpy()
    if w is None:
        return float(np.corrcoef(rx, ry)[0, 1])
    ww = w[m]
    ww = ww / ww.sum()
    mx, my = (ww * rx).sum(), (ww * ry).sum()
    cov = (ww * (rx - mx) * (ry - my)).sum()
    sx = np.sqrt((ww * (rx - mx) ** 2).sum())
    sy = np.sqrt((ww * (ry - my) ** 2).sum())
    return float(cov / max(sx * sy, 1e-18))


def deflated_sharpe(sr: float, n_trials: int, n_obs: int,
                    skew: float, kurt: float) -> tuple[float, float]:
    """Deflated Sharpe Ratio（Bailey & López de Prado 2014）。

    返回 (dsr, sr0)：dsr = P(真实 Sharpe > 0 | 试验了 n_trials 次)；
    sr0 = 纯噪声下 n_trials 次试验的期望最大 Sharpe（年化需自行换算）。
    """
    from scipy import stats as _st
    euler = 0.5772156649
    if n_trials < 2 or n_obs < 30:
        return float("nan"), float("nan")
    e_max = ((1 - euler) * _st.norm.ppf(1 - 1.0 / n_trials) +
             euler * _st.norm.ppf(1 - 1.0 / (n_trials * np.e)))
    sr0 = e_max / np.sqrt(n_obs)
    num = (sr - sr0) * np.sqrt(n_obs - 1)
    den = np.sqrt(max(1 - skew * sr + ((kurt - 1) / 4) * sr ** 2, 1e-12))
    return float(_st.norm.cdf(num / den)), float(sr0)


def sharpe_annualized(pnl: np.ndarray, bars_per_year: float) -> float:
    pnl = pnl[np.isfinite(pnl)]
    if len(pnl) < 30 or pnl.std() == 0:
        return float("nan")
    return float(pnl.mean() / pnl.std() * np.sqrt(bars_per_year))
