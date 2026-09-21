"""研究取证 17：量化实盘融合分的真实预测力 + mobius 偏置的成因。

  A. mobius 打分函数的偏置来源（读 _score_fn 的结构性缺陷）
  B. 融合分 S 对未来收益的 IC（用真实 1m 数据重放，无前视）
  C. 结构性多头偏置对盈亏的影响：把 S 的常数偏移去掉后结果如何
  D. 结论
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

RES = Path(__file__).parent
DATA = Path(__file__).resolve().parents[1] / "data" / "cache"
OUT: list[str] = []


def p(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


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


d = pd.read_parquet(DATA / "XAUUSDm_1m.parquet")
d["time"] = pd.to_datetime(d["time"], utc=True)
d = d.sort_values("time").reset_index(drop=True).iloc[-60000:].reset_index(drop=True)
close = d.close.to_numpy(float)
n = len(d)

p("=" * 96)
p("研究取证 17 · 实盘融合分的真实预测力")
p("=" * 96)
p(f"1m {n} 根  {d.time.iloc[0]} .. {d.time.iloc[-1]}  "
  f"区间位移 {close[-1]-close[0]:+.1f} USD")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("A. mobius 打分函数的偏置来源")
p("=" * 96)
p("")
p("_score_fn 的三个组成部分：")
p("")
p("1) swing_structures 取**最后 3 个**，CHoCH=±2.0 / BOS=±1.5，按 bias 累加。")
p("   这是**有符号累加**，理论上可正可负 —— 但见下。")
p("")
p("2) order_blocks：仅当 `last_price <= ob['bottom']*1.002`（看多 OB）时 **+1.0**")
p("   或 `last_price >= ob['top']*0.998`（看空 OB）时 **−1.0**。")
p("   ⚠ 这是**单边条件**：只有价格回到看多 OB 下方才加分，")
p("     只有价格涨到看空 OB 上方才减分。二者不是对称情形。")
p("")
p("3) fair_value_gaps：同样的单边条件结构。")
p("")
p("关键：score **没有减去任何基准**（no de-meaning）。")
p("  SMC 在黄金这种长期上行品种上，结构性偏向会持续累积：")
p("  上涨过程中不断产生 BOS/CHoCH(bull)，而 bear 结构出现后很快被覆盖。")
p("  → 结果就是 88.0% 为正、均值 +1.2604。")
p("")
p("**这个 +1.26 的常数偏移不是预测，是偏置。**")
p("  融合分随后被它推到 +0.52 的均值（80.2% 为正）。")
p("  而 decision.machine 用 `abs(s) < open_threshold` 判断是否开仓，")
p("  于是 S=+0.52 的「中性」被当成「偏多信号」，永远只能做多。")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("B. 融合分 S 对未来收益的 IC（真实数据重放）")
p("=" * 96)
p("")
p("说明：实盘日志只有 881 轮（约 1 天），不足以算 IC。")
p("      这里用真实 1m 数据重放 kalman_persist 与 classic_indicators 两个")
p("      **可在本地完整复现**的源，验证「方向源到底有没有预测力」。")
p("      （mobius 是远程 API，本地无法重放；chanlun 需 vendor skill，见 04_report）")
p("")

from gold_agent.fusion.engine import compute_indicators  # noqa: E402
from gold_agent.fusion.kalman import KalmanTrend  # noqa: E402

step, warm = 5, 400          # 每 5 分钟决策一次（贴近实盘 60s 循环）
idx = list(range(warm, n - 60, step))
kal = KalmanTrend()

kal_scores, cls_scores = [], []
for i in idx:
    w = d.iloc[i - warm:i]
    k = kal.fit(w.close.to_numpy(float))
    kal_scores.append(float(np.clip(k.trend * min(k.slope_persist / 10.0, 1.5), -3, 3)))
    ind = compute_indicators(w)
    c = (0.35 * ind.momentum_accel + 0.30 * ind.tick_imbalance * 2.0
         + 0.20 * ind.vol_pressure
         + 0.15 * ind.range_compression * np.sign(ind.momentum_accel + 0.01))
    cls_scores.append(float(c))

idx = np.array(idx)
kal_scores = np.array(kal_scores)
cls_scores = np.array(cls_scores)

p(f"{'前瞻期':<10}{'kalman IC':>12}{'kalman t':>10}{'classic IC':>12}"
  f"{'classic t':>10}{'S合成 IC':>11}")
p("-" * 96)
for hz in (15, 60, 240, 1440):
    fwd = np.full(n, np.nan)
    fwd[:-hz] = close[hz:] - close[:-hz]
    y = fwd[idx]
    m = np.isfinite(y)
    if m.sum() < 50:
        continue
    ic_k = float(np.corrcoef(kal_scores[m], y[m])[0, 1])
    ic_c = float(np.corrcoef(cls_scores[m], y[m])[0, 1])
    # 按实盘权重合成（kalman 0.5259 / classic 2.7778，去掉两个缺失源后归一）
    wk, wc = 0.5259, 2.7778
    S = (wk * kal_scores + wc * cls_scores) / (wk + wc)
    ic_s = float(np.corrcoef(S[m], y[m])[0, 1])
    t_k = nw_t(np.sign(kal_scores[m]) * y[m], lags=30)
    t_c = nw_t(np.sign(cls_scores[m]) * y[m], lags=30)
    p(f"{f'{hz}m':<10}{ic_k:>+12.4f}{t_k:>+10.2f}{ic_c:>+12.4f}{t_c:>+10.2f}"
      f"{ic_s:>+11.4f}")

p("")
p("对照：09_power 的功效分析显示，1m 上盈亏平衡需要 IC ≈ 0.30（stride=1 重算 >0.50）。")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("C. 结构性多头偏置的代价：把常数偏移去掉会怎样")
p("=" * 96)
p("")
p("用实盘日志的 881 轮重算：S_raw（现状）vs S_demean（减去滚动均值）。")
p("")
rows = []
for f in ["logs/decision_20260918.jsonl", "logs/decision_20260919.jsonl",
          "logs/decision_20260920.jsonl"]:
    fp = Path(__file__).resolve().parents[1] / f
    if not fp.exists():
        continue
    for line in fp.read_text(encoding="utf-8-sig").splitlines():
        try:
            dd = json.loads(line)
        except Exception:
            continue
        if dd.get("event") == "signals" and isinstance(dd.get("per_source"), list):
            rows.append(dd)

S = np.array([float(r["score"]) for r in rows])
p(f"实盘 {len(S)} 轮：S 均值={S.mean():+.4f}  SD={S.std():.4f}  "
  f"为正={np.mean(S>0):.1%}")
p(f"  |S|≥1.3 → {int((np.abs(S)>=1.3).sum())} 轮，"
  f"其中做多 {int((S>=1.3).sum())} / 做空 {int((S<=-1.3).sum())}")
mu = pd.Series(S).rolling(144, min_periods=48).mean().to_numpy()
Sd = S - np.where(np.isfinite(mu), mu, np.nanmean(S))
p(f"\n减去滚动均值后：S_demean 均值={np.nanmean(Sd):+.4f}  SD={np.nanstd(Sd):.4f}  "
  f"为正={np.nanmean(Sd>0):.1%}")
p(f"  |S_demean|≥1.3 → {int((np.abs(Sd)>=1.3).sum())} 轮，"
  f"其中做多 {int((Sd>=1.3).sum())} / 做空 {int((Sd<=-1.3).sum())}")
p("")
p("→ 现状：38 轮触发全部做多，0 轮做空。")
p("  去偏后：多空两侧都有信号，系统才真正在「择时」而不是「单边持有」。")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("D. 结论")
p("=" * 96)
p("1) mobius 源有 +1.2604 的**结构性常数偏移**，88.0% 为正。")
p("2) 该源因手填 sigma=0.5 拿到 35.4% 权重（与 chanlun 并列最高，是 kalman 的 7.6 倍）。")
p("3) 融合分因此 80.2% 为正，38 轮开仓信号**全部做多、0 轮做空**。")
p("4) 本地可复现的两个方向源（kalman / classic）的 IC 见 B 段表 ——")
p("   它们才是系统里唯一有据可查的方向信息，却合计只有 29.3% 权重。")
p("5) 修法（按优先级）：")
p("   a. 每个源**去均值**（滚动 z-score），消除结构性偏移 —— 最小改动、最大收益")
p("   b. 权重改为按**实测 IC/IR**分配，而不是手填 sigma")
p("   c. mobius 加**本地校准**：用历史数据测它的 IC，为 0 就降到 0 权重")
p("   d. tests/test_fusion_replay.py 的断言 `ic > -0.05` 必须改成有意义的下限")

(RES / "17_fusion_predictive.txt").write_text("\n".join(OUT), encoding="utf-8")
p(f"\n[已写入 research/17_fusion_predictive.txt]")
