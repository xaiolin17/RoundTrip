# -*- coding: utf-8 -*-
"""研究取证 33：**权重尺度下调** 与 **做多趋势确认过滤** 的逐笔反事实。

用户诉求（2026-10-14 原话）
--------------------------
1. 「现在的胜率不对啊 亏损次数大于盈利」
2. 「我现在主要是想调整各个信号权重 现在各个权重系数肯定是不对的
    但是也不能取消 可以降低权重」
3. 选定方案：**降低整体权重尺度（降 W_SCALE）** + **做多单额外加趋势确认**。

为什么是「降尺度」而不是「改各源相对权重」
------------------------------------------
对最近窗口做了 per-source 逐笔归因：三个可测源（kalman_persist / chanlun /
classic_indicators）的**方向准确率几乎相同**、净贡献**逐笔完全相同**
（每一笔里三者都投同一方向），互相调权重是**数学空操作**；
`source_ir.json` 里三者 skill 全为负 → `w_measured` 全 0 → DL 排序失效 →
三者**顶格等权** `w_final = W_SCALE = 4.0`。
唯一还能动的旋钮是**整体尺度** `W_SCALE`：

    σ = 1 / √(Σw)        （gaussian.py）
    Σw' = k · Σw  →  σ' = σ/√k  →  z' = S/σ' = z·√k

score 是**加权平均**，对所有 w 同乘 k **不变**；只有 σ 变。
所以 k<1 → σ 变大 → 同一阈值 `z_min` 变**更难**过 → **交易更少**。
因为当前期望为负，「少交易」= 真实改善（真实信号变少，不是改口径）。

本脚本回答
----------
A. 样本概览：窗口内**真实开出来**的每一笔（risk_decision），其 z_obs 与结局。
B. 尺度扫描：对每个候选 `W_SCALE`（4.0→3.0/2.5/2.0，即 k=0.75/0.625/0.5）
   重算 z' = z·√k，切出**保留组**与**被剔除的边缘组**，比较两组结局。
   ⚠️ 必须正面检验 config.toml L42-46 的旧反证：
      「低信号档剔除 10-02 后 124 笔净 +37.77、胜率 54%」——
      若本窗口被剔除组同样为**正**，则「降尺度」不成立，不能改。
C. 做多趋势确认：对每笔做多单，看 chanlun 4h/1h 与 kalman.trend 是否同向为正，
   统计被该过滤挡掉的做多单结局。

口径与诚实声明
--------------
· 样本 = `trades.jsonl` 的 `risk_decision`（真实开仓/加仓），按 ts **精确**
  关联 `decision_*.jsonl` 的 `decision` 事件（实测 Δt 中位 0.00s），
  再按 round 取 `signals` 事件拿 chanlun / kalman / effective_weight。
· 因 decision 日志只保留 2026-10-12..10-14 三天，**样本窗口仅这三天**。
· 结局用 1m K 线**回放**：持有上限 = 现行 `max_holding_h`（4h = 240 根），
  同根内先判止损（不给乐观偏差），净R=(价格变动−成本)/止损距离，
  成本 = XAUUSDm 往返点差。入场价取决策时现价，非真实成交价。
· 未来窗口不足 240 根的近端单**直接剔除**，避免右截断把「超时」误当结局。
· 这是「同一批真实信号下 开/不开」的反事实，不是择时研究。

跑法::

    & $py research/33_weight_scale_and_long_filter.py
"""
from __future__ import annotations

import bisect
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

DAYS = ("20261012", "20261013", "20261014")
COST = 0.240            # XAUUSDm 实测往返点差（价格单位）
MAX_HOLD_MIN = 240      # 最长持有（1m 根数）：默认 4 小时，下面用现行配置覆盖
W_SCALE_CUR = 4.0       # 现行权重尺度（weights.py）

# z 门槛：默认走现行值；tight 窗口用 CFG 判定
Z_MIN_DEFAULT = 2.66
Z_MIN_TIGHT = 4.0
try:
    from gold_agent.common.config import CFG as _CFG
    Z_MIN_DEFAULT = float(_CFG.decision.z_min)
    Z_MIN_TIGHT = float(_CFG.decision.z_min_tight)
    MAX_HOLD_MIN = int(float(_CFG.risk.max_holding_h) * 60)   # 4h -> 240 根

    def _tight(ts: float) -> bool:
        from gold_agent.common.config import in_tight_window
        return bool(in_tight_window(ts))
except Exception:  # pragma: no cover
    def _tight(ts: float) -> bool:
        return False

OUT: list[str] = []


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


def load_decisions() -> tuple[list[dict], dict]:
    """读 decision_*.jsonl：返回 (decision 事件列表, round->signals)。"""
    decs: list[dict] = []
    sig_by_round: dict = {}
    for day in DAYS:
        pth = ROOT / "logs" / f"decision_{day}.jsonl"
        if not pth.exists():
            continue
        with pth.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                e = r.get("event")
                if e == "decision":
                    pr = r.get("proposal") or {}
                    decs.append(dict(ts=float(r.get("ts") or 0.0), round=r.get("round"),
                                     kind=pr.get("kind"), direction=pr.get("direction"),
                                     score_eff=r.get("score_eff"), sigma=r.get("sigma")))
                elif e == "signals":
                    sig_by_round[r.get("round")] = r
    decs.sort(key=lambda d: d["ts"])
    return decs, sig_by_round


def load_released(symbol: str = "XAUUSDm") -> list[dict]:
    """读 trades.jsonl 的 risk_decision（真实开仓/加仓腿）。"""
    pth = ROOT / "logs" / "trades.jsonl"
    out: list[dict] = []
    if not pth.exists():
        return out
    with pth.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("event") != "risk_decision":
                continue
            if r.get("symbol") not in (None, symbol):
                continue
            d = r.get("direction")
            ts = r.get("ts")
            if d not in ("LONG", "SHORT") or ts is None:
                continue
            row = _mk(d, r.get("entry_ref"), r.get("tp"), r.get("sl"), float(ts),
                      r.get("kind"), r.get("sl_source"))
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
    if not all(500.0 <= v <= 8000.0 for v in (e, tp, sl)):
        return None
    is_long = d == "LONG"
    tp_dist = (tp - e) if is_long else (e - tp)
    sl_dist = (e - sl) if is_long else (sl - e)
    if sl_dist <= 0 or tp_dist <= 0:
        return None
    return dict(direction=d, entry=e, tp=tp, sl=sl, ts=ts, kind=kind,
                sl_source=sl_source or "none", is_long=is_long,
                tp_dist=tp_dist, sl_dist=sl_dist, rr=tp_dist / sl_dist)


def _tf_score(node) -> float:
    """取 chanlun 某个周期的 score；状态非 ok 或缺值返回 nan。"""
    if not isinstance(node, dict):
        return float("nan")
    if node.get("status") != "ok":
        return float("nan")
    v = node.get("score")
    try:
        v = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return v if np.isfinite(v) else float("nan")


# ══════════════════════════════════════════════════════════════════
# 回放
# ══════════════════════════════════════════════════════════════════
def replay(bars: pd.DataFrame, i0: int, entry: float, tp: float, sl: float,
           is_long: bool) -> tuple[str, float]:
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


def summ(rs: list[float], outs: list[str]) -> dict:
    """rs = 净R 列表；outs = 结局列表。"""
    if not rs:
        return dict(n=0, wr=float("nan"), mR=float("nan"), tR=float("nan"),
                    wins=0, loss=0, tout=0, tot=0.0)
    wins = sum(1 for o in outs if o == "止盈")
    loss = sum(1 for o in outs if o == "止损")
    tout = sum(1 for o in outs if o == "超时")
    return dict(n=len(rs), wr=wins / len(rs), mR=float(np.mean(rs)), tR=tstat(rs),
                wins=wins, loss=loss, tout=tout, tot=float(np.sum(rs)))


def fmt(name: str, s: dict) -> str:
    if not s or s["n"] == 0:
        return f"    {name:<16} n=0"
    return (f"    {name:<16} n={s['n']:<4} 胜率 {s['wr']:>5.1%} "
            f"(盈{s['wins']}/亏{s['loss']}/超{s['tout']})  净R {s['mR']:>+7.3f} "
            f"(合计 {s['tot']:>+8.2f})  tR {s['tR']:>+5.2f}")


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════
def main() -> int:
    p("=" * 104)
    p("研究取证 33 · 权重尺度下调 与 做多趋势确认 的逐笔反事实")
    p("=" * 104)

    bars = load_bars()
    if bars is None or bars.empty:
        p("!! 拿不到 1m K 线，无法回放。")
        return 1
    ns = bars["time"].astype("datetime64[ns, UTC]").astype("int64").to_numpy()
    decs, sig_by_round = load_decisions()
    dec_ts = [d["ts"] for d in decs]
    p("")
    p(f"  1m K 线：{len(bars)} 根，{bars['time'].iloc[0]} .. {bars['time'].iloc[-1]}")
    p(f"  decision 事件 {len(decs)}，signals 轮 {len(sig_by_round)}；"
      f"成本={COST}  最长持有={MAX_HOLD_MIN} 分钟")
    p(f"  现行 W_SCALE={W_SCALE_CUR}  z_min={Z_MIN_DEFAULT}  z_min_tight={Z_MIN_TIGHT}")

    # ---------------- 关联 ----------------
    rel = load_released()
    rows: list[dict] = []
    n_nomatch = n_trunc = 0
    for r in rel:
        i = bisect.bisect_left(dec_ts, r["ts"])
        cand = [j for j in (i - 1, i) if 0 <= j < len(decs)]
        if not cand:
            n_nomatch += 1
            continue
        j = min(cand, key=lambda x: abs(dec_ts[x] - r["ts"]))
        if abs(dec_ts[j] - r["ts"]) > 1.0:
            n_nomatch += 1
            continue
        d = decs[j]
        se, sg = d.get("score_eff"), d.get("sigma")
        if se is None or sg in (None, 0) or not np.isfinite(sg) or sg <= 0:
            n_nomatch += 1
            continue
        sig = sig_by_round.get(d["round"]) or {}
        ew = sig.get("effective_weight")
        if ew is None or not np.isfinite(ew) or ew <= 0:
            ew = 1.0 / (float(sg) ** 2)          # 由 σ 反推 Σw
        ps = sig.get("per_source") or []
        po_w = 0.0
        for s in ps:
            if s.get("name") == "openmobius_smc" and s.get("w"):
                po_w = float(s["w"])
                break
        cl = sig.get("chanlun") or {}
        k4 = _tf_score(cl.get("4h"))
        k1 = _tf_score(cl.get("1h"))
        kt = (sig.get("kalman") or {}).get("trend")
        kt = float(kt) if isinstance(kt, (int, float)) and np.isfinite(kt) else np.nan

        i0 = int(np.searchsorted(ns, int(pd.Timestamp(r["ts"], unit="s", tz="UTC").value),
                                 side="left"))
        if i0 + MAX_HOLD_MIN > len(bars):
            n_trunc += 1          # 未来窗口不足 → 回放结局不可信，剔除
            continue
        o, g = replay(bars, i0, r["entry"], r["tp"], r["sl"], r["is_long"])
        R = (g - COST) / r["sl_dist"]
        r.update(z_obs=abs(float(se)) / float(sg), score_eff=float(se), sigma=float(sg),
                 ew=float(ew), po_w=po_w, cl4=k4, cl1=k1, ktrend=kt,
                 outcome=o, netR=R, tight=_tight(r["ts"]))
        rows.append(r)

    p("")
    p(f"  窗口内 risk_decision {len(rel)} 笔 → 成功关联 {len(rows)} 笔"
      f"（无决策匹配 {n_nomatch}，未来窗口不足 {n_trunc}）")
    if not rows:
        p("!! 无可关联样本。")
        return 1

    kinds: dict[str, int] = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    p(f"  类型分布：{kinds}")
    zs = np.array([r["z_obs"] for r in rows])
    p(f"  z_obs：中位 {np.median(zs):.2f}  p10 {np.quantile(zs, .1):.2f}  "
      f"p90 {np.quantile(zs, .9):.2f}  min {zs.min():.2f}")

    base = summ([r["netR"] for r in rows], [r["outcome"] for r in rows])
    p("")
    p(f"  全样本基线：{base['n']} 笔  胜率 {base['wr']:.1%}  "
      f"(盈{base['wins']}/亏{base['loss']}/超{base['tout']})  "
      f"净R {base['mR']:+.3f}  合计 {base['tot']:+.2f}  tR {base['tR']:+.2f}")

    # ---------------- B. 权重尺度扫描 ----------------
    p("")
    p("=" * 104)
    p("B. 权重尺度扫描：W_SCALE 4.0 -> 候选值（k = 新/旧 => z' = z·√k）")
    p("=" * 104)
    p("  说明：Σw' = k·Σw_可测 + Σw_仅先验；z' = z_obs·√(Σw'/Σw)。")
    p("        门槛用现行 z_min（tight 窗口内用 z_min_tight）。")
    p("")
    for k in (0.75, 0.625, 0.5):
        kept_r, kept_o, fil_r, fil_o = [], [], [], []
        for r in rows:
            ew_meas = max(0.0, r["ew"] - r["po_w"])
            ew_new = k * ew_meas + r["po_w"]
            ratio = ew_new / r["ew"]
            z_new = r["z_obs"] * math.sqrt(ratio)
            thr = Z_MIN_TIGHT if r["tight"] else Z_MIN_DEFAULT
            if z_new >= thr:
                kept_r.append(r["netR"]); kept_o.append(r["outcome"])
            else:
                fil_r.append(r["netR"]); fil_o.append(r["outcome"])
        sk, sf = summ(kept_r, kept_o), summ(fil_r, fil_o)
        p(f"  ── W_SCALE {W_SCALE_CUR:.1f} -> {W_SCALE_CUR * k:.2f}（k={k}） "
          f"保留 {sk['n']} / 剔除 {sf['n']} 笔")
        p(fmt("保留组", sk))
        p(fmt("被剔除的边缘组", sf))
        if sk["n"] and sf["n"]:
            d = sk["mR"] - sf["mR"]
            p(f"    差值：保留组净R − 被剔除组净R = {d:+.3f}")
            p(f"    若被剔除组净R < 0 → 剔除是改善；> 0 → 剔除是伤害。")
        p("")

    # ---------------- C. 做多趋势确认 ----------------
    p("=" * 104)
    p("C. 做多趋势确认过滤（仅作用于做多单；做空单不动）")
    p("=" * 104)
    longs = [r for r in rows if r["is_long"]]
    shorts = [r for r in rows if not r["is_long"]]
    sl_ = summ([r["netR"] for r in shorts], [r["outcome"] for r in shorts])
    lg_ = summ([r["netR"] for r in longs], [r["outcome"] for r in longs])
    p("")
    p(fmt("做多单（现状）", lg_))
    p(fmt("做空单（现状）", sl_))
    p("")

    def apply_filter(name: str, pred) -> None:
        keep_r, keep_o, drop_r, drop_o = [], [], [], []
        for r in longs:
            ok = pred(r)
            if ok is None:      # 缺数据 -> 保守放行
                keep_r.append(r["netR"]); keep_o.append(r["outcome"]); continue
            (keep_r if ok else drop_r).append(r["netR"])
            (keep_o if ok else drop_o).append(r["outcome"])
        sk, sd = summ(keep_r, keep_o), summ(drop_r, drop_o)
        p(f"  ── {name}（放行 {sk['n']} / 挡掉 {sd['n']}）")
        p(fmt("放行", sk))
        p(fmt("被挡掉", sd))
        p("")

    apply_filter("做多需 chanlun 4h>0 且 1h>0",
                 lambda r: (None if not (np.isfinite(r["cl4"]) and np.isfinite(r["cl1"]))
                            else (r["cl4"] > 0 and r["cl1"] > 0)))
    apply_filter("做多需 kalman.trend>0",
                 lambda r: (None if not np.isfinite(r["ktrend"]) else (r["ktrend"] > 0)))
    apply_filter("做多需 4h>0 且 1h>0 且 kalman.trend>0",
                 lambda r: (None if not (np.isfinite(r["cl4"]) and np.isfinite(r["cl1"])
                                         and np.isfinite(r["ktrend"]))
                            else (r["cl4"] > 0 and r["cl1"] > 0 and r["ktrend"] > 0)))

    # ---------------- D. 判读 ----------------
    p("=" * 104)
    p("D. 判读")
    p("=" * 104)
    p("  · B 段：若「被剔除的边缘组」净R 为负 → 降尺度是真实改善（少交易 = 去掉负期望）")
    p("          若为正 → 与 config.toml L42-46 的旧反证一致，**不应**降尺度。")
    p("  · C 段：若「被挡掉的做多单」净R 明显为负 → 趋势确认过滤有效。")
    p("  · 样本仅 2026-10-12..10-14 三天，N 有限；结论需按参数纪律记入 data/trials.csv。")

    out = ROOT / "research" / "33_weight_scale_and_long_filter_out.txt"
    try:
        out.write_text("\n".join(OUT), encoding="utf-8")
        p(f"\n已保存：{out.relative_to(ROOT)}")
    except Exception as e:
        p(f"\n（保存失败：{e}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
