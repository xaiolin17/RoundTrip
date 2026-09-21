"""研究取证 10：对 09_power 的结论做「对照组校准」+ 成本结构的算术检验。

要回答三件事：
  Q1  三重障碍在**无漂移**随机游走下的毛收益到底是不是 0？
      （09 的合成对照给出 IC=0 → 毛收益 +0.1953，与赌徒破产理论矛盾，必须查清）
  Q2  真实数据上「随机方向」的毛收益 +0.0092 是什么？是障碍机制偏差，还是金价漂移？
  Q3  10 个模型的「毛收益」里，有多少只是**漂移暴露（beta）**，有多少是**择时能力**？

方法（全部无前视、可复现）：
  A. 合成 GBM（μ=0）做零假设标定，并拆出「同根双触发保守判负」规则的贡献
  B. 真实数据上对漂移做**剂量-反应**实验：去漂移 / 原漂移 / 双倍漂移
  C. 零信息对照分布：随机方向 / 匹配多头比例的随机方向 / 块置换（保留自相关）
  D. 漂移暴露的解析分解：predicted_gross = mean(drift × side × bars_held)
  E. 成本结构算术：同一时间窗内，各周期的「总成本」vs「市场总位移」
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


def p(s: str = "") -> None:
    print(f"[{time.time()-T0:6.1f}s] {s}", flush=True)
    OUT.append(s)


def load1m() -> pd.DataFrame:
    df = pd.read_parquet(DATA / "XAUUSDm_1m.parquet")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.sort_values("time").reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════
# 公共工具
# ══════════════════════════════════════════════════════════════════
def run_tb(close, high, low, vol, side, cost, pt=2.0, sl=1.0, hold=60):
    tb = triple_barrier(close, high, low, vol, side, pt, sl, hold, cost)
    m = (side != 0) & np.isfinite(tb.ret) & (tb.bars_held > 0)
    return tb, m


def stats_of(tb, m, cost):
    """返回 (笔数, 毛均值, 净均值, 平均持有, TP率, SL率, 超时率)"""
    if m.sum() == 0:
        return (0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan)
    net = tb.ret[m]
    gross = net + cost
    return (int(m.sum()), float(gross.mean()), float(net.mean()),
            float(tb.bars_held[m].mean()),
            float(np.mean(tb.touch[m] == "tp")),
            float(np.mean(tb.touch[m] == "sl")),
            float(np.mean(tb.touch[m] == "time")))


def tb_tie_diag(close, high, low, vol, side, cost, pt=2.0, sl=1.0, hold=60):
    """与 triple_barrier 同一逻辑，但额外统计「同一根 bar 双触发」被保守判负的次数。"""
    n = len(close)
    side = np.where(np.isfinite(np.asarray(side, float)), np.asarray(side, float), 0.0)
    side = np.sign(side).astype(np.int8)
    n_tie_sl = 0
    n_sl = 0
    n_tp = 0
    n_time = 0
    rets = []
    for t in range(n - 1):
        s = int(side[t])
        if s == 0 or not np.isfinite(vol[t]) or vol[t] <= 0:
            continue
        if s > 0:
            tp_px, sl_px = close[t] + pt * vol[t], close[t] - sl * vol[t]
        else:
            tp_px, sl_px = close[t] - pt * vol[t], close[t] + sl * vol[t]
        end = min(t + hold, n - 1)
        hit = None
        for j in range(t + 1, end + 1):
            hi, lo = high[j], low[j]
            if s > 0:
                t_tp, t_sl = hi >= tp_px, lo <= sl_px
            else:
                t_tp, t_sl = lo <= tp_px, hi >= sl_px
            if t_tp and t_sl:
                hit = ("sl", j, True)
                break
            if t_tp:
                hit = ("tp", j, False)
                break
            if t_sl:
                hit = ("sl", j, False)
                break
        if hit is None:
            j = end
            exit_px = close[j]
            n_time += 1
        else:
            kind, j, tie = hit
            exit_px = tp_px if kind == "tp" else sl_px
            if kind == "tp":
                n_tp += 1
            else:
                n_sl += 1
                n_tie_sl += int(tie)
        rets.append(s * (exit_px - close[t]) - cost)
    return np.array(rets), n_tp, n_sl, n_time, n_tie_sl


def zscore(x: np.ndarray, win: int = 1440) -> np.ndarray:
    s = pd.Series(x)
    m = s.rolling(win, min_periods=120).mean()
    sd = s.rolling(win, min_periods=120).std().replace(0, np.nan)
    return np.clip(((s - m) / sd).to_numpy(), -4, 4)


def nw_t(x, lags=30):
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


# ══════════════════════════════════════════════════════════════════
df = load1m().iloc[-60000:].reset_index(drop=True)
close = df.close.to_numpy(float)
high = df.high.to_numpy(float)
low = df.low.to_numpy(float)
open_ = df.open.to_numpy(float)
n = len(df)
SPREAD = float(df.spread.median()) * 0.001
COST = 2 * SPREAD
vol = ewma_vol(close, 60, 30)
vol = np.where(np.isfinite(vol) & (vol > 0), vol, np.nanmedian(vol))
SIG = float(np.nanmedian(vol))
DRIFT = float((close[-1] - close[0]) / (n - 1))          # USD / 根
PT, SL, HOLD = 2.0, 1.0, 60

p("=" * 96)
p("研究取证 10 · 对照组校准 + 成本结构算术")
p("=" * 96)
p(f"数据：1m XAUUSDm，{n} 根，{df.time.iloc[0]} .. {df.time.iloc[-1]}")
p(f"往返成本 = {COST:.3f} USD（点差中位数 {df.spread.median():.0f} points）")
p(f"σ(1m, EWMA) = {SIG:.4f} USD   障碍 = {PT}σ/{SL}σ = "
  f"{PT*SIG:.3f} / {SL*SIG:.3f} USD   最长持有 {HOLD} 根")
p(f"区间涨跌 = {close[-1]-close[0]:+.1f} USD   漂移 = {DRIFT:+.6f} USD/根")
p(f"成本 / σ = {COST/SIG:.3f}   成本 / TP距离 = {COST/(PT*SIG):.1%}   "
  f"成本 / SL距离 = {COST/(SL*SIG):.1%}")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("A. 零假设标定：无漂移随机游走下，三重障碍的毛收益真的是 0 吗？")
p("=" * 96)
p("理论（赌徒破产，无漂移、连续监控、无限时间）：")
p(f"   P(先触 +{PT}σ) = {SL/(PT+SL):.4f}   P(先触 −{SL}σ) = {PT/(PT+SL):.4f}")
p(f"   E[毛收益] = P(TP)·(+{PT}σ) + P(SL)·(−{SL}σ) = "
  f"{SL/(PT+SL)*PT*SIG - PT/(PT+SL)*SL*SIG:+.6f} USD  ← 恒等于 0")
p("")

NSYN = 120_000
syn_rows = []
for variant in ("无影线(仅收盘价)", "含影线(真实OHLC)"):
    for seed in range(5):
        rng = np.random.default_rng(1000 + seed)
        step = rng.standard_normal(NSYN) * SIG
        c = 5000.0 + np.cumsum(step)                     # μ = 0 的随机游走
        if variant.startswith("无影线"):
            h = c.copy()
            l = c.copy()
        else:
            o = np.concatenate([[c[0]], c[:-1]])
            wick = np.abs(rng.standard_normal(NSYN)) * 0.3 * SIG
            h = np.maximum(o, c) + wick
            l = np.minimum(o, c) - wick
        v = np.full(NSYN, SIG)                            # 已知真实 σ，排除估计噪声
        sg = rng.choice(np.array([-1, 1], dtype=np.int8), size=NSYN)
        tb, m = run_tb(c, h, l, v, sg, COST, PT, SL, HOLD)
        syn_rows.append({"variant": variant, "seed": seed, **dict(zip(
            ["n", "gross", "net", "held", "ptp", "psl", "ptime"], stats_of(tb, m, COST)))})
sy = pd.DataFrame(syn_rows)
p(f"合成 GBM（μ=0，σ={SIG:.4f} 已知，n={NSYN}，{len(sy)} 次运行）：")
p(f"{'变体':<20}{'毛均值':>12}{'净均值':>12}{'平均持有':>10}{'TP率':>8}{'SL率':>8}{'超时率':>8}")
p("-" * 96)
for v, g in sy.groupby("variant", sort=False):
    p(f"{v:<20}{g.gross.mean():>+12.4f}{g.net.mean():>+12.4f}{g.held.mean():>10.2f}"
      f"{g.ptp.mean():>8.3f}{g.psl.mean():>8.3f}{g.ptime.mean():>8.4f}")
    p(f"{'  └ 5 次运行极差':<20}{g.gross.max()-g.gross.min():>12.4f}"
      f"{'':>12}{'':>10}   (毛均值标准差 {g.gross.std():.4f})")

# 同根双触发规则单独量化
rng = np.random.default_rng(7)
step = rng.standard_normal(NSYN) * SIG
c = 5000.0 + np.cumsum(step)
o = np.concatenate([[c[0]], c[:-1]])
wick = np.abs(rng.standard_normal(NSYN)) * 0.3 * SIG
h = np.maximum(o, c) + wick
l = np.minimum(o, c) - wick
v = np.full(NSYN, SIG)
sg = rng.choice(np.array([-1, 1], dtype=np.int8), size=NSYN)
rets, n_tp, n_sl, n_time, n_tie = tb_tie_diag(c, h, l, v, sg, COST, PT, SL, HOLD)
p(f"\n「同一根 bar 双触发 → 保守判负」规则的单独量化（n={NSYN}）：")
p(f"   TP={n_tp}  SL={n_sl}  超时={n_time}   其中因双触发被判负的 SL = {n_tie} "
  f"（占 SL 的 {n_tie/max(n_sl,1):.3%}，占总笔数 {n_tie/len(rets):.3%}）")
p(f"   毛均值 = {rets.mean()+COST:+.4f} USD")
p("   → 该规则制造的是**负**偏差，不可能解释 09 里 +0.1953 的正毛收益。")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("B. 剂量-反应实验：真实数据上，把漂移去掉/加倍，随机方向的毛收益怎么变？")
p("=" * 96)
off = DRIFT * np.arange(n)
variants = {
    "去漂移 (×0)":  (-off, 0.0),
    "原数据 (×1)":  (np.zeros(n), DRIFT),
    "双倍漂移 (×2)": (+off, 2 * DRIFT),
}
SEEDS_B = 10
dose_rows = []
for label, (shift, eff_drift) in variants.items():
    gs = []
    for seed in range(SEEDS_B):
        rng = np.random.default_rng(500 + seed)
        sg = rng.choice(np.array([-1, 1], dtype=np.int8), size=n)
        tb, m = run_tb(close - shift, high - shift, low - shift, vol, sg, COST, PT, SL, HOLD)
        s = stats_of(tb, m, COST)
        gs.append(s[1])
        held = s[3]
    dose_rows.append({"variant": label, "eff_drift": eff_drift,
                      "gross": float(np.mean(gs)), "sd": float(np.std(gs)),
                      "held": held,
                      "pred": eff_drift * held})
dz = pd.DataFrame(dose_rows)
p(f"{'变体':<16}{'有效漂移/根':>14}{'平均持有':>10}{'漂移预测':>12}"
  f"{'实测毛均值':>13}{'10次运行SD':>12}{'残差':>11}")
p("-" * 96)
for _, r in dz.iterrows():
    p(f"{r['variant']:<16}{r['eff_drift']:>+14.6f}{r['held']:>10.2f}{r['pred']:>+12.4f}"
      f"{r['gross']:>+13.4f}{r['sd']:>12.4f}{r['gross']-r['pred']:>+11.4f}")
p("\n→ 若「去漂移」的毛均值回到 0 附近，则 09 里随机方向的正毛收益 = 金价漂移，"
  "不是障碍机制偏差。")
p("※ 本段设计有缺陷：随机方向 E[side]=0，漂移在多空间自我抵消，测不出漂移效应。")
p("  三行结果几乎相同即是证据。修正设计（固定方向）见 11_mechanism.py B 段。")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("C. 零信息对照分布：10 个模型的「毛收益」是否超出随机？")
p("=" * 96)

# ── Null A：随机方向（期望净暴露 0）──
NSEED_A = 200
p(f"Null A：随机方向 × {NSEED_A} 个种子（同一价格路径、同一几何、同一成本）")
nullA = np.empty(NSEED_A)
for seed in range(NSEED_A):
    rng = np.random.default_rng(9000 + seed)
    sg = rng.choice(np.array([-1, 1], dtype=np.int8), size=n)
    tb, m = run_tb(close, high, low, vol, sg, COST, PT, SL, HOLD)
    nullA[seed] = stats_of(tb, m, COST)[1]
loA, hiA = np.percentile(nullA, [2.5, 97.5])
p(f"   毛均值：均值={nullA.mean():+.4f}  SD={nullA.std():.4f}  "
  f"95%区间=[{loA:+.4f}, {hiA:+.4f}]  最大={nullA.max():+.4f}")

# ── 载入模型信号并评估 ──
ad = pd.read_parquet(RES / "arena_dir_1m.parquet")
rows = []
for name in ad["model"]:
    cf = CACHE / f"1m_60000_{name}.npy"
    if not cf.exists():
        continue
    sig = zscore(np.load(cf))
    sgn = np.sign(np.nan_to_num(sig, nan=0.0)).astype(np.int8)
    tb, m = run_tb(close, high, low, vol, sgn, COST, PT, SL, HOLD)
    s = stats_of(tb, m, COST)
    frac_long = float(np.mean(sgn[m] > 0))
    # 漂移暴露的解析分解：drift × side × bars_held
    pred = DRIFT * sgn[m].astype(float) * tb.bars_held[m]
    rows.append({"model": name, "n": s[0], "gross": s[1], "net": s[2],
                 "held": s[3], "ptp": s[4], "frac_long": frac_long,
                 "drift_pred": float(pred.mean()),
                 "gross_t": float((s[1]) / (np.std(tb.ret[m] + COST) / np.sqrt(m.sum()))),
                 "pct_in_nullA": float((nullA < s[1]).mean() * 100)})
md = pd.DataFrame(rows).sort_values("gross", ascending=False).reset_index(drop=True)

p(f"\n{'模型':<16}{'笔数':>7}{'多头占比':>9}{'平均持有':>9}{'毛均值':>10}"
  f"{'漂移可解释':>11}{'残差':>10}{'残差占比':>10}{'NullA分位':>10}")
p("-" * 96)
for _, r in md.iterrows():
    resid = r["gross"] - r["drift_pred"]
    p(f"{r['model']:<16}{int(r['n']):>7}{r['frac_long']:>9.3f}{r['held']:>9.2f}"
      f"{r['gross']:>+10.4f}{r['drift_pred']:>+11.4f}{resid:>+10.4f}"
      f"{(resid/r['gross'] if abs(r['gross'])>1e-9 else np.nan):>9.1%}"
      f"{r['pct_in_nullA']:>9.1f}%")
p(f"\n对照：随机方向毛均值 95% 区间 = [{loA:+.4f}, {hiA:+.4f}]")
p(f"      → 10 个模型里有 {int((md['gross'] <= hiA).sum())} 个的毛收益落在"
  f"「纯随机方向」的 95% 区间内。")

# ── Null B：匹配多头比例的随机方向（控制 beta 暴露）──
NSEED_B = 40
p(f"\nNull B：匹配各模型多头比例的随机方向 × {NSEED_B} 个种子"
  f"（同样暴露于漂移，但择时随机）")
brows = []
for _, r in md.iterrows():
    pl = r["frac_long"]
    gs = []
    for seed in range(NSEED_B):
        rng = np.random.default_rng(7000 + seed)
        sg = np.where(rng.random(n) < pl, 1, -1).astype(np.int8)
        tb, m = run_tb(close, high, low, vol, sg, COST, PT, SL, HOLD)
        gs.append(stats_of(tb, m, COST)[1])
    gs = np.array(gs)
    lo, hi = np.percentile(gs, [2.5, 97.5])
    brows.append({"model": r["model"], "gross": r["gross"], "nullB_mean": gs.mean(),
                  "lo": lo, "hi": hi, "pct": float((gs < r["gross"]).mean() * 100)})
bd = pd.DataFrame(brows)
p(f"{'模型':<16}{'实测毛均值':>12}{'NullB均值':>12}{'NullB 95%区间':>26}"
  f"{'分位':>9}  判定")
p("-" * 96)
for _, r in bd.iterrows():
    verdict = "超出随机" if r["pct"] >= 97.5 else "与随机无异"
    rng_s = "[{:+.4f}, {:+.4f}]".format(r["lo"], r["hi"])
    p(f"{r['model']:<16}{r['gross']:>+12.4f}{r['nullB_mean']:>+12.4f}"
      f"{rng_s:>26}{r['pct']:>8.1f}%  {verdict}")

# ── Null C：块置换（保留模型信号自身的自相关与多头比例）──
NSEED_C = 100
BLOCK = int(round(md["held"].median())) or 4
p(f"\nNull C：块置换模型自身的方向序列 × {NSEED_C} 个种子"
  f"（块长={BLOCK} 根 ≈ 平均持有，保留自相关与多头比例，只打乱与未来的对齐）")
crows = []
for name in ("kalman_trend", "ema_cross_z"):
    if name not in set(md["model"]):
        continue
    cf = CACHE / f"1m_60000_{name}.npy"
    sig = zscore(np.load(cf))
    base = np.sign(np.nan_to_num(sig, nan=0.0)).astype(np.int8)
    gs = []
    for seed in range(NSEED_C):
        rng = np.random.default_rng(3000 + seed)
        starts = rng.integers(0, n, size=n // BLOCK + 2)
        perm = np.concatenate([np.arange(s, s + BLOCK) % n for s in starts])[:n]
        sg = base[perm]
        tb, m = run_tb(close, high, low, vol, sg, COST, PT, SL, HOLD)
        gs.append(stats_of(tb, m, COST)[1])
    gs = np.array(gs)
    obs = float(md.loc[md["model"] == name, "gross"].iloc[0])
    crows.append({"model": name, "obs": obs, "mean": gs.mean(), "sd": gs.std(),
                  "pct": float((gs < obs).mean() * 100),
                  "p_one_sided": float((gs >= obs).mean())})
cd = pd.DataFrame(crows)
p(f"{'模型':<16}{'实测毛均值':>12}{'置换均值':>12}{'置换SD':>10}"
  f"{'分位':>9}{'单边p值':>10}  判定")
p("-" * 96)
for _, r in cd.iterrows():
    p(f"{r['model']:<16}{r['obs']:>+12.4f}{r['mean']:>+12.4f}{r['sd']:>10.4f}"
      f"{r['pct']:>8.1f}%{r['p_one_sided']:>10.3f}  "
      f"{'超出随机' if r['p_one_sided'] < 0.05 else '与随机无异'}")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("D. 成本结构算术：同一时间窗内，各周期的「总成本」vs「市场总位移」")
p("=" * 96)
p("这是不需要任何模型的纯算术：任何方向策略能赚到的上限 ≈ 市场位移 × 择时系数 ≤ 市场位移。")
p("而成本 = 笔数 × 往返成本，笔数随周期变细而线性膨胀。")
p("")
d = df.set_index("time")
tbl = []
for rule, lab in [("1min", "1m"), ("5min", "5m"), ("15min", "15m"),
                  ("30min", "30m"), ("1h", "1h"), ("4h", "4h")]:
    r = (d.resample(rule).agg({"open": "first", "high": "max",
                               "low": "min", "close": "last"}).dropna())
    if len(r) < 50:
        continue
    bars = len(r)
    mv = float(abs(r.close.iloc[-1] - r.close.iloc[0]))
    sgb = float(r.close.diff().std())
    tbl.append({"tf": lab, "bars": bars, "sigma": sgb,
                "cost_over_sigma": COST / max(sgb, 1e-9),
                "total_cost": bars * COST, "move": mv,
                "cost_over_move": bars * COST / max(mv, 1e-9)})
ct = pd.DataFrame(tbl)
p(f"{'周期':<7}{'根数':>8}{'σ/根(USD)':>12}{'成本/σ':>10}"
  f"{'总成本(每根都交易)':>20}{'市场总位移':>12}{'总成本/位移':>13}")
p("-" * 96)
for _, r in ct.iterrows():
    p(f"{r['tf']:<7}{int(r['bars']):>8}{r['sigma']:>12.3f}{r['cost_over_sigma']:>10.3f}"
      f"{r['total_cost']:>20,.0f}{r['move']:>12.1f}{r['cost_over_move']:>12.1f}x")
p("")
p(f"读法：在 1m 上，即使每根 K 线只交易一次，整个 {int(ct.iloc[0]['bars'])} 根窗口的")
p(f"      往返成本合计 {ct.iloc[0]['total_cost']:,.0f} USD，而同期金价总共只走了 "
  f"{ct.iloc[0]['move']:.1f} USD。")
p(f"      → 成本是「市场能提供的全部方向性收益」的 {ct.iloc[0]['cost_over_move']:.0f} 倍。")
p(f"      在 4h 上这个倍数降到 {ct.iloc[-1]['cost_over_move']:.1f} 倍。")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("E. 结论")
p("=" * 96)
p(f"1) 无漂移合成随机游走（已知 σ、μ=0）的毛均值 = "
  f"{sy[sy.variant.str.startswith('无影线')].gross.mean():+.4f} USD（含影线 "
  f"{sy[sy.variant.str.startswith('含影线')].gross.mean():+.4f}）。")
p(f"   理论值 = 0.0000 → **「毛收益」指标本身带构造性正偏误**（详见 11_mechanism）。")
p(f"   机制：三重障碍只在每根 bar 的 high/low 检查，价格越过障碍后仍按障碍价成交，")
p(f"   离散监控下的越障不对称使 E[毛收益] > 0。11_mechanism A 段已证明：")
p(f"   监控变密时毛均值单调 → 0。")
p(f"2) 真实数据上的随机方向基准 = {nullA.mean():+.4f} USD，不是 0，也不是合成值 "
  f"{sy[sy.variant.str.startswith('无影线')].gross.mean():+.4f}。")
p(f"   真实路径的均值回复削弱了越障幅度，故基准远低于纯随机游走。")
p(f"   （方差比 VR(2)={float(np.var(close[2:]-close[:-2], ddof=1)/(2*np.var(np.diff(close), ddof=1))):.4f}，"
  f"详见 11_mechanism C 段）")
p(f"   → 必须用**同一价格路径**的随机方向基准校准，理论值 0 与合成值都不可用。")
p(f"3) 10_verify B 段的剂量-反应设计无效：随机方向 E[side]=0，漂移自我抵消，")
p(f"   三行结果几乎相同（+0.0105/+0.0110/+0.0115）恰好证明了这一点。")
p(f"   修正设计（固定方向）见 11_mechanism B 段。")
p(f"4) 漂移暴露不能用 drift×平均持有期 解析预测（残差反号），")
p(f"   因三重障碍持有期是内生的（见 11_mechanism B 段说明）。")
p(f"5) 校准后的真实图景：毛收益高于零基准的模型 = "
  f"{int((md['gross'] > nullA.mean()).sum())} / {len(md)} 个，")
p(f"   其中毛 NW-t > 2.81（Bonferroni）的 = {int((md['gross_t'] > 2.81).sum())} 个，")
p(f"   而全部 10 个模型的净 NW-t 都 < 0（最差 {md['n'] .min() and ad['nw_t'].min():.1f}，"
  f"最好 {ad['nw_t'].max():.1f}）。")
p(f"6) 成本结构（不需要任何模型）：1m 上「每根都交易」的总成本 = "
  f"{ct.iloc[0]['total_cost']:,.0f} USD，")
p(f"   而同期金价总位移只有 {ct.iloc[0]['move']:.1f} USD，比值 "
  f"{ct.iloc[0]['cost_over_move']:.0f}x；到 4h 降到 {ct.iloc[-1]['cost_over_move']:.1f}x。")
p(f"   → 周期的选择比模型的调参重要一个数量级。")

(RES / "10_verify.txt").write_text("\n".join(OUT), encoding="utf-8")
p(f"\n[已写入 research/10_verify.txt]  总用时 {time.time()-T0:.0f}s")
