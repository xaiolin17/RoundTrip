# -*- coding: utf-8 -*-
"""研究取证 34：**做多方向趋势闸** 的真实成交反事实（MT5 权威口径）。

用户诉求（2026-10-14 原话）
--------------------------
1. 「现在的胜率不对啊 亏损次数大于盈利」
2. 「我要的是修改权重和止损止盈 达到提高胜率的效果 不是把数据换个方式来造假
    保证数据好看 我要的是真实的信号和操作」
3. 选定方案：**做多单额外加趋势确认**（权重线经 33 号取证判定为数学空操作，放弃）。

为什么用 MT5 真实成交而不是回放
--------------------------------
`research/33` 用 decision 日志 + 1m K 线**回放**，基线胜率仅 2.4%，与 MT5 权威
口径的 42.4%/51.1% 严重脱节（`entry_ref` 非当时市价、同一 position 多腿被当
独立样本、真实平仓规则未建模）。故本脚本**只信 MT5 交割单**：

· 逐笔盈亏 = 同一 `position_id` 全部 OUT 腿的 `profit + commission + swap` 之和；
· 方向 = 开仓腿的 `type`（0=买/做多，1=卖/做空）；
· 开仓时刻 = 开仓腿的 `time`（服务器时钟，与 4h K 线同钟，无时区换算问题）。

趋势判据（**严格无前视**）
--------------------------
对每个开仓时刻 t，取**最后一根已收盘**的 4h K 线（open_time + 4h <= t）收盘价
与其 EMA(period) 比较：`close > EMA` → 该周期趋势向上。EMA 用截至该根为止的
序列递推（`ewm(adjust=False)`），不含 t 之后任何信息。

候选规则（做多侧：不满足 → 不开多/不加多；做空侧不动，本脚本只做统计对照）
------------------------------------------------------------------------
R1 4h 价 > EMA50        R2 4h EMA20 > EMA50
R3 4h 价 > EMA50 且 EMA20 > EMA50        R4 4h 价 > EMA100

多空对称口径（S1..S4，同上判据的镜像）：做多需在均线上方、做空需在均线下方，
即「只做与 4h 趋势同向的单」。试验族 N = 4 + 4 = 8。

判读口径
--------
· 若「被闸挡掉的做多单」净盈亏明显为负 → 闸是真实改善（去掉负期望交易）。
· 若挡掉组为正 → 与最终结论相反，**不应**加闸。
· 同时报告「放行组」与「全组合（做多放行 + 做空全部）」的净盈亏/胜率，
  以及组合层面的 DSR（按逐笔美元盈亏序列）。

跑法::

    & $py research/34_long_trend_gate.py
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
H4_SEC = 4 * 3600

#: 试验族规模 N：本脚本评估的候选规则条数（用于 DSR 去膨胀）。
#: 4 条「仅做多闸」（R1..R4）+ 4 条「多空对称趋势一致闸」（S1..S4）= 8。
#: 记入 data/trials.csv，每试一条 +1。
N_TRIALS = 8

OUT: list[str] = []


def p(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


# ══════════════════════════════════════════════════════════════════
# 数据
# ══════════════════════════════════════════════════════════════════
def load_positions() -> list[dict]:
    """MT5 交割单 → 逐笔已平仓 position（权威口径）。"""
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"MT5 初始化失败：{mt5.last_error()}")
    try:
        now = dt.datetime.now(dt.UTC)
        deals = mt5.history_deals_get(now - dt.timedelta(days=DAYS),
                                      now + dt.timedelta(days=1))
        bars = mt5.copy_rates_from(SYMBOL, mt5.TIMEFRAME_H4, now, 1000)
    finally:
        mt5.shutdown()
    if deals is None:
        raise RuntimeError("history_deals_get 返回空")
    deals = [d for d in deals if d.symbol == SYMBOL and d.magic == MAGIC]

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
        pnl = sum(d.profit + d.commission + d.swap for d in cl)
        rows.append(dict(pid=pid,
                         is_long=(op[0].type == 0),
                         t_in=float(op[0].time),
                         t_out=float(cl[-1].time),
                         comment=(op[0].comment or ""),
                         pnl=float(pnl)))
    rows.sort(key=lambda r: r["t_in"])

    h4 = None
    if bars is not None and len(bars):
        h4 = pd.DataFrame(bars)
        h4["time"] = h4["time"].astype("int64")
        h4 = h4.sort_values("time").reset_index(drop=True)
    return rows, h4


# ══════════════════════════════════════════════════════════════════
# 无前视 4h 趋势
# ══════════════════════════════════════════════════════════════════
def build_trend(h4: pd.DataFrame) -> dict:
    """预计算 4h 各周期 EMA，并给出「截至每根收盘」的判据数组。"""
    t = h4["time"].to_numpy()
    c = h4["close"].to_numpy(dtype=float)
    emas = {per: h4["close"].ewm(span=per, adjust=False).mean().to_numpy()
            for per in (20, 50, 100)}
    return dict(t=t, c=c, emas=emas)


def trend_at(tr: dict, t: float) -> dict:
    """开仓时刻 t 的 4h 趋势判据（只用 t 之前**已收盘**的 bar）。"""
    # 已收盘 bar：open_time + 4h <= t  →  open_time <= t - 4h
    idx = bisect.bisect_right(tr["t"], t - H4_SEC) - 1
    if idx < 0:
        return dict(ok=False)
    close = float(tr["c"][idx])
    e20 = float(tr["emas"][20][idx])
    e50 = float(tr["emas"][50][idx])
    e100 = float(tr["emas"][100][idx])
    if not all(np.isfinite(v) for v in (close, e20, e50, e100)):
        return dict(ok=False)
    return dict(ok=True, close=close, e20=e20, e50=e50, e100=e100,
                r1=close > e50, r2=e20 > e50, r4=close > e100,
                s1=close < e50, s2=e20 < e50, s4=close < e100)


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
    return dict(n=len(rows), wr=len(wins) / len(rows), tot=tot,
                avg=tot / len(rows),
                aw=(gw / len(wins)) if wins else float("nan"),
                al=(sum(loss) / len(loss)) if loss else float("nan"),
                pf=(gw / gl) if gl > 0 else float("inf"))


def fmt(name: str, s: dict) -> str:
    if not s or s["n"] == 0:
        return f"    {name:<20} n=0"
    return (f"    {name:<20} n={s['n']:<4} 胜率 {s['wr']:>6.1%}  净 {s['tot']:>+9.2f} "
            f"均笔 {s['avg']:>+7.3f}  均盈 {s['aw']:>6.2f} 均亏 {s['al']:>7.2f} "
            f"盈亏比 {s['pf']:>5.2f}")


def dsr_of(rows: list[dict]) -> tuple[float, float, float]:
    """对逐笔美元盈亏序列算 DSR（返回 dsr, sr0, per-trade sharpe）。"""
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


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════
def main() -> int:
    p("=" * 108)
    p("研究取证 34 · 做多方向趋势闸（MT5 真实成交口径，4h 趋势无前视）")
    p("=" * 108)

    rows, h4 = load_positions()
    if h4 is None or h4.empty:
        p("!! 拿不到 4h K 线，无法判定趋势。")
        return 1
    tr = build_trend(h4)

    longs = [r for r in rows if r["is_long"]]
    shorts = [r for r in rows if not r["is_long"]]
    p("")
    p(f"  品种 {SYMBOL}  magic {MAGIC}  窗口 {DAYS} 天  已平仓 position {len(rows)} 笔")
    p(f"    做多 {len(longs)}  做空 {len(shorts)}")
    p(f"  4h K 线 {len(h4)} 根：{dt.datetime.fromtimestamp(int(h4['time'].iloc[0]), dt.UTC)}"
      f" .. {dt.datetime.fromtimestamp(int(h4['time'].iloc[-1]), dt.UTC)}")

    # 标注趋势
    n_nodata = 0
    for r in rows:
        tg = trend_at(tr, r["t_in"])
        r["tg"] = tg
        if not tg.get("ok"):
            n_nodata += 1
    p(f"  趋势判据缺失（无已收盘 bar）{n_nodata} 笔 → 保守**放行**")

    p("")
    p("-" * 108)
    p("【A】现状（无闸）")
    p("-" * 108)
    p(fmt("做多", summ(longs)))
    p(fmt("做空", summ(shorts)))
    p(fmt("合计", summ(rows)))

    # ---------- 候选规则 ----------
    def gate_r1(r):        # 4h 价 > EMA50
        return r["tg"].get("r1")

    def gate_r2(r):        # 4h EMA20 > EMA50
        return r["tg"].get("r2")

    def gate_r3(r):        # 价>EMA50 且 EMA20>EMA50
        t = r["tg"]
        return None if not t.get("ok") else (t["r1"] and t["r2"])

    def gate_r4(r):        # 4h 价 > EMA100
        return r["tg"].get("r4")

    rules = [("R1 4h价>EMA50", gate_r1),
             ("R2 4hEMA20>EMA50", gate_r2),
             ("R3 价>EMA50 且 EMA20>EMA50", gate_r3),
             ("R4 4h价>EMA100", gate_r4)]

    results = {}
    for name, fn in rules:
        keep, drop = [], []
        for r in longs:
            v = fn(r)
            (keep if (v is None or v) else drop).append(r)   # 缺数据 → 保守放行
        sk, sd = summ(keep), summ(drop)
        combo = summ(keep + shorts)
        dsr, sr0, sr = dsr_of(keep + shorts)
        results[name] = dict(keep=sk, drop=sd, combo=combo, dsr=dsr, sr0=sr0, sr=sr)

    p("")
    p("-" * 108)
    p("【B】做多趋势闸各候选（仅作用于做多；做空全部保留）")
    p("-" * 108)
    for name, _ in rules:
        res = results[name]
        p(f"  ── {name}")
        p(fmt("放行做多", res["keep"]))
        p(fmt("被挡做多", res["drop"]))
        p(fmt("全组合(放行多+全部空)", res["combo"]))
        c = res["combo"]
        dsr = res["dsr"]
        dsr_s = "n/a" if not np.isfinite(dsr) else f"{dsr:.3f}"
        sr_s = "n/a" if not np.isfinite(res["sr"]) else f"{res['sr']:+.3f}"
        p(f"    组合净 {c['tot']:+.2f}  逐笔Sharpe {sr_s}  "
          f"DSR(N={N_TRIALS}) {dsr_s}"
          + ("  通过(>0.95)" if np.isfinite(dsr) and dsr > 0.95 else ""))
        if res["keep"]["n"] and res["drop"]["n"]:
            p(f"    Δ(放行均笔−被挡均笔) = "
              f"{res['keep']['avg'] - res['drop']['avg']:+.3f}")
        p("")

    # ---------- 多空对称（趋势一致）口径 ----------
    def sym_keep(r, up_fn, dn_fn) -> bool:
        """做多按 up_fn、做空按 dn_fn（镜像）；缺数据保守放行。"""
        t = r["tg"]
        if not t.get("ok"):
            return True
        return bool(up_fn(t)) if r["is_long"] else bool(dn_fn(t))

    sym_rules = [
        ("S1 价>EMA50 / 空价<EMA50",
         lambda t: t["r1"], lambda t: t["s1"]),
        ("S2 EMA20>EMA50 / 空EMA20<EMA50",
         lambda t: t["r2"], lambda t: t["s2"]),
        ("S3 价与EMA20同向[对EMA50]",
         lambda t: t["r1"] and t["r2"], lambda t: t["s1"] and t["s2"]),
        ("S4 价>EMA100 / 空价<EMA100",
         lambda t: t["r4"], lambda t: t["s4"]),
    ]
    sym_results = {}
    for name, up_fn, dn_fn in sym_rules:
        keep = [r for r in rows if sym_keep(r, up_fn, dn_fn)]
        drop = [r for r in rows if not sym_keep(r, up_fn, dn_fn)]
        dsr, sr0, sr = dsr_of(keep)
        sym_results[name] = dict(keep=keep, drop=drop, combo=summ(keep),
                                 dsr=dsr, sr=sr)

    p("-" * 108)
    p("【B2】多空对称「趋势一致」闸（做多需在均线上方，做空需在均线下方）")
    p("-" * 108)
    for name, _, _ in sym_rules:
        res = sym_results[name]
        c = res["combo"]
        dsr = res["dsr"]
        dsr_s = "n/a" if not np.isfinite(dsr) else f"{dsr:.3f}"
        sr_s = "n/a" if not np.isfinite(res["sr"]) else f"{res['sr']:+.3f}"
        dl = [r for r in res["drop"] if r["is_long"]]
        ds = [r for r in res["drop"] if not r["is_long"]]
        p(f"  ── {name}")
        p(fmt("放行(多+空)", c))
        p(fmt("被挡(多+空)", summ(res["drop"])))
        p(f"    组合净 {c['tot']:+.2f}  逐笔Sharpe {sr_s}  DSR(N={N_TRIALS}) {dsr_s}"
          + ("  通过(>0.95)" if np.isfinite(dsr) and dsr > 0.95 else ""))
        p(f"    其中被挡做多 {len(dl)} 笔 净 {summ(dl)['tot']:+.2f}；"
          f"被挡做空 {len(ds)} 笔 净 {summ(ds)['tot']:+.2f}")
        p("")

    # ---------- 分段稳健性（对候选 R1 / R4 做前后半段对照）----------
    p("-" * 108)
    p("【C】分段稳健性（按开仓时刻中位切前后半段，检验是否只靠某一段）")
    p("-" * 108)
    tmid = float(np.median([r["t_in"] for r in rows])) if rows else 0.0
    for name, fn in (("R1 4h价>EMA50", gate_r1), ("R4 4h价>EMA100", gate_r4)):
        p(f"  ── {name}")
        for half, sub in (("前半段", [r for r in rows if r["t_in"] <= tmid]),
                          ("后半段", [r for r in rows if r["t_in"] > tmid])):
            sl = [r for r in sub if r["is_long"]]
            ss = [r for r in sub if not r["is_long"]]
            keep, drop = [], []
            for r in sl:
                v = fn(r)
                (keep if (v is None or v) else drop).append(r)
            p(f"    {half}: 现有全组合 {summ(sub)['tot']:+.2f} → "
              f"加闸后 {summ(keep + ss)['tot']:+.2f}  "
              f"(挡掉做多 {len(drop)} 笔 {summ(drop)['tot']:+.2f})")
        p("")

    # ---------- 判读 ----------
    p("=" * 108)
    p("【D】判读")
    p("=" * 108)
    r0 = summ(rows)
    p(f"  · 现状全组合净 {r0['tot']:+.2f}；做多净 {summ(longs)['tot']:+.2f}，"
      f"做空净 {summ(shorts)['tot']:+.2f}。")
    for name, _ in rules:
        res = results[name]
        d = res["drop"]
        p(f"  · {name}：挡掉 {d['n']} 笔（净 {d['tot']:+.2f}），"
          f"全组合 {r0['tot']:+.2f} → {res['combo']['tot']:+.2f}")
    for name, _, _ in sym_rules:
        res = sym_results[name]
        d = summ(res["drop"])
        p(f"  · {name}：挡掉 {d['n']} 笔（净 {d['tot']:+.2f}），"
          f"全组合 {r0['tot']:+.2f} → {res['combo']['tot']:+.2f}")
    p("  · 结论：被挡组净为负且全组合改善明显、且前后半段方向一致的规则才采用。")
    p(f"  · 试验族 N={N_TRIALS} 须记入 data/trials.csv。")

    out = ROOT / "research" / "34_long_trend_gate_out.txt"
    try:
        out.write_text("\n".join(OUT), encoding="utf-8")
        p(f"\n已保存：{out.relative_to(ROOT)}")
    except Exception as e:
        p(f"\n（保存失败：{e}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
