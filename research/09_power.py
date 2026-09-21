"""研究取证 09：分解「毛收益 vs 成本」+ 计算「需要多高的 IC 才能盈利」。

回答一个关键问题：模型是"完全无效"，还是"有效但被成本吃光"？
  三重障碍里 net = gross − cost（每笔常数），所以：
    gross_mean = net_mean + cost
    SE 不变（减常数不改方差）
    gross_t = t_net × (1 + cost / net_mean)
  于是可以直接从擂台结果解析出毛收益，无需重算。
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
from gold_agent.quant.labeling import ewma_vol, triple_barrier

RES = Path(__file__).parent
OUT: list[str] = []


def p(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


def load(tf):
    df = pd.read_parquet(CFG.data_dir / f"XAUUSDm_{tf}.parquet")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.sort_values("time").reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════
p("=" * 92)
p("A. 分解：模型到底有没有「毛收益」？还是纯粹被成本吃光？")
p("=" * 92)
ad = pd.read_parquet(RES / "arena_dir_1m.parquet")
COST = 0.520
ad["gross_mean"] = ad["mean_ret"] + COST
ad["se"] = (ad["mean_ret"] / ad["nw_t"]).abs()
ad["gross_t"] = ad["gross_mean"] / ad["se"]
ad["cost_ratio"] = COST / ad["gross_mean"].abs()

p(f"1m 数据，往返成本 = {COST:.3f} USD/盎司")
p(f"（net = gross − cost，每笔扣常数，故 SE 不变、毛 t 值可解析推出）\n")
p(f"{'模型':<16}{'笔数':>7}{'净均值':>10}{'毛均值':>10}{'毛NW-t':>9}"
  f"{'净NW-t':>9}{'成本/毛收益':>12}  判定")
p("-" * 92)
ad = ad.sort_values("gross_t", ascending=False).reset_index(drop=True)
for _, r in ad.iterrows():
    if r["gross_mean"] > 0:
        verdict = "有毛收益" if r["gross_t"] > 2.81 else "毛收益不显著"
    else:
        verdict = "毛收益为负"
    p(f"{r['model']:<16}{int(r['n']):>7}{r['mean_ret']:>10.4f}{r['gross_mean']:>+10.4f}"
      f"{r['gross_t']:>+9.2f}{r['nw_t']:>+9.2f}{r['cost_ratio']:>11.1f}x  {verdict}")

# ── 对照组：完全随机方向，同样几何/同样数据 ──
# 目的：验证「毛收益为正」不是障碍机制本身产生的假象。
p("\n对照组：随机方向（同样 2σ/1σ 几何、同样数据、同样成本）")
df1 = load("1m").iloc[-60000:].reset_index(drop=True)
c1 = df1.close.to_numpy(float)
h1 = df1.high.to_numpy(float)
l1 = df1.low.to_numpy(float)
v1 = ewma_vol(c1, 60, 30)
v1 = np.where(np.isfinite(v1) & (v1 > 0), v1, np.nanmedian(v1))
rng_c = np.random.default_rng(11)
ctrl = []
for k in range(3):
    sg = rng_c.choice(np.array([-1, 1], dtype=np.int8), size=len(c1))
    tbc = triple_barrier(c1, h1, l1, v1, sg, 2.0, 1.0, 60, COST)
    mc = np.isfinite(tbc.ret) & (tbc.bars_held > 0)
    ctrl.append(float((tbc.ret[mc] + COST).mean()))
    p(f"  种子{k}: 毛均值={ctrl[-1]:+.4f}  "
      f"TP率={np.mean(tbc.touch[mc]=='tp'):.3f} SL率={np.mean(tbc.touch[mc]=='sl'):.3f} "
      f"超时率={np.mean(tbc.touch[mc]=='time'):.3f}")
CTRL = float(np.mean(ctrl))
p(f"  对照组毛均值 = {CTRL:+.4f} USD  ← 这是「零信息」的基准线")
p(f"\n扣除对照组基准后的真实毛收益（模型毛均值 − 对照基准）：")
ad["edge_net_ctrl"] = ad["gross_mean"] - CTRL
for _, r in ad.iterrows():
    p(f"  {r['model']:<16} 毛均值={r['gross_mean']:+.4f}  "
      f"净边际={r['edge_net_ctrl']:+.4f} USD  ({r['edge_net_ctrl']/COST*100:+.1f}% 成本)")

pos = ad[ad["gross_mean"] > 0]
p(f"\n10 个模型里，毛收益为正的 = {len(pos)} 个")
p(f"其中毛 NW-t > 2.81（10 次检验的 Bonferroni 阈值）= "
  f"{(ad['gross_t'] > 2.81).sum()} 个")
p(f"毛收益最高的模型 = {ad.iloc[0]['model']}，毛均值 = {ad.iloc[0]['gross_mean']:+.4f} USD")
p(f"  → 成本 {COST:.3f} 是它的毛收益的 {ad.iloc[0]['cost_ratio']:.1f} 倍")
p(f"\n★ 关键结论：模型不是「比随机还差」，而是「毛收益≈0，亏损≈成本」。")
p(f"  验证：净亏损 ≈ 笔数 × 成本")
for _, r in ad.head(4).iterrows():
    p(f"    {r['model']:<16} 净总盈亏={r['mean_ret']*r['n']:>9.0f}  "
      f"笔数×成本={-r['n']*COST:>9.0f}")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 92)
p("B. 需要多高的 IC 才能盈利？（功效分析：注入已知 IC 的合成信号）")
p("=" * 92)
p("说明：这是**功效分析**不是回测——用已知 IC 的信号反推门槛。")
p("      信号 = ρ·标准化未来收益 + √(1−ρ²)·噪声，故 corr(信号, 未来收益) = ρ 精确可控。")


def power_curve(tf: str, stride: int, hold: int, cost: float, label: str,
                rhos: list[float], seed: int = 7):
    df = load(tf).iloc[::stride].reset_index(drop=True)
    close = df.close.to_numpy(float)
    high = df.high.to_numpy(float)
    low = df.low.to_numpy(float)
    n = len(close)
    vol = ewma_vol(close, 60, 30)
    vol = np.where(np.isfinite(vol) & (vol > 0), vol, np.nanmedian(vol))
    sig_med = float(np.nanmedian(vol))
    fwd = np.full(n, np.nan)
    fwd[:-hold] = close[hold:] - close[:-hold]
    m = np.isfinite(fwd)
    z = np.full(n, np.nan)
    z[m] = (fwd[m] - fwd[m].mean()) / fwd[m].std()
    rng = np.random.default_rng(seed)
    p(f"\n[{label}] n={n}  σ/根={sig_med:.3f}  USD 成本={cost:.3f}  "
      f"成本/σ={cost/sig_med:.3f}")
    p(f"  {'IC(ρ)':>7}{'命中率':>9}{'净均值':>10}{'毛均值':>10}{'净NW-t':>9}{'总盈亏':>11}  判定")
    be_rho = None
    for rho in rhos:
        noise = rng.standard_normal(n)
        sig = rho * np.nan_to_num(z, nan=0.0) + np.sqrt(max(1 - rho ** 2, 0)) * noise
        sgn = np.sign(sig).astype(np.int8)
        tb = triple_barrier(close, high, low, vol, sgn, 2.0, 1.0, hold * 4, cost)
        mm = (sgn != 0) & np.isfinite(tb.ret) & (tb.bars_held > 0)
        if mm.sum() < 100:
            continue
        ret = tb.ret[mm]
        gross = ret + cost
        # NW-t
        e = ret - ret.mean()
        var = float(e @ e) / len(ret)
        for L in range(1, 31):
            var += 2 * (1 - L / 31) * float(e[L:] @ e[:-L]) / len(ret)
        t = ret.mean() / np.sqrt(max(var, 1e-18) / len(ret))
        ok = "✓盈利" if ret.mean() > 0 else ""
        if ret.mean() > 0 and be_rho is None:
            be_rho = rho
        p(f"  {rho:>7.3f}{np.mean(ret>0):>9.3f}{ret.mean():>10.4f}"
          f"{gross.mean():>10.4f}{t:>+9.2f}{ret.sum():>11.0f}  {ok}")
    return be_rho, sig_med


rhos = [0.0, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.20, 0.30, 0.40]
be1, s1 = power_curve("1m", 3, 15, COST, "1m（决策每 3 分钟）", rhos)
be5, s5 = power_curve("5m", 2, 12, COST, "5m", rhos)
be15, s15 = power_curve("15m", 1, 8, COST, "15m", rhos)

p("\n" + "=" * 92)
p("C. 盈亏平衡所需的 IC（汇总）")
p("=" * 92)
p(f"{'周期':<10}{'σ/根(USD)':>12}{'成本/σ':>10}{'盈亏平衡 IC':>14}")
p("-" * 50)
for lab, be, s in (("1m", be1, s1), ("5m", be5, s5), ("15m", be15, s15)):
    p(f"{lab:<10}{s:>12.3f}{COST/s:>10.3f}"
      f"{(f'{be:.2f}' if be is not None else '>0.40'):>14}")
p("\n参考：真实市场里「好模型」的 IC 大约是 0.02 ~ 0.05；")
p("      顶级高频/另类数据的 IC 也极少超过 0.10。")

(RES / "09_power.txt").write_text("\n".join(OUT), encoding="utf-8")
p(f"\n[已写入 research/09_power.txt]")
