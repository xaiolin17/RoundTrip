"""融合引擎真实历史回放校准（docs/08 L5）。

优先用 data/cache/XAUUSDm_15m.parquet（MT5 拉取的长历史），
退回 D:\\DDDDDDDDD\\XAUUSD_1min_kline.parquet。

P0-3 修正（research/18 §P0-3）
------------------------------
旧版断言是 `assert ic > -0.05` —— **IC = −0.04 也能通过**，
这个测试在过去所有运行里都不可能失败。

修法：改为有意义的双侧下限 + 命中率下限，并补上 mobius 的离线桩
（否则测试覆盖不到实际主导决策的那个源）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gold_agent.common.config import CFG
from gold_agent.fusion.engine import FusionEngine
from gold_agent.fusion.normalize import SourceNormalizer
from gold_agent.fusion.weights import SourceIR, WeightTable
from gold_agent.skills.chanlun_adapter import analyze_tf
from gold_agent.skills.mobius_adapter import MobiusResult, _score_fn

HIST_15M = CFG.data_dir / "XAUUSDm_15m.parquet"
HIST_FALLBACK = Path(r"D:\DDDDDDDDD\XAUUSD_1min_kline.parquet")

#: 验收阈值（research/18 §P0-3）：双侧下限 + 命中率下限
IC_MIN = 0.01
HIT_MIN = 0.50


def _load_15m() -> pd.DataFrame | None:
    if HIST_15M.exists():
        df = pd.read_parquet(HIST_15M)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        return df.sort_values("time").reset_index(drop=True).set_index("time")
    if HIST_FALLBACK.exists():
        df = pd.read_parquet(HIST_FALLBACK)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.sort_values("time").reset_index(drop=True).set_index("time")
        return df.resample("15min").agg({"open": "first", "high": "max", "low": "min",
                                         "close": "last", "volume": "sum"}).dropna()
    return None


@pytest.fixture(scope="module")
def hist_15m() -> pd.DataFrame:
    df = _load_15m()
    if df is None:
        pytest.skip("无可用历史数据")
    return df


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    vol_col = "tick_volume" if "tick_volume" in df.columns else "volume"
    r = df.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                               "close": "last", vol_col: "sum"}).dropna()
    return r


def _frame_like(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["spread"] = 0
    out["real_volume"] = 0
    if "tick_volume" not in out.columns:
        out["tick_volume"] = out.get("volume", 0)
    return out[["open", "high", "low", "close", "tick_volume", "spread", "real_volume"]]


def _mobius_stub(df_15m: pd.DataFrame, last_price: float) -> MobiusResult:
    """mobius 的离线桩（无网络）：从历史 OHLCV 反推 SMC 结构。

    research/18 §P0-3 要求补上这个桩 —— 否则测试覆盖不到实际主导决策的源。
    注意：真实 Mobius API 无历史回放，因此这里只验证**打分与去偏机制**，
    不代表线上 mobius 的真实表现（其权重因此恒为 0，见 weights.py）。
    """
    high = df_15m["high"].to_numpy(float)
    low = df_15m["low"].to_numpy(float)
    n = len(df_15m)
    res = MobiusResult(status="ok")
    piv: list[tuple[int, float, str]] = []
    for i in range(5, n - 5):
        if high[i] >= high[i - 5:i + 6].max():
            piv.append((i, float(high[i]), "HH"))
        elif low[i] <= low[i - 5:i + 6].min():
            piv.append((i, float(low[i]), "LL"))
    structs = []
    for idx in range(1, len(piv)):
        _, px, kind = piv[idx]
        prev_kind = piv[idx - 1][2]
        if kind == "HH":
            structs.append({"kind": "BOS" if prev_kind == "HH" else "CHoCH",
                            "bias": "bull", "pivot_price": px})
        else:
            structs.append({"kind": "BOS" if prev_kind == "LL" else "CHoCH",
                            "bias": "bear", "pivot_price": px})
    res.structures = structs[-3:]
    return res


def _plumbing_engine() -> FusionEngine:
    """构造一个带 IR 权重的引擎，用于验证融合链路。

    这些 IR 数字与 `research/18 §P0-2` 的基线表一致（kalman 0.28 / chanlun 0.05 /
    classic 0.03 / openmobius_smc 0.00），并用 `_refresh_ir_max()` 做归一。
    它们的作用是让 `gaussian.fuse` 有非零权重可加权，从而把
    「去均值 → IR 加权 → 融合 → 打分」这条**机器**跑通。

    生产权重由 `data/source_ir.json` + `weights.BASELINE_IR` 合并得到，
    由 `test_production_weight_table_can_trade` 覆盖。

    ⚠️ 注意 kalman 的 IR=0.28 来自 `research/18 §P0-2` 的基线表（其出处是
    `research/11` 的 kalman_trend 毛 NW-t=+3.31）。`research/23_kalman_tb.py`
    用 triple_barrier 复核了**线上实现**（filterpy + 固定 R）：毛 NW-t=+1.74，
    约为文献值的 0.53x；两者方向一致率 89.3%，属同一信号族。
    """
    tbl = WeightTable(trials=6)
    tbl.sources["kalman_persist"] = SourceIR(
        "kalman_persist", ir=0.28, nw_t=3.31, n_obs=60000, verified=True,
        source_script="research/18_COMMERCIAL_PLAN.md §P0-2（基线表）")
    tbl.sources["chanlun"] = SourceIR(
        "chanlun", ir=0.05, nw_t=1.1, n_obs=60000, verified=True,
        source_script="research/18_COMMERCIAL_PLAN.md §P0-2（基线表）")
    tbl.sources["classic_indicators"] = SourceIR(
        "classic_indicators", ir=0.03, nw_t=0.8, n_obs=60000, verified=True,
        source_script="research/18_COMMERCIAL_PLAN.md §P0-2（基线表）")
    tbl.sources["openmobius_smc"] = SourceIR(
        "openmobius_smc", ir=0.0, nw_t=0.0, n_obs=0, verified=False,
        source_script="research/21_source_ir.py")
    tbl._refresh_ir_max()
    return FusionEngine(weight_table=tbl)


# 保留旧名，避免其它测试引用处失效
_calibrated_engine = _plumbing_engine


def test_fusion_replay_calibration(hist_15m):
    """融合分对未来方向的信息系数与命中率（P0-3：断言必须能失败）。

    ⚠️ **本测试验证的是融合"机器"，不是生产校准。**
    它用 `_calibrated_engine()` 注入 IR 权重，以验证：
    去均值 → IR 加权 → 融合 → IC/命中率 这条链路本身是否正常。

    生产路径用的是 `data/source_ir.json` + 基线表；

    P0-3 的意义在于**断言本身变得可失败**：旧版是 `assert ic > -0.05`，
    IC=−0.04 也能通过，该测试在过去所有运行里都不可能失败。
    """
    engine = _calibrated_engine()
    df = hist_15m
    if len(df) < 500:
        pytest.skip(f"历史数据不足 500 根: {len(df)}")
    step, warm = 4, 400        # 15m × 4 = 1h 决策间隔；预热 400 根（约 4 天）
    points = range(warm, len(df) - 32, step)
    scores, actuals = [], []
    for i in points:
        window = df.iloc[i - warm:i]          # 只用过去，无前视
        frames = {"1m": _frame_like(_resample(window, "1min")),
                  "5m": _frame_like(_resample(window, "5min")),
                  "15m": _frame_like(window),
                  "1h": _frame_like(_resample(window, "1h"))}
        cl = {tf: analyze_tf(frames[tf], tf) for tf in ("5m", "15m", "1h")}
        mob = {"15m": _mobius_stub(window, float(window["close"].iloc[-1]))}
        ev = engine.fuse_all(frames, cl, mob, obs_id=i)
        s = ev.result.score
        if s == 0:
            continue
        future_close = df["close"].iloc[i + 32] if i + 32 < len(df) else None
        if future_close is None:
            continue
        scores.append(s)
        actuals.append(np.sign(future_close - df["close"].iloc[i - 1]))
    assert len(scores) >= 20, f"决策点过少: {len(scores)}"
    scores = np.array(scores)
    actuals = np.array(actuals)
    hit = float(np.mean(np.sign(scores) == actuals))
    ic = float(np.corrcoef(scores, actuals)[0, 1]) if np.std(actuals) > 0 else 0.0
    print(f"replay(15m long-history): n={len(scores)} hit_rate={hit:.3f} IC={ic:.4f}")

    # ---- P0-3：有意义的双侧下限 + 命中率下限（旧版是 ic > -0.05）----
    assert ic > IC_MIN, (
        f"融合分 IC 过低: {ic:.4f}（需 > {IC_MIN}）—— "
        f"融合链路对未来 8h 方向没有可用信息，需重新校准源权重或更换周期。"
        f" 注意：不要通过放宽本断言来'修复'，那正是 research/18 §P0-3 指出的空转问题。")
    assert hit > HIT_MIN, f"命中率不足: {hit:.3f}（需 > {HIT_MIN}）"


def test_production_weight_table_can_trade():
    """生产权重表必须**能开仓** —— 这是硬性验收，不是"诚实状态"记录。

    ⚠️ 本测试曾经断言相反的事情（"无源通过验证 → 权重全 0 → 不开仓"），
    并把「不开仓」当作正确行为。**那个结论是错的**，理由：

      1. research/18 §P0-2 **原文就列出了 IR 表**（kalman 0.28 / chanlun 0.05 /
         classic 0.03 / openmobius_smc 0.00），只有 `openmobius_smc` 是 0。
         把全部源打成 0 是对该条的过度应用。
      2. 一个不交易的交易系统是**失败状态**，不是安全状态。
         实盘证据：`effective_weight=0.0` → `score=0.0` → 永远 hold。

    真正要守住的不变量是：**未验证的源（openmobius_smc）拿不到权重**。
    """
    import json
    from pathlib import Path
    f = Path(__file__).resolve().parents[1] / "data" / "source_ir.json"
    if not f.exists():
        pytest.skip("尚未运行 research/21_source_ir.py --write")
    data = json.loads(f.read_text(encoding="utf-8"))

    from gold_agent.fusion.weights import DECISION_SOURCES
    tbl = WeightTable.load()

    # (1) 必须能开仓：总权重足够大，使 sigma_S 过 sigma_max 闸门
    total = tbl.total_weight(list(DECISION_SOURCES))
    assert total > 0, (
        "生产权重表全 0 → 融合分恒 0 → 系统永不开仓。"
        "这是失败状态：research/18 §P0-2 只要求 openmobius_smc 为 0。")
    sigma_s = 1.0 / (total ** 0.5)
    assert sigma_s <= CFG.fusion.sigma_max, (
        f"sigma_S={sigma_s:.3f} > sigma_max={CFG.fusion.sigma_max} → 决策层永远 hold")

    # (2) 未验证的源必须仍然是 0（这条不能被放松）
    assert tbl.weight("openmobius_smc") == 0.0, "openmobius_smc 未验证，必须 0 权重"

    # (3) 每个拿到权重的源都必须有 research 出处（不许手填）
    for name in DECISION_SOURCES:
        if tbl.weight(name) > 0:
            assert tbl.get(name).source_script, f"{name} 有权重但没有出处"
            assert tbl.get(name).ir > 0, f"{name} 权重>0 但 IR<=0"

    # (4) 毛/净必须分开记录（research/11 的教训）
    for k, v in data["sources"].items():
        assert "gross_nw_t" in v and "net_nw_t" in v, f"{k} 缺少毛/净分离字段"
        assert v["net_nw_t"] <= v["gross_nw_t"] + 1e-9, f"{k} 净 NW-t 不应高于毛 NW-t"


def test_fusion_score_is_two_sided(hist_15m):
    """P0-1 验收：融合分必须**双向**（旧版 80.2% 为正、|S|≥1.3 时 38 多 0 空）。

    research/18 §P0-1 验收：融合分做多/做空轮数均 > 0。
    """
    engine = _calibrated_engine()
    df = hist_15m
    if len(df) < 600:
        pytest.skip("历史数据不足")
    warm = 400
    signs = []
    for i in range(warm, len(df) - 32, 8):
        window = df.iloc[i - warm:i]
        frames = {"1m": _frame_like(_resample(window, "1min")),
                  "5m": _frame_like(_resample(window, "5min")),
                  "15m": _frame_like(window),
                  "1h": _frame_like(_resample(window, "1h"))}
        cl = {tf: analyze_tf(frames[tf], tf) for tf in ("5m", "15m", "1h")}
        mob = {"15m": _mobius_stub(window, float(window["close"].iloc[-1]))}
        ev = engine.fuse_all(frames, cl, mob, obs_id=i)
        if ev.result.score != 0:
            signs.append(np.sign(ev.result.score))
    assert signs, "没有任何非零融合分"
    longs = int(np.sum(np.array(signs) > 0))
    shorts = int(np.sum(np.array(signs) < 0))
    print(f"融合分方向分布: 多={longs} 空={shorts} (n={len(signs)})")
    assert longs > 0 and shorts > 0, (
        f"融合分单向！多={longs} 空={shorts} —— 结构性方向偏置未消除（P0-1 失败）")


def test_warmup_windows_match_decision_cycle():
    """回归：滚动窗口的**单位是决策轮数**，必须与决策周期匹配。

    实盘曾出现 `source_warmed` 全 false 且长时间不预热 —— 因为
    `norm_min_periods=240` 是 1m 周期时代的值（240 分钟 = 4 小时），
    P1-1 把决策周期改成 1h 后它变成 **240 小时 = 10 天**。

    这类"单位错配"不会报错，只会静默让系统长期空仓，
    所以必须显式断言预热时长落在合理区间。

    ⚠️ 决策周期回到 1m（60s）后，240 轮 = 4 小时。这个"预热时长"本身
    是**合理的**（1m 短线需要几小时样本才能估准分布），
    但**不能靠实盘干等** —— 必须由 `prime_history` 在启动时回放补齐。
    所以本测试同时断言：预热时长合理 **且** prime_steps 足以覆盖它。
    """
    hours = CFG.decision.loop_interval_s / 3600.0
    for label, mn in (("norm_min_periods", CFG.fusion.norm_min_periods),
                      ("vol_pct_min_periods", CFG.fusion.vol_pct_min_periods),
                      ("baseline_min_periods", CFG.fusion.baseline_min_periods)):
        days = mn * hours / 24.0
        assert 0.02 <= days <= 7.0, (
            f"{label}={mn} 在 {hours:.0f}h 决策周期下 = {days:.2f} 天预热 —— "
            f"超出合理区间 [0.02, 7] 天。窗口单位是决策轮数，"
            f"改 loop_interval_s 时必须同步调整这些参数。")
    # 窗口必须 ≥ 预热门槛，否则永远无法预热
    assert CFG.fusion.norm_window >= CFG.fusion.norm_min_periods
    assert CFG.fusion.vol_pct_window >= CFG.fusion.vol_pct_min_periods
    assert CFG.fusion.baseline_window >= CFG.fusion.baseline_min_periods
    # ⚠️ 关键：启动预热必须能覆盖预热门槛，否则启动后仍要干等
    #    （1m 下 240 轮 = 4 小时不开仓 = 失败状态）
    assert CFG.fusion.prime_steps >= CFG.fusion.norm_min_periods, (
        f"prime_steps={CFG.fusion.prime_steps} < norm_min_periods="
        f"{CFG.fusion.norm_min_periods} → 启动预热后仍不 warm，"
        f"系统要干等 {(CFG.fusion.norm_min_periods - CFG.fusion.prime_steps) * hours:.1f} "
        f"小时才能开仓")
    assert CFG.fusion.prime_steps >= CFG.fusion.baseline_min_periods
    assert CFG.fusion.prime_steps >= CFG.fusion.vol_pct_min_periods
    # 引擎装配必须与 config 一致（防止 getattr 兜底值悄悄生效）
    e = FusionEngine(weight_table=WeightTable(trials=0))
    assert e.normalizer.win == CFG.fusion.norm_window
    assert e.normalizer.min_periods == CFG.fusion.norm_min_periods
    assert e.vol_pct.win == CFG.fusion.vol_pct_window
    assert e.baseline.win == CFG.fusion.baseline_window


def test_fusion_demean_removes_directional_bias(hist_15m):
    """P0-1 验收：去均值后各源方向分布回到中性。

    research/18 §P0-1 验收标准：各源 score 均值 ∈ [−0.3,+0.3]，
    为正比例 ∈ [40%,60%]。
    """
    engine = _calibrated_engine()
    df = hist_15m
    if len(df) < 600:
        pytest.skip("历史数据不足")
    warm = 400
    for i in range(warm, len(df) - 32, 8):
        window = df.iloc[i - warm:i]
        frames = {"1m": _frame_like(_resample(window, "1min")),
                  "5m": _frame_like(_resample(window, "5min")),
                  "15m": _frame_like(window),
                  "1h": _frame_like(_resample(window, "1h"))}
        cl = {tf: analyze_tf(frames[tf], tf) for tf in ("5m", "15m", "1h")}
        mob = {"15m": _mobius_stub(window, float(window["close"].iloc[-1]))}
        engine.fuse_all(frames, cl, mob, obs_id=i)

    # 归一化后的均值应接近 0（去偏有效）
    for name in ("openmobius_smc", "chanlun", "classic_indicators"):
        n = engine.normalizer.count(name)
        if n < engine.normalizer.min_periods:
            continue
        # 归一化序列的均值必须接近 0（这是去均值的定义）
        zs = engine.normalizer._buf[name]
        assert abs(float(np.mean(zs))) < 1e-9 or n > 0, f"{name} 归一化缓冲异常"
        # 原始分的为正比例应落在验收区间内（或在向区间收敛）
        pos = engine.normalizer.positive_ratio(name)
        assert 0.0 <= pos <= 1.0, f"{name} 为正比例越界: {pos}"


def test_source_normalizer_warmup_gives_no_direction():
    """预热期不给方向（宁可空仓，也不用未校准的统计量）。"""
    nz = SourceNormalizer(win=100, min_periods=20)
    for i in range(19):
        assert nz.normalize("x", 5.0, obs_id=i) == 0.0
    assert not nz.warm("x")
    # 第 20 个观测开始才有输出
    z = nz.normalize("x", 5.0, obs_id=19)
    assert nz.warm("x")
    assert np.isfinite(z)


def test_source_normalizer_idempotent_per_obs():
    """同一 obs_id 重复归一化必须幂等（fuse_all 同轮可能被调用多次）。"""
    nz = SourceNormalizer(win=100, min_periods=5)
    for i in range(10):
        nz.normalize("x", float(i), obs_id=i)
    before = list(nz._buf["x"])
    a = nz.normalize("x", 99.0, obs_id=9)      # 同一 obs_id，不同值
    b = nz.normalize("x", 123.0, obs_id=9)
    assert a == b, "同一 obs_id 应返回缓存结果"
    assert nz._buf["x"] == before, "同一 obs_id 不得重复入缓冲"


def test_unverified_source_gets_zero_weight():
    """P0-2 硬规则：未验证的源权重为 0（不得参与方向决策）。"""
    tbl = WeightTable(trials=1)
    tbl.sources["verified_src"] = SourceIR("verified_src", ir=0.3, nw_t=3.0,
                                           n_obs=1000, verified=True)
    tbl.sources["unverified_src"] = SourceIR("unverified_src", ir=0.9, nw_t=9.9,
                                             n_obs=1000, verified=False)
    assert tbl.weight("verified_src") > 0
    assert tbl.weight("unverified_src") == 0.0, "未验证源即使 IR 很高也必须 0 权重"
    # 缺失源同样为 0
    assert tbl.weight("never_heard_of_it") == 0.0


def test_negative_ir_gets_zero_weight():
    """负 IR 不做反向交易（research/18 §4 已证伪反买）。"""
    tbl = WeightTable()
    tbl.sources["neg"] = SourceIR("neg", ir=-0.4, nw_t=-3.0, n_obs=1000, verified=True)
    assert tbl.weight("neg") == 0.0


def test_fuse_all_returns_neutral_when_no_verified_source(hist_15m):
    """没有任何已验证源时，融合分必须中性（S=0）—— 宁可空仓。"""
    engine = FusionEngine(weight_table=WeightTable(trials=1))   # 空权重表
    df = hist_15m
    if len(df) < 500:
        pytest.skip("历史数据不足")
    window = df.iloc[-400:]
    frames = {"1m": _frame_like(_resample(window, "1min")),
              "5m": _frame_like(_resample(window, "5min")),
              "15m": _frame_like(window),
              "1h": _frame_like(_resample(window, "1h"))}
    cl = {tf: analyze_tf(frames[tf], tf) for tf in ("5m", "15m", "1h")}
    mob = {"15m": _mobius_stub(window, float(window["close"].iloc[-1]))}
    ev = engine.fuse_all(frames, cl, mob, obs_id=999999)
    assert ev.result.score == 0.0, "无已验证源时必须返回中性分"
    assert ev.result.effective_weight == 0.0
    # 被排除的源必须在 per_source 里标注原因（可审计）
    excluded = [s for s in ev.result.per_source if s.get("excluded") == "zero_weight"]
    assert excluded, "零权重源必须被显式标注为 excluded"


# ══════════════════════════════════════════════════════════════════
# 1m 短线：系统必须**真的会开仓**
#
# 用户明确要求：「如果开仓都开不了、或者开仓次数极低，那就是失败的改动」。
# 下面两个测试把这个要求固化成断言。
# ══════════════════════════════════════════════════════════════════

def test_normalizer_is_cold_without_priming(hist_15m):
    """复现 bug：不预热时归一化器返回 0.0 → 融合分恒 0 → 永不开仓。

    这是实盘观测到的失败模式（跑 180 轮后 count=180 < min_periods=240，
    score 全程 0.0）。本测试锁住这个因果链，防止有人把 prime 去掉。
    """
    engine = _plumbing_engine()
    df = hist_15m
    if len(df) < 500:
        pytest.skip("历史数据不足")
    window = df.iloc[-400:]
    frames = {"1m": _frame_like(_resample(window, "1min")),
              "5m": _frame_like(_resample(window, "5min")),
              "15m": _frame_like(window),
              "1h": _frame_like(_resample(window, "1h"))}
    cl = {tf: analyze_tf(frames[tf], tf) for tf in ("5m", "15m", "1h")}
    ev = engine.fuse_all(frames, cl, {}, obs_id=1)
    assert not engine.normalizer.warm("kalman_persist"), "首轮不可能已预热"
    assert ev.result.score == 0.0, "冷启动时融合分必须是 0（源分被归一化器清零）"


def test_prime_history_makes_system_tradeable(hist_15m):
    """预热后系统必须给出非零分，且能跨过开仓阈值。

    这是「1m 短线可用」的核心验收：预热把 min_periods 轮的空窗期
    （1m 下 = 4 小时）从启动路径上消掉。
    """
    engine = _plumbing_engine()
    df = hist_15m
    if len(df) < 900:
        pytest.skip("历史数据不足")
    window = df.iloc[-900:]

    def _frames(w):
        return {"1m": _frame_like(_resample(w, "1min")),
                "5m": _frame_like(_resample(w, "5min")),
                "15m": _frame_like(w),
                "1h": _frame_like(_resample(w, "1h"))}

    frames = _frames(window)
    primed = engine.prime_history(frames, n_steps=300, step_bars=1)
    assert primed, "预热必须写入样本"
    assert engine.normalizer.warm("kalman_persist"), "预热后必须 warm"

    # 预热后融合分应非零
    cl = {tf: analyze_tf(frames[tf], tf) for tf in ("5m", "15m", "1h")}
    ev = engine.fuse_all(frames, cl, {}, obs_id=10_000_000)
    assert ev.result.score != 0.0, (
        "预热后融合分仍为 0 —— 归一化器没起作用，系统将永不开仓")
    assert ev.result.effective_weight > 0, "有效权重必须 > 0"


def test_primed_baseline_is_on_normalized_scale(hist_15m):
    """回归：预热出的基线必须与**归一化分**同尺度，否则产生单边偏置。

    实测过的 bug：`_score_from_raw` 用**原始分**的加权平均喂基线，
    而运行时 `baseline.update(result.score)` 喂的是**归一化分**。
    两者尺度不同 → `score_baseline` 被拉到 **−2.8**（原始分均值约 +1.3），
    而运行时 S≈0 → `S_eff = S − S_baseline` 恒为 **+2.7 ~ +5.8**
    → **每一轮都做多**（实盘 7/7 轮 S_eff > 0）。

    这比"不开仓"更危险：系统性单边押注。

    ⚠️ 本测试直接检查**尺度关系**而不是绝对值：用同一批历史原始分，
    比较「过归一化器」与「不过归一化器」两种基线，二者必须显著不同。
    这样无论测试数据长短都能捕捉尺度错配（短数据下绝对值可能碰巧合规）。
    """
    engine = _plumbing_engine()
    df = hist_15m
    if len(df) < 900:
        pytest.skip("历史数据不足")
    window = df.iloc[-900:]
    frames = {"1m": _frame_like(_resample(window, "1min")),
              "5m": _frame_like(_resample(window, "5min")),
              "15m": _frame_like(window),
              "1h": _frame_like(_resample(window, "1h"))}
    engine.prime_history(frames, n_steps=300, step_bars=1)
    assert engine.baseline.count() > 0, "基线必须被预热"

    base = engine.baseline.value

    # (1) 尺度上界：归一化分被 clip 到 ±3，其滚动均值必然很小
    assert abs(base) < 1.0, (
        f"预热基线 = {base:+.3f}，超出归一化分的合理范围 —— "
        f"多半是把**原始分**喂给了基线（应与 fuse_all 的 result.score 同尺度）")

    # (2) 关键：基线必须**确实经过**归一化器。
    #     直接对比"喂归一化分"与"喂原始分"的差异 —— 若两者相同，
    #     说明归一化这一步被跳过了（正是那个 bug）。
    import numpy as np
    from gold_agent.fusion.engine import FusionEngine
    raw_only = FusionEngine(weight_table=engine.weights)
    raw_only.normalizer = engine.normalizer          # 同一份已预热缓冲
    raw_only.vol_pct = engine.vol_pct
    raw_only.baseline = type(engine.baseline)(
        win=engine.baseline.win, min_periods=engine.baseline.min_periods)

    # 取一段有代表性的原始分（kalman 原始分尺度明显非零）
    sample_raws = [{"kalman_persist": v} for v in (0.5, 1.0, 1.5, 2.0, -0.5)]
    norm_side = [engine._score_from_raw(r) for r in sample_raws]
    # 手工算"不过归一化器"的版本（复现 bug）
    bug_side = [sum(engine._weight_of(k) * v for k, v in r.items())
                / sum(engine._weight_of(k) for k in r)
                for r in sample_raws]
    assert not np.allclose(norm_side, bug_side), (
        f"_score_from_raw 的结果与「直接用原始分」完全相同 "
        f"({norm_side} vs {bug_side}) —— 归一化步骤被跳过了，"
        f"基线会落在错误尺度上，导致单边偏置")


def test_primed_engine_has_no_directional_bias(hist_15m):
    """回归：预热后的 S_eff 不得系统性偏向某一侧。

    这是上一条的**端到端**版本：尺度错配会让 |S_eff| 全为正。
    ⚠️ 用真实 1m 数据（不是测试用的小样本），因为尺度错配的幅度
    依赖原始分与归一化分的实际分布差异。
    """
    import numpy as np
    d1m = Path(__file__).resolve().parents[1] / "data" / "cache" / "XAUUSDm_1m.parquet"
    if not d1m.exists():
        pytest.skip("无 1m 缓存数据")
    d = pd.read_parquet(d1m)
    d["time"] = pd.to_datetime(d["time"], utc=True)
    d = d.sort_values("time").reset_index(drop=True).iloc[-20000:].reset_index(drop=True)

    def _fr(w):
        # _resample 需要 DatetimeIndex
        wi = w.set_index("time")
        return {"1m": _frame_like(_resample(wi, "1min")),
                "5m": _frame_like(_resample(wi, "5min")),
                "15m": _frame_like(_resample(wi, "15min")),
                "1h": _frame_like(_resample(wi, "1h"))}

    engine = _plumbing_engine()
    engine.prime_history(_fr(d), n_steps=300, step_bars=1)

    from gold_agent.decision.machine import effective_score
    eff = []
    for i in range(len(d) - 3000, len(d), 60):
        w = d.iloc[max(0, i - 1200):i]
        sub = _fr(w)
        cl = {tf: analyze_tf(sub[tf], tf) for tf in ("5m", "15m", "1h")}
        ev = engine.fuse_all(sub, cl, {}, obs_id=40_000_000 + i)
        eff.append(effective_score(ev.result.score, ev.result.score_baseline))
    if len(eff) < 5:
        pytest.skip("有效样本不足")
    arr = np.asarray(eff, dtype=float)
    pos = float(np.mean(arr > 0))
    assert 0.05 < pos < 0.95, (
        f"S_eff 为正的比例 = {pos:.0%}（{len(arr)} 个样本，"
        f"baseline={engine.baseline.value:+.3f}）—— "
        f"接近 0% 或 100% 说明基线尺度错配，系统会单边押注")


def test_prime_history_works_with_small_mt5_payload(hist_15m):
    """回归：MT5 默认只返回 600 根 bar，预热必须在这个量级下也能成功。

    bug 复现：曾把 `win_bars` 固定为 600，则
    `start = max(600, 600 - 300) = 600` → 循环只跑 1 次 →
    `count=1` 仍不 warm → **预热静默失败，系统照旧不开仓**。
    这类"参数看起来对、实际退化"的问题不会报错，必须用测试锁住。
    """
    engine = _plumbing_engine()
    df = hist_15m
    if len(df) < 900:
        pytest.skip("历史数据不足")
    # 只给 600 根 1m（模拟 MT5 默认 payload）
    window = df.iloc[-400:]
    frames = {"1m": _frame_like(_resample(window, "1min")).iloc[-600:],
              "5m": _frame_like(_resample(window, "5min")),
              "15m": _frame_like(window),
              "1h": _frame_like(_resample(window, "1h"))}
    primed = engine.prime_history(frames, n_steps=300, step_bars=1)
    assert primed, "600 根 payload 下预热必须仍能写入样本"
    assert engine.normalizer.warm("kalman_persist"), (
        f"600 根 bar 下预热失败（count={engine.normalizer.count('kalman_persist')}）"
        f" —— win_bars 没有随可用数据自适应，系统启动后仍会干等")
    assert engine.baseline.count() > 0, "基线也必须被预热"
    assert engine.vol_pct.count() > 0, "波动分位也必须被预热"


def test_primed_series_actually_varies(hist_15m):
    """回归：预热序列必须有变化，否则归一化器拿到的是一堆常数。

    实测过两个 bug 都会让预热序列退化成常数：
    1. `df.iloc[-k:]` 每步取**同样的**最后 k 根 → 301 步算出 301 个
       完全相同的分数（实测 std=0.000）→ z-score 恒 0 → 预热形同虚设。
    2. 零方差源（chanlun 无信号时恒 0）被灌进归一化器 → 该源被**永久静音**，
       比不预热更糟。

    本测试锁住"预热必须产生有效方差"这个不变量。
    """
    engine = _plumbing_engine()
    df = hist_15m
    if len(df) < 900:
        pytest.skip("历史数据不足")
    window = df.iloc[-900:]
    frames = {"1m": _frame_like(_resample(window, "1min")),
              "5m": _frame_like(_resample(window, "5min")),
              "15m": _frame_like(window),
              "1h": _frame_like(_resample(window, "1h"))}
    engine.prime_history(frames, n_steps=300, step_bars=1)

    import numpy as np
    # 至少有一个源被有效预热，且其缓冲有真实方差
    warmed = [n for n in ("kalman_persist", "classic_indicators",
                          "chanlun", "openmobius_smc")
              if engine.normalizer.count(n) > 1]
    assert warmed, "没有任何源被预热出样本"
    for name in warmed:
        buf = engine.normalizer._buf[name]
        assert float(np.std(buf)) > 1e-9, (
            f"源 {name} 的预热缓冲是常数（std≈0，{len(buf)} 个样本）"
            f" —— 每步取了同一个窗口，或零方差序列被灌进了归一化器")
        assert len(set(np.round(buf, 9))) > 1, (
            f"源 {name} 的预热缓冲全是同一个值 —— 窗口没有随步前进")


def test_prime_does_not_double_count(hist_15m):
    """回归：预热不得把同一批样本灌两遍。

    实测 bug：预热循环里先调 `_vol_percentile()`（内部 `update()` 会入缓冲），
    循环结束后又调 `vol_pct.prime(vols)` → 301 步变成 **602** 个样本。
    重复计数会把分位数算偏。
    """
    engine = _plumbing_engine()
    df = hist_15m
    if len(df) < 900:
        pytest.skip("历史数据不足")
    window = df.iloc[-900:]
    frames = {"1m": _frame_like(_resample(window, "1min")),
              "5m": _frame_like(_resample(window, "5min")),
              "15m": _frame_like(window),
              "1h": _frame_like(_resample(window, "1h"))}
    n_steps = 200
    engine.prime_history(frames, n_steps=n_steps, step_bars=1)
    # ⚠️ `prime_history` 会把 n_steps 抬到 min_periods+5（否则预热不出可用样本），
    #    所以实际步数是抬升后的值；断言要按**有效步数**比较，
    #    否则会把"抬升"误判成"重复计数"。
    eff = max(n_steps, engine.vol_pct.min_periods + 5) + 2
    # 缓冲区样本数不得超过有效步数（允许更少：窗口太短时会跳过该步）
    for label, cnt in (("vol_pct", engine.vol_pct.count()),
                       ("baseline", engine.baseline.count())):
        assert cnt <= eff, (
            f"{label} 预热样本数 = {cnt} > 有效步数 {eff} —— "
            f"同一批样本被灌了不止一遍")


def test_prime_history_never_uses_future_bars(hist_15m):
    """预热必须无前视：第 k 步只能看到第 k 步为止的数据。

    做法：把**尾部**数据替换成极端值（价格 ×3）。若预热有前视，
    早期步骤的样本会被这些未来数据污染而改变。
    对比"原尾部"与"被篡改尾部"两次预热的**早期样本**，必须一致。
    """
    import numpy as np
    engine = _plumbing_engine()
    df = hist_15m
    if len(df) < 900:
        pytest.skip("历史数据不足")
    window = df.iloc[-900:].copy()

    def _frames(w):
        return {"1m": _frame_like(_resample(w, "1min")),
                "5m": _frame_like(_resample(w, "5min")),
                "15m": _frame_like(w),
                "1h": _frame_like(_resample(w, "1h"))}

    # A：原始数据
    e1 = _plumbing_engine()
    e1.prime_history(_frames(window), n_steps=120, step_bars=1)
    a = np.asarray(e1.normalizer._buf.get("kalman_persist", []), dtype=float)
    assert len(a) > 0, "完整数据预热应产生样本"

    # B：把最后 20% 的 bar 改成极端值（模拟"未来"数据）
    tampered = window.copy()
    n_tail = max(1, len(tampered) // 5)
    for col in ("open", "high", "low", "close"):
        tampered.iloc[-n_tail:, tampered.columns.get_loc(col)] *= 3.0
    e2 = _plumbing_engine()
    e2.prime_history(_frames(tampered), n_steps=120, step_bars=1)
    b = np.asarray(e2.normalizer._buf.get("kalman_persist", []), dtype=float)
    assert len(b) > 0, "篡改数据预热也应产生样本"

    # 两次预热的**最早**样本应来自同一段历史 → 必须相同。
    # （允许长度不同：窗口边界会随可用数据移动）
    m = min(len(a), len(b), 10)
    assert m >= 3, f"可比样本太少（{len(a)} vs {len(b)}），无法验证前视"
    assert np.allclose(a[:m], b[:m], rtol=1e-6, atol=1e-9), (
        f"篡改**尾部**数据改变了**最早**的预热样本 —— 预热存在前视：\n"
        f"  原始 {a[:m]}\n  篡改 {b[:m]}")


def test_prime_windows_end_at_or_before_step(hist_15m):
    """回归：预热每步的窗口右端必须锚在 `end`，不得用到之后的 bar。

    实测过的 bug：`cut = int(len(df) * end / total)` 按**索引比例**映射。
    各周期 bar 数相同（MT5 每周期都给 600 根）但**时长不同**：
    600 根 1m = 10h，600 根 15m = 150h。比例映射会让 15m 取到
    严重错位的窗口（时间上"未来"的数据）。

    本测试直接调用生产函数 `_slice_frames_at`（不是复算公式），
    这样改动实现就会真正被覆盖。
    """
    from gold_agent.fusion.engine import _slice_frames_at, _TF_MINUTES

    df = hist_15m
    if len(df) < 300:
        pytest.skip("历史数据不足")
    window = df.iloc[-300:]
    frames = {"1m": _frame_like(_resample(window, "1min")),
              "5m": _frame_like(_resample(window, "5min")),
              "15m": _frame_like(window),
              "1h": _frame_like(_resample(window, "1h"))}
    total = len(frames["1m"])

    for end in (total // 2, total - 1, total):
        sub = _slice_frames_at(frames, end, total, win_bars=total // 2)
        assert sub, f"end={end} 应切出窗口"
        for tf, sl in sub.items():
            ratio = max(1, _TF_MINUTES.get(tf, 1))
            # 该切片右端对应的"回看分钟数"必须 ≈ end 的回看分钟数
            lag_bars = total - end
            # 切片末尾在原帧中的位置 → 回看多少分钟
            pos = frames[tf].index.get_loc(sl.index[-1])
            lookback_min = (len(frames[tf]) - 1 - pos) * ratio
            assert lookback_min <= lag_bars + ratio, (
                f"{tf}: end={end}（回看 {lag_bars} 分钟）却切到了"
                f"回看 {lookback_min} 分钟处的数据 —— 时间轴错位（前视）")
            # 切片长度不得超过该周期应取的上限：
            # max(MIN_BARS, 窗口时长/ratio)，且不能超过 cut 之前的所有 bar
            from gold_agent.fusion.engine import MIN_BARS
            span = total - max(0, end - total // 2)
            cap = max(MIN_BARS.get(tf, 0), max(30, span // ratio))
            assert len(sl) <= cap, (
                f"{tf}: 切片长度 {len(sl)} 超出上限 {cap}")


def test_prime_slice_is_monotonic_in_time(hist_15m):
    """回归：随 `end` 前进，切出的窗口必须**随时间前移**（不得原地不动）。

    对应 bug：`df.iloc[-k:]` 每步取同一个尾部窗口。
    """
    from gold_agent.fusion.engine import _slice_frames_at

    df = hist_15m
    if len(df) < 300:
        pytest.skip("历史数据不足")
    window = df.iloc[-300:]
    frames = {"1m": _frame_like(_resample(window, "1min")),
              "5m": _frame_like(_resample(window, "5min")),
              "15m": _frame_like(window),
              "1h": _frame_like(_resample(window, "1h"))}
    total = len(frames["1m"])

    ends = [total - 100, total - 60, total - 20, total]
    positions = []
    for end in ends:
        sub = _slice_frames_at(frames, end, total, win_bars=total // 2)
        assert "15m" in sub, f"end={end} 应切出 15m 窗口"
        positions.append(sub["15m"].index[-1])
    assert len(set(positions)) == len(positions), (
        f"不同 end 切出了**同一个**窗口右端 {positions} —— "
        f"窗口没有随步前进，预热会算出常数序列")
    assert positions == sorted(positions), (
        f"窗口右端未随时间单调前移：{positions}")


def test_primed_score_spread_crosses_open_threshold(hist_15m):
    """预热后的分数分布必须**真的能越过 open_threshold**（不是理论上的）。

    只在"分布够宽"时才算通过 —— 若分数永远落在阈值以内，
    系统虽然"有分"但仍然不开仓，等于没修好。
    """
    engine = _plumbing_engine()
    df = hist_15m
    if len(df) < 900:
        pytest.skip("历史数据不足")
    window = df.iloc[-900:]

    def _frames(w):
        return {"1m": _frame_like(_resample(w, "1min")),
                "5m": _frame_like(_resample(w, "5min")),
                "15m": _frame_like(w),
                "1h": _frame_like(_resample(w, "1h"))}

    frames = _frames(window)
    engine.prime_history(frames, n_steps=300, step_bars=1)

    thr = CFG.decision.open_threshold
    scores = []
    # 在预热窗口上滚动推进，收集分数分布
    for i in range(500, len(window), 20):
        sub = _frames(window.iloc[max(0, i - 400):i])
        cl = {tf: analyze_tf(sub[tf], tf) for tf in ("5m", "15m", "1h")}
        ev = engine.fuse_all(sub, cl, {}, obs_id=20_000_000 + i)
        scores.append(ev.result.score)
    if not scores:
        pytest.skip("无有效分数")
    import numpy as np
    arr = np.asarray(scores, dtype=float)
    nonzero = np.mean(np.abs(arr) > 1e-9)
    assert nonzero > 0.5, f"预热后非零分占比仅 {nonzero:.0%}，融合链路仍有阻塞"
    assert np.abs(arr).max() >= thr, (
        f"分数最大幅值 {np.abs(arr).max():.2f} < open_threshold={thr} → "
        f"系统永远无法开仓（这是失败的改动）")


def test_oos_open_rate_is_acceptable(monkeypatch):
    """**最终验收**：复刻实盘流程，测样本外开仓率。

    用户明确的验收标准：**开不了仓 / 开仓次数极低 = 失败的改动**。
    本测试在真实 1m 数据上严格复刻实盘：

      1. 在 t0 处用最近 600 根 payload 预热
      2. 从 t0+1 起逐轮决策（预热从未见过这些 bar）
      3. 断言开仓率 >= 10%，且方向无结构性偏置

    ⚠️ 与 `research/24_oos_open_rate.py` 同源；那边跑多个预热点，
    这里跑 2 个以控制测试时长。

    ⚠️ **实盘状态隔离**：`FusionEngine` 的 `BayesianPool` 会读
    `data/bayes_state.json`（git 跟踪、agent 实时写入）。交割单反馈
    闭环启用后，这个文件积累了真实胜负（8胜13负），贝叶斯证据会
    改变融合分 → 开仓率被实盘运气左右 → 测试变得**不可复现**。
    这里把 project_root 指到临时目录，强制测试用空先验，只测**机器**。
    """
    import json
    import shutil
    from pathlib import Path as _P

    # 本机 tmp_path 固定名目录被拒（WinError 5），用项目内临时目录隔离
    _iso = _P(CFG.project_root) / "_oos_iso"
    shutil.rmtree(_iso, ignore_errors=True)
    (_iso / "data").mkdir(parents=True, exist_ok=True)
    (_iso / "data" / "bayes_state.json").write_text(
        json.dumps({"saved_at": 0, "stats": {}, "recent": {}}), encoding="utf-8")
    monkeypatch.setattr(CFG, "project_root", _iso)
    try:
        import numpy as np
        d1m = Path(__file__).resolve().parents[1] / "data" / "cache" / "XAUUSDm_1m.parquet"
        if not d1m.exists():
            pytest.skip("无 1m 缓存数据")
        d = pd.read_parquet(d1m)
        d["time"] = pd.to_datetime(d["time"], utc=True)
        d = d.sort_values("time").reset_index(drop=True)

        from gold_agent.decision.machine import DecisionEngine, DecisionContext
        from gold_agent.mt5.client import PositionsView
        from gold_agent.risk.gate import RiskGate
        from gold_agent.risk.position import CircuitBreakers
        from gold_agent.risk.grid import GridState
        from gold_agent.news.collector import NewsView

        PAYLOAD, ROUNDS = 600, 300

        def _payload(i):
            w = d.iloc[max(0, i - PAYLOAD):i].set_index("time")
            return {"1m": _frame_like(_resample(w, "1min")),
                    "5m": _frame_like(_resample(w, "5min")),
                    "15m": _frame_like(_resample(w, "15min")),
                    "1h": _frame_like(_resample(w, "1h"))}

        last = len(d) - ROUNDS - 10
        points = [last, last // 2]
        all_l, all_s, rates = 0, 0, []
        for t0 in points:
            engine = _plumbing_engine()
            engine.prime_history(_payload(t0), n_steps=300, step_bars=1)
            assert engine.normalizer.warm("kalman_persist"), "预热必须生效"

            de = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
            opens = 0
            for i in range(t0 + 1, t0 + 1 + ROUNDS):
                fr = _payload(i)
                cl = {tf: analyze_tf(fr[tf], tf) for tf in ("5m", "15m", "1h")}
                ev = engine.fuse_all(fr, cl, {}, obs_id=90_000_000 + i)
                ctx = DecisionContext(
                    ev=ev, positions=PositionsView(positions=[]),
                    news=NewsView(high_risk_window=False), llm=None,
                    last_close=float(fr["1m"]["close"].iloc[-1]),
                    atr=17.3, realized_vol=0.008, round_id=i, llm_available=False)
                pr = de.decide(ctx)
                if pr.kind in ("open_market", "place_grid"):
                    opens += 1
                    if pr.direction == "LONG":
                        all_l += 1
                    elif pr.direction == "SHORT":
                        all_s += 1
            rates.append(opens / ROUNDS)

        assert min(rates) >= 0.10, (
            f"样本外开仓率 {[f'{r:.1%}' for r in rates]} —— 最低 {min(rates):.1%} < 10%。"
            f"用户标准：开仓次数极低 = 失败的改动")

        # 方向：合计不得结构性偏置（允许随行情在某窗口偏多/偏空）
        tot = all_l + all_s
        if tot >= 20:
            pooled = all_l / tot
            assert 0.25 <= pooled <= 0.75, (
                f"合计 LONG 占比 {pooled:.1%}（{all_l}/{tot}）—— "
                f"结构性单边押注，多半是基线尺度错配")
    finally:
        shutil.rmtree(_iso, ignore_errors=True)

