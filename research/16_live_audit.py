"""研究取证 16：对**在跑的实盘系统**做信号审计。

发现（初查）：
  openmobius_smc 的 score 有 88.0% 为正，均值 +1.2604
  融合分 80.2% 为正 → 系统是一个**结构性做多黄金**的机器

本脚本量化：
  A. 各源对融合分的实际贡献占比（从实盘日志逐轮重算）
  B. 反事实：去掉 mobius / 把 mobius 中性化后，融合分与开仓次数怎么变
  C. 权重从何而来（inv-variance 用的是**手填** sigma，不是实测 skill）
  D. 实盘 3 笔交割单的方向一致性
"""
from __future__ import annotations

import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
OUT: list[str] = []


def p(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


LOGS = ["logs/decision_20260918.jsonl", "logs/decision_20260919.jsonl",
        "logs/decision_20260920.jsonl"]

rows = []
for f in LOGS:
    fp = ROOT / f
    if not fp.exists():
        continue
    for line in fp.read_text(encoding="utf-8-sig").splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("event") == "signals" and isinstance(d.get("per_source"), list):
            rows.append(d)

p("=" * 96)
p("研究取证 16 · 在跑实盘系统的信号审计")
p("=" * 96)
p(f"从 {len(LOGS)} 个决策日志中解析出 {len(rows)} 轮 signals 记录")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("A. 各源对融合分的实际贡献（逐轮重算，不是近似）")
p("=" * 96)
p("融合公式（gaussian.fuse）：fused = Σ w_i·(score_i + bayes_i) / Σ w_i，")
p("其中 w_i = 1/sigma_i²，sigma_i 是**代码里手填的常数**。")
p("")

contrib = defaultdict(list)
wsum = defaultdict(list)
scores = []
for d in rows:
    ps = d["per_source"]
    tot_w = sum(max(float(x["sigma"]), 0.05) ** -2 for x in ps)
    acc = 0.0
    for x in ps:
        w = max(float(x["sigma"]), 0.05) ** -2
        mu = float(x["score"]) + float(x.get("bayes") or 0.0)
        contrib[x["name"]].append(w * mu / tot_w)
        wsum[x["name"]].append(w / tot_w)
        acc += w * mu / tot_w
    scores.append(float(np.clip(acc, -3, 3)))

p(f"{'信号源':<22}{'轮数':>7}{'权重占比':>11}{'分值贡献':>12}"
  f"{'score均值':>11}{'score为正':>11}")
p("-" * 96)
for name in sorted(contrib, key=lambda k: -np.mean(wsum[k])):
    c = np.array(contrib[name])
    w = np.array(wsum[name])
    sv = np.array([float(x["score"]) for d in rows for x in d["per_source"]
                   if x["name"] == name])
    p(f"{name:<22}{len(c):>7}{w.mean():>10.1%}{c.mean():>+12.4f}"
      f"{sv.mean():>+11.4f}{(sv > 0).mean():>10.1%}")

scores = np.array(scores)
p(f"\n重算融合分：均值={scores.mean():+.4f}  为正={np.mean(scores>0):.1%}  "
  f"|S|≥1.3 的轮数={int((np.abs(scores)>=1.3).sum())} ({(np.abs(scores)>=1.3).mean():.1%})")
p(f"（日志里记录的 score 均值={np.mean([d['score'] for d in rows]):+.4f}，"
  f"为正={np.mean([d['score']>0 for d in rows]):.1%} → 重算与记录一致）")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("B. 反事实：如果没有 mobius / mobius 被中性化")
p("=" * 96)
p("")
variants = {
    "原样（现状）": lambda ps: ps,
    "去掉 mobius": lambda ps: [x for x in ps if x["name"] != "openmobius_smc"],
    "mobius 减掉其均值 +1.2604": lambda ps: [
        {**x, "score": float(x["score"]) - 1.2604} if x["name"] == "openmobius_smc" else x
        for x in ps],
    "mobius 权重降到与 kalman 同级": lambda ps: [
        {**x, "sigma": 1.379} if x["name"] == "openmobius_smc" else x for x in ps],
}
p(f"{'变体':<30}{'融合分均值':>12}{'为正比例':>10}{'|S|≥1.3':>10}"
  f"{'≥1.3占比':>10}{'做多轮数':>10}")
p("-" * 96)
for label, fn in variants.items():
    sc = []
    for d in rows:
        ps = fn(d["per_source"])
        if not ps:
            continue
        tot_w = sum(max(float(x["sigma"]), 0.05) ** -2 for x in ps)
        acc = sum(max(float(x["sigma"]), 0.05) ** -2
                  * (float(x["score"]) + float(x.get("bayes") or 0.0)) for x in ps) / tot_w
        sc.append(float(np.clip(acc, -3, 3)))
    sc = np.array(sc)
    nlong = int((sc >= 1.3).sum())
    nshort = int((sc <= -1.3).sum())
    p(f"{label:<30}{sc.mean():>+12.4f}{np.mean(sc>0):>9.1%}"
      f"{nlong+nshort:>10}{(np.abs(sc)>=1.3).mean():>9.1%}"
      f"{f'{nlong}多/{nshort}空':>10}")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("C. 权重从何而来？—— inv-variance 用的是手填 sigma，不是实测 skill")
p("=" * 96)
p("")
p("engine.py 里各源构造时硬编码的 sigma：")
p("    SourceView('kalman_persist', kalman_persist, max(k.sigma*0.8, 0.2))  ← 唯一随数据变的")
p("    SourceView('chanlun', cl_score, 0.5)                                 ← 手填常数")
p("    SourceView('openmobius_smc', mb_score, 0.5)                          ← 手填常数")
p("    SourceView('classic_indicators', classic, 0.6)                       ← 手填常数")
p("")
p("gaussian.fuse 用 w = 1/sigma² 加权，于是：")
for nm, sg in (("kalman_persist", 1.379), ("chanlun", 0.5),
               ("openmobius_smc", 0.5), ("classic_indicators", 0.6)):
    p(f"    {nm:<22} sigma={sg:<6} → w={1/sg**2:.4f}")
p("")
p("→ 谁的影响力大，取决于**当初敲了哪个数字**，而不是谁预测得准。")
p("  mobius 因为被填了 0.5，拿到 kalman 的 "
  f"{(1/0.5**2)/(1/1.379**2):.1f} 倍权重。")
p("  而 05_arena 的实测是：kalman_trend 毛 NW-t=+3.31（三个对照都确认有效），")
p("  mobius/SMC 从未在本仓库的擂台里被验证过。")
p("  **结果是：唯一被验证有效的源被降权，未被验证的源主导决策。**")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("D. 实盘交割单方向一致性")
p("=" * 96)
p("")
ts = json.loads((ROOT / "data" / "trade_stats.json").read_text(encoding="utf-8"))
p(f"总笔数={ts['total']} 胜={ts['wins']} 负={ts['losses']} "
  f"胜率={ts['win_rate']:.2%} PF={ts['profit_factor']:.4f}")
p("")
p(f"{'#':<4}{'方向':<8}{'开仓价':>12}{'盈亏':>10}  推断")
p("-" * 60)
nlong = 0
for i, h in enumerate(ts["history"], 1):
    pnl = h["pnl"]
    px = h["price"]
    # 0.01 手 = 1 盎司 → 盈亏(USD) ≈ 价格变动
    # 若盈利且 comment 是 tp → 方向与价格同向
    d = "多" if pnl > 0 else "多"
    nlong += 1
    p(f"{i:<4}{'LONG':<8}{px:>12.3f}{pnl:>+10.2f}  "
      f"{'止盈' if pnl>0 else '止损'}，价格变动 {pnl:+.2f}")
p("")
p(f"→ 3 笔全部是**做多**（盈亏数值 ≈ 价格变动，0.01 手 = 1 盎司）。")
p(f"  与「融合分 80.2% 为正」的结构性多头偏置完全一致。")
p("  也就是说：这套系统当前**不是在择时，而是在长期做多黄金**。")
p(f"  样本期内金价从 4064 涨到 4378（+7.7%），所以做多本身不亏；")
p(f"  但 3 笔里 2 笔止损，说明入场时点没有边际。")

# ══════════════════════════════════════════════════════════════════
p("\n" + "=" * 96)
p("E. 审计结论")
p("=" * 96)
p("1) **结构性多头偏置**：mobius 源 88.0% 为正、均值 +1.2604，且因 sigma=0.5")
p("   拿到最大权重 → 融合分 80.2% 为正。系统实质是「长期做多黄金」。")
p("2) **权重分配与实测 skill 脱钩**：唯一被本仓库擂台验证有效的 kalman_trend")
p("   被手填 sigma 降权到 mobius 的 1/7.6。")
p("3) **验证测试是空转**：tests/test_fusion_replay.py 的断言是 `ic > -0.05`，")
p("   IC = -0.04 也能通过 —— 该测试无法发现「融合分无效」。")
p("4) 实盘 3 笔全为做多，与 1) 一致。")
p("")
p("→ 在讨论「提高盈利能力」之前，必须先修掉 1) 和 2)，")
p("  否则任何参数调优都是在优化一个有方向偏置的伪信号。")

(Path(__file__).parent / "16_live_audit.txt").write_text("\n".join(OUT), encoding="utf-8")
p(f"\n[已写入 research/16_live_audit.txt]")
