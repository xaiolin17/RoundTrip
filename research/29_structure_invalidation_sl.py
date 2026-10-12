# -*- coding: utf-8 -*-
"""研究取证 29：按「结构失效边界 + 真实波幅修正 + 不利波动分位」重定止损，
止盈不足 1.8 时扩到下一级结构位（历史回放）。

用户 2026-10-10 指定（原话）：
> 根据结构失效边界、真实波幅修正、不利波动分位和风险预算反推
> 重新对黄金开仓和止损止盈进行优化

四个因子的落点
--------------
1. **结构失效边界**：最近一段**同向**走势段的起点（做多 = 上行段起点低点，
   做空 = 下行段起点高点）。价格跌破/升破它，该段结构即失效。
   历史回放里用 15m 的自研摆动检测 `find_swings`/`alternate_swings`
   复现（与线上 `structure.last_leg` 同一套逻辑）。
2. **真实波幅修正**：在结构边界外再加 `k_vol × ATR` 缓冲，避免贴着边界
   被一根影线扫掉。
3. **不利波动分位**：历史上价格**逆着我的方向**走的最大偏移（MAE）在
   ATR 尺度下的经验分位。止损至少要跨过 p 分位，否则会被噪音打掉。
4. **风险预算反推**：手数已由 `position_lots` 按**实际止损距离**反推
   （本脚本不动它，只验证止损距离的量级是否还能容纳最小手数风险）。

对比的三个方案（隔离变量）
--------------------------
* A：「现状」——历史真实下过的单（`risk_decision` 的 sl/tp），
  止损由止盈按 `min_rr` 反推（`sl_source=rr_from_tp`）。
* B：**只换止损** —— 止损改锚结构失效边界 + 波动缓冲 + MAE 下限，
  止盈仍用 A 的止盈。→ 隔离"止损改锚"的单独效应。
* C：**新方案完整形态** —— B 的止损 + 止盈改为"最近的、满足
  盈亏比 1.8 的结构位"（不足则扩到下一级结构位）。

⚠️ 诚实声明
------------
· 结构边界用 15m 自研摆动检测**代理**线上缠论段起点，二者不完全等价；
  但自研检测正是线上入场位（`own_candidates`）所用的同一套，量级可信。
· 止盈"下一级结构位"用 15m 摆动高/低点代理线上缠论中枢 + SMC OB 位。
· 入场用 `entry_ref`（决策时现价），非真实成交价 → 有轻微滑点误差。
· 未决单按最后一根收盘价 mark-to-market，不当作 0。
· 这是**同一批历史信号**下的反事实 A/B/C，不是择时研究。

跑法::

    & $py research/29_structure_invalidation_sl.py
"""
from __future__ import annotations

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

from gold_agent.risk.structure import (alternate_swings,  # noqa: E402
                                       find_swings)

OUT: list[str] = []
COST = 0.240            # XAUUSDm 实测往返点差（价格单位）
MAX_HOLD_MIN = 14400    # 最长持有（1m 根数）= 10 天
SWING_K = 2             # 15m 摆动确认根数


def p(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


# ══════════════════════════════════════════════════════════════════
# 数据
# ══════════════════════════════════════════════════════════════════
def load_bars(symbol: str = "XAUUSDm") -> pd.DataFrame | None:
    """1m K 线：优先 MT5 实时，退回本地缓存。"""
    df = None
    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            try:
                import datetime as _dt
                rates = mt5.copy_rates_from(symbol, mt5.TIMEFRAME_M1,
                                            _dt.datetime.now(_dt.UTC), 90000)
                if rates is not None and len(rates):
                    df = pd.DataFrame(rates)
                    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
            finally:
                try:
                    mt5.shutdown()
                except Exception:
                    pass
    except Exception as e:
        p(f"  [提示] MT5 取数失败（{type(e).__name__}），改用缓存")
    if df is None or df.empty:
        c = ROOT / "data" / "cache" / f"{symbol}_1m.parquet"
        if c.exists():
            d = pd.read_parquet(c)
            tcol = next((x for x in d.columns
                         if x.lower() in ("time", "datetime", "date", "timestamp")), None)
            if tcol:
                d["time"] = pd.to_datetime(d[tcol], utc=True, errors="coerce")
                df = d.dropna(subset=["time"])
    if df is None:
        return None
    need = {"open", "high", "low", "close"}
    if not need.issubset(df.columns):
        return None
    return df.sort_values("time").reset_index(drop=True)


def resample_tf(df1m: pd.DataFrame, rule: str) -> pd.DataFrame:
    d = df1m.set_index("time").resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return d.reset_index()


def atr_1h_aligned(df1m: pd.DataFrame, mult: float = 1.0) -> np.ndarray:
    """14 周期 1h ATR，映射到每根 1m（无前视：shift(1)）。"""
    d1h = df1m.set_index("time").resample("1h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    tr = pd.concat([d1h["high"] - d1h["low"],
                    (d1h["high"] - d1h["close"].shift()).abs(),
                    (d1h["low"] - d1h["close"].shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().reindex(df1m["time"], method="ffill").shift(1)
    a = atr.to_numpy(float) * mult
    return np.where(np.isfinite(a) & (a > 0), a, np.nan)


# ══════════════════════════════════════════════════════════════════
# 历史入场
# ══════════════════════════════════════════════════════════════════
def load_entries(symbol: str = "XAUUSDm") -> list[dict]:
    """从 trades.jsonl 取历史**首仓**决策（市价首仓 + 挂单首仓）。

    ⚠️ 日志覆盖多品种时代，须按 `symbol` 剔除非黄金残留；再加价格带兜底
    ——否则 BTC/指数类的高价 `entry_ref` 会把价差算成数万，污染统计。
    """
    pth = ROOT / "logs" / "trades.jsonl"
    out: list[dict] = []
    if not pth.exists():
        return out
    for line in pth.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("event") != "risk_decision":
            continue
        if r.get("kind") not in ("open_market", "place_pending"):
            continue
        if r.get("symbol") not in (None, symbol):
            continue
        d = r.get("direction")
        e, tp, sl = r.get("entry_ref"), r.get("tp"), r.get("sl")
        ts = r.get("ts")
        if d not in ("LONG", "SHORT") or None in (e, tp, sl, ts):
            continue
        try:
            e, tp, sl, ts = float(e), float(tp), float(sl), float(ts)
        except (TypeError, ValueError):
            continue
        if not all(500.0 <= v <= 8000.0 for v in (e, tp, sl)):   # 黄金价格带
            continue
        out.append({"direction": d, "entry": e, "tp": tp, "sl": sl, "ts": ts,
                    "kind": r.get("kind")})
    return out


# ══════════════════════════════════════════════════════════════════
# 结构（15m 自研摆动检测）
# ══════════════════════════════════════════════════════════════════
def structure_at(df15: pd.DataFrame, ts: float,
                 is_long: bool) -> tuple[float | None, list[float], list[float]]:
    """返回 (结构失效边界, 上方摆动高列表, 下方摆动低列表)。

    结构失效边界：从交替序列末尾往前找**最近的、方向匹配**的一段，
    取其起点价（做多=上行段起点低点；做空=下行段起点高点）。
    """
    t = pd.Timestamp(ts, unit="s", tz="UTC")
    sub = df15[df15["time"] < t]
    if len(sub) < 20:
        return None, [], []
    alt = alternate_swings(find_swings(sub, SWING_K))
    if len(alt) < 2:
        return None, [], []
    boundary = None
    for j in range(len(alt) - 1, 0, -1):
        up = (alt[j][1] == "H")
        if up == is_long:
            boundary = float(alt[j - 1][2])
            break
    highs = sorted(float(x) for _, k, x in alt if k == "H")
    lows = sorted(float(x) for _, k, x in alt if k == "L")
    return boundary, highs, lows


def next_tp_above(levels: list[float], entry: float, need: float) -> float | None:
    """最近的、且距入场 >= need 的上方结构位（不足则取更上一级）。"""
    for lv in levels:
        if lv - entry >= need:
            return lv
    return None


def next_tp_below(levels: list[float], entry: float, need: float) -> float | None:
    """最近的、且距入场 >= need 的下方结构位（不足则取更下一级）。"""
    for lv in reversed(levels):
        if entry - lv >= need:
            return lv
    return None


# ══════════════════════════════════════════════════════════════════
# 回放
# ══════════════════════════════════════════════════════════════════
def replay(bars: pd.DataFrame, i0: int, entry: float, tp: float, sl: float,
           is_long: bool) -> tuple[str, float, int]:
    """从第 i0 根起逐根回放。返回 (结局, 价格变动（按方向）, 用掉的分钟数)。

    保守规则：**同一根内同时触及止损与止盈 → 判止损**（不给乐观偏差）。
    """
    hi = bars["high"].to_numpy()
    lo = bars["low"].to_numpy()
    cl = bars["close"].to_numpy()
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


def mae_atr(bars: pd.DataFrame, i0: int, entry: float, is_long: bool,
            atr: float) -> float:
    """窗口内最大不利偏移（MAE），按 ATR 归一。"""
    hi = bars["high"].to_numpy()
    lo = bars["low"].to_numpy()
    end = min(len(bars), i0 + MAX_HOLD_MIN)
    if end <= i0 or not (atr and atr > 0):
        return float("nan")
    if is_long:
        worst = float(lo[i0:end].min())
        return max(0.0, (entry - worst)) / atr
    worst = float(hi[i0:end].max())
    return max(0.0, (worst - entry)) / atr


def first_touch(bars: pd.DataFrame, i0: int, entry: float,
                is_long: bool) -> int | None:
    """挂单成交判定：从 i0 起找第一根**价格触及挂单价**的 1m 根。

    挂单价是未来价位，只有价格真的走到它才算成交；在此之前不存在持仓，
    因此 MAE/回放都必须从成交那根起算（否则会用未来价当成交价，产生巨大伪盈亏）。
    """
    hi = bars["high"].to_numpy()
    lo = bars["low"].to_numpy()
    end = min(len(bars), i0 + MAX_HOLD_MIN)
    for j in range(i0, end):
        if is_long and lo[j] <= entry:
            return j
        if (not is_long) and hi[j] >= entry:
            return j
    return None


def tstat(xs: list[float]) -> float:
    """单样本 t 统计量（零假设：均值 = 0）。样本不足/含非有限值/方差为 0 时返回 nan。"""
    arr = [x for x in xs if np.isfinite(x)]
    n = len(arr)
    if n < 3:
        return float("nan")
    m = sum(arr) / n
    var = sum((x - m) ** 2 for x in arr) / (n - 1)
    sd = math.sqrt(var)
    if not np.isfinite(sd) or sd <= 0:
        return float("nan")
    return float(m / (sd / math.sqrt(n)))


def summarize(lst: list[tuple[str, float, float]]) -> dict:
    """lst: [(结局, 价格变动, 止损距离), ...]。

    · `mn`  价格口径净期望（P&L/笔）——**不做仓位归一，仅供参考**；
    · `mR`  R 倍数净期望（(P&L-成本)/止损距离）——风控口径，固定风险预算下
      仓位与止损距离成反比，R 才是方案间**可比**的度量。
    """
    if not lst:
        return {}
    wins = sum(1 for o, _, _ in lst if o == "止盈")
    loss = sum(1 for o, _, _ in lst if o == "止损")
    tout = sum(1 for o, _, _ in lst if o == "超时")
    gross = [g for _, g, _ in lst]
    rs = [(g - COST) / d for _, g, d in lst if d and d > 0 and np.isfinite(d)]
    mg = sum(gross) / len(gross)
    mr = sum(rs) / len(rs) if rs else float("nan")
    return dict(n=len(lst), wins=wins, loss=loss, tout=tout,
                wr=wins / len(lst), mg=mg, mn=mg - COST, t=tstat(gross),
                mR=mr, tR=tstat(rs), worst=min(gross), best=max(gross))


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════
def main() -> int:
    min_rr = 1.8
    min_atr = 0.5
    try:
        from gold_agent.common.config import CFG
        min_rr = float(CFG.risk.min_rr)
        min_atr = float(CFG.risk.structure_sl_min_atr)
    except Exception:
        pass

    p("=" * 100)
    p("研究取证 29 · 止损改锚「结构失效边界 + 真实波幅 + 不利波动分位」（历史回放）")
    p("=" * 100)

    bars = load_bars()
    if bars is None or bars.empty:
        p("!! 拿不到 1m K 线，无法回放。")
        return 1
    df15 = resample_tf(bars, "15min")
    atr1h = atr_1h_aligned(bars, mult=1.0)
    atr_map = atr_1h_aligned(bars, mult=float(min_atr))   # 下限用
    ns = bars["time"].astype("datetime64[ns, UTC]").astype("int64").to_numpy()

    p("")
    p(f"  1m K 线：{len(bars)} 根，{bars['time'].iloc[0]} .. {bars['time'].iloc[-1]}")
    p(f"  15m K 线：{len(df15)} 根   当前参数：min_rr={min_rr} "
      f"structure_sl_min_atr={min_atr}  成本={COST}")

    rows = load_entries()
    n_mkt = sum(1 for r in rows if r.get("kind") == "open_market")
    n_pnd = sum(1 for r in rows if r.get("kind") == "place_pending")
    p(f"  历史首仓决策：{len(rows)} 笔（市价 {n_mkt} · 挂单 {n_pnd}）")

    # ---- 第一遍：算决策时的 ATR / 结构边界，及成交后的 MAE ----
    # 系统在**决策时**算好 ATR 与结构位；但持仓只有**成交后**才存在，
    # 所以 MAE/回放一律从成交那根起（挂单需先被价格触及）。
    recs: list[dict] = []
    n_unfilled = 0
    for r in rows:
        ts = r["ts"]
        i0 = int(np.searchsorted(ns, int(pd.Timestamp(ts, unit="s", tz="UTC").value),
                                 side="left"))
        if i0 >= len(bars) - 5:
            continue
        is_long = r["direction"] == "LONG"
        atr = float(atr1h[i0])
        if not np.isfinite(atr) or atr <= 0:
            continue
        if r.get("kind") == "place_pending":
            i_fill = first_touch(bars, i0, r["entry"], is_long)
            if i_fill is None:          # 挂单始终没成交 → 无持仓，剔除
                n_unfilled += 1
                continue
        else:
            i_fill = i0
        bnd, highs, lows = structure_at(df15, ts, is_long)
        if bnd is not None:
            # 有效失效边界必须在**正确的一侧**（做多在下方、做空在上方），
            # 否则说明最近的同向段起点已在入场价之内，不能当止损锚。
            if (is_long and bnd >= r["entry"]) or \
               ((not is_long) and bnd <= r["entry"]):
                bnd = None
        m = mae_atr(bars, i_fill, r["entry"], is_long, atr)
        recs.append(dict(r, i0=i_fill, atr=atr, is_long=is_long, bnd=bnd,
                         highs=highs, lows=lows, mae=m))

    p(f"  可回放样本：{len(recs)} 笔（挂单未成交剔除 {n_unfilled} 笔）")
    if not recs:
        p("\n无样本，不可结论。")
        return 0

    # ---- 不利波动分位（MAE/ATR 的经验分位）----
    maes = [x["mae"] for x in recs if np.isfinite(x["mae"])]
    qs = {}
    if maes:
        arr = np.array(maes)
        for q in (0.50, 0.70, 0.80, 0.90):
            qs[q] = float(np.quantile(arr, q))
    p("")
    p("=" * 100)
    p("A. 不利波动分位（MAE/ATR，窗口最多 10 天）")
    p("=" * 100)
    p(f"  样本 {len(maes)} 笔")
    for q in (0.50, 0.70, 0.80, 0.90):
        p(f"  p{int(q*100)} = {qs.get(q, float('nan')):.3f} × ATR")
    p("  → 止损至少跨过所选分位，才不会长期被噪音打掉。")

    # ---- 第二遍：对 MAE 下限系数 K_MAE 做小范围扫描，B/C 各回放一次 ----
    # 不把 p80 直接钉死，而是扫 0 / p50 / p70 / p80，用净期望与 t 值挑值，
    # 避免「MAE 下限把止损推得过远」的单点过拟合。
    K_VOL = 0.5                     # 结构边界外的波动缓冲（ATR 倍数）
    K_MAE_LIST = [("纯结构 K=0", 0.0),
                  ("K=p50", qs.get(0.50, 0.0)),
                  ("K=p70", qs.get(0.70, 0.0)),
                  ("K=p80", qs.get(0.80, 0.0))]

    res: dict[str, list[tuple[str, float]]] = {"A 现状(rr_from_tp)": []}
    for label, _ in K_MAE_LIST:
        res[f"B 结构止损+原止盈 [{label}]"] = []
        res[f"C 结构止损+结构止盈 [{label}]"] = []

    detail: list[dict] = []
    sl_atr: dict[str, list[float]] = {lb: [] for lb, _ in K_MAE_LIST}
    n_no_bnd = 0
    for x in recs:
        e, is_long, atr, bnd = x["entry"], x["is_long"], x["atr"], x["bnd"]
        if bnd is None:
            n_no_bnd += 1
            continue
        struct_dist = abs(e - bnd)
        floor = float(min_atr) * atr
        tpa, sla = x["tp"], x["sl"]        # 方案 A：历史真实 sl/tp
        d_a = abs(e - sla)

        oa, ga, _ = replay(bars, x["i0"], e, tpa, sla, is_long)
        res["A 现状(rr_from_tp)"].append((oa, ga, d_a))

        for lb, km in K_MAE_LIST:
            sl_dist = max(struct_dist + K_VOL * atr, km * atr, floor)
            need = min_rr * sl_dist
            # 方案 B：结构止损 + 原止盈
            slb = (e - sl_dist) if is_long else (e + sl_dist)
            # 方案 C：结构止损 + 最近的、满足赔率的结构位当止盈
            if is_long:
                tpc = next_tp_above(x["highs"], e, need)
            else:
                tpc = next_tp_below(x["lows"], e, need)
            if tpc is None:
                tpc = (e + need) if is_long else (e - need)
            ob, gb, _ = replay(bars, x["i0"], e, tpa, slb, is_long)
            oc, gc, _ = replay(bars, x["i0"], e, tpc, slb, is_long)
            res[f"B 结构止损+原止盈 [{lb}]"].append((ob, gb, sl_dist))
            res[f"C 结构止损+结构止盈 [{lb}]"].append((oc, gc, sl_dist))
            sl_atr[lb].append(sl_dist / atr if atr > 0 else float("nan"))
        detail.append(dict(d=x["direction"], e=e, atr=atr, bnd=bnd,
                           tpa=tpa, oa=oa, ga=ga))

    p(f"  （跳过 {n_no_bnd} 笔：无可用结构边界）")
    p("")
    p("  止损距离量级（sl_dist / 1h-ATR 的中位数 / p80）：")
    for lb, _ in K_MAE_LIST:
        arr = np.array([v for v in sl_atr[lb] if np.isfinite(v)])
        if len(arr):
            p(f"    {lb:<12} 中位 {np.quantile(arr, 0.5):.2f}×ATR   "
              f"p80 {np.quantile(arr, 0.8):.2f}×ATR")
    p("")
    p("=" * 100)
    p("B. 方案回放对比（同一批历史信号，A 为现状基准）")
    p("=" * 100)
    p("")
    p(f"  {'方案':<30}{'止盈':>6}{'止损':>6}{'超时':>6}{'胜率':>8}"
      f"{'净R':>9}{'tR':>7}{'对A(R)':>9}{'净价':>9}")
    p("  " + "-" * 100)
    summ: dict[str, dict] = {}
    for name, lst in res.items():
        s = summarize(lst)
        if not s:
            continue
        summ[name] = s
        base_r = summ.get("A 现状(rr_from_tp)", {}).get("mR", 0.0)
        p(f"  {name:<30}{s['wins']:>6}{s['loss']:>6}{s['tout']:>6}{s['wr']:>7.1%}"
          f"{s['mR']:>+9.3f}{s['tR']:>+7.2f}{s['mR'] - base_r:>+9.3f}{s['mn']:>+9.2f}")

    # ---- 判读 ----
    if "A 现状(rr_from_tp)" in summ:
        a = summ["A 现状(rr_from_tp)"]
        p("")
        p("=" * 100)
        p("C. 判读（风控口径：净R = 每笔 (P&L-成本)/止损距离）")
        p("=" * 100)
        p("")
        p(f"  A 现状(rr_from_tp)：净R {a['mR']:+.3f}  胜率 {a['wr']:.1%}  "
          f"止损 {a['loss']}  tR={a['tR']:+.2f}")
        p("")
        best = max(summ.items(), key=lambda kv: kv[1]["mR"])
        for name, s in summ.items():
            if name == "A 现状(rr_from_tp)":
                continue
            mark = "  ← 风控口径最优" if name == best[0] else ""
            p(f"  {name:<30} 净R {s['mR']:+.3f}  胜率 {s['wr']:.1%}  "
              f"止损 {s['loss']}  tR={s['tR']:+.2f}  （对 A {s['mR']-a['mR']:+.3f}）{mark}")
        p("")
        if len(detail) < 100:
            p(f"  [警示] 样本 {len(detail)} < 100，结论仅供参考，不足以支撑参数定案。")
        p(f"  风控口径最优：{best[0]}（净R {best[1]['mR']:+.3f}，tR={best[1]['tR']:+.2f}）")
        p("  判读口径：净R>0 且 |tR|>=2 才算「有统计意义」；tR<2 只作方向参考，"
          "仍需记录 N 并后续跟踪。")

    out = ROOT / "research" / "29_structure_invalidation_sl_out.txt"
    try:
        out.write_text("\n".join(OUT), encoding="utf-8")
        p(f"\n已保存：{out.relative_to(ROOT)}")
    except Exception as e:
        p(f"\n（保存失败：{e}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
