"""模型擂台：在真实 1m 数据上对所有模型做统一、无前视、扣成本的评估。

流程：
  1. 载入 1m 真实数据（MT5 拉取）
  2. 计算全部模型输出（缓存到 research/model_cache/）
  3. 对每个方向模型：三重障碍标注（σ 自适应障碍）+ 唯一性权重
  4. 统一指标：IC / 命中 / 净收益 / NW-t / Sharpe / DSR
  5. 落盘 research/arena_results.parquet + 报告

所有评估强制扣除真实点差成本。
"""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_agent.common.config import CFG
from gold_agent.quant import models as M
from gold_agent.quant.labeling import (deflated_sharpe, ewma_vol, meta_labels,
                                       newey_west_t, spearman_ic, triple_barrier,
                                       uniqueness_weights, weighted_nw_t)

RES = Path(__file__).parent
CACHE = RES / "model_cache"
CACHE.mkdir(exist_ok=True)
OUT: list[str] = []


def p(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


# ══════════════════════════════════════════════════════════════════
TF = sys.argv[1] if len(sys.argv) > 1 else "1m"
MAXBARS = int(sys.argv[2]) if len(sys.argv) > 2 else 60000

df = pd.read_parquet(CFG.data_dir / f"XAUUSDm_{TF}.parquet")
df["time"] = pd.to_datetime(df["time"], utc=True)
df = df.sort_values("time").reset_index(drop=True).iloc[-MAXBARS:].reset_index(drop=True)
SPREAD = float(df.spread.median()) * 0.001
COST = 2 * SPREAD

p("=" * 92)
p(f"模型擂台 · 周期={TF} · {len(df)} 根 · {df.time.iloc[0]} .. {df.time.iloc[-1]}")
p(f"往返成本 = {COST:.3f} USD/盎司（点差中位数 {df.spread.median():.0f} points）")
p("=" * 92)

# ── 1) 计算模型输出（带缓存）──────────────────────────────────────
p("\n[1] 计算模型输出")
t_start = time.time()
vals: dict[str, np.ndarray] = {}
for i, spec in enumerate(M.REGISTRY, 1):
    cf = CACHE / f"{TF}_{MAXBARS}_{spec.name}.npy"
    if cf.exists():
        v = np.load(cf)
        if len(v) == len(df):
            vals[spec.name] = v
            p(f"    [{i:>2}/{len(M.REGISTRY)}] {spec.name:<22} 缓存命中")
            continue
    t0 = time.time()
    try:
        v = np.asarray(spec.fn(df), float)
        if len(v) != len(df):
            raise ValueError(f"length {len(v)}")
        np.save(cf, v)
        vals[spec.name] = v
        p(f"    [{i:>2}/{len(M.REGISTRY)}] {spec.name:<22} {time.time()-t0:>6.1f}s")
    except Exception as e:
        p(f"    [{i:>2}/{len(M.REGISTRY)}] {spec.name:<22} ERROR "
          f"{type(e).__name__}: {str(e)[:50]}")
p(f"    共 {len(vals)} 个模型，用时 {time.time()-t_start:.0f}s")

# ── 2) 标准化方向模型（滚动 z，消除量纲与漂移）──────────────────
def zscore(x: np.ndarray, win: int = 1440) -> np.ndarray:
    s = pd.Series(x)
    m = s.rolling(win, min_periods=120).mean()
    sd = s.rolling(win, min_periods=120).std().replace(0, np.nan)
    return np.clip(((s - m) / sd).to_numpy(), -4, 4)


dir_models = {m.name: zscore(vals[m.name]) for m in M.DIRECTION_MODELS if m.name in vals}
state_models = {m.name: vals[m.name] for m in M.STATE_MODELS if m.name in vals}

# ── 3) 标注 ──────────────────────────────────────────────────────
p("\n[2] 三重障碍标注（σ 自适应障碍，pt=2.0σ / sl=1.0σ / 最长 60 根）")
vol = ewma_vol(df.close.to_numpy(float), halflife=60, min_periods=30)
vol = np.where(np.isfinite(vol) & (vol > 0), vol, np.nanmedian(vol))
close = df.close.to_numpy(float)
high = df.high.to_numpy(float)
low = df.low.to_numpy(float)
p(f"    σ 中位数 = {np.nanmedian(vol):.3f} USD  →  TP 距离 {2.0*np.nanmedian(vol):.3f} / "
  f"SL 距离 {1.0*np.nanmedian(vol):.3f} USD")
p(f"    成本占 SL 距离 = {COST/(1.0*np.nanmedian(vol)):.1%}，占 TP 距离 = "
  f"{COST/(2.0*np.nanmedian(vol)):.1%}")

fwd_ret = np.full(len(df), np.nan)
fwd_ret[:-15] = close[15:] - close[:-15]

# 全方向基准标注（用于评估状态模型）
tb_all = triple_barrier(close, high, low, vol, np.ones(len(df), dtype=int),
                        2.0, 1.0, 60, COST)
uni_all = uniqueness_weights(tb_all.t1, len(df))
p(f"    全多头标注：胜率={np.mean(tb_all.label>0):.3f}  平均持有={tb_all.bars_held.mean():.1f} 根")
p(f"    唯一性权重均值={uni_all.mean():.3f}（<1 表示标签重叠，显著性需打折）")

# ── 4) 逐模型评估 ────────────────────────────────────────────────
p("\n[3] 逐模型评估（方向模型：按模型符号进场，三重障碍出场）")
rows = []
for name, sig in dir_models.items():
    sgn = np.sign(np.nan_to_num(sig, nan=0.0)).astype(np.int8)
    tb = triple_barrier(close, high, low, vol, sgn, 2.0, 1.0, 60, COST)
    uni = uniqueness_weights(tb.t1, len(df))
    m = (sgn != 0) & np.isfinite(tb.ret) & (tb.bars_held > 0)
    if m.sum() < 200:
        continue
    ret = tb.ret[m]
    icv = spearman_ic(sig, fwd_ret, uni)
    hit = float(np.mean(ret > 0))
    nw = weighted_nw_t(ret, uni[m], lags=30)
    nwd = newey_west_t(ret, lags=30)
    # 固定前瞻收益（同一持有期）才是可比的 Sharpe 基础；
    # 用变长持有期会因「止损单持有短、止盈单持有长」产生系统性偏差。
    fixed = np.sign(np.nan_to_num(sig, nan=0.0)) * fwd_ret - COST
    mf = np.isfinite(fixed) & (sgn != 0)
    sr = (fixed[mf].mean() / max(fixed[mf].std(), 1e-12) * np.sqrt(1440 * 252)
          if mf.sum() > 200 else np.nan)
    rows.append({"model": name, "n": int(m.sum()), "ic": icv,
                 "hit": hit, "mean_ret": ret.mean(), "median_ret": float(np.median(ret)),
                 "nw_t": nw, "nw_t_unw": nwd, "sharpe": sr,
                 "avg_bars": float(tb.bars_held[m].mean()),
                 "fixed_mean": float(fixed[mf].mean()) if mf.sum() else np.nan,
                 "total": float(ret.sum()), "std": float(ret.std()),
                 "skew": float(pd.Series(ret).skew()),
                 "kurt": float(pd.Series(ret).kurtosis() + 3)})

ad = pd.DataFrame(rows).sort_values("nw_t", ascending=False).reset_index(drop=True)
p(f"\n{'模型':<16}{'笔数':>7}{'IC':>9}{'命中':>7}{'净均值':>9}{'NW-t':>7}"
  f"{'年化SR':>8}{'持有':>6}{'固定期均值':>11}{'总盈亏':>10}")
p("-" * 92)
for _, r in ad.iterrows():
    p(f"{r['model']:<16}{int(r['n']):>7}{r['ic']:>+9.4f}{r['hit']:>7.3f}"
      f"{r['mean_ret']:>9.3f}{r['nw_t']:>7.2f}{r['sharpe']:>8.2f}"
      f"{r['avg_bars']:>6.0f}{r['fixed_mean']:>11.4f}{r['total']:>10.0f}")

# ── 5) 状态模型评估 ──────────────────────────────────────────────
p("\n[4] 状态模型评估（与未来波动/收益的关系，非方向）")
p(f"{'状态模型':<20}{'与未来|收益|相关':>18}{'与未来收益相关':>16}"
  f"{'高低分位波动比':>16}{'高低分位收益差':>16}")
abs_fwd = pd.Series(np.abs(fwd_ret))
srows = []
for name, v in state_models.items():
    m = np.isfinite(v) & np.isfinite(fwd_ret)
    if m.sum() < 500:
        continue
    c_abs = float(np.corrcoef(pd.Series(v[m]).rank(), abs_fwd[m].rank())[0, 1])
    c_ret = float(np.corrcoef(pd.Series(v[m]).rank(),
                              pd.Series(fwd_ret[m]).rank())[0, 1])
    q = pd.qcut(pd.Series(v[m]), 4, labels=False, duplicates="drop")
    hi = np.abs(fwd_ret[m])[q == q.max()].mean()
    lo = np.abs(fwd_ret[m])[q == 0].mean()
    rhi = fwd_ret[m][q == q.max()].mean()
    rlo = fwd_ret[m][q == 0].mean()
    srows.append({"model": name, "corr_absret": c_abs, "corr_ret": c_ret,
                  "vol_ratio": hi / max(lo, 1e-12), "ret_spread": rhi - rlo})
    p(f"{name:<20}{c_abs:>+18.4f}{c_ret:>+16.4f}{hi/max(lo,1e-12):>16.2f}"
      f"{rhi-rlo:>+16.4f}")
sd = pd.DataFrame(srows).sort_values("corr_absret", ascending=False)

# ── 6) 多重检验校正 ──────────────────────────────────────────────
p("\n[5] 多重检验校正（Deflated Sharpe Ratio）")
N = len(ad)
p(f"    试验族规模 N = {N} 个方向模型配置")
best = ad.iloc[0]
bars_per_year = 1440 * 252
dsr, sr0 = deflated_sharpe(best["mean_ret"] / max(best["std"], 1e-12), N,
                           int(best["n"]), best["skew"], best["kurt"])
p(f"    最优模型 = {best['model']}")
p(f"    样本内年化 Sharpe = {best['sharpe']:.2f}（这是未校正的数字）")
p(f"    纯噪声下 N={N} 次试验的期望最大年化 Sharpe = {sr0*np.sqrt(bars_per_year):.2f}")
p(f"    Deflated Sharpe Ratio = {dsr:.3f}  → {'通过' if dsr > 0.95 else '未通过'}（阈值 0.95）")

p(f"\n    全部 {N} 个模型里 NW-t > 2 的个数 = {(ad['nw_t'] > 2).sum()}")
p(f"    全部 {N} 个模型里 NW-t > 3 的个数 = {(ad['nw_t'] > 3).sum()}")
p(f"    在纯噪声下，{N} 次独立试验期望有 {N*0.023:.1f} 个 |t|>2、{N*0.0014:.2f} 个 |t|>3")
p("    → 若实际显著个数不超过噪声期望，则整族无真实 alpha")

ad.to_parquet(RES / f"arena_dir_{TF}.parquet", index=False)
sd.to_parquet(RES / f"arena_state_{TF}.parquet", index=False)
(RES / f"05_arena_{TF}.txt").write_text("\n".join(OUT), encoding="utf-8")
p(f"\n[已写入 research/05_arena_{TF}.txt]")
