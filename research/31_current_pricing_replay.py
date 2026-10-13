# -*- coding: utf-8 -*-
"""研究取证 31：**走当前定价口径**的首仓回放——「被 0.8 闸拒的单若开出来会怎样」。

为什么要有这个脚本
------------------
research/28/29/30 的回放**都没有走** `levels.py` 的当前定价逻辑，也没有走
`first_entry_min_rr=0.8` 这道闸：
  · 样本来自 `trades.jsonl` 里**历史上真正开出来的**首仓 → 天然排除了
    「会被闸拒」的单（选择偏差）；
  · research/29 方案 B/C 自算止损/止盈，但用的是 15m 摆动的**代理**，
    且明确排除 43 笔「无结构边界」样本；
  · research/30 索性把 RR 当作「交易自身属性」，**不重建**定价。
所以它们**不能**回答用户 2026-10-13 的质疑：
  > 回放数据有走价位/赔率计算逻辑吗？会不会里面有的开不了仓？

本脚本换口径：**直接读线上真实定价的输出**（`risk_reject.levels_notes` 里就写着
gate 算出来的止盈距离与止损距离），逐笔用 1m K 线回放，看：
  A. 今日（2026-10-13）被 0.8 闸拒的这批单，「若开出来」净 R 是多少；
  B. 历史上真正放行开出的首仓，净 R 是多少（对照）；
  C. 这批被拒单的**赔率结构**（止盈距离 vs 止损距离）说明了什么。

数据来源与口径
--------------
· 被拒单：`logs/decision_YYYYMMDD.jsonl`
    - `event=="decision"` 且 `proposal.kind=="open_market"` → 取 方向/入场价/时间；
    - 紧随其后的 `event=="risk_reject"` 且 `reason` 以 `rr_below` 开头 → 解析
      `levels_notes` 文本，取出 gate 真实算出的 `止盈距离` 与 `止损距离`。
      （这两条 note 由 levels.py 写入，就是 trade_levels 的最终输出。）
· 放行单：`logs/trades.jsonl` 的 `risk_decision`（首仓，含网格挂单层）——
  这些是**历史真实开仓**，字段齐全（entry_ref/tp/sl/sl_source）。
· 回放：1m K 线（优先 MT5 实时，退回本地缓存）；**同一根内先触止损再判止盈**
  （保守，不给乐观偏差）；挂单层需价格先触及挂单价才算成交。
· 净 R（风控口径）= (价格变动 − 成本) / 止损距离；成本取 XAUUSDm 往返点差。

⚠️ 诚实声明
------------
· 被拒单样本**只有今日一批**（此前 0.8 闸从未拒过任何单）→ N 很小、且集中在
  同一天同一段行情，**不足以单独下结论**，只能作为「量级/结构」的证据。
· 入场价用决策时的现价（`entry_ref` / proposal.entry），非真实成交价。
· 这是**同一批真实信号**下「开/不开」的反事实，不是择时研究。
· 触发本脚本的动机：2026-10-13 用户观察「1 小时突破，短期却开不了仓」。

跑法::

    & $py research/31_current_pricing_replay.py
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

OUT: list[str] = []
COST = 0.240            # XAUUSDm 实测往返点差（价格单位）
MAX_HOLD_MIN = 14400    # 最长持有（1m 根数）= 10 天

# levels.py 写入 levels_notes 的两条关键文案（提取 gate 真实输出）
#   1) "止盈按用户要求缩 30%（系数 0.7）：结构距离 1.992 -> 5.256"  -> 末值 = 止盈距离
#   2) "... 下限 0.5×ATR 5.256 = 止损距离 24.699" / "= 止损距离 21.5）" -> 止损距离
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


# ══════════════════════════════════════════════════════════════════
# A 段：今日被 0.8 闸拒的首仓（真实定价输出 + 重建入场）
# ══════════════════════════════════════════════════════════════════
def load_rejected(day: str = "20261013") -> list[dict]:
    """从 decision 日志重建「被赔率闸拒掉的首仓」。

    配对规则：按文件顺序推进，记住**最近一条** `open_market` 决策（方向/入场/时间），
    遇到其后的 `risk_reject`（reason 以 rr_below 开头）即配对并消费掉。
    gate 里 `entry = prop.entry`，与决策日志 `proposal.entry` 同值（已用
    levels_notes 里的「距入场」交叉核对过）。
    """
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
                pending = dict(ts=r.get("ts"), direction=pr.get("direction"),
                               entry=pr.get("entry"), score=r.get("score"),
                               reasons=pr.get("reasons"))
            continue
        if ev != "risk_reject":
            continue
        reason = str(r.get("reason") or "")
        if not reason.startswith("rr_below"):
            continue
        notes = r.get("levels_notes") or []
        if pending is None:
            out.append(dict(ts=r.get("ts"), direction=None, entry=None,
                            tp_dist=None, sl_dist=None, reason=reason,
                            notes=notes, paired=False))
            continue
        tp_dist = _last_group(notes, RE_TP_LAST, 2)
        sl_dist = _last_group(notes, RE_SL, 1)
        row = dict(pending)
        row.update(tp_dist=tp_dist, sl_dist=sl_dist, reason=reason,
                   notes=notes, paired=True)
        out.append(row)
        pending = None
    return out


def _last_group(notes: list[str], rx: re.Pattern, gi: int) -> float | None:
    """在 notes 里找**最后一处**匹配并取第 gi 组（gate 的最终输出在末条）。"""
    val = None
    for s in notes:
        for m in rx.finditer(s):
            try:
                val = float(m.group(gi))
            except (TypeError, ValueError):
                pass
    return val


# ══════════════════════════════════════════════════════════════════
# B 段：历史已放行的首仓（对照）
# ══════════════════════════════════════════════════════════════════
def load_released(symbol: str = "XAUUSDm") -> list[dict]:
    """从 trades.jsonl 取历史**已开仓**首仓（市价首仓 + 网格挂单层）。"""
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
        d, ts = r.get("direction"), r.get("ts")
        if d not in ("LONG", "SHORT") or ts is None:
            continue
        if kind == "place_grid":
            for lay in (r.get("layers") or []):
                row = _mk(d, lay.get("level"), lay.get("tp"), lay.get("sl"),
                          ts, "place_grid", "grid")
                if row:
                    out.append(row)
            continue
        row = _mk(d, r.get("entry_ref"), r.get("tp"), r.get("sl"),
                  ts, kind, r.get("sl_source"))
        if row:
            out.append(row)
    return out


def _mk(d, e, tp, sl, ts, kind, sl_source) -> dict | None:
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
    if sl_dist <= 0 or tp_dist <= 0:
        return None
    return dict(direction=d, entry=e, tp=tp, sl=sl, ts=float(ts), kind=kind,
                sl_source=sl_source or "none", is_long=is_long,
                tp_dist=tp_dist, sl_dist=sl_dist, rr=tp_dist / sl_dist)


# ══════════════════════════════════════════════════════════════════
# 回放
# ══════════════════════════════════════════════════════════════════
def replay(bars: pd.DataFrame, i0: int, entry: float, tp: float, sl: float,
           is_long: bool) -> tuple[str, float, int]:
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
            return "止损", (sl - entry) if is_long else (entry - sl), j - i0
        if hit_tp:
            return "止盈", (tp - entry) if is_long else (entry - tp), j - i0
    last = cl[end - 1]
    return "超时", (last - entry) if is_long else (entry - last), end - 1 - i0


def first_touch(bars: pd.DataFrame, i0: int, entry: float,
                is_long: bool) -> int | None:
    """挂单成交判定：价格先触及挂单价才算成交。"""
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
    """lst: [(结局, 价格变动, 止损距离), ...] → 净 R 等。"""
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
                mR=mr, tR=tstat(rs))


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════
def main() -> int:
    p("=" * 100)
    p("研究取证 31 · 走当前定价口径的首仓回放：「被 0.8 闸拒的单若开出来会怎样」")
    p("=" * 100)

    bars = load_bars()
    if bars is None or bars.empty:
        p("!! 拿不到 1m K 线，无法回放。")
        return 1
    ns = bars["time"].astype("datetime64[ns, UTC]").astype("int64").to_numpy()
    p("")
    p(f"  1m K 线：{len(bars)} 根，{bars['time'].iloc[0]} .. {bars['time'].iloc[-1]}")
    p(f"  成本 = {COST}（价格单位/笔）  最长持有 = {MAX_HOLD_MIN} 分钟")

    # ---------------- A. 被拒单 ----------------
    rej = load_rejected("20261013")
    p("")
    p("=" * 100)
    p("A. 今日被「首仓赔率闸」拒掉的单（定价输出取自 risk_reject.levels_notes）")
    p("=" * 100)
    if not rej:
        p("  今日没有被 rr_below_* 拒掉的首仓。")
    else:
        p(f"  共 {len(rej)} 笔；其中可重建入场/定价 {sum(1 for x in rej if x.get('paired'))} 笔")
        p("")
        p(f"  {'#':>3} {'时间':<16}{'方向':<6}{'入场':>10}{'止盈距离':>10}"
          f"{'止损距离':>10}{'赔率':>8}{'保本胜率':>9}{'结局':>6}{'净R':>8}")
        p("  " + "-" * 92)
        recs: list[dict] = []
        n_skip = 0
        for k, x in enumerate(rej, 1):
            tp_d, sl_d = x.get("tp_dist"), x.get("sl_dist")
            e, d = x.get("entry"), x.get("direction")
            if None in (tp_d, sl_d, e) or d not in ("LONG", "SHORT"):
                n_skip += 1
                continue
            is_long = d == "LONG"
            tp = e + tp_d if is_long else e - tp_d
            sl = e - sl_d if is_long else e + sl_d
            i0 = int(np.searchsorted(ns, int(pd.Timestamp(x["ts"], unit="s", tz="UTC").value),
                                     side="left"))
            if i0 >= len(bars) - 5:
                n_skip += 1
                continue
            o, g, mins = replay(bars, i0, e, tp, sl, is_long)
            R = (g - COST) / sl_d
            recs.append(dict(x, outcome=o, gross=g, R=R, is_long=is_long,
                             tp=tp, sl=sl, rr=tp_d / sl_d))
            tstr = f"{pd.Timestamp(x['ts'], unit='s', tz='UTC'):%m-%d %H:%M}"
            be = sl_d / (tp_d + sl_d)          # 保本胜率
            p(f"  {k:>3} {tstr:<16}{d:<6}{e:>10.3f}{tp_d:>10.3f}"
              f"{sl_d:>10.3f}{tp_d / sl_d:>8.3f}{be:>8.1%}{o:>6}{R:>+8.3f}")
        if n_skip:
            p(f"  （另有 {n_skip} 笔：入场/定价缺失或超出 K 线范围，未回放）")

        if recs:
            s = summarize([(r["outcome"], r["gross"], r["sl_dist"]) for r in recs])
            rrs = np.array([r["rr"] for r in recs])
            tpd = np.array([r["tp_dist"] for r in recs])
            sld = np.array([r["sl_dist"] for r in recs])
            p("")
            p(f"  若这批单全部照价开出来：{s['n']} 笔  胜率 {s['wr']:.1%}  "
              f"（止盈 {s['wins']} / 止损 {s['loss']} / 超时 {s['tout']}）")
            p(f"    净R {s['mR']:+.3f}（tR={s['tR']:+.2f}）   净价 {s['mn']:+.3f}")
            p(f"    赔率：中位 {np.quantile(rrs, 0.5):.3f}  "
              f"最小 {rrs.min():.3f}  最大 {rrs.max():.3f}")
            p(f"    止盈距离：中位 {np.quantile(tpd, 0.5):.3f}   "
              f"止损距离：中位 {np.quantile(sld, 0.5):.3f}   "
              f"（比值 {np.quantile(sld, 0.5) / max(np.quantile(tpd, 0.5), 1e-9):.2f}x）")

    # ---------------- B. 放行单（对照） ----------------
    rel = load_released()
    p("")
    p("=" * 100)
    p("B. 历史**真正放行**的首仓（对照：这批没被闸拒，因为当时定价口径不同）")
    p("=" * 100)
    p("")
    if not rel:
        p("  无历史放行首仓记录。")
    else:
        recs2: list[dict] = []
        n_unfilled = n_skip2 = 0
        for r in rel:
            i0 = int(np.searchsorted(ns, int(pd.Timestamp(r["ts"], unit="s", tz="UTC").value),
                                     side="left"))
            if i0 >= len(bars) - 5:
                n_skip2 += 1
                continue
            if r["kind"] in ("place_pending", "place_grid"):
                i_fill = first_touch(bars, i0, r["entry"], r["is_long"])
                if i_fill is None:
                    n_unfilled += 1
                    continue
            else:
                i_fill = i0
            o, g, mins = replay(bars, i_fill, r["entry"], r["tp"], r["sl"], r["is_long"])
            recs2.append(dict(r, outcome=o, gross=g))
        if recs2:
            s2 = summarize([(r["outcome"], r["gross"], r["sl_dist"]) for r in recs2])
            rrs2 = np.array([r["rr"] for r in recs2])
            p(f"  历史放行首仓 {len(recs2)} 笔可回放"
              f"（越界剔除 {n_skip2}，挂单未成交剔除 {n_unfilled}）")
            p(f"    胜率 {s2['wr']:.1%}  净R {s2['mR']:+.3f}（tR={s2['tR']:+.2f}）"
              f"   净价 {s2['mn']:+.3f}")
            p(f"    RR 中位 {np.quantile(rrs2, 0.5):.2f}   "
              f"<0.8 的占比 {(rrs2 < 0.8).mean():.1%}")

    # ---------------- C. 判读 ----------------
    p("")
    p("=" * 100)
    p("C. 判读")
    p("=" * 100)
    p("")
    if rej:
        paired = [x for x in rej if x.get("paired")]
        tps = [x["tp_dist"] for x in paired if x.get("tp_dist")]
        sls = [x["sl_dist"] for x in paired if x.get("sl_dist")]
        if tps and sls:
            mt, ms = np.median(tps), np.median(sls)
            p(f"  · 被拒单的定价结构：止盈距离中位 {mt:.2f}，止损距离中位 {ms:.2f}"
              f" → 赔率约 {mt / ms:.2f}。")
            p(f"    「止盈取最近反向结构位（再缩水/触 0.5×ATR 下限）」"
              f"与「止损锚远端结构失效边界」**尺度不一致**，")
            p(f"    是赔率被压到 0.8 以下的直接原因（需要 ≥"
              f"{ms / (mt + ms):.0%} 胜率才保本）。")
        p("  · 结论口径：被拒单样本仅今日一批、集中在同段行情，N 小，"
          "只能看「量级与结构」，不能单独定案。")
    p("  · 若被拒单「照价开出来」净R 明显为负 → 闸在正确地挡坏单（问题在取位，"
      "不在闸）；")
    p("  · 若净R 不差 → 说明闸误杀，应放宽阈值或修取位让 TP/SL 尺度一致。")

    out = ROOT / "research" / "31_current_pricing_replay_out.txt"
    try:
        out.write_text("\n".join(OUT), encoding="utf-8")
        p(f"\n已保存：{out.relative_to(ROOT)}")
    except Exception as e:
        p(f"\n（保存失败：{e}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
