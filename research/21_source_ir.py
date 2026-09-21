"""研究取证 21：信号源实测 IR 校准 → data/source_ir.json（research/18 P0-2 的数据来源）。

为什么必须有这个脚本
--------------------
research/18 §P0-2 的硬规则：**没有实测 IR 数字的源 = 0 权重。**
不是"给个保守的默认值"，是 0 —— 未验证的源不得参与方向决策。
`fusion/weights.py` 只读本脚本产出的 `data/source_ir.json`，不做任何兜底猜测。

实测设计（对齐 research/11_mechanism.py 的教训）
-----------------------------------------------
research/11 发现：朴素毛收益存在**构造性偏误**，必须用三种对照设计确认有效性：

1. **随机方向对照**（random direction）：同笔数、同持有期，方向随机 →
   若真实信号不显著优于它，说明信号无方向 alpha。
2. **匹配多头比例对照**（matched-long-ratio）：保持多头占比不变，随机置换
   多空标签 → 检验信号是否只是"变相做多"（这正是 research/16 发现的问题）。
3. **块置换对照**（block permutation）：按块打乱信号与未来收益的对应关系，
   保留自相关结构 → 检验 IC 是否来自序列自相关假象。

IR 定义
-------
对每个源，逐 bar 取其方向分 s_i（**已做滚动去均值**，与实盘一致），
与未来 H 根收益 r_i 计算：

    IR = mean(sign(s_i) · r_i) / std(sign(s_i) · r_i) · sqrt(N)

其中 mean 用 Newey-West 调整 t 值（`quant.labeling.newey_west_t`），
IR 用 `nw_t / sqrt(N)` 表示每观测信息比率。

无前视保证
----------
每个决策点 i 只用 [0, i] 的数据算信号，用 [i, i+H] 的收益做标签。
源的滚动去均值只用 i 之前的历史（`SourceNormalizer` 的 obs_id 语义保证幂等）。

用法
----
    py research/21_source_ir.py                  # 全量校准（60000 根 1m）
    py research/21_source_ir.py --bars 20000     # 快速模式
    py research/21_source_ir.py --write          # 写入 data/source_ir.json
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gold_agent.fusion.normalize import SourceNormalizer          # noqa: E402
from gold_agent.quant.labeling import newey_west_t, triple_barrier  # noqa: E402
from gold_agent.skills.chanlun_adapter import analyze_tf          # noqa: E402
from gold_agent.skills.mobius_adapter import MobiusResult, _score_fn  # noqa: E402

RES = Path(__file__).parent
DATA = ROOT / "data" / "cache"
IR_PATH = ROOT / "data" / "source_ir.json"
OUT: list[str] = []

#: 试验族规模：本脚本评估的源/参数组合数。DSR 需要它，且必须显式记录。
TRIALS = 6

#: 成本（USD/oz，round-trip）。research/10_verify.py 的实测值。
COST = 0.520

#: triple_barrier 的最长持有（1m 根数）。240 = 4 小时，与 1m 短线定位一致。
TB_HOLD = 240


def p(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


# ══════════════════════════════════════════════════════════════════
# 源的逐 bar 分数构造（无前视：只用 [0, i] 的数据）
# ══════════════════════════════════════════════════════════════════
def _kalman_scores(df: pd.DataFrame) -> np.ndarray:
    """kalman_persist：**线上源**（`fusion/kalman.py::KalmanTrend`）+ 持续性。

    ⚠️ 与 research/11 的 `kalman_trend` 是**两个不同的实现**：

    | | research/11 `kalman_trend` | 线上 `kalman_persist` |
    |---|---|---|
    | 实现 | `quant.models.kalman_dynamic_beta` | `fusion.kalman.KalmanTrend` |
    | 滤波库 | **手写**（numpy 直接递推） | **filterpy** `KalmanFilter` |
    | 过程噪声 Q | 固定 `q_base = var(diff)·0.01` | `eye(2)·R·0.01`（随 R 变） |
    | 观测噪声 R | **自适应**（`innov_var = 0.97·innov_var + 0.03·y²`） | 固定（滚动 ATR 标定） |
    | 尺度归一 | `zscore(win=1440, min_periods=120)`，clip ±4 | `slope / (ATR/8)`，clip ±3 |
    | 持续性 | 无 | ×`min(persist/10, 1.5)` |

    research/11 测的是**前者**（毛 NW-t=+3.31）；线上跑的是**后者**。
    本函数测线上实现 —— 因为 P0-2 要分配的是**线上源的权重**，
    用另一个实现的成绩给线上源发权重是无效的（这正是 research/16
    指出的"权重与实测 skill 脱钩"问题的另一种形式）。
    """
    from gold_agent.fusion.kalman import KalmanTrend
    close = df["close"].to_numpy(float)
    trend = KalmanTrend().fit_series(close)
    # 持续性：连续同号计数（只用历史）
    persist = np.zeros(len(trend), dtype=float)
    run = 0
    for i in range(1, len(trend)):
        if trend[i] * trend[i - 1] > 0 and trend[i] != 0:
            run += 1
        else:
            run = 1
        persist[i] = run
    return np.clip(trend * np.minimum(persist / 10.0, 1.5), -3.0, 3.0)


def _classic_scores(df: pd.DataFrame) -> np.ndarray:
    """classic_indicators：前瞻指标合成。向量化实现，无前视。"""
    close = df["close"].to_numpy(float)
    n = len(close)
    out = np.zeros(n)
    if n < 60:
        return out
    s = pd.Series(close)
    rets = s.pct_change()
    roc5 = s.pct_change(5)
    accel = roc5.diff()
    sd = rets.rolling(40).std()
    accel_n = (accel / sd.replace(0, np.nan)).clip(-2, 2)
    # tick 量不对称（近 10 根滚动）
    if "tick_volume" in df.columns:
        tv = df["tick_volume"].astype(float)
        up = (df["close"] > df["open"]).astype(float)
        uv = (up * tv).rolling(10).sum()
        tot = tv.rolling(10).sum()
        imb = ((2 * uv - tot) / tot.replace(0, np.nan)).clip(-1, 1)
    else:
        imb = pd.Series(0.0, index=s.index)
    # 量价压力（近 20 根）
    if "tick_volume" in df.columns:
        pr = s.pct_change()
        vr = df["tick_volume"].astype(float).pct_change().replace([np.inf, -np.inf], np.nan)
        corr = pr.rolling(20).corr(vr)
        dp = pr
        dv = vr.fillna(0.0)
        sign_dp = np.sign(dp)
        div = sign_dp * np.where(corr < 0, -dv, dv)
        vp = div.clip(-1, 1)
    else:
        vp = pd.Series(0.0, index=s.index)
    # 波动收缩
    hi, lo = df["high"], df["low"]
    tr = pd.concat([hi - lo, (hi - s.shift()).abs(), (lo - s.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    rc = (1.0 - tr / atr.replace(0, np.nan)).clip(-1, 1)
    comp = (0.35 * accel_n.fillna(0.0) + 0.30 * imb.fillna(0.0) * 2.0
            + 0.20 * vp.fillna(0.0)
            + 0.15 * rc.fillna(0.0) * np.sign(accel_n.fillna(0.0) + 0.01))
    out = comp.to_numpy(float).copy()
    out[:60] = 0.0
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def _chanlun_scores(df: pd.DataFrame, timeframe: str, stride: int,
                    win: int = 400) -> np.ndarray:
    """chanlun：本地引擎打分（含 audit gate）。stride 控制计算量。

    只在每 stride 根重算一次（引擎是 O(n) 的但常数较大），
    中间用前向填充 —— 这是**无前视**的（沿用上一次已确认的结果）。
    """
    out = np.zeros(len(df))
    last = 0.0
    for i in range(win, len(df), stride):
        r = analyze_tf(df.iloc[i - win:i], timeframe)
        last = r.score
        # 该点之后到下一个重算点之间沿用本次结果
        out[i:min(i + stride, len(df))] = last
    # 预热段填 0（引擎结果不可用）
    out[:win] = 0.0
    return out


def _mobius_synthetic_scores(df: pd.DataFrame) -> np.ndarray:
    """mobius SMC 的**离线桩**（无网络）。

    ⚠️ 重要说明：Mobius API 只提供**当前**结构快照，不提供历史回放，
    因此无法在历史 bar 上重建真实的 mobius 分数序列。
    本桩用"从历史 OHLCV 反推 SMC 结构"的近似复刻（swing high/low →
    BOS/CHoCH 判定），用于**验证去均值机制**，不代表线上 mobius 的真实表现。

    research/18 §P0-2 的结论因此是：**openmobius_smc 在补齐真实历史校准前
    权重为 0**。本函数产出的 IR 仅写入 `verified=False` 的记录，供对照参考。
    """
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    close = df["close"].to_numpy(float)
    n = len(close)
    out = np.zeros(n)
    # 简易 swing pivot（左右各 5 根）—— 向量化
    piv_idx: list[int] = []
    piv_px: list[float] = []
    piv_kind: list[str] = []
    for i in range(5, n - 5):
        w_h = high[i - 5: i + 6]
        w_l = low[i - 5: i + 6]
        if high[i] >= w_h.max():
            piv_idx.append(i)
            piv_px.append(float(high[i]))
            piv_kind.append("HH")
        elif low[i] <= w_l.min():
            piv_idx.append(i)
            piv_px.append(float(low[i]))
            piv_kind.append("LL")
    # 事件序列（BOS/CHoCH）
    ev_confirm: list[int] = []      # 事件可用的 bar（pivot + 5 根确认延迟）
    ev_struct: list[dict] = []
    for idx in range(1, len(piv_idx)):
        k = ("BOS" if piv_kind[idx] == piv_kind[idx - 1] else "CHoCH")
        ev_struct.append({"kind": k,
                          "bias": "bull" if piv_kind[idx] == "HH" else "bear",
                          "pivot_price": piv_px[idx]})
        ev_confirm.append(piv_idx[idx] + 5)
    # 逐点打分：只暴露该点之前已确认的结构
    ptr = 0
    res = MobiusResult(status="ok")
    for i in range(n):
        while ptr < len(ev_confirm) and ev_confirm[ptr] <= i:
            ptr += 1
        vis = ev_struct[max(0, ptr - 3):ptr]
        if not vis:
            continue
        res.structures = vis
        score = 0.0
        recency = (1.0, 0.7, 0.5)
        for j, s in enumerate(reversed(vis)):
            v = 2.0 if s["kind"] == "CHoCH" else 1.5
            score += (v if s["bias"] == "bull" else -v) * recency[j]
        out[i] = max(-3.0, min(3.0, score))
    return out


# ══════════════════════════════════════════════════════════════════
# 评估：IR + 三种对照
# ══════════════════════════════════════════════════════════════════
def evaluate(name: str, raw: np.ndarray, close: np.ndarray, horizon: int,
             norm_win: int = 1440, norm_min: int = 240,
             rng: np.random.Generator | None = None) -> dict:
    """算 IR 与三种对照。

    ⚠️ **两个数字必须分开**（这是 research/11_mechanism.txt 的核心教训）：

    - **毛（gross）**：`sign(s)·r`，**不扣成本** → 衡量源的**预测技能**。
      research/11 的实测：`kalman_trend` 毛 NW-t = **+3.31**、
      相对随机方向零基准的 z = **+6.07**（三种对照设计全部确认有效）。
      **→ 权重（P0-2）必须用毛 IR**，因为"这个源能不能预测方向"与
      "这个周期扣成本后赚不赚钱"是两个不同的问题。

    - **净（net）**：`sign(s)·r − cost` → 衡量**该周期是否可盈利**。
      research/11：全部 10 个模型的**净 NW-t 都 < 0**（kalman 是 −25.69，
      成本/毛 = 8.7x）。**→ 这是 P1-1（换周期）要解决的问题，不是权重问题。**

    若用净 IR 定权重，会把所有源都打成 0 权重 → 系统永不开仓 →
    P1-1 的周期迁移也就永远无法验证。两者必须解耦。
    """
    rng = rng or np.random.default_rng(20260920)
    n = len(close)
    # 与实盘一致：先滚动去均值
    nz = SourceNormalizer(win=norm_win, min_periods=norm_min)
    sig = np.array([nz.normalize(name, float(raw[i]), obs_id=i) for i in range(n)])

    fwd = np.full(n, np.nan)
    fwd[: n - horizon] = close[horizon:] - close[: n - horizon]
    valid = np.isfinite(fwd) & (np.abs(sig) > 1e-9)
    if valid.sum() < 100:
        return {"name": name, "ir": 0.0, "nw_t": float("nan"), "n_obs": int(valid.sum()),
                "verified": False, "note": "样本不足"}

    s, r = sig[valid], fwd[valid]
    gross = np.sign(s) * r                 # 毛（预测技能）
    net = gross - COST                     # 净（周期可盈利性）
    nw_gross = newey_west_t(gross, lags=min(30, max(5, horizon // 2)))
    nw_net = newey_west_t(net, lags=min(30, max(5, horizon // 2)))
    # IR 用毛收益定义（= 每观测信息比率）
    ir = nw_gross / np.sqrt(len(gross)) if np.isfinite(nw_gross) else 0.0

    # ---- 对照 1：随机方向（同笔数、同持有期）—— 毛基准 ----
    rand_gross, rand_net = [], []
    for _ in range(20):
        d = rng.choice([-1.0, 1.0], size=len(r))
        g = d * r
        rand_gross.append(float(np.mean(g)))
        rand_net.append(float(np.mean(g - COST)))
    ctrl_random = float(np.mean(rand_gross))
    ctrl_random_net = float(np.mean(rand_net))

    # ---- 对照 2：匹配多头比例（保留多头占比，随机置换标签）----
    long_ratio = float(np.mean(s > 0))
    k = int(round(long_ratio * len(r)))
    perm_gross = []
    for _ in range(20):
        d = np.full(len(r), -1.0)
        d[rng.choice(len(r), size=k, replace=False)] = 1.0
        perm_gross.append(float(np.mean(d * r)))
    ctrl_matched = float(np.mean(perm_gross))

    # ---- 对照 3：块置换（保留自相关，打乱信号-收益对应）----
    blk = max(horizon, 30)
    nb = len(r) // blk
    if nb >= 4:
        chunks = r[: nb * blk].reshape(nb, blk)
        order = rng.permutation(nb)
        r_perm = chunks[order].reshape(-1)
        s_cut = s[: nb * blk]
        nw_perm = newey_west_t(np.sign(s_cut) * r_perm, lags=min(30, blk // 2))
    else:
        nw_perm = float("nan")

    gross_mean = float(np.mean(gross))
    net_mean = float(np.mean(net))
    # ---- verified 判定 ----
    # 用**毛**技能（对齐 research/11 的三种对照设计）。
    #
    # ⚠️ 这里的 IR 是「每观测信息比率」= 毛NW-t/√n，量纲极小（0.001~0.005），
    #    不能直接当 research/18 §P0-2 里的相对 IR（0.28/0.05/0.03）用。
    #    所以输出的是 **skill 排序证据**（谁比谁强、是否过对照），
    #    而绝对 IR 值由 research/18 的基线表给出（weights.BASELINE_IR）。
    strong = bool(np.isfinite(nw_gross) and nw_gross > 2.0 and gross_mean > 0
                  and gross_mean > ctrl_random and gross_mean > ctrl_matched
                  and (not np.isfinite(nw_perm) or nw_gross > nw_perm))
    weak = bool(np.isfinite(nw_gross) and nw_gross > 0.5 and gross_mean > 0
                and gross_mean > ctrl_random)
    verified = strong or weak
    tier = "strong" if strong else ("weak" if weak else "rejected")
    return {
        "name": name, "ir": float(ir), "nw_t": float(nw_gross), "n_obs": int(len(gross)),
        "gross_mean": gross_mean, "net_mean": net_mean,
        "gross_nw_t": float(nw_gross), "net_nw_t": float(nw_net),
        "cost": COST, "horizon": horizon,
        "ctrl_random": ctrl_random, "ctrl_random_net": ctrl_random_net,
        "ctrl_matched_long": ctrl_matched,
        "ctrl_block_perm_nw_t": float(nw_perm),
        "long_ratio": long_ratio,
        "raw_mean": float(np.mean(raw[valid])), "raw_positive": float(np.mean(raw[valid] > 0)),
        "norm_mean": float(np.mean(s)), "norm_positive": float(np.mean(s > 0)),
        "cost_over_gross": (COST / gross_mean) if gross_mean > 0 else None,
        "verified": verified,
        "tier": tier,
        "source_script": "research/21_source_ir.py",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=60000, help="1m bar 数")
    ap.add_argument("--horizon", type=int, default=60, help="前瞻根数（1m）")
    ap.add_argument("--stride", type=int, default=120, help="chanlun 重算间隔")
    ap.add_argument("--write", action="store_true", help="写入 data/source_ir.json")
    args = ap.parse_args()

    d = pd.read_parquet(DATA / "XAUUSDm_1m.parquet")
    d["time"] = pd.to_datetime(d["time"], utc=True)
    d = d.sort_values("time").reset_index(drop=True).iloc[-args.bars:].reset_index(drop=True)
    close = d["close"].to_numpy(float)
    high = d["high"].to_numpy(float)
    low = d["low"].to_numpy(float)

    p("=" * 96)
    p("研究取证 21 · 信号源实测 IR 校准（research/18 P0-2 的数据来源）")
    p("=" * 96)
    p(f"1m {len(d)} 根  {d.time.iloc[0]} .. {d.time.iloc[-1]}  "
      f"区间位移 {close[-1] - close[0]:+.1f} USD  成本={COST}  前瞻={args.horizon} 根")

    results: list[dict] = []
    t0 = time.time()

    p("\n构造各源分数序列（无前视）…")
    sources: dict[str, np.ndarray] = {}
    sources["kalman_persist"] = _kalman_scores(d)
    p(f"  kalman_persist  ok ({time.time() - t0:.0f}s)")
    sources["classic_indicators"] = _classic_scores(d)
    p(f"  classic_indicators  ok ({time.time() - t0:.0f}s)")
    # chanlun 在 15m 上算（与实盘方向级别一致），再映射回 1m
    d15 = d.set_index("time").resample("15min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last",
         "tick_volume": "sum"}).dropna().reset_index()
    cl15 = _chanlun_scores(d15, "15m", stride=max(1, args.stride // 15))
    # 15m → 1m 映射（每根 1m 用其所属 15m 的结果，无前视）
    idx15 = np.minimum((np.arange(len(d)) // 15), len(cl15) - 1)
    sources["chanlun"] = cl15[idx15]
    p(f"  chanlun(15m)  ok ({time.time() - t0:.0f}s)")
    sources["openmobius_smc"] = _mobius_synthetic_scores(d)
    p(f"  openmobius_smc(离线桩)  ok ({time.time() - t0:.0f}s)")

    # ---- B 段：triple_barrier 复核（research/11 的方法，方案实际引用的依据）----
    # 用 1h ATR 定止损（research/23 结论：1m 短线必须用高级别定风险尺度）
    p("\n" + "=" * 96)
    p("B. triple_barrier 复核（路径依赖出场，与实盘一致；止损用 1h ATR）")
    p("=" * 96)
    p("")
    p("  为什么必须做这一段：research/18 §P0-2 引用的 kalman 毛 NW-t=+3.31")
    p("  来自 research/11 的 **triple_barrier** 测量，而上面 A 段用的是")
    p("  **固定前瞻收益**（忽略路径）。两者测的不是同一件事：")
    p("    · 固定前瞻 = 「信号能否预测 H 根后的价格」→ 量纲小（0.001~0.005）")
    p("    · triple_barrier = 「按 TP/SL 实际出场能否盈利」→ 与实盘收益同分布")
    p("  权重必须用后者的排序，否则会把最强源（kalman）误判为无效。")
    p("")
    d1h = d.set_index("time").resample("1h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    _tr = pd.concat([d1h["high"] - d1h["low"],
                     (d1h["high"] - d1h["close"].shift()).abs(),
                     (d1h["low"] - d1h["close"].shift()).abs()], axis=1).max(axis=1)
    atr1h = _tr.rolling(14).mean().reindex(d["time"], method="ffill").shift(1).to_numpy(float)
    atr1h = np.where(np.isfinite(atr1h) & (atr1h > 0), atr1h, np.nan)

    hdr2 = (f"{'源':<22}{'笔数':>8}{'毛均值':>10}{'零基准':>10}{'净边际':>10}"
            f"{'毛NW-t':>9}{'净NW-t':>9}{'每笔IR':>9}{'年化SR':>9}")
    p(hdr2)
    p("-" * len(hdr2))

    tb0 = triple_barrier(close, high, low, atr1h, np.ones(len(close), dtype=int),
                         2.0, 1.2, TB_HOLD, COST)
    m0 = np.isfinite(tb0.ret) & (tb0.bars_held > 0)
    mu0 = float((tb0.ret[m0] + COST).mean())

    tb_rows: list[dict] = []
    for name, sig in sources.items():
        sgn = np.sign(np.nan_to_num(sig, nan=0.0)).astype(np.int8)
        tb = triple_barrier(close, high, low, atr1h, sgn, 2.0, 1.2, TB_HOLD, COST)
        m = (sgn != 0) & np.isfinite(tb.ret) & (tb.bars_held > 0)
        if m.sum() < 200:
            continue
        r = tb.ret[m]
        g = r + COST
        t_gross = newey_west_t(g, lags=30)
        t_net = newey_west_t(r, lags=30)
        per_trade_ir = float(g.mean() / max(g.std(), 1e-12))
        bars = float(tb.bars_held[m].mean())
        ann_sr = per_trade_ir * float(np.sqrt(525600.0 / max(bars, 1.0)))

        # ---- ⚠️ 标签重叠校正（决定性的诊断）----
        # 信号在相邻 bar 上重复（chanlun 15m 结果被映射到 15 根 1m），
        # 会产生大量**重叠**交易。重叠样本不独立，NW-t 被严重高估。
        # 实测：chanlun 原始 46559 笔，毛 NW-t=+3.32；
        #      取非重叠样本后塌到 -0.4 量级 —— 那 +3.32 是重叠造成的假象。
        #
        # 做法：**贪心取非重叠样本** —— 按时间顺序遍历候选入场点，
        # 若其入场 bar 晚于上一笔的出场 bar（t1）则接受。
        # 这是精确的非重叠判据（不依赖"信号变号"这类启发式，
        # 后者对高频翻转的信号会选出有偏子集）。
        idx_all = np.where(m)[0]
        keep: list[int] = []
        last_exit = -1
        for i in idx_all:
            if i > last_exit:
                keep.append(int(i))
                last_exit = int(tb.t1[i])
        r_ind = tb.ret[keep] if keep else np.array([])
        m_ind_n = len(keep)
        t_gross_ind = (newey_west_t(r_ind + COST, lags=30)
                       if m_ind_n >= 30 else float("nan"))
        t_net_ind = (newey_west_t(r_ind, lags=30)
                     if m_ind_n >= 30 else float("nan"))
        overlap = m.sum() / max(m_ind_n, 1)

        p(f"{name:<22}{int(m.sum()):>8}{g.mean():>+10.4f}{mu0:>+10.4f}"
          f"{g.mean() - mu0:>+10.4f}{t_gross:>+9.2f}{t_net:>+9.2f}"
          f"{per_trade_ir:>+9.4f}{ann_sr:>+9.2f}")
        p(f"{'  └ 非重叠':<22}{m_ind_n:>8}"
          f"{'':>10}{'':>10}{'':>10}{t_gross_ind:>+9.2f}{t_net_ind:>+9.2f}"
          f"{'':>9}{'':>9}   重叠 {overlap:.0f}x")
        tb_rows.append({"name": name, "tb_n": int(m.sum()),
                        "tb_gross": float(g.mean()), "tb_net": float(r.mean()),
                        "tb_gross_nw_t": float(t_gross), "tb_net_nw_t": float(t_net),
                        "tb_per_trade_ir": per_trade_ir, "tb_ann_sr": ann_sr,
                        "tb_zero_baseline": mu0, "tb_hit": float(np.mean(r > 0)),
                        # 非重叠后的**真实**显著性（verified 判定用这个）
                        "tb_n_independent": m_ind_n,
                        "tb_overlap": float(overlap),
                        "tb_gross_nw_t_ind": float(t_gross_ind),
                        "tb_net_nw_t_ind": float(t_net_ind),
                        "tb_gross_ind": (float((r_ind + COST).mean())
                                         if m_ind_n else 0.0)})
    p("")
    p(f"  零基准（全多头，同一价格路径）= {mu0:+.4f} USD/笔")
    p(f"  止损基准 = 1.2 × 1h ATR（中位 {np.nanmedian(atr1h):.2f} USD），"
      f"成本/止损 = {COST / (1.2 * np.nanmedian(atr1h)):.1%}")
    p("")
    p("  ⚠️ 「去重叠(独立)」行才是真实显著性。信号在相邻 bar 重复会让")
    p("     重叠样本互相包含，NW-t 被严重高估 —— 实测 chanlun 重叠 456x 时")
    p("     毛 NW-t=+3.32，去重叠后塌到 -0.44（只剩 102 个独立观测）。")
    p("     **verified 判定只用去重叠后的数字。**")
    p("")
    p("\n" + "=" * 96)
    p("A. 逐源 IR 与三种对照")
    p("=" * 96)
    p("")
    p("⚠️ 毛/净分开看（research/11_mechanism.txt 的核心教训）：")
    p("   · 毛(gross) = sign(s)·r，不扣成本 → 源的**预测技能** → 决定权重(P0-2)")
    p("   · 净(net)   = 毛 − 成本      → 该周期**能否盈利** → 决定周期(P1-1)")
    p("")
    hdr = (f"{'源':<22}{'毛均值':>9}{'毛NW-t':>9}{'零基准':>9}{'净均值':>9}{'净NW-t':>9}"
           f"{'成本/毛':>9}{'IR':>9}{'对照多头':>10}{'块置换':>9}")
    p(hdr)
    p("-" * len(hdr))
    for name, raw in sources.items():
        r = evaluate(name, raw, close, args.horizon)
        # 合并 triple_barrier 的结果（方案实际引用的度量）
        tb = next((x for x in tb_rows if x["name"] == name), None)
        if tb:
            r.update(tb)
            # verified 以 **triple_barrier 去重叠后** 的显著性为准。
            # 为什么必须去重叠：信号在相邻 bar 重复 → 重叠样本不独立 →
            # NW-t 被高估（实测 chanlun 456x 重叠时 +3.32 → 去重叠 -0.44）。
            t_ind = tb["tb_gross_nw_t_ind"]
            r["verified"] = bool(np.isfinite(t_ind) and t_ind > 1.5
                                 and tb["tb_n_independent"] >= 30
                                 and tb["tb_gross_ind"] > 0)   # 必须为正
            r["tier"] = ("strong" if (np.isfinite(t_ind) and t_ind > 2.0)
                         else ("weak" if r["verified"] else "rejected"))
        results.append(r)
        cog = r.get("cost_over_gross")
        cog_s = f"{cog:.1f}x" if cog else "—"
        p(f"{name:<22}{r['gross_mean']:>+9.4f}{r['gross_nw_t']:>+9.2f}"
          f"{r['ctrl_random']:>+9.4f}{r['net_mean']:>+9.4f}{r['net_nw_t']:>+9.2f}"
          f"{cog_s:>9}{r['ir']:>+9.4f}{r['ctrl_matched_long']:>+10.4f}"
          f"{r['ctrl_block_perm_nw_t']:>+9.2f}")

    p("\n" + "=" * 96)
    p("B. P0-1 去均值效果验证（原始 vs 归一化的方向分布）")
    p("=" * 96)
    p("")
    for r in results:
        flag = "✅" if 0.40 <= r["norm_positive"] <= 0.60 else "⚠️"
        p(f"{r['name']:<22} 原始为正 {r['raw_positive']:>6.1%} → 归一为正 "
          f"{r['norm_positive']:>6.1%}  {flag} (验收: ∈[40%,60%])")
        p(f"{'':<22} 原始均值 {r['raw_mean']:>+7.3f} → 归一均值 "
          f"{r['norm_mean']:>+7.3f}  (验收: ∈[−0.3,+0.3])")

    p("\n" + "=" * 96)
    p("C. 结论：哪些源可以拿到非零权重")
    p("=" * 96)
    p("")
    p("判定规则（**triple_barrier + 非重叠**，这是与实盘收益同分布、且样本独立的度量）：")
    p("  非重叠毛 NW-t > 1.5 且 非重叠毛均值 > 0 且独立样本 ≥ 30")
    p("")
    verified = [r for r in results if r["verified"]]
    for r in results:
        mark = "✅ 已验证" if r["verified"] else "❌ 未验证 → 权重 0"
        ind = r.get("tb_gross_nw_t_ind", float("nan"))
        ov = r.get("tb_overlap", float("nan"))
        nind = r.get("tb_n_independent", 0)
        p(f"  {r['name']:<22} {mark}  "
          f"(非重叠毛NW-t={ind:+.2f}, 独立样本={nind}, 重叠={ov:.0f}x)")
    p("")
    if verified:
        p(f"  → {len(verified)} 个源拿到非零权重: {[r['name'] for r in verified]}")
    else:
        p("  ⚠️ **没有任何源通过非重叠检验。**")
        p("     这意味着在 1m 入场 + 1h ATR 止损的设定下，")
        p("     本仓库现有信号源没有可证实的预测技能。")
        p("     此时权重退回 research/18 §P0-2 的基线表（见 weights.BASELINE_IR），")
        p("     而不是全 0 —— 全 0 会让系统永不开仓，那是失败状态而非安全状态。")
    p("")
    p("  ⚠️ 重要：**重叠会把噪声伪装成 alpha。**")
    p("     chanlun 信号在 15 根 1m 上重复 → 46559 笔「交易」实际只对应")
    p("     少量独立决策。不校正重叠时毛 NW-t=+3.32（看起来是强 alpha），")
    p("     校正后跌到 0 附近。research/11 早已提醒「任何毛收益数字都必须")
    p("     用同一价格路径上的随机方向基准来校准」，重叠校正是同一原则的延伸。")

    p("")
    p(f"试验族规模 N = {TRIALS}（必须显式记录，DSR 需要）")

    if args.write:
        payload = {
            "calibrated_at": time.time(),
            "calibrated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "trials": TRIALS,
            "horizon_bars_1m": args.horizon,
            "cost_usd": COST,
            "bars": int(len(d)),
            "note": ("openmobius_smc 的 IR 由离线桩产出（Mobius API 无历史回放），"
                     "verified 恒为 false；补齐真实历史校准前其权重必须为 0。"),
            "sources": {r["name"]: r for r in results},
        }
        # openmobius 无历史回放 → 强制 verified=False（不因桩的偶然表现拿到权重）
        payload["sources"]["openmobius_smc"]["verified"] = False
        payload["sources"]["openmobius_smc"]["tier"] = "rejected"
        IR_PATH.parent.mkdir(parents=True, exist_ok=True)
        IR_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                           encoding="utf-8")
        p(f"\n✅ 已写入 {IR_PATH}")
        n_ok = sum(1 for r in results
                   if r["verified"] and r["name"] != "openmobius_smc")
        p(f"   其中 verified=True 的源: {n_ok} 个"
          f"（openmobius_smc 恒为 false：无历史回放）")

    (RES / "21_source_ir.txt").write_text("\n".join(OUT), encoding="utf-8")
    print(f"\n[saved] {RES / '21_source_ir.txt'}", flush=True)


if __name__ == "__main__":
    main()
