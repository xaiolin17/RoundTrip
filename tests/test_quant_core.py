"""量化内核的回归测试（真实数据，无 mock）。

覆盖：
  - 三重障碍标注的正确性与保守性（同 bar 双触发判亏）
  - 唯一性权重与 purged K-Fold 的无泄漏性质
  - 各模型的因果性（截断数据后历史输出不变）
  - Newey-West / DSR 的数值健全性
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gold_agent.common.config import CFG
from gold_agent.quant import models as M
from gold_agent.quant.labeling import (deflated_sharpe, ewma_vol, newey_west_t,
                                       purged_kfold_indices, spearman_ic,
                                       triple_barrier, uniqueness_weights,
                                       weighted_nw_t)


@pytest.fixture(scope="module")
def df1m() -> pd.DataFrame:
    path = CFG.data_dir / "XAUUSDm_1m.parquet"
    if not path.exists():
        pytest.skip("无 1m 历史数据")
    d = pd.read_parquet(path)
    d["time"] = pd.to_datetime(d["time"], utc=True)
    return d.sort_values("time").reset_index(drop=True).iloc[:8000].reset_index(drop=True)


# ────────────────────────── 标注 ──────────────────────────
def test_triple_barrier_conservative_on_double_touch():
    """同一根 bar 同时触及上下障碍时必须判亏（商用系统保守原则）。"""
    close = np.array([100.0, 100.0, 100.0])
    high = np.array([100.0, 200.0, 100.0])      # 同时触及 TP 与 SL
    low = np.array([100.0, 1.0, 100.0])
    vol = np.array([1.0, 1.0, 1.0])
    side = np.array([1, 0, 0])
    tb = triple_barrier(close, high, low, vol, side, pt_mult=2.0, sl_mult=1.0,
                        max_hold=5, cost=0.0)
    assert tb.label[0] == -1
    assert tb.touch[0] == "sl"


def test_triple_barrier_hits_tp():
    close = np.array([100.0, 103.0, 103.0])
    high = np.array([100.0, 103.0, 103.0])
    low = np.array([100.0, 99.9, 103.0])
    vol = np.array([1.0, 1.0, 1.0])
    side = np.array([1, 0, 0])
    tb = triple_barrier(close, high, low, vol, side, 2.0, 1.0, 5, 0.0)
    assert tb.label[0] == 1 and tb.touch[0] == "tp"
    assert tb.t1[0] == 1


def test_triple_barrier_short_side_uses_flipped_barriers():
    """空头障碍必须翻转：止盈在下、止损在上。

    这是最关键的方向性回归测试——若障碍不随方向翻转，空头会被系统性地
    判成「几乎全部止损」，从而污染整个模型擂台结论。
    """
    # 空头：价格下跌 → 应触发 TP
    close = np.array([100.0, 97.0, 97.0])
    high = np.array([100.0, 100.1, 97.0])
    low = np.array([100.0, 96.9, 97.0])
    vol = np.array([1.0, 1.0, 1.0])
    side = np.array([-1, 0, 0])
    tb = triple_barrier(close, high, low, vol, side, 2.0, 1.0, 5, 0.0)
    assert tb.label[0] == 1, "空头下跌必须判为盈利"
    assert tb.touch[0] == "tp"

    # 空头：价格上涨 → 应触发 SL
    close2 = np.array([100.0, 101.5, 101.5])
    high2 = np.array([100.0, 101.6, 101.5])
    low2 = np.array([100.0, 99.9, 101.5])
    tb2 = triple_barrier(close2, high2, low2, vol, side, 2.0, 1.0, 5, 0.0)
    assert tb2.label[0] == -1, "空头上涨必须判为亏损"
    assert tb2.touch[0] == "sl"


def test_triple_barrier_handles_nan_side_without_overflow():
    """NaN 方向不得溢出成 INT_MIN 而污染收益序列。"""
    close = np.array([100.0, 101.0, 102.0])
    high = np.array([100.0, 101.0, 102.0])
    low = np.array([100.0, 100.0, 101.0])
    vol = np.array([1.0, 1.0, 1.0])
    side = np.array([np.nan, np.inf, 1.0])
    tb = triple_barrier(close, high, low, vol, side, 2.0, 1.0, 5, 0.0)
    assert np.all(np.isfinite(tb.ret))
    assert np.abs(tb.ret).max() < 100.0, f"收益异常: {tb.ret}"
    assert tb.label[0] == 0 and tb.label[1] == 0


def test_triple_barrier_short_tp_and_sl_are_symmetric():
    """对称的上下行情下，多空胜率应当对称。"""
    rng = np.random.default_rng(42)
    n = 4000
    px = 100 + np.cumsum(rng.standard_normal(n) * 0.5)
    close = np.abs(px) + 50
    high = close + np.abs(rng.standard_normal(n)) * 0.3
    low = close - np.abs(rng.standard_normal(n)) * 0.3
    vol = np.full(n, 1.0)
    long_r = triple_barrier(close, high, low, vol, np.ones(n, int), 2.0, 1.0, 30, 0.0)
    short_r = triple_barrier(close, high, low, vol, -np.ones(n, int), 2.0, 1.0, 30, 0.0)
    long_tp = np.mean(long_r.touch == "tp")
    short_tp = np.mean(short_r.touch == "tp")
    assert abs(long_tp - short_tp) < 0.05, \
        f"多空 TP 触发率不对称: {long_tp:.3f} vs {short_tp:.3f}"


def test_triple_barrier_cost_can_flip_label():
    """刚好打到 TP 但成本更高时，应判为不盈利。"""
    close = np.array([100.0, 102.0, 102.0])
    high = np.array([100.0, 102.0, 102.0])
    low = np.array([100.0, 100.0, 102.0])
    vol = np.array([1.0, 1.0, 1.0])
    side = np.array([1, 0, 0])
    tb = triple_barrier(close, high, low, vol, side, 2.0, 1.0, 5, cost=3.0)
    assert tb.label[0] == -1          # 2.0 毛利 - 3.0 成本 < 0


def test_uniqueness_weights_bounds():
    t1 = np.array([5, 6, 7, 8, 9, 9, 9, 9, 9, 9])
    w = uniqueness_weights(t1, 10)
    assert len(w) == 10
    assert np.all(w > 0) and np.all(w <= 1.0 + 1e-9)
    assert w[0] < w[-1]               # 早期样本与更多标签重叠 → 权重更低


def test_purged_kfold_no_overlap():
    n = 1000
    t1 = np.minimum(np.arange(n) + 30, n - 1)
    folds = purged_kfold_indices(t1, n_splits=5, embargo_pct=0.01)
    assert len(folds) == 5
    for tr, te in folds:
        assert len(np.intersect1d(tr, te)) == 0
        # 训练集不得包含测试区间内的标签
        t_lo, t_hi = te.min(), t1[te].max()
        inside = tr[(tr >= t_lo) & (tr <= t_hi)]
        assert len(inside) == 0


# ────────────────────────── 统计量 ──────────────────────────
def test_newey_west_reduces_t_for_positive_autocorr():
    rng = np.random.default_rng(0)
    e = rng.standard_normal(5000)
    x = np.zeros(5000)
    for i in range(1, 5000):          # 强正自相关序列
        x[i] = 0.9 * x[i - 1] + e[i]
    x = x + 0.5
    t_nw = newey_west_t(x, lags=50)
    t_naive = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
    assert abs(t_nw) < abs(t_naive)   # NW 必须更保守


def test_weighted_nw_t_runs():
    rng = np.random.default_rng(1)
    x = rng.standard_normal(1000) * 0.5 + 0.1
    w = rng.uniform(0.2, 1.0, 1000)
    t = weighted_nw_t(x, w, lags=10)
    assert np.isfinite(t)


def test_deflated_sharpe_penalizes_many_trials():
    d1, _ = deflated_sharpe(0.05, 2, 5000, 0.0, 3.0)
    d2, _ = deflated_sharpe(0.05, 500, 5000, 0.0, 3.0)
    assert d2 < d1                    # 试验越多，同样的 Sharpe 越不可信
    assert 0.0 <= d2 <= 1.0


def test_spearman_ic_perfect():
    x = np.arange(200, dtype=float)
    assert abs(spearman_ic(x, x) - 1.0) < 1e-9
    assert abs(spearman_ic(x, -x) + 1.0) < 1e-9


# ────────────────────────── 模型因果性 ──────────────────────────
CAUSAL_MODELS = ["vol_ewma", "vol_parkinson", "vol_garman_klass", "jump_ratio",
                 "vol_of_vol", "vol_regime_quantile", "roll_spread", "cs_spread",
                 "amihud", "kyle_lambda", "ofi", "vpin", "fracdiff", "ou_halflife",
                 "ou_zscore", "variance_ratio", "ar_forecast", "kalman_trend",
                 "cusum", "entropy", "kl_div", "evt_hill", "evt_es",
                 "fft_cycle", "ema_cross_z", "ac_urgency", "vol_target"]


@pytest.mark.parametrize("name", CAUSAL_MODELS)
def test_model_has_no_lookahead(df1m, name):
    """截断数据后重算，重叠部分必须逐点一致（无前视）。"""
    spec = M.BY_NAME[name]
    full = np.asarray(spec.fn(df1m), float)
    half = len(df1m) // 2
    part = np.asarray(spec.fn(df1m.iloc[:half].reset_index(drop=True)), float)
    m = np.isfinite(full[:half]) & np.isfinite(part[:half])
    assert m.sum() > 50, f"{name}: 有效值过少"
    denom = np.abs(part[:half][m]) + 1e-9
    leak = float(np.max(np.abs(full[:half][m] - part[:half][m]) / denom))
    assert leak < 1e-6, f"{name}: 检测到前视泄漏 {leak:.3e}"


def test_ewma_vol_positive(df1m):
    v = ewma_vol(df1m.close.to_numpy(float), 60, 30)
    fin = v[np.isfinite(v)]
    assert len(fin) > 100 and np.all(fin > 0)


def test_all_models_return_right_length(df1m):
    for spec in M.REGISTRY:
        v = np.asarray(spec.fn(df1m), float)
        assert len(v) == len(df1m), f"{spec.name} 长度不匹配"
