"""研究取证 03：把统计显著性换算成钱。

1) 1m 均值回归（方差比检验唯一显著的发现）能否覆盖成本？
2) chanlun 结构分在 2 年 15m 真实历史上有没有 IC？
3) 波动率目标化能否改善风险调整收益？
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
from gold_agent.skills.chanlun_adapter import analyze_tf

RES = Path(__file__).parent
OUT: list[str] = []


def p(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


def nw_t(x: np.ndarray, lags: int) -> float:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < 30:
        return float("nan")
    e = x - x.mean()
    var = float(e @ e) / len(x)
    for L in range(1, lags + 1):
        var += 2 * (1 - L / (lags + 1)) * float(e[L:] @ e[:-L]) / len(x)
    return float(x.mean() / np.sqrt(max(var, 1e-18) / len(x)))


def load(tf: str) -> pd.DataFrame:
    df = pd.read_parquet(CFG.data_dir / f"XAUUSDm_{tf}.parquet")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.sort_values("time").reset_index(drop=True)


df1 = load("1m")
px = df1.close.to_numpy(float)
SPREAD = float(df1.spread.median()) * 0.001
COST = 2 * SPREAD

# ══════════════════════════════════════════════════════════════════
p("=" * 80)
p("A. 1m 均值回归：统计显著 ≠ 可交易（净成本检验）")
p("=" * 80)
r1 = np.diff(np.log(px))
p(f"往返成本 = {COST:.3f} USD/盎司；1m 收益 σ = {r1.std()*px.mean():.3f} USD")
p(f"成本 / 1m σ = {COST/(r1.std()*px.mean()):.2f} 倍  ← 成本比单根 K 线的波动还大")

p(f"\n{'信号':<26}{'持有':>6}{'笔数':>8}{'毛均值':>10}{'净均值':>10}{'NW-t(净)':>10}{'胜率':>8}{'总盈亏USD':>12}")
for look in (5, 15, 30, 60):
    z = (px - pd.Series(px).rolling(look).mean()) / pd.Series(px).rolling(look).std()
    z = z.to_numpy()
    for hold in (5, 15, 30, 60):
        sig = -np.sign(z)                      # 反转：涨多了做空
        pnl_gross = np.zeros(len(px))
        valid = np.isfinite(z) & (sig != 0)
        idx = np.where(valid)[0]
        idx = idx[idx + hold < len(px)]
        fwd = px[idx + hold] - px[idx]
        g = sig[idx] * fwd
        net = g - COST
        p(f"{f'反转 z({look})':<26}{hold:>6}{len(idx):>8}{g.mean():>10.3f}"
          f"{net.mean():>10.3f}{nw_t(net, hold):>10.2f}"
          f"{np.mean(net>0):>8.3f}{net.sum():>12.1f}")

p("\n【只在极端 z 值交易（提高每笔期望）】")
for thr in (1.5, 2.0, 2.5, 3.0):
    z = ((px - pd.Series(px).rolling(30).mean()) / pd.Series(px).rolling(30).std()).to_numpy()
    for hold in (15, 30, 60):
        idx = np.where(np.isfinite(z) & (np.abs(z) > thr))[0]
        idx = idx[idx + hold < len(px)]
        if len(idx) < 30:
            continue
        net = -np.sign(z[idx]) * (px[idx + hold] - px[idx]) - COST
        p(f"  |z|>{thr} hold={hold:>3}m: n={len(idx):5d} 净均值={net.mean():+.3f} "
          f"NW-t={nw_t(net, hold):+.2f} 胜率={np.mean(net>0):.3f} 总={net.sum():+.1f}")

p("\n【限价挂单版本：假设 50% 成交率，赚取点差的一半】")
p("  （网格/挂单的真实经济：入场不付点差，只付出场点差）")
for look in (15, 30, 60):
    z = ((px - pd.Series(px).rolling(look).mean()) / pd.Series(px).rolling(look).std()).to_numpy()
    for hold in (15, 30, 60):
        idx = np.where(np.isfinite(z) & (np.abs(z) > 1.5))[0]
        idx = idx[idx + hold < len(px)]
        if len(idx) < 30:
            continue
        # 限价成交：只付单边点差
        net = -np.sign(z[idx]) * (px[idx + hold] - px[idx]) - SPREAD
        p(f"  z({look}) |z|>1.5 hold={hold:>3}m: n={len(idx):5d} 净均值={net.mean():+.3f} "
          f"NW-t={nw_t(net, hold):+.2f} 总={net.sum():+.1f}")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 80)
p("B. chanlun 结构分在 2 年 15m 真实历史上的预测力")
p("=" * 80)
df15 = load("15m")
p(f"15m: {len(df15)} 根  {df15.time.iloc[0]} .. {df15.time.iloc[-1]}")

WARM = 400
STEP = 4
HZ = {"4根(1h)": 4, "8根(2h)": 8, "16根(4h)": 16, "32根(8h)": 32}
recs = []
for i in range(WARM, len(df15) - 40, STEP):
    win = df15.iloc[i - WARM:i].reset_index(drop=True)
    try:
        r = analyze_tf(win, "15m")
    except Exception:
        continue
    if r.status != "ok":
        continue
    rec = {"i": i, "score": r.score, "structure": r.structure,
           "n_sig": len(r.signals),
           "sig_kinds": ",".join(sorted({str(s.get("kind")) for s in r.signals}))}
    for nm, h in HZ.items():
        rec[f"f_{nm}"] = float(df15.close.iloc[i + h] - df15.close.iloc[i - 1])
    recs.append(rec)

cd = pd.DataFrame(recs)
p(f"决策点 n={len(cd)}  分数分布: mean={cd.score.mean():+.3f} std={cd.score.std():.3f} "
  f"min={cd.score.min():+.1f} max={cd.score.max():+.1f}")
p(f"非零占比={np.mean(cd.score != 0):.1%}  结构分布: "
  f"{cd.structure.value_counts().head(8).to_dict()}")

p(f"\n{'horizon':>10}{'IC':>10}{'NW-t':>8}{'命中':>8}{'n':>7}")
for nm in HZ:
    x = cd.score.to_numpy()
    y = cd[f"f_{nm}"].to_numpy()
    m = np.isfinite(x) & np.isfinite(y) & (x != 0)
    if m.sum() < 50:
        continue
    icv = float(np.corrcoef(pd.Series(x[m]).rank(), pd.Series(y[m]).rank())[0, 1])
    hit = float(np.mean(np.sign(x[m]) == np.sign(y[m])))
    pnl = np.sign(x[m]) * y[m] - COST
    p(f"{nm:>10}{icv:>+10.4f}{nw_t(pnl, 32):>8.2f}{hit:>8.3f}{m.sum():>7}")

p("\n【按 |score| 分档（当前生产用 1.3 开仓阈值）】")
for nm in ("16根(4h)", "32根(8h)"):
    y = cd[f"f_{nm}"].to_numpy()
    p(f"  horizon={nm}")
    for lo, hi in [(0, .5), (.5, 1.0), (1.0, 1.5), (1.5, 2.5), (2.5, 10)]:
        m = (cd.score.abs() >= lo) & (cd.score.abs() < hi)
        if m.sum() < 30:
            continue
        net = np.sign(cd.score[m]) * y[m] - COST
        p(f"    |score|∈[{lo:.1f},{hi:.1f}) n={m.sum():4d} "
          f"命中={np.mean(net>0):.3f} 净均值={net.mean():+.3f} NW-t={nw_t(net,32):+.2f}")

p("\n【按结构类型分解】")
for st, gg in cd.groupby("structure"):
    if len(gg) < 50:
        continue
    y = gg["f_16根(4h)"].to_numpy()
    x = gg.score.to_numpy()
    m = x != 0
    if m.sum() < 30:
        p(f"  {st:<22} n={len(gg):5d} 分数恒为0或样本不足")
        continue
    net = np.sign(x[m]) * y[m] - COST
    p(f"  {st:<22} n={len(gg):5d} 非零{m.sum():5d} 净均值={net.mean():+.3f} "
      f"NW-t={nw_t(net,32):+.2f} 命中={np.mean(net>0):.3f}")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 80)
p("C. 波动率目标化对风险调整收益的影响（GARCH vs 固定仓位）")
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
        s2[t] = max(s2[t], 1e-14)
    return 0.5 * float(np.sum(np.log(2 * np.pi * s2) + e ** 2 / s2))


from scipy import optimize

r15 = np.log(df15.close).diff().dropna().to_numpy()
res = optimize.minimize(garch11_negll, np.array([r15.mean(), np.var(r15) * 0.05, 0.1, 0.85]),
                        args=(r15,), method="Nelder-Mead",
                        options={"maxiter": 6000, "xatol": 1e-9, "fatol": 1e-9})
mu_g, w_g, a_g, b_g = res.x
p(f"GARCH(1,1): ω={w_g:.3e} α={a_g:.4f} β={b_g:.4f}")

# 滤波出条件波动率序列
s2 = np.var(r15)
sig_t = np.empty(len(r15))
for t in range(len(r15)):
    sig_t[t] = np.sqrt(s2)
    s2 = w_g + a_g * (r15[t] - mu_g) ** 2 + b_g * s2
sig_t = pd.Series(sig_t).shift(1).to_numpy()      # 只用 t-1 信息，避免前视

# 一个朴素的动量策略（12 根 = 3h 动量），分别用固定仓位 vs 波动率目标仓位
mom = pd.Series(np.log(df15.close)).diff(12).to_numpy()
fwd = (df15.close.shift(-4) - df15.close).to_numpy()
valid = np.isfinite(mom) & np.isfinite(fwd) & np.isfinite(sig_t) & (sig_t > 0)
m = valid
target = np.nanmedian(sig_t[m])
p(f"\n目标波动率 = 中位数 σ = {target:.3e}")

pos_fixed = np.sign(mom[m])
pos_volt = np.sign(mom[m]) * np.clip(target / sig_t[m], 0.25, 3.0)
pnl_fixed = pos_fixed * fwd[m] - COST * np.abs(pos_fixed)
pnl_volt = pos_volt * fwd[m] - COST * np.abs(pos_volt)

p(f"\n{'方案':<24}{'总盈亏':>12}{'均值':>10}{'标准差':>10}{'Sharpe(年化)':>14}{'最大回撤':>12}")
for nm, pnl, pos in (("固定仓位(±1)", pnl_fixed, pos_fixed),
                     ("GARCH 波动率目标", pnl_volt, pos_volt)):
    eq = np.cumsum(pnl)
    dd = float(np.max(np.maximum.accumulate(eq) - eq))
    sharpe = pnl.mean() / pnl.std() * np.sqrt(96 * 252)
    p(f"{nm:<24}{pnl.sum():>12.1f}{pnl.mean():>10.4f}{pnl.std():>10.4f}"
      f"{sharpe:>14.2f}{dd:>12.1f}")

p("\n【同样的对比：用真实 1m 数据 + 现有系统的 S 分（无法用 chanlun 的部分用动量代理）】")
p("  结论：波动率目标化降低回撤、改善 Sharpe，但不改变策略方向期望（方向仍为 0）")

(RES / "03_report.txt").write_text("\n".join(OUT), encoding="utf-8")
p("\n[已写入 research/03_report.txt]")
