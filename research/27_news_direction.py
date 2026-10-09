# -*- coding: utf-8 -*-
"""研究取证 27：新闻方向到底准不准（为"新闻提供做单方向"提供依据）。

背景
----
用户 2026-10-09：
> 我觉得新闻事件可以提供做单方向 而不是停止开仓

代码已改为**方向冲突闸**（`machine._decide_flat`）：新闻与信号冲突才拦，
一致就放行。但新闻的方向**从未被测量过** —— 实测 `news_*.jsonl` 里原先
只有 `{"event":"fetched","count":150}`，LLM 调用的 `chat_ok` 只记
`parsed_keys`，**结论本身没有落盘**。所以本脚本做两件事：

  A. 盘点现有日志里能拿到多少新闻结论（改动前 vs 改动后）
  B. 对**已落盘的** assessment 做前瞻收益检验：新闻说多/说空之后，
     价格真的往那边走了吗？（命中率 + 平均收益 + t 值）

⚠️ 诚实声明（必须写进结论）
---------------------------
金十 `search_flash` 只返回**当前**快讯，没有历史窗口，因此新闻
**无法回溯补测**。本脚本只能测「改动上线之后新积累的 assessment」。
若样本量不足，脚本会明确打印"不可结论"，而不是给一个漂亮的假数字。

口径
----
· 前瞻窗口：15/30/60/120 分钟（新闻是短时效信息）。
· 基准价：assessment 落盘时刻**之后**第一根 1m 收盘价（严格因果：
  绝不用落盘前的价格，否则测的是它已经知道的事）。
· 命中：看多且后续收益 > 0，或看空且后续收益 < 0。
· 中性（sentiment=neutral）不参与命中率统计，单独计数。
· 成本：往返 0.240 价格单位（XAUUSDm 实测点差），毛/净都报。
· `impact` 分档：高影响（>= news_impact_block）与低影响分开看 ——
  闸门只用高影响那一档，低影响档的表现不该混进来。

跑法::

    & $py research/27_news_direction.py
    & $py research/27_news_direction.py --symbol XAUUSDm
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sys
from pathlib import Path

import pandas as pd
import numpy as np

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parents[1]
OUT: list[str] = []

#: XAUUSDm 实测往返成本（价格单位）
COST = 0.240
#: 前瞻分钟数
HORIZONS = (15, 30, 60, 120)


def p(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def load_news_assessments() -> list[dict]:
    """从 news 日志里取 `event=assessment` 的记录（新格式）。"""
    rows = []
    for f in sorted((ROOT / "logs").glob("news_*.jsonl")):
        for r in _load_jsonl(f):
            if r.get("event") == "assessment":
                rows.append(r)
    return rows


def load_bars(symbol: str, tf: str = "1m") -> pd.DataFrame | None:
    """读 1m K 线：**优先 MT5 实时**（缓存可能远落后于 assessment 时间）。

    ⚠️ 为什么必须先试 MT5：`data/cache/` 是离线研究用的历史快照，
    实测只到 2026-09-18，而 assessment 是当天刚产生的 —— 只用缓存
    会一律"无可用样本"，得出"新闻没法测"的错误结论。
    """
    df = None

    # 1) MT5 实时（需要终端在跑）
    try:
        sys.path.insert(0, str(ROOT / "src"))
        import MetaTrader5 as mt5
        if mt5.initialize():
            try:
                import datetime as _dt
                need = 40000          # 1m bar 数，覆盖数天
                rates = mt5.copy_rates_from(symbol, mt5.TIMEFRAME_M1,
                                            _dt.datetime.now(_dt.UTC), need)
                if rates is not None and len(rates):
                    df = pd.DataFrame(rates)
                    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
                    df = df[["time", "close"]].sort_values("time") \
                           .reset_index(drop=True)
            finally:
                try:
                    mt5.shutdown()
                except Exception:
                    pass
    except Exception as e:
        p(f"  [提示] MT5 取数失败（{type(e).__name__}: {e}），改用缓存")

    # 2) 退回本地缓存
    if df is None or df.empty:
        for c in (ROOT / "data" / "cache" / f"{symbol}_{tf}.parquet",
                  ROOT / "data" / "cache" / f"{symbol}_{tf}_merged.parquet"):
            if not c.exists():
                continue
            try:
                d = pd.read_parquet(c)
            except Exception:
                continue
            if d.empty:
                continue
            tcol = next((x for x in d.columns
                         if x.lower() in ("time", "datetime", "date", "timestamp")),
                        None)
            if tcol is None:
                continue
            d = d[[tcol, "close"]].rename(columns={tcol: "time"})
            d["time"] = pd.to_datetime(d["time"], utc=True, errors="coerce")
            df = d.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
            break
    return df


def first_close_after(bars: pd.DataFrame, ts: float) -> tuple[float, int] | None:
    """严格因果：返回 assessment 时刻**之后**第一根 bar 的 (收盘价, 行号)。

    ⚠️ 两个坑（都实测踩过）：
    1. 不要用 `Series.searchsorted(Timestamp)`：pandas 对
       `datetime64[us, UTC]` 与 Timestamp 之间会报
       "Cannot losslessly convert units"。
    2. **不要**假设 `.astype("int64")` 得到的是纳秒 —— MT5 的
       `copy_rates_from` 回来是 `datetime64[s]`，直接转 int64 得到的是
       **秒**，与 Timestamp.value（纳秒）比较会差 10^9 倍，
       于是永远"越界"。这里统一转成 `datetime64[ns]` 再取 int64。
    """
    t = pd.Timestamp(ts, unit="s", tz="UTC")
    key = t.value  # 纳秒
    ns = bars["time"].astype("datetime64[ns, UTC]").astype("int64").to_numpy()
    idx = int(np.searchsorted(ns, key, side="left"))
    if idx >= len(bars):
        return None
    return float(bars["close"].iloc[idx]), idx


def close_at_offset(bars: pd.DataFrame, idx: int, minutes: int) -> float | None:
    """从行号 idx 起，minutes 分钟后的收盘价（1m bar -> idx+minutes）。"""
    j = idx + minutes
    if j >= len(bars):
        return None
    return float(bars["close"].iloc[j])


def tstat(xs: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    sd = math.sqrt(var)
    if sd <= 0:
        return float("nan")
    return m / (sd / math.sqrt(n))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSDm")
    ap.add_argument("--min-n", type=int, default=30,
                    help="每组最少样本数，低于此值只报数不下结论")
    args = ap.parse_args()

    p("=" * 96)
    p("研究取证 27 · 新闻方向准确性（为「新闻提供做单方向」提供依据）")
    p("=" * 96)

    # ── A. 现有日志盘点 ──
    p("\n" + "=" * 96)
    p("A. 新闻结论的落盘情况（改动前只有 fetched，结论从未落盘）")
    p("=" * 96)
    p("")
    n_fetched = n_assess = 0
    for f in sorted((ROOT / "logs").glob("news_*.jsonl")):
        for r in _load_jsonl(f):
            if r.get("event") == "fetched":
                n_fetched += 1
            elif r.get("event") == "assessment":
                n_assess += 1
    p(f"  news 日志里 fetched（只有条数）  = {n_fetched}")
    p(f"  news 日志里 assessment（有结论） = {n_assess}")
    if n_assess == 0:
        p("")
        p("  ⚠️ 尚无 assessment 记录。原因：该字段是 2026-10-09 本次改动**新增**的，")
        p("     而金十 search_flash 只返回当前快讯、**无历史窗口**，所以新闻无法")
        p("     回溯补测。跑完实盘（或先跑 dry_run 循环）后重跑本脚本即可。")
        p("")
        p("     为让下一次运行立刻有数据，本次同时把 impact/sentiment/headline")
        p("     方向分布写进了 news_*.jsonl（orchestrator._log_news_verdict）。")

    rows = load_news_assessments()
    if not rows:
        p("")
        p("结论：样本为 0，**不可结论**。等实盘积累 assessment 后重跑。")
        return 0

    # ── B. 前瞻收益检验 ──
    bars = load_bars(args.symbol)
    if bars is None:
        p("")
        p(f"!! 找不到 {args.symbol} 的 1m 缓存，无法做前瞻检验。")
        p(f"   期望文件：data/cache/{args.symbol}_1m.parquet")
        return 1

    p("")
    p(f"  1m 缓存：{len(bars)} 根，"
      f"{bars['time'].iloc[0]} .. {bars['time'].iloc[-1]}")

    p("\n" + "=" * 96)
    p("B. 前瞻收益：新闻说多/说空之后，价格真的往那边走了吗")
    p("=" * 96)

    # 情绪分布
    from collections import Counter
    senti = Counter(str(r.get("sentiment") or "") for r in rows)
    p("")
    p(f"  情绪分布：{dict(senti)}")

    thr = 0.7
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from gold_agent.common.config import CFG
        thr = float(CFG.decision.news_impact_block)
    except Exception:
        pass
    p(f"  闸门阈值 news_impact_block = {thr}")

    p("")
    p("  分组：高影响（>= 阈值，闸门实际使用）/ 低影响（< 阈值，仅供参考）")
    p("")

    # ── ⚠️ 有效独立样本数 ──
    # 相邻 assessment 只隔约 73 秒，而前瞻窗口是 15~120 分钟 → 窗口**大量重叠**，
    # 名义 n 会严重高估统计功效。实测踩过：24 条样本跨度仅 28.7 分钟，
    # 15 分钟窗口下真正独立的观测只有约 2 个，却算出了"命中率 100% / t=+8.70"。
    # 那是**同一段趋势被重复计数 24 次**，不是 24 个独立证据。
    ts_all = sorted(float(r["ts"]) for r in rows if r.get("ts"))
    span_min = (ts_all[-1] - ts_all[0]) / 60.0 if len(ts_all) > 1 else 0.0
    p(f"  样本时间跨度：{span_min:.1f} 分钟（{len(ts_all)} 条）")
    p(f"  → 15 分钟前瞻下**真正独立**的观测数约 {max(1.0, span_min/15):.1f} 个")
    p("     （窗口重叠会把名义 n 放大成假功效，下面每行都按此折算判读）")
    p("")

    for group, pred in (("高影响", lambda r: float(r.get("impact") or 0) >= thr),
                        ("低影响", lambda r: float(r.get("impact") or 0) < thr)):
        sub = [r for r in rows if pred(r)]
        dirs = [r for r in sub if str(r.get("sentiment")) in ("bullish", "bearish")]
        p("-" * 96)
        p(f"  【{group}】记录 {len(sub)} 条，其中有方向（多/空）{len(dirs)} 条")
        if not dirs:
            p("    （无有方向样本，跳过）")
            continue
        for h in HORIZONS:
            rets, hits, used = [], [], 0
            n_no_bar = n_no_fwd = 0
            for r in dirs:
                ts = r.get("ts")
                if not ts:
                    continue
                fa = first_close_after(bars, float(ts))
                if fa is None:
                    n_no_bar += 1      # K 线根本没覆盖到这个时刻
                    continue
                px0, idx = fa
                px1 = close_at_offset(bars, idx, h)
                if px1 is None:
                    n_no_fwd += 1      # 该时刻之后还没走够 h 分钟
                    continue
                used += 1
                long_ = str(r.get("sentiment")) == "bullish"
                # 方向收益（价格变动 × 方向）
                raw = (px1 - px0) if long_ else (px0 - px1)
                rets.append(raw)
                hits.append(1.0 if raw > 0 else 0.0)
            if used == 0:
                why = []
                if n_no_bar:
                    why.append(f"{n_no_bar} 条落在 K 线范围之外")
                if n_no_fwd:
                    why.append(f"{n_no_fwd} 条之后还没走满 {h} 分钟")
                p(f"    {h:>4} 分钟：无可用样本（{'；'.join(why) or '无样本'}）")
                continue
            hr = sum(hits) / used
            mean_gross = sum(rets) / used
            mean_net = mean_gross - COST
            t = tstat(rets)
            # 有效独立样本 ≈ 时间跨度 / 前瞻窗口（重叠修正）
            n_eff = max(1.0, span_min / h) if span_min > 0 else 1.0
            flag = ""
            if used < args.min_n or n_eff < args.min_n:
                flag = (f"  ⚠️ 名义 n={used}，但**有效独立样本仅 {n_eff:.1f} 个**"
                        f" -> 不可结论")
                # 有效样本这么少时 t 值没有意义，不展示以免被误读
                t_show = "  n/a"
            else:
                t_show = f"{t:>+5.2f}"
            if n_no_fwd:
                flag += f"  (另有 {n_no_fwd} 条尚未走满该窗口)"
            p(f"    {h:>4} 分钟：n={used:>4}  命中率={hr:>6.1%}  "
              f"平均毛利={mean_gross:>+7.3f}  净={mean_net:>+7.3f}  "
              f"t={t_show}{flag}")
        p("")

    p("=" * 96)
    p("读法（避免误读）")
    p("=" * 96)
    p("""
  · 命中率 50% + 净收益 <= 0 → 新闻方向**没有**可交易的信息量，
    此时"提供做单方向"只能停留在"否决冲突"（当前实现），不该升级为驱动开仓。
  · 净收益显著为正且 t > 2 → 才有资格讨论把新闻升级为方向来源。
  · 样本重叠：相邻 assessment 的前瞻窗口会重叠，t 值偏乐观；
    样本 < 30 一律视为不可结论（脚本会标注）。
  · 成本 0.240 是 XAUUSDm 实测点差；其它品种需按各自点差重算。
""")
    p(f"（本次样本总量 {len(rows)} 条）")

    out = ROOT / "research" / "27_news_direction_out.txt"
    try:
        out.write_text("\n".join(OUT), encoding="utf-8")
        p(f"\n已保存：{out.relative_to(ROOT)}")
    except Exception as e:
        p(f"\n（保存输出失败：{e}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
