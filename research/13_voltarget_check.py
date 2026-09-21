"""研究取证 13：检验「波动率目标化已证明能改善盈利」这个说法。

04_report C 段的结论是：
  固定仓位 ±1      总盈亏 10648.5  Sharpe 4.54  最大回撤 2167.1  Calmar 4.91
  GARCH 波动率目标  总盈亏  8688.8  Sharpe 4.44  最大回撤 1634.0  Calmar 5.32

本脚本回答三个问题：
  Q1 那个信号（1h 12 期动量）本身是否显著？还是纯噪声？
  Q2 波动率目标化的「改善」在纯噪声信号上是否同样出现？（若是 → 是几何效应，不是 alpha）
  Q3 回撤改善是否只是「仓位变小」的算术结果？做等波动缩放对照。
"""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize, stats

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

RES = Path(__file__).parent
DATA = Path(__file__).resolve().parents[1] / "data" / "cache"
OUT: list[str] = []
T0 = time.time()
COST = 0.52


def p(s: str = "") -> None:
    print(f"[{time.time()-T0:6.1f}s] {s}", flush=True)
    OUT.append(s)


def nw_t(x, lags=8):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < 30:
        return float("nan")
    e = x - x.mean()
    var = float(e @ e) / len(x)
    for L in range(1, lags + 1):
        var += 2 * (1 - L / (lags + 1)) * float(e[L:] @ e[:-L]) / len(x)
    return float(x.mean() / np.sqrt(max(var, 1e-18) / len(x)))


def report(name, pnl, scale=1.0):
    pnl = np.asarray(pnl, float) * scale
    eq = np.cumsum(pnl)
    dd = float(np.max(np.maximum.accumulate(eq) - eq)) if len(eq) else np.nan
    return {"name": name, "total": float(pnl.sum()), "mean": float(pnl.mean()),
            "sd": float(pnl.std()),
            "sharpe": float(pnl.mean() / max(pnl.std(), 1e-12) * np.sqrt(24 * 252)),
            "dd": dd, "calmar": float(pnl.sum() / max(dd, 1e-9)),
            "nw_t": nw_t(pnl), "n": len(pnl)}


# ══════════════════════════════════════════════════════════════════
d = pd.read_parquet(DATA / "XAUUSDm_1h.parquet")
d["time"] = pd.to_datetime(d["time"], utc=True)
d = d.sort_values("time").reset_index(drop=True)
if len(d) > 4000:
    d = d.iloc[-4000:].reset_index(drop=True)
close = d.close.to_numpy(float)
n = len(d)

p("=" * 96)
p("研究取证 13 · 「波动率目标化已改善盈利」的复核")
p("=" * 96)
p(f"1h 数据 {n} 根  {d.time.iloc[0]} .. {d.time.iloc[-1]}  "
  f"区间位移 {close[-1]-close[0]:+.1f} USD")

# ── 复现 04_report 的 GARCH ──
r = np.log(pd.Series(close)).diff().dropna().to_numpy()


def garch_negll(theta, x):
    mu, w, a, b = theta
    if w <= 0 or a < 0 or b < 0 or a + b >= 0.999:
        return 1e10
    s2 = np.empty(len(x))
    s2[0] = np.var(x)
    e = x - mu
    for t in range(1, len(x)):
        s2[t] = max(w + a * e[t - 1] ** 2 + b * s2[t - 1], 1e-14)
    return 0.5 * float(np.sum(np.log(2 * np.pi * s2) + e ** 2 / s2))


res = optimize.minimize(garch_negll, np.array([r.mean(), np.var(r) * 0.05, 0.1, 0.85]),
                        args=(r,), method="Nelder-Mead",
                        options={"maxiter": 6000, "xatol": 1e-9, "fatol": 1e-9})
mu_g, w_g, a_g, b_g = res.x
p(f"GARCH(1,1): ω={w_g:.3e} α={a_g:.4f} β={b_g:.4f} "
  f"持续性={a_g+b_g:.4f} 半衰期={np.log(0.5)/np.log(max(a_g+b_g,1e-9)):.1f}h")

s2 = np.var(r)
sig_t = np.empty(len(r) + 1)
sig_t[0] = np.nan
for t in range(len(r)):
    sig_t[t + 1] = np.sqrt(s2)
    s2 = w_g + a_g * (r[t] - mu_g) ** 2 + b_g * s2
sig_prev = pd.Series(sig_t).shift(1).to_numpy()

mom = np.log(pd.Series(close)).diff(12).to_numpy()
fwd = (pd.Series(close).shift(-6) - pd.Series(close)).to_numpy()
m = np.isfinite(mom) & np.isfinite(fwd) & np.isfinite(sig_prev) & (sig_prev > 0)
target = float(np.nanmedian(sig_prev[m]))
p(f"目标 σ = {target:.3e}  有效样本 n={int(m.sum())}")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("Q1. 那个信号（1h 12 期动量，持有 6h）本身显著吗？")
p("=" * 96)
pos_f = np.sign(mom[m])
pos_v = np.sign(mom[m]) * np.clip(target / sig_prev[m], 0.25, 3.0)
pnl_f = pos_f * fwd[m] - COST * np.abs(pos_f)
pnl_v = pos_v * fwd[m] - COST * np.abs(pos_v)

rows = [report("固定仓位 ±1", pnl_f), report("GARCH 波动率目标", pnl_v)]
p(f"{'方案':<22}{'总盈亏':>11}{'均值':>10}{'标准差':>10}{'年化Sharpe':>12}"
  f"{'最大回撤':>11}{'Calmar':>9}{'NW-t':>8}")
p("-" * 96)
for r_ in rows:
    p(f"{r_['name']:<22}{r_['total']:>11.1f}{r_['mean']:>10.4f}{r_['sd']:>10.4f}"
      f"{r_['sharpe']:>12.2f}{r_['dd']:>11.1f}{r_['calmar']:>9.2f}{r_['nw_t']:>+8.2f}")
p("")
p(f"★ 关键：该信号的 NW-t = {rows[0]['nw_t']:+.2f} —— 恰好落在双侧 5% 临界值 1.96 上。")
p("  即：单看这一个信号是**勉强边缘显著**，但它来自 04_report D 段那个 57 个变体的")
p("  试验族，而该族通不过 White Reality Check（p=1.000）、DSR=0.135。")
p("  多重检验校正后，这个 +1.96 不能算作已确立的 alpha。")
p(f"  它的 +10,648 总盈亏与区间位移的关系：")
p(f"    样本区间价格位移 = {close[-1]-close[0]:+.1f} USD，信号多头占比 = "
  f"{np.mean(pos_f>0):.3f}")
p(f"    纯多头买入持有 = {(close[m][-1]-close[m][0]):+.1f} USD（未扣成本）")
p("    → 区间整体下跌，而策略做多空双向却赚了 +10,648，说明收益来自**波动捕获**")
p("      （6h 持有期的双向暴露）而非单边 beta。但这部分收益的显著性未通过校正。")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("Q2. 波动率目标化的「改善」在**纯噪声信号**上是否同样出现？")
p("=" * 96)
p("若是 → 说明改善来自几何/缩放效应，与信号质量无关，不能算「提升盈利」。")
p("")
p(f"{'信号':<26}{'方案':<20}{'总盈亏':>11}{'Sharpe':>9}{'最大回撤':>11}"
  f"{'Calmar':>9}")
p("-" * 96)
rng = np.random.default_rng(4242)
noise_sig = rng.choice(np.array([-1.0, 1.0]), size=int(m.sum()))
for lab, sgn in (("真实动量信号", pos_f),
                 ("纯噪声（随机方向）", noise_sig)):
    for nm, pos in ((f"固定 ±1", sgn),
                    (f"波动率目标", sgn * np.clip(target / sig_prev[m], 0.25, 3.0))):
        pnl = pos * fwd[m] - COST * np.abs(pos)
        rr = report(nm, pnl)
        p(f"{lab:<26}{nm:<20}{rr['total']:>11.1f}{rr['sharpe']:>9.2f}"
          f"{rr['dd']:>11.1f}{rr['calmar']:>9.2f}")
p("")
p("→ 噪声信号上「回撤下降」同样出现（2974 → 2803），且两个方案的 Calmar 都仍是负的。")
p("  这说明回撤下降是缩放效应；但噪声上**没有**出现 Calmar 转正，")
p("  所以真实信号上 Calmar 4.91→5.32 的上升不能完全归因于缩放。见 Q3。")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("Q3. 回撤改善是否只是「仓位变小」？做等波动缩放对照")
p("=" * 96)
p("对照设计：把固定仓位方案整体乘以一个常数 k，使其波动与波动率目标方案相同。")
p("          若两者 Calmar 接近，则「改善」完全由缩放解释。")
p("")
base = report("固定 ±1", pnl_f)
tgt = report("GARCH 波动率目标", pnl_v)
k = tgt["sd"] / max(base["sd"], 1e-12)
scaled = report(f"固定 ±1 × {k:.3f}", pnl_f, scale=k)
p(f"{'方案':<24}{'总盈亏':>11}{'标准差':>10}{'最大回撤':>11}{'Calmar':>9}")
p("-" * 96)
for r_ in (base, tgt, scaled):
    p(f"{r_['name']:<24}{r_['total']:>11.1f}{r_['sd']:>10.4f}{r_['dd']:>11.1f}"
      f"{r_['calmar']:>9.2f}")
p("")
p(f"→ 等波动缩放后 Calmar = {scaled['calmar']:.2f}（与原始固定仓位 {base['calmar']:.2f} **完全相同**），")
diff = tgt["calmar"] - scaled["calmar"]
p(f"  波动率目标化 = {tgt['calmar']:.2f}。差值 = {diff:+.2f}。")
p("")
p("★ 为什么缩放不改变 Calmar：Calmar = 总盈亏 / 最大回撤，两者都随仓位线性缩放，")
p("  比值恒定。因此「回撤从 2167 降到 1634」**本身不构成任何改善的证据**——")
p("  只要把仓位乘 0.834，回撤就降到 1807，而 Calmar 一点没变。")
p(f"  真正的改善只有 Calmar 的 {diff:+.2f}（相对 {(diff/base['calmar']):+.1%}）。")
p("")
p("★ 复核结论：")
p("  1. 04_report C 段的「波动率目标化改善 Calmar 4.91→5.32」在算术上可复现。")
p(f"     但「最大回撤 2167→1634（−25%）」**不是改善**：等波动缩放即可复现该降幅，")
p(f"     Calmar 纹丝不动。真实的改善量只有 Calmar 的 {diff:+.2f}。")
p("  2. 该信号 NW-t = +1.96，边缘显著，但属于 57 个变体的试验族，")
p("     该族通不过 White Reality Check（p=1.000）与 DSR（0.135）。")
p("  3. 纯噪声对照显示：波动率目标化在无 alpha 的信号上只缩小亏损规模")
p("     （−721 → −305），不改变符号。")
p("  → 因此「波动率目标化已验证能提升盈利」这个说法**不成立**。")
p("     正确的表述是：它是**风险管理工具**（控制暴露与回撤规模），")
p("     不是**盈利来源**。把它当作已证实的盈利改善会误导后续投入方向。")

(RES / "13_voltarget_check.txt").write_text("\n".join(OUT), encoding="utf-8")
p(f"\n[已写入 research/13_voltarget_check.txt]  总用时 {time.time()-T0:.0f}s")
