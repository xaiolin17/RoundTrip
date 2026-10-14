# -*- coding: utf-8 -*-
"""研究取证 38：把 **5m 档**迭代到达标（用户 2026-10-14 要求）。

背景（research/37 的结论）
------------------------
5m 档 15 个组合全为负（最好 −24.71）。但**分波动率档**暴露出真正的死因：

    5m k=1.5 rr=1.8 → 低波动 +32.7(n112) / 中波动 −3.0(n64) / 高波动 −54.4(n77)

即：5m 的止损 = k×ATR(5m)（≈3 美元）在**高波动**时太紧，进场即被扫。
15m 档之所以赚（+58.27），正是因为它的止损宽了约 3.5 倍。

所以本轮不是"再扫一遍 k"，而是测**机制**（每条机制都要在物理上说得通）：
  F1 止损倍数扫描（基准线：确认"更宽的止损"到底能不能救 5m）
  F2 **波动率分位上限闸**：只在"止损相对波动够宽"的行情里做 5m
  F3 **双周期下限**：止损 = max(k×ATR(5m), f×ATR(15m))（用高级别托底）
  F4 **更短的最大持有**：5m 单被套住就不该等 4 小时
  F5 **平滑 ATR**：ATR(5m) 用 50 根而非 14 根（14 根在 5m 上噪声太大）

判定口径（沿用项目既定门槛，与 research/36 的"采用门槛"一致）
------------------------------------------------------------
  · 达标 = 净R > 0 且 DSR > 0.95
  · 附加稳健性检查（防过拟合）：**前后半段同向**、族B（真实成交）同向
  ⚠️ DSR 的试验族规模用**累计 N**（含 research/37 的 31 次）——
     每多试一个变体，门槛就更高。这正是"不能靠扫参数把结果扫好看"的机制。

跑法::

    & $py research/38_sltp_5m_iterate.py
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
COST = 0.240
ATR_N = 14
DAYS = 62
#: ⚠️ 累计试验族：research/37 已试 31 次，本轮从 32 起累加（显式记录，不隐藏）
N_BASE = 31

OUT: list[str] = []


def p(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


# ══════════════════════════════════════════════════════════════════
# 数据（与 research/37 同一口径）
# ══════════════════════════════════════════════════════════════════
def load_bars():
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
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    idx = pd.DatetimeIndex(df["time"]).tz_convert("UTC").tz_localize(None)
    df["tsec"] = idx.values.astype("datetime64[s]").astype("int64")
    df = df.sort_values("time").reset_index(drop=True)
    real = []
    for d in (deals or []):
        try:
            if int(getattr(d, "magic", 0)) != MAGIC or d.symbol != SYMBOL:
                continue
            if int(d.entry) != 0:
                continue
            real.append({"ts": float(d.time), "entry": float(d.price),
                         "direction": "LONG" if int(d.type) == 0 else "SHORT"})
        except Exception:
            continue
    return df, real


def resample_tf(bars: pd.DataFrame, minutes: int) -> pd.DataFrame:
    d = bars.set_index("time").resample(f"{minutes}min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return d.reset_index()


def atr_series(tb: pd.DataFrame, n: int = ATR_N) -> np.ndarray:
    hi, lo, cl = tb["high"], tb["low"], tb["close"]
    tr = pd.concat([hi - lo, (hi - cl.shift()).abs(), (lo - cl.shift()).abs()],
                   axis=1).max(axis=1)
    return tr.rolling(n).mean().to_numpy()


def close_sec(times: pd.Series, minutes: int) -> np.ndarray:
    idx = pd.DatetimeIndex(times).tz_convert("UTC").tz_localize(None)
    return idx.values.astype("datetime64[s]").astype("int64") + minutes * 60


def load_log_entries() -> list[dict]:
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
        d, ts, e = r.get("direction"), r.get("ts"), r.get("entry_ref")
        if d not in ("LONG", "SHORT") or ts is None or e is None:
            continue
        try:
            e, ts = float(e), float(ts)
        except (TypeError, ValueError):
            continue
        if not 500.0 <= e <= 8000.0:
            continue
        out.append({"ts": ts, "entry": e, "direction": d})
    return out


def replay(bars, i0, entry, tp, sl, is_long, hold_min):
    hi, lo, cl = bars["high"].to_numpy(), bars["low"].to_numpy(), bars["close"].to_numpy()
    end = min(len(bars), i0 + hold_min)
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
    R = np.array([r["R"] for r in rows if np.isfinite(r["R"])], dtype=float)
    n = len(R)
    if n == 0:
        return {"n": 0}
    m, sd = float(R.mean()), (float(R.std(ddof=1)) if n > 1 else 0.0)
    return {"n": n, "wr": float((R > 0).sum()) / n, "netR": float(R.sum()),
            "meanR": m, "tR": (m / (sd / math.sqrt(n))) if sd > 0 else float("nan"),
            "tp": sum(1 for r in rows if r["outcome"] == "止盈"),
            "sl": sum(1 for r in rows if r["outcome"] == "止损"),
            "to": sum(1 for r in rows if r["outcome"] == "超时")}


def dsr_of(rows: list[dict], n_trials: int) -> tuple[float, float, float]:
    """返回 (DSR, 逐笔 Sharpe, **DSR 的门槛 Sharpe `sr0`**)。

    ⚠️ 第三项 `sr0` 是回答"能不能达标"的关键：DSR > 0.95 要求
    `本策略 Sharpe` 显著高于 `sr0`（= 在 n_trials 次尝试下**纯运气**能达到的
    最大 Sharpe）。只看 DSR 数字看不出差多远，把 sr0 打出来才知道。
    """
    from gold_agent.quant.labeling import deflated_sharpe
    R = np.array([r["R"] for r in rows if np.isfinite(r["R"])], dtype=float)
    n = len(R)
    if n < 30:
        return float("nan"), float("nan"), float("nan")
    m, sd = R.mean(), R.std(ddof=1)
    if not np.isfinite(sd) or sd <= 0:
        return float("nan"), float("nan"), float("nan")
    z = (R - m) / sd
    sr = float(m / sd)
    dsr, sr0 = deflated_sharpe(sr, n_trials, n,
                               float((z ** 3).mean()), float((z ** 4).mean()))
    return float(dsr), sr, float(sr0)


def fmt(s: dict) -> str:
    if not s.get("n"):
        return "n=0"
    return (f"n={s['n']:<4} 胜率{s['wr']:>6.1%} 净R{s['netR']:>+8.2f} "
            f"均R{s['meanR']:>+7.3f} tR{s['tR']:>+6.2f} "
            f"TP{s['tp']}/SL{s['sl']}/超时{s['to']}")


def register_trials(rows: list[tuple[str, str, float, str]]) -> int:
    """幂等登记 trials.csv（按 param+value 去重）。note 里不写逗号。"""
    pth = ROOT / "data" / "trials.csv"
    head = "ts,param,value,dsr,note\n"
    old = pth.read_text(encoding="utf-8") if pth.exists() else head
    have = {(c[1], c[2]) for c in (l.split(",") for l in old.splitlines()[1:])
            if len(c) >= 3}
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new = [f"{stamp},{pa},{va},{dv:.3f},{no}"
           for pa, va, dv, no in rows if (pa, va) not in have]
    if new:
        with open(pth, "a", encoding="utf-8", newline="") as f:
            f.write("\n".join(new) + "\n")
    return len(new)


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════
def main() -> int:
    bars, real_entries = load_bars()
    t_sec = bars["tsec"].to_numpy()
    tb5, tb15, tb60 = resample_tf(bars, 5), resample_tf(bars, 15), resample_tf(bars, 60)
    A5 = atr_series(tb5, 14)          # ATR(5m, 14)  —— research/37 用的基准
    A5s = atr_series(tb5, 50)         # ATR(5m, 50)  —— 平滑版（5m 噪音大）
    A15 = atr_series(tb15, 14)        # ATR(15m, 14) —— 双周期下限用
    A60 = atr_series(tb60, 14)        # ATR(1h, 14)  —— 波动率分档用
    C5 = close_sec(tb5["time"], 5)
    C15 = close_sec(tb15["time"], 15)
    C60 = close_sec(tb60["time"], 60)
    pct60 = pd.Series(A60).rolling(240, min_periods=60).rank(pct=True).to_numpy()

    # ---- 生产口径的波动率分位（`FusionResult.vol_percentile`）----
    # 口径（见 `fusion/engine.py::_vol_percentile`）：15m 收盘 pct_change 的
    # 60 根滚动标准差，再在**决策轮（1m）**上取 vol_pct_window=1440 轮滚动分位。
    # ⚠️ 研究侧必须用**同一口径**，否则会出现"回测里达标、实盘闸门却是另一个量"。
    rv15 = tb15["close"].pct_change().rolling(60).std()
    _rv = pd.Series(rv15.to_numpy(), index=close_sec(tb15["time"], 15))
    _rv = _rv[~_rv.index.duplicated()].sort_index()
    vp_prod = (_rv.reindex(t_sec, method="ffill")
               .rolling(1440, min_periods=240).rank(pct=True).to_numpy())
    # 1h 趋势（SMA50）：顺势过滤用（5m 逆势单在紧止损下极易被扫）
    cl60 = tb60["close"].to_numpy()
    sma50_60 = tb60["close"].rolling(50).mean().to_numpy()

    p("=" * 96)
    p("研究 38 · 5m 档迭代（机制优先，不做无原则的参数扫描）")
    p("=" * 96)
    p(f"1m K 线 {len(bars)} 根：{pd.to_datetime(t_sec[0], unit='s', utc=True)} .. "
      f"{pd.to_datetime(t_sec[-1], unit='s', utc=True)}")

    def look(close_arr: np.ndarray, atr_arr: np.ndarray,
             ts: float) -> float | None:
        """该周期**已收盘**的最后一根 bar 的 ATR（无前视）。"""
        i = int(np.searchsorted(close_arr, float(ts), "right")) - 1
        if i < ATR_N or i >= len(atr_arr) or not np.isfinite(atr_arr[i]) \
                or atr_arr[i] <= 0:
            return None
        return float(atr_arr[i])

    def regime_of(ts: float) -> str:
        i = int(np.searchsorted(C60, float(ts), "right")) - 1
        if i < 0 or not np.isfinite(pct60[i]):
            return "未知"
        q = float(pct60[i])
        return "低波动" if q < 1 / 3 else ("中波动" if q < 2 / 3 else "高波动")

    def volpct_of(ts: float, key: str = "atr1h") -> float:
        """波动率分位：`prod` = 生产口径（15m 已实现波动率 1440 轮滚动分位），
        `atr1h` = 研究 37 用的 ATR(1h) 240 根滚动分位。"""
        if key == "prod":
            i = int(np.searchsorted(t_sec, float(ts), "right")) - 1
            return (float(vp_prod[i])
                    if i >= 0 and np.isfinite(vp_prod[i]) else 0.5)
        i = int(np.searchsorted(C60, float(ts), "right")) - 1
        return float(pct60[i]) if i >= 0 and np.isfinite(pct60[i]) else 0.5

    def trend_ok(ts: float, direction: str) -> bool:
        """1h 收盘价是否在该周期 SMA50 的顺势一侧（数据不足 → 不拦）。"""
        i = int(np.searchsorted(C60, float(ts), "right")) - 1
        if i < 50 or not np.isfinite(sma50_60[i]):
            return True
        up = float(cl60[i]) > float(sma50_60[i])
        return up if direction == "LONG" else (not up)

    t_end = float(t_sec[-1])

    def prep(raw: list[dict]) -> list[dict]:
        out = []
        for e in raw:
            ts = float(e["ts"])
            if ts < float(t_sec[0]) or ts >= t_end:
                continue
            i0 = int(np.searchsorted(t_sec, ts, "left"))
            if i0 >= len(bars) - 2:
                continue
            a5 = look(C5, A5, ts)
            a5s = look(C5, A5s, ts)
            a15 = look(C15, A15, ts)
            if a5 is None or a5s is None or a15 is None:
                continue
            out.append(dict(e, ts=ts, i0=i0, a5=a5, a5s=a5s, a15=a15,
                            reg=regime_of(ts), vp=volpct_of(ts),
                            vpp=volpct_of(ts, "prod")))
        return out

    ent_log, ent_real = prep(load_log_entries()), prep(real_entries)
    p(f"入场样本：族A 决策日志 {len(ent_log)} 笔；族B MT5 真实开仓腿 {len(ent_real)} 笔")
    p(f"ATR 中位：ATR(5m,14)={np.median([e['a5'] for e in ent_log]):.3f}  "
      f"ATR(5m,50)={np.median([e['a5s'] for e in ent_log]):.3f}  "
      f"ATR(15m)={np.median([e['a15'] for e in ent_log]):.3f}  "
      f"→ 5m 止损约为 15m 的 "
      f"{np.median([e['a5'] for e in ent_log]) / np.median([e['a15'] for e in ent_log]):.2f} 倍")

    def sl_dist(e: dict, spec: dict) -> float:
        """按 spec 算止损距离（价格单位）。"""
        basis = spec["basis"]
        base = spec["k"] * (e["a5s"] if basis == "smooth" else e["a5"])
        if basis == "floor15":
            base = max(base, spec["f"] * e["a15"])
        return base

    def run(entries: list[dict], spec: dict) -> list[dict]:
        rows = []
        for e in entries:
            vp = e["vpp"] if spec.get("vp") == "prod" else e["vp"]
            if vp > spec["vol_max"] + 1e-9:
                continue
            if spec.get("trend") and not trend_ok(e["ts"], e["direction"]):
                continue
            sd = sl_dist(e, spec)
            if sd <= 0:
                continue
            is_long = e["direction"] == "LONG"
            tp = e["entry"] + sd * spec["rr"] if is_long else e["entry"] - sd * spec["rr"]
            sl = e["entry"] - sd if is_long else e["entry"] + sd
            oc, mv, _m = replay(bars, e["i0"], e["entry"], tp, sl, is_long,
                                spec["hold"])
            rows.append({"R": (mv - COST) / sd, "outcome": oc, "reg": e["reg"],
                         "ts": e["ts"]})
        return rows

    def judge(rows: list[dict], n_trials: int) -> tuple[dict, float, bool, bool]:
        st = stats(rows)
        d, _sr, _sr0 = dsr_of(rows, n_trials)
        if not st.get("n"):
            return st, d, False, False
        mid = float(np.median([r["ts"] for r in rows]))
        h1 = stats([r for r in rows if r["ts"] <= mid])
        h2 = stats([r for r in rows if r["ts"] > mid])
        stable = (h1.get("netR", -1) > 0 and h2.get("netR", -1) > 0)
        pass_ = (st["netR"] > 0 and np.isfinite(d) and d > 0.95)
        return st, d, pass_, stable

    # ---- 变体表（按机制分组）----
    V: list[tuple[str, str, dict]] = []
    # F1 止损倍数（基准：确认"更宽止损"能否救 5m）
    for k in (1.5, 2.0, 2.5, 3.0, 4.0):
        for rr in (1.5, 1.8):
            V.append(("F1", f"k{k}_rr{rr}",
                      dict(basis="atr5", k=k, rr=rr, hold=240, vol_max=1.0, f=0.0)))
    # F2 波动率分位上限闸（5m 的止损只在"相对波动够宽"时才够用）
    for vmax in (0.33, 0.50, 0.67):
        V.append(("F2", f"volmax{vmax}_k2.0_rr1.5",
                  dict(basis="atr5", k=2.0, rr=1.5, hold=240, vol_max=vmax, f=0.0)))
        V.append(("F2", f"volmax{vmax}_k1.5_rr1.8",
                  dict(basis="atr5", k=1.5, rr=1.8, hold=240, vol_max=vmax, f=0.0)))
    # F3 双周期下限：止损 = max(k×ATR(5m), f×ATR(15m))
    for f in (0.3, 0.5, 0.7):
        for k in (1.5, 2.0):
            V.append(("F3", f"floor15_f{f}_k{k}_rr1.5",
                      dict(basis="floor15", k=k, rr=1.5, hold=240, vol_max=1.0,
                           f=f)))
    # F4 更短的最大持有（5m 单被套住不该等 4 小时）
    for hold in (30, 60, 120, 240):
        V.append(("F4", f"hold{hold}_k2.0_rr1.5",
                  dict(basis="atr5", k=2.0, rr=1.5, hold=hold, vol_max=1.0, f=0.0)))
    # F5 平滑 ATR(5m,50)
    for k in (1.5, 2.0, 2.5):
        V.append(("F5", f"smooth_k{k}_rr1.5",
                  dict(basis="smooth", k=k, rr=1.5, hold=240, vol_max=1.0, f=0.0)))
    # ---- 第二轮：组合机制（生产口径分位 × 平滑止损 × 趋势过滤）----
    # 依据第一轮：F5（平滑 ATR，净R 最高 +61.97）与 F2（波动率上限闸，唯一
    # "前后半段皆正"且族B 同向为正）各自治住了一半问题 —— 前者治住"5m 噪音大、
    # ATR(14) 抖动"，后者治住"高波动下紧止损必被扫"。故把两者合起来，
    # 并把分位换成**生产口径**（15m 已实现波动率 1440 轮滚动分位），
    # 使回测与未来的实盘闸门是同一个量。
    for k in (2.5, 3.0):
        for vmax in (0.33, 0.50, 0.67):
            V.append(("K", f"prod_vmax{vmax}_smooth_k{k}_rr1.5",
                      dict(basis="smooth", k=k, rr=1.5, hold=240, vol_max=vmax,
                           f=0.0, vp="prod")))
    for vmax in (0.33, 0.50):
        V.append(("K", f"prod_vmax{vmax}_atr5_k1.5_rr1.8",
                  dict(basis="atr5", k=1.5, rr=1.8, hold=240, vol_max=vmax,
                       f=0.0, vp="prod")))
    for vmax in (0.33, 0.50):
        V.append(("K", f"prod_vmax{vmax}_smooth_k2.5_trend",
                  dict(basis="smooth", k=2.5, rr=1.5, hold=240, vol_max=vmax,
                       f=0.0, vp="prod", trend=True)))
    # ---- 第三轮：补上第二轮**漏掉的那一格** ----
    # 第二轮把"平滑止损"与**生产口径**分位组合，结果更弱（最好 +22.99 / tR 1.51）；
    # 但"平滑止损 × **ATR(1h) 分位**上限"这一格从未测过 —— 而它才是把
    # "净R 最高"（F5）与"唯一稳健"（F2）放进同一格的组合。
    for k in (2.5, 3.0):
        for vmax in (0.50, 0.67):
            V.append(("K2", f"atr1h_vmax{vmax}_smooth_k{k}_rr1.5",
                      dict(basis="smooth", k=k, rr=1.5, hold=240, vol_max=vmax,
                           f=0.0)))
    # ---- 第四轮：**生产口径的落点几何**（要上线的是这一格，必须先量出来）----
    # 生产实际几何 = 止损 min(结构失效边界, k×ATR(entry_tf))、止盈
    # max(缩水结构目标, 止损×盈亏比下限)，且盈亏比下限 = `min_rr`（1.5，用户指定）。
    # 结构边界通常远于封顶（实测 15m 边界约 28 点 vs 封顶 1.5×3.87≈5.8），
    # 故落点等价于「止损 k×ATR(5m) + 盈亏比恰为 1.5 + 波动率上限闸」。
    # ⚠️ 这一格此前从未量过（F2 只测了 k1.5_rr1.8 与 k2.0_rr1.5）——
    #    不能拿"盈亏比 1.8 的那格"当作上线后的表现。
    for k in (1.2, 1.5, 2.0):
        for vmax in (0.50, 0.67):
            V.append(("P", f"prodgeom_vmax{vmax}_k{k}_rr1.5",
                      dict(basis="atr5", k=k, rr=1.5, hold=240, vol_max=vmax,
                           f=0.0)))

    n_trials = N_BASE + len(V)
    cnt = {f: sum(1 for x, _, _ in V if x == f)
           for f in ("F1", "F2", "F3", "F4", "F5", "K", "K2", "P")}
    p(f"本轮变体 {len(V)} 个（" + " / ".join(f"{k} {v}" for k, v in cnt.items() if v)
      + f"）  → **累计试验族 N={n_trials}**（含 research/37 的 {N_BASE} 次）")

    p("")
    p("【变体结果】族A（决策日志首仓 253 笔）；达标 = 净R>0 且 DSR>0.95；"
      "稳健 = 前后半段皆为正")
    p("")
    scored: list[tuple[float, str, str, dict, dict, float, bool, bool, list[dict]]] = []
    for fam, name, spec in V:
        rows = run(ent_log, spec)
        if not rows:
            continue
        st, d, ok, stable = judge(rows, n_trials)
        scored.append((st.get("netR", -1e9), fam, name, spec, st, d, ok, stable, rows))
    scored.sort(key=lambda x: -x[0])
    for netR, fam, name, _spec, st, d, ok, stable, _rows in scored[:20]:
        flag = "<= 达标" if ok else ("<= 稳健(正) " if stable else "")
        p(f"  [{fam}] {name:<26} {fmt(st)}  DSR{d:>6.3f} {flag}")

    p("")
    p("【第二轮 组合机制】全部 K 族（生产口径分位 × 平滑止损 × 趋势过滤）")
    for netR, fam, name, _spec, st, d, ok, stable, _rows in scored:
        if fam != "K":
            continue
        flag = "<= 达标" if ok else ("<= 稳健(正)" if stable else "")
        p(f"  [K] {name:<34} {fmt(st)}  DSR{d:>6.3f} {flag}")

    p("")
    p("【第四轮 生产落点几何】全部 P 族（止损 k×ATR(5m)、盈亏比恰为全局下限 1.5、"
      "波动率上限闸）—— 上线后实际跑的就是这一格")
    for netR, fam, name, spec, st, d, ok, stable, rows in scored:
        if fam != "P":
            continue
        e2 = run(ent_real, spec)
        s2 = stats(e2)
        d2, _sr2, _sr02 = dsr_of(e2, n_trials)
        seg = []
        for rg in ("低波动", "中波动", "高波动"):
            s3 = stats([r for r in rows if r["reg"] == rg])
            seg.append(f"{rg}{s3.get('netR', 0):+.1f}(n{s3.get('n', 0)})")
        p(f"  [P] {name:<30} 族A {fmt(st)} DSR{d:>6.3f} "
          f"稳健={'是' if stable else '否'}")
        p(f"{'':>8}族B {fmt(s2)} DSR{d2:>6.3f} 分档 " + " ".join(seg))

    p("")
    p("【分波动率档】前 6 名（5m 的死因是否被治住：高波动档不再拖后腿？）")
    for netR, fam, name, _spec, st, d, ok, stable, rows in scored[:6]:
        seg = []
        for rg in ("低波动", "中波动", "高波动"):
            s2 = stats([r for r in rows if r["reg"] == rg])
            seg.append(f"{rg}{s2.get('netR', 0):+.1f}(n{s2.get('n', 0)})")
        p(f"  [{fam}] {name:<26} " + " ".join(seg) + f"  合计{netR:+.2f}")

    p("")
    p("【DSR 门槛差距】达标的物理含义：本策略 Sharpe 必须显著超过 `sr0`"
      "（= n_trials 次尝试下**纯运气**能达到的最大 Sharpe）")
    for netR, fam, name, spec, st, d, ok, stable, rows in scored[:5]:
        _d, sr, sr0 = dsr_of(rows, n_trials)
        e2 = run(ent_real, spec)
        _d2, sr2, sr02 = dsr_of(e2, n_trials)
        need = "已超过" if sr > sr0 else "**未超过**"
        p(f"  [{fam}] {name:<34} 族A Sharpe={sr:.3f} vs sr0={sr0:.3f}"
          f"（{need}）  DSR={d:.3f}")
        p(f"{'':>10}族B Sharpe={sr2:.3f} vs sr0={sr02:.3f}"
          f"（{'已超过' if sr2 > sr02 else '**未超过**'}）")
    p("  ⚠️ 每多试一个变体，`sr0` 就抬高一档 —— 所以「再扫一批参数」")
    p("     在数学上**降低**达标概率，不是提高。")

    # ---- 族B 交叉验证（真实成交开仓腿 502 笔）----
    p("")
    p("【族B 交叉验证】**所有族A 为正**的变体在 MT5 真实开仓腿上的表现"
      "（真实成交价/时刻；这是防「只有决策日志这批单子才成立」的关键一列）")
    for netR, fam, name, spec, st, d, ok, stable, _rows in scored:
        if netR <= 0:
            continue
        e2 = run(ent_real, spec)
        s2 = stats(e2)
        d2, _sr2, _sr02 = dsr_of(e2, n_trials)
        p(f"  [{fam}] {name:<34} 族B {fmt(s2)}  DSR{d2:>6.3f}"
          f"  {'同向(正)' if s2.get('netR', 0) > 0 else '⚠️ 反向'}")

    # ---- 结论与登记 ----
    best = scored[0] if scored else None
    p("")
    p("=" * 96)
    if best:
        netR, fam, name, spec, st, d, ok, stable, rows = best
        seg = []
        for rg in ("低波动", "中波动", "高波动"):
            s2 = stats([r for r in rows if r["reg"] == rg])
            seg.append(f"{rg}{s2.get('netR', 0):+.1f}")
        p(f"【最佳 5m 变体】[{fam}] {name}：{fmt(st)} DSR{d:.3f} "
          f"稳健={'是' if stable else '否'} 达标={'是' if ok else '否'}")
        p(f"  分档：{' / '.join(seg)}")
    p(f"沿用门槛：净R > 0 且 DSR > 0.95（N={n_trials}）。"
      f"{'达标' if (best and best[6]) else '**未达标**'}")
    p("⚠️ 累计 N 越大、DSR 门槛越高 —— 这正是「不能靠扫参数把结果扫好看」的机制，")
    p("   故若本轮未达标，下一步应换**机制**（不是继续堆变体数量）。")
    p("=" * 96)

    trial_rows: list[tuple[str, str, float, str]] = []
    for _netR, fam, name, _spec, st, d, ok, stable, _rows in scored:
        trial_rows.append((
            f"5m_iter_{fam}", name,
            (d if np.isfinite(d) else 0.0),
            f"族A {fmt(st)} DSR(N={n_trials}) 稳健={'是' if stable else '否'} "
            f"达标={'是' if ok else '否'}"))
    trial_rows.append((
        "sltp_5m_iterate", f"FAMILY_N{len(V)}", (best[5] if best else 0.0),
        f"结论 5m 迭代 {len(V)} 变体 最佳=[{best[1]}] {best[2]} "
        f"净R{best[4]['netR']:+.2f} tR{best[4]['tR']:+.2f} "
        f"DSR(N={n_trials})={best[5]:.3f} 达标={'是' if best[6] else '否'} "
        f"稳健={'是' if best[7] else '否'} 脚本=research/38_sltp_5m_iterate.py"))
    nreg = register_trials(trial_rows)
    p(f"已登记 data/trials.csv：新增 {nreg} 行（幂等）")

    out = ROOT / "research" / "38_sltp_5m_iterate_out.txt"
    try:
        out.write_text("\n".join(OUT), encoding="utf-8")
        p(f"已保存：{out.relative_to(ROOT)}")
    except Exception as e:
        p(f"（保存失败：{e}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
