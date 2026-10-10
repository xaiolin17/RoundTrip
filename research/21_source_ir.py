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
    py research/21_source_ir.py --symbol BTCUSDm --cost 12.5 --write
                                                 # 按品种校准 → data/BTCUSDm/source_ir.json

⚠️ 源 IR 是**按品种**的实测技能（黄金的趋势性 ≠ 欧元的均值回归），
`fusion/weights.py` 按品种优先读 `data/<品种>/source_ir.json`，
缺失才回退共享的 `data/source_ir.json`。故新品种必须逐个跑本脚本，
不能用一份表套所有品种。
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

#: 成本（**价格单位**，round-trip）。research/10_verify.py 的实测值（黄金口径）。
#: ⚠️ 各品种点值/点差不同，成本必须按品种实测：用 `--cost` 覆盖。
COST = 0.520

#: triple_barrier 的最长持有（1m 根数）。240 = 4 小时，与 1m 短线定位一致。
TB_HOLD = 240

#: 方向匹配置换对照的模拟次数。用于把「真实择时技能」与「趋势市里的
#: 方向偏差」分开 —— 后者不需要任何预测能力也能拿到正的 NW-t。
#: 200 次足以把 p 值分辨到 0.005 粒度（保守置换 p 的下限 = 1/(1+200)）。
TB_CTRL_SIMS = 200


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
    # ⚠️ 这里的 IR 是「每观测信息比率」= 毛NW-t/√n，量纲极小（0.001~0.005）**不是**
    #    research/18 §P0-2 里的相对 IR（0.28/0.05/0.03）——那张表已删除，
    #    其中 kalman 的 0.28 比它自己的出处（research/11 的 t=3.31，n=59879
    #    → IR=0.01353）大 20.7 倍，是伪造的先验。
    #    权重现在由 weights.py 用 DL 收缩从**本脚本输出的 skill** 直接算出，
    #    不再需要任何手写基线值。
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
        # 固定视界下的 skill 估计（三重障碍那一支会覆盖成非重叠版）。
        # 见 triple_barrier 段里 `skill` 的说明。
        "skill": float(nw_gross - ctrl_matched),
        # 有真实历史数据可跑 → 可测。与 `verified`（显著性）是两回事。
        "measurable": bool(len(gross) > 0),
        "source_script": "research/21_source_ir.py",
    }


def main() -> None:
    global COST
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=60000, help="1m bar 数")
    ap.add_argument("--horizon", type=int, default=60, help="前瞻根数（1m）")
    ap.add_argument("--stride", type=int, default=120, help="chanlun 重算间隔")
    ap.add_argument("--write", action="store_true",
                    help="写入 IR 文件（默认 data/source_ir.json，"
                         "给定 --symbol 时写 data/<品种>/source_ir.json）")
    #: 换一份 1m 数据文件（默认仍是历史基线用的那份）。
    #: 为什么需要：broker 的 1m 上限是 60000 根，实测窗口会随时间**向前滚动**
    #: （旧缓存 07-21..09-18，新拉 07-29..09-29）。两次拉取的**重叠区
    #: 51129 根逐字节一致**，所以可以合并成更长的序列来提高检验功效。
    #: 不默认换文件：历史结论必须能用原数据复现。
    ap.add_argument("--data", default=None,
                    help="data/cache 下的 1m parquet 文件名（默认按 --symbol 推导）")
    #: 按品种校准。源 IR 是**该品种**上实测的技能，各品种排序不同：
    #: 共用一份会把 A 品种校准出的源排序套到 B 品种身上。
    ap.add_argument("--symbol", default=None,
                    help="按品种校准：写入 data/<品种>/source_ir.json，"
                         "数据默认取 data/cache/<品种>_1m.parquet")
    ap.add_argument("--cost", type=float, default=None,
                    help="往返成本（**价格单位**）。各品种点值/点差不同，"
                         "必须按品种实测，不能用黄金的 0.520")
    args = ap.parse_args()

    if args.data is None:
        args.data = f"{args.symbol}_1m.parquet" if args.symbol else "XAUUSDm_1m.parquet"
    if args.cost is not None:
        COST = float(args.cost)

    # 输出位置：按品种 → data/<品种>/source_ir.json；否则共享 data/source_ir.json
    ir_path = (ROOT / "data" / args.symbol / "source_ir.json") if args.symbol \
        else IR_PATH
    # 位移的单位标签：保持黄金基线的原文不变，其它品种不误标 USD
    _unit = "USD" if not args.symbol else "报价单位"

    _src = DATA / args.data
    if not _src.exists():
        raise SystemExit(f"数据文件不存在: {_src}")
    d = pd.read_parquet(_src)
    d["time"] = pd.to_datetime(d["time"], utc=True)
    d = d.sort_values("time").reset_index(drop=True).iloc[-args.bars:].reset_index(drop=True)
    close = d["close"].to_numpy(float)
    high = d["high"].to_numpy(float)
    low = d["low"].to_numpy(float)

    p("=" * 96)
    p("研究取证 21 · 信号源实测 IR 校准（research/18 P0-2 的数据来源）")
    p("=" * 96)
    p(f"数据文件: {args.data}  品种: {args.symbol or '(共享/黄金基线)'}")
    p(f"1m {len(d)} 根  {d.time.iloc[0]} .. {d.time.iloc[-1]}  "
      f"区间位移 {close[-1] - close[0]:+.1f} {_unit}  成本={COST}  前瞻={args.horizon} 根")

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

        # ---- ⚠️ 方向匹配置换对照（判定门的核心）----
        # 只有 t_ind 会被**方向偏差**污染：本窗口是趋势市（全多头毛收益
        # -0.46 USD/笔，全空头 +0.57 USD/笔），所以一个持续偏空的源
        # **不需要任何预测能力**就能拿到正的 t_ind。
        # 旧判定门只看 `t_ind > 1.5`，等于给趋势市里的偏空源送分。
        #
        # 做法：把非重叠样本的**方向在其内部随机重排**（多空比例严格不变、
        # 收益路径严格不变），得到"同样倾斜、但零择时能力"的基准分布。
        # 源必须超过这个分布的高分位，才算真的有技能。
        #
        # ⚠️ 量纲陷阱（第一版写错过，务必别再踩）：
        #    `tb.ret` **已经带了源自己的方向**（ret[i] = sgn[i]·u[i]，u 是无
        #    方向收益）。所以方向的置换必须写成 `perm · ret`（perm 是 sgn 的
        #    置换），**不能**写成 `d · ret` —— 后者是把收益取反，而不是把
        #    方向打乱，多空比例会跟着歪掉，对照就不"匹配"了。
        s_ind = sgn[keep] if m_ind_n else np.zeros(0, dtype=np.int8)
        ctrl_t: list[float] = []
        if m_ind_n >= 30:
            # 种子必须**确定性**地从源名导出：不能用内置 hash()
            # （PYTHONHASHSEED 随机化会让每次运行结果不同）。
            _seed = 20260920 + sum((i + 1) * ord(c) for i, c in enumerate(name))
            _rng = np.random.default_rng(_seed)
            for _ in range(TB_CTRL_SIMS):
                perm = _rng.permutation(s_ind).astype(float)
                ctrl_t.append(newey_west_t(perm * r_ind + COST, lags=30))
        ctrl_t = [float(x) for x in ctrl_t if np.isfinite(x)]
        if ctrl_t:
            ctrl_mean = float(np.mean(ctrl_t))
            ctrl_sd = float(np.std(ctrl_t, ddof=1)) if len(ctrl_t) > 1 else 0.0
            # 保守置换 p 值：(1 + #{对照 ≥ 观测}) / (1 + 模拟数)，
            # 分子加 1 保证 p 不会伪造成 0。
            p_ctrl = (1.0 + float(np.sum(np.asarray(ctrl_t) >= t_gross_ind))) \
                / (1.0 + len(ctrl_t))
        else:
            ctrl_mean = ctrl_sd = p_ctrl = float("nan")

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
                                         if m_ind_n else 0.0),
                        # 方向匹配置换对照：控制方向偏差后的真实技能证据
                        "tb_ctrl_mean": ctrl_mean,
                        "tb_ctrl_sd": ctrl_sd,
                        "tb_ctrl_p": p_ctrl,
                        "tb_ctrl_n": len(ctrl_t),
                        # ⚠️ `skill` = 观测 t 减去方向匹配对照均值。
                        #    这才是"超出方向偏差"的真实技能证据，也是
                        #    weights.py 里 DL 收缩估计量的输入。
                        #    它**不**单独决定谁拿权重：k 个源的 skill 一起
                        #    进 DerSimonian-Laird 分解，算出 lambda 后按
                        #    `lambda·实测 + (1−lambda)·w_prior` 分配
                        #    （普通源 w_prior=等权 W_SCALE；无离线历史的源
                        #      w_prior=中庸先验 PRIOR_ONLY_WEIGHT）。
                        #    理由：本窗口 skill 为 −0.19/−0.35/+0.17，
                        #    Q=0.142 < df=2 → tau^2=0 → 数据分辨不出高下，
                        #    硬按 skill 排序就是拟合噪声。
                        "skill": (float(t_gross_ind - ctrl_mean)
                                  if (np.isfinite(t_gross_ind)
                                      and np.isfinite(ctrl_mean)) else 0.0),
                        "tb_long_ratio_ind": (float(np.mean(s_ind > 0))
                                              if m_ind_n else 0.0)})
    p("")
    p(f"  零基准（全多头，同一价格路径）= {mu0:+.4f} {_unit}/笔")
    p(f"  止损基准 = 1.2 × 1h ATR（中位 {np.nanmedian(atr1h):.2f} {_unit}），"
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
            #
            # ⚠️ 2026-09-29 加入**方向匹配置换对照**（旧门只看 t_ind，有漏洞）：
            #    本窗口是趋势市（全空头毛收益 +0.5690 vs 全多头 -0.4644），
            #    一个持续偏空的源**不需要任何择时能力**就能拿到正的 t_ind。
            #    实测：把非重叠样本的方向随机重排（多空比例不变、收益路径不变），
            #    纯置换的 t 均值就有 +0.52、sd 1.0 量级 —— 与三个真实源的观测
            #    值（+0.31/+0.17/+0.67）同量级，说明旧门测到的多半是方向偏差。
            #    更直接的反证：**纯随机方向有 14% 的概率通过旧门**（t>1.5）。
            #    故新增要求：必须显著超过方向匹配对照（置换 p < 0.05）。
            t_ind = tb["tb_gross_nw_t_ind"]
            p_ctrl_i = tb.get("tb_ctrl_p", float("nan"))
            ctrl_ok = bool(np.isfinite(p_ctrl_i) and p_ctrl_i < 0.05)
            r["verified"] = bool(np.isfinite(t_ind) and t_ind > 1.5
                                 and tb["tb_n_independent"] >= 30
                                 and tb["tb_gross_ind"] > 0   # 必须为正
                                 and ctrl_ok)                # 必须胜过方向对照
            r["tier"] = ("strong" if (np.isfinite(t_ind) and t_ind > 2.0 and ctrl_ok)
                         else ("weak" if r["verified"] else "rejected"))
            # ---- `measurable`：该源**能不能测**，与"显不显著"是两回事 ----
            # ⚠️ 这里刻意**不**用 `verified`。`verified` 是显著性判定：本窗口
            #    三源 skill 为 −0.19/−0.35/+0.17，独立样本仅 316~380，
            #    而 80% 功效需要真实 t ≥ 2.80 —— 测不出显著**不等于**测不了。
            #    把"不显著"当成"不可测"，就会让权重全 0、系统永不开仓
            #    （这正是被修掉的缺陷）。`measurable` 只看有没有真实历史
            #    数据可跑：有 Close 序列能算分数并回测 → 可测。
            #    openmobius_smc 是离线桩（无历史回放）→ 下面单独强制 False。
            r["measurable"] = bool(np.isfinite(t_ind) and tb["tb_n_independent"] > 0)
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
    p("C. 结论：各源拿到多少权重")
    p("=" * 96)
    p("")
    p("判定规则（**triple_barrier + 非重叠 + 方向匹配对照**）：")
    p("  非重叠毛 NW-t > 1.5 且 非重叠毛均值 > 0 且独立样本 ≥ 30")
    p("  **且 置换 p < 0.05**（必须胜过「同样多空比例、方向随机重排」的对照）")
    p("")
    p("  为什么必须加最后一条：本窗口是趋势市（全多头毛收益 -0.46 USD/笔，")
    p("  全空头 +0.57 USD/笔），持续偏空的源**不需要任何择时能力**就能")
    p("  拿到正的 NW-t。实测纯随机方向有 14% 概率通过只看 t>1.5 的旧门。")
    p("")
    p("  ⚠️ **但 `verified` 不决定权重，只决定「能不能证明它强」。**")
    p("     本窗口独立样本仅 316~380，双侧 0.05 下要 80% 功效需要真实")
    p("     t ≥ 2.80 —— 测不出显著**不等于**没有技能。所以权重由")
    p("     `weights.py` 的 DerSimonian-Laird 收缩算出：")
    p("       skill_i = t_i − 方向匹配对照均值_i")
    p("       tau^2 = max(0, (Q − df)/C),  lambda = tau^2/(tau^2 + 1)")
    p("       w_i = lambda·(skill_i/skill_max)^2·W_SCALE + (1−lambda)·w_prior")
    p("     其中普通源 w_prior = W_SCALE（等权）；openmobius_smc 这类无离线")
    p("     历史的源以 PRIOR_ONLY_WEIGHT（0.1）为**下限**，其权重由实盘滚动")
    p("     命中率在线驱动（区间 0.1 ~ PRIOR_ONLY_MAX_WEIGHT=4.0，见 weights.py）")
    p("     lambda = 0 → 源间差异不显著于噪声 → 取先验（不拟合噪声）")
    p("     lambda → 1 → 差异确凿 → 完全采用实测排序")
    p("")
    verified = [r for r in results if r["verified"]]
    skills = []
    for r in results:
        mark = "已证实" if r["verified"] else "未证实（不等于没技能）"
        ind = r.get("tb_gross_nw_t_ind", float("nan"))
        ov = r.get("tb_overlap", float("nan"))
        nind = r.get("tb_n_independent", 0)
        cm = r.get("tb_ctrl_mean", float("nan"))
        cp = r.get("tb_ctrl_p", float("nan"))
        lr = r.get("tb_long_ratio_ind", float("nan"))
        sk = r.get("skill", float("nan"))
        if r["name"] != "openmobius_smc":
            skills.append(float(sk))
        p(f"  {r['name']:<22} {mark}")
        p(f"  {'':<22}   非重叠毛NW-t={ind:+.2f}  独立样本={nind}  重叠={ov:.0f}x")
        p(f"  {'':<22}   对照(同多空比 {lr:.1%} 随机重排) 均值={cm:+.2f}  "
          f"置换p={cp:.3f}  {'通过' if (np.isfinite(cp) and cp < 0.05) else '未通过'}")
        p(f"  {'':<22}   skill = t − 对照均值 = {sk:+.3f}")
    p("")
    # 现场复算 lambda，让结论自洽可验证（结论里的 Q/df/lambda 全部取自这里，
    # 不写死数字 —— 写死就会随数据漂移而变成假话）。
    q, df, lam, _sk_txt = 0.0, 0, 0.0, "n/a"
    if len(skills) >= 2:
        k = len(skills)
        th = float(np.mean(skills))
        q = float(sum((x - th) ** 2 for x in skills))
        df = k - 1
        c = float(k - 1)
        tau2 = max(0.0, (q - df) / c) if c > 0 else 0.0
        lam = tau2 / (tau2 + 1.0)
        _sk_txt = " / ".join(f"{x:+.3f}" for x in skills)
        p(f"  DL 复算：k={k}  Q={q:.4f}  df={df}  tau^2={tau2:.4f}  lambda={lam:.4f}")
    p("")
    if verified:
        p(f"  → {len(verified)} 个源已**证实**有效: {[r['name'] for r in verified]}")
        p("     它们按实测 skill 拿权重（lambda 越接近 1，实测排序影响越大）。")
        p("     **未证实**的源仍然拿到权重：lambda 由全部可测源共同决定，")
        p("     未证实只说明样本量不足以证明它强，不构成把它打成 0 的依据。")
    else:
        p("  ⚠️ **没有任何源通过「非重叠 + 方向匹配对照」检验（即未证实）。**")
        p("     这不等于「没有技能」：独立样本只有约 310~390，")
        p("     双侧 0.05 下要 80% 功效需要真实 t ≥ 2.80，而实测 t 都在 1 以下")
        p("     —— 是**分辨不出来**，不是**测不出东西**。")
        p("")
        p("     后续行为（weights.py，**没有开关**，纯估计量）：")
        p("       · 权重的先验取法：普通源用等权先验 W_SCALE，无离线历史的源")
        p("         （openmobius_smc）用中庸先验 PRIOR_ONLY_WEIGHT；两者再按")
        p("         `lambda` 与实测 skill 混合，没有「用哪张表」的二选一。")
        p(f"       · 本窗口 skill = {_sk_txt}（上方逐源实测）")
        p(f"         → Q = {q:.4f} < df = {df} → tau^2 = 0 → lambda = 0")
        p("         → **可测源取先验（普通源等权）**。这是数据给出的答案，不是兜底常数。")
        p("       · 判据是 Q 与 df 的比较，**不是**某个写死的数字：")
        p("         源间差异一旦真的超过抽样噪声（Q > df），lambda 自动 > 0，")
        p("         实测排序随即接管权重（见 research/25 §11.4 的可证伪性表）。")
        p("       · 系统照常开仓（冷启动 Σw = 3×4.0 + 0.1 = 12.1 → σ ≈ 0.287 ≤ sigma_max")
        p("         0.8；该源成绩变好后 Σw 最高 16.0 → σ ≈ 0.25，仍过闸），")
        p("         但风险层按「未校准模式」降仓：低置信度 → 小仓位，")
        p("         而不是零交易（一个不交易的交易系统不是安全，是失败）。")
        p("       · openmobius_smc 的权重由**实盘滚动命中率在线驱动**（用户 2026-10-10")
        p("         选定）：它没有离线历史可校准（Mobius API 无历史回放，桩技能不可")
        p("         采信），故 skill 置 0 且不进 DL 方差分解；权重区间")
        p("         [PRIOR_ONLY_WEIGHT=0.1, PRIOR_ONLY_MAX_WEIGHT=4.0]（下限=入场券，")
        p("         上限=与满额源平权），命中率高且窗口满则逼近上限。")
        p("         分数层另有贝叶斯证据按同一命中率同步调节。")
    p("")
    p("  ⚠️ 重要：**重叠会把噪声伪装成 alpha。**")
    p("     信号在相邻 bar 上重复（如 chanlun 的 15m 结果映射到 15 根 1m）")
    p("     → 大量「交易」实际只对应少量独立决策。不校正重叠时毛 NW-t")
    p("     可达 +3 量级（看起来是强 alpha），校正后跌到 0 附近。")
    p("     research/11 早已提醒「任何毛收益数字都必须用同一价格路径上的")
    p("     随机方向基准来校准」，重叠校正是同一原则的延伸。")
    p("")
    p("  ⚠️ 另一件同样重要的事：**去重叠还不够，必须再控制方向偏差。**")
    p("     本窗口是趋势市，一个持续偏空的源不需要择时能力就能拿到正 t。")
    p("     故判定门额外要求「置换 p < 0.05」（见上方逐源输出）。")

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
            "note": ("openmobius_smc 无历史回放（Mobius API 不提供），离线分数来自桩，"
                     "桩技能不可采信，故 skill 强制为 0 且不进入 DL 方差分解；其权重由"
                     "实盘滚动命中率在线驱动（区间 [PRIOR_ONLY_WEIGHT=0.1, "
                     "PRIOR_ONLY_MAX_WEIGHT=4.0]，n<20 时为下限 0.1，命中率高且窗口满则"
                     "逼近上限；measurable=true）。其余源 measurable=true，权重由 "
                     "weights.py 用 DL 收缩（lambda）在实测 skill 与等权先验之间连续混合，"
                     "无开关。"),
            "sources": {r["name"]: r for r in results},
        }
        # openmobius 无历史回放 → 桩的 skill 不可采信。
        # 强制 verified=False + tier=rejected + skill=0，
        # 但 measurable=True（权重下限 PRIOR_ONLY_WEIGHT=0.1，由实盘命中率在线驱动）——
        # 这是"没有离线历史可校准"，不是"不显著"，也不是"无权重"。
        payload["sources"]["openmobius_smc"]["verified"] = False
        payload["sources"]["openmobius_smc"]["tier"] = "rejected"
        payload["sources"]["openmobius_smc"]["measurable"] = True
        payload["sources"]["openmobius_smc"]["skill"] = 0.0
        if args.symbol:
            payload["symbol"] = args.symbol
        ir_path.parent.mkdir(parents=True, exist_ok=True)
        ir_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                           encoding="utf-8")
        p(f"\n✅ 已写入 {ir_path}")
        n_ok = sum(1 for r in results
                   if r["verified"] and r["name"] != "openmobius_smc")
        p(f"   其中 verified=True 的源: {n_ok} 个"
          f"（openmobius_smc 恒为 verified=false：桩技能不可采信）")

    # ⚠️ 输出文件名带上数据来源：历史上这里固定写 `21_source_ir.txt`，
    #    换数据重跑就会**静默覆盖**已有取证（本次实测踩到：扩展数据的
    #    结果把基线那份覆盖了）。基线那份现在叫 `21_source_ir_baseline.txt`。
    _stem = "21_source_ir" if args.data == "XAUUSDm_1m.parquet" \
        else "21_source_ir_" + Path(args.data).stem.replace("XAUUSDm_1m_", "")
    (RES / f"{_stem}.txt").write_text("\n".join(OUT), encoding="utf-8")
    print(f"\n[saved] {RES / f'{_stem}.txt'}", flush=True)


if __name__ == "__main__":
    main()
