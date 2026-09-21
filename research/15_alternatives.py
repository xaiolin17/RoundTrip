"""研究取证 15：直接检验「反买」「止损止盈互换」，以及真正可能提高收益的方向。

用户三问：
  Q1 直接按信号反买行吗？
  Q2 止损止盈互换行吗？
  Q3 如果方向判断率提不上去，还有什么办法提高盈利？

A 段：Q1/Q2 的实测 + 算术证明
B 段：各周期的盈亏平衡 IC（修正 09_power 的 stride 缺陷）
C 段：真正可能有效的过滤器（高波动 regime / 时段 / 多模型一致性）
D 段：结论
"""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_agent.quant import models as M
from gold_agent.quant.labeling import ewma_vol, triple_barrier

RES = Path(__file__).parent
CACHE = RES / "model_cache"
DATA = Path(__file__).resolve().parents[1] / "data" / "cache"
OUT: list[str] = []
T0 = time.time()
COST = 0.520


def p(s: str = "") -> None:
    print(f"[{time.time()-T0:6.1f}s] {s}", flush=True)
    OUT.append(s)


def load(tf):
    d = pd.read_parquet(DATA / f"XAUUSDm_{tf}.parquet")
    d["time"] = pd.to_datetime(d["time"], utc=True)
    return d.sort_values("time").reset_index(drop=True)


def zscore(x, win=1440):
    s = pd.Series(x)
    m = s.rolling(win, min_periods=120).mean()
    sd = s.rolling(win, min_periods=120).std().replace(0, np.nan)
    return np.clip(((s - m) / sd).to_numpy(), -4, 4)


def nw_t(x, lags=30):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < 30:
        return float("nan")
    e = x - x.mean()
    var = float(e @ e) / len(x)
    for L in range(1, lags + 1):
        var += 2 * (1 - L / (lags + 1)) * float(e[L:] @ e[:-L]) / len(x)
    return float(x.mean() / np.sqrt(max(var, 1e-18) / len(x)))


def run(close, high, low, vol, side, cost=COST, pt=2.0, sl=1.0, hold=60, sel=None):
    s = np.asarray(side, dtype=np.int8).copy()
    if sel is not None:
        s = np.where(sel, s, 0).astype(np.int8)
    tb = triple_barrier(close, high, low, vol, s, pt, sl, hold, cost)
    m = (s != 0) & np.isfinite(tb.ret) & (tb.bars_held > 0)
    if m.sum() < 50:
        return None
    ret = tb.ret[m]
    gross = ret + cost
    return {"n": int(m.sum()), "net": float(ret.mean()), "gross": float(gross.mean()),
            "total": float(ret.sum()), "t": nw_t(ret), "hit": float(np.mean(ret > 0)),
            "held": float(tb.bars_held[m].mean()),
            "tp": float(np.mean(tb.touch[m] == "tp"))}


# ══════════════════════════════════════════════════════════════════
df = load("1m").iloc[-60000:].reset_index(drop=True)
close = df.close.to_numpy(float)
high = df.high.to_numpy(float)
low = df.low.to_numpy(float)
n = len(df)
vol = ewma_vol(close, 60, 30)
vol = np.where(np.isfinite(vol) & (vol > 0), vol, np.nanmedian(vol))
SIG = float(np.nanmedian(vol))

sig_raw = zscore(np.load(CACHE / "1m_60000_kalman_trend.npy"))
sgn = np.sign(np.nan_to_num(sig_raw, nan=0.0)).astype(np.int8)

p("=" * 96)
p("研究取证 15 · 反买 / 止损止盈互换 / 真正可行的方向")
p("=" * 96)
p(f"1m {n} 根  σ={SIG:.4f}  往返成本={COST:.3f}  模型=kalman_trend")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("Q1/Q2. 反买 与 止损止盈互换 —— 实测")
p("=" * 96)
base = run(close, high, low, vol, sgn, COST, 2.0, 1.0, 60)
inv = run(close, high, low, vol, -sgn, COST, 2.0, 1.0, 60)
swap = run(close, high, low, vol, sgn, COST, 1.0, 2.0, 60)
invswap = run(close, high, low, vol, -sgn, COST, 1.0, 2.0, 60)

p(f"{'方案':<26}{'几何':>10}{'笔数':>8}{'TP率':>8}{'命中':>8}"
  f"{'毛均值':>10}{'净均值':>10}{'总净盈亏':>11}{'净NW-t':>9}")
p("-" * 96)
for lab, r, geo in (("① 原信号（做多信号就做多）", base, "2σ/1σ"),
                    ("② 反买（信号取反）", inv, "2σ/1σ"),
                    ("③ 止损止盈互换", swap, "1σ/2σ"),
                    ("④ 反买 + 互换", invswap, "1σ/2σ")):
    p(f"{lab:<26}{geo:>10}{r['n']:>8}{r['tp']:>8.3f}{r['hit']:>8.3f}"
      f"{r['gross']:>+10.4f}{r['net']:>+10.4f}{r['total']:>+11.0f}{r['t']:>+9.2f}")

p("\n【反买的算术证明】")
p("  净收益 = 方向 × 价格变动 − 成本。取反只翻转第一项，**成本项不变号**：")
p("     E[净_反买] = −E[毛_原] − 成本 = −(E[净_原] + 成本) − 成本")
p(f"                = −E[净_原] − 2×成本")
p(f"  代入实测：−({base['net']:+.4f}) − 2×{COST:.3f} = "
  f"{-base['net'] - 2*COST:+.4f}   （实测反买净均值 = {inv['net']:+.4f}）")
p(f"  → 反买比原信号**更差，差距恰好是 2×成本 = {2*COST:.3f}**。")
p("  直觉：成本是「每次进场都要交的过路费」，跟你看多还是看空无关。")
p("        方向看反了要交，看对了也要交。反买只是把「略微看对」变成「略微看错」，")
p("        过路费一分不少。")

p("\n【止损止盈互换的算术】")
p(f"  互换后 TP 距离 = 1σ = {SIG:.3f}，成本占 TP 的 {COST/SIG:.1%}（原来只占 "
  f"{COST/(2*SIG):.1%}）")
p("  胜率确实从 ~33% 升到 ~67%，但每笔盈利只有原来的一半、亏损是原来的两倍。")
p(f"  毛均值 = P(TP)·(+1σ) + P(SL)·(−2σ)，无漂移下恒等于 0 —— 与原来一样。")
p(f"  但成本占比翻倍 → 净结果更差：{base['net']:+.4f} → {swap['net']:+.4f}")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("B. 各周期的盈亏平衡 IC（修正 09_power 的 stride 缺陷，stride=1）")
p("=" * 96)
p("09_power 用 iloc[::3] 抽样，导致 2/3 的价格路径不可见，监控被人为稀疏化，")
p("使 IC=0 的对照毛收益虚高到 +0.1953。这里改用 stride=1 重算。")
p("")
p("信号构造：s = ρ·(fwd/scale) + √(1−ρ²)·噪声  →  corr(s, fwd) = ρ 精确可控")
p("（scale 是单一常数，不含逐点前视）")
p("")


def breakeven(tf, rhos, hold=15, max_hold=60, n_seed=5):
    d = load(tf)
    c = d.close.to_numpy(float)
    h = d.high.to_numpy(float)
    l = d.low.to_numpy(float)
    v = ewma_vol(c, 60, 30)
    v = np.where(np.isfinite(v) & (v > 0), v, np.nanmedian(v))
    nn = len(c)
    fwd = np.full(nn, np.nan)
    fwd[:-hold] = c[hold:] - c[:-hold]
    m = np.isfinite(fwd)
    scale = float(np.nanstd(fwd))
    sigm = float(np.nanmedian(v))
    p(f"\n[{tf}] n={nn}  σ/根={sigm:.3f}  成本/σ={COST/sigm:.3f}  "
      f"区间位移={c[-1]-c[0]:+.0f}   （每个 IC 跑 {n_seed} 个噪声种子）")
    p(f"  {'IC(ρ)':>7}{'净均值':>10}{'种子SD':>9}{'净NW-t':>9}"
      f"{'总净盈亏':>11}{'盈利种子':>10}  判定")
    be = None
    null_net = None
    for rho in rhos:
        nets, ts, tots = [], [], []
        for sd_i in range(n_seed):
            rng = np.random.default_rng(1700 + sd_i)
            noise = rng.standard_normal(nn)
            s = (rho * np.nan_to_num(fwd / max(scale, 1e-12))
                 + np.sqrt(max(1 - rho**2, 0)) * noise)
            side = np.sign(s).astype(np.int8)
            side[~m] = 0
            r = run(c, h, l, v, side, COST, 2.0, 1.0, max_hold)
            if r is None:
                continue
            nets.append(r["net"]); ts.append(r["t"]); tots.append(r["total"])
        if not nets:
            continue
        nets = np.array(nets)
        nwin = int((nets > 0).sum())
        if rho == 0.0:
            null_net = float(nets.mean())
        if nwin > n_seed / 2 and be is None:
            be = rho
        p(f"  {rho:>7.3f}{nets.mean():>+10.4f}{nets.std():>9.4f}"
          f"{np.mean(ts):>+9.2f}{np.mean(tots):>+11.0f}"
          f"{f'{nwin}/{n_seed}':>10}  {'✓' if nwin > n_seed/2 else ''}")
    return be, sigm, null_net


RHOS = [0.0, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50]
res = {}
for tf in ("1m", "5m", "15m", "1h", "4h", "1d"):
    try:
        res[tf] = breakeven(tf, RHOS)
    except Exception as e:
        p(f"  [{tf}] 跳过：{type(e).__name__}: {e}")

p("\n" + "-" * 96)
p(f"{'周期':<8}{'σ/根(USD)':>12}{'成本/σ':>10}{'IC=0基准':>11}"
  f"{'盈亏平衡 IC':>13}{'现实可达?':>26}")
p("-" * 96)
for tf, (be, sigm, nul) in res.items():
    bs = f"{be:.2f}" if be is not None else ">0.50"
    flag = "⚠ 基准已为正，不可采信" if (nul is not None and nul > 0) else "现实中 IC≈0.02~0.05"
    p(f"{tf:<8}{sigm:>12.3f}{COST/sigm:>10.3f}"
      f"{(f'{nul:+.3f}' if nul is not None else 'n/a'):>11}{bs:>13}{flag:>26}")
p("")
p("★ 读表警告：4h/1d 的 IC=0 基准本身**就是正的**（+1.31 / +0.98），")
p("  即随机方向在纯噪声下也「盈利」——说明这些周期上基准被区间单边行情严重污染，")
p("  其「盈亏平衡 IC = 0.00」是假象，**不可采信**。")
p("  1m/5m/15m/1h 的基准明显为负（−0.51 ~ −0.69），其盈亏平衡 IC 才有意义。")
p("  样本越少（4h 仅 2000 根、1d 仅 1500 根）污染越重，这是样本量的必然结果。")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("C. 真正可能提高收益的过滤器 —— 实测")
p("=" * 96)

# ── C1 高波动 regime 过滤 ──
p("\nC1. 高波动 regime 过滤")
p("    原理：成本是**固定** 0.52 USD，障碍宽度 = 2σ 随波动变化。")
p("          高波动时 σ 大 → 成本/障碍宽度 小 → 每笔经济性更好。")
p("          这是唯一一个「不依赖方向预测」就能改善单笔经济性的杠杆。")
p("")
vr = pd.Series(vol).rolling(1440, min_periods=240).rank(pct=True).to_numpy()
p(f"{'波动分位门槛':<24}{'保留率':>9}{'笔数':>8}{'σ中位':>9}{'成本/2σ':>10}"
  f"{'毛均值':>10}{'净均值':>10}{'总净盈亏':>11}{'净NW-t':>9}")
p("-" * 96)
for thr in (0.0, 0.3, 0.5, 0.7, 0.9):
    sel = np.isfinite(vr) & (vr >= thr)
    r = run(close, high, low, vol, sgn, COST, 2.0, 1.0, 60, sel=sel)
    if r is None:
        continue
    smed = float(np.nanmedian(vol[sel & (sgn != 0)]))
    p(f"{f'波动分位 ≥ {thr:.0%}':<24}{sel.mean()*100:>8.1f}%{r['n']:>8}"
      f"{smed:>9.3f}{COST/(2*smed):>10.1%}{r['gross']:>+10.4f}{r['net']:>+10.4f}"
      f"{r['total']:>+11.0f}{r['t']:>+9.2f}")

# ── C2 时段过滤 ──
p("\nC2. 时段过滤（UTC 小时）")
p("")
hour = df.time.dt.hour.to_numpy()
p(f"{'时段':<16}{'笔数':>8}{'σ中位':>9}{'成本/2σ':>10}{'净均值':>10}{'净NW-t':>9}")
p("-" * 96)
for lo_h in range(0, 24, 3):
    sel = (hour >= lo_h) & (hour < lo_h + 3)
    r = run(close, high, low, vol, sgn, COST, 2.0, 1.0, 60, sel=sel)
    if r is None:
        continue
    smed = float(np.nanmedian(vol[sel & (sgn != 0)]))
    p(f"{f'{lo_h:02d}-{lo_h+3:02d}h':<16}{r['n']:>8}{smed:>9.3f}"
      f"{COST/(2*smed):>10.1%}{r['net']:>+10.4f}{r['t']:>+9.2f}")

# ── C3 多模型一致性过滤 ──
p("\nC3. 多模型一致性过滤（几个模型同时指向同一方向才进场）")
p("")
pool = []
for nm in ("kalman_trend", "ema_cross_z", "fracdiff", "fft_cycle",
           "ou_zscore", "ml_gbdt", "ofi"):
    cf = CACHE / f"1m_60000_{nm}.npy"
    if cf.exists():
        pool.append(np.sign(np.nan_to_num(zscore(np.load(cf)), nan=0.0)).astype(np.int8))
P = np.column_stack(pool)
agree_long = (P > 0).sum(axis=1)
agree_short = (P < 0).sum(axis=1)
k = P.shape[1]
p(f"    模型池 = {k} 个")
p(f"{'一致性门槛':<24}{'笔数':>8}{'净均值':>10}{'总净盈亏':>11}{'净NW-t':>9}{'命中':>8}")
p("-" * 96)
for need in (1, 4, 5, 6, 7):
    side = np.where(agree_long >= need, 1,
                    np.where(agree_short >= need, -1, 0)).astype(np.int8)
    r = run(close, high, low, vol, side, COST, 2.0, 1.0, 60)
    if r is None:
        continue
    p(f"{f'≥{need}/{k} 一致':<24}{r['n']:>8}{r['net']:>+10.4f}"
      f"{r['total']:>+11.0f}{r['t']:>+9.2f}{r['hit']:>8.3f}")

# ── C4 组合：高周期 + 高波动 ──
p("\nC4. 组合：高周期 + 高波动分位")
p("")
p(f"{'周期':<8}{'波动门槛':<12}{'笔数':>8}{'σ中位':>9}{'成本/2σ':>10}"
  f"{'净均值':>10}{'总净盈亏':>11}{'净NW-t':>9}")
p("-" * 96)
for tf in ("1h", "4h"):
    d = load(tf)
    c = d.close.to_numpy(float)
    h = d.high.to_numpy(float)
    l = d.low.to_numpy(float)
    v = ewma_vol(c, 60, 30)
    v = np.where(np.isfinite(v) & (v > 0), v, np.nanmedian(v))
    cf = CACHE / f"{tf}_{len(d)}_kalman_trend.npy"
    if cf.exists():
        sg = np.sign(np.nan_to_num(zscore(np.load(cf)), nan=0.0)).astype(np.int8)
    else:
        # 缓存未命中：现算（同一 z-score 流程，无前视）
        raw = next(s.fn for s in M.REGISTRY if s.name == "kalman_trend")(d)
        sg = np.sign(np.nan_to_num(zscore(np.asarray(raw, float)), nan=0.0)).astype(np.int8)
    vrank = pd.Series(v).rolling(500, min_periods=100).rank(pct=True).to_numpy()
    for thr in (0.0, 0.5):
        sel = np.isfinite(vrank) & (vrank >= thr)
        r = run(c, h, l, v, sg, COST, 2.0, 1.0, 60, sel=sel)
        if r is None:
            continue
        smed = float(np.nanmedian(v[sel & (sg != 0)]))
        p(f"{tf:<8}{f'≥{thr:.0%}':<12}{r['n']:>8}{smed:>9.3f}"
          f"{COST/(2*smed):>10.1%}{r['net']:>+10.4f}{r['total']:>+11.0f}{r['t']:>+9.2f}")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("D. 结论")
p("=" * 96)
p("1) 反买：**数学上必然更差**，差距恰为 2×成本。")
p(f"   −(净_原) − 2×成本 = {-base['net']-2*COST:+.4f}，实测 {inv['net']:+.4f}。")
p("   成本与方向无关，反买不省一分钱，只把「略微看对」变成「略微看错」。")
p("2) 止损止盈互换：胜率 33%→67%，但赔率同步反转，毛期望仍为 0，")
p(f"   而成本占 TP 的比例翻倍 → 净结果更差（{base['net']:+.4f} → {swap['net']:+.4f}）。")
p("3) 盈亏平衡 IC 随周期放大而下降：1m >0.50 → 5m 0.40 → 15m 0.30 → 1h 0.10。")
p("   4h/1d 的基准被单边行情污染（IC=0 也「盈利」），不可采信。")
p("   现实模型 IC 约 0.02~0.05 → **只有 1h 及以上才进入可能区间**。")
p("4) 高波动 regime 过滤是唯一**不依赖方向预测**就能改善单笔经济性的手段，")
p("   因为它直接改善「成本/障碍宽度」这个比值（见 C1）。")
p("5) C4 显示组合后 1h/4h 净均值为正（+1.20 / +2.64，NW-t 0.74 / 1.38），")
p("   但 NW-t < 2，**统计上不显著**；且 4h/1d 的零基准本身为正（见 B 段警告），")
p("   无法排除是区间单边行情的 beta。这是「值得进一步验证」的方向，不是已证实的结论。")

(RES / "15_alternatives.txt").write_text("\n".join(OUT), encoding="utf-8")
p(f"\n[已写入 research/15_alternatives.txt]  总用时 {time.time()-T0:.0f}s")
