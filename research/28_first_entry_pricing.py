# -*- coding: utf-8 -*-
"""研究取证 28：首仓定价改为「止盈 70% + 止损按盈亏比 1.8 反推」的历史回放。

用户 2026-10-09 指定：
> 我们每个品种首仓止盈点数为计算的70% 比如100买入 计算止盈110
> 那么实际止盈107 止损按照盈亏比1.8计算

即首仓改为 **止盈优先**：先把计算止盈缩到 70%，再由它反推止损
（`sl_dist = tp_dist / min_rr`）。这必然**同时**收紧止盈与止损，
两个方向的效应是相反的：

  · 止盈更近 → 更容易被打到（胜率升），但每笔赚得更少
  · 止损更近 → 更容易被打到（胜率降），但每笔亏得更少

净效果是正是负**不能靠推理**，必须回放。本脚本用实盘历史首仓单
（`logs/trades.jsonl` 的 `goldagent-open` / `goldagent-grid` /
`goldagent-pending`）在真实 1m K 线上做反事实回放。

方法（严格因果）
----------------
1. 取每笔历史首仓的**方向、入场价、原 TP**（= 旧语义下的结构目标，
   作为"计算止盈"的可用代理）。
2. 构造两套点位：
   · 旧：原 TP / 原 SL（历史真实下过的单）
   · 新：TP' = entry + 0.7×(TP-entry)，
         SL' = entry - (TP'-entry)/1.8（做空镜像）
3. 从**下单时刻之后**第一根 1m bar 起逐根走，先到哪个先算哪个
   （同一根内同时触及 → 保守判为止损，不给乐观偏差）。
4. 统计：止盈/止损/超时未决、毛期望、净期望（扣往返点差）。

⚠️ 诚实声明
------------
· 原 TP 是旧语义（"从支撑定止损，再找满足 RR 的止盈"）的产物，
  不等于用户口中的"计算止盈"，是**可得的最佳代理**；回放结论
  应理解为"把任何结构止盈缩到 70% 并相应收紧止损"的效应。
· 入场价用计划价（挂单）或成交价（市价单）；市价单的真实成交价
  已在 `order_done.result.price`，但本脚本为可复现只读计划价，
  故市价单有轻微滑点误差。
· 未决单按最后一根收盘价 mark-to-market，不当作 0。
· 这是**同一批信号**下的 A/B，不是择时研究。

跑法::

    & $py research/28_first_entry_pricing.py
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
OUT: list[str] = []
COST = 0.240           # XAUUSDm 实测往返点差（价格单位）
MAX_HOLD_MIN = 14400   # 挂单有效期上限（4h*4，与 grid expiration 一致）


def p(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


def load_bars(symbol: str = "XAUUSDm") -> pd.DataFrame | None:
    """1m K 线：优先 MT5 实时，退回本地缓存。"""
    df = None
    try:
        sys.path.insert(0, str(ROOT / "src"))
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
                d = d[[tcol, "close", "high", "low"]].rename(columns={tcol: "time"})
                d["time"] = pd.to_datetime(d["time"], utc=True, errors="coerce")
                df = d.dropna(subset=["time"])
    if df is None:
        return None
    need = {"open", "high", "low", "close"}
    if not need.issubset(df.columns):
        return None
    return df.sort_values("time").reset_index(drop=True)


def load_first_entries() -> list[dict]:
    """从 trades.jsonl 取历史首仓（市价首仓 + 挂单首仓）。"""
    pth = ROOT / "logs" / "trades.jsonl"
    rows = []
    if not pth.exists():
        return rows
    for line in pth.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("event") != "order_done":
            continue
        pl = r.get("plan") or {}
        if pl.get("kind") not in ("open_market", "place_pending"):
            continue
        cm = str(pl.get("comment") or "")
        # 首仓 = open / grid / pending；goldagent-add 是加仓，排除
        if "add" in cm:
            continue
        entry, tp, sl = pl.get("entry"), pl.get("tp"), pl.get("sl")
        d = pl.get("direction")
        if d not in ("LONG", "SHORT") or tp is None or sl is None:
            continue
        if entry is None:
            # 市价单：用成交价
            entry = (r.get("result") or {}).get("price")
        if not entry:
            continue
        try:
            entry, tp, sl = float(entry), float(tp), float(sl)
        except (TypeError, ValueError):
            continue
        rows.append({"direction": d, "entry": entry, "tp": tp, "sl": sl,
                     "ts": r.get("ts"), "comment": cm})
    return rows


def replay(bars: pd.DataFrame, entry: float, tp: float, sl: float,
           direction: str, ts: float) -> tuple[str, float, int]:
    """逐根回放。返回 (结局, 价格变动（按方向）, 用掉的分钟数)。

    保守规则：**同一根内同时触及止损与止盈 → 判止损**（不给乐观偏差）。
    """
    t = pd.Timestamp(ts, unit="s", tz="UTC")
    key = t.value
    ns = bars["time"].astype("datetime64[ns, UTC]").astype("int64").to_numpy()
    i = int(np.searchsorted(ns, key, side="left"))
    if i >= len(bars):
        return "无数据", 0.0, 0
    hi = bars["high"].to_numpy()
    lo = bars["low"].to_numpy()
    cl = bars["close"].to_numpy()
    end = min(len(bars), i + MAX_HOLD_MIN)
    is_long = direction == "LONG"
    for j in range(i, end):
        if is_long:
            hit_sl = lo[j] <= sl
            hit_tp = hi[j] >= tp
        else:
            hit_sl = hi[j] >= sl
            hit_tp = lo[j] <= tp
        if hit_sl and hit_tp:
            return "止损", (sl - entry) if is_long else (entry - sl), j - i
        if hit_sl:
            return "止损", (sl - entry) if is_long else (entry - sl), j - i
        if hit_tp:
            return "止盈", (tp - entry) if is_long else (entry - tp), j - i
    last = cl[end - 1]
    return ("超时", (last - entry) if is_long else (entry - last), end - 1 - i)


def tstat(xs: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    sd = math.sqrt(var)
    return float("nan") if sd <= 0 else m / (sd / math.sqrt(n))


def main() -> int:
    p("=" * 96)
    p("研究取证 28 · 首仓定价：止盈 70% + 止损按盈亏比 1.8 反推（历史回放）")
    p("=" * 96)

    min_rr = 1.8
    shrink = 0.7
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from gold_agent.common.config import CFG
        min_rr = float(CFG.risk.min_rr)
        shrink = float(CFG.risk.first_tp_shrink)
    except Exception:
        pass

    bars = load_bars()
    if bars is None:
        p("!! 拿不到带 high/low 的 1m K 线，无法回放。")
        return 1
    p("")
    p(f"  1m K 线：{len(bars)} 根，{bars['time'].iloc[0]} .. {bars['time'].iloc[-1]}")
    p(f"  当前参数：first_tp_shrink={shrink}  min_rr={min_rr}  成本={COST}")

    rows = load_first_entries()
    p(f"  历史首仓单：{len(rows)} 笔")
    if not rows:
        p("\n无样本，不可结论。")
        return 0

    res = {"旧（原 TP/SL）": [], "新（TP×0.7，SL 反推）": []}
    detail = []
    for r in rows:
        if not r["ts"]:
            continue
        e, tp0, sl0 = r["entry"], r["tp"], r["sl"]
        d = r["direction"]
        # 新点位：先把 TP 缩到 70%，再由它反推 SL
        tp_dist = abs(tp0 - e) * shrink
        tp1 = e + tp_dist if d == "LONG" else e - tp_dist
        sl_dist = tp_dist / min_rr
        sl1 = e - sl_dist if d == "LONG" else e + sl_dist
        o0, g0, t0 = replay(bars, e, tp0, sl0, d, r["ts"])
        o1, g1, t1 = replay(bars, e, tp1, sl1, d, r["ts"])
        if o0 == "无数据" or o1 == "无数据":
            continue
        res["旧（原 TP/SL）"].append((o0, g0))
        res["新（TP×0.7，SL 反推）"].append((o1, g1))
        detail.append((d, e, tp0, sl0, o0, g0, tp1, sl1, o1, g1))

    n = len(detail)
    p(f"  可回放样本：{n} 笔")
    p("")
    p("=" * 96)
    p("结果对比")
    p("=" * 96)
    p("")
    p(f"  {'方案':<24}{'止盈':>7}{'止损':>7}{'超时':>7}{'胜率':>8}"
      f"{'毛期望':>10}{'净期望':>10}{'t':>7}")
    p("  " + "-" * 88)
    summary = {}
    for name, lst in res.items():
        if not lst:
            continue
        wins = sum(1 for o, _ in lst if o == "止盈")
        loss = sum(1 for o, _ in lst if o == "止损")
        tout = sum(1 for o, _ in lst if o == "超时")
        gross = [g for _, g in lst]
        mg = sum(gross) / len(gross)
        mn = mg - COST
        t = tstat(gross)
        wr = wins / len(lst)
        summary[name] = dict(n=len(lst), wins=wins, loss=loss, tout=tout,
                             wr=wr, mg=mg, mn=mn, t=t)
        p(f"  {name:<24}{wins:>7}{loss:>7}{tout:>7}{wr:>7.1%}"
          f"{mg:>+10.3f}{mn:>+10.3f}{t:>+7.2f}")

    if len(summary) == 2:
        a = summary["旧（原 TP/SL）"]
        b = summary["新（TP×0.7，SL 反推）"]
        p("")
        p("=" * 96)
        p("判读")
        p("=" * 96)
        p("")
        p(f"  胜率     ：{a['wr']:.1%} -> {b['wr']:.1%}  （{(b['wr']-a['wr'])*100:+.1f}pp）")
        p(f"  净期望/笔：{a['mn']:+.3f} -> {b['mn']:+.3f}  （{b['mn']-a['mn']:+.3f}）")
        p(f"  止损次数 ：{a['loss']} -> {b['loss']}  （{b['loss']-a['loss']:+d}）")
        p("")
        delta = b["mn"] - a["mn"]
        if n < 100:
            p(f"  ⚠️ 样本 {n} < 100，结论**仅供参考**，不足以支撑参数定案。")
        if delta > 0:
            p(f"  新定价的净期望**更高**（{delta:+.3f}/笔）→ 与用户指定方向一致。")
        elif delta < 0:
            p(f"  新定价的净期望**更低**（{delta:+.3f}/笔）。")
            p("  注意：这是用户 2026-10-09 **明确指定**的规则（不是调参），")
            p("  故记录在案但**不擅自回滚**；若后续要重新评估，以本脚本为准。")
        else:
            p("  两者净期望相同。")
        p("")
        p("  机制解释（数字自明）：止盈缩到 %.0f%% 使目标更近，止损按 1/%.1f"
          % (shrink * 100, min_rr))
        p("  反推后止损距离 = 止盈距离/%.1f。止盈距离变近 → 止损同步变近，"
          % min_rr)
        p("  于是胜率与单笔盈亏同向变化，净效果由本回放给出。")

    out = ROOT / "research" / "28_first_entry_pricing_out.txt"
    try:
        out.write_text("\n".join(OUT), encoding="utf-8")
        p(f"\n已保存：{out.relative_to(ROOT)}")
    except Exception as e:
        p(f"\n（保存失败：{e}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
