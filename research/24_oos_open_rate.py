# -*- coding: utf-8 -*-
"""决定性测量：完全复刻实盘流程，测「预热后、样本外」的开仓率。

实盘流程：
  1. 启动时用最近 300 根 1m 预热（prime_history）
  2. 之后每 60 秒用最新 600 根 payload 决策一轮

本脚本严格照做，只是在**历史数据**上滚动前进：
  - 在 t0 处预热
  - 从 t0 之后开始逐轮决策（预热**从未见过**这些 bar）
  - 统计开仓率

这样得到的开仓率才是实盘的诚实估计。

验收线（research/18 的"必须能开仓"要求）
----------------------------------------
- 开仓率 ≥ 10%（远高于 0 才算"能开仓"）
- LONG 占比在 25%~75% 之间（不得单边押注）
- 在**多个**不同预热点上都成立（不是某一段行情的偶然）

跑法::

    & $py research/24_oos_open_rate.py            # 全部预热点
    & $py research/24_oos_open_rate.py --quick    # 只跑 2 个点
"""
import sys
import argparse
sys.path.insert(0, "src")

# ⚠️ 必须在导入 DecisionEngine **之前**静默文件日志。
#    `DecisionEngine.decide()` 内部会 `decision_log(...)`，回放会往
#    `logs/decision_YYYYMMDD.jsonl` 灌入数千条**伪造轮次**
#    （实测 R14847/R29915/R44543… 与实盘 R23xx 交错），
#    导致实盘日志不可读。
from gold_agent.common import logging_util
logging_util.set_silent(True)
logging_util.set_source("research")

import numpy as np
import pandas as pd
from gold_agent.fusion.engine import FusionEngine
from gold_agent.skills.chanlun_adapter import analyze_tf
from gold_agent.decision.machine import (DecisionContext, DecisionEngine,
                                         effective_score)
from gold_agent.mt5.client import PositionsView
from gold_agent.risk.gate import RiskGate
from gold_agent.risk.position import CircuitBreakers
from gold_agent.risk.grid import GridState
from gold_agent.news.collector import NewsView
from gold_agent.common.config import CFG

PAYLOAD = 600          # MT5 每周期返回的 bar 数
PRIME_STEPS = 300      # 预热步数
ROUNDS = 600           # 样本外轮数（每轮前进 1 根 1m）


def frame(df, rule):
    wi = df.set_index("time")
    v = "tick_volume" if "tick_volume" in wi.columns else "volume"
    x = wi.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                               "close": "last", v: "sum"}).dropna()
    x["spread"] = 0
    x["real_volume"] = 0
    if "tick_volume" not in x.columns:
        x["tick_volume"] = x.get("volume", 0)
    return x[["open", "high", "low", "close", "tick_volume", "spread", "real_volume"]]


def payload_at(d, i):
    """模拟实盘：取截至 i 的最近 PAYLOAD 根 1m，各周期按比例取样。"""
    w = d.iloc[max(0, i - PAYLOAD):i]
    return {"1m": frame(w, "1min"), "5m": frame(w, "5min"),
            "15m": frame(w, "15min"), "1h": frame(w, "1h")}


def run_one(d, t0, rounds, verbose=False):
    """在一个预热点上跑样本外回放，返回统计字典。"""
    eng = FusionEngine()
    eng.prime_history(payload_at(d, t0), n_steps=PRIME_STEPS, step_bars=1)
    if verbose:
        print(f"  预热: kalman n={eng.normalizer.count('kalman_persist')} "
              f"baseline n={eng.baseline.count()} value={eng.baseline.value:+.4f}")

    de = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    kinds, dirs, eff = {}, [], []
    for i in range(t0 + 1, t0 + 1 + rounds):
        if i >= len(d):
            break
        fr = payload_at(d, i)
        cl = {tf: analyze_tf(fr[tf], tf) for tf in ("5m", "15m", "1h")}
        ev = eng.fuse_all(fr, cl, {}, obs_id=i)
        ctx = DecisionContext(ev=ev, positions=PositionsView(positions=[]),
                              news=NewsView(high_risk_window=False), llm=None,
                              last_close=float(fr["1m"]["close"].iloc[-1]),
                              atr=17.3, realized_vol=0.008,
                              round_id=i, llm_available=False)
        pr = de.decide(ctx)
        kinds[pr.kind] = kinds.get(pr.kind, 0) + 1
        if pr.direction:
            dirs.append(pr.direction)
        eff.append(effective_score(ev.result.score, ev.result.score_baseline))

    n = len(eff)
    a = np.array(eff) if n else np.array([0.0])
    op = sum(v for k, v in kinds.items() if k in ("open_market", "place_grid"))
    return {"t0": t0, "n": n, "opens": op, "rate": op / n if n else 0.0,
            "long": dirs.count("LONG"), "short": dirs.count("SHORT"),
            "long_frac": (dirs.count("LONG") / len(dirs)) if dirs else 0.5,
            "s_mean": float(a.mean()), "s_std": float(a.std()),
            "kinds": kinds}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="只跑 2 个预热点")
    ap.add_argument("--rounds", type=int, default=ROUNDS)
    args = ap.parse_args()

    d = pd.read_parquet("data/cache/XAUUSDm_1m.parquet")
    d["time"] = pd.to_datetime(d["time"], utc=True)
    d = d.sort_values("time").reset_index(drop=True)
    print(f"数据: {len(d)} 根 1m, {d['time'].iloc[0]} .. {d['time'].iloc[-1]}")

    # 多个预热点：覆盖不同行情段，避免"某一段的偶然"
    last = len(d) - args.rounds - 10
    if args.quick:
        points = [last]
    else:
        points = [last, last // 2, last // 4, last * 3 // 4]
    points = sorted({p for p in points if p > PAYLOAD + PRIME_STEPS + 100})

    print(f"预热点 {len(points)} 个，每点样本外 {args.rounds} 轮\n")
    results = []
    for t0 in points:
        r = run_one(d, t0, args.rounds, verbose=True)
        results.append(r)
        print(f"  t0={t0:>6}  开仓 {r['opens']:>4}/{r['n']:<4} = {r['rate']:>6.1%}   "
              f"LONG {r['long_frac']:>5.1%}   S_eff {r['s_mean']:+.3f}±{r['s_std']:.3f}")
        if r["kinds"]:
            print(f"            {r['kinds']}")

    print()
    print("=" * 62)
    rates = [r["rate"] for r in results]
    longs = [r["long_frac"] for r in results]
    tot_l = sum(r["long"] for r in results)
    tot_s = sum(r["short"] for r in results)
    pooled = tot_l / (tot_l + tot_s) if (tot_l + tot_s) else 0.5
    print(f"开仓率: 均值 {np.mean(rates):.1%}  最低 {min(rates):.1%}  最高 {max(rates):.1%}")
    print(f"LONG 占比: 各窗口 {min(longs):.1%}~{max(longs):.1%}   合计 {pooled:.1%}"
          f"  (LONG {tot_l} / SHORT {tot_s})")

    # ⚠️ 判据说明：**不能**要求每个窗口内部多空均衡。
    #    趋势跟踪系统在下跌窗口就该偏空、上涨窗口偏多 ——
    #    强行要求每个窗口 50/50 等于要求它在半个市场里做错。
    #    真正要排除的是**结构性偏置**：无论行情如何都押同一侧。
    #    因此判据是：
    #      (a) 合计多空接近均衡（无恒定偏向）
    #      (b) 各窗口占比**有变化**（方向随行情调整，而不是被钉死）
    ok_rate = min(rates) >= 0.10
    ok_pooled = 0.25 <= pooled <= 0.75
    # 单窗口时"各窗口有变化"无法判定（1 个点谈不上变化）→ 跳过该项，
    # 否则 `--quick` 会稳定误报 FAIL。
    if len(results) >= 2:
        ok_varies = ((max(longs) - min(longs)) >= 0.10
                     and max(longs) < 0.95 and min(longs) > 0.05)
    else:
        ok_varies = 0.05 < pooled < 0.95
    print()
    print(f"  [{'OK ' if ok_rate else 'FAIL'}] 每个预热点开仓率 >= 10%（能开仓）")
    print(f"  [{'OK ' if ok_pooled else 'FAIL'}] 合计 LONG 占比在 25%~75%（无结构性偏置）")
    label = ("各窗口 LONG 占比有变化（方向随行情，未被钉死）"
             if len(results) >= 2 else "LONG 占比未接近极端（单窗口，跳过变化判定）")
    print(f"  [{'OK ' if ok_varies else 'FAIL'}] {label}")
    print()
    ok = ok_rate and ok_pooled and ok_varies
    print("总判定:", "PASS - 系统在样本外稳定开仓且方向无结构性偏置"
          if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
