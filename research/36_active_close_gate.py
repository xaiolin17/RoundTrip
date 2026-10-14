# -*- coding: utf-8 -*-
"""研究取证 36：**系统主动平仓闸**在做多侧的真实价值（MT5 权威口径 + 1m K 线反事实）。

用户诉求（2026-10-14 原话）
--------------------------
1.「现在的胜率不对啊 亏损次数大于盈利」
2.「我要的是修改权重和止损止盈 达到提高胜率的效果 不是把数据换个方式来造假
    保证数据好看 我要的是真实的信号和操作」
3. research/35 已证：只改做多单的止损/止盈**距离**无法把它从亏改到盈
   （9 个配置全部仍亏；做多止损单 107 笔中 0 笔曾摸到过计划止盈）。
4. 35 号【B】标出唯一未被证伪的可改点：
   **「机器人主动平」（平仓腿 reason=3）在做多侧净 -215.81、均笔 -2.036、胜率 38.7%**，
   而做空侧同样动作净 +94.91 → 用户 2026-10-14 选定：**取证主动平仓闸**。

本脚本回答的三个问题
--------------------
Q1 这些「机器人主动平」到底是**哪条规则**关掉的？
   （`decision/machine.py::_decide_holding` 共有 6 条 close_position 来源：
     窗口不一致率闸 / LLM 反向 / 锁盈回吐 / 信号回吐(收窄不可行) / 新闻不利 /
     **持仓超时 max_holding_h=4h 且亏损**。MT5 交割单只给 reason=3、不分来源，
     故本脚本用**持仓时长**做代理归因：时长 >= 3.9h 者即「4h 超时闸」。）
Q2 若这些单**不平仓**、按开仓时的计划 SL/TP 继续持有 → 真实成交会更好还是更差？
Q3 若把 `max_holding_h` 从 4h 放宽到 6/8/12/24h → 组合净盈亏与 DSR 如何？

数据来源与口径
--------------
与 research/35 完全一致（MT5 history_deals_get + history_orders_get + 1m K 线）：
· 逐笔盈亏 = 同一 position_id 全部 OUT 腿的 profit + commission + swap；
· 方向 = 开仓腿 type（0=BUY 做多 / 1=SELL 做空）；
· 出场方式 = 平仓腿 reason（3=机器人主动平 / 4=止损SL / 5=止盈TP）；
· 计划 SL/TP = **开仓 order** 的 sl/tp（成交单 order.price_open 恒为 0，故入场价
  一律取开仓腿真实成交价）。
· 反事实一律用「价格位移 × 手数 × 100」计价（XAUUSDm 1 手 = 100 盎司），
  与真实结果同口径比较（真实侧同样只用价格位移，不含手续费与隔夜息）。

无前视声明
----------
· 反事实只用**平仓之后**的 1m K 线推演「假设当时不平仓」的结果 —— 决策时未知未来，
  评估时用未来，是标准的反事实评估，不构成前视。
· 局限：不重建加仓腿、也不重建持仓期间被 trailing 改过的 SL/TP，
  一律用开仓时的计划 SL/TP → 反事实结果为**乐观上界**（把"可能被后续规则提前关掉"
  这部分放行了）。判读时按上界理解。

跑法::

    & $py research/36_active_close_gate.py
"""
from __future__ import annotations

import bisect
import datetime as dt
import io
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

#: 出场原因（deal.reason）中文标签。实测只出现 3/4/5。
REASON_ZH = {0: "客户端手动", 1: "移动端", 2: "网页", 3: "机器人主动平",
             4: "止损SL", 5: "止盈TP", 6: "强平SO", 7: "隔夜结算", 8: "追加保证金", 9: "拆单"}

#: 试验族 1：若「机器人主动平」的单**不平仓**、按原计划 SL/TP 继续持有，上限（小时）
HOLD_H = (1.0, 2.0, 4.0, 8.0, 24.0)
#: 试验族 2：放宽「持仓超时闸」max_holding_h（现网 4.0h；只对超时平仓单生效）
TIMEOUT_H = 4.0
MAXHOLD_H = (4.0, 6.0, 8.0, 12.0, 24.0)
#: DSR 去膨胀所用试验族规模：保守取两族合计 5 + 5 = 10（含各自基线配置）
N_TRIALS = len(HOLD_H) + len(MAXHOLD_H)

#: 持仓时长分桶边界（小时）；>= 3.9h 视作由 max_holding_h=4h 超时闸触发
EDGES = (0.0, 0.25, 0.5, 1.0, 2.0, 3.9, 1e9)

OUT: list[str] = []


def p(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


# ══════════════════════════════════════════════════════════════════
# 数据装载（与 research/35 同源同口径）
# ══════════════════════════════════════════════════════════════════
def load() -> tuple[list[dict], pd.DataFrame | None]:
    """MT5 交割单 + 历史订单 → 逐笔 position（含真实计划几何）；另返回 1m K 线。"""
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"MT5 初始化失败：{mt5.last_error()}")
    try:
        now = dt.datetime.now(dt.UTC)
        t0 = now - dt.timedelta(days=DAYS)
        deals = mt5.history_deals_get(t0, now + dt.timedelta(days=1))
        orders = mt5.history_orders_get(t0, now + dt.timedelta(days=1))
        bars = mt5.copy_rates_from(SYMBOL, mt5.TIMEFRAME_M1, now, 60000)
    finally:
        mt5.shutdown()
    if deals is None:
        raise RuntimeError("history_deals_get 返回空")

    deals = [d for d in deals if d.symbol == SYMBOL and d.magic == MAGIC]
    orders = [o for o in orders if o.symbol == SYMBOL and o.magic == MAGIC] if orders else []

    by_pid: dict = {}
    for o in orders:
        if o.position_id:
            by_pid.setdefault(o.position_id, []).append(o)

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
        is_long = (op[0].type == 0)
        in_px = float(op[0].price)
        out_px = float(cl[-1].price)
        t_in = float(op[0].time)
        t_out = float(cl[-1].time)
        vol0 = float(op[0].volume)
        # 开仓 order：方向一致（做多=BUY 0 / 做空=SELL 1），取成交时刻最接近开仓腿者
        want = 0 if is_long else 1
        cand = [o for o in by_pid.get(pid, []) if o.type == want]
        o = min(cand, key=lambda x: abs(x.time_done - t_in)) if cand else None
        sl = float(getattr(o, "sl", 0.0)) if o is not None else 0.0
        tp = float(getattr(o, "tp", 0.0)) if o is not None else 0.0
        sl_dist = abs(in_px - sl) if sl else 0.0
        tp_dist = abs(tp - in_px) if tp else 0.0
        rr = (tp_dist / sl_dist) if sl_dist > 0 else float("nan")
        move = (out_px - in_px) if is_long else (in_px - out_px)
        rows.append(dict(
            pid=pid, is_long=is_long, t_in=t_in, t_out=t_out,
            in_px=in_px, out_px=out_px,
            reason=int(cl[-1].reason),
            pnl=float(sum(d.profit + d.commission + d.swap for d in cl)),
            pnl_px=move * vol0 * 100.0,        # 价格位移口径（与反事实可比）
            vol0=vol0,
            sl=sl, tp=tp, sl_dist=sl_dist, tp_dist=tp_dist, rr=rr))
    rows.sort(key=lambda r: r["t_in"])

    m1 = None
    if bars is not None and len(bars):
        m1 = pd.DataFrame(bars)
        m1["time"] = m1["time"].astype("int64")
        m1 = m1.sort_values("time").reset_index(drop=True)
    return rows, m1


# ══════════════════════════════════════════════════════════════════
# 统计
# ══════════════════════════════════════════════════════════════════
def summ(rows: list[dict], key: str = "pnl") -> dict:
    if not rows:
        return dict(n=0, wr=float("nan"), tot=0.0, avg=float("nan"),
                    aw=float("nan"), al=float("nan"), pf=float("nan"))
    wins = [r[key] for r in rows if r[key] > 0]
    loss = [r[key] for r in rows if r[key] < 0]
    tot = sum(r[key] for r in rows)
    gw = sum(wins)
    gl = -sum(loss)
    return dict(n=len(rows), wr=len(wins) / len(rows), tot=tot, avg=tot / len(rows),
                aw=(gw / len(wins)) if wins else float("nan"),
                al=(sum(loss) / len(loss)) if loss else float("nan"),
                pf=(gw / gl) if gl > 0 else float("inf"))


def fmt(name: str, s: dict) -> str:
    if not s or s["n"] == 0:
        return f"    {name:<26} n=0"
    return (f"    {name:<26} n={s['n']:<4} 胜率 {s['wr']:>6.1%}  净 {s['tot']:>+9.2f} "
            f"均笔 {s['avg']:>+7.3f}  均盈 {s['aw']:>6.2f} 均亏 {s['al']:>7.2f} "
            f"盈亏比 {s['pf']:>5.2f}")


def dsr_of(rows: list[dict], key: str = "pnl") -> tuple[float, float, float]:
    """对逐笔美元盈亏序列算 DSR（返回 dsr, sr0, 逐笔 Sharpe）。"""
    from gold_agent.quant.labeling import deflated_sharpe
    x = np.array([r[key] for r in rows], dtype=float)
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


def q(a: list[float]) -> str:
    x = np.array([v for v in a if np.isfinite(v)], dtype=float)
    if not len(x):
        return "n=0"
    return (f"n={len(x):<4} P10={np.percentile(x,10):>7.2f} 中位={np.median(x):>7.2f} "
            f"P90={np.percentile(x,90):>7.2f} 最小={x.min():>7.2f} 最大={x.max():>7.2f}")


def dur_h(r: dict) -> float:
    return (r["t_out"] - r["t_in"]) / 3600.0


def px_pnl(r: dict, px: float) -> float:
    mv = (px - r["in_px"]) if r["is_long"] else (r["in_px"] - px)
    return mv * r["vol0"] * 100.0


def plan_prices(r: dict) -> tuple[float, float]:
    """按开仓时的计划几何还原 (止损价, 止盈价)。"""
    e = r["in_px"]
    return (e - r["sl_dist"], e + r["tp_dist"]) if r["is_long"] \
        else (e + r["sl_dist"], e - r["tp_dist"])


def with_overrides(rows: list[dict], override: dict) -> list[dict]:
    """返回把指定 pid 的 pnl_px 换成反事实值的行副本（其余保持真实）。"""
    out = []
    for r in rows:
        if r["pid"] in override:
            r2 = dict(r)
            r2["pnl_px"] = override[r["pid"]]
            out.append(r2)
        else:
            out.append(r)
    return out


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════
def main() -> int:
    p("=" * 112)
    p("研究取证 36 · 系统主动平仓闸的真实价值（MT5 真实成交 + 1m K 线反事实）")
    p("=" * 112)

    rows, m1 = load()
    longs = [r for r in rows if r["is_long"]]
    shorts = [r for r in rows if not r["is_long"]]

    p("")
    p(f"  品种 {SYMBOL}  magic {MAGIC}  窗口 {DAYS} 天  已平仓 position {len(rows)} 笔"
      f"（做多 {len(longs)} / 做空 {len(shorts)}）")
    p(f"  去膨胀试验族规模 N={N_TRIALS}"
      f"（族1 继续持有上限 {len(HOLD_H)} 个 + 族2 超时闸 {len(MAXHOLD_H)} 个）")
    if m1 is not None and len(m1):
        p(f"  1m K 线 {len(m1)} 根："
          f"{dt.datetime.fromtimestamp(int(m1['time'].iloc[0]), dt.UTC)}"
          f" .. {dt.datetime.fromtimestamp(int(m1['time'].iloc[-1]), dt.UTC)}")

    # ---------------- A 现状（价格位移口径，供反事实比对） ----------------
    p("")
    p("-" * 112)
    p("【A】现状（价格位移口径 = 与反事实同口径；不含手续费/隔夜息）")
    p("-" * 112)
    p(fmt("做多", summ(longs, "pnl_px")))
    p(fmt("做空", summ(shorts, "pnl_px")))
    p(fmt("合计", summ(rows, "pnl_px")))
    p(f"    （含手续费/隔夜息口径：做多 {summ(longs)['tot']:+.2f}  "
      f"做空 {summ(shorts)['tot']:+.2f}  合计 {summ(rows)['tot']:+.2f}）")

    # ---------------- B 归因：主动平仓到底是谁触发的 ----------------
    p("")
    p("=" * 112)
    p("【B】归因：reason=3「机器人主动平」按**持仓时长**分桶（时长>=3.9h 即 4h 超时闸）")
    p("=" * 112)
    active = [r for r in rows if r["reason"] == 3]
    p(f"  主动平仓合计 {len(active)}/{len(rows)} 笔（{len(active)/len(rows):.1%}）")
    for label, sub in (("做多", longs), ("做空", shorts)):
        g = [r for r in sub if r["reason"] == 3]
        if not g:
            continue
        p("")
        p(f"  ── {label} 主动平仓 {len(g)} 笔（占该方向 {len(g)/len(sub):.1%}），"
          f"持仓时长(h) {q([dur_h(r) for r in g])}")
        for a, b in zip(EDGES, EDGES[1:]):
            gg = [r for r in g if a <= dur_h(r) < b]
            if gg:
                tag = "  <= 4h 超时闸" if a >= 3.9 else ""
                p(fmt(f"时长[{a},{b})h{tag}", summ(gg, "pnl_px")))
        to = [r for r in g if dur_h(r) >= 3.9]
        er = [r for r in g if dur_h(r) < 3.9]
        p(f"     小结：超时闸(>=3.9h) {len(to)} 笔 净 {summ(to,'pnl_px')['tot']:+.2f}"
          f"（{len(to)/len(g):.1%}）；提前平(<3.9h) {len(er)} 笔 "
          f"净 {summ(er,'pnl_px')['tot']:+.2f}（{len(er)/len(g):.1%}）")

    # ---------------- C 反事实 1：不平仓、按原计划 SL/TP 继续持有 ----------------
    p("")
    p("=" * 112)
    p("【C】反事实 1：这些主动平仓单**若不平**、按开仓时的计划 SL/TP 继续持有（上限 H 小时）")
    p("     规则：用 1m K 线从平仓时刻之后推进，先触及者成交；同一根 bar 内两者都触及 →")
    p("     保守判为先止损；到上限仍未触及 → 按当时收盘价了结。")
    p("     局限：不重建加仓腿与被 trailing 改过的 SL/TP → 结果是**乐观上界**。")
    p("=" * 112)
    have = [r for r in active if r["sl_dist"] > 0 and r["tp_dist"] > 0]
    p(f"  可用于反事实的主动平仓单 {len(have)}/{len(active)} 笔"
      f"（缺有效计划 SL/TP 的 {len(active)-len(have)} 笔跳过）")
    if not have or m1 is None or len(m1) == 0:
        p("  数据不足，跳过【C】。")
    else:
        tt = m1["time"].to_numpy()
        hi = m1["high"].to_numpy(dtype=float)
        lo = m1["low"].to_numpy(dtype=float)
        cl_ = m1["close"].to_numpy(dtype=float)

        def hold_to(r: dict, deadline: float) -> tuple[float, str]:
            """从平仓时刻之后推进到 deadline，返回 (成交价, 触发明细)。"""
            a = bisect.bisect_right(tt, r["t_out"])
            b = bisect.bisect_right(tt, deadline)
            if b <= a:
                return float(cl_[min(a, len(cl_) - 1)]), "TO"
            sl_px, tp_px = plan_prices(r)
            for k in range(a, b):
                if r["is_long"]:
                    if lo[k] <= sl_px:
                        return sl_px, "SL"
                    if hi[k] >= tp_px:
                        return tp_px, "TP"
                else:
                    if hi[k] >= sl_px:
                        return sl_px, "SL"
                    if lo[k] <= tp_px:
                        return tp_px, "TP"
            return float(cl_[b - 1]), "TO"

        p("")
        p("  ── 逐档：把**全部**主动平仓单换成「继续持有」后的组合结果（价格位移口径）")
        base_px = summ(rows, "pnl_px")
        p(f"     基线（现状）      24 合计 n={base_px['n']:<4} 净 {base_px['tot']:>+9.2f}  "
          f"胜率 {base_px['wr']:.1%}")
        for H in HOLD_H:
            ov, hits = {}, {"TP": 0, "SL": 0, "TO": 0}
            for r in have:
                px, hit = hold_to(r, r["t_out"] + H * 3600.0)
                ov[r["pid"]] = px_pnl(r, px)
                hits[hit] += 1
            comb = with_overrides(rows, ov)
            s = summ(comb, "pnl_px")
            dsr, _, sr = dsr_of(comb, "pnl_px")
            p(f"     上限 {H:>4.1f}h 继续持有  n={s['n']:<4} 净 {s['tot']:>+9.2f}  "
              f"胜率 {s['wr']:>6.1%}  改善 {s['tot']-base_px['tot']:>+9.2f}  "
              f"Sharpe {sr:>+.3f}  DSR(N={N_TRIALS}) {dsr:.3f}   "
              f"(TP {hits['TP']} / SL {hits['SL']} / 超时 {hits['TO']})")

        p("")
        p("  ── 分方向（上限 24h，仅看主动平仓单这一子集）")
        for label, sub in (("做多", longs), ("做空", shorts)):
            g = [r for r in sub if r["reason"] == 3 and r["sl_dist"] > 0 and r["tp_dist"] > 0]
            if not g:
                continue
            real = summ(g, "pnl_px")
            cust: dict = {}
            hits = {"TP": 0, "SL": 0, "TO": 0}
            for r in g:
                px, hit = hold_to(r, r["t_out"] + 24 * 3600.0)
                cust[r["pid"]] = dict(pnl_px=px_pnl(r, px))
                hits[hit] += 1
            cf_rows = [dict(r, pnl_px=cust[r["pid"]]["pnl_px"]) for r in g]
            cfs = summ(cf_rows, "pnl_px")
            p(f"     {label}：真实 主动平 {real['n']} 笔 净 {real['tot']:>+8.2f} 胜率 {real['wr']:>6.1%}"
              f"  →  若继续持有 净 {cfs['tot']:>+8.2f} 胜率 {cfs['wr']:>6.1%}"
              f"  （差 {cfs['tot']-real['tot']:>+8.2f}；TP {hits['TP']} / SL {hits['SL']} / 超时 {hits['TO']}）")

    # ---------------- D 反事实 2：放宽持仓超时闸 max_holding_h ----------------
    p("")
    p("=" * 112)
    p(f"【D】反事实 2：放宽 `max_holding_h`（现网 {TIMEOUT_H:.1f}h）—— 只对**超时平仓单**生效")
    p("     只把「时长>=3.9h 且亏损被关」的那批换成「持有到新上限」，其余单保持真实不变。")
    p("=" * 112)
    to_rows = [r for r in rows if r["reason"] == 3 and dur_h(r) >= 3.9]
    p(f"  超时闸平仓单 {len(to_rows)} 笔（做多 "
      f"{sum(1 for r in to_rows if r['is_long'])} / 做空 "
      f"{sum(1 for r in to_rows if not r['is_long'])}），现网净 {summ(to_rows,'pnl_px')['tot']:+.2f}")
    if not to_rows or m1 is None or len(m1) == 0:
        p("  数据不足，跳过【D】。")
    else:
        tt = m1["time"].to_numpy()
        hi = m1["high"].to_numpy(dtype=float)
        lo = m1["low"].to_numpy(dtype=float)
        cl_ = m1["close"].to_numpy(dtype=float)

        def hold_to(r: dict, deadline: float) -> tuple[float, str]:
            a = bisect.bisect_right(tt, r["t_out"])
            b = bisect.bisect_right(tt, deadline)
            if b <= a:
                return float(cl_[min(a, len(cl_) - 1)]), "TO"
            sl_px, tp_px = plan_prices(r)
            for k in range(a, b):
                if r["is_long"]:
                    if lo[k] <= sl_px:
                        return sl_px, "SL"
                    if hi[k] >= tp_px:
                        return tp_px, "TP"
                else:
                    if hi[k] >= sl_px:
                        return sl_px, "SL"
                    if lo[k] <= tp_px:
                        return tp_px, "TP"
            return float(cl_[b - 1]), "TO"

        base_px = summ(rows, "pnl_px")
        p(f"  基线（现状） 组合 n={base_px['n']} 净 {base_px['tot']:+.2f} 胜率 {base_px['wr']:.1%}")
        for H in MAXHOLD_H:
            ov, hits = {}, {"TP": 0, "SL": 0, "TO": 0}
            for r in to_rows:
                if r["sl_dist"] <= 0 or r["tp_dist"] <= 0:
                    continue
                px, hit = hold_to(r, r["t_in"] + H * 3600.0)
                ov[r["pid"]] = px_pnl(r, px)
                hits[hit] += 1
            comb = with_overrides(rows, ov)
            s = summ(comb, "pnl_px")
            dsr, _, sr = dsr_of(comb, "pnl_px")
            tag = "（=基线自检）" if abs(H - TIMEOUT_H) < 1e-9 else ""
            p(f"    max_holding_h={H:>4.1f}h  n={s['n']:<4} 净 {s['tot']:>+9.2f}  "
              f"胜率 {s['wr']:>6.1%}  改善 {s['tot']-base_px['tot']:>+9.2f}  "
              f"Sharpe {sr:>+.3f}  DSR(N={N_TRIALS}) {dsr:.3f}  {tag}"
              f"  (TP {hits['TP']} / SL {hits['SL']} / 超时 {hits['TO']})")
        p("  说明：4.0h 一行是自检 —— 它的截止时刻≈真实平仓时刻，应几乎等于基线。")

    # ---------------- E 判读 ----------------
    p("")
    p("=" * 112)
    p("【E】判读")
    p("=" * 112)
    for label, sub in (("做多", longs), ("做空", shorts)):
        g = [r for r in sub if r["reason"] == 3]
        to = [r for r in g if dur_h(r) >= 3.9]
        er = [r for r in g if dur_h(r) < 3.9]
        p(f"  · {label}主动平仓 {len(g)} 笔：超时闸(>=3.9h) {len(to)} 笔 净 {summ(to,'pnl_px')['tot']:+.2f}"
          f"；提前平 {len(er)} 笔 净 {summ(er,'pnl_px')['tot']:+.2f}")
    p(f"  · 试验族规模 N={N_TRIALS}（族1 {len(HOLD_H)} + 族2 {len(MAXHOLD_H)}）须记入 data/trials.csv。")
    p("  · 采用门槛：组合净改善、且 DSR>0.95；否则不落地。")
    p("  · ⚠️ 反事实是乐观上界：真实持有中还会被其它规则提前关掉，故实际改善只会更小。")

    out_path = ROOT / "research" / "36_active_close_gate_out.txt"
    out_path.write_text("\n".join(OUT), encoding="utf-8")
    p("")
    p(f"已保存：{out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
