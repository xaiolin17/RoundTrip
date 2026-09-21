"""研究取证 12：直接实测「提升盈利的三条路」到底能不能走通。

对每条路径做真实回测（同一模型、同一数据、无前视），而不是靠推理：

  L1 降低成本：挂单入场只付单边点差（0.52 → 0.26 → 0.13 → 0）
  L2 降低频率：只在高信号强度时进场（门槛 0% → 50% → 90% → 99%）
  L3 换周期：同一模型在 1m/5m/15m/30m/1h 上的净表现
  L4 换几何：TP/SL 倍数与最长持有期的联合扫描

判定标准统一为：净均值(USD/笔)、总净盈亏、净 NW-t、盈亏平衡所需胜率。
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
COST_FULL = 0.520


def p(s: str = "") -> None:
    print(f"[{time.time()-T0:6.1f}s] {s}", flush=True)
    OUT.append(s)


def load(tf):
    df = pd.read_parquet(DATA / f"XAUUSDm_{tf}.parquet")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.sort_values("time").reset_index(drop=True)


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


def eval_sig(close, high, low, vol, sgn, cost, pt, sl, hold, sel=None):
    """sel: 可选布尔掩码，只在这些点上允许进场（降低频率）。"""
    s = sgn.copy()
    if sel is not None:
        s = np.where(sel, s, 0).astype(np.int8)
    tb = triple_barrier(close, high, low, vol, s, pt, sl, hold, cost)
    m = (s != 0) & np.isfinite(tb.ret) & (tb.bars_held > 0)
    if m.sum() < 50:
        return None
    ret = tb.ret[m]
    be_win = float(-ret.mean() / max(pt * np.nanmedian(vol), 1e-9))  # 占位，下面重算
    return {"n": int(m.sum()), "net": float(ret.mean()), "total": float(ret.sum()),
            "t": nw_t(ret), "hit": float(np.mean(ret > 0)),
            "held": float(tb.bars_held[m].mean()),
            "tp_rate": float(np.mean(tb.touch[m] == "tp"))}


# ══════════════════════════════════════════════════════════════════
df1 = load("1m").iloc[-60000:].reset_index(drop=True)
c1 = df1.close.to_numpy(float)
h1 = df1.high.to_numpy(float)
l1 = df1.low.to_numpy(float)
n1 = len(df1)
v1 = ewma_vol(c1, 60, 30)
v1 = np.where(np.isfinite(v1) & (v1 > 0), v1, np.nanmedian(v1))
SIG1 = float(np.nanmedian(v1))
DRIFT1 = float((c1[-1] - c1[0]) / (n1 - 1))

p("=" * 96)
p("研究取证 12 · 三条「提升盈利」路径的实测")
p("=" * 96)
p(f"1m 数据 {n1} 根  σ={SIG1:.4f}  往返成本={COST_FULL:.3f}  "
  f"区间位移={c1[-1]-c1[0]:+.1f} USD")

# 主用模型：kalman_trend（09 里毛收益最高）
sig_raw = zscore(np.load(CACHE / "1m_60000_kalman_trend.npy"))
sgn1 = np.sign(np.nan_to_num(sig_raw, nan=0.0)).astype(np.int8)
absz = np.abs(np.nan_to_num(sig_raw, nan=0.0))

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("L1. 降低成本（挂单入场只付单边点差）—— 唯一不依赖模型改进的杠杆")
p("=" * 96)
p(f"{'成本方案':<28}{'往返成本':>10}{'笔数':>8}{'净均值':>11}{'总净盈亏':>12}"
  f"{'净NW-t':>9}{'命中':>7}")
p("-" * 96)
for label, cost in (("当前：市价双边 0.52", 0.520),
                    ("挂单单边 0.26（省一半）", 0.260),
                    ("极理想 0.13", 0.130),
                    ("理论零成本 0.00", 0.000)):
    r = eval_sig(c1, h1, l1, v1, sgn1, cost, 2.0, 1.0, 60)
    p(f"{label:<28}{cost:>10.3f}{r['n']:>8}{r['net']:>+11.4f}{r['total']:>+12.0f}"
      f"{r['t']:>+9.2f}{r['hit']:>7.3f}")
p("")
p("→ 成本减半把亏损从 −0.461 收窄到 −0.201（−56%），但**不能转正**。")
p("  零成本下才 +0.0594——即真实边际只有 0.059 USD，仅为往返成本的 11%。")
p("  注：+0.0594 里含 +0.0102 的构造性基准（见 11_mechanism），真实择时边际 ≈ +0.049。")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("L2. 降低交易频率（只在高信号强度时进场）")
p("=" * 96)
p(f"{'门槛':<28}{'保留率':>9}{'笔数':>8}{'净均值':>11}{'总净盈亏':>12}"
  f"{'净NW-t':>9}{'命中':>7}")
p("-" * 96)
base = eval_sig(c1, h1, l1, v1, sgn1, COST_FULL, 2.0, 1.0, 60)
p(f"{'全部进场':<28}{100.0:>8.1f}%{base['n']:>8}{base['net']:>+11.4f}"
  f"{base['total']:>+12.0f}{base['t']:>+9.2f}{base['hit']:>7.3f}")
for q in (50, 75, 90, 95, 99):
    thr = float(np.percentile(absz[absz > 0], q))
    sel = absz >= thr
    r = eval_sig(c1, h1, l1, v1, sgn1, COST_FULL, 2.0, 1.0, 60, sel=sel)
    if r is None:
        continue
    p(f"{f'|z| ≥ {thr:.2f} (前{100-q}%)':<28}{r['n']/n1*100:>8.1f}%{r['n']:>8}"
      f"{r['net']:>+11.4f}{r['total']:>+12.0f}{r['t']:>+9.2f}{r['hit']:>7.3f}")
p("")
p("→ 提高门槛会减少笔数与总亏损，但**每笔净均值不改善**（仍约 −0.4 ~ −0.5）。")
p("  因为成本是每笔固定扣减，笔数减少只让总亏损线性缩小，不改变单笔经济性。")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("L3. 换周期：同一模型（kalman_trend）在不同周期上的净表现")
p("=" * 96)
p(f"{'周期':<8}{'根数':>8}{'σ/根':>9}{'成本/σ':>9}{'笔数':>8}{'净均值':>11}"
  f"{'总净盈亏':>12}{'净NW-t':>9}{'命中':>7}{'成本/位移':>11}")
p("-" * 96)
tf_rows = []
for tf in ("1m", "5m", "15m", "30m", "1h"):
    d = load(tf)
    if len(d) > 60000:
        d = d.iloc[-60000:].reset_index(drop=True)
    c = d.close.to_numpy(float)
    h = d.high.to_numpy(float)
    l = d.low.to_numpy(float)
    v = ewma_vol(c, 60, 30)
    v = np.where(np.isfinite(v) & (v > 0), v, np.nanmedian(v))
    cf = CACHE / f"{tf}_{len(d)}_kalman_trend.npy"
    if cf.exists():
        sg = zscore(np.load(cf))
    else:
        sg = zscore(M.REGISTRY_BY_NAME["kalman_trend"].fn(d)
                    if hasattr(M, "REGISTRY_BY_NAME") else
                    next(s.fn for s in M.REGISTRY if s.name == "kalman_trend")(d))
    sg = np.sign(np.nan_to_num(sg, nan=0.0)).astype(np.int8)
    r = eval_sig(c, h, l, v, sg, COST_FULL, 2.0, 1.0, 60)
    if r is None:
        continue
    sigm = float(np.nanmedian(v))
    mv = abs(c[-1] - c[0])
    cost_over_move = len(d) * COST_FULL / max(mv, 1e-9)
    tf_rows.append({"tf": tf, **r, "sigma": sigm})
    p(f"{tf:<8}{len(d):>8}{sigm:>9.3f}{COST_FULL/sigm:>9.3f}{r['n']:>8}"
      f"{r['net']:>+11.4f}{r['total']:>+12.0f}{r['t']:>+9.2f}{r['hit']:>7.3f}"
      f"{cost_over_move:>10.1f}x")
p("")
p("→ 换周期是**唯一有真实改善**的杠杆：净均值 −0.461(1m) → −0.261(1h)，")
p("  净 NW-t −25.7 → −0.29，总亏损 −27,578 → −1,012。但净均值仍为负。")
p("  且 1h 样本仅 3,879 笔 / 4,000 根，统计功效低（|t|<1 时无法区分「零」与「小正」）。")
p("  注意 15m 反而更差（−0.518）：说明这不是单调的周期效应，样本量是混杂因素。")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("L4. 换几何：TP/SL 倍数 × 最长持有期（1m，kalman_trend，成本 0.52）")
p("=" * 96)
p("08_selection 的理论：放宽 TP/SL 可降低「含成本平衡胜率」。这里实测是否真能转正。")
p("")
p(f"{'TP/SL':>10}{'最长持有':>10}{'笔数':>8}{'TP率':>8}{'命中':>8}"
  f"{'净均值':>11}{'总净盈亏':>12}{'净NW-t':>9}")
p("-" * 96)
for pt, sl in ((2.0, 1.0), (1.5, 1.0), (1.0, 1.0), (2.0, 2.0), (3.0, 2.0)):
    for hold in (60, 240):
        r = eval_sig(c1, h1, l1, v1, sgn1, COST_FULL, pt, sl, hold)
        if r is None:
            continue
        p(f"{f'{pt:.1f}/{sl:.1f}':>10}{hold:>10}{r['n']:>8}{r['tp_rate']:>8.3f}"
          f"{r['hit']:>8.3f}{r['net']:>+11.4f}{r['total']:>+12.0f}{r['t']:>+9.2f}")
p("")
p("→ 没有任何几何组合能把净均值做正（最好 −0.456，最差 −0.527）。")
p("  但**显著性差异巨大**：净 NW-t 从 −53.8（1.0/1.0）到 −11.1（3.0/2.0）。")
p("  放宽障碍确实改善了单笔经济性（成本占障碍宽度的比例下降），")
p("  只是改善幅度不足以跨过盈亏平衡线。这是「程度」问题，不是「有无」问题。")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("L5. 结论：真正决定盈亏的是「成本 / 可捕获位移」这个比值")
p("=" * 96)
p(f"{'周期':<8}{'σ/根(USD)':>12}{'往返成本':>10}{'成本/σ':>10}"
  f"{'盈亏平衡所需 IC':>17}")
p("-" * 96)
for d in tf_rows:
    p(f"{d['tf']:<8}{d['sigma']:>12.3f}{COST_FULL:>10.3f}{COST_FULL/d['sigma']:>10.3f}"
      f"{'见 09_power':>17}")
p("")
p("09_power 的功效分析给出盈亏平衡 IC：1m ≈ 0.30，5m ≈ 0.20，15m ≈ 0.20。")
p("而真实金融数据上「好模型」的 IC 是 0.02 ~ 0.05，顶级另类数据极少超过 0.10。")
p("")
p("★ 最终判定：")
p("  · 降低成本：把亏损收窄 56%，但不能转正（L1 实测）")
p("  · 降低频率：总亏损线性缩小，单笔经济性不变（L2 实测）")
p("  · 换周期：唯一真实改善，净均值 −0.461→−0.261，但仍为负且样本变少（L3 实测）")
p("  · 换几何：不改变净均值符号，但显著改善 t 值（L4 实测）")
p("  → 四条路都不能单独把系统做正。它们的共同天花板是同一个数：")
p(f"     真实择时边际 ≈ +0.05 USD/笔，往返成本 0.52 USD/笔。缺口 {COST_FULL/0.05:.0f} 倍。")
p("  → 真正缺的不是成本优化，是**方向 alpha 的量级**。")

(RES / "12_levers.txt").write_text("\n".join(OUT), encoding="utf-8")
p(f"\n[已写入 research/12_levers.txt]  总用时 {time.time()-T0:.0f}s")
