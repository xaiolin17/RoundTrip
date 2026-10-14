# -*- coding: utf-8 -*-
"""研究取证 35：**做多单的止损止盈几何**（MT5 权威口径 + 真实计划 SL/TP）。

用户诉求（2026-10-14 原话）
--------------------------
1. 「现在的胜率不对啊 亏损次数大于盈利」
2. 「我要的是修改权重和止损止盈 达到提高胜率的效果 不是把数据换个方式来造假
    保证数据好看 我要的是真实的信号和操作」
3. 做多趋势闸经 34 号取证后 DSR 全 < 0.95、且放行组仍亏 → 用户决定**暂不加闸**，
   先修「做多单的止损止盈几何」（本人点名项）。

本脚本回答的三个问题
--------------------
Q1 做多的钱到底是怎么亏掉的？（按**真实出场方式**拆解：止损SL / 止盈TP / 机器人主动平）
Q2 做多与做空的**计划几何**（止损距离、止盈距离、盈亏比）有没有系统性差异？
Q3 若抬高做多首仓的**计划盈亏比下限**（RR floor），真实成交会改善吗？DSR 如何？

数据来源与口径（全部来自 MT5，不用日志、不用回放）
--------------------------------------------------
· 逐笔盈亏 = 同一 `position_id` 全部 OUT 腿的 `profit + commission + swap`；
· 方向 = 开仓腿 `type`（0=BUY/做多，1=SELL/做空）；
· **出场方式 = 平仓腿的 `reason`**：3=机器人主动平、4=止损SL、5=止盈TP
  （成交明细实测只有这三类，无手动单；用户手工单 magic 不同已被过滤）；
· **计划止损/止盈 = 开仓 order 的 `sl` / `tp`**（`history_orders_get`）。
  注意：这些成交单的 `order.price_open` 恒为 0，故入场价一律取**开仓腿的真实成交价**；
  可信度检验见【D】——止损平仓单的实际出场价应等于计划 `sl`。
· 计划 RR = 止盈距离 / 止损距离（按真实入场价计算）。

无前视声明
----------
· 计划几何（sl/tp）是**开仓前**就定好的，选单不依赖任何未来信息；
· 【G】的最大有利偏移（MFE）只统计**开仓到实际平仓之间**的 1m K 线，严格无前视。

跑法::

    & $py research/35_sl_tp_geometry.py
"""
from __future__ import annotations

import bisect
import datetime as dt
import io
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SYMBOL = "XAUUSDm"
MAGIC = 20260918
DAYS = 30

#: 出场原因（deal.reason）中文标签。实测只出现 3/4/5。
REASON_ZH = {0: "客户端手动", 1: "移动端", 2: "网页", 3: "机器人主动平",
             4: "止损SL", 5: "止盈TP", 6: "强平SO", 7: "隔夜结算", 8: "追加保证金", 9: "拆单"}

#: 试验族规模 N：本脚本评估的「首仓盈亏比下限」配置条数（用于 DSR 去膨胀）。
#: 6 个阈值 × 2 个作用范围（仅做多 / 多空对称）= 12。记入 data/trials.csv，每试一条 +1。
N_TRIALS = 12
RR_FLOORS = (1.0, 1.1, 1.2, 1.31, 1.5, 1.8)

OUT: list[str] = []


def p(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


# ══════════════════════════════════════════════════════════════════
# 数据装载
# ══════════════════════════════════════════════════════════════════
def load() -> tuple[list[dict], pd.DataFrame | None]:
    """MT5 交割单 + 历史订单 → 逐笔 position（含真实计划几何）；另返回 1m K 线。"""
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"MT5 初始化失败：{mt5.last_error()}")
    try:
        now = dt.datetime.now(dt.UTC)
        t0 = now - dt.timedelta(days=DAYS)
        deals = mt5.history_deals_get(t0, now + dt.timedelta(days=1))
        orders = mt5.history_orders_get(t0, now + dt.timedelta(days=1))
        bars = mt5.copy_rates_from(SYMBOL, mt5.TIMEFRAME_M1, now, 60000)
    finally:
        mt5.shutdown()
    if deals is None:
        raise RuntimeError("history_deals_get 返回空")

    deals = [d for d in deals if d.symbol == SYMBOL and d.magic == MAGIC]
    orders = [o for o in orders if o.symbol == SYMBOL and o.magic == MAGIC] if orders else []

    # 订单按 position_id 归集，供匹配开仓 order
    by_pid: dict = {}
    for o in orders:
        if o.position_id:
            by_pid.setdefault(o.position_id, []).append(o)

    grp: dict = {}
    for d in deals:
        grp.setdefault(d.position_id, []).append(d)

    rows: list[dict] = []
    for pid, legs in grp.items():
        legs.sort(key=lambda d: d.time)
        op = [d for d in legs if d.entry == 0]
        cl = [d for d in legs if d.entry in (1, 2)]
        if not op or not cl:
            continue
        is_long = (op[0].type == 0)
        in_px = float(op[0].price)
        t_in = float(op[0].time)
        # 开仓 order：方向一致（做多=BUY 0，做空=SELL 1），取成交时刻最接近开仓腿者
        want = 0 if is_long else 1
        cand = [o for o in by_pid.get(pid, []) if o.type == want]
        o = min(cand, key=lambda x: abs(x.time_done - t_in)) if cand else None
        sl = float(getattr(o, "sl", 0.0)) if o is not None else 0.0
        tp = float(getattr(o, "tp", 0.0)) if o is not None else 0.0
        sl_dist = abs(in_px - sl) if sl else 0.0
        tp_dist = abs(tp - in_px) if tp else 0.0
        rr = (tp_dist / sl_dist) if sl_dist > 0 else float("nan")
        rows.append(dict(
            pid=pid, is_long=is_long, t_in=t_in, t_out=float(cl[-1].time),
            in_px=in_px, out_px=float(cl[-1].price),
            reason=int(cl[-1].reason),
            pnl=float(sum(d.profit + d.commission + d.swap for d in cl)),
            vol0=float(op[0].volume),
            sl=sl, tp=tp, sl_dist=sl_dist, tp_dist=tp_dist, rr=rr))
    rows.sort(key=lambda r: r["t_in"])

    m1 = None
    if bars is not None and len(bars):
        m1 = pd.DataFrame(bars)
        m1["time"] = m1["time"].astype("int64")
        m1 = m1.sort_values("time").reset_index(drop=True)
    return rows, m1


# ══════════════════════════════════════════════════════════════════
# 统计
# ══════════════════════════════════════════════════════════════════
def summ(rows: list[dict]) -> dict:
    if not rows:
        return dict(n=0, wr=float("nan"), tot=0.0, avg=float("nan"),
                    aw=float("nan"), al=float("nan"), pf=float("nan"))
    wins = [r["pnl"] for r in rows if r["pnl"] > 0]
    loss = [r["pnl"] for r in rows if r["pnl"] < 0]
    tot = sum(r["pnl"] for r in rows)
    gw = sum(wins)
    gl = -sum(loss)
    return dict(n=len(rows), wr=len(wins) / len(rows), tot=tot, avg=tot / len(rows),
                aw=(gw / len(wins)) if wins else float("nan"),
                al=(sum(loss) / len(loss)) if loss else float("nan"),
                pf=(gw / gl) if gl > 0 else float("inf"))


def fmt(name: str, s: dict) -> str:
    if not s or s["n"] == 0:
        return f"    {name:<24} n=0"
    return (f"    {name:<24} n={s['n']:<4} 胜率 {s['wr']:>6.1%}  净 {s['tot']:>+9.2f} "
            f"均笔 {s['avg']:>+7.3f}  均盈 {s['aw']:>6.2f} 均亏 {s['al']:>7.2f} "
            f"盈亏比 {s['pf']:>5.2f}")


def dsr_of(rows: list[dict]) -> tuple[float, float, float]:
    """对逐笔美元盈亏序列算 DSR（返回 dsr, sr0, 逐笔 Sharpe）。"""
    from gold_agent.quant.labeling import deflated_sharpe
    x = np.array([r["pnl"] for r in rows], dtype=float)
    n = len(x)
    if n < 3:
        return float("nan"), float("nan"), float("nan")
    m = x.mean()
    sd = x.std(ddof=1)
    if not np.isfinite(sd) or sd <= 0:
        return float("nan"), float("nan"), float("nan")
    z = (x - m) / sd
    skew = float((z ** 3).mean())
    kurt = float((z ** 4).mean())      # 原始峰度（正态=3），与 labeling 约定一致
    sr = float(m / sd)
    dsr, sr0 = deflated_sharpe(sr, N_TRIALS, n, skew, kurt)
    return float(dsr), float(sr0), sr


def q(a: list[float]) -> str:
    if not a:
        return "n=0"
    x = np.array(a, dtype=float)
    x = x[np.isfinite(x)]
    if not len(x):
        return "n=0"
    return (f"n={len(x):<4} P10={np.percentile(x,10):>7.2f} 中位={np.median(x):>7.2f} "
            f"P90={np.percentile(x,90):>7.2f} 最小={x.min():>7.2f} 最大={x.max():>7.2f}")


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════
def main() -> int:
    p("=" * 112)
    p("研究取证 35 · 做多单的止损止盈几何（MT5 真实成交 + 真实计划 SL/TP）")
    p("=" * 112)

    rows, m1 = load()
    longs = [r for r in rows if r["is_long"]]
    shorts = [r for r in rows if not r["is_long"]]

    p("")
    p(f"  品种 {SYMBOL}  magic {MAGIC}  窗口 {DAYS} 天  已平仓 position {len(rows)} 笔"
      f"（做多 {len(longs)} / 做空 {len(shorts)}）")
    if m1 is not None and len(m1):
        p(f"  1m K 线 {len(m1)} 根："
          f"{dt.datetime.fromtimestamp(int(m1['time'].iloc[0]), dt.UTC)}"
          f" .. {dt.datetime.fromtimestamp(int(m1['time'].iloc[-1]), dt.UTC)}")

    # ---------------- A 现状 ----------------
    p("")
    p("-" * 112)
    p("【A】现状")
    p("-" * 112)
    p(fmt("做多", summ(longs)))
    p(fmt("做空", summ(shorts)))
    p(fmt("合计", summ(rows)))

    # ---------------- B 出场方式 × 方向 ----------------
    p("")
    p("-" * 112)
    p("【B】真实出场方式 × 方向（平仓腿 reason）—— 钱是怎么亏掉的")
    p("-" * 112)
    for label, sub in (("做多", longs), ("做空", shorts)):
        p(f"  ── {label}  共 {len(sub)} 笔")
        for rs in (3, 4, 5):
            g = [r for r in sub if r["reason"] == rs]
            s = summ(g)
            if not s["n"]:
                continue
            p(fmt(REASON_ZH.get(rs, str(rs)), s)
              + f"  占比 {s['n'] / len(sub):>5.1%}")

    # ---------------- C 计划几何 ----------------
    p("")
    p("-" * 112)
    p("【C】计划几何（开仓 order 的 sl/tp，按真实入场价换算距离）")
    p("-" * 112)
    for label, sub in (("做多", longs), ("做空", shorts)):
        has = [r for r in sub if r["sl_dist"] > 0]
        p(f"  ── {label}  有有效计划止损 {len(has)}/{len(sub)} 笔")
        p(f"    止损距离($) {q([r['sl_dist'] for r in has])}")
        p(f"    止盈距离($) {q([r['tp_dist'] for r in has])}")
        p(f"    计划盈亏比  {q([r['rr'] for r in has])}")
        for lo in RR_FLOORS:
            n = sum(1 for r in has if r["rr"] < lo)
            p(f"      计划RR<{lo:<5}  {n:>4} 笔")

    # ---------------- D 可信度检验 ----------------
    p("")
    p("-" * 112)
    p("【D】数据可信度检验：止损平仓单的实际出场价是否等于计划 sl")
    p("-" * 112)
    for label, sub in (("做多", longs), ("做空", shorts)):
        g = [r for r in sub if r["reason"] == 4 and r["sl_dist"] > 0]
        if not g:
            continue
        eq = sum(1 for r in g if abs(r["out_px"] - r["sl"]) < 0.05)
        g5 = [r for r in sub if r["reason"] == 5 and r["tp_dist"] > 0]
        eq5 = sum(1 for r in g5 if abs(r["out_px"] - r["tp"]) < 0.05)
        p(f"  {label}：止损单 {eq}/{len(g)} 笔出场价==计划sl；"
          f"止盈单 {eq5}/{len(g5)} 笔出场价==计划tp")
    p("  （若接近全部相等 → 计划 sl/tp 就是当时真实生效的止损止盈，可用于反事实）")

    # ---------------- E 按计划 RR 分桶 × 方向 ----------------
    p("")
    p("-" * 112)
    p("【E】按计划盈亏比分桶 × 方向 → 实际净盈亏（做多的盈亏平衡线：1/胜率-1）")
    p("-" * 112)
    edges = [0.0, 1.0, 1.1, 1.2, 1.31, 1.5, 1.8, 99.0]
    for label, sub in (("做多", longs), ("做空", shorts)):
        p(f"  ── {label}")
        for a, b in zip(edges, edges[1:]):
            g = [r for r in sub if a <= r["rr"] < b]
            if g:
                p(fmt(f"计划RR[{a:.2f},{b:.2f})", summ(g)))
        p("")

    # ---------------- F 反事实：抬高首仓 RR 下限 ----------------
    p("=" * 112)
    p("【F】反事实：抬高首仓盈亏比下限（RT 真实成交，按计划 RR 过滤）")
    p("    说明：只做「开仓前」的选单过滤，不含任何未来信息。")
    p("=" * 112)
    base = summ(rows)
    p(f"  基线（现状全组合）净 {base['tot']:+.2f}  胜率 {base['wr']:.1%}")
    p("")
    fam: dict = {}
    p("  ── 作用范围：仅做多")
    for lo in RR_FLOORS:
        keep_l = [r for r in longs if not (r["sl_dist"] > 0 and r["rr"] < lo)]
        combo = keep_l + shorts
        s = summ(combo)
        dsr, _, sr = dsr_of(combo)
        n_drop = len(longs) - len(keep_l)
        drop = [r for r in longs if r["sl_dist"] > 0 and r["rr"] < lo]
        fam[("多", lo)] = (s, dsr, sr, drop)
        d = "n/a" if not np.isfinite(dsr) else f"{dsr:.3f}"
        p(f"    RR下限 {lo:<5} 挡掉做多 {n_drop:>3} 笔(净 {summ(drop)['tot']:>+8.2f})"
          f" → 全组合 n={s['n']:<4} 净 {s['tot']:>+9.2f} 胜率 {s['wr']:>6.1%}"
          f"  逐笔Sharpe {sr:+.3f}  DSR(N={N_TRIALS}) {d}"
          + ("  通过(>0.95)" if np.isfinite(dsr) and dsr > 0.95 else ""))
    p("")
    p("  ── 作用范围：多空对称")
    for lo in RR_FLOORS:
        keep = [r for r in rows if not (r["sl_dist"] > 0 and r["rr"] < lo)]
        drop = [r for r in rows if r["sl_dist"] > 0 and r["rr"] < lo]
        s = summ(keep)
        dsr, _, sr = dsr_of(keep)
        fam[("对称", lo)] = (s, dsr, sr, drop)
        d = "n/a" if not np.isfinite(dsr) else f"{dsr:.3f}"
        p(f"    RR下限 {lo:<5} 挡掉 {len(drop):>3} 笔(净 {summ(drop)['tot']:>+8.2f})"
          f" → 组合 n={s['n']:<4} 净 {s['tot']:>+9.2f} 胜率 {s['wr']:>6.1%}"
          f"  逐笔Sharpe {sr:+.3f}  DSR(N={N_TRIALS}) {d}"
          + ("  通过(>0.95)" if np.isfinite(dsr) and dsr > 0.95 else ""))

    # 族内最优
    best_name, best_s = None, None
    for k, v in fam.items():
        s = v[0]
        if best_s is None or s["tot"] > best_s["tot"]:
            best_s, best_name = s, k
    if best_s is not None:
        p("")
        p(f"  族内净盈亏最优：{best_name[0]}侧 RR下限={best_name[1]} "
          f"→ 净 {best_s['tot']:+.2f}（基线 {base['tot']:+.2f}，"
          f"改善 {best_s['tot'] - base['tot']:+.2f}）")

    # ---------------- G MFE / MAE（无前视）----------------
    p("")
    p("=" * 112)
    p("【G】最大有利偏移 MFE（开仓→实际平仓区间内，严格无前视）")
    p("     问：做多的止盈是不是设得「市场根本给不到」？")
    p("=" * 112)
    if m1 is None or m1.empty:
        p("  拿不到 1m K 线，跳过。")
    else:
        tt = m1["time"].to_numpy()
        hi = m1["high"].to_numpy(dtype=float)
        lo = m1["low"].to_numpy(dtype=float)
        for label, sub in (("做多", longs), ("做空", shorts)):
            mfes, reach = [], []
            for r in sub:
                a = bisect.bisect_left(tt, r["t_in"])
                b = bisect.bisect_right(tt, r["t_out"])
                if b <= a:
                    continue
                if r["is_long"]:
                    mfe = float(hi[a:b].max()) - r["in_px"]
                else:
                    mfe = r["in_px"] - float(lo[a:b].min())
                mfes.append(mfe)
                if r["tp_dist"] > 0:
                    reach.append(1 if mfe >= r["tp_dist"] else 0)
            p(f"  ── {label}  持仓期最大有利偏移($) {q(mfes)}")
            if reach:
                p(f"     其中 MFE 曾达到计划止盈距离的比例：{sum(reach)}/{len(reach)} "
                  f"= {sum(reach) / len(reach):.1%}")
            # 止损平仓单：MFE 有没有到过计划止盈
            g = [r for r in sub if r["reason"] == 4 and r["tp_dist"] > 0]
            hit = 0
            for r in g:
                a = bisect.bisect_left(tt, r["t_in"])
                b = bisect.bisect_right(tt, r["t_out"])
                if b <= a:
                    continue
                mfe = (float(hi[a:b].max()) - r["in_px"]) if r["is_long"] \
                    else (r["in_px"] - float(lo[a:b].min()))
                hit += 1 if mfe >= r["tp_dist"] else 0
            if g:
                p(f"     止损平仓的 {len(g)} 笔中，曾摸到过计划止盈的仅 {hit} 笔 "
                  f"({hit / len(g):.1%}) → 这些单子不是「差一点止盈」，是方向就错了")

    # ---------------- I 出场规则重放（只改 SL/TP 距离）----------------
    p("")
    p("=" * 112)
    p("【I】出场规则重放：只改止损/止盈**距离倍数**，入场时刻与入场价保持真实不变")
    p("     规则：从真实开仓 bar 起用 1m K 线推进，先触及者成交；同一根 bar 内两者都触及 →")
    p("     保守判为**先止损**；到真实平仓时刻仍未触发 → 按当时收盘价了结（近似 4h 时间止损）。")
    p("     局限：不重建加仓腿与机器人主动平仓，故只用于比较**方向性**，不作为精确盈亏预测。")
    p("=" * 112)
    if m1 is None or m1.empty:
        p("  拿不到 1m K 线，跳过。")
    else:
        tt = m1["time"].to_numpy()
        hi = m1["high"].to_numpy(dtype=float)
        lo = m1["low"].to_numpy(dtype=float)
        cl_ = m1["close"].to_numpy(dtype=float)

        def replay(sub: list[dict], tp_mult: float, sl_mult: float) -> dict:
            """按倍数改出场规则重放，返回胜率与每 0.01 手期望盈亏($)。"""
            outs: list[float] = []
            ntp = nsl = nto = 0
            for r in sub:
                if r["sl_dist"] <= 0 or r["tp_dist"] <= 0:
                    continue
                a = bisect.bisect_left(tt, r["t_in"])
                b = bisect.bisect_right(tt, r["t_out"])
                if b <= a:
                    continue
                e = r["in_px"]
                if r["is_long"]:
                    tp_px, sl_px = e + r["tp_dist"] * tp_mult, e - r["sl_dist"] * sl_mult
                else:
                    tp_px, sl_px = e - r["tp_dist"] * tp_mult, e + r["sl_dist"] * sl_mult
                px = None
                for k in range(a, b):
                    if r["is_long"]:
                        if lo[k] <= sl_px:
                            px, hit = sl_px, "SL"; break
                        if hi[k] >= tp_px:
                            px, hit = tp_px, "TP"; break
                    else:
                        if hi[k] >= sl_px:
                            px, hit = sl_px, "SL"; break
                        if lo[k] <= tp_px:
                            px, hit = tp_px, "TP"; break
                else:
                    px, hit = float(cl_[b - 1]), "TO"
                ntp += hit == "TP"; nsl += hit == "SL"; nto += hit == "TO"
                move = (px - e) if r["is_long"] else (e - px)
                outs.append(move * r["vol0"] * 100.0)   # XAUUSD 1 手=100 盎司
            if not outs:
                return dict(n=0)
            x = np.array(outs)
            return dict(n=len(x), wr=float((x > 0).mean()), tot=float(x.sum()),
                        avg=float(x.mean()), ntp=ntp, nsl=nsl, nto=nto)

        # 试验族规模（第二族：SL/TP 距离倍数）
        tp_grid = (0.5, 0.7, 1.0)
        sl_grid = (0.7, 1.0, 1.5)
        p(f"  网格：止盈倍数 {tp_grid} × 止损倍数 {sl_grid} = "
          f"{len(tp_grid) * len(sl_grid)} 个配置（作用范围：做多；做空仅作对照）")
        p("")
        for label, sub in (("做多", longs), ("做空", shorts)):
            p(f"  ── {label}（真实成交：n={len(sub)} 净 {summ(sub)['tot']:+.2f} "
              f"胜率 {summ(sub)['wr']:.1%}）")
            for slm in sl_grid:
                for tpm in tp_grid:
                    d = replay(sub, tpm, slm)
                    if not d.get("n"):
                        continue
                    p(f"    止盈×{tpm:<4} 止损×{slm:<4} → n={d['n']:<4} 胜率 {d['wr']:>6.1%} "
                      f"期望 {d['avg']:>+7.3f}$/笔  合计 {d['tot']:>+8.2f}  "
                      f"(TP {d['ntp']} / SL {d['nsl']} / 超时 {d['nto']})")
            p("")

    # ---------------- H 判读 ----------------
    p("")
    p("=" * 112)
    p("【H】判读")
    p("=" * 112)
    sl_l = summ([r for r in longs if r["reason"] == 4])
    tp_l = summ([r for r in longs if r["reason"] == 5])
    ex_l = summ([r for r in longs if r["reason"] == 3])
    sl_s = summ([r for r in shorts if r["reason"] == 4])
    tp_s = summ([r for r in shorts if r["reason"] == 5])
    ex_s = summ([r for r in shorts if r["reason"] == 3])
    p(f"  · 做多：止损 {sl_l['n']} 笔({sl_l['n'] / len(longs):.1%}) 净 {sl_l['tot']:+.2f}；"
      f"止盈 {tp_l['n']} 笔({tp_l['n'] / len(longs):.1%}) 净 {tp_l['tot']:+.2f}；"
      f"机器人主动平 {ex_l['n']} 笔({ex_l['n'] / len(longs):.1%}) 净 {ex_l['tot']:+.2f}")
    p(f"  · 做空：止损 {sl_s['n']} 笔({sl_s['n'] / len(shorts):.1%}) 净 {sl_s['tot']:+.2f}；"
      f"止盈 {tp_s['n']} 笔({tp_s['n'] / len(shorts):.1%}) 净 {tp_s['tot']:+.2f}；"
      f"机器人主动平 {ex_s['n']} 笔({ex_s['n'] / len(shorts):.1%}) 净 {ex_s['tot']:+.2f}")
    p(f"  · 试验族 N={N_TRIALS}（6 阈值 × 2 作用范围）须记入 data/trials.csv。")
    p("  · 采用门槛：组合净改善、且 DSR>0.95；否则不落地。")

    out = ROOT / "research" / "35_sl_tp_geometry_out.txt"
    try:
        out.write_text("\n".join(OUT), encoding="utf-8")
        p(f"\n已保存：{out.relative_to(ROOT)}")
    except Exception as e:
        p(f"\n（保存失败：{e}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
