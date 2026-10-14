# -*- coding: utf-8 -*-
"""研究取证 32：首仓「取位方案」回放——哪种取位能让赔率回到合理区且不亏。

背景（2026-10-13）
------------------
用户观察「1 小时突破，短期却开不了仓」。核查结论（research/31）：
今日 21/21 首仓提案被 `rr_below_0.8` 赔率硬闸拒掉、0 放行；病根是**取位尺度
不一致**——止盈取「最近反向结构位」再缩 70% 触 0.5×ATR 下限 -> 约 5.3 点；
止损锚「远端结构失效边界」-> 约 28 点；两者差 5.4 倍，赔率恒约 0.19。

本脚本要回答
------------
在**同一批真实信号**上，对比几种首仓取位方案，用净 R + 胜率 + 赔率分布定夺
哪种能让赔率回到合理区且不亏（定案后再决定是否动 levels.py）：

  A  实际记录：历史放行单用 trades.jsonl 实际记的 tp/sl；今日用闸输出的 tp/sl。
  A′ 现状口径复算：用 15m 结构代理重建 levels.py 的首仓取位
     （止盈取「最近反向结构位」缩 0.70、触 0.5×ATR 下限；止损锚结构失效边界）。
     用来验证代理是否忠实（今日 A′ 应≈A），并看历史若走新口径会怎样。
     —— 以下 B′/C′/D′ **都在 A′ 的基线上只动一处**，隔离变量：
  B′ 只扩止盈到「过闸」：止损不动，止盈外扩到最近的、满足 0.8×止损 的结构位
     （不足则外推到该距离）。
  C′ 只扩止盈到「满赔率」：同上，门槛换成 min_rr=1.8。
  D′ 收止损（尺度对齐）：止盈不动，止损收成 止盈/1.8（回退旧口径 rr_from_tp）。

样本与口径
----------
· 对照样本（大样本、前向 K 线完整）：trades.jsonl 历史**真正放行**的首仓。
· 主样本（触发对象）：今日被 0.8 闸拒的 21 笔（定价取自 risk_reject.levels_notes
  里 gate 的真实输出 tp_dist/sl_dist）。
· 结构代理：15m 自研摆动检测（find_swings/alternate_swings），与线上 levels.py
  的完整输入（缠论中枢/SMC OB/经典支撑阻力）**不完全等价**，量级可信。
· 回放：1m K 线，**同一根内先触止损**（保守）；净R = (价格变动-成本)/止损距离。

⚠️ 诚实声明
------------
· 今日样本的**前向 K 线很短**（数据只到 2026-10-13 03:36 UTC）→ 多数结局是
  「超时按最后收盘 mark」，只能看方向与量级，不能单独定案。
· 历史放行单的 A 是**旧定价口径**（sl_source 各异），与今日新口径不完全同源。
· A′/B′/C′ 依赖结构代理，与线上真实取位有偏差；结论看「量级与方向」。
· 这是**同一批真实信号**下的反事实 A/A′/B′/C′/D′，不是择时研究；不改任何 src。

跑法::

    & $py research/32_first_entry_positioning.py
"""
from __future__ import annotations

import io
import json
import math
import re
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

# levels.py 写入 levels_notes 的两条关键文案（提取 gate 真实输出）
RE_TP_LAST = re.compile(r"结构距离\s*([\d.]+)\s*->\s*([\d.]+)")
RE_SL = re.compile(r"止损距离\s*([\d.]+)")


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
# 样本：历史放行首仓 + 今日被拒首仓
# ══════════════════════════════════════════════════════════════════
def load_released(symbol: str = "XAUUSDm") -> list[dict]:
    """trades.jsonl 历史**真正放行**的首仓（市价 + 挂单；不含网格加仓层）。

    ⚠️ 日志覆盖多品种时代，须按 symbol 剔除非黄金残留；再加价格带兜底。
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
        e, tp, sl, ts = r.get("entry_ref"), r.get("tp"), r.get("sl"), r.get("ts")
        if d not in ("LONG", "SHORT") or None in (e, tp, sl, ts):
            continue
        try:
            e, tp, sl, ts = float(e), float(tp), float(sl), float(ts)
        except (TypeError, ValueError):
            continue
        if not all(500.0 <= v <= 8000.0 for v in (e, tp, sl)):
            continue
        is_long = d == "LONG"
        tp_d = (tp - e) if is_long else (e - tp)
        sl_d = (e - sl) if is_long else (sl - e)
        if tp_d <= 0 or sl_d <= 0:
            continue
        out.append(dict(ts=ts, entry=e, direction=d, is_long=is_long,
                        tp_dist=tp_d, sl_dist=sl_d, src="历史放行",
                        sl_source=r.get("sl_source") or "none"))
    return out


def _last_group(notes: list[str], rx: re.Pattern, gi: int) -> float | None:
    val = None
    for s in notes:
        for m in rx.finditer(s):
            try:
                val = float(m.group(gi))
            except (TypeError, ValueError):
                pass
    return val


def load_rejected(day: str = "20261013") -> list[dict]:
    """从 decision 日志重建「今日被赔率闸拒掉的首仓」（gate 真实定价输出）。"""
    pth = ROOT / "logs" / f"decision_{day}.jsonl"
    out: list[dict] = []
    if not pth.exists():
        return out
    pending: dict | None = None
    for line in pth.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        ev = r.get("event")
        if ev == "decision":
            pr = r.get("proposal") or {}
            if pr.get("kind") == "open_market" and pr.get("entry") is not None:
                pending = dict(ts=r.get("ts"), entry=float(pr["entry"]),
                               direction=pr.get("direction"),
                               score=r.get("score"))
            continue
        if ev != "risk_reject":
            continue
        if not str(r.get("reason") or "").startswith("rr_below"):
            continue
        notes = r.get("levels_notes") or []
        tp_d = _last_group(notes, RE_TP_LAST, 2)
        sl_d = _last_group(notes, RE_SL, 1)
        if pending is None or None in (tp_d, sl_d):
            pending = None
            continue
        if pending["direction"] not in ("LONG", "SHORT"):
            pending = None
            continue
        row = dict(pending)
        row.update(tp_dist=float(tp_d), sl_dist=float(sl_d), src="今日被拒",
                   is_long=pending["direction"] == "LONG")
        out.append(row)
        pending = None
    return out


# ══════════════════════════════════════════════════════════════════
# 结构（15m 自研摆动代理）
# ══════════════════════════════════════════════════════════════════
def structure_at(df15: pd.DataFrame, ts: float, is_long: bool
                 ) -> tuple[float | None, list[float], list[float]]:
    """返回 (结构失效边界, 上方摆动高列表升序, 下方摆动低列表升序)。"""
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
    for lv in levels:
        if lv - entry >= need:
            return lv
    return None


def next_tp_below(levels: list[float], entry: float, need: float) -> float | None:
    for lv in reversed(levels):
        if entry - lv >= need:
            return lv
    return None


# ══════════════════════════════════════════════════════════════════
# 回放
# ══════════════════════════════════════════════════════════════════
def replay(bars: pd.DataFrame, i0: int, entry: float, tp: float, sl: float,
           is_long: bool) -> tuple[str, float]:
    """从第 i0 根起逐根回放。**同一根内先判止损**（保守）。"""
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
            return "止损", (sl - entry) if is_long else (entry - sl)
        if hit_tp:
            return "止盈", (tp - entry) if is_long else (entry - tp)
    last = cl[end - 1]
    return "超时", (last - entry) if is_long else (entry - last)


def tstat(xs: list[float]) -> float:
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
    """lst: [(结局, 价格变动, 止损距离), ...] → 净R 等。"""
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
                wr=wins / len(lst), mg=mg, mn=mg - COST, mR=mr, tR=tstat(rs))


# ══════════════════════════════════════════════════════════════════
# 各取位方案 → (止盈距离, 止损距离)
# ══════════════════════════════════════════════════════════════════
def cur_rule_dists(e: float, is_long: bool, atr: float, bnd: float | None,
                   highs: list[float], lows: list[float], shrink: float,
                   min_atr: float, buf_atr: float, min_rr: float
                   ) -> tuple[float | None, float | None]:
    """A′：复算 levels.py 首仓口径（止盈取最近反向结构位缩 0.70 + 0.5ATR 下限；
    止损锚结构失效边界 + 缓冲，无边界则 tp/min_rr 回退）。"""
    if is_long:
        cand = [h for h in highs if h > e]
        raw = (min(cand) - e) if cand else None
    else:
        cand = [l for l in lows if l < e]
        raw = (e - max(cand)) if cand else None
    if raw is None or raw <= 0:
        return None, None
    floor = min_atr * atr
    tp_d = raw * shrink
    if tp_d < floor:
        tp_d = floor
    if bnd is not None and ((is_long and bnd < e) or ((not is_long) and bnd > e)):
        sl_d = max(abs(e - bnd) + buf_atr * atr, floor, 1e-9)
    else:
        sl_d = tp_d / min_rr
    return tp_d, sl_d


def expand_tp(e: float, is_long: bool, need: float,
              highs: list[float], lows: list[float]) -> float:
    """把止盈外扩到 >= need：优先最近的、满足条件的结构位，否则按 need 外推。"""
    lvl = next_tp_above(highs, e, need) if is_long else next_tp_below(lows, e, need)
    return abs(lvl - e) if lvl is not None else need


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════
def main() -> int:
    shrink, min_atr, buf_atr = 0.70, 0.5, 0.5
    min_rr, gate_rr = 1.8, 0.8
    try:
        from gold_agent.common.config import CFG
        shrink = float(CFG.risk.first_tp_shrink)
        min_atr = float(CFG.risk.structure_sl_min_atr)
        buf_atr = float(CFG.risk.structure_sl_buffer_atr)
        min_rr = float(CFG.risk.min_rr)
        # ⚠️ 2026-10-14：`first_entry_min_rr`（首仓专用赔率下限）已随
        #    「盈亏比下限全局唯一（min_rr）」的重新设计**删除**。
        #    本脚本是当时的取证脚本（结论已归档在 trials.csv 与 config.toml 的历史注释里），
        #    取值退化为 `min_rr`，以免脚本因配置键消失而直接崩掉。
        gate_rr = float(getattr(CFG.risk, "first_entry_min_rr", CFG.risk.min_rr))
    except Exception:
        pass

    p("=" * 104)
    p("研究取证 32 · 首仓「取位方案」回放：哪种取位能让赔率回到合理区且不亏")
    p("=" * 104)
    p(f"  参数：first_tp_shrink={shrink}  structure_sl_min_atr={min_atr}  "
      f"structure_sl_buffer_atr={buf_atr}  min_rr={min_rr}  first_entry_rr_gate={gate_rr}")
    p(f"  成本={COST}（价格单位/笔）  最长持有={MAX_HOLD_MIN} 分钟  "
      f"摆动确认 k={SWING_K}（15m）")

    bars = load_bars()
    if bars is None or bars.empty:
        p("!! 拿不到 1m K 线，无法回放。")
        return 1
    df15 = resample_tf(bars, "15min")
    atr1h = atr_1h_aligned(bars, mult=1.0)
    ns = bars["time"].astype("datetime64[ns, UTC]").astype("int64").to_numpy()
    p("")
    p(f"  1m K 线：{len(bars)} 根，{bars['time'].iloc[0]} .. {bars['time'].iloc[-1]}")
    p(f"  15m K 线：{len(df15)} 根")

    hist = load_released()
    rej = load_rejected("20261013")
    p(f"  历史放行首仓：{len(hist)} 笔    今日被拒首仓（有定价）：{len(rej)} 笔")

    # ---- 逐信号预计算：结构 / ATR / 各方案距离 ----
    VARIANTS = ["A 实际", "A′ 现状口径", "B′ 扩止盈过闸",
                "C′ 扩止盈满赔率", "D′ 收止损"]
    res: dict[str, dict[str, list]] = {
        src: {v: [] for v in VARIANTS} for src in ("历史放行", "今日被拒")}
    n_skip = {"历史放行": 0, "今日被拒": 0}
    n_nostruct = 0

    for src, rows in (("历史放行", hist), ("今日被拒", rej)):
        for r in rows:
            e, is_long, ts = r["entry"], r["is_long"], r["ts"]
            i0 = int(np.searchsorted(
                ns, int(pd.Timestamp(ts, unit="s", tz="UTC").value), side="left"))
            if i0 >= len(bars) - 5:
                n_skip[src] += 1
                continue
            atr = float(atr1h[i0])
            if not np.isfinite(atr) or atr <= 0:
                n_skip[src] += 1
                continue
            bnd, highs, lows = structure_at(df15, ts, is_long)
            if not highs and not lows:
                n_nostruct += 1

            tp_a, sl_a = float(r["tp_dist"]), float(r["sl_dist"])

            def _replay(tp_d: float | None, sl_d: float | None):
                if tp_d is None or sl_d is None or tp_d <= 0 or sl_d <= 0:
                    return None
                tp = e + tp_d if is_long else e - tp_d
                sl = e - sl_d if is_long else e + sl_d
                o, g = replay(bars, i0, e, tp, sl, is_long)
                return (o, g, sl_d, tp_d)

            cand = {}
            cand["A 实际"] = _replay(tp_a, sl_a)
            tp_p, sl_p = cur_rule_dists(e, is_long, atr, bnd, highs, lows,
                                        shrink, min_atr, buf_atr, min_rr)
            cand["A′ 现状口径"] = _replay(tp_p, sl_p)
            # B′/C′/D′ 都以 A′ 为基线，只动一处（孤立变量）；A′ 不可用则整体跳过
            if tp_p is not None and sl_p is not None and sl_p > 0:
                cand["B′ 扩止盈过闸"] = _replay(
                    expand_tp(e, is_long, gate_rr * sl_p, highs, lows), sl_p)
                cand["C′ 扩止盈满赔率"] = _replay(
                    expand_tp(e, is_long, min_rr * sl_p, highs, lows), sl_p)
                cand["D′ 收止损"] = _replay(tp_p, tp_p / min_rr)
            else:
                cand["B′ 扩止盈过闸"] = None
                cand["C′ 扩止盈满赔率"] = None
                cand["D′ 收止损"] = None

            for v in VARIANTS:
                if cand[v] is not None:
                    res[src][v].append(cand[v])

    def _row(v: str, lst: list) -> None:
        s = summarize([(o, g, d) for o, g, d, _ in lst])
        if not s:
            p(f"  {v:<16}  -- 无可回放样本")
            return
        rr = np.array([t / d for _, _, d, t in lst if d > 0])
        be = np.array([d / (t + d) for _, _, d, t in lst if (t + d) > 0])
        slm = float(np.median([d for _, _, d, _ in lst]))
        p(f"  {v:<16}{s['n']:>5}{s['wins']:>6}{s['loss']:>6}{s['tout']:>6}"
          f"{s['wr']:>8.1%}{np.quantile(rr, 0.5):>9.2f}{slm:>9.1f}"
          f"{np.quantile(be, 0.5):>11.1%}{s['mR']:>+9.3f}{s['tR']:>+7.2f}")

    def _block(src: str) -> None:
        p("")
        p("=" * 104)
        p(f"{src} · 各取位方案回放对比（同一批信号；净R=(价格变动-成本)/止损距离）")
        p("=" * 104)
        if n_skip[src]:
            p(f"  （越界/无 ATR 剔除 {n_skip[src]} 笔；无结构代理 {n_nostruct} 笔）")
        p("")
        p(f"  {'方案':<16}{'N':>5}{'止盈':>6}{'止损':>6}{'超时':>6}"
          f"{'胜率':>8}{'RR中位':>9}{'止损距中位':>11}{'保本胜率':>12}{'净R':>9}{'tR':>7}")
        p("  " + "-" * 100)
        for v in VARIANTS:
            _row(v, res[src][v])

    _block("历史放行")
    _block("今日被拒")

    # ---- RR 硬闸阈值扫描 ----
    p("")
    p("=" * 104)
    p("RR 硬闸阈值扫描（逐档过滤「赔率 >= 阈值」的单子，看闸放松/收紧的影响）")
    p("=" * 104)
    p("  赔率 RR = 止盈距 / 止损距。「保留占比」相对该方案全部可回放样本。")
    p("  A′ 现状口径的 RR 典型值最低——若它在低阈值下净R 明显更好，说明闸与口径冲突。")
    p("")
    thresholds = [0.0, 0.3, 0.5, 0.7, 0.8, 1.0, 1.5]
    for src in ("历史放行", "今日被拒"):
        for v in ("A 实际", "A′ 现状口径"):
            lst = res[src][v]
            if not lst:
                continue
            p(f"  · {src} / {v}（全样本 N={len(lst)}）")
            p(f"    {'阈值':>6}{'保留N':>8}{'保留占比':>10}"
              f"{'胜率':>9}{'净R':>10}{'tR':>8}")
            for thr in thresholds:
                kept = [x for x in lst if x[2] > 0 and (x[3] / x[2]) >= thr - 1e-9]
                s = summarize([(o, g, d) for o, g, d, _ in kept])
                if not s:
                    p(f"    {thr:>6.2f}{0:>8}{0.0:>10.1%}{'--':>9}{'--':>10}{'--':>8}")
                    continue
                p(f"    {thr:>6.2f}{s['n']:>8}{s['n']/len(lst):>10.1%}"
                  f"{s['wr']:>9.1%}{s['mR']:>+10.3f}{s['tR']:>+8.2f}")
            p("")

    # ---- 判读 ----
    p("")
    p("=" * 104)
    p("判读")
    p("=" * 104)
    p("")
    # A′ 代理忠实度
    hh = res["历史放行"]["A′ 现状口径"]
    hd = res["历史放行"]["A 实际"]
    if hh and hd:
        ra = np.median([t / d for _, _, d, t in hd])
        rp = np.median([t / d for _, _, d, t in hh])
        p(f"  · 代理忠实度（历史放行）：实际 RR 中位 {ra:.2f} vs A′ 复算 RR 中位 "
          f"{rp:.2f} —— 差距越小，说明 15m 摆动代理越贴近线上取位。")
    p("  · 判读口径：净R>0 且 |tR|>=2 才算「有统计意义」；tR<2 只作方向参考。")
    p("  · B′/C′ 保住 A′ 的止损、只把止盈外扩到「过闸 / 满赔率」；"
      "D′ 保住 A′ 的止盈、只把止损收到 止盈/1.8。")
    p("  · B′/C′/D′ 都以 A′ 为基线只动一处（孤立变量）；谁能在净R>0 的前提下"
      "把 RR 抬到阈值以上，谁才值得改 levels.py。")
    p("  · 若三者净R 都不如 A′，则说明「强推 RR 上升」本身在亏，病根不在取位而在"
      "闸阈值与口径的匹配——此时应调 first_entry_min_rr，而非改 levels.py 定价。")
    p("  · 今日样本前向 K 线很短（数据止于 2026-10-13 03:36 UTC），超时占比高，"
      "只作「触发对象」结构证据，不以它定案。")

    out = ROOT / "research" / "32_first_entry_positioning_out.txt"
    try:
        out.write_text("\n".join(OUT), encoding="utf-8")
        p(f"\n已保存：{out.relative_to(ROOT)}")
    except Exception as ex:
        p(f"\n（保存失败：{ex}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
