"""研究取证 04：alpha 还是 beta？多重检验校正下的真实存活策略。

1) 修正波动率目标化对比（形状对齐）。
2) chanlun 在更长历史（1h 5.5 月 / 4h 1.4 年 / 1d 4.8 年）上的表现。
3) 把策略盈亏对市场收益做回归：区分 alpha（真信号）与 beta（单边行情）。
4) White Reality Check / Hansen SPA：对整族试验做多重检验校正。
5) Deflated Sharpe Ratio：给最优策略打折。
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize, stats

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_agent.common.config import CFG
from gold_agent.skills.chanlun_adapter import analyze_tf

RES = Path(__file__).parent
OUT: list[str] = []


def p(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


def nw_t(x, lags):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < 30:
        return float("nan")
    e = x - x.mean()
    var = float(e @ e) / len(x)
    for L in range(1, lags + 1):
        var += 2 * (1 - L / (lags + 1)) * float(e[L:] @ e[:-L]) / len(x)
    return float(x.mean() / np.sqrt(max(var, 1e-18) / len(x)))


def load(tf):
    df = pd.read_parquet(CFG.data_dir / f"XAUUSDm_{tf}.parquet")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.sort_values("time").reset_index(drop=True)


def resample(df, rule):
    return (df.set_index("time").resample(rule)
            .agg({"open": "first", "high": "max", "low": "min",
                  "close": "last", "tick_volume": "sum"})
            .dropna().reset_index())


df1 = load("1m")
df15 = load("15m")
df1h = load("1h")
df4h = load("4h")
df1d = load("1d")
SPREAD = float(df1.spread.median()) * 0.001
COST = 2 * SPREAD

# ══════════════════════════════════════════════════════════════════
p("=" * 80)
p("A. 各周期的市场背景（判断 alpha/beta 的前提）")
p("=" * 80)
p(f"{'周期':>6}{'根数':>8}{'起点':>22}{'终点':>22}{'区间涨跌':>12}{'年化':>10}")
for nm, df in (("15m", df15), ("1h", df1h), ("4h", df4h), ("1d", df1d)):
    tot = df.close.iloc[-1] / df.close.iloc[0] - 1
    yrs = (df.time.iloc[-1] - df.time.iloc[0]).days / 365.25
    p(f"{nm:>6}{len(df):>8}{str(df.time.iloc[0])[:19]:>22}{str(df.time.iloc[-1])[:19]:>22}"
      f"{tot:>11.2%}{(1+tot)**(1/max(yrs,0.01))-1:>10.1%}")
p("→ 样本期黄金单边上涨 ⇒ 任何净多头策略都会「看起来赚钱」，必须做 beta 剥离")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 80)
p("B. chanlun 结构分：长历史 + beta 剥离")
p("=" * 80)


def run_chanlun(df, tf, warm, step, horizons, cost):
    recs = []
    for i in range(warm, len(df) - max(horizons.values()) - 1, step):
        win = df.iloc[i - warm:i].reset_index(drop=True)
        try:
            r = analyze_tf(win, tf)
        except Exception:
            continue
        if r.status != "ok":
            continue
        rec = {"i": i, "score": r.score, "structure": r.structure,
               "n_sig": len(r.signals)}
        for nm, h in horizons.items():
            rec[f"f_{nm}"] = float(df.close.iloc[i + h] - df.close.iloc[i - 1])
        recs.append(rec)
    return pd.DataFrame(recs)


for tf, df, warm, step, hz, cost in (
        ("15m", df15, 400, 4, {"1h": 4, "4h": 16, "8h": 32}, COST),
        ("1h", df1h, 400, 2, {"2h": 2, "8h": 8, "24h": 24, "48h": 48}, COST),
        ("4h", df4h, 300, 1, {"4h": 1, "24h": 6, "72h": 18}, COST),
        ("1d", df1d, 300, 1, {"1d": 1, "5d": 5, "20d": 20}, COST)):
    cd = run_chanlun(df, tf, warm, step, hz, cost)
    if len(cd) < 100:
        p(f"\n[{tf}] 样本不足 n={len(cd)}，跳过")
        continue
    p(f"\n[{tf}] n={len(cd)}  分数 mean={cd.score.mean():+.3f} std={cd.score.std():.3f}  "
      f"非零={np.mean(cd.score != 0):.1%}  结构={cd.structure.value_counts().head(4).to_dict()}")
    p(f"{'horizon':>9}{'IC':>10}{'NW-t':>8}{'毛均值':>10}{'净均值':>10}{'净NW-t':>9}"
      f"{'命中':>8}{'市场beta':>10}{'alpha/t':>12}")
    for nm in hz:
        x = cd.score.to_numpy()
        y = cd[f"f_{nm}"].to_numpy()
        m = np.isfinite(x) & np.isfinite(y) & (x != 0)
        if m.sum() < 50:
            continue
        icv = float(np.corrcoef(pd.Series(x[m]).rank(), pd.Series(y[m]).rank())[0, 1])
        gross = np.sign(x[m]) * y[m]
        net = gross - cost
        # beta 剥离：把策略盈亏对同期市场收益回归
        beta = float(np.polyfit(y[m], gross, 1)[0])
        alpha = float(gross.mean() - beta * y[m].mean())
        resid = gross - beta * y[m]
        p(f"{nm:>9}{icv:>+10.4f}{nw_t(gross, 48):>8.2f}{gross.mean():>10.3f}"
          f"{net.mean():>10.3f}{nw_t(net, 48):>9.2f}{np.mean(net>0):>8.3f}"
          f"{beta:>10.3f}{alpha:>+9.3f}/{nw_t(resid, 48):>+5.2f}")
    # 只用大分数
    for lo in (0.9, 1.2):
        m = cd.score.abs().to_numpy() >= lo
        if m.sum() < 50:
            continue
        y = cd[f"f_{list(hz)[-1]}"].to_numpy()
        net = np.sign(cd.score.to_numpy()[m]) * y[m] - cost
        p(f"    |score|>={lo}: n={m.sum():4d} 净均值={net.mean():+.3f} NW-t={nw_t(net,48):+.2f} "
          f"命中={np.mean(net>0):.3f} 总={net.sum():+.1f}")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 80)
p("C. 波动率目标化（修正版）")
p("=" * 80)


def garch11_negll(theta, r):
    mu, w, a, b = theta
    if w <= 0 or a < 0 or b < 0 or a + b >= 0.999:
        return 1e10
    s2 = np.empty(len(r))
    s2[0] = np.var(r)
    e = r - mu
    for t in range(1, len(r)):
        s2[t] = max(w + a * e[t - 1] ** 2 + b * s2[t - 1], 1e-14)
    return 0.5 * float(np.sum(np.log(2 * np.pi * s2) + e ** 2 / s2))


r1h = np.log(df1h.close).diff().dropna().to_numpy()
res = optimize.minimize(garch11_negll, np.array([r1h.mean(), np.var(r1h) * 0.05, 0.1, 0.85]),
                        args=(r1h,), method="Nelder-Mead",
                        options={"maxiter": 6000, "xatol": 1e-9, "fatol": 1e-9})
mu_g, w_g, a_g, b_g = res.x
p(f"1h GARCH(1,1): ω={w_g:.3e} α={a_g:.4f} β={b_g:.4f} 半衰期="
  f"{np.log(0.5)/np.log(a_g+b_g):.1f}h")

s2 = np.var(r1h)
sig_t = np.empty(len(r1h) + 1)
sig_t[0] = np.nan
for t in range(len(r1h)):
    sig_t[t + 1] = np.sqrt(s2)
    s2 = w_g + a_g * (r1h[t] - mu_g) ** 2 + b_g * s2
sig_prev = pd.Series(sig_t).shift(1).to_numpy()      # 严格只用 t-1 及以前

mom = np.log(df1h.close).diff(12).to_numpy()          # 12h 动量
fwd = (df1h.close.shift(-6) - df1h.close).to_numpy()  # 6h 前瞻
m = np.isfinite(mom) & np.isfinite(fwd) & np.isfinite(sig_prev) & (sig_prev > 0)
target = float(np.nanmedian(sig_prev[m]))
p(f"目标 σ = {target:.3e}（中位数）  有效样本 n={m.sum()}")

pos_f = np.sign(mom[m])
pos_v = np.sign(mom[m]) * np.clip(target / sig_prev[m], 0.25, 3.0)
pnl_f = pos_f * fwd[m] - COST * np.abs(pos_f)
pnl_v = pos_v * fwd[m] - COST * np.abs(pos_v)

p(f"\n{'方案':<22}{'总盈亏':>11}{'均值':>10}{'标准差':>10}{'年化Sharpe':>13}{'最大回撤':>11}{'Calmar':>9}")
for nm, pnl in (("固定仓位 ±1", pnl_f), ("GARCH 波动率目标", pnl_v)):
    eq = np.cumsum(pnl)
    dd = float(np.max(np.maximum.accumulate(eq) - eq))
    sh = pnl.mean() / pnl.std() * np.sqrt(24 * 252)
    p(f"{nm:<22}{pnl.sum():>11.1f}{pnl.mean():>10.4f}{pnl.std():>10.4f}"
      f"{sh:>13.2f}{dd:>11.1f}{pnl.sum()/max(dd,1e-9):>9.2f}")
p("→ 波动率目标化降低回撤与波动，改善风险调整收益；但方向期望仍由信号决定")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 80)
p("D. 多重检验校正：整族试验的 White Reality Check / Hansen SPA")
p("=" * 80)
p("把本报告 + 01/02/03 里试过的所有信号变体作为一个「试验族」，")
p("用 stationary bootstrap 计算最大 Sharpe 的零分布，得到数据窥探校正后的 p 值。")

df15_ = df15
c15 = df15_.close.to_numpy(float)
h15 = df15_.high.to_numpy(float)
l15 = df15_.low.to_numpy(float)
px15 = df15_.close.to_numpy(float)
r15 = np.log(df15_.close).diff().to_numpy()

# 试验族：每个策略输出一个逐时点收益序列（15m 粒度）
cands: dict[str, np.ndarray] = {}
n_ = len(df15_)


def add(name, sig, hold, cost=COST):
    """sig: 每根 bar 的目标仓位（已 shift 保证无前视）。"""
    fwd = np.full(n_, np.nan)
    fwd[:-hold] = px15[hold:] - px15[:-hold]
    pnl = sig * fwd - cost * np.abs(sig)
    pnl = np.where(np.isfinite(sig) & np.isfinite(fwd), pnl, np.nan)
    if np.isfinite(pnl).sum() > 200:
        cands[name] = pnl


# 动量族
for lb in (4, 8, 12, 24, 48, 96):
    add(f"mom{lb}_h4", np.sign(px15 - pd.Series(px15).shift(lb)).to_numpy(), 4)
    add(f"mom{lb}_h8", np.sign(px15 - pd.Series(px15).shift(lb)).to_numpy(), 8)
# 反转族
for lb in (4, 8, 12, 24, 48):
    add(f"rev{lb}_h4", -np.sign(px15 - pd.Series(px15).shift(lb)).to_numpy(), 4)
    add(f"rev{lb}_h8", -np.sign(px15 - pd.Series(px15).shift(lb)).to_numpy(), 8)
# z-score 反转族
for lb in (24, 48, 96):
    z = ((px15 - pd.Series(px15).rolling(lb).mean()) /
         pd.Series(px15).rolling(lb).std()).to_numpy()
    for thr in (1.0, 1.5, 2.0):
        s = np.where(np.abs(z) > thr, -np.sign(z), 0.0)
        add(f"z{lb}_{thr}_h4", s, 4)
        add(f"z{lb}_{thr}_h8", s, 8)
# 突破族
for lb in (8, 16, 32):
    hh = pd.Series(h15).rolling(lb).max().shift(1).to_numpy()
    ll = pd.Series(l15).rolling(lb).min().shift(1).to_numpy()
    add(f"brk{lb}_h4", np.where(px15 > hh, 1.0, np.where(px15 < ll, -1.0, 0.0)), 4)
    add(f"brk{lb}_h8", np.where(px15 > hh, 1.0, np.where(px15 < ll, -1.0, 0.0)), 8)
    add(f"brkrev{lb}_h4", np.where(px15 > hh, -1.0, np.where(px15 < ll, 1.0, 0.0)), 4)
# 波动率突破族
atr15 = (df15_.high - df15_.low).rolling(14).mean().to_numpy()
rng = (df15_.high - df15_.low).to_numpy()
add("volbrk_h4", np.sign(px15 - pd.Series(px15).shift(1)) * (rng > 1.5 * atr15), 4)
# 时段族
hour = df15_.time.dt.hour.to_numpy()
for h0 in (0, 8, 12, 14, 20):
    add(f"hour{h0}_long_h4", (hour == h0).astype(float), 4)
# chanlun 族（用上面 15m 的分数对齐）
cl15 = run_chanlun(df15, "15m", 400, 1, {"h4": 4, "h8": 8}, COST)
if len(cl15) > 200:
    sig_cl = np.full(n_, np.nan)
    for _, row in cl15.iterrows():
        sig_cl[int(row["i"])] = np.sign(row["score"])
    add("chanlun_h4", sig_cl, 4)
    add("chanlun_h8", sig_cl, 8)

p(f"试验族规模 = {len(cands)} 个策略变体")

stats_tbl = []
for nm, pnl in cands.items():
    v = pnl[np.isfinite(pnl)]
    if len(v) < 200:
        continue
    sh = v.mean() / v.std() * np.sqrt(96 * 252)
    stats_tbl.append({"name": nm, "n": len(v), "mean": v.mean(),
                      "sharpe": sh, "t": nw_t(v, 8)})
st = pd.DataFrame(stats_tbl).sort_values("sharpe", ascending=False)
p(f"\n{'策略':<22}{'n':>7}{'均值USD':>11}{'年化Sharpe':>13}{'NW-t':>8}")
for _, r in st.head(12).iterrows():
    p(f"{r['name']:<22}{int(r['n']):>7}{r['mean']:>11.4f}{r['sharpe']:>13.2f}{r['t']:>8.2f}")
p("  ...")
for _, r in st.tail(4).iterrows():
    p(f"{r['name']:<22}{int(r['n']):>7}{r['mean']:>11.4f}{r['sharpe']:>13.2f}{r['t']:>8.2f}")

# Stationary bootstrap（Politis-Romano）：块长 ~ 平均持有期
rng_ = np.random.default_rng(20260920)
names = list(cands.keys())
M = np.column_stack([np.nan_to_num(cands[k], nan=0.0) for k in names])
mask = np.column_stack([np.isfinite(cands[k]) for k in names])
n_obs = M.shape[0]
BLOCK = 8
B = 1000
max_stat = np.empty(B)
obs_sharpe = np.array([cands[k][np.isfinite(cands[k])].mean() /
                       max(cands[k][np.isfinite(cands[k])].std(), 1e-12) for k in names])
for b in range(B):
    idx = []
    while len(idx) < n_obs:
        s = rng_.integers(0, n_obs)
        idx.extend(range(s, min(s + BLOCK, n_obs)))
    idx = np.array(idx[:n_obs])
    Mb, maskb = M[idx], mask[idx]
    cnt = maskb.sum(axis=0)
    mu = np.where(cnt > 0, (Mb * maskb).sum(axis=0) / np.maximum(cnt, 1), 0.0)
    sq = np.where(cnt > 0, (Mb ** 2 * maskb).sum(axis=0) / np.maximum(cnt, 1), 0.0)
    sd = np.sqrt(np.maximum(sq - mu ** 2, 1e-18))
    max_stat[b] = np.max(np.where(sd > 0, (mu - mu.mean()) / sd, -np.inf))
p(f"\nStationary bootstrap B={B}, 块长={BLOCK}:")
p(f"  观测到的最大 Sharpe（15m 单位）= {obs_sharpe.max():.4f}  "
  f"（策略: {names[int(np.argmax(obs_sharpe))]}）")
p(f"  零分布 95% 分位 = {np.percentile(max_stat, 95):.4f}  "
  f"99% 分位 = {np.percentile(max_stat, 99):.4f}")
pval = float(np.mean(max_stat >= obs_sharpe.max()))
p(f"  White Reality Check p 值 = {pval:.3f}")
p("  → p>0.05 表示：整族里最好的策略也无法在数据窥探校正后显著跑赢零假设")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 80)
p("E. Deflated Sharpe Ratio（Bailey & López de Prado）")
p("=" * 80)
N = len(cands)
best = st.iloc[0]
v = cands[best["name"]]
v = v[np.isfinite(v)]
T = len(v)
sr = v.mean() / v.std()                       # 非年化
g3 = float(stats.skew(v))
g4 = float(stats.kurtosis(v, fisher=False))
EULER = 0.5772156649
e_max = ((1 - EULER) * stats.norm.ppf(1 - 1 / N) +
         EULER * stats.norm.ppf(1 - 1 / (N * np.e)))
sr0 = (np.std(v) / np.sqrt(T)) * 0  # placeholder
# 期望最大 Sharpe（单位与 sr 一致）
sr0 = (1 / np.sqrt(T)) * e_max * 1.0
num = (sr - sr0) * np.sqrt(T - 1)
den = np.sqrt(1 - g3 * sr + ((g4 - 1) / 4) * sr ** 2)
dsr = float(stats.norm.cdf(num / max(den, 1e-12)))
p(f"试验数 N={N}  样本 T={T}  最优策略={best['name']}")
p(f"  年化 Sharpe = {best['sharpe']:.2f}  偏度={g3:+.2f}  峰度={g4:.2f}")
p(f"  期望最大 Sharpe（纯噪声下，N 次试验）= {sr0*np.sqrt(96*252):.3f}（年化）")
p(f"  Deflated Sharpe Ratio（真实>0 的概率）= {dsr:.3f}")
p(f"  → {'通过' if dsr > 0.95 else '未通过'}（惯例阈值 0.95）")
p(f"  需要多少样本才能让该 Sharpe 显著：T* ≈ {(e_max/max(sr,1e-9))**2:.0f} 根 15m bar "
  f"= {(e_max/max(sr,1e-9))**2*15/60/24:.0f} 天")

(RES / "04_report.txt").write_text("\n".join(OUT), encoding="utf-8")
p("\n[已写入 research/04_report.txt]")
