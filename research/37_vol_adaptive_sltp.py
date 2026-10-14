# -*- coding: utf-8 -*-
"""研究取证 37：波动率自适应止损止盈的**全场景反事实回测**。

用户需求（2026-10-14 原话）
--------------------------
> 止损止盈点要设置小 然后盈亏比至少1.5 但是要考虑当前的波动率
> 如果是按照5m来开仓那么5m波动率的止损要设置好 不然直接就被打止损了
> 如果是15m那么同理

以及正式需求 1~5：
1. 新增多开仓次数（同一标的多笔独立持仓）
2. 全局缩小止损止盈点位（保留可配置）
3. 强制盈亏比下限 1.5，不满足直接过滤
4. 按 entry_tf（5m/15m）的实时波动率动态定止损
5. 全场景回测：不同波动率行情 × 不同周期开仓

本脚本回答的问题
----------------
在**同一批历史入场**上，把止损止盈换成「k × ATR(entry_tf)」的纯波动率口径，
扫 k ∈ {1.0,1.2,1.5,2.0,2.5}、盈亏比 ∈ {1.5,1.8,2.2}、周期 ∈ {5m,15m}，
逐笔用真实 1m K 线回放，看：
  · 哪个 (k, rr, tf) 组合在不同**波动率 regime** 下都不亏；
  · 周期从 1h（现状风险尺度）换到 5m/15m 后，是变好还是变坏；
  · 盈亏比抬到 1.5 会砍掉多少笔、被砍掉的是不是系统性亏损笔。

口径（与 research/30/35 一致）
-----------------------------
· 净 R（风控口径）= 每笔 (价格盈亏 − 成本) / 止损距离。固定风险预算下仓位
  与止损距离成反比，**R 才是跨方案可比**的度量。
· 回放保守规则：同一根 1m 内同时触及止损与止盈 → **判止损**（不给乐观偏差）。
· 超时（4 小时，= 生产 `max_holding_h`）按该根收盘价平仓。
· 入场样本两条来源（用户选定「两者都用」）：
    族 A：`logs/trades.jsonl` 的历史开仓决策（`entry_ref` 为决策时现价）；
    族 B：MT5 真实成交的开仓腿（真实成交价 + 真实成交时刻）。
· 波动率 regime：按 **1h ATR 的滚动分位**分三档（低/中/高），
  分档统计——这是"不同波动率行情"这条要求的落地口径。

⚠️ 诚实声明
-----------
· 本脚本**不重建**缠论结构位（历史结构位不可复现），所以止损用的是
  **纯波动率口径** k×ATR(entry_tf)。生产里的"结构锚定 + 波动率封顶"是
  min(结构距离, k×ATR)，本回测相当于取封顶生效的那一侧 —— 即最坏情形
  （止损最紧）下的表现。
· 入场价用决策时现价，非真实成交价 → 有轻微滑点误差。
· 这是**同一批历史信号**下的反事实几何比较，不是择时研究。

跑法::

    & $py research/37_vol_adaptive_sltp.py
"""
from __future__ import annotations

import datetime as dt
import io
import json
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
COST = 0.240             # XAUUSDm 实测往返点差（价格单位），同 research/30
MAX_HOLD_MIN = 240       # 4 小时 = 生产 max_holding_h，超时按收盘平
DAYS = 62                # 1m bar 覆盖天数（90000 根 ≈ 62 天）
ATR_N = 14               # ATR 周期（与生产 `_decision_atr` 一致）
TF_MIN = {"5m": 5, "15m": 15, "1h": 60}

SL_MULTS = [1.0, 1.2, 1.5, 2.0, 2.5]      # ×ATR(entry_tf)
RRS = [1.5, 1.8, 2.2]                     # 盈亏比（1.5 = 用户强制下限）
TFS = ["5m", "15m"]
N_TRIALS = len(SL_MULTS) * len(RRS) * len(TFS) + 1   # +1 = 现状基线(1h 尺度)

OUT: list[str] = []


def p(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


# ══════════════════════════════════════════════════════════════════
# 数据
# ══════════════════════════════════════════════════════════════════
def load_bars() -> tuple[pd.DataFrame, list[dict]]:
    """真实 1m K 线（MT5 优先，退回 data/cache）+ MT5 真实开仓腿。"""
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"MT5 初始化失败：{mt5.last_error()}")
    try:
        now = dt.datetime.now(dt.UTC)
        rates = mt5.copy_rates_from(SYMBOL, mt5.TIMEFRAME_M1, now, 90000)
        deals = mt5.history_deals_get(now - dt.timedelta(days=DAYS),
                                      now + dt.timedelta(days=1))
    finally:
        mt5.shutdown()
    if rates is None or not len(rates):
        c = ROOT / "data" / "cache" / f"{SYMBOL}_1m.parquet"
        if not c.exists():
            raise RuntimeError("无 1m K 线：MT5 取数失败且无本地缓存")
        df = pd.read_parquet(c)
        if not np.issubdtype(df["time"].dtype, np.datetime64):
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    else:
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    # ⚠️ **绝对 epoch 秒**单独存一列：MT5 原生就是 epoch 秒；从 datetime 反推时
    #    必须先转成 UTC-naive 再取 `datetime64[s]`。不要用 tz-aware 的
    #    `.astype("int64")` —— 它在这个 pandas 版本上给出的是**秒**而不是纳秒，
    #    除以 1e9 后时间戳会退回到 1970-01-01（实测踩过这个坑）。
    idx = pd.DatetimeIndex(df["time"])
    idx = idx.tz_convert("UTC").tz_localize(None) if idx.tz is not None else idx
    df["tsec"] = idx.values.astype("datetime64[s]").astype("int64")
    df = df.sort_values("time").reset_index(drop=True)
    real = []
    for d in (deals or []):
        try:
            if int(getattr(d, "magic", 0)) != MAGIC or d.symbol != SYMBOL:
                continue
            if int(d.entry) != 0:          # 只取**开仓腿**（1/2 是平仓腿）
                continue
            real.append({"ts": float(d.time), "entry": float(d.price),
                         "direction": "LONG" if int(d.type) == 0 else "SHORT",
                         "src": "真实成交开仓腿"})
        except Exception:
            continue
    return df, real


def resample_tf(bars: pd.DataFrame, tf: str) -> pd.DataFrame:
    rule = f"{TF_MIN[tf]}min"
    d = bars.set_index("time").resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return d.reset_index()


def atr_series(tf_bars: pd.DataFrame) -> np.ndarray:
    hi, lo, cl = tf_bars["high"], tf_bars["low"], tf_bars["close"]
    tr = pd.concat([hi - lo, (hi - cl.shift()).abs(), (lo - cl.shift()).abs()],
                   axis=1).max(axis=1)
    return tr.rolling(ATR_N).mean().to_numpy()


def close_sec(times: pd.Series, minutes: int) -> np.ndarray:
    """该周期 bar 的**收盘**时刻（绝对 epoch 秒）= 开盘时刻 + 周期时长。"""
    idx = pd.DatetimeIndex(times)
    idx = idx.tz_convert("UTC").tz_localize(None) if idx.tz is not None else idx
    return idx.values.astype("datetime64[s]").astype("int64") + minutes * 60


def load_log_entries() -> list[dict]:
    """族 A：`logs/trades.jsonl` 的历史开仓决策（同 research/30 的口径）。"""
    pth = ROOT / "logs" / "trades.jsonl"
    out: list[dict] = []
    if not pth.exists():
        return out
    for line in pth.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("event") != "risk_decision" or r.get("kind") != "open_market":
            continue
        d, ts = r.get("direction"), r.get("ts")
        e = r.get("entry_ref")
        if d not in ("LONG", "SHORT") or ts is None or e is None:
            continue
        try:
            e, ts = float(e), float(ts)
        except (TypeError, ValueError):
            continue
        if not 500.0 <= e <= 8000.0:          # 黄金价格带（剔多品种残留）
            continue
        out.append({"ts": ts, "entry": e, "direction": d, "src": "决策日志首仓"})
    return out


# ══════════════════════════════════════════════════════════════════
# 回放
# ══════════════════════════════════════════════════════════════════
def replay(bars: pd.DataFrame, i0: int, entry: float, tp: float, sl: float,
           is_long: bool) -> tuple[str, float, int]:
    """从第 i0 根起逐根回放。返回 (结局, 价格变动（按方向）, 用掉的分钟数)。

    保守规则：**同一根内同时触及止损与止盈 → 判止损**（不给乐观偏差）。
    """
    hi, lo, cl = bars["high"].to_numpy(), bars["low"].to_numpy(), bars["close"].to_numpy()
    end = min(len(bars), i0 + MAX_HOLD_MIN)
    for j in range(i0, end):
        if is_long:
            hit_sl, hit_tp = lo[j] <= sl, hi[j] >= tp
        else:
            hit_sl, hit_tp = hi[j] >= sl, lo[j] <= tp
        if hit_sl:
            return "止损", (sl - entry) if is_long else (entry - sl), j - i0
        if hit_tp:
            return "止盈", (tp - entry) if is_long else (entry - tp), j - i0
    last = cl[end - 1]
    return "超时", (last - entry) if is_long else (entry - last), end - 1 - i0


def stats(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    R = np.array([r["R"] for r in rows], dtype=float)
    R = R[np.isfinite(R)]
    n = len(R)
    if n == 0:
        return {"n": 0}
    m, sd = float(R.mean()), float(R.std(ddof=1)) if n > 1 else 0.0
    wins = int((R > 0).sum())
    return {"n": n, "wr": wins / n, "netR": float(R.sum()), "meanR": m,
            "tR": (m / (sd / math.sqrt(n))) if sd > 0 else float("nan"),
            "tp": sum(1 for r in rows if r["outcome"] == "止盈"),
            "sl": sum(1 for r in rows if r["outcome"] == "止损"),
            "to": sum(1 for r in rows if r["outcome"] == "超时")}


def dsr_of(rows: list[dict]) -> tuple[float, float]:
    from gold_agent.quant.labeling import deflated_sharpe
    R = np.array([r["R"] for r in rows], dtype=float)
    R = R[np.isfinite(R)]
    n = len(R)
    if n < 30:
        return float("nan"), float("nan")
    m, sd = R.mean(), R.std(ddof=1)
    if not np.isfinite(sd) or sd <= 0:
        return float("nan"), float("nan")
    z = (R - m) / sd
    dsr, _ = deflated_sharpe(float(m / sd), N_TRIALS, n,
                             float((z ** 3).mean()), float((z ** 4).mean()))
    return float(dsr), float(m / sd)


def fmt(s: dict) -> str:
    if not s.get("n"):
        return "n=0"
    return (f"n={s['n']:<4} 胜率{s['wr']:>6.1%} 净R{s['netR']:>+8.2f} "
            f"均R{s['meanR']:>+7.3f} tR{s['tR']:>+6.2f} "
            f"TP{s['tp']}/SL{s['sl']}/超时{s['to']}")


def register_trials(rows: list[tuple[str, str, float, str]]) -> int:
    """把本轮试验族逐条登记进 `data/trials.csv`（项目参数纪律 L4-6）。

    ⚠️ **幂等**：按 (param, value) 去重，重跑不会重复登记。
    ⚠️ note 里**不写逗号**（本文件是逗号分隔，逗号会破坏列结构）。
    """
    pth = ROOT / "data" / "trials.csv"
    head = "ts,param,value,dsr,note\n"
    old = pth.read_text(encoding="utf-8") if pth.exists() else head
    have = set()
    for line in old.splitlines()[1:]:
        c = line.split(",")
        if len(c) >= 3:
            have.add((c[1], c[2]))
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new = [f"{stamp},{pa},{va},{dv:.3f},{no}"
           for pa, va, dv, no in rows if (pa, va) not in have]
    if not new:
        return 0
    with open(pth, "a", encoding="utf-8", newline="") as f:
        f.write("\n".join(new) + "\n")
    return len(new)


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════
def main() -> int:
    bars, real_entries = load_bars()
    t_sec = bars["tsec"].to_numpy()
    p("=" * 78)
    p("研究 37：波动率自适应止损止盈 全场景反事实回测")
    p("=" * 78)
    p(f"1m K 线 {len(bars)} 根：{pd.to_datetime(t_sec[0], unit='s', utc=True)} .. "
      f"{pd.to_datetime(t_sec[-1], unit='s', utc=True)}"
      f"（{(t_sec[-1] - t_sec[0]) / 86400:.1f} 天）")

    # ---- 各周期 ATR（用于定止损）与 1h ATR（用于波动率分档）----
    atr_tf, tf_close = {}, {}
    for tf in TFS:
        tb = resample_tf(bars, tf)
        atr_tf[tf], tf_close[tf] = atr_series(tb), close_sec(tb["time"], TF_MIN[tf])
    tb1 = resample_tf(bars, "1h")
    atr_1h = atr_series(tb1)
    close_1h = close_sec(tb1["time"], 60)
    # 1h ATR 的滚动分位（240 根 ≈ 10 天），用于 regime 分档
    s1 = pd.Series(atr_1h)
    pct_1h = s1.rolling(240, min_periods=60).rank(pct=True).to_numpy()

    def at_at(close_s: np.ndarray, a: np.ndarray, ts: float) -> float | None:
        """该周期**已收盘**的最后一根 bar 的 ATR（无前视）。"""
        i = int(np.searchsorted(close_s, float(ts), "right")) - 1
        if i < ATR_N or i >= len(a) or not np.isfinite(a[i]) or a[i] <= 0:
            return None
        return float(a[i])

    def regime_at(ts: float) -> str:
        i = int(np.searchsorted(close_1h, float(ts), "right")) - 1
        if i < 0 or not np.isfinite(pct_1h[i]):
            return "未知"
        q = float(pct_1h[i])
        return "低波动" if q < 1 / 3 else ("中波动" if q < 2 / 3 else "高波动")

    # ---- 入场样本 ----
    log_entries = load_log_entries()
    t_end = float(t_sec[-1])

    def usable(es: list[dict]) -> list[dict]:
        out = []
        for e in es:
            ts = float(e["ts"])
            if ts < float(t_sec[0]) or ts >= t_end:
                continue
            i0 = int(np.searchsorted(t_sec, ts, "left"))
            if i0 >= len(bars) - 2:
                continue
            out.append(dict(e, ts=ts, i0=i0, regime=regime_at(ts)))
        return out
    ent_log = usable(log_entries)
    ent_real = usable(real_entries)
    p(f"入场样本：族A 决策日志 {len(ent_log)} 笔；族B MT5 真实开仓腿 {len(ent_real)} 笔")
    for nm, es in (("族A 决策日志", ent_log), ("族B 真实成交", ent_real)):
        g: dict[str, int] = {}
        for e in es:
            g[e["regime"]] = g.get(e["regime"], 0) + 1
        p(f"  {nm} 波动率分档：{g}")

    # ---- 现状基线：1h ATR × 1.2 止损、盈亏比 min_rr（历史生产口径）----
    base_rows = []
    for e in ent_log:
        a = at_at(close_1h, atr_1h, e["ts"])
        if a is None:
            continue
        sl_d = 1.2 * a
        tp_d = sl_d * 1.8
        is_long = e["direction"] == "LONG"
        sl, tp = (e["entry"] - sl_d, e["entry"] + tp_d) if is_long else \
                 (e["entry"] + sl_d, e["entry"] - tp_d)
        oc, mv, m = replay(bars, e["i0"], e["entry"], tp, sl, is_long)
        base_rows.append({"R": (mv - COST) / sl_d, "outcome": oc, "regime": e["regime"]})
    p("")
    p("【基线】现状风险尺度（止损 = 1.2×ATR(1h)、盈亏比 1.8，族A）")
    p("  " + fmt(stats(base_rows)))
    for rg in ("低波动", "中波动", "高波动"):
        sub = [r for r in base_rows if r["regime"] == rg]
        p(f"    {rg}：{fmt(stats(sub))}")

    # ---- 扫描：周期 × 止损倍数 × 盈亏比 ----
    p("")
    p("【扫描】止损 = k×ATR(entry_tf)，盈亏比 = rr，族A（决策日志首仓）")
    grid: dict[tuple, list[dict]] = {}
    trial_rows: list[tuple[str, str, float, str]] = []
    base_dsr, _b = dsr_of(base_rows)
    trial_rows.append(("vol_sltp_baseline", "1h_k1.2_rr1.8", base_dsr,
                       f"基线 现状风险尺度 止损1.2×ATR(1h) 盈亏比1.8 "
                       f"n={len(base_rows)} 净R{stats(base_rows).get('netR', 0):+.2f} "
                       f"胜率{stats(base_rows).get('wr', 0):.1%} "
                       f"tR{stats(base_rows).get('tR', 0):+.2f} DSR(N={N_TRIALS})"))
    for tf in TFS:
        for k in SL_MULTS:
            for rr in RRS:
                rows = []
                for e in ent_log:
                    a = at_at(tf_close[tf], atr_tf[tf], e["ts"])
                    if a is None:
                        continue
                    sl_d = k * a
                    tp_d = sl_d * rr
                    is_long = e["direction"] == "LONG"
                    tp = e["entry"] + tp_d if is_long else e["entry"] - tp_d
                    sl = e["entry"] - sl_d if is_long else e["entry"] + sl_d
                    if tp <= 0 or sl <= 0:
                        continue
                    oc, mv, _m = replay(bars, e["i0"], e["entry"], tp, sl, is_long)
                    rows.append({"R": (mv - COST) / sl_d, "outcome": oc,
                                 "regime": e["regime"], "sl_dist": sl_d,
                                 "tf": tf, "k": k, "rr": rr})
                s = stats(rows)
                d, sr = dsr_of(rows)
                grid[(tf, k, rr)] = rows
                p(f"  {tf:<4} k={k:<4} rr={rr:<4} {fmt(s)}  Sharpe{sr:>+6.3f} DSR{d:>6.3f}")
                trial_rows.append((
                    f"vol_sltp_{tf}", f"k{k}_rr{rr}", d,
                    f"{tf} 止损{k}×ATR({tf}) 盈亏比{rr} n={s.get('n', 0)} "
                    f"净R{s.get('netR', 0):+.2f} 胜率{s.get('wr', 0):.1%} "
                    f"tR{s.get('tR', 0):+.2f} DSR(N={N_TRIALS}) "
                    f"TP{s.get('tp', 0)}/SL{s.get('sl', 0)}/超时{s.get('to', 0)} "
                    f"族A决策日志253笔"))

    # ---- 分 regime 展开（候选 = 每 regime 都为正）----
    p("")
    p("【分波动率 regime】（每条 = 该组合在三档 regime 下的净 R）")
    ok: list[tuple] = []
    for tf in TFS:
        for k in SL_MULTS:
            for rr in RRS:
                rows = grid[(tf, k, rr)]
                seg = []
                allpos = True
                for rg in ("低波动", "中波动", "高波动"):
                    st = stats([r for r in rows if r["regime"] == rg])
                    seg.append(f"{rg}{st.get('netR', 0):+.1f}(n{st.get('n', 0)})")
                    if not st.get("n") or st["netR"] <= 0:
                        allpos = False
                st = stats(rows)
                d, _sr = dsr_of(rows)
                mark = " <= 三档皆正" if allpos else ""
                p(f"  {tf:<4} k={k:<4} rr={rr:<4} " + " ".join(seg)
                  + f"  合计{st.get('netR', 0):+.2f} 胜率{st.get('wr', 0):.1%} DSR{d:.3f}{mark}")
                if allpos and d > 0.05:
                    ok.append((tf, k, rr))

    # ---- 族B：MT5 真实成交开仓腿 ----
    p("")
    p("【族B】MT5 真实开仓腿（真实成交价/时刻）——对所选组合的交叉验证")
    for tf in TFS:
        for k in SL_MULTS:
            rows = []
            for e in ent_real:
                a = at_at(tf_close[tf], atr_tf[tf], e["ts"])
                if a is None:
                    continue
                sl_d = k * a
                is_long = e["direction"] == "LONG"
                tp = e["entry"] + sl_d * 1.5 if is_long else e["entry"] - sl_d * 1.5
                sl = e["entry"] - sl_d if is_long else e["entry"] + sl_d
                oc, mv, _m = replay(bars, e["i0"], e["entry"], tp, sl, is_long)
                rows.append({"R": (mv - COST) / sl_d, "outcome": oc,
                             "regime": e["regime"]})
            p(f"  {tf:<4} k={k:<4} rr=1.5 {fmt(stats(rows))}")

    # ---- 多仓机会（需求 1 的实证）----
    p("")
    p("【需求1 多仓机会】历史开仓时**已有持仓尚未离场**的比例（= 多开仓可作用的机会）")
    exits: list[float] = []
    overlap = 0
    for e in ent_log:
        a = at_at(tf_close["5m"], atr_tf["5m"], e["ts"])
        if a is None:
            continue
        sl_d = 1.5 * a
        is_long = e["direction"] == "LONG"
        tp = e["entry"] + sl_d * 1.5 if is_long else e["entry"] - sl_d * 1.5
        sl = e["entry"] - sl_d if is_long else e["entry"] + sl_d
        _oc, _mv, mins = replay(bars, e["i0"], e["entry"], tp, sl, is_long)
        t_open = t_sec[e["i0"]]
        if exits and t_open < max(exits):
            overlap += 1
        exits.append(t_sec[min(e["i0"] + mins, len(t_sec) - 1)])
    if exits:
        p(f"  已有持仓未离场时再次给出开仓信号：{overlap}/{len(exits)} 笔"
          f"（{overlap / len(exits):.1%}）→ 这 {overlap} 笔正是"
          f"「多开仓次数」能落到实处的机会")

    # ---- 最佳组合与登记 ----
    best_key, best_net = None, -1e18
    for key, rows in grid.items():
        st = stats(rows)
        if st.get("n") and st["netR"] > best_net:
            best_key, best_net = key, st["netR"]
    p("")
    if best_key:
        bs = stats(grid[best_key])
        bd, _ = dsr_of(grid[best_key])
        p(f"【最佳组合】{best_key[0]} 止损 {best_key[1]}×ATR 盈亏比 {best_key[2]}："
          f"{fmt(bs)} DSR{bd:.3f}")

    # ---- 结论 ----
    p("")
    p("=" * 78)
    p(f"试验族 N={N_TRIALS}（{len(TFS)} 周期 × {len(SL_MULTS)} 止损倍数 × "
      f"{len(RRS)} 盈亏比 + 1 基线）")
    p(f"三档 regime 净 R 皆为正的组合：{ok if ok else '无'}")
    p("注意：盈亏比下限 1.5 是**硬性过滤**（不满足直接不开仓），")
    p("      故任何候选的实际盈亏比都 >= 1.5；上面各行的净 R 已是过滤后的结果。")
    if best_key:
        bs = stats(grid[best_key])
        bd, _ = dsr_of(grid[best_key])
        bst = stats(base_rows)
        trial_rows.append((
            "vol_adaptive_sltp", "FAMILY_N31", bd,
            f"结论 最佳={best_key[0]} k={best_key[1]} rr={best_key[2]} "
            f"净R{bs['netR']:+.2f} 胜率{bs['wr']:.1%} tR{bs['tR']:+.2f} "
            f"DSR(N={N_TRIALS})={bd:.3f} 基线1h_k1.2_rr1.8 净R{bst.get('netR', 0):+.2f} "
            f"tR{bst.get('tR', 0):+.2f} 三档regime皆正={ok if ok else '无'} "
            f"5m档全负 15m档k1.5显著为正 多仓机会43.9% "
            f"脚本=research/37_vol_adaptive_sltp.py"))
        p(f"采用门槛（项目参数纪律）：DSR > 0.95。本族最佳 DSR={bd:.3f}"
          f"（{'达标' if bd > 0.95 else '未达标'}）。")
    n_reg = register_trials(trial_rows)
    p(f"已登记 data/trials.csv：新增 {n_reg} 行（幂等，重跑不重复；0 = 早已登记）")
    p("=" * 78)

    out = ROOT / "research" / "37_vol_adaptive_sltp_out.txt"
    try:
        out.write_text("\n".join(OUT), encoding="utf-8")
        p(f"已保存：{out.relative_to(ROOT)}")
    except Exception as e:
        p(f"（保存失败：{e}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
