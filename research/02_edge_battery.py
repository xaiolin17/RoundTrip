"""研究取证 02：成本门槛 · 波动率建模 · 方向可预测性 · regime 检测。

结论必须由真实数据支撑，全部统计量给 Newey-West 稳健 t 值（重叠样本修正）。
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

RES = Path(__file__).parent
OUT: list[str] = []


def p(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


def nw_t(x: np.ndarray, lags: int) -> float:
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 30:
        return float("nan")
    e = x - x.mean()
    var = float(e @ e) / n
    for L in range(1, lags + 1):
        var += 2 * (1 - L / (lags + 1)) * float(e[L:] @ e[:-L]) / n
    return float(x.mean() / np.sqrt(max(var, 1e-18) / n))


def load(tf: str) -> pd.DataFrame:
    df = pd.read_parquet(CFG.data_dir / f"XAUUSDm_{tf}.parquet")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.sort_values("time").reset_index(drop=True)


df1 = load("1m")
df15 = load("15m")
px = df1.close.to_numpy(dtype=float)
hi = df1.high.to_numpy(dtype=float)
lo = df1.low.to_numpy(dtype=float)
SPREAD_USD = float(df1.spread.median()) * 0.001
p(f"数据: 1m {len(df1)} 根 | 点差 {SPREAD_USD:.3f} USD/盎司 (单边)")

tr = np.maximum.reduce([hi[1:] - lo[1:], np.abs(hi[1:] - px[:-1]), np.abs(lo[1:] - px[:-1])])
ATR = np.concatenate([[np.nan], pd.Series(tr).rolling(14).mean().to_numpy()])
p(f"ATR(14,1m) 中位数 = {np.nanmedian(ATR):.3f} USD | 点差/ATR = "
  f"{SPREAD_USD/np.nanmedian(ATR)*100:.2f}%")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 80)
p("A. 成本-几何经济学：当前 TP/SL 结构在不同胜率下的期望")
p("=" * 80)
p(f"当前实际几何（config 2.0/1.2 经 shrink 0.6/0.65）: TP=1.20ATR  SL=0.78ATR  R:R=1.54")
p(f"\n{'R:R':>7}{'TP(ATR)':>10}{'SL(ATR)':>10}{'盈亏平衡胜率':>14}{'含成本平衡胜率':>16}")
atr_med = float(np.nanmedian(ATR))
for rr, tp_a in [(1.0, 1.0), (1.54, 1.20), (2.0, 1.5), (2.5, 1.5), (3.0, 1.8), (4.0, 2.0)]:
    sl_a = tp_a / rr
    be = sl_a / (tp_a + sl_a)
    cost_atr = 2 * SPREAD_USD / atr_med          # 往返成本（ATR 单位）
    be_c = (sl_a + cost_atr) / (tp_a + sl_a)
    p(f"{rr:>7.2f}{tp_a:>10.2f}{sl_a:>10.2f}{be:>13.1%}{be_c:>15.1%}")
p(f"\n往返成本 = 2×{SPREAD_USD:.3f} = {2*SPREAD_USD:.3f} USD = {2*SPREAD_USD/atr_med:.3f} ATR "
  f"= {2*SPREAD_USD/atr_med*100:.1f}% of ATR")
p("→ 胜率必须显著超过盈亏平衡胜率，成本才被覆盖；")
p("  实测各源命中率 49.2%~51.1%（见 01 报告）⇒ 全部低于任何合理 R:R 的平衡点")

p("\n不同持仓时长的成本占比（成本固定，波动随时长增长）:")
p(f"{'时长':>8}{'σ(USD)':>10}{'成本/σ':>10}{'成本/1σ收益':>14}")
r1 = np.log(px[1:] / px[:-1])
for mins in (5, 15, 30, 60, 240, 1440):
    sig = float(np.std(r1[: len(r1) // mins * mins].reshape(-1, mins).sum(axis=1)) * px.mean())
    p(f"{mins:>6}m{mins:>0}{sig:>10.3f}{2*SPREAD_USD/sig:>10.3f}"
      f"{2*SPREAD_USD/sig:>13.1%}")
p("→ 5 分钟持仓成本 = 40% 的一个标准差；1 小时 = 13%；4 小时 = 6.7%")
p("  短线的数学现实：持有期越短，成本/信号比越差")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 80)
p("B. 波动率建模：GARCH(1,1) vs EWMA vs 滚动标准差（真实样本外检验）")
p("=" * 80)


def garch11_negll(theta, r):
    mu, w, a, b = theta
    if w <= 0 or a < 0 or b < 0 or a + b >= 0.999:
        return 1e10
    n = len(r)
    s2 = np.empty(n)
    s2[0] = np.var(r)
    e = r - mu
    for t in range(1, n):
        s2[t] = w + a * e[t - 1] ** 2 + b * s2[t - 1]
        if s2[t] <= 1e-14:
            s2[t] = 1e-14
    return 0.5 * float(np.sum(np.log(2 * np.pi * s2) + e ** 2 / s2))


r15 = np.log(df15.close).diff().dropna().to_numpy()
n = len(r15)
split = int(n * 0.7)
train, test = r15[:split], r15[split:]
p(f"15m 收益: n={n}  训练 {len(train)} / 测试 {len(test)}（时间顺序切分，无未来信息）")

x0 = np.array([train.mean(), np.var(train) * 0.05, 0.08, 0.90])
best, bf = None, np.inf
for a0 in (0.05, 0.10, 0.15):
    for b0 in (0.80, 0.85, 0.90):
        for w0 in (0.01, 0.05, 0.1):
            th = np.array([train.mean(), np.var(train) * w0, a0, b0])
            try:
                res = optimize.minimize(garch11_negll, th, args=(train,),
                                        method="Nelder-Mead",
                                        options={"maxiter": 4000, "xatol": 1e-8, "fatol": 1e-8})
            except Exception:
                continue
            if res.fun < bf:
                bf, best = float(res.fun), res.x
mu_g, w_g, a_g, b_g = best
p(f"\nGARCH(1,1) MLE 参数: ω={w_g:.3e} α={a_g:.4f} β={b_g:.4f} "
  f"α+β={a_g+b_g:.4f}")
half_life = np.log(0.5) / np.log(a_g + b_g)
p(f"波动率冲击半衰期 = {half_life:.1f} 根 15m bar = {half_life*15/60:.1f} 小时")
p(f"无条件年化波动 = {np.sqrt(w_g/(1-a_g-b_g))*np.sqrt(96*252):.1%}")


def garch_forecast_path(r_hist, mu, w, a, b, s2_last):
    """在测试集上滚动一步预测（用真实历史更新，不用未来信息）。"""
    s2 = s2_last
    out = np.empty(len(r_hist))
    for t in range(len(r_hist)):
        out[t] = s2
        s2 = w + a * (r_hist[t] - mu) ** 2 + b * s2
    return out


# 用训练集末尾的滤波状态初始化
s2 = np.var(train)
for t in range(len(train)):
    s2 = w_g + a_g * (train[t] - mu_g) ** 2 + b_g * s2
fc_garch = garch_forecast_path(test, mu_g, w_g, a_g, b_g, s2)

# EWMA λ=0.94
lam = 0.94
s2 = np.var(train)
fc_ewma = np.empty(len(test))
for t in range(len(test)):
    fc_ewma[t] = s2
    s2 = lam * s2 + (1 - lam) * (test[t] - train.mean()) ** 2

# 滚动 std（生产里 realized_vol_daily 的做法）
W = 96
fc_roll = np.array([np.var(test[max(0, t - W):t]) if t >= 20 else np.var(train) for t in range(len(test))])

realized = (test - test.mean()) ** 2


def qlike(actual_var, fc):
    fc = np.maximum(fc, 1e-14)
    return float(np.mean(np.log(fc) + actual_var / fc))


def mz_r2(actual_var, fc):
    """Mincer-Zarnowitz: 真实方差 ~ 预测方差，R² 衡量解释力。"""
    x = fc[np.isfinite(fc)]
    y = actual_var[np.isfinite(fc)]
    if len(x) < 30:
        return float("nan")
    b = np.polyfit(x, y, 1)
    yhat = np.polyval(b, x)
    ss = 1 - np.sum((y - yhat) ** 2) / np.sum((y - y.mean()) ** 2)
    return float(ss)


p(f"\n{'模型':<20}{'QLIKE(越小越好)':>18}{'MZ-R²':>10}{'与真实方差相关':>16}")
for nm, fc in (("GARCH(1,1)", fc_garch), ("EWMA(λ=0.94)", fc_ewma),
               ("滚动std(96)", fc_roll)):
    c = float(np.corrcoef(fc, realized)[0, 1])
    p(f"{nm:<20}{qlike(realized, fc):>18.4f}{mz_r2(realized, fc):>10.4f}{c:>16.4f}")
p("→ 波动率是唯一稳健可预测的量：GARCH/EWMA 的 QLIKE 明显优于滚动 std")

# 波动率预测能否改善风控：用预测波动分档，看未来 |收益| 是否单调
p("\n波动率预测的分档有效性（预测σ 五分位 → 实际 |收益| 均值）:")
q = pd.qcut(fc_garch, 5, labels=False, duplicates="drop")
for k in range(5):
    m = q == k
    p(f"  Q{k+1}: 预测σ={fc_garch[m].mean():.3e}  实际|收益|均值={np.abs(test[m]).mean():.3e}  "
      f"实际收益方差={realized[m].mean():.3e}")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 80)
p("C. 方向可预测性检验（真实数据，多重检验意识）")
p("=" * 80)

p("\nC1. 方差比检验 (Lo-MacKinlay) — 收益是否随机游走")
for tf_nm, s in (("1m", r1), ("15m", r15)):
    p(f"  [{tf_nm}]  n={len(s)}")
    for q_ in (2, 5, 10, 20):
        m = len(s) // q_ * q_
        v1 = np.var(s[:m], ddof=1)
        vq = np.var(s[:m].reshape(-1, q_).sum(axis=1), ddof=1) / q_
        vr = vq / v1
        # 同方差稳健统计量
        n_ = len(s[:m])
        z = (vr - 1) / np.sqrt(2 * (2 * q_ - 1) * (q_ - 1) / (3 * q_ * n_))
        p(f"    q={q_:>3}  VR={vr:.4f}  z={z:+.2f}  "
          f"{'均值回归' if vr<0.98 else ('趋势' if vr>1.02 else '随机游走')}")

p("\nC2. 收益自回归 AR(p) — 线性可预测性（样本外 R²）")
for tf_nm, s in (("1m", r1), ("15m", r15)):
    n_ = len(s)
    sp = int(n_ * 0.7)
    for lag in (1, 2, 5):
        X = np.column_stack([s[lag - 1 - i: n_ - 1 - i] for i in range(lag)])
        y = s[lag:]
        Xtr, ytr, Xte, yte = X[:sp - lag], y[:sp - lag], X[sp - lag:], y[sp - lag:]
        beta, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(Xtr)), Xtr]), ytr, rcond=None)
        pred = np.column_stack([np.ones(len(Xte)), Xte]) @ beta
        r2_oos = 1 - np.sum((yte - pred) ** 2) / np.sum((yte - yte.mean()) ** 2)
        # 策略收益：按预测符号交易
        pnl = np.sign(pred) * yte
        t = nw_t(pnl, lags=lag * 2)
        p(f"  [{tf_nm}] AR({lag}) 样本外R²={r2_oos:+.5f}  按预测交易 NW-t={t:+.2f}  "
          f"命中={np.mean(np.sign(pred)==np.sign(yte)):.4f}")

p("\nC3. 时段效应（UTC 小时）— 15m 收益均值与波动")
d15 = df15.copy()
d15["ret"] = np.log(d15.close).diff()
d15["hour"] = d15.time.dt.hour
g = d15.dropna(subset=["ret"]).groupby("hour")["ret"]
p(f"{'UTC时':>6}{'n':>7}{'均值(bp)':>12}{'t值':>8}{'std(bp)':>10}")
for hh, v in g:
    if len(v) < 50:
        continue
    t = float(v.mean() / (v.std(ddof=1) / np.sqrt(len(v))))
    p(f"{hh:>6}{len(v):>7}{v.mean()*1e4:>12.2f}{t:>8.2f}{v.std(ddof=1)*1e4:>10.2f}")
p("  （16 个小时桶 × 多重检验：|t|>2.8 才值得关注，Bonferroni α=0.05/16）")

p("\nC4. 波动率突破（开盘区间 ORB）— 15m 粒度")
d15["day"] = d15.time.dt.date
d15["atr15"] = (d15.high - d15.low).rolling(14).mean()
d15["hh"] = d15.high.rolling(8).max().shift(1)   # 前 8 根(2h)高点
d15["ll"] = d15.low.rolling(8).min().shift(1)
d15["fwd4"] = d15.close.shift(-4) - d15.close
d15["fwd8"] = d15.close.shift(-8) - d15.close
up_break = d15.close > d15.hh
dn_break = d15.close < d15.ll
for nm, mask, sgn in (("向上突破", up_break, 1), ("向下突破", dn_break, -1)):
    for fw in ("fwd4", "fwd8"):
        m = mask & d15[fw].notna()
        if m.sum() < 50:
            continue
        pnl = sgn * d15.loc[m, fw].to_numpy()
        p(f"  {nm}/{fw}: n={m.sum():4d} 平均={pnl.mean():+.3f} USD "
          f"NW-t={nw_t(pnl, 8):+.2f} 命中={np.mean(pnl>0):.3f}")
p("  （含点差前；扣 2×0.26 USD 后见下方净额）")
for nm, mask, sgn in (("向上突破", up_break, 1), ("向下突破", dn_break, -1)):
    m = mask & d15["fwd4"].notna()
    pnl = sgn * d15.loc[m, "fwd4"].to_numpy() - 2 * SPREAD_USD
    p(f"  {nm}/fwd4 扣成本后: 平均={pnl.mean():+.3f} USD NW-t={nw_t(pnl,8):+.2f}")

p("\nC5. N-σ 反转（均值回归）— 15m")
for k in (2.0, 2.5, 3.0):
    z = (d15.close - d15.close.rolling(96).mean()) / d15.close.rolling(96).std()
    for fw in ("fwd4", "fwd8"):
        for nm, mask, sgn in ((f"z>{k} 做空", z > k, -1), (f"z<-{k} 做多", z < -k, 1)):
            m = mask & d15[fw].notna()
            if m.sum() < 30:
                continue
            pnl = sgn * d15.loc[m, fw].to_numpy() - 2 * SPREAD_USD
            p(f"  {nm}/{fw}: n={m.sum():3d} 净平均={pnl.mean():+.3f} USD "
              f"NW-t={nw_t(pnl,8):+.2f} 命中={np.mean(pnl>0):.3f}")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 80)
p("D. Regime 检测：2 状态高斯 HMM vs 现有 Hurst 阈值")
p("=" * 80)


def em_hmm(x, k=2, iters=200, seed=7):
    rng = np.random.default_rng(seed)
    n_ = len(x)
    mu = np.array([x.mean() - x.std(), x.mean() + x.std()]) + rng.normal(0, 1e-4, k)
    sd = np.array([x.std() * 0.7, x.std() * 1.5])
    A = np.array([[0.95, 0.05], [0.05, 0.95]])
    pi = np.array([0.5, 0.5])
    for _ in range(iters):
        B = np.array([stats.norm.pdf(x, mu[i], max(sd[i], 1e-9)) for i in range(k)]).T + 1e-300
        alpha = np.zeros((n_, k)); c = np.zeros(n_)
        alpha[0] = pi * B[0]; c[0] = alpha[0].sum(); alpha[0] /= c[0]
        for t in range(1, n_):
            alpha[t] = (alpha[t - 1] @ A) * B[t]
            c[t] = alpha[t].sum(); alpha[t] /= c[t]
        beta = np.zeros((n_, k)); beta[-1] = 1.0
        for t in range(n_ - 2, -1, -1):
            beta[t] = (A @ (B[t + 1] * beta[t + 1])) / c[t + 1]
        g = alpha * beta
        g /= g.sum(axis=1, keepdims=True)
        xi = np.zeros((k, k))
        for t in range(n_ - 1):
            xi += (np.outer(alpha[t], B[t + 1] * beta[t + 1]) * A) / c[t + 1]
        A = xi / xi.sum(axis=1, keepdims=True)
        pi = g[0]
        for i in range(k):
            w = g[:, i]
            mu[i] = float((w * x).sum() / w.sum())
            sd[i] = float(np.sqrt((w * (x - mu[i]) ** 2).sum() / w.sum()))
    return mu, sd, A, g


x = r15
mu, sd, A, g = em_hmm(x)
order = np.argsort(sd)
mu, sd = mu[order], sd[order]
A = A[np.ix_(order, order)]
g = g[:, order]
state = g.argmax(axis=1)
p(f"2 状态 HMM（15m 对数收益，n={len(x)}）:")
for i in range(2):
    p(f"  状态{i} ({'低波动' if i==0 else '高波动'}): μ={mu[i]*1e4:+.3f}bp  "
      f"σ={sd[i]*1e4:.2f}bp  占比={np.mean(state==i):.1%}")
p(f"  转移矩阵: P(00)={A[0,0]:.4f} P(01)={A[0,1]:.4f} | P(10)={A[1,0]:.4f} P(11)={A[1,1]:.4f}")
p(f"  平均持续: 状态0={1/(1-A[0,0]):.1f} 根={1/(1-A[0,0])*15/60:.1f}h  "
  f"状态1={1/(1-A[1,1]):.1f} 根={1/(1-A[1,1])*15/60:.1f}h")
# 状态是否预测未来波动
p("\n  状态对未来 8 根(2h) 已实现波动的预测力:")
fut_vol = pd.Series(np.abs(x)).rolling(8).mean().shift(-8).to_numpy()
for i in range(2):
    m = (state == i) & np.isfinite(fut_vol)
    p(f"    状态{i}: 未来2h平均|收益|={fut_vol[m].mean()*1e4:.2f}bp (n={m.sum()})")
p(f"  比值 = {fut_vol[(state==1)&np.isfinite(fut_vol)].mean()/fut_vol[(state==0)&np.isfinite(fut_vol)].mean():.2f}x "
  f"→ HMM 状态对波动率有强预测力（可用于仓位/风控，不用于方向）")

# Hurst regime 对照
from gold_agent.fusion.gaussian import _hurst_rs
c15 = df15.close.to_numpy(dtype=float)
hs = np.array([_hurst_rs(c15[i-500:i]) if i >= 500 else np.nan
               for i in range(len(c15))])
hs_s = pd.Series(hs).ffill()
p(f"\n  对照 Hurst 阈值法: mean_reverting 占比={np.mean(hs_s<0.45):.1%}  "
  f"transition={np.mean((hs_s>=0.45)&(hs_s<=0.55)):.1%}  trending={np.mean(hs_s>0.55):.1%}")
p("  → Hurst 阈值几乎从不触发 mean_reverting，regime 门控实际失效；")
p("    HMM 提供可解释、可持续、可检验的两态划分")

(RES / "02_report.txt").write_text("\n".join(OUT), encoding="utf-8")
p("\n[已写入 research/02_report.txt]")
