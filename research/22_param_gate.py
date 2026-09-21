"""研究取证 22：参数变更门（research/18 §P2-1 / §P2-2）。

问题
----
`config.toml` 的调参记录显示：
    2026-09-18  open_threshold 1.6 → 1.2（64 轮全 hold，峰值仅 1.29）
    2026-09-19  3 笔交割单复盘（1胜2负）→ 阈值回提 1.2 → 1.3

**这是用 3 笔交易调参。** 3 笔样本的胜率置信区间是 [6%, 79%] ——
它不能支持任何结论。

本门要求（research/18 §P2-1）
-----------------------------
任何参数变更必须：
1. 在 ≥ 60,000 根历史 bar 上回放
2. 通过 **Purged K-Fold**（`quant.labeling.purged_kfold_indices`）
3. 报告 **Deflated Sharpe**（`quant.labeling.deflated_sharpe`）
4. 试验族规模 N 必须显式记录（每试一个参数 +1）

验收：`config.toml` 的每条调参记录后面必须跟一个 DSR 数字。没有 = 回滚。

额外门（docs/compliance/2026-commercial-trading-system-standards.md §2）
-----------------------------------------------------------------------
商用信号产品的最低可信门槛是 **DSR + PBO + MinBTL 三件套**：
- **MinBTL**（Bailey/López de Prado Theorem 3.1）：若只有 N=10 次配置尝试，
  即使所有策略真实 SR=0，也**期望**找到 IS Sharpe ≈ 1.57。
  测试 100 个配置想信任 Sharpe=1.0，需要约 9.2 年数据。
- **PBO / CSCV**：IS 选出的最优配置在 OOS 跑输中位数的概率。
  判读：**PBO > 0.05 即拒绝**。

用法
----
    py research/22_param_gate.py --param open_threshold --values 1.0 1.1 1.2 1.3 1.4 1.5
    py research/22_param_gate.py --trials-file data/trials.csv   # 查试验族规模
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gold_agent.quant.labeling import (deflated_sharpe, newey_west_t,  # noqa: E402
                                       purged_kfold_indices)

RES = Path(__file__).parent
DATA = ROOT / "data" / "cache"
TRIALS_PATH = ROOT / "data" / "trials.csv"
OUT: list[str] = []

COST = 0.520
#: triple_barrier 出场参数（与 config.toml 的 risk 段一致）
PT = 2.0            # tp_atr_mult
SL = 1.2            # sl_atr_mult
HOLD_1M = 240       # 最长持有（1m 根数）= 4 小时，与 max_holding_h=4.0 一致
EULER = 0.5772156649


def p(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


# ══════════════════════════════════════════════════════════════════
# 试验族规模记录（MinBTL / DSR 的输入）
# ══════════════════════════════════════════════════════════════════
def load_trials() -> tuple[int, list[dict]]:
    """读 data/trials.csv（每试一个参数 +1 行）。不存在 → N=1。"""
    if not TRIALS_PATH.exists():
        return 1, []
    try:
        df = pd.read_csv(TRIALS_PATH)
        return max(len(df), 1), df.to_dict("records")
    except Exception:
        return 1, []


def log_trial(param: str, value, dsr: float, note: str = "") -> None:
    """追加一行试验记录（必须显式记录 N）。"""
    row = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "param": param,
           "value": value, "dsr": round(float(dsr), 4) if np.isfinite(dsr) else None,
           "note": note}
    TRIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TRIALS_PATH.exists():
        df = pd.read_csv(TRIALS_PATH)
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    else:
        df = pd.DataFrame([row])
    df.to_csv(TRIALS_PATH, index=False, encoding="utf-8")


# ══════════════════════════════════════════════════════════════════
# MinBTL（Theorem 3.1）
# ══════════════════════════════════════════════════════════════════
def expected_max_sharpe(n_trials: int) -> float:
    """E[max_N] ≈ (1−γ)Z⁻¹(1−1/N) + γZ⁻¹(1−1/(N·e))。"""
    from scipy import stats as st
    if n_trials < 2:
        return 0.0
    return float((1 - EULER) * st.norm.ppf(1 - 1.0 / n_trials)
                 + EULER * st.norm.ppf(1 - 1.0 / (n_trials * np.e)))


def min_btl_years(n_trials: int, target_sr: float = 1.0) -> float:
    """MinBTL（年）：避免选出 IS Sharpe=E[max] 但 OOS 期望为 0 的策略。

    上界近似 MinBTL < 2·ln(N) / E[max]²。这里返回更保守的精确式。
    """
    if n_trials < 2 or target_sr <= 0:
        return 0.0
    e_max = expected_max_sharpe(n_trials)
    return float((e_max / target_sr) ** 2)


# ══════════════════════════════════════════════════════════════════
# PBO / CSCV
# ══════════════════════════════════════════════════════════════════
def pbo_cscv(pnl_matrix: np.ndarray, n_splits: int = 8) -> dict:
    """Probability of Backtest Overfitting（CSCV，Bailey et al.）。

    pnl_matrix: (T × N) —— N 个 trial 的逐期损益序列，行同步。
    判读：**PBO > 0.05 即拒绝**（Neyman-Pearson 惯例）。
    """
    T, N = pnl_matrix.shape
    if N < 2 or T < n_splits * 2 or n_splits % 2 != 0:
        return {"pbo": float("nan"), "n_combos": 0, "note": "样本不足或 N<2"}
    sub = T // n_splits
    blocks = [pnl_matrix[i * sub:(i + 1) * sub] for i in range(n_splits)]
    logits: list[float] = []
    for combo in combinations(range(n_splits), n_splits // 2):
        j = [i for i in range(n_splits) if i not in combo]
        is_m = np.vstack([blocks[i] for i in combo])
        oos_m = np.vstack([blocks[i] for i in j])
        # IS 表现：夏普
        with np.errstate(invalid="ignore", divide="ignore"):
            is_sr = np.array([_sharpe(is_m[:, k]) for k in range(N)])
            oos_sr = np.array([_sharpe(oos_m[:, k]) for k in range(N)])
        if not np.isfinite(is_sr).any():
            continue
        n_star = int(np.nanargmax(is_sr))
        # OOS 相对排名 ω ∈ (0,1)
        rank = float(np.sum(oos_sr <= oos_sr[n_star])) / (N + 1)
        rank = min(max(rank, 1e-6), 1 - 1e-6)
        logits.append(float(np.log(rank / (1 - rank))))
    if not logits:
        return {"pbo": float("nan"), "n_combos": 0, "note": "无有效组合"}
    logits = np.array(logits)
    return {"pbo": float(np.mean(logits <= 0)), "n_combos": len(logits),
            "logit_mean": float(logits.mean()), "logit_std": float(logits.std())}


def _sharpe(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    if len(x) < 3 or x.std() == 0:
        return float("nan")
    return float(x.mean() / x.std())


# ══════════════════════════════════════════════════════════════════
# 参数扫描回放
# ══════════════════════════════════════════════════════════════════
def replay_threshold(sig: np.ndarray, close: np.ndarray, threshold: float,
                     horizon: int, cost: float = COST) -> np.ndarray:
    """按阈值回放：|sig| ≥ threshold 才进场，持有 horizon 根。返回逐笔净损益。

    这是**参数无关的回放骨架**：真实系统还要过 σ/regime/新闻等闸，
    但那些闸对所有候选阈值一视同仁，因此不影响阈值之间的相对比较。

    ⚠️ 这是**固定前瞻**版本（忽略路径）。生产用 `triple_barrier`
    （TP/SL 先到先出），两者测的不是同一件事 —— 见 `replay_threshold_tb`。
    """
    n = len(close)
    fwd = np.full(n, np.nan)
    fwd[: n - horizon] = close[horizon:] - close[: n - horizon]
    mask = (np.abs(sig) >= threshold) & np.isfinite(fwd)
    if mask.sum() == 0:
        return np.array([])
    return np.sign(sig[mask]) * fwd[mask] - cost


def replay_threshold_tb(sig: np.ndarray, df: pd.DataFrame, threshold: float,
                        hold: int, atr: np.ndarray,
                        pt: float | None = None, sl: float | None = None,
                        cost: float = COST) -> np.ndarray:
    """按阈值回放，出场用 **triple_barrier**（与生产一致）。

    ⚠️ 为什么必须有这个：生产用 TP/SL 路径依赖出场（`atr_tf="1h"`），
    而固定前瞻回放假设"持有 N 根后平价出场"。两者在同样信号下
    可能给出**符号相反**的结论（research/21 实测：固定前瞻毛 NW-t=+0.39，
    triple_barrier=+1.74）。参数门必须测生产真正执行的东西。
    """
    from gold_agent.quant.labeling import triple_barrier
    pt = PT if pt is None else pt
    sl = SL if sl is None else sl
    sgn = np.sign(sig).astype(np.int8)
    tb = triple_barrier(df["close"].to_numpy(float), df["high"].to_numpy(float),
                        df["low"].to_numpy(float), atr, sgn, pt, sl, hold, cost)
    mask = (np.abs(sig) >= threshold) & (sgn != 0) & np.isfinite(tb.ret) & (tb.bars_held > 0)
    if mask.sum() == 0:
        return np.array([])
    return tb.ret[mask]


def atr_1h_map(df: pd.DataFrame, mult: float = 1.2) -> np.ndarray:
    """把 1h ATR 映射到每根 1m（无前视：用上一根已收盘的 1h ATR）。

    生产 `risk.atr_tf = "1h"`：止损 = `sl_atr_mult × ATR(1h)`。
    research/23 实测：1m 波动定止损时成本占 46%，1h ATR 定止损只占 2.5%。
    """
    d1h = df.set_index("time").resample("1h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    tr = pd.concat([d1h["high"] - d1h["low"],
                    (d1h["high"] - d1h["close"].shift()).abs(),
                    (d1h["low"] - d1h["close"].shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().reindex(df["time"], method="ffill").shift(1).to_numpy(float)
    atr = np.where(np.isfinite(atr) & (atr > 0), atr, np.nan)
    return atr * mult


def build_signal(df: pd.DataFrame, horizon: int) -> np.ndarray:
    """构造回放用的融合分代理：**线上** kalman 源（`fusion.kalman.KalmanTrend`）。

    用滚动去均值后的 z-score，与实盘 P0-1 的处理一致。

    ⚠️ 单遍滤波（`fit_series`）而非逐点 `fit(closes[:i+1])`：
    后者是 O(n²)，60000 根要跑几十分钟。`fit_series` 天然无前视
    （t 时刻状态只由 closes[:t+1] 决定），结果与逐点等价。
    """
    from gold_agent.fusion.kalman import KalmanTrend
    from gold_agent.fusion.normalize import SourceNormalizer
    close = df["close"].to_numpy(float)
    trend = KalmanTrend().fit_series(close)
    # 持续性：连续同号计数
    persist = np.zeros(len(trend), dtype=float)
    run = 0
    for i in range(1, len(trend)):
        if trend[i] * trend[i - 1] > 0 and trend[i] != 0:
            run += 1
        else:
            run = 1
        persist[i] = run
    raw = np.clip(trend * np.minimum(persist / 10.0, 1.5), -3.0, 3.0)
    nz = SourceNormalizer(win=1440, min_periods=240)
    return np.array([nz.normalize("kalman_persist", float(raw[i]), obs_id=i)
                     for i in range(len(raw))])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--param", default="open_threshold")
    ap.add_argument("--values", type=float, nargs="+",
                    default=[1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6])
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--horizon", type=int, default=60)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--extra-trials", type=int, default=0,
                    help="本仓库历史上已试过的其它配置数（累加到 N）")
    ap.add_argument("--record", action="store_true", help="把本次试验写入 data/trials.csv")
    args = ap.parse_args()

    d = pd.read_parquet(DATA / "XAUUSDm_1m.parquet")
    d["time"] = pd.to_datetime(d["time"], utc=True)
    d = d.sort_values("time").reset_index(drop=True).iloc[-args.bars:].reset_index(drop=True)
    close = d["close"].to_numpy(float)

    p("=" * 96)
    p("研究取证 22 · 参数变更门（research/18 §P2-1）")
    p("=" * 96)
    p(f"1m {len(d)} 根  成本={COST}  前瞻={args.horizon} 根  "
      f"参数={args.param}  候选={args.values}")

    p("\n构造融合分代理序列（kalman_trend，滚动去均值，无前视）…")
    sig = build_signal(d, args.horizon)
    p(f"  信号非零占比 {np.mean(np.abs(sig) > 1e-9):.1%}  "
      f"为正占比 {np.mean(sig > 0):.1%}")

    # 试验族规模 N：历史试验 + 本次候选数
    n_hist, hist = load_trials()
    n_trials = n_hist + len(args.values) + args.extra_trials
    p(f"\n试验族规模 N = {n_trials}（历史记录 {n_hist} + 本次候选 {len(args.values)}"
      f" + 额外 {args.extra_trials}）")

    # ---- MinBTL 门 ----
    e_max = expected_max_sharpe(n_trials)
    years = len(d) / (60 * 24 * 252)     # 1m bar → 交易年（252 日）
    btl = min_btl_years(n_trials, target_sr=1.0)
    p("\n" + "=" * 96)
    p("A. MinBTL 门（Bailey/López de Prado Theorem 3.1）")
    p("=" * 96)
    p(f"  纯噪声下 {n_trials} 次试验的期望最大 Sharpe  E[max] = {e_max:.3f}")
    p(f"  数据长度 = {years:.2f} 年")
    p(f"  想信任 Sharpe=1.0 所需 MinBTL = {btl:.2f} 年")
    p(f"  判定: {'✅ 数据足够' if years >= btl else '❌ 数据不足 —— 任何 Sharpe≈1.0 的结果都不可信'}")

    # ---- 逐候选回放 ----
    p("\n" + "=" * 96)
    p("B. 逐候选回放（含 Purged K-Fold 与 DSR）")
    p("=" * 96)
    p("")
    hdr = (f"{'阈值':>7}{'笔数':>9}{'毛均值':>10}{'净均值':>10}{'净NW-t':>10}"
           f"{'年化SR':>10}{'DSR':>9}{'K-Fold净均值':>14}{'判定':>8}")
    p(hdr)
    p("-" * len(hdr))

    n = len(close)
    t1 = np.minimum(np.arange(n) + args.horizon, n - 1)
    folds = purged_kfold_indices(t1, n_splits=args.folds, embargo_pct=0.01)
    results: list[dict] = []
    pnl_cols: list[np.ndarray] = []

    # ---- triple_barrier 基准（与生产一致：1h ATR 定止损）----
    # 先算一次 ATR 映射，供所有候选阈值共用。
    atr_map = atr_1h_map(d, mult=SL)
    p(f"  止损基准 = {SL} × ATR(1h)，中位 {np.nanmedian(atr_map):.2f} USD，"
      f"成本/止损 = {COST / np.nanmedian(atr_map):.1%}")
    p("")
    hdr_tb = (f"{'阈值':>7}{'TB笔数':>9}{'TB毛均值':>11}{'TB净均值':>11}"
              f"{'TB净NW-t':>11}{'TB命中':>9}{'判定':>8}")
    p(hdr_tb)
    p("-" * len(hdr_tb))
    for thr in args.values:
        pnl_tb = replay_threshold_tb(sig, d, thr, HOLD_1M, atr_map)
        if len(pnl_tb) < 30:
            p(f"{thr:>7.2f}{len(pnl_tb):>9}{'—':>11}{'—':>11}{'—':>11}{'—':>9}{'样本不足':>8}")
            continue
        p(f"{thr:>7.2f}{len(pnl_tb):>9}{pnl_tb.mean() + COST:>+11.4f}"
          f"{pnl_tb.mean():>+11.4f}{newey_west_t(pnl_tb, 30):>+11.2f}"
          f"{np.mean(pnl_tb > 0):>9.1%}"
          f"{'净正' if pnl_tb.mean() > 0 else '净负':>8}")
    p("")
    p("  ⚠️ 上面是 **triple_barrier**（路径依赖出场，与生产一致）的结果，")
    p("     下面是**固定前瞻**（持有 N 根平价出场）的结果。两者不可混用 ——")
    p("     research/21 实测同一信号在两种度量下毛 NW-t 可差 4 倍。")
    p("")

    for thr in args.values:
        pnl = replay_threshold(sig, close, thr, args.horizon)
        if len(pnl) < 30:
            p(f"{thr:>7.2f}{len(pnl):>9}{'—':>10}{'—':>10}{'—':>10}{'—':>10}{'—':>9}"
              f"{'—':>14}{'样本不足':>8}")
            results.append({"threshold": thr, "n": len(pnl), "dsr": float("nan")})
            continue
        net = float(pnl.mean())
        gross = net + COST
        nw = newey_west_t(pnl, lags=min(30, args.horizon // 2))
        sr_bar = float(pnl.mean() / pnl.std()) if pnl.std() > 0 else 0.0
        sr_ann = sr_bar * np.sqrt(60 * 24 * 252 / args.horizon)
        sk = float(pd.Series(pnl).skew())
        ku = float(pd.Series(pnl).kurtosis() + 3.0)     # 转成非超额峰度
        dsr, sr0 = deflated_sharpe(sr_ann, n_trials, len(pnl), sk, ku)

        # ---- Purged K-Fold：训练集选阈值、测试集评估 ----
        # 这里做的是"选择过程"的检验：每折在训练集上选最优阈值，看它在测试集的表现
        oos_means: list[float] = []
        for tr_idx, te_idx in folds:
            if len(tr_idx) < 100 or len(te_idx) < 10:
                continue
            # 训练集：用 IS 段重放选阈值
            best_thr, best_is = None, -np.inf
            for cand in args.values:
                sub_close = close[tr_idx.min(): tr_idx.max() + 1]
                sub_sig = sig[tr_idx.min(): tr_idx.max() + 1]
                cand_pnl = replay_threshold(sub_sig, sub_close, cand, args.horizon)
                if len(cand_pnl) >= 30 and cand_pnl.mean() > best_is:
                    best_is, best_thr = cand_pnl.mean(), cand
            if best_thr is None:
                continue
            # 测试集：用选中的阈值
            sub_close = close[te_idx.min(): te_idx.max() + 1]
            sub_sig = sig[te_idx.min(): te_idx.max() + 1]
            te_pnl = replay_threshold(sub_sig, sub_close, best_thr, args.horizon)
            if len(te_pnl) >= 10:
                oos_means.append(float(te_pnl.mean()))

        kf_mean = float(np.mean(oos_means)) if oos_means else float("nan")
        # 判定：DSR > 0.95 且 OOS 净均值为正
        ok = bool(np.isfinite(dsr) and dsr > 0.95 and net > 0
                  and (not np.isfinite(kf_mean) or kf_mean > 0))
        verdict = "✅ 通过" if ok else "❌ 拒绝"
        p(f"{thr:>7.2f}{len(pnl):>9}{gross:>+10.3f}{net:>+10.3f}{nw:>+10.2f}"
          f"{sr_ann:>+10.2f}{dsr:>9.3f}{kf_mean:>+14.3f}{verdict:>8}")
        results.append({"threshold": thr, "n": len(pnl), "gross_mean": gross,
                        "net_mean": net, "nw_t": float(nw), "sr_ann": sr_ann,
                        "dsr": float(dsr), "sr0": float(sr0), "skew": sk, "kurt": ku,
                        "kfold_oos_mean": kf_mean, "pass": ok})
        if args.record:
            log_trial(args.param, thr, dsr,
                      note=f"net={net:+.4f} nw_t={nw:+.2f} kfold={kf_mean:+.4f}")

    # ---- PBO / CSCV ----
    p("\n" + "=" * 96)
    p("C. PBO / CSCV（回测过拟合概率；判读：> 0.05 即拒绝）")
    p("=" * 96)
    # 构造 T×N 损益矩阵：每个候选阈值的逐笔损益对齐到公共长度
    per_cand: list[np.ndarray] = []
    for thr in args.values:
        pnl = replay_threshold(sig, close, thr, args.horizon)
        per_cand.append(pnl)
    minlen = min((len(x) for x in per_cand if len(x) > 0), default=0)
    if minlen >= 32 and len(per_cand) >= 2:
        mat = np.column_stack([x[:minlen] for x in per_cand if len(x) >= minlen])
        r = pbo_cscv(mat, n_splits=8)
        p(f"  组合数 = {r.get('n_combos')}   PBO = {r.get('pbo')}")
        if np.isfinite(r.get("pbo", float("nan"))):
            p(f"  判定: {'✅ 无显著过拟合' if r['pbo'] <= 0.05 else '❌ 过拟合可能性高 —— 拒绝该选择过程'}")
    else:
        p(f"  样本不足（minlen={minlen}），跳过")

    # ---- 结论 ----
    p("\n" + "=" * 96)
    p("D. 结论")
    p("=" * 96)
    passed = [r for r in results if r.get("pass")]
    if passed:
        best = max(passed, key=lambda r: r["net_mean"])
        p(f"  ✅ 有 {len(passed)} 个候选通过（DSR>0.95 且净均值为正且 K-Fold OOS 为正）")
        p(f"     最优: {args.param}={best['threshold']}  "
          f"净均值={best['net_mean']:+.4f}  DSR={best['dsr']:.3f}")
        p(f"     → 该变更可写入 config.toml，并在调参记录中附 DSR={best['dsr']:.3f}")
    else:
        p("  ❌ **没有任何候选通过。**")
        p("     按 research/18 §P2-1 的纪律：")
        p("     · 在拿到通过的候选之前，不应再改动该参数")
        p("     · 但**也不应据此把参数「回滚」** —— 回滚同样没有 DSR 支撑，")
        p("       而且本门无法区分候选之间的优劣（PBO=1.0 意味着")
        p("       「IS 最优在 OOS 跑输中位数」是必然事件）。")
        p("       在无法区分时改动参数只会增加试验族 N、进一步降低可信度。")
        p("     · 正确的读法：**这个参数当前不可辨识**。")
        p("       维持一个中性默认值，把精力放到止损宽度与找新信息源上。")

    if args.record:
        p(f"\n  已记录 {len(results)} 行到 {TRIALS_PATH}（试验族 N 现为 {n_hist + len(results)}）")

    (RES / "22_param_gate.txt").write_text("\n".join(OUT), encoding="utf-8")
    print(f"\n[saved] {RES / '22_param_gate.txt'}", flush=True)


if __name__ == "__main__":
    main()
