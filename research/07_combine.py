"""组合与验证引擎：把单模型重组成最优组合，走前验证，误差分析调权。

核心方法（全部严格因果，权重只用历史估计）：
  1. 等权（基准，不可被轻易击败）
  2. IC 加权（滚动 IC 作为权重，负 IC 自动反向）
  3. 逆波动加权
  4. Ridge 堆叠（purged 走前拟合）
  5. PCA 主成分组合（去共线性）
  6. 元标注过滤器（二级模型只决定「做不做」，提升精确率）
  7. 误差分析：按状态/时段/波动分档，找出模型失效条件，回归出条件权重

验证：
  - 走前（walk-forward）样本外评估，权重每 N 根重估一次
  - Purged K-Fold 交叉验证
  - Deflated Sharpe / PBO
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_agent.common.config import CFG
from gold_agent.quant import models as M
from gold_agent.quant.labeling import (deflated_sharpe, ewma_vol, newey_west_t,
                                       purged_kfold_indices, spearman_ic,
                                       triple_barrier, uniqueness_weights)

RES = Path(__file__).parent
CACHE = RES / "model_cache"
OUT: list[str] = []


def p(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


TF = sys.argv[1] if len(sys.argv) > 1 else "1m"
MAXBARS = int(sys.argv[2]) if len(sys.argv) > 2 else 60000

df = pd.read_parquet(CFG.data_dir / f"XAUUSDm_{TF}.parquet")
df["time"] = pd.to_datetime(df["time"], utc=True)
df = df.sort_values("time").reset_index(drop=True).iloc[-MAXBARS:].reset_index(drop=True)
SPREAD = float(df.spread.median()) * 0.001
COST = 2 * SPREAD
n = len(df)

p("=" * 92)
p(f"组合与验证 · 周期={TF} · {n} 根 · 成本 {COST:.3f} USD")
p("=" * 92)

# ── 载入模型输出 ─────────────────────────────────────────────────
names, cols = [], []
for spec in M.DIRECTION_MODELS:
    cf = CACHE / f"{TF}_{MAXBARS}_{spec.name}.npy"
    if cf.exists():
        v = np.load(cf)
        if len(v) == n:
            names.append(spec.name)
            cols.append(v)
states = {}
for spec in M.STATE_MODELS:
    cf = CACHE / f"{TF}_{MAXBARS}_{spec.name}.npy"
    if cf.exists():
        v = np.load(cf)
        if len(v) == n:
            states[spec.name] = v

X_raw = np.column_stack(cols)


def zscore(x, win=1440):
    s = pd.Series(x)
    m = s.rolling(win, min_periods=120).mean()
    sd = s.rolling(win, min_periods=120).std().replace(0, np.nan)
    return np.clip(((s - m) / sd).to_numpy(), -4, 4)


X = np.column_stack([zscore(X_raw[:, i]) for i in range(X_raw.shape[1])])
p(f"方向模型 {len(names)} 个: {names}")

close = df.close.to_numpy(float)
high = df.high.to_numpy(float)
low = df.low.to_numpy(float)
vol = ewma_vol(close, 60, 30)
vol = np.where(np.isfinite(vol) & (vol > 0), vol, np.nanmedian(vol))
fwd15 = np.full(n, np.nan)
fwd15[:-15] = close[15:] - close[:-15]

# ── 组合方法 ─────────────────────────────────────────────────────
REBAL = 1440          # 每 1 天重估权重
MIN_TRAIN = 5000      # 至少 5000 根（约 3.5 天）才开仓


def eval_signal(sig: np.ndarray, tag: str, hold: int = 60) -> dict:
    """统一评估：按 sig 符号进场，三重障碍出场，扣成本。"""
    sgn = np.sign(np.nan_to_num(sig, nan=0.0))
    tb = triple_barrier(close, high, low, vol, sgn.astype(int), 2.0, 1.0, hold, COST)
    uni = uniqueness_weights(tb.t1, n)
    m = (sgn != 0) & np.isfinite(tb.ret) & (tb.bars_held > 0)
    if m.sum() < 100:
        return {"tag": tag, "n": int(m.sum()), "valid": False}
    ret = tb.ret[m]
    sr = ret.mean() / max(ret.std(), 1e-12) * np.sqrt(1440 / max(tb.bars_held[m].mean(), 1))
    return {"tag": tag, "n": int(m.sum()), "valid": True,
            "hit": float(np.mean(ret > 0)), "mean": float(ret.mean()),
            "nw_t": newey_west_t(ret, 30), "sharpe": float(sr),
            "total": float(ret.sum()), "std": float(ret.std()),
            "skew": float(pd.Series(ret).skew()),
            "kurt": float(pd.Series(ret).kurtosis() + 3),
            "uni_mean": float(uni[m].mean()),
            "avg_bars": float(tb.bars_held[m].mean()),
            "ic15": spearman_ic(sig, fwd15, uni)}


# ── 1) 单模型基准 ────────────────────────────────────────────────
p("\n[1] 单模型基准（样本外无效，仅作参照）")
single = []
for i, nm in enumerate(names):
    r = eval_signal(X[:, i], nm)
    if r.get("valid"):
        single.append(r)
sdf = pd.DataFrame(single).sort_values("nw_t", ascending=False)
p(f"{'模型':<18}{'笔数':>7}{'命中':>8}{'净均值':>10}{'NW-t':>8}{'年化SR':>9}{'IC15':>9}")
for _, r in sdf.iterrows():
    p(f"{r['tag']:<18}{int(r['n']):>7}{r['hit']:>8.3f}{r['mean']:>10.4f}"
      f"{r['nw_t']:>8.2f}{r['sharpe']:>9.2f}{r['ic15']:>+9.4f}")

# ── 2) 走前组合（权重只用历史）───────────────────────────────────
p("\n[2] 走前组合（每 1440 根重估权重，权重只用历史数据）")


def walk_forward_combine(method: str, rebal: int = REBAL,
                         min_train: int = MIN_TRAIN) -> np.ndarray:
    sig = np.full(n, np.nan)
    w_hist = []
    for t0 in range(min_train, n, rebal):
        t1 = min(t0 + rebal, n)
        Xtr, Xte = X[:t0], X[t0:t1]
        ytr = fwd15[:t0]
        mtr = np.isfinite(Xtr).all(axis=1) & np.isfinite(ytr)
        if mtr.sum() < 1000:
            continue
        A, y = Xtr[mtr], ytr[mtr]
        if method == "equal":
            w = np.ones(X.shape[1]) / X.shape[1]
        elif method == "ic":
            ics = np.array([spearman_ic(A[:, j], y) for j in range(A.shape[1])])
            ics = np.nan_to_num(ics, nan=0.0)
            w = ics / max(np.abs(ics).sum(), 1e-9)
        elif method == "invvol":
            sds = np.array([np.nanstd(A[:, j]) for j in range(A.shape[1])])
            iv = 1.0 / np.maximum(sds, 1e-9)
            w = iv / iv.sum()
        elif method == "ridge":
            lam = 100.0
            As = np.column_stack([np.ones(len(A)), A])
            G = As.T @ As + lam * np.eye(As.shape[1])
            G[0, 0] -= lam
            try:
                b = np.linalg.solve(G, As.T @ y)
            except np.linalg.LinAlgError:
                continue
            w = b[1:]
            w = w / max(np.abs(w).sum(), 1e-9)
        elif method == "pca":
            Ac = A - A.mean(axis=0)
            U, S, Vt = np.linalg.svd(Ac, full_matrices=False)
            k = min(3, Vt.shape[0])
            comp = Vt[:k]                        # k×p
            sc = Ac @ comp.T                     # 训练集成分
            cs = np.array([spearman_ic(sc[:, j], y) for j in range(k)])
            cs = np.nan_to_num(cs, nan=0.0)
            w = (cs / max(np.abs(cs).sum(), 1e-9)) @ comp
        else:
            w = np.ones(X.shape[1]) / X.shape[1]
        w_hist.append(w)
        Xte_f = np.nan_to_num(Xte, nan=0.0)
        sig[t0:t1] = Xte_f @ w
    return sig, np.array(w_hist)


results = {}
for method in ("equal", "ic", "invvol", "ridge", "pca"):
    sig, wh = walk_forward_combine(method)
    r = eval_signal(sig, method)
    r["weights"] = wh
    results[method] = r

p(f"{'组合方法':<14}{'笔数':>7}{'命中':>8}{'净均值':>10}{'NW-t':>8}{'年化SR':>9}"
  f"{'总盈亏':>11}{'IC15':>9}")
for method, r in sorted(results.items(), key=lambda kv: -kv[1].get("nw_t", -99)):
    if not r.get("valid"):
        p(f"{method:<14} 样本不足")
        continue
    p(f"{method:<14}{int(r['n']):>7}{r['hit']:>8.3f}{r['mean']:>10.4f}"
      f"{r['nw_t']:>8.2f}{r['sharpe']:>9.2f}{r['total']:>11.1f}{r['ic15']:>+9.4f}")

# ── 3) 元标注过滤器 ──────────────────────────────────────────────
p("\n[3] 元标注过滤器：二级模型只决定「做不做」（目标：提升精确率）")
best_method = max((m for m in results if results[m].get("valid")),
                  key=lambda m: results[m]["nw_t"], default="ic")
p(f"    以 {best_method} 组合作为一级信号")
sig1, wh1 = walk_forward_combine(best_method)

# 一级信号方向 + 三重障碍标签 → 元标签
sgn1 = np.sign(np.nan_to_num(sig1, nan=0.0))
tb1 = triple_barrier(close, high, low, vol, sgn1.astype(int), 2.0, 1.0, 60, COST)
ymeta = ((tb1.ret > 0) & (sgn1 != 0) & (tb1.bars_held > 0)).astype(int)

# 元特征：一级信号强度 + 状态模型（波动/流动性/regime/信息）
meta_feats, meta_names = [np.abs(sig1)], ["sig_strength"]
for nm in ("hmm_high_vol", "vol_regime_quantile", "jump_ratio", "vpin",
           "entropy", "kl_div", "ac_urgency", "evt_es", "ofi", "variance_ratio"):
    if nm in states:
        meta_feats.append(zscore(states[nm]))
        meta_names.append(nm)
Xm = np.column_stack(meta_feats)
p(f"    元特征 {len(meta_names)} 个: {meta_names}")

meta_prob = np.full(n, np.nan)
for t0 in range(MIN_TRAIN, n, REBAL):
    t1 = min(t0 + REBAL, n)
    A, y = Xm[:t0], ymeta[:t0]
    m = np.isfinite(A).all(axis=1) & (sgn1[:t0] != 0)
    if m.sum() < 800 or y[m].sum() < 50:
        continue
    Aa, ya = A[m], y[m]
    mu, sd = Aa.mean(axis=0), Aa.std(axis=0) + 1e-9
    As = np.column_stack([np.ones(len(Aa)), (Aa - mu) / sd])
    b = np.zeros(As.shape[1])
    lam = 10.0
    for _ in range(30):
        pr = 1 / (1 + np.exp(-np.clip(As @ b, -30, 30)))
        W = np.maximum(pr * (1 - pr), 1e-6)
        g = As.T @ (pr - ya) + lam * np.r_[0, b[1:]]
        H = (As * W[:, None]).T @ As + lam * np.eye(As.shape[1])
        H[0, 0] += 1e-8
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
        b -= step
        if np.abs(step).max() < 1e-6:
            break
    Xt = np.nan_to_num((Xm[t0:t1] - mu) / sd, nan=0.0)
    meta_prob[t0:t1] = 1 / (1 + np.exp(-np.clip(
        np.column_stack([np.ones(len(Xt)), Xt]) @ b, -30, 30)))

p(f"    元概率分布: mean={np.nanmean(meta_prob):.3f} "
  f"p25={np.nanpercentile(meta_prob,25):.3f} p75={np.nanpercentile(meta_prob,75):.3f}")

p(f"\n{'阈值':<10}{'笔数':>8}{'保留率':>9}{'命中':>8}{'净均值':>10}{'NW-t':>8}{'年化SR':>9}")
base_n = int(np.sum((sgn1 != 0) & (tb1.bars_held > 0)))
for thr in (0.0, 0.4, 0.5, 0.6, 0.7):
    gate = np.where(np.isfinite(meta_prob), meta_prob >= thr, thr == 0.0)
    sig2 = np.where(gate, sig1, 0.0)
    r = eval_signal(sig2, f"meta>={thr}")
    if not r.get("valid"):
        continue
    p(f"{thr:<10.1f}{int(r['n']):>8}{r['n']/max(base_n,1):>9.1%}{r['hit']:>8.3f}"
      f"{r['mean']:>10.4f}{r['nw_t']:>8.2f}{r['sharpe']:>9.2f}")

# ── 4) 误差分析 ──────────────────────────────────────────────────
p("\n[4] 误差分析：找出模型在什么条件下失效")
sgnb = np.sign(np.nan_to_num(sig1, nan=0.0))
mbase = (sgnb != 0) & np.isfinite(tb1.ret) & (tb1.bars_held > 0)
p(f"    基础样本 n={mbase.sum()}")

for sname in ("hmm_high_vol", "vol_regime_quantile", "jump_ratio", "entropy",
              "kl_div", "ac_urgency", "variance_ratio"):
    if sname not in states:
        continue
    v = states[sname]
    mv = mbase & np.isfinite(v)
    if mv.sum() < 300:
        continue
    q = pd.qcut(pd.Series(v[mv]), 4, labels=False, duplicates="drop")
    line = f"    {sname:<20}"
    for k in range(int(q.max()) + 1):
        idx = np.where(mv)[0][q == k]
        rr = tb1.ret[idx]
        line += f" Q{k+1}:{rr.mean():+.3f}(t={newey_west_t(rr,20):+.1f})"
    p(line)

# 时段
hour = df.time.dt.hour.to_numpy()
p(f"\n    {'UTC时段':<12}{'笔数':>7}{'净均值':>10}{'NW-t':>8}{'命中':>8}")
for h0 in range(0, 24, 3):
    mm = mbase & (hour >= h0) & (hour < h0 + 3)
    if mm.sum() < 100:
        continue
    rr = tb1.ret[mm]
    p(f"    {f'{h0:02d}-{h0+3:02d}h':<12}{mm.sum():>7}{rr.mean():>10.4f}"
      f"{newey_west_t(rr,20):>8.2f}{np.mean(rr>0):>8.3f}")

# 信号强度分档
p(f"\n    {'|信号|分档':<12}{'笔数':>7}{'净均值':>10}{'NW-t':>8}{'命中':>8}")
av = np.abs(sig1)
for lo, hi in ((0, .5), (.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 99)):
    mm = mbase & (av >= lo) & (av < hi)
    if mm.sum() < 100:
        continue
    rr = tb1.ret[mm]
    p(f"    {f'[{lo},{hi})':<12}{mm.sum():>7}{rr.mean():>10.4f}"
      f"{newey_west_t(rr,20):>8.2f}{np.mean(rr>0):>8.3f}")

# ── 5) Purged K-Fold 与 DSR ──────────────────────────────────────
p("\n[5] 稳健性：Purged K-Fold + Deflated Sharpe")
folds = purged_kfold_indices(tb1.t1, n_splits=5, embargo_pct=0.01)
p(f"    Purged K-Fold 5 折（embargo 1%）")
p(f"    {'折':<5}{'训练n':>9}{'测试n':>9}{'测试净均值':>13}{'测试NW-t':>11}")
for i, (tr, te) in enumerate(folds):
    mm = np.isin(np.arange(n), te) & mbase
    if mm.sum() < 50:
        p(f"    {i:<5}{len(tr):>9}{len(te):>9}   样本不足")
        continue
    rr = tb1.ret[mm]
    p(f"    {i:<5}{len(tr):>9}{len(te):>9}{rr.mean():>13.4f}"
      f"{newey_west_t(rr,20):>11.2f}")

r_best = results[best_method]
if r_best.get("valid"):
    N = len(names) * 5 + 6      # 试验族：单模型 + 5 种组合 + 元标注阈值
    dsr, sr0 = deflated_sharpe(r_best["mean"] / max(r_best["std"], 1e-12), N,
                               int(r_best["n"]), r_best["skew"], r_best["kurt"])
    p(f"\n    最优组合 = {best_method}  试验族 N={N}")
    p(f"    样本内年化 Sharpe = {r_best['sharpe']:.2f}")
    p(f"    噪声下期望最大年化 Sharpe = {sr0*np.sqrt(1440*252/max(r_best['avg_bars'],1)):.2f}")
    p(f"    Deflated Sharpe Ratio = {dsr:.3f} → "
      f"{'通过' if dsr > 0.95 else '未通过'}（阈值 0.95）")

# ── 6) 权重稳定性 ────────────────────────────────────────────────
p("\n[6] 走前权重的稳定性（权重乱跳 = 过拟合信号）")
wh = results[best_method].get("weights")
if wh is not None and len(wh) > 1:
    p(f"    {'模型':<18}{'均值':>10}{'标准差':>10}{'符号翻转率':>12}")
    for j, nm in enumerate(names):
        wj = wh[:, j]
        flips = np.mean(np.sign(wj[1:]) != np.sign(wj[:-1])) if len(wj) > 1 else 0
        p(f"    {nm:<18}{wj.mean():>+10.4f}{wj.std():>10.4f}{flips:>12.1%}")

(RES / f"07_combine_{TF}.txt").write_text("\n".join(OUT), encoding="utf-8")
p(f"\n[已写入 research/07_combine_{TF}.txt]")
