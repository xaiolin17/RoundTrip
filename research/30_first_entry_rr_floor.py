# -*- coding: utf-8 -*-
"""研究取证 30：首仓「赔率硬闸」——按 RR 分桶与阈值扫描（历史回放）。

背景
----
用户 2026-10-12 发现一笔持仓盈亏比极低：

    LONG entry=4208.866 sl=4178.142 tp=4215.44  sl_source=struct_invalidation
    tp_dist=6.574  sl_dist=30.724  → RR ≈ 0.21

成因：止损锚 15m 结构失效边界（距离 30.72），止盈被「缩 70% + 0.5×ATR 下限」
托到 6.574，而 `struct_invalidation` 路径**刻意没有赔率下限**；首仓又**没有
LLM plan 复核**（只有加仓有 `add_review`）→ 低赔率首仓毫无拦截。
用户决策：在 gate 首仓分支加**本地赔率硬闸**（RR 低于阈值直接拒单），
阈值**先跑本脚本用数据定**。

问题
----
历史上「低 RR 首仓」是否系统性亏损？若是，加 RR 下限应**提升净 R**；
若否（低 RR 也正期望），硬闸会**误杀**盈利单。
本脚本用同一批历史首仓做反事实：分别剔除 RR<X 的单，看净 R 与 tR 怎么变。

口径
----
· 净 R（风控口径）= 每笔 (P&L − 成本) / 止损距离。固定风险预算下仓位与止损
  距离成反比，**R 才是跨方案可比**的度量；净价（P&L）仅供参照。
· 回放保守规则：同一根内同时触及止损与止盈 → **判止损**（不给乐观偏差）。
· 首仓样本：`open_market`（市价首仓）+ `place_grid` 的每个挂单层
  （挂单层需价格先触及挂单价才成交，MAE/回放从成交那根起算）。

⚠️ 诚实声明
------------
· 历史日志横跨多版策略，`struct_invalidation` 首仓仅 1 笔（即上面那笔）。
  本脚本**不重建**当前策略定价，而是把 RR 当作**交易自身属性**（tp/sl 相对
  入场距离），跨策略统计「RR 与净 R 的关系」——这是评估「RR 下限」这一
  **风控规则**的合理口径，但不能等同于「新策略下的精确 RR 分布」。
· 入场用 `entry_ref`（决策时现价），非真实成交价 → 有轻微滑点误差。
· 未决单按最后一根收盘价 mark-to-market，不当作 0。
· 这是**同一批历史信号**下的反事实筛选，不是择时研究，也不是新策略回测。

跑法::

    & $py research/30_first_entry_rr_floor.py
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

OUT: list[str] = []
COST = 0.240            # XAUUSDm 实测往返点差（价格单位）
MAX_HOLD_MIN = 14400    # 最长持有（1m 根数）= 10 天
CANDIDATES = [0.8, 1.0, 1.2, 1.4, 1.8]   # 候选赔率下限


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


# ══════════════════════════════════════════════════════════════════
# 历史首仓
# ══════════════════════════════════════════════════════════════════
def load_entries(symbol: str = "XAUUSDm") -> list[dict]:
    """从 trades.jsonl 取历史**首仓**决策，展开成逐笔。

    · `open_market`：一笔 = 一个市价首仓（entry_ref / tp / sl）。
    · `place_grid` ：一笔 = 每个挂单层（level 当入场价，tp / sl 各自）。
    日志覆盖多品种时代，按 `symbol` 剔除非黄金残留；再加价格带兜底
    ——否则 BTC/指数类高价 `entry_ref` 会把价差算成数万，污染统计。
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
        kind = r.get("kind")
        if kind not in ("open_market", "place_pending", "place_grid"):
            continue
        if r.get("symbol") not in (None, symbol):
            continue
        d = r.get("direction")
        ts = r.get("ts")
        if d not in ("LONG", "SHORT") or ts is None:
            continue
        try:
            ts = float(ts)
        except (TypeError, ValueError):
            continue

        if kind == "place_grid":
            for lay in (r.get("layers") or []):
                e, tp, sl = lay.get("level"), lay.get("tp"), lay.get("sl")
                row = _mk(d, e, tp, sl, ts, "place_grid", "grid", symbol)
                if row:
                    out.append(row)
            continue

        e, tp, sl = r.get("entry_ref"), r.get("tp"), r.get("sl")
        row = _mk(d, e, tp, sl, ts, kind, r.get("sl_source"), symbol)
        if row:
            out.append(row)
    return out


def _mk(d, e, tp, sl, ts, kind, sl_source, symbol) -> dict | None:
    if None in (e, tp, sl):
        return None
    try:
        e, tp, sl = float(e), float(tp), float(sl)
    except (TypeError, ValueError):
        return None
    if not all(500.0 <= v <= 8000.0 for v in (e, tp, sl)):   # 黄金价格带
        return None
    is_long = d == "LONG"
    tp_dist = (tp - e) if is_long else (e - tp)
    sl_dist = (e - sl) if is_long else (sl - e)
    if sl_dist <= 0 or tp_dist <= 0:        # 方向与 sl/tp 不匹配的脏数据
        return None
    return dict(direction=d, entry=e, tp=tp, sl=sl, ts=ts, kind=kind,
                sl_source=sl_source or "none", symbol=symbol,
                is_long=is_long, tp_dist=tp_dist, sl_dist=sl_dist,
                rr=tp_dist / sl_dist)


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


def first_touch(bars: pd.DataFrame, i0: int, entry: float,
                is_long: bool) -> int | None:
    """挂单成交判定：从 i0 起找第一根**价格触及挂单价**的 1m 根。

    挂单价是未来价位，只有价格真的走到它才算成交；在此之前不存在持仓，
    因此回放必须从成交那根起算（否则会用未来价当成交价，产生巨大伪盈亏）。
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
    · `mR`  R 倍数净期望（(P&L-成本)/止损距离）——风控口径，跨方案可比。
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
                wr=wins / len(lst), mg=mg, mn=mg - COST,
                mR=mr, tR=tstat(rs), tn=tstat(gross),
                worst=min(gross), best=max(gross))


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════
BUCKETS = [(0.0, 0.5), (0.5, 0.8), (0.8, 1.0), (1.0, 1.2),
           (1.2, 1.3), (1.3, 1.4), (1.4, 1.5), (1.5, 1.6), (1.6, 1.8),
           (1.8, 2.0), (2.0, 2.5), (2.5, 1e9)]


def main() -> int:
    p("=" * 100)
    p("研究取证 30 · 首仓「赔率硬闸」：RR 分桶 + 阈值扫描（历史回放）")
    p("=" * 100)

    bars = load_bars()
    if bars is None or bars.empty:
        p("!! 拿不到 1m K 线，无法回放。")
        return 1
    ns = bars["time"].astype("datetime64[ns, UTC]").astype("int64").to_numpy()

    p("")
    p(f"  1m K 线：{len(bars)} 根，{bars['time'].iloc[0]} .. {bars['time'].iloc[-1]}")
    p(f"  成本 = {COST}（价格单位/笔）  最长持有 = {MAX_HOLD_MIN} 分钟")

    rows = load_entries()
    p(f"  历史首仓（逐笔）：{len(rows)} 笔")

    # ---- 逐笔回放 ----
    recs: list[dict] = []
    n_skip_ts = n_unfilled = 0
    for r in rows:
        i0 = int(np.searchsorted(ns, int(pd.Timestamp(r["ts"], unit="s", tz="UTC").value),
                                 side="left"))
        if i0 >= len(bars) - 5:
            n_skip_ts += 1
            continue
        if r["kind"] in ("place_pending", "place_grid"):
            i_fill = first_touch(bars, i0, r["entry"], r["is_long"])
            if i_fill is None:              # 挂单始终没成交 → 无持仓，剔除
                n_unfilled += 1
                continue
        else:
            i_fill = i0
        o, g, mins = replay(bars, i_fill, r["entry"], r["tp"], r["sl"], r["is_long"])
        recs.append(dict(r, i0=i_fill, outcome=o, gross=g, mins=mins,
                         R=(g - COST) / r["sl_dist"]))

    p(f"  可回放样本：{len(recs)} 笔"
      f"（越界剔除 {n_skip_ts} 笔，挂单未成交剔除 {n_unfilled} 笔）")
    if not recs:
        p("\n无样本，不可结论。")
        return 0

    # ---- 基线 ----
    base_lst = [(x["outcome"], x["gross"], x["sl_dist"]) for x in recs]
    base = summarize(base_lst)
    p("")
    p("=" * 100)
    p("A. 基线（全部首仓，不加赔率闸）")
    p("=" * 100)
    p("")
    p(f"  样本 {base['n']} 笔   胜率 {base['wr']:.1%}   "
      f"止盈 {base['wins']} / 止损 {base['loss']} / 超时 {base['tout']}")
    p(f"  净R {base['mR']:+.3f}（tR={base['tR']:+.2f}）   "
      f"净价 {base['mn']:+.3f}（t={base['tn']:+.2f}）")
    rrs = np.array([x["rr"] for x in recs])
    p(f"  RR 分布：中位 {np.quantile(rrs, 0.5):.2f}   "
      f"p10 {np.quantile(rrs, 0.1):.2f}   p90 {np.quantile(rrs, 0.9):.2f}   "
      f"最小 {rrs.min():.2f}   最大 {rrs.max():.2f}")

    # ---- B. RR 分桶 ----
    p("")
    p("=" * 100)
    p("B. 按 RR 分桶（看净 R 是否随赔率单调改善——这是硬闸成立的前提）")
    p("=" * 100)
    p("")
    p(f"  {'RR 桶':<12}{'笔数':>6}{'胜率':>8}{'净R':>9}{'tR':>7}"
      f"{'净价':>9}{'止损':>6}{'超时':>6}")
    p("  " + "-" * 84)
    for lo, hi in BUCKETS:
        sel = [x for x in recs if lo <= x["rr"] < hi]
        if not sel:
            continue
        s = summarize([(x["outcome"], x["gross"], x["sl_dist"]) for x in sel])
        lab = f"[{lo:.1f},{hi:.1f})" if hi < 1e8 else f"[{lo:.1f},∞)"
        p(f"  {lab:<12}{s['n']:>6}{s['wr']:>7.1%}{s['mR']:>+9.3f}"
          f"{s['tR']:>+7.2f}{s['mn']:>+9.3f}{s['loss']:>6}{s['tout']:>6}")

    # ---- C. 阈值扫描 ----
    p("")
    p("=" * 100)
    p("C. 阈值扫描：剔除 RR<X 后的净 R（Δ 相对基线）")
    p("=" * 100)
    p("")
    p(f"  {'阈值 X':<10}{'保留':>6}{'剔除':>6}{'保留胜率':>10}{'保留净R':>10}"
      f"{'tR':>7}{'Δ净R':>9}{'剔除净R':>10}{'剔除tR':>8}")
    p("  " + "-" * 92)
    p(f"  {'基线(0)':<10}{base['n']:>6}{0:>6}{base['wr']:>9.1%}"
      f"{base['mR']:>+10.3f}{base['tR']:>+7.2f}{0.0:>+9.3f}{float('nan'):>+10.3f}"
      f"{float('nan'):>+8.2f}")
    for x in CANDIDATES:
        keep = [r for r in recs if r["rr"] >= x]
        drop = [r for r in recs if r["rr"] < x]
        if not keep:
            p(f"  {x:<10}（全部被剔除，无样本）")
            continue
        sk = summarize([(r["outcome"], r["gross"], r["sl_dist"]) for r in keep])
        sd = summarize([(r["outcome"], r["gross"], r["sl_dist"]) for r in drop]) \
            if drop else {}
        dmr = sd.get("mR", float("nan"))
        dtR = sd.get("tR", float("nan"))
        p(f"  {x:<10}{sk['n']:>6}{len(drop):>6}{sk['wr']:>9.1%}"
          f"{sk['mR']:>+10.3f}{sk['tR']:>+7.2f}{sk['mR'] - base['mR']:>+9.3f}"
          f"{dmr:>+10.3f}{dtR:>+8.2f}")

    # ---- D. 分来源 ----
    p("")
    p("=" * 100)
    p("D. 按 sl_source 分组的 RR 与净 R（看低赔率出自哪条路径）")
    p("=" * 100)
    p("")
    p(f"  {'sl_source':<26}{'笔数':>6}{'RR中位':>9}{'RR最小':>9}{'净R':>9}{'tR':>7}")
    p("  " + "-" * 76)
    groups: dict[str, list[dict]] = {}
    for x in recs:
        groups.setdefault(x["sl_source"], []).append(x)
    for name, sel in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        s = summarize([(x["outcome"], x["gross"], x["sl_dist"]) for x in sel])
        rr = np.array([x["rr"] for x in sel])
        p(f"  {name:<26}{s['n']:>6}{np.quantile(rr, 0.5):>9.2f}"
          f"{rr.min():>9.2f}{s['mR']:>+9.3f}{s['tR']:>+7.2f}")

    # ---- E. 关键桶时间分布（判断差桶是「赔率效应」还是「时段/版本效应」）----
    p("")
    p("=" * 100)
    p("E. [1.3,1.4) 差桶的时间分布（若是短窗口聚集 → 版本/行情效应，非纯赔率效应）")
    p("=" * 100)
    p("")
    for lab, sel in (("[1.2,1.4)", [x for x in recs if 1.2 <= x["rr"] < 1.4]),
                     ("[1.4,1.8)", [x for x in recs if 1.4 <= x["rr"] < 1.8]),
                     ("[1.8,∞)", [x for x in recs if x["rr"] >= 1.8])):
        if not sel:
            continue
        tss = pd.to_datetime([x["ts"] for x in sel], unit="s", utc=True)
        months = tss.strftime("%Y-%m").value_counts().sort_index()
        spread = (tss.max() - tss.min()).days
        p(f"  {lab:<10} {len(sel):>3} 笔  跨 {spread:>3} 天  "
          f"{tss.min():%Y-%m-%d} .. {tss.max():%Y-%m-%d}")
        p("            月度分布：" +
          "  ".join(f"{m}:{c}" for m, c in months.items()))
    p("  → 若差桶集中在少数月份，说明「亏损」更多来自那段行情/版本，"
      "对赔率的归因要打折。")

    # ---- 判读 ----
    p("")
    p("=" * 100)
    p("F. 判读")
    p("=" * 100)
    p("")
    if base["n"] < 100:
        p(f"  [警示] 样本 {base['n']} < 100，结论仅供参考，不足以单独支撑参数定案。")
    # 低赔率（<1.4）是否系统性亏损
    for thr in (1.2, 1.4, 1.8):
        low = [r for r in recs if r["rr"] < thr]
        if not low:
            p(f"  · RR<{thr}：样本中无此首仓。")
            continue
        sl = summarize([(r["outcome"], r["gross"], r["sl_dist"]) for r in low])
        verdict = "系统性亏损" if sl["mR"] < 0 else "未见系统性亏损"
        sig = "显著" if (np.isfinite(sl["tR"]) and abs(sl["tR"]) >= 2) else "不显著"
        p(f"  · RR<{thr} 共 {sl['n']} 笔：净R {sl['mR']:+.3f}"
          f"（tR={sl['tR']:+.2f}）→ {verdict}（{sig}）")
    p("  · 口径：净R>0 且 |tR|>=2 才算「有统计意义」；tR<2 只作方向参考，"
      "仍需记录 N 并后续跟踪。")
    p("  · 若「剔除低赔率」使保留组净R 上升、且被剔除组净R 明显为负，"
      "则该阈值可用；否则应退回更保守阈值或不做硬闸。")

    out = ROOT / "research" / "30_first_entry_rr_floor_out.txt"
    try:
        out.write_text("\n".join(OUT), encoding="utf-8")
        p(f"\n已保存：{out.relative_to(ROOT)}")
    except Exception as e:
        p(f"\n（保存失败：{e}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
