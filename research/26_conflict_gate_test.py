# -*- coding: utf-8 -*-
"""测量「紧贴反向结构位」闸门（fusion_vs_levels_conflict）的经济学正确性。

被测规则（src/gold_agent/risk/levels.py 约 400-463 行）
----------------------------------------------------
  · 做多：入场价上方最近的**压力位**若距离 < conf_d = conflict_atr_mult x ATR
    （默认 0.3），则拒绝开仓，理由 fusion_vs_levels_conflict；
  · 做空对称：下方最近的**支撑位**若距离 < conf_d，拒绝；
  · 逃逸：若该位与反向位「纠缠」（conf_d 内存在反向位），跳过否决。

规则的理由（源码注释原话）：
  「做多但上方紧贴压力位 -> 进场就是买在压力位下方，随时被压回。」

竞争假设
--------
  该理由是**语义反了**：对做多来说，上方压力位是**止盈目标**，不是否决理由。
  做多的止盈本来就该放在压力位下方；「上方有压力位」是**必要条件**而非风险。
  若成立，则本闸门在砍掉本来正常的单子。

本脚本要回答的唯一问题
----------------------
  当价格处于入场点、且反向结构位非常近（< 0.3 x ATR）时，
  该方向的**前瞻收益**是否比无条件基线**更差**？

口径（重要，必须与实盘一致）
----------------------------
1. ATR 用**项目自己的约定**，不是「1m 上的 14 期 ATR」。
   src/gold_agent/agent/graph.py::_decision_atr 明确：
     tf = CFG.risk.atr_tf（config.toml = "1h"），
     tr = max(H-L, |H-prevC|, |L-prevC|)，atr = tr.rolling(14).mean()。
   即**1h 重采样的 ATR14（SMA）**，再因果地（只用已收盘的 1h bar）前推到 1m。
   1m ATR14 中位数只有 1.95 -> 0.3xATR = 0.585，与实盘 conf_d（4.2~5.2）差 9 倍，
   用它测的不是线上那条规则。1h 口径下 conf_d 中位数 5.18，与实盘观测吻合。
   （第 8 节仍给出 1m ATR 口径作为敏感性对照。）

2. 结构位用**诚实代理**：摆动高低点。
   · 摆动高：high[j] 是 [j-k, j+k] 窗口内的最大值；
   · 摆动低：low[j]  是 [j-k, j+k] 窗口内的最小值；
   · **因果性**：在 bar i 只使用 j <= i-k 的摆动（右侧 k 根已收盘才确认）；
   · **时效性**：位在形成后若被收盘价穿越（压力位被收盘突破 / 支撑位被收盘跌破）
     即失效，用最小堆求出每个位的首次失效时刻，只在 [j, inv[j]] 内有效；
   · **回溯窗口** W = 1440 根 1m（= 1 个交易日）。
   这不是完整的缠论/SMC 栈，是**代理**；跑得快、无前视、可复现。

3. 抽样步长 stride = 5 根 1m。前瞻窗口 15/30/60/120/240 根，因此样本**重叠**，
   普通 t 统计量会被高估；额外报告 Newey-West 调整 t（滞后阶数 = h/stride）。

4. 成本：往返 0.240 价格单位（实测买价 4176.955 / 卖价 4177.195）。
   1 价格单位 = 1000 点，故 0.240 = 240 点。毛/净均报告。

5. 样本不足 100 的分组一律标注为**不可结论**。

跑法::

    & $py research/26_conflict_gate_test.py
    & $py research/26_conflict_gate_test.py --stride 10 --w 2880
"""
from __future__ import annotations

import argparse
import heapq
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# 控制台/管道统一按 UTF-8 输出（内容仍只用中文与 ASCII，保持 GBK 可编码）
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)
except Exception:  # pragma: no cover
    pass

# ---------------------------------------------------------------
# 读取项目配置（失败则退回 config.toml 里的默认值，保证脚本可独立运行）
# ---------------------------------------------------------------
sys.path.insert(0, "src")
CONF_MULT, SL_ATR, MIN_RR, ATR_TF = 0.3, 1.2, 1.2, "1h"
try:
    from gold_agent.common.config import CFG
    CONF_MULT = float(CFG.risk.conflict_atr_mult)
    SL_ATR = float(CFG.risk.sl_atr_mult)
    MIN_RR = float(CFG.risk.min_rr)
    ATR_TF = str(CFG.risk.atr_tf)
except Exception as exc:  # pragma: no cover - 仅在脱离项目环境时触发
    print(f"[提示] 未能读取 CFG（{exc}），改用默认值 "
          f"conflict_atr_mult={CONF_MULT} sl_atr_mult={SL_ATR} min_rr={MIN_RR}")

HORIZONS = (15, 30, 60, 120, 240)
DATA_DEFAULT = Path("data/cache/XAUUSDm_1m_merged.parquet")
COST = 0.240          # 往返成本，价格单位
MIN_N = 100           # 低于此样本量 -> 不可结论


# ---------------------------------------------------------------
# 统计工具
# ---------------------------------------------------------------
def stats(x: np.ndarray, lag: int = 0) -> dict:
    """均值 / 中位数 / t(对 0) / Newey-West t。"""
    x = np.asarray(x, dtype=float)
    n = x.size
    if n < 2:
        return {"n": n, "mean": float("nan"), "med": float("nan"),
                "t": float("nan"), "nwt": float("nan")}
    m = float(x.mean())
    sd = float(x.std(ddof=1))
    t = m / (sd / np.sqrt(n)) if sd > 0 else float("nan")
    nwt = t
    if lag > 0:
        d = x - m
        v = float((d * d).mean())
        for l in range(1, lag + 1):
            v += 2.0 * (1.0 - l / (lag + 1.0)) * float((d[l:] * d[:-l]).mean())
        nwt = m / np.sqrt(max(v, 1e-18) / n)
    return {"n": n, "mean": m, "med": float(np.median(x)),
            "t": t, "nwt": nwt}


def welch(a: np.ndarray, b: np.ndarray) -> float:
    """Welch 差值 t 检验（a - b）。"""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if a.size < 2 or b.size < 2:
        return float("nan")
    se = np.sqrt(a.var(ddof=1) / a.size + b.var(ddof=1) / b.size)
    return float((a.mean() - b.mean()) / se) if se > 0 else float("nan")


def fmt(x: float, w: int = 8, d: int = 3) -> str:
    return f"{'nan':>{w}}" if not np.isfinite(x) else f"{x:>{w}.{d}f}"


# ---------------------------------------------------------------
# 结构位：摆动高低点 + 因果确认 + 失效判定
# ---------------------------------------------------------------
def find_swings(high: np.ndarray, low: np.ndarray, k: int):
    """摆动高/低。窗口 [j-k, j+k]，j 为窗口内极值。"""
    hs = pd.Series(high)
    ls = pd.Series(low)
    w = 2 * k + 1
    mh = hs.rolling(w, center=True).max()
    ml = ls.rolling(w, center=True).min()
    sh = ((hs == mh) & mh.notna()).to_numpy()
    sl = ((ls == ml) & ml.notna()).to_numpy()
    return sh, sl


def first_invalidation(level: np.ndarray, is_swing: np.ndarray,
                        close: np.ndarray, kind: str) -> np.ndarray:
    """求每个位的首次失效时刻（不含位自身所在的那根）。

    压力位：收盘价 > 位值 -> 失效（最小堆，按位值升序弹出）。
    支撑位：收盘价 < 位值 -> 失效（最大堆，取负）。
    未失效 -> n。
    """
    n = close.size
    inv = np.full(n, n, dtype=np.int64)
    heap: list[tuple[float, int]] = []
    if kind == "res":
        for t in range(n):
            c = close[t]
            while heap and heap[0][0] < c:
                _, j = heapq.heappop(heap)
                inv[j] = t
            if is_swing[t]:
                heapq.heappush(heap, (level[t], t))
    else:
        for t in range(n):
            c = close[t]
            while heap and -heap[0][0] > c:
                _, j = heapq.heappop(heap)
                inv[j] = t
            if is_swing[t]:
                heapq.heappush(heap, (-level[t], t))
    return inv


class Levels:
    """某一 k 值下的结构位集合，支持按 bar 查询「最近的上方位/下方位」。"""

    def __init__(self, df: pd.DataFrame, k: int):
        self.k = k
        self.close = df["close"].to_numpy(float)
        high = df["high"].to_numpy(float)
        low = df["low"].to_numpy(float)
        sh, sl = find_swings(high, low, k)
        # 压力位候选 = 摆动高，值取 high；支撑位候选 = 摆动低，值取 low
        self.res_idx = np.flatnonzero(sh)
        self.res_val = high[self.res_idx]
        self.res_inv = first_invalidation(high, sh, self.close, "res")
        self.sup_idx = np.flatnonzero(sl)
        self.sup_val = low[self.sup_idx]
        self.sup_inv = first_invalidation(low, sl, self.close, "sup")

    def _window(self, idx, val, inv, i, w):
        """返回 bar i 上处于有效期的位（值数组）。"""
        a = np.searchsorted(idx, i - w, "left")
        b = np.searchsorted(idx, i - self.k, "right")
        if b <= a:
            return np.empty(0)
        j = idx[a:b]
        v = val[a:b]
        return v[inv[a:b] > i]

    def above(self, i, w):
        """i 上有效的、严格高于收盘价的压力位值。"""
        v = self._window(self.res_idx, self.res_val, self.res_inv, i, w)
        c = self.close[i]
        return v[v > c]

    def below(self, i, w):
        """i 上有效的、严格低于收盘价的支撑位值。"""
        v = self._window(self.sup_idx, self.sup_val, self.sup_inv, i, w)
        c = self.close[i]
        return v[v < c]


# ---------------------------------------------------------------
# 前瞻收益
# ---------------------------------------------------------------
def forward(close: np.ndarray, i: int, h: int) -> float:
    """方向修正前的原始位移（价格单位）。"""
    return float(close[i + h] - close[i])


def build_samples(lv: Levels, atr: np.ndarray, w: int, stride: int,
                  i0: int, i1: int):
    """遍历抽样 bar，记录闸门条件与各周期的前瞻收益。

    返回 dict：每行 = 一个抽样 bar，含方向、是否紧贴反向位、是否纠缠、
    以及各 horizon 的**方向修正后**位移（正 = 该方向赚钱）。
    """
    rows = []
    for i in range(i0, i1, stride):
        c = lv.close[i]
        a = atr[i]
        if not np.isfinite(a) or a <= 0 or c <= 0:
            continue
        cd = CONF_MULT * a
        # 做多：上方压力位
        ra = lv.above(i, w)
        # 做空：下方支撑位
        sb = lv.below(i, w)
        # 纠缠：位附近 conf_d 内存在反向位（源码 _entangled 的语义）
        row = {"i": i, "close": c, "atr": a, "cd": cd}
        # 做多
        if ra.size:
            d = ra - c
            m = d < cd
            row["L_near"] = bool(m.any())
            row["L_dist"] = float(d[m].min()) if m.any() else float("nan")
            row["L_any"] = True
            if m.any():
                lvl = float(ra[m].min())
                # 纠缠：该压力位 conf_d 内是否有支撑位
                ent = bool(sb.size and np.any(np.abs(sb - lvl) < cd))
                row["L_ent"] = ent
            else:
                row["L_ent"] = False
        else:
            row["L_near"], row["L_dist"], row["L_any"], row["L_ent"] = \
                False, float("nan"), False, False
        # 做空
        if sb.size:
            d = c - sb
            m = d < cd
            row["S_near"] = bool(m.any())
            row["S_dist"] = float(d[m].min()) if m.any() else float("nan")
            row["S_any"] = True
            if m.any():
                lvl = float(sb[m].max())
                ent = bool(ra.size and np.any(np.abs(ra - lvl) < cd))
                row["S_ent"] = ent
            else:
                row["S_ent"] = False
        else:
            row["S_near"], row["S_dist"], row["S_any"], row["S_ent"] = \
                False, float("nan"), False, False
        # 是否有「足够远」的反向位可供止盈（min_rr 冗余度用）
        need = MIN_RR * SL_ATR * a
        row["L_far"] = bool(ra.size and np.any(ra - c >= need))
        row["S_far"] = bool(sb.size and np.any(c - sb >= need))
        # 前瞻位移（价格单位，正 = 该方向赚钱）
        for h in HORIZONS:
            f = forward(lv.close, i, h)
            row[f"L_{h}"] = f
            row[f"S_{h}"] = -f
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------
# 报表
# ---------------------------------------------------------------
def report_group(df: pd.DataFrame, cond: pd.Series, side: str,
                 title: str, lag_map: dict) -> None:
    """打印一个分组的各周期统计（毛 / 净）。"""
    sub = df[cond]
    print(f"\n  [{title}]  n={len(sub)}"
          + ("  ** 样本不足 %d，不可结论 **" % MIN_N if len(sub) < MIN_N else ""))
    print("  周期 |       n |    毛均值 |    中位数 | 毛均值(点) |      t |   NW-t"
          " |    净均值 | 净均值(点) | 净NW-t")
    for h in HORIZONS:
        x = sub[f"{side}_{h}"].to_numpy(float)
        if x.size == 0:
            continue
        s = stats(x, lag_map[h])
        # 净 = 毛 - 往返成本（价格单位）；成本是固定扣减
        net = x - COST
        sn = stats(net, lag_map[h])
        flag = "  <-- n<100" if s["n"] < MIN_N else ""
        print(f"  {h:>4} | {s['n']:>7} | {fmt(s['mean'])} | {fmt(s['med'])} "
              f"| {fmt(s['mean'] * 1000, 9, 1)} | {fmt(s['t'], 7, 2)} "
              f"| {fmt(s['nwt'], 7, 2)} | {fmt(sn['mean'])} "
              f"| {fmt(sn['mean'] * 1000, 9, 1)} | {fmt(sn['nwt'], 7, 2)}{flag}")


def report_diff(df: pd.DataFrame, cond: pd.Series, base: pd.Series, side: str,
                title: str) -> None:
    """紧贴组 vs 对照组的差值检验。"""
    a_all, b_all = df[cond], df[base]
    print(f"\n  [{title}]  差值 = 紧贴组 - 对照组（负 = 紧贴更差）")
    print("  周期 |   紧贴n |   对照n |   均值差 | 均值差(点) |  差值t | 净均值差 | 净差值t")
    for h in HORIZONS:
        a = a_all[f"{side}_{h}"].to_numpy(float)
        b = b_all[f"{side}_{h}"].to_numpy(float)
        if a.size < 2 or b.size < 2:
            continue
        t = welch(a, b)
        tn = welch(a - COST, b - COST)   # 成本对两组同额扣减，差值不变
        note = "  <-- n<100，不可结论" if min(a.size, b.size) < MIN_N else ""
        print(f"  {h:>4} | {a.size:>7} | {b.size:>7} | {fmt(a.mean() - b.mean())} "
              f"| {fmt((a.mean() - b.mean()) * 1000, 9, 1)} | {fmt(t, 7, 2)} "
              f"| {fmt(a.mean() - b.mean())} | {fmt(tn, 7, 2)}{note}")


def headline(df: pd.DataFrame, side: str) -> None:
    """单行结论摘要（净均值差 = 紧贴 - 对照）。"""
    print(f"\n  【{('做多' if side == 'L' else '做空')} 净均值差汇总（紧贴 - 对照，价格单位）】")
    print("  周期 | 紧贴n | 对照n | 毛均值差 | 净均值差 | 净差值t | 判定")
    for h in HORIZONS:
        if side == "L":
            a = df[df.L_near][f"L_{h}"].to_numpy(float)
            b = df[~df.L_near][f"L_{h}"].to_numpy(float)
        else:
            a = df[df.S_near][f"S_{h}"].to_numpy(float)
            b = df[~df.S_near][f"S_{h}"].to_numpy(float)
        if a.size < 2 or b.size < 2:
            continue
        d = a.mean() - b.mean()
        t = welch(a, b)
        if min(a.size, b.size) < MIN_N:
            v = "不可结论(n<100)"
        elif not np.isfinite(t):
            v = "不可结论"
        elif t < -1.96:
            v = "紧贴显著更差(支持闸门)"
        elif t > 1.96:
            v = "紧贴显著更好(反对闸门)"
        else:
            v = "无显著差异"
        print(f"  {h:>4} | {a.size:>5} | {b.size:>5} | {fmt(d)} | {fmt(d)} "
              f"| {fmt(t, 7, 2)} | {v}")
    print("  注：净均值差 = 毛均值差（两组同额扣成本 0.240，差值不变）。")


# ---------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="紧贴反向结构位闸门的前瞻收益测量")
    ap.add_argument("--data", default=str(DATA_DEFAULT), help="1m parquet 路径")
    ap.add_argument("--w", type=int, default=1440, help="结构位回溯窗口（1m 根数）")
    ap.add_argument("--stride", type=int, default=5, help="抽样步长")
    ap.add_argument("--ks", type=int, nargs="+", default=[5, 10],
                    help="摆动窗口 k（左右各 k 根）")
    args = ap.parse_args()

    path = Path(args.data)
    if not path.exists():
        print(f"[错误] 找不到数据文件 {path}")
        return 2

    df = pd.read_parquet(path)
    df = df.sort_values("time").reset_index(drop=True)
    print("=" * 78)
    print("0. 数据")
    print("=" * 78)
    print(f"  文件      : {path}")
    print(f"  列        : {list(df.columns)}")
    t = pd.to_datetime(df['time'])
    print(f"  时间范围  : {t.min()} -> {t.max()}  (UTC)")
    print(f"  bar 数    : {len(df)}")
    days = t.dt.date
    print(f"  覆盖交易日: {days.nunique()} 天（跨度 {(t.max() - t.min()).days} 天）")
    print(f"  价格区间  : {df.close.min():.3f} ~ {df.close.max():.3f}")
    print(f"  重复时间戳: {int(t.duplicated().sum())}")
    print(f"  往返成本  : {COST:.3f} 价格单位 = {COST * 1000:.0f} 点")

    # ---- ATR：项目约定 = 高级别（1h）ATR14，因果前推到 1m ----
    print("\n" + "=" * 78)
    print("1. ATR 口径（与实盘一致）")
    print("=" * 78)
    print(f"  CFG.risk.atr_tf = {ATR_TF}；ATR = tr.rolling(14).mean()（SMA）")
    d = df.set_index("time")
    o = d.resample(ATR_TF).agg({"high": "max", "low": "min",
                                "close": "last"}).dropna()
    tr = pd.concat([o["high"] - o["low"],
                    (o["high"] - o["close"].shift()).abs(),
                    (o["low"] - o["close"].shift()).abs()], axis=1).max(axis=1)
    a_hi = tr.rolling(14).mean().dropna()
    # 因果映射：1h bar 在收盘后才可用，故时间戳 +1 个 1h 再前推
    shift = pd.Timedelta(hours=1) if ATR_TF == "1h" else pd.Timedelta(0)
    s = pd.Series(a_hi.to_numpy(), index=a_hi.index + shift)
    atr = s.reindex(d.index, method="ffill").to_numpy(float)
    valid = np.isfinite(atr)
    print(f"  {ATR_TF} bar 数 = {len(o)}；ATR14 中位数 = {np.median(a_hi):.3f}")
    print(f"  1m 对齐后有效 ATR 覆盖 {valid.sum()}/{len(df)} 根"
          f"（前 {int((~valid).sum())} 根预热期无 ATR）")
    cd_all = CONF_MULT * atr[valid]
    print(f"  conf_d = {CONF_MULT} x ATR：中位数 = {np.median(cd_all):.3f}，"
          f"p05 = {np.percentile(cd_all, 5):.3f}，p95 = {np.percentile(cd_all, 95):.3f}")
    print(f"  止损代理 sl_dist = sl_atr_mult({SL_ATR}) x ATR：中位数 = "
          f"{np.median(SL_ATR * atr[valid]):.3f}")
    print(f"  min_rr = {MIN_RR} -> 所需止盈距离中位数 = "
          f"{np.median(MIN_RR * SL_ATR * atr[valid]):.3f}")
    print("  说明：实盘 sl_dist 由最近支撑位决定（实测中位数 9.53），"
          "此处 ATR 代理仅用于赔率冗余度测算。")

    # ---- 结构位口径 ----
    print("\n" + "=" * 78)
    print("2. 结构位口径（诚实代理：摆动高低点）")
    print("=" * 78)
    print("  · 摆动高 = high[j] 为 [j-k, j+k] 窗口最大值；摆动低对称取最小")
    print("  · 因果性：bar i 只使用 j <= i-k 的摆动（右侧 k 根已收盘）")
    print("  · 时效性：位被收盘价穿越即失效（压力位被收盘上破 / 支撑位被收盘下破）")
    print(f"  · 回溯窗口 W = {args.w} 根 1m；仅用 1m 结构位（不用 LLM 位）")
    print(f"  · 抽样步长 stride = {args.stride} 根 1m")

    i0 = args.w + 300
    i1 = len(df) - max(HORIZONS)
    print(f"  · 抽样区间 = [{i0}, {i1})，共 {(i1 - i0) // args.stride} 个样本点")
    lag_map = {h: max(1, int(round(h / args.stride))) for h in HORIZONS}
    print(f"  · Newey-West 滞后阶数 = {lag_map}（因前瞻窗口重叠，普通 t 会高估）")

    # ---- 逐 k 计算 ----
    results: dict[int, pd.DataFrame] = {}
    for k in args.ks:
        lv = Levels(df, k)
        print(f"\n  [k={k}] 摆动高 {lv.res_idx.size} 个 / 摆动低 {lv.sup_idx.size} 个")
        smp = build_samples(lv, atr, args.w, args.stride, i0, i1)
        results[k] = smp
        print(f"        有效样本 {len(smp)}；"
              f"命中率 near_res(做多) = {smp.L_near.mean():.3f}，"
              f"near_sup(做空) = {smp.S_near.mean():.3f}")
        if smp.L_near.any():
            print(f"        紧贴距离中位数：压力 {smp.L_dist.median():.3f} / "
                  f"支撑 {smp.S_dist.median():.3f} 价格单位")
            print(f"        其中与反向位「纠缠」（闸门逃逸）比例："
                  f"做多 {smp[smp.L_near].L_ent.mean():.3f}，"
                  f"做空 {smp[smp.S_near].S_ent.mean():.3f}")

    # ---- 主结果 ----
    k_main = args.ks[0]
    smp = results[k_main]
    print("\n" + "=" * 78)
    print(f"3. 主结果（k={k_main}）—— 分组前瞻收益，正 = 该方向赚钱")
    print("=" * 78)
    print(f"  基线说明：对照组 = 同方向上「conf_d 内无反向结构位」的样本。")
    print(f"  毛均值单位 = 价格单位（1 单位 = 1000 点）；净 = 毛 - {COST}。")

    for side, name in (("L", "做多 LONG"), ("S", "做空 SHORT")):
        near = smp[f"{side}_near"]
        print("\n" + "-" * 78)
        print(f"  方向：{name}")
        print("-" * 78)
        report_group(smp, near, side, f"紧贴反向位 {name}", lag_map)
        report_group(smp, ~near, side, f"对照组（无紧贴位）{name}", lag_map)
        report_group(smp, pd.Series(True, index=smp.index), side,
                     f"无条件基线 {name}", lag_map)
        report_diff(smp, near, ~near, side, f"紧贴 vs 对照 {name}")
        headline(smp, side)

    # ---- 不同 k 的口径对照 ----
    if len(args.ks) > 1:
        print("\n" + "=" * 78)
        print("3b. 摆动窗口 k 的口径对照（紧贴 - 对照，净均值差）")
        print("=" * 78)
        print("  k 越大 -> 结构位越少越显著 -> 命中率越低、对照组越大")
        for k in args.ks:
            sk = results[k]
            print(f"\n  【k={k}】near_res 命中率 {sk.L_near.mean():.3f}，"
                  f"near_sup 命中率 {sk.S_near.mean():.3f}")
            print("  方向 | 周期 | 紧贴n | 对照n | 净均值差 | 净差值t | 判定")
            for side, name in (("L", "做多"), ("S", "做空")):
                near = sk[f"{side}_near"]
                for h in HORIZONS:
                    a = sk[near][f"{side}_{h}"].to_numpy(float)
                    b = sk[~near][f"{side}_{h}"].to_numpy(float)
                    if a.size < 2 or b.size < 2:
                        continue
                    d_ = a.mean() - b.mean()
                    tt = welch(a, b)
                    if min(a.size, b.size) < MIN_N:
                        v = "不可结论(n<100)"
                    elif not np.isfinite(tt):
                        v = "不可结论"
                    elif tt < -1.96:
                        v = "紧贴更差"
                    elif tt > 1.96:
                        v = "紧贴更好"
                    else:
                        v = "无差异"
                    print(f"  {name} | {h:>4} | {a.size:>5} | {b.size:>5} "
                          f"| {fmt(d_)} | {fmt(tt, 7, 2)} | {v}")

    # ---- 闸门真正会砍掉的那批：紧贴 且 不纠缠 ----
    print("\n" + "=" * 78)
    print(f"4. 闸门实际会否决的子集（紧贴 且 不纠缠）—— 最贴近线上行为")
    print("=" * 78)
    for side, name in (("L", "做多"), ("S", "做空")):
        near = smp[f"{side}_near"]
        veto = near & (~smp[f"{side}_ent"])       # 会被 fusion_vs_levels_conflict 拒绝
        ctrl = ~near                              # 对照组
        print(f"\n  {name}：被否决 n={int(veto.sum())}，"
              f"对照组 n={int(ctrl.sum())}")
        print("  周期 |   否决n |   对照n |   均值差 | 均值差(点) |  差值t | 判定")
        for h in HORIZONS:
            a = smp[veto][f"{side}_{h}"].to_numpy(float)
            b = smp[ctrl][f"{side}_{h}"].to_numpy(float)
            if a.size < 2 or b.size < 2:
                continue
            d_ = a.mean() - b.mean()
            tt = welch(a, b)
            if min(a.size, b.size) < MIN_N:
                v = "不可结论(n<100)"
            elif not np.isfinite(tt):
                v = "不可结论"
            elif tt < -1.96:
                v = "被否决的更差(支持闸门)"
            elif tt > 1.96:
                v = "被否决的更好(反对闸门)"
            else:
                v = "无显著差异"
            print(f"  {h:>4} | {a.size:>7} | {b.size:>7} | {fmt(d_)} "
                  f"| {fmt(d_ * 1000, 9, 1)} | {fmt(tt, 7, 2)} | {v}")

    # ---- 分半样本 ----
    print("\n" + "=" * 78)
    print(f"5. 稳健性：按时间对半切分（k={k_main}）")
    print("=" * 78)
    mid = smp["i"].median()
    for half, hs in (("前半", smp[smp["i"] <= mid]), ("后半", smp[smp["i"] > mid])):
        d0, d1 = pd.to_datetime(df['time'].iloc[int(hs['i'].min())]), \
            pd.to_datetime(df['time'].iloc[int(hs['i'].max())])
        print(f"\n  【{half}】 {d0} -> {d1}  样本 {len(hs)}  "
              f"覆盖 {pd.Series(pd.to_datetime(df['time'].iloc[hs['i'].tolist()]).dt.date).nunique()} 天")
        print("  方向 | 周期 | 紧贴n | 对照n | 毛均值差 | 净均值差 | 净差值t | 判定")
        for side, name in (("L", "做多"), ("S", "做空")):
            near = hs[f"{side}_near"]
            a_all, b_all = hs[near], hs[~near]
            for h in HORIZONS:
                a = a_all[f"{side}_{h}"].to_numpy(float)
                b = b_all[f"{side}_{h}"].to_numpy(float)
                if a.size < 2 or b.size < 2:
                    continue
                d_ = a.mean() - b.mean()
                tt = welch(a, b)
                if min(a.size, b.size) < MIN_N:
                    v = "不可结论(n<100)"
                elif not np.isfinite(tt):
                    v = "不可结论"
                elif tt < -1.96:
                    v = "紧贴更差"
                elif tt > 1.96:
                    v = "紧贴更好"
                else:
                    v = "无差异"
                print(f"  {name} | {h:>4} | {a.size:>5} | {b.size:>5} | {fmt(d_)} "
                      f"| {fmt(d_)} | {fmt(tt, 7, 2)} | {v}")

    # ---- 与 min_rr 的冗余度 ----
    print("\n" + "=" * 78)
    print("6. 与既有 min_rr 拒绝的重叠（冗余度）")
    print("=" * 78)
    ln = smp[smp.L_near]
    sn = smp[smp.S_near]
    need = MIN_RR * SL_ATR * smp["atr"]
    # (a) 题面口径：止盈被迫放在「最近压力位」时是否够赔率
    fail_a = (ln["L_dist"] < MIN_RR * SL_ATR * ln["atr"]).mean()
    fail_s = (sn["S_dist"] < MIN_RR * SL_ATR * sn["atr"]).mean()
    # (b) 线上真实口径：_target_beyond 会跳过近位往更远处找，
    #     只有当上方**不存在**距离 >= need 的压力位时 min_rr 才会拒绝
    red_l = (~ln["L_far"]).mean()
    red_s = (~sn["S_far"]).mean()
    # (c) 用实盘实测 sl_dist 中位数 9.53 做敏感性
    live_need = MIN_RR * 9.53
    fail_live_l = (ln["L_dist"] < live_need).mean()
    print(f"  sl_dist 代理 = sl_atr_mult({SL_ATR}) x ATR(1h)；"
          f"min_rr = {MIN_RR}")
    print(f"  所需止盈距离 need 中位数 = {(MIN_RR * SL_ATR * smp['atr']).median():.3f}")
    print("")
    print("  (a) 题面口径：止盈必须放在「最近压力位/支撑位」上")
    print(f"      做多 near_res 中 (near_res - entry) < 1.2 x sl_dist 的比例 = "
          f"{fail_a:.4f}  (n={len(ln)})")
    print(f"      做空 near_sup 中 (entry - near_sup) < 1.2 x sl_dist 的比例 = "
          f"{fail_s:.4f}  (n={len(sn)})")
    print(f"      -> 结构性必然接近 100%：近位距离 < {CONF_MULT} x ATR = "
          f"{np.median(CONF_MULT * smp['atr']):.3f}，"
          f"而 need 中位数 {np.median(MIN_RR * SL_ATR * smp['atr']):.3f}")
    print("")
    print("  (b) 线上真实口径：_target_beyond 会跳过近位往更远处找止盈，")
    print("      只有「上方不存在距离 >= need 的压力位」时 min_rr 才拒绝")
    print(f"      做多：被闸门否决的样本里，min_rr 也会拒绝的比例 = {red_l:.4f} "
          f"(n={len(ln)})")
    print(f"      做空：被闸门否决的样本里，min_rr 也会拒绝的比例 = {red_s:.4f} "
          f"(n={len(sn)})")
    print(f"      -> 真正的冗余度 = {red_l:.4f}（做多）/ {red_s:.4f}（做空）；"
          f"其余 {1 - red_l:.4f}/{1 - red_s:.4f} 是闸门**独有**的否决")
    print("")
    print(f"  (c) 敏感性：若 sl_dist = 9.53（实盘实测中位数），need = {live_need:.3f}")
    print(f"      做多 near_res 中距离 < {live_need:.2f} 的比例 = {fail_live_l:.4f}")
    print("")
    print("  另：做多样本中上方完全没有任何有效压力位的比例 = "
          f"{1 - smp['L_any'].mean():.4f}；做空下方无任何支撑位 = "
          f"{1 - smp['S_any'].mean():.4f}")

    # ---- 敏感性：1m ATR 口径 ----
    print("\n" + "=" * 78)
    print("7. 敏感性对照：若误用 1m ATR14（Wilder）会得到什么 conf_d")
    print("=" * 78)
    prev_c = np.empty(len(df))
    prev_c[0] = df["close"].iloc[0]
    prev_c[1:] = df["close"].to_numpy(float)[:-1]
    hh = df["high"].to_numpy(float)
    ll = df["low"].to_numpy(float)
    tr1 = np.maximum(hh - ll, np.maximum(np.abs(hh - prev_c), np.abs(ll - prev_c)))
    atr1m = pd.Series(tr1).ewm(alpha=1.0 / 14, adjust=False).mean().to_numpy()
    print(f"  1m ATR14 中位数 = {np.median(atr1m[300:]):.3f}，"
          f"conf_d 中位数 = {np.median(CONF_MULT * atr1m[300:]):.3f}")
    print(f"  1h ATR14 中位数 = {np.median(a_hi):.3f}，"
          f"conf_d 中位数 = {np.median(CONF_MULT * a_hi):.3f}")
    print("  两者相差约 9 倍 -> 用 1m ATR 测的不是线上那条规则（线上 atr_tf = "
          f"{ATR_TF}）。")
    for k in (k_main,):
        lv = Levels(df, k)
        smp2 = build_samples(lv, atr1m, args.w, args.stride, i0, i1)
        print(f"  [k={k}, 1m ATR] near_res 命中率 = {smp2.L_near.mean():.3f} "
              f"(1h 口径 {smp.L_near.mean():.3f})，样本 {len(smp2)}")
        print("  周期 |   紧贴n |   对照n |   均值差 | 均值差(点) |  差值t | 判定")
        for h in HORIZONS:
            a = smp2[smp2.L_near][f"L_{h}"].to_numpy(float)
            b = smp2[~smp2.L_near][f"L_{h}"].to_numpy(float)
            if a.size < 2 or b.size < 2:
                continue
            d_ = a.mean() - b.mean()
            tt = welch(a, b)
            v = ("不可结论(n<100)" if min(a.size, b.size) < MIN_N
                 else ("紧贴更差" if tt < -1.96 else
                       ("紧贴更好" if tt > 1.96 else "无差异")))
            print(f"  {h:>4} | {a.size:>7} | {b.size:>7} | {fmt(d_)} "
                  f"| {fmt(d_ * 1000, 9, 1)} | {fmt(tt, 7, 2)} | {v}")

    # ---- 距离梯度：闸门故事若为真，距离越远收益应单调越好 ----
    print("\n" + "=" * 78)
    print("8. 距离梯度检验（关键）")
    print("=" * 78)
    print("  问题：hit 率约 0.89，对照组只剩 11% —— 它其实是「1440 根内没有任何")
    print("  有效反向位」的**稀有行情**（强突破/单边），不是干净的对照。")
    print("  更干净的检验：在**全体样本**上，看前瞻收益是否随「到最近反向位的距离」")
    print("  单调改善。若闸门故事为真（越贴近越容易被压回），距离越大收益应越好。")
    for side, name, col in (("L", "做多", "L_dist"), ("S", "做空", "S_dist")):
        dist_atr = smp[col] / smp["atr"]          # 归一化为 ATR 倍数
        edges = [0.0, 0.05, 0.10, 0.20, 0.30, np.inf]
        labels = ["<0.05", "0.05-0.10", "0.10-0.20", "0.20-0.30", ">=0.30(对照)"]
        print(f"\n  {name}：按「到最近反向位的距离 / ATR」分组")
        print("  距离区间 |       n |  h=15 |  h=30 |  h=60 | h=120 | h=240 | 净h=60")
        for bi in range(len(edges) - 1):
            lo, hi = edges[bi], edges[bi + 1]
            m = (dist_atr >= lo) & (dist_atr < hi)
            if side == "S":
                # 做空侧：col 为 nan 表示下方无支撑位 -> 归入对照组
                m = m | (smp[col].isna() & (hi == np.inf))
            sub = smp[m]
            if len(sub) == 0:
                continue
            cells = []
            for h in HORIZONS:
                cells.append(fmt(sub[f'{side}_{h}'].mean(), 6, 3))
            net60 = sub[f"{side}_60"].mean() - COST
            flag = "  <-- n<100" if len(sub) < MIN_N else ""
            print(f"  {labels[bi]:>9} | {len(sub):>7} | " + " | ".join(cells)
                  + f" | {fmt(net60, 6, 3)}{flag}")
        # 连续斜率：fwd ~ a + b * (dist/ATR)，只在紧贴组内
        near = smp[f"{side}_near"]
        x = dist_atr[near].to_numpy(float)
        print(f"  紧贴组内回归（n={int(near.sum())}，x = 距离/ATR）：")
        for h in HORIZONS:
            y = smp[near][f"{side}_{h}"].to_numpy(float)
            if x.size < 3 or np.std(x) == 0:
                continue
            b = np.polyfit(x, y, 1)
            yh = np.polyval(b, x)
            se = np.sqrt(((y - yh) ** 2).sum() / max(x.size - 2, 1)
                         / max(((x - x.mean()) ** 2).sum(), 1e-18))
            tt = b[0] / se if se > 0 else float("nan")
            print(f"    h={h:>3}: 斜率 = {b[0]:+.3f} 价格单位/ATR，"
                  f"t = {tt:+.2f}"
                  + ("  (正=距离越远越好，支持闸门)" if b[0] > 0 else
                     "  (负=距离越远越差，反对闸门)"))
        print("    判读：只有当斜率显著为正时，闸门「越贴近越糟」的前提才成立。")

    # ---- 按日分块自助法：重叠窗口 + 同日聚类的诚实显著性 ----
    print("\n" + "=" * 78)
    print("9. 按交易日分块自助法（block bootstrap，处理重叠窗口与同日聚类）")
    print("=" * 78)
    days_i = pd.to_datetime(df["time"]).dt.date.to_numpy()
    smp_days = days_i[smp["i"].to_numpy()]
    uniq = pd.unique(smp_days)
    print(f"  样本覆盖 {len(uniq)} 个交易日；每次迭代按日有放回重抽")
    rng = np.random.default_rng(20260929)
    B = 400
    idx_by_day = {d: np.flatnonzero(smp_days == d) for d in uniq}
    print("  方向 | 周期 |   均值差 |  95% 自助区间 | 自助P(差>=0) | 判定")
    for side, name in (("L", "做多"), ("S", "做空")):
        near = smp[f"{side}_near"].to_numpy()
        for h in HORIZONS:
            y = smp[f"{side}_{h}"].to_numpy(float)
            obs = y[near].mean() - y[~near].mean()
            boot = np.empty(B)
            for b_i in range(B):
                pick = rng.choice(len(uniq), size=len(uniq), replace=True)
                sel = np.concatenate([idx_by_day[uniq[j]] for j in pick])
                yn, mn = y[sel], near[sel]
                if mn.all() or (~mn).all():
                    boot[b_i] = np.nan
                    continue
                boot[b_i] = yn[mn].mean() - yn[~mn].mean()
            boot = boot[np.isfinite(boot)]
            lo, hi = np.percentile(boot, [2.5, 97.5])
            p_pos = float((boot >= 0).mean())
            if lo > 0:
                v = "紧贴显著更好(反对闸门)"
            elif hi < 0:
                v = "紧贴显著更差(支持闸门)"
            else:
                v = "无显著差异"
            print(f"  {name} | {h:>4} | {fmt(obs)} | [{fmt(lo, 7, 3)},"
                  f"{fmt(hi, 7, 3)}] | {p_pos:>12.3f} | {v}")

    # ---- 结论 ----
    print("\n" + "=" * 78)
    print("10. 结论（净成本口径，k=%d）" % k_main)
    print("=" * 78)
    print(f"  成本 {COST} 价格单位 = {COST * 1000:.0f} 点，"
          f"对紧贴组与对照组同额扣减，故**不改变**两组均值差。")
    print("  判定标准：净均值差（紧贴 - 对照）显著为负 -> 支持闸门；")
    print("            无显著差异或为正 -> 不支持闸门。")
    for side, name in (("L", "做多 LONG"), ("S", "做空 SHORT")):
        print(f"\n  {name}：")
        for h in HORIZONS:
            a = smp[smp[f"{side}_near"]][f"{side}_{h}"].to_numpy(float)
            b = smp[~smp[f"{side}_near"]][f"{side}_{h}"].to_numpy(float)
            d_ = a.mean() - b.mean()
            tt = welch(a, b)
            s = stats(a, lag_map[h])
            sn = stats(a - COST, lag_map[h])
            print(f"    h={h:>3}: 紧贴毛均值 {s['mean']:+.3f} "
                  f"(净 {sn['mean']:+.3f})，对照毛均值 {b.mean():+.3f}，"
                  f"差值 {d_:+.3f}（{d_ * 1000:+.0f} 点），t={tt:+.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
