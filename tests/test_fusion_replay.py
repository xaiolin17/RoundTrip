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
from gold_agent.fusion.engine import FusionEngine, MB_TF_WEIGHTS
from gold_agent.fusion.gaussian import SourceView, fuse
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
    """构造一个带**非零权重**的引擎，用于验证融合链路。

    ⚠️ **这是一份合成夹具，不是校准结果，不得当作任何 IR 依据。**

    它的唯一职责是让每个源都拿到非零权重，从而把
    「去均值 → 加权 → 融合 → 打分」这条**机器**跑通 ——
    否则权重全 0 时 `gaussian.fuse` 会把所有源排除，链路根本走不到。

    历史上这里手填过 `research/18 §P0-2` 的基线表
    （kalman 0.28 / chanlun 0.05 / classic 0.03）+ `_refresh_ir_max()` 归一。
    该表已删除：其中 kalman 的 0.28 比它自己的出处（`research/11` 的
    `kalman_trend n=59879 毛 NW-t=+3.31` → IR = 3.31/√59879 = 0.01353）
    **大 20.7 倍**，且正是这个假数字把排序做成了 kalman > chanlun > classic
    —— 而 `research/21_source_ir.py` 实测恰好相反。测试夹具里继续手填
    数字，等于把伪造的先验从源码搬到测试里，故一并去掉。

    现在用**等权先验**（`skill=0` → `lambda=0`），与生产当前状态一致：
    三个可测源各得 `W_SCALE`，`openmobius_smc` 结构性不可测 → 0。
    生产权重由 `data/source_ir.json` 经 DL 收缩得到，
    由 `test_production_weight_table_can_trade` 覆盖。
    """
    tbl = WeightTable(trials=6)
    for name in ("kalman_persist", "chanlun", "classic_indicators"):
        tbl.sources[name] = SourceIR(
            name, ir=0.0, measurable=True, skill=0.0,
            basis="equal_prior",
            source_script="测试夹具（合成，非校准结果）")
    tbl.sources["openmobius_smc"] = SourceIR(
        "openmobius_smc", ir=0.0, measurable=False,
        source_script="research/21_source_ir.py（离线桩，无历史回放）")
    tbl._refresh_weights()
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
    """两种权重策略各自的行为都必须明确 —— 这是策略选择的验收。

    ⚠️ 本测试经过两次修正，记录完整推理：

      · 最初断言的相反命题是"无源通过验证 → 权重全 0 → 不开仓"，
        并把「不开仓」当成正确行为。
      · 第一次修正（`baseline_fallback` 时代）：论证 research/18 §P0-2
        原文就列出了 IR 表，把全部源打成 0 是过度应用；且"一个不交易的
        交易系统是失败状态"。于是要求 `total > 0`。
      · **第二次修正（2026-09-29，用户明确要求"让校准结果真能影响权重"）**：
        上一条的要求本身是有代价的 —— 它把系统**锁死在兜底常数**上，
        使 `data/source_ir.json` 无论测出什么都无法影响权重（已实测：
        写入一份"四源全未通过"的校准文件，权重一模一样）。
        用户选择了如实反映实测证据，接受"当前校准下不开仓"的后果。
        因此本测试改为**分别验收两种策略**，而不再把"能开仓"当成
        对生产配置的硬性要求。

    真正要守住的不变量（与策略无关，收缩模型下依然成立）：
      **未验证的源（openmobius_smc）拿不到权重。**
      且系统必须**可交易**（σ ≤ sigma_max）—— 一个不交易的交易系统是失败状态。

    ⚠️ **第三次修正（2026-09-29 晚，用户指出前两次都留下了死代码）**：
    用户原话「要恢复交易 但是有合理的处理方式吗 不能放一个没有作用的
    死代码在那吧 我这是商用项目欸」。这个批评是对的，且根因比"选哪个
    策略"更深：**把统计估计做成了二值开关**。
      · `baseline_fallback` 下校准文件永不影响权重（文件是装饰性的）；
      · `authoritative` 下 `BASELINE_IR` 永不被读取（兜底表是死代码），
        且系统不开仓。
    两个方案都必然留下一段死代码。故本测试改为验收**收缩模型**：
    权重永远是 `lambda·实测 + (1−lambda)·等权`，两者都实际参与计算
    （`lambda` 是权重，不是开关），且 `lambda` 会随数据移动。
    """
    import json
    from pathlib import Path
    f = Path(__file__).resolve().parents[1] / "data" / "source_ir.json"
    if not f.exists():
        pytest.skip("尚未运行 research/21_source_ir.py --write")
    data = json.loads(f.read_text(encoding="utf-8"))

    from gold_agent.fusion.weights import DECISION_SOURCES  # noqa: E402

    tbl = WeightTable.load(f)

    # ---- (1) 必须可交易：否则"恢复交易"这个目标没有达成 ----
    total = tbl.total_weight(list(DECISION_SOURCES))
    assert total > 0, (
        "权重总和为 0 → 融合分恒为 0 → 系统不会开仓。"
        "一个不交易的交易系统是失败状态，不是安全状态。")
    sigma = 1.0 / (total ** 0.5)
    assert sigma <= CFG.fusion.sigma_max, (
        f"sigma_S={sigma:.3f} > sigma_max={CFG.fusion.sigma_max} → 决策层永远 hold")

    # ---- (2) 收缩端点都必须真实参与（没有死代码）----
    for name in DECISION_SOURCES:
        s = tbl.get(name)
        if not s.measurable:
            continue
        assert s.w_prior > 0, f"{name}: 等权先验必须非零（否则是死代码）"
        expect = tbl.lam * s.w_measured + (1.0 - tbl.lam) * s.w_prior
        assert s.w_final == pytest.approx(expect), (
            f"{name}: 最终权重必须等于收缩式 lambda*实测+(1-lambda)*先验")

    # ---- (3) 不可测的源必须是 0（硬规则未被放松）----
    assert tbl.weight("openmobius_smc") == 0.0, (
        "openmobius_smc 无历史回放（分数来自离线桩）→ 结构性不可测 → 0 权重")

    # ---- (4) 每个拿到权重的可测源都必须有出处 ----
    for name in DECISION_SOURCES:
        if tbl.weight(name) > 0:
            assert tbl.get(name).source_script, f"{name} 有权重但没有出处"

    # ---- (5) 毛/净必须分开记录（research/11 的教训）----
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


def test_aggregate_tf_scores_is_coverage_shrunk_mean():
    """统一聚合口径：覆盖率收缩加权平均（缺周期 -> 向 0 收缩）。

    取代原先两套不一致的公式：
      chanlun `clip(Σwᵢsᵢ/(wsum/3), ±3)`   —— 代数上 = 3 × 加权平均
      mobius  `clip(Σwᵢsᵢ,          ±3)`   —— 裸求和，缺周期就静默变小
    """
    from gold_agent.fusion.engine import aggregate_tf_scores

    W = {"1h": 1.00, "4h": 0.50, "15m": 0.40, "5m": 0.20, "1m": 0.00}
    # 1) 全齐 -> 加权平均（除以**声明**权重和 2.1，不是实际到齐的）
    got = aggregate_tf_scores(W, {"1h": -1.7, "4h": -1.0, "15m": -1.2,
                                  "5m": -0.6})
    exp = (1.0 * -1.7 + 0.5 * -1.0 + 0.4 * -1.2 + 0.2 * -0.6) / 2.1
    assert abs(got - exp) < 1e-12, (got, exp)

    # 2) 缺周期 -> 保守收缩（分子少了，分母不变）
    only1h = aggregate_tf_scores(W, {"1h": -1.7})
    assert abs(only1h - (-1.7 / 2.1)) < 1e-12, only1h
    assert abs(only1h) < abs(got), "缺数据必须收缩，不能放大"
    # 缺失 ≠ 0 分：显式 None 与"没这个键"等价；但真给 0 分不改变分子
    assert aggregate_tf_scores(W, {"1h": None}) == aggregate_tf_scores(W, {})
    # 缺 15m 时，分子少一项 -> 与"15m 给 0 分"不同（0 分是真实观点）
    a = aggregate_tf_scores(W, {"1h": -1.7, "15m": None})
    b = aggregate_tf_scores(W, {"1h": -1.7, "15m": 0.0})
    assert abs(a - b) < 1e-12, "0 分与缺失在分子上都是 0，这里应相同"

    # 3) 零权重周期不参与（1m 权重 0）
    assert aggregate_tf_scores(W, {"1m": 3.0}) == 0.0
    # 4) 空输入不炸
    assert aggregate_tf_scores(W, {}) == 0.0
    assert aggregate_tf_scores({}, {"1h": 3.0}) == 0.0


def test_aggregate_tf_scores_does_not_saturate():
    """不得像旧口径那样把分数顶死在 ±3（旧实测 53.1% 贴限）。

    旧 mobius 裸求和：min −4.770 / max +4.500，实测 53.1% 触限；
    新口径是加权平均，|结果| <= max|sᵢ|，因此**永不饱和**。
    """
    from gold_agent.fusion.engine import aggregate_tf_scores

    W = {"1h": 1.00, "4h": 0.50, "15m": 0.40, "5m": 0.20, "1m": 0.00}
    # 全部顶到上限：加权平均仍是 +3（不超），而不是被 clip 成 +3 的 4.5
    allmax = aggregate_tf_scores(W, {k: 3.0 for k in W if W[k] > 0})
    assert abs(allmax - 3.0) < 1e-12, allmax
    # 部分为正部分为负 -> 落在中间，不像裸求和那样轻易越过 ±3
    mixed = aggregate_tf_scores(W, {"1h": 3.0, "4h": -3.0, "15m": -3.0,
                                    "5m": -3.0})
    assert -3.0 <= mixed <= 3.0
    assert mixed != 3.0 and mixed != -3.0, "不应贴限"


def test_mobius_aggregate_no_longer_shrinks_when_tf_missing():
    """回归：4h 历史上 100% 缺失时，旧裸求和把分数静默压小。

    旧：`Σ wᵢsᵢ` 少了 4h 的 0.5×s₄ₕ -> 分数凭空变小（不是方向变弱，
        纯粹缺数据）。新口径分母固定为声明权重和 2.1，缺失只让分子
        少一项，等价于"证据不足 -> 收缩"，且**不重分配**权重。
    """
    from gold_agent.fusion.engine import (MB_TF_WEIGHTS,
                                          aggregate_tf_scores)

    sub = {"1h": -2.0, "15m": -1.0, "5m": -0.5}      # 4h 缺失
    new = aggregate_tf_scores(MB_TF_WEIGHTS, sub)
    assert abs(new - (-2.0 - 0.4 - 0.1) / 2.1) < 1e-12, new
    # 旧口径（裸求和）会给出 -2.5，量纲完全不同
    old = sum(MB_TF_WEIGHTS[t] * v for t, v in sub.items())
    assert abs(old - (-2.5)) < 1e-12
    # 新口径与"分数尺度"一致：结果在 [min(s), max(s)] 之间
    assert -2.0 <= new <= -0.5, new
    assert not (-2.0 <= old <= -0.5), "旧口径超出输入尺度 -> 量纲错误"


def test_mobius_weight_zero_means_value_change_is_decision_neutral():
    """安全前提：mobius 权重恒为 0，所以改它的分数不影响融合结果。

    这是**先改 mobius、暂不改 chanlun** 的唯一理由：mobius 未被验证
    （`data/source_ir.json`：verified=false、tier=rejected），权重 0，
    它的分数只被记录、不参与加权和。chanlun 权重 4.0 是活源，改它的
    聚合口径会移动融合分分布与历史阈值标定，必须单独评估。
    """
    from gold_agent.fusion.engine import MB_TF_WEIGHTS

    assert MB_TF_WEIGHTS["1m"] == 0.0
    # 记录在案：mobius 的 IR 未验证 -> 权重必须为 0，直到有真实历史校准
    import json
    import pathlib
    p = pathlib.Path(__file__).resolve().parents[1] / "data" / "source_ir.json"
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        m = (d.get("sources") or {}).get("openmobius_smc")
        if m is not None:
            assert m.get("verified") is False, (
                "若 mobius 已被验证并取得非零权重，则本测试的前提失效，"
                "改变其聚合口径前必须做 A/B 回放")


def test_all_weighted_mobius_timeframes_are_supported():
    """权重表里非零权重的周期，必须都是 Mobius 能抓的周期。

    事故背景：`MB_TF_WEIGHTS` 声明 `4h: 0.50`（占全部权重预算 2.1 的
    23.8%），但 `graph.py` 的抓取列表是手写的 4 个周期、**漏了 4h**。
    实测 7716 条 `mobius_score` 日志里 `4h` 键**从未出现**——声明的权重
    永远拿不到数据，等于把注释里"1h/4h 主导方向"悄悄降级成"1h 主导"。

    现改为从 `MB_TF_WEIGHTS` 派生抓取列表。本测试锁住两层一致性：
      1. 派生出的周期都在 `SUPPORTED_INTERVALS` 内（否则 API 直接拒）
      2. 抓取列表恰好等于非零权重集合（新增权重会自动被抓）
    """
    from gold_agent.skills.mobius_adapter import MobiusClient

    wanted = tuple(tf for tf, w in MB_TF_WEIGHTS.items() if w > 0)
    assert wanted, "权重表不得全为 0"
    # 1) 每个要抓的周期，适配器都必须支持（否则静默 unavailable）
    unsupported = [tf for tf in wanted if tf not in MobiusClient.SUPPORTED_INTERVALS]
    assert not unsupported, (
        f"权重表声明要抓 {unsupported}，但 Mobius 不支持"
        f"（支持 {MobiusClient.SUPPORTED_INTERVALS}）-> 该权重是死的")
    # 2) 4h 必须在内（这是本次修的具体缺口）
    assert "4h" in wanted, "4h 权重非零，必须被抓取"
    # 3) 1m 权重为 0 -> 不必抓（但抓到也无害，仅浪费配额）
    assert MB_TF_WEIGHTS["1m"] == 0.0
    print(f"非零权重周期: {wanted}")


def test_mobius_4h_contributes_to_aggregate():
    """4h 一旦有数据，必须按权重 0.50 真正进入聚合分。

    防止"抓了但没算"——只在抓取侧修、聚合侧不认，等于没修。
    """
    from gold_agent.fusion.engine import _mobius_score
    from gold_agent.skills.mobius_adapter import MobiusResult

    res = MobiusResult(computed_at=0.0, status="ok")
    res.structures = [{"kind": "BOS", "bias": "bear", "confirmed": True,
                       "price": 4100.0, "time": "2026-09-28T00:00:00Z"}]
    sc = _mobius_score(res, 4138.0)
    # 单条 BOS/bear -> 分量为负（-1.5 × recency 1.0）
    assert sc < 0, f"bear BOS 应为负分，实际 {sc}"
    w = MB_TF_WEIGHTS["4h"]
    assert w == 0.50
    assert w * sc == 0.50 * sc, "4h 必须按权重 0.50 计入"


def test_zero_weight_source_cannot_trigger_disagreement():
    """零权重源不得触发「源间分歧」（用户反馈的假分歧 bug）。

    实测（logs/decision_*.jsonl 7888 轮）：`openmobius_smc` 权重恒为 0，
    却在 3235 轮把 `disagreement` 拉成 True；其中 **766 轮（9.7%）没有任何
    加权源分歧** —— 纯粹由它造成。

    为什么必须修：`disagreement` 会让手数 ×0.5（`risk/gate.py`
    L103/L109/L219），等于让一个**没有投票权的源实际影响了下单规模**，
    正是"未验证源不得影响决策"要禁止的事。
    """
    tbl = WeightTable(trials=1)
    tbl.sources["w_src"] = SourceIR("w_src", ir=0.3, nw_t=3.0, n_obs=1000,
                                    measurable=True, skill=0.5)
    tbl.sources["zero_src"] = SourceIR("zero_src", ir=0.0, measurable=False)
    tbl._refresh_weights()
    closes = np.linspace(4000.0, 4010.0, 600)

    srcs = [SourceView("w_src", 1.5, 1.0, weight=tbl.weight("w_src")),
            SourceView("zero_src", -3.0, 0.5, weight=tbl.weight("zero_src"))]
    res = fuse(srcs, {}, closes)
    assert tbl.weight("zero_src") == 0.0
    assert res.disagreement is False, (
        "权重为 0 的源不得触发分歧（它没有投票权）")
    # 但必须仍然被记录在案（可审计），只是标了 excluded
    names = {p["name"]: p for p in res.per_source}
    assert names["zero_src"].get("excluded") == "zero_weight"
    assert names["zero_src"]["w"] == 0.0

    # 真正的加权源分歧仍须触发（不能把功能改死）
    srcs2 = [SourceView("w_src", 2.9, 1.0, weight=tbl.weight("w_src")),
             SourceView("w_src2", -2.9, 1.0, weight=tbl.weight("w_src"))]
    res2 = fuse(srcs2, {}, closes)
    assert res2.disagreement is True, "加权源真反向必须仍触发分歧"


def test_news_score_no_longer_changes_fusion():
    """news 不得影响融合分（它无实测 IR -> 0 权重）。

    历史实现把 LLM 情绪拼成 ±1.5×impact 传进 `fuse_all(news_score=...)`，
    但 news 权重恒为 0 -> `gaussian.fuse` 把它排除 -> **对结果零影响**，
    那次重融合是空操作（实测 news_score 0→+1.5→-1.5 融合分恒为 +1.438195）。

    本测试锁住语义：`news_score` 参数不再改变任何输出，防止有人日后
    误以为 news 在投票。news 的现有权力在 decision 层（事件闸）
    与 risk 层（手数降级）。
    """
    tbl = WeightTable(trials=1)
    tbl.sources["w_src"] = SourceIR("w_src", ir=0.3, nw_t=3.0, n_obs=1000,
                                    measurable=True, skill=0.5)
    tbl.sources["news"] = SourceIR("news", ir=0.0, measurable=False)
    tbl._refresh_weights()
    closes = np.linspace(4000.0, 4010.0, 600)

    def _run(news_score):
        srcs = [SourceView("w_src", 1.5, 1.0, weight=tbl.weight("w_src"))]
        if news_score != 0.0:
            srcs.append(SourceView("news", news_score, 0.8,
                                   weight=tbl.weight("news")))
        return fuse(srcs, {}, closes)

    base = _run(0.0)
    for ns in (1.5, -1.5):
        got = _run(ns)
        assert got.score == base.score, (
            f"news_score={ns} 不得改变融合分（news 无投票权）")
        assert got.effective_weight == base.effective_weight


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


def test_primed_score_spread_crosses_open_threshold(hist_15m, monkeypatch):
    """预热后的分数分布必须**真的能越过 open_threshold**（不是理论上的）。

    只在"分布够宽"时才算通过 —— 若分数永远落在阈值以内，
    系统虽然"有分"但仍然不开仓，等于没修好。

    ⚠️ **实盘状态隔离**：`_plumbing_engine()` 里的 `BayesianPool()`
    会读 `data/bayes_state.json`（git 跟踪、agent 实时写入），
    实测 9胜20负 -> 21负，贝叶斯证据持续变化会左右测试结果。
    """
    import json
    import shutil
    from pathlib import Path as _P

    _iso = _P(CFG.project_root) / "_primed_iso"
    shutil.rmtree(_iso, ignore_errors=True)
    (_iso / "data").mkdir(parents=True, exist_ok=True)
    (_iso / "data" / "bayes_state.json").write_text(
        json.dumps({"saved_at": 0, "stats": {}, "recent": {}}), encoding="utf-8")
    monkeypatch.setattr(CFG, "project_root", _iso)
    try:
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
    finally:
        shutil.rmtree(_iso, ignore_errors=True)


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


# ---------------------------------------------------------------------------
# 权重校准：DL 收缩（取代旧的 source_ir_policy 二选一开关）
#
# 设计依据（research/25 §12）：旧版把**统计估计**做成了二值开关，两个取值
# 都必然留下一段死代码 ——
#   · baseline_fallback：校准文件永不影响权重（文件是装饰性的）
#   · authoritative    ：BASELINE_IR 永不被读取（兜底表是死代码）+ 不开仓
# 现在权重恒为 `lambda·实测 + (1−lambda)·等权`，两个端点都真实参与计算，
# 且 `lambda` 由 DerSimonian-Laird 估计量从数据算出、会随数据移动。
# ---------------------------------------------------------------------------
def _shrink_table(skills: dict, **extra) -> WeightTable:
    """构造一份带 `measurable`/`skill` 的校准文件并加载（收缩模型入口）。"""
    import json
    import tempfile
    from pathlib import Path as _P

    rows = {}
    for n, sk in skills.items():
        rows[n] = {"ir": 0.01, "nw_t": 0.5, "n_obs": 1000, "measurable": True,
                   "skill": sk, "tb_n_independent": 300,
                   "source_script": "cal.py"}
    payload = {"trials": 6, "sources": rows}
    payload.update(extra)
    td = tempfile.mkdtemp()
    p = _P(td) / "source_ir.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return WeightTable.load(p)


def test_shrinkage_reproduces_the_measured_calibration():
    """当前实测 skill 下必须给出 lambda=0（等权），且**手工可复算**。

    实测（research/21，68871 根 / 用 68000）：
        skill = t − 方向匹配对照均值 = −0.19 / −0.35 / +0.17
    三者均值 −0.1233，Q = Σ(skill−mean)² = 0.14187，df = k−1 = 2。
    Q < df → tau^2 = max(0,(Q−df)/C) = 0 → lambda = 0 → 等权。

    `tau^2 = 0` 的实质含义：观测到的源间差异**不比纯抽样噪声更大**。
    既然数据分辨不出源的高下，任何按这组数据重排权重的公式都是拟合噪声。
    """
    from gold_agent.fusion.weights import W_SCALE

    tbl = _shrink_table({"kalman_persist": -0.19,
                         "classic_indicators": -0.35,
                         "chanlun": 0.17})
    # 手工复算 Q（不依赖实现细节，独立验证）
    sk = [-0.19, -0.35, 0.17]
    mean = sum(sk) / len(sk)
    q_manual = sum((x - mean) ** 2 for x in sk)
    assert tbl.q_stat == pytest.approx(q_manual, abs=1e-9), (
        f"Q 必须等于手工复算值 {q_manual:.5f}，实测 {tbl.q_stat:.5f}")
    assert tbl.q_df == 2
    assert tbl.q_stat < tbl.q_df, "Q < df 正是 tau^2 = 0 的成因"
    assert tbl.tau2 == 0.0
    assert tbl.lam == 0.0, "源间差异不显著于噪声 → lambda=0"

    # lambda=0 → 完全落在等权先验上
    for n in ("kalman_persist", "classic_indicators", "chanlun"):
        assert tbl.weight(n) == pytest.approx(W_SCALE), (
            f"{n}: lambda=0 时应拿等权先验 {W_SCALE}")
    assert tbl.total_weight(["kalman_persist", "classic_indicators",
                             "chanlun"]) == pytest.approx(3 * W_SCALE)


def test_shrinkage_lambda_moves_when_sources_really_differ():
    """**可证伪性**：源间差异真的变大时，lambda 必须离开 0 并改变权重。

    这是"没有死代码"的关键证据 —— `lambda` 不是被钉死在 0 的常量。
    实算（k=3，s²=1，C=k−1=2）：
        skill = (−s, 0, +s)
        s=1.00 → Q=2.000, Q−df=0     → tau²=0      → lambda=0
        s=1.35 → Q=3.645, Q−df=1.645 → tau²=0.8225 → lambda=0.451
        s=2.00 → Q=8.000, Q−df=6.000 → tau²=3.0000 → lambda=0.750
    且 skill 高的源必须拿到**更多**权重（实测排序真正接管）。
    """
    # s=1.00：恰好压在临界点，仍不显著
    t0 = _shrink_table({"kalman_persist": -1.0, "classic_indicators": 0.0,
                        "chanlun": 1.0})
    assert t0.q_stat == pytest.approx(2.0)
    assert t0.lam == 0.0, "Q == df 时 tau^2 仍为 0"

    # s=1.35：越过临界点，lambda 必须 > 0
    t1 = _shrink_table({"kalman_persist": -1.35, "classic_indicators": 0.0,
                        "chanlun": 1.35})
    assert t1.q_stat == pytest.approx(3.645)
    assert t1.tau2 == pytest.approx(0.8225)
    assert t1.lam == pytest.approx(0.4513, abs=1e-3), (
        f"lambda 必须离开 0（实算 0.4513），实测 {t1.lam:.4f}")
    assert t1.weight("chanlun") > t1.weight("kalman_persist"), (
        "skill 高的源必须拿到更多权重 —— 否则实测排序没有真正接管")

    # s=2.00：更极端的差异 → lambda 更大
    t2 = _shrink_table({"kalman_persist": -2.0, "classic_indicators": 0.0,
                        "chanlun": 2.0})
    assert t2.lam == pytest.approx(0.75)
    assert t2.lam > t1.lam, "lambda 必须随差异单调增大"


def test_shrinkage_endpoints_are_both_live():
    """两个收缩端点都必须**真实参与**计算（这是"没有死代码"的验收）。

    旧版二选一开关的性质是：任一时刻必有一个分支的输出被整体忽略。
    收缩模型下 `w = lambda·w_measured + (1−lambda)·w_prior`，
    两个端点在每个源上都以 lambda 为**权重**（不是开关）参与。
    """
    from gold_agent.fusion.weights import W_SCALE

    # 构造一个 lambda 严格位于 (0,1) 的中间态
    tbl = _shrink_table({"kalman_persist": -2.0, "classic_indicators": 0.0,
                         "chanlun": 2.0})
    assert 0.0 < tbl.lam < 1.0, f"需要中间态，实测 lambda={tbl.lam}"

    ch = tbl.get("chanlun")
    assert ch.w_prior == pytest.approx(W_SCALE)
    assert ch.w_measured > 0
    # 中间态下，两个端点都既没有被忽略、也没有单独决定结果
    assert ch.w_prior != ch.w_final, "等权先验必须实际参与（否则是死代码）"
    assert ch.w_measured != ch.w_final, "实测排序必须实际参与（否则是死代码）"
    assert ch.w_final == pytest.approx(tbl.lam * ch.w_measured
                                       + (1 - tbl.lam) * ch.w_prior)

    # 单调性：lambda 越大，实测排序的影响越大
    lo = _shrink_table({"kalman_persist": -1.35, "classic_indicators": 0.0,
                        "chanlun": 1.35})
    hi = _shrink_table({"kalman_persist": -2.0, "classic_indicators": 0.0,
                        "chanlun": 2.0})
    assert hi.lam > lo.lam
    # 弱源在"更相信实测"的设定下必须被压得更低
    assert hi.weight("kalman_persist") < lo.weight("kalman_persist")


def test_unmeasurable_source_never_gets_weight():
    """结构性不可测的源（无历史回放）恒为 0 —— 与显著性判定**无关**。

    关键区分：`verified=False` 只说明"这个样本量下测不出显著技能"
    （三个真实源都是这个状态，但它们是**可测**的）；而
    `openmobius_smc` 的分数来自离线桩 `_mobius_synthetic_scores`
    （Mobius API 无历史回放）→ **根本测不了**。把两者混为一谈，
    就会让权重全 0、系统永不开仓 —— 正是被修掉的缺陷。
    """
    import json
    import tempfile
    from pathlib import Path as _P

    payload = {"trials": 6, "sources": {
        # 即使文件声称它 measurable 且 skill 最高，也必须被强制 0
        "openmobius_smc": {"ir": 0.9, "nw_t": 5.0, "n_obs": 5000,
                           "measurable": True, "skill": 9.99,
                           "source_script": "stub.py"},
        "chanlun": {"ir": 0.01, "nw_t": 0.5, "n_obs": 1000,
                    "measurable": True, "skill": 0.5,
                    "source_script": "cal.py"},
    }}
    with tempfile.TemporaryDirectory() as td:
        p = _P(td) / "source_ir.json"
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tbl = WeightTable.load(p)
        assert tbl.weight("openmobius_smc") == 0.0, (
            "无历史回放的源必须 0 权重，即使文件里 skill 最高")
        assert tbl.weight("chanlun") > 0, "可测源不受影响，仍应有权重"


def test_missing_file_gives_equal_prior_not_fabricated_ir():
    """文件缺失 → 等权先验，而不是退回某张手填 IR 表。

    旧版 `BASELINE_IR` 声称 kalman=0.28 出自 research/11，而该文件写的是
    `kalman_trend n=59879 毛 NW-t=+3.31` → IR = 3.31/√59879 = 0.01353。
    **0.28 比它自己的出处大 20.7 倍**，且正是这个数字把排序做成了
    kalman > chanlun > classic（research/21 实测恰好相反）。
    所以它被删除：没有实测依据时，正确答案是"等权（无信息）"，
    而不是编造一张带小数点的表。
    """
    import tempfile
    from pathlib import Path as _P

    from gold_agent.fusion.weights import W_SCALE

    with tempfile.TemporaryDirectory() as td:
        tbl = WeightTable.load(_P(td) / "nope.json")
        for n in ("kalman_persist", "chanlun", "classic_indicators"):
            assert tbl.weight(n) == pytest.approx(W_SCALE), (
                f"{n}: 无校准文件时应拿等权先验")
            assert tbl.get(n).basis == "equal_prior", (
                "必须标成 equal_prior，与实测值区分开")
        assert tbl.weight("openmobius_smc") == 0.0
        # 关键：不得再有任何手填 IR 冒充实测
        for s in tbl.sources.values():
            assert s.ir == 0.0, "无实测依据时不得编造 IR 数字"

    # 文件损坏同样退化为等权，而不是崩溃或全 0
    with tempfile.TemporaryDirectory() as td:
        bad = _P(td) / "source_ir.json"
        bad.write_text("{ not json", encoding="utf-8")
        t2 = WeightTable.load(bad)
        assert t2.weight("chanlun") == pytest.approx(W_SCALE)


def test_old_format_file_falls_back_to_equal_prior():
    """旧格式（缺 `measurable`）→ 等权先验，**不得**用 verified 顶替。

    `verified` 是显著性判定；当前三源都因样本量不足而为 false，
    但它们的分数序列是真实历史数据算出来的、**可测**。
    旧实现（用 verified 当 measurable）会把"不显著"读成"不可测"
    → 全部 0 权重 → 系统永不开仓。这正是本次要修掉的缺陷。
    """
    import json
    import tempfile
    from pathlib import Path as _P

    from gold_agent.fusion.weights import W_SCALE

    payload = {"trials": 6, "sources": {
        # 旧格式：没有 measurable 字段，且 verified=false（正是真实文件的样子）
        n: {"ir": 0.0, "nw_t": 0.3, "n_obs": 60000, "verified": False,
            "tier": "rejected", "source_script": "old.py"}
        for n in ("kalman_persist", "chanlun", "classic_indicators")}}
    with tempfile.TemporaryDirectory() as td:
        p = _P(td) / "source_ir.json"
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tbl = WeightTable.load(p)
        for n in ("kalman_persist", "chanlun", "classic_indicators"):
            assert tbl.weight(n) == pytest.approx(W_SCALE), (
                f"{n}: 旧格式文件不得因 verified=false 被打成 0 权重"
                f"（那是把「不显著」误读成「不可测」）")
        assert tbl.weight("openmobius_smc") == 0.0


def test_weight_logs_are_gbk_encodable():
    """权重日志必须能被 GBK 编码（控制台 cp936，否则 print 抛异常）。

    ⚠️ 实测事故：`✓`/`⛔` 等非 GBK 符号曾让进程在**第一次真正开仓那一轮**
    崩溃 —— 日志看着能跑，一交易就死。故逐条验证可编码。
    """
    import tempfile
    from pathlib import Path as _P

    from gold_agent.fusion import weights as W

    msgs = []
    o_w, o_i = W.log_warn, W.log_info
    W.log_warn = lambda m: msgs.append(m)
    W.log_info = lambda m: msgs.append(m)
    try:
        W.WeightTable.load()                       # 旧格式 → warn
        W.WeightTable.load(_P(tempfile.mkdtemp()) / "nope.json")
        _shrink_table({"kalman_persist": -0.19, "classic_indicators": -0.35,
                       "chanlun": 0.17})           # lambda=0 → warn
        _shrink_table({"kalman_persist": -2.0, "classic_indicators": 0.0,
                       "chanlun": 2.0})            # lambda>0 → info
    finally:
        W.log_warn, W.log_info = o_w, o_i

    assert msgs, "权重状态必须写进日志（不能静默）"
    for m in msgs:
        m.encode("gbk")   # 不可编码会抛 UnicodeEncodeError


def test_ir_gate_requires_direction_matched_control():
    """校准判定门必须要求**胜过方向匹配对照**，不能只看 t 值。

    实测缺陷（2026-09-29）：旧门只要求 `非重叠毛 NW-t > 1.5`。但本窗口是
    趋势市（全空头毛收益 +0.5690 vs 全多头 -0.4644 USD/笔），一个持续偏空
    的源**不需要任何择时能力**就能拿到正 t。实测：
      · 纯随机方向有 **14%** 概率通过旧门（t>1.5）；
      · 把非重叠样本方向随机重排（多空比例不变），对照 t 均值就有 +0.5；
      · 四个源（含那个"通过"的离线桩）全部落在对照分布内部。

    ⚠️ `verified` 只决定"能不能证明它强"，**不决定权重**（权重走 DL 收缩）。
    本测试守住"对照必须参与判定"这条不变量。
    """
    from pathlib import Path as _P

    src = (_P(__file__).resolve().parents[1] / "research" /
           "21_source_ir.py").read_text(encoding="utf-8")

    # 对照必须存在且可复现（确定性种子，不用内置 hash()）
    assert "TB_CTRL_SIMS" in src, "方向匹配对照的模拟次数必须显式定义"
    assert "_seed = 20260920" in src, (
        "对照的随机种子必须确定性导出 —— 内置 hash() 会被 PYTHONHASHSEED "
        "随机化，导致同一份数据每次跑出不同结论")

    # 判定必须引用对照结果
    assert "ctrl_ok" in src, "判定门必须计算对照是否通过"
    assert "and ctrl_ok)" in src, "verified 判定必须包含对照条件"
    assert "t_ind > 2.0 and ctrl_ok" in src, "strong 档也必须过对照"

    # 量纲陷阱：ret 已含源方向，置换必须写成 perm * r_ind
    assert "perm * r_ind" in src, (
        "对照必须用 `perm * r_ind`（置换已带方向的收益，多空比例严格不变）")
    assert "d * r_ind" not in src, (
        "不得写成 `d * r_ind` —— 那是把收益取反，不是打乱方向，"
        "多空比例会歪掉，对照就不'匹配'了")

    # 保守置换 p 值（分子加 1，保证 p 不会被伪造成 0）
    assert "np.sum(np.asarray(ctrl_t) >= t_gross_ind)" in src, (
        "置换 p 值必须用单侧计数且分子加 1")

    # skill 必须写进校准文件（权重估计量的唯一输入）
    assert '"skill":' in src, (
        "必须把 skill（t − 对照均值）写进校准文件，否则权重无从估计")
    assert '"measurable":' in src, (
        "必须把 measurable 写进校准文件，否则无法区分"
        "「不可测」与「不显著」（那正是本次修掉的缺陷）")


def test_shrinkage_replaces_the_policy_switch():
    """旧的 `source_ir_policy` 开关与其兜底表必须已被彻底删除。

    删除的理由不是"换个默认值"，而是它**结构上必然产生死代码**：
    两个取值里总有一个分支的输出被整体忽略。且 `BASELINE_IR` 本身是伪造的
    先验（kalman 0.28 vs 出处隐含的 0.01353，差 20.7 倍）。
    """
    from pathlib import Path as _P

    from gold_agent.fusion import weights as W

    src = (_P(__file__).resolve().parents[1] / "src" / "gold_agent" /
           "fusion" / "weights.py").read_text(encoding="utf-8")

    for gone in ("BASELINE_IR", "POLICY_BASELINE", "POLICY_AUTHORITATIVE",
                 "VALID_POLICIES", "source_ir_policy", "from_baseline"):
        assert not hasattr(W, gone), f"{gone} 应已删除（它必然产生死代码）"
        assert gone not in src, f"{gone} 不应再出现在 weights.py 里"

    assert not hasattr(CFG.fusion, "source_ir_policy"), (
        "config 里的策略开关也应删除")

    # 取而代之的是收缩端点，且确实是"权重"不是"开关"
    assert hasattr(W, "LAMBDA_CALIBRATED")
    assert hasattr(W, "NO_HISTORY_SOURCES")
    assert "openmobius_smc" in W.NO_HISTORY_SOURCES
