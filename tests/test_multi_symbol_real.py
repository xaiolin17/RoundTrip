# -*- coding: utf-8 -*-
"""多品种参数化的**真实**回归测试。

覆盖目标：把"品种相关量"从硬编码改成按 `SymbolProfile` 取，并证明
**单品种（黄金）行为零变化** —— 这是本次改造的核心契约。

为什么必须有这些测试
====================
1. **价格规整错位会重演重复下单事故。**
   `_PX_DIGITS=3` 对 EURUSDm（digits=5）会把 1.12419 规整成 1.12400
   （偏 19 个 point）。这与 2026-09-30"同一持仓重复提交 83 次"同类：
   提交值与 MT5 存回值永不相等 → 幂等判定不收敛。
2. **手数换算里的 point 是"自消"的，改一处就错。**
   `sl_points = sl_dist / point` 与
   `point_value_per_lot = tick_value * (point / tick_size)`
   两处相乘后 point 在代数上消掉。只改一处 → EURUSDm 手数差 100 倍。
   必须有一个测试**锁死两者同源**。
3. **持仓过滤只认 magic、不认 symbol。**
   全仓库 `p.magic == CFG.mt5.magic` 无一处按 symbol 过滤。
   共用 magic 时各品种互相认领持仓。测试必须证明各品种 magic 唯一。
"""
from __future__ import annotations

import json
import math

import pytest

from gold_agent.common.config import CFG
from gold_agent.common.symbols import (MAGIC_BASE, PROFILES, VENUE_INTERVALS,
                                       all_magics, get_profile,
                                       profile_by_magic, registered_symbols)


# ══════════════════════════════════════════════════════════════════
# 1. 档案表自身的完整性
# ══════════════════════════════════════════════════════════════════
def test_all_five_target_symbols_are_registered():
    """用户要求交易的 5 个品种必须全部登记。"""
    want = {"XAUUSDm", "BTCUSDm", "USOILm", "EURUSDm", "USDJPYm"}
    assert want <= set(registered_symbols()), \
        f"缺少品种档案：{want - set(registered_symbols())}"


def test_magic_is_unique_per_symbol():
    """⚠️ 每品种 magic 必须唯一 —— 这是多品种**最重要的**安全前提。

    全仓库的持仓/挂单/交割单过滤**只按 magic 判断**
    （`machine.py`、`gate.py`、`graph.py`、`deal_feedback.py`），
    没有任何一处按 symbol 过滤。若共用 magic：
      · 每个品种会把别的品种的持仓当成自己的；
      · 已用总手数被跨品种求和 → 加仓额度判定全错；
      · 止损/平仓提案可能发到别的品种的持仓上。
    """
    ms = [p.magic for p in PROFILES.values()]
    assert len(set(ms)) == len(ms), f"magic 有重复：{ms}"


def test_gold_magic_unchanged_for_history_continuity():
    """⚠️ XAUUSDm 的 magic 必须仍是 20260918。

    它是实盘正在用的值；`trades.jsonl` / MT5 交割单 / research 脚本
    全按这个 magic 归档。改动会让历史统计数据无法衔接
    （胜率、熔断、贝叶斯全部从零开始）。
    """
    assert get_profile("XAUUSDm").magic == 20260918
    assert MAGIC_BASE == 20260918


def test_magic_lookup_roundtrip():
    """magic -> profile 反查必须能回到同一个品种。"""
    for sym, p in PROFILES.items():
        assert profile_by_magic(p.magic) is p
    assert profile_by_magic(99999999) is None


def test_unregistered_symbol_raises_not_silently_defaults():
    """⚠️ 未注册品种必须**显式报错**，不得静默兜底。

    静默用一个错的点值/小数位会直接开出错价格的单，
    而幂等判定不收敛（重复提交）。宁可启动即失败。
    """
    with pytest.raises(KeyError) as ei:
        get_profile("NOT_A_SYMBOL")
    assert "PROFILES" in str(ei.value)


def test_profile_derived_quantities_are_consistent():
    """派生量自洽：point 与 digits 必须匹配（10^-digits）。"""
    for sym, p in PROFILES.items():
        expect = 10.0 ** (-p.digits)
        assert abs(p.point - expect) < expect * 1e-9, (
            f"{sym}: point={p.point} 与 digits={p.digits} 不一致（应为 {expect}）")


# ══════════════════════════════════════════════════════════════════
# 2. 价格规整：真实事故的回归防线
# ══════════════════════════════════════════════════════════════════
def test_px_digits_matches_profile_and_falls_back_when_absent():
    """`_px(ctx)` 必须按档案取 digits；无档案时退回旧值 3（单品种兼容）。"""
    from gold_agent.decision.machine import _PX_DIGITS, _px

    class _Ctx:
        profile = None

    assert _px(_Ctx()) == _PX_DIGITS == 3, "无档案时必须退回旧的 3 位"

    for sym, p in PROFILES.items():
        c = _Ctx()
        c.profile = p
        assert _px(c) == p.digits, f"{sym}: _px 未按档案取 digits"


def test_eurusd_stop_loss_is_not_corrupted_by_3_digit_rounding():
    """⚠️ 真实事故回归：EURUSDm 的 SL 被按 3 位规整会偏 19 个 point。

    这是 2026-09-30"同一持仓重复提交 83 次"的同一类故障：
    提交值与 MT5 存回值永不相等 → 幂等判定不收敛 → 每轮重发同一个值
    → MT5 每次回 `10025 No changes`。

    这里同时证明"旧行为确实是错的、新行为是对的"，而不只是断言新值。
    """
    from gold_agent.decision.machine import _px

    class _Ctx:
        pass

    p = get_profile("EURUSDm")
    true_sl = 1.12419

    old = round(true_sl, 3)          # 旧硬编码行为
    c = _Ctx(); c.profile = p
    new = round(true_sl, _px(c))     # 新按档案

    assert old == 1.124, "前提：旧行为确实会规整成 1.124"
    assert new == true_sl, "新行为必须保持 5 位精度原样"
    # 偏差换算成 point：1.12419 - 1.12400 = 0.00019 / 0.00001 = 19 point
    off_points = (true_sl - old) / p.point
    assert off_points == pytest.approx(19.0), \
        f"旧行为偏离 {off_points} point —— 正是重复下单事故的成因"


def test_machine_prices_round_to_symbol_digits():
    """`DecisionEngine` 产出的 SL/TP 必须按**该品种** digits 规整。

    直接驱动真实的 `_decide_holding` 移动止损路径成本高，这里用
    `_px` 契约 + 各品种代表性价格验证"提交值 == MT5 可能存回的值"。
    """
    from gold_agent.decision.machine import _px

    cases = {"XAUUSDm": (4117.2113333, 4117.211),
             "BTCUSDm": (81942.0449, 81942.04),
             "USOILm": (90.94999695, 90.950),
             "EURUSDm": (1.12419345, 1.12419),
             "USDJPYm": (158.02400207, 158.024)}
    for sym, (raw, want) in cases.items():
        class _Ctx:
            profile = get_profile(sym)
        got = round(raw, _px(_Ctx()))
        assert abs(got - want) < 1e-12, f"{sym}: {raw} -> {got}，期望 {want}"


# ══════════════════════════════════════════════════════════════════
# 3. 手数换算：point 必须与 point_value 同源（真实券商规格验证）
# ══════════════════════════════════════════════════════════════════
#: 券商实测规格（`mt5.symbol_info`，2026-10-09）。
#: 用真实值而非构造值，才能覆盖 tick_value/tick_size 不成整数倍的品种
#: （BTCUSDm 的 tick_value=0.01 与 XAUUSDm 的 0.1 差 10 倍）。
BROKER_SPECS = {
    "XAUUSDm": {"digits": 3, "point": 0.001, "tick_value": 0.1, "tick_size": 0.001},
    "BTCUSDm": {"digits": 2, "point": 0.01, "tick_value": 0.01, "tick_size": 0.01},
    "USOILm": {"digits": 3, "point": 0.001, "tick_value": 1.0, "tick_size": 0.001},
    "EURUSDm": {"digits": 5, "point": 0.00001, "tick_value": 1.0, "tick_size": 0.00001},
    "USDJPYm": {"digits": 3, "point": 0.001, "tick_value": 0.63318791,
                "tick_size": 0.001},
}


def test_broker_specs_match_profiles():
    """档案里的 digits/point 必须与券商实测规格一致（错一个点值就会开错仓）。"""
    for sym, spec in BROKER_SPECS.items():
        p = get_profile(sym)
        assert p.digits == spec["digits"], f"{sym} digits 不符"
        assert abs(p.point - spec["point"]) < 1e-15, f"{sym} point 不符"


def test_point_value_per_lot_keeps_point_and_tick_size_consistent():
    """`point_value_per_lot` 必须 = tick_value × (point / tick_size)。

    这是"每手每 point 的美元值"的定义。`position_lots` 里的
    `sl_points = sl_dist / point` 与它相乘后 point 会消掉 ——
    只要两者用**同一个** point，结果就与品种无关（正确）。
    """
    for sym, spec in BROKER_SPECS.items():
        p = get_profile(sym)
        pv = spec["tick_value"] * (p.point / spec["tick_size"])
        # 手算期望：
        expect = {"XAUUSDm": 0.1, "BTCUSDm": 0.01, "USOILm": 1.0,
                  "EURUSDm": 1.0, "USDJPYm": 0.63318791}[sym]
        assert abs(pv - expect) < 1e-9, f"{sym}: point_value={pv}，期望 {expect}"


@pytest.mark.parametrize("sym", sorted(BROKER_SPECS))
def test_per_lot_risk_is_symbol_independent(sym):
    """⚠️ 核心不变式：per_lot_risk = sl_dist × tick_value / tick_size。

    推导：per_lot_risk = (sl_dist / point) × (tick_value × point / tick_size)
    两处的 `point` **在代数上消掉** → 与品种无关。

    这正是原实现的真实情形：`position.py` 与 `graph._point_value`
    各自硬编码 0.001，于是"碰巧正确"。实测 5 品种下与正确公式完全一致。

    但这个巧合极脆弱：**只改一处**就会产生成百倍误差
    （EURUSDm point=1e-5 → 100 倍）。本测试锁死"两处必须同源"：
    若有人只改一边，下面的等式立刻破裂。
    """
    spec = BROKER_SPECS[sym]
    p = get_profile(sym)
    sl_dist = 12.5                      # 任取一个止损距离（价格单位）

    # 正确路径：两处都用档案 point
    pv_correct = spec["tick_value"] * (p.point / spec["tick_size"])
    risk_correct = (sl_dist / p.point) * pv_correct
    # 代数闭式（不含 point）
    risk_closed = sl_dist * spec["tick_value"] / spec["tick_size"]
    assert risk_correct == pytest.approx(risk_closed, rel=1e-12), \
        f"{sym}: point 未正确消去（{risk_correct} vs {risk_closed}）"

    # 反向：若只把 point 改成"按品种"、point_value 仍按旧 0.001 → 偏离
    pv_stale = spec["tick_value"] * (0.001 / spec["tick_size"])
    risk_stale = (sl_dist / p.point) * pv_stale
    if abs(p.point - 0.001) > 1e-15:
        ratio = risk_stale / risk_correct
        assert abs(ratio - 1.0) > 1e-6, (
            f"{sym}: 只改一处竟然没产生偏差，测试前提有误")
        expect = 0.001 / p.point        # EURUSDm -> 100 倍
        assert ratio == pytest.approx(expect, rel=1e-9), \
            f"{sym}: 单边改动的偏差应为 {expect} 倍"


def test_mt5_client_is_symbol_bound():
    """⚠️ 真实构建：每个 Graph 的 MT5Client 必须**绑定自己的品种**。

    这是 2026-10-09 多品种试点时发现的**真实事故**：
    `MT5Client` 当时没有任何 symbol 字段，`get_ohlcv` / `_positions_sync`
    / `_validate` 全部写死 `CFG.mt5.symbol`。于是 5 个 Graph 各有正确的
    品种档案，却全部去拉 **XAUUSDm** 的 K 线与持仓。

    实测证据：5 个品种的收盘价**完全相同**（都是 4175.704），
    融合分只差 0.001（+0.1729 ~ +0.1756）。

    危险在于**不报错**：每个品种都"正常工作"、都在产出信号，
    只是所有信号都是黄金的。持仓侧更严重 —— 每个品种都按自己的 magic
    去过滤黄金的持仓，滤出空列表，于是都以为"我没有持仓"，
    可以无限开仓、看不到已用总手数、无法加仓或平仓。
    """
    from gold_agent.agent.graph import Graph

    seen = {}
    for sym in ("XAUUSDm", "BTCUSDm", "USOILm", "EURUSDm", "USDJPYm"):
        g = Graph.build(sym)
        seen[sym] = g.client.symbol
        # 客户端绑定的品种必须与档案一致
        assert g.client.symbol == sym, \
            f"{sym}: MT5Client 绑定了 {g.client.symbol!r}，会拉错品种的行情"
        # account 是全局的，但 positions/ohlcv 必须按品种
        assert g.client._sym() == sym

    assert len(set(seen.values())) == 5, \
        f"多个 Graph 共用了同一个品种的客户端：{seen}"


def test_mt5_client_symbol_info_uses_own_symbol():
    """`symbol_info()` 缺省时必须用本实例品种，不是配置默认品种。"""
    from gold_agent.mt5.client import MT5Client

    c = MT5Client(symbol="EURUSDm")
    assert c._sym() == "EURUSDm"
    c2 = MT5Client()                      # 不传 -> 退回配置默认
    assert c2._sym() == CFG.mt5.symbol == "XAUUSDm"


def test_client_has_no_hardcoded_default_symbol_in_queries():
    """⚠️ 静态检查：行情/持仓查询里不得残留写死的默认品种。

    这是防回归的**源码级**断言 —— 上述事故的根因就是三处写死
    `CFG.mt5.symbol`，而当时没有任何测试覆盖"客户端是否绑定品种"。
    用函数体源码检查，比只跑行为测试更能防止后人改回去。
    """
    import inspect

    from gold_agent.mt5 import client as C

    for fn in (C.MT5Client.get_ohlcv, C.MT5Client._positions_sync,
               C.MT5Client.get_ohlcv_sync, C.MT5Client._validate,
               C.MT5Client._doctor_sync):
        src = inspect.getsource(fn)
        assert "CFG.mt5.symbol" not in src, (
            f"{fn.__name__} 里仍写死 CFG.mt5.symbol —— "
            f"多品种下会拉错品种（见 test_mt5_client_is_symbol_bound）")
        assert ("self._sym()" in src or "self.symbol" in src
                or "symbol" in src), \
            f"{fn.__name__} 看起来没有使用本实例的品种"


def test_mt5_client_init_is_serialized():
    """⚠️ `mt5.initialize()` 是进程级全局操作，多品种并发初始化必须串行。

    不串行的话多个 Client 同时 initialize 会互相打断。
    """
    import threading as _th

    from gold_agent.mt5 import client as C

    assert isinstance(C._INIT_LOCK, type(_th.Lock())), \
        "缺少 _INIT_LOCK，多品种并发初始化未串行化"


def test_multi_symbol_rounds_have_distinct_prices():
    """⚠️ 端到端：5 个品种实跑一轮，收盘价必须**互不相同**。

    这条是"数据串台"的最终防线。若各品种拿到同一份行情，
    收盘价会完全相同 —— 单看任何一个品种都察觉不到。
    """
    import asyncio
    import os

    os.environ["TRADE_SYMBOLS"] = "XAUUSDm,BTCUSDm,USOILm,EURUSDm,USDJPYm"
    try:
        from gold_agent.agent.graph import Graph

        syms = ("XAUUSDm", "BTCUSDm", "USOILm", "EURUSDm", "USDJPYm")

        async def run():
            graphs = {s: Graph.build(s) for s in syms}
            for g in graphs.values():
                try:
                    await g.client.initialize()
                except Exception:
                    pass
            res = await asyncio.gather(
                *[g.run_round(1) for g in graphs.values()],
                return_exceptions=True)
            closes = {}
            for s, r in zip(syms, res):
                if not isinstance(r, Exception):
                    closes[s] = r.get("last_close")
            for g in graphs.values():
                try:
                    await g.close()
                except Exception:
                    pass
            return closes

        closes = asyncio.run(run())
        got = {k: v for k, v in closes.items() if v is not None}
        if len(got) < 2:
            pytest.skip(f"实盘数据不足，无法比对：{closes}")
        assert len(set(got.values())) == len(got), (
            f"有品种拿到相同收盘价（数据串台）: {got}")
    finally:
        os.environ.pop("TRADE_SYMBOLS", None)


def test_used_lots_filters_by_own_magic():
    """`_used_lots` 只统计本品种 magic 的持仓（多品种下不能跨品种求和）。"""
    from gold_agent.agent.graph import Graph

    g = Graph.build("BTCUSDm")
    mine = g.profile.magic
    other = get_profile("XAUUSDm").magic
    assert mine != other

    class _P:
        def __init__(self, magic, vol):
            self.magic = magic
            self.volume = vol

    class _Pos:
        positions = [_P(mine, 0.10), _P(other, 9.99)]

    got = g._used_lots(_Pos())
    assert got == pytest.approx(0.10), \
        f"_used_lots 把别的品种也算进来了：{got}"


def test_position_lots_is_symbol_consistent_with_broker_specs(monkeypatch):
    """⚠️ 真实调用 `position_lots`：手数换算必须与品种无关。

    两个"测试陷阱"必须先讲清楚，否则这个测试会**形同虚设**（初版就踩了）：

    1. **止损距离必须按品种等比给。**
       初版用 `sl_dist=12.5`（黄金尺度）。对 EURUSDm 而言 12.5 是
       几十倍汇价的荒谬距离 → 被 `risk_budget_below_min_lot` 拒绝、
       返回 `lots=0`，断言被 `if lots > 0` 跳过 —— 测了等于没测。
       正确做法：`sl_dist = 1000 × point`，使各品种处于**等价尺度**。

    2. **`CFG.max_lot` 会掩盖 100 倍换算错误。**
       实盘 `max_lot=0.06` 时，正确实现与 bug 实现都被封顶到 0.06，
       手数看起来一模一样（实测：EURUSDm 正确 0.05 / bug 0.06，
       仅 20% 差异，极易被误判为"波动"）。
       解除封顶后差异才暴露：EURUSDm 正确 0.05 vs bug **5.0（100 倍）**。
       所以这里临时抬高 `max_lot`，专门验算**换算本身**。

    判据是"实际风险 ≈ 预算" —— 它同时覆盖 lots 与 per_lot_risk 两侧。
    """
    from gold_agent.risk.position import position_lots

    # 解除封顶，暴露真实换算（否则 max_lot 会把错误藏起来）
    monkeypatch.setattr(CFG, "max_lot", 100.0)

    equity = 10000.0
    budget = equity * 0.005                      # risk_pct=0.5% -> 50 USD
    for sym, spec in BROKER_SPECS.items():
        p = get_profile(sym)
        # ① 等价尺度止损（不是黄金的 12.5）
        sl_dist = 1000 * p.point
        pv = spec["tick_value"] * (p.point / spec["tick_size"])
        true_per_lot = sl_dist * spec["tick_value"] / spec["tick_size"]

        lots, rej = position_lots(equity, 15.0, pv, 0.5,
                                  sl_dist=sl_dist, point=p.point)
        assert rej is None, f"{sym}: 等价尺度下不该被拒绝（{rej}）"
        assert lots > 0, f"{sym}: 手数为 0，断言会失效 —— 测试前提错了"

        actual = lots * true_per_lot
        # 允许一个 volume_step（0.01 手）的取整误差
        tol = 0.01 * true_per_lot + 0.5
        assert actual <= budget + tol, (
            f"{sym}: 实际风险 {actual:.2f} USD 超预算 {budget:.2f} —— "
            f"疑似 point 单边改动（手数 {lots}）")
        assert actual >= budget - tol, (
            f"{sym}: 实际风险 {actual:.2f} USD 远低于预算 {budget:.2f} —— "
            f"疑似 point 单边改动（手数 {lots}）")

    # 反向证明：point 单边改动（只改 sl_points、不 point_value）必然被抓住。
    # 这是本次改造最危险的失误模式，必须用测试固化。
    for sym in ("EURUSDm", "BTCUSDm"):
        spec = BROKER_SPECS[sym]
        p = get_profile(sym)
        sl_dist = 1000 * p.point
        pv_correct = spec["tick_value"] * (p.point / spec["tick_size"])
        # bug 版：sl_points 仍按 0.001 算，point_value 按品种算
        bug_per_lot = (sl_dist / 0.001) * pv_correct
        bug_lots = math.floor((budget / bug_per_lot) / 0.01) * 0.01

        good_lots, _ = position_lots(equity, 15.0, pv_correct, 0.5,
                                     sl_dist=sl_dist, point=p.point)
        ratio = bug_lots / good_lots
        assert ratio > 1.5 or ratio < 0.67, (
            f"{sym}: 单边 point 改动未产生手数偏差（{bug_lots} vs {good_lots}），"
            f"测试无法防住该 bug —— 需重新设计")
        # EURUSDm 恰好差 100 倍，BTCUSDm 差 10 倍
        assert ratio == pytest.approx(0.001 / p.point, rel=1e-6), \
            f"{sym}: 偏差倍数应为 {0.001 / p.point}，实为 {ratio}"


def test_position_lots_default_point_preserves_legacy_behavior():
    """⚠️ 不传 point 时必须与改造前**完全一致**（默认 0.001）。

    这是"参数化零行为变化"契约的直接证据：旧调用方（研究脚本、
    未更新的测试）拿到的手数一个比特都不能变。
    """
    from gold_agent.risk.position import position_lots

    args = dict(equity=10000.0, atr=15.0, point_value_per_lot=0.1,
                win_rate=0.5, sl_dist=12.5)
    implicit, _ = position_lots(**args)
    explicit, _ = position_lots(**args, point=0.001)
    assert implicit == explicit


# ══════════════════════════════════════════════════════════════════
# 4. Mobius venue / 周期裁剪（多品种最容易 400 的地方）
# ══════════════════════════════════════════════════════════════════
def test_mobius_mapping_matches_verified_live_facts():
    """Mobius 映射必须是实测确认过的组合，不是凭印象写的。

    实测（官方 /api/markets + 真实调用）：
      · 油**不在** commodity:spot（那个 venue 只有 XAUUSD 一个品种），
        油是 commodity:futures 的 `WTIUSD`；
      · 比特币在 binance:spot 叫 `BTCUSDT`，不是 `BTCUSD`（后者 404）；
      · forex / commodity:futures **只支持 1h/1d**。
    """
    assert get_profile("XAUUSDm").mobius_symbol == "XAUUSD"
    assert get_profile("XAUUSDm").mobius_venue == "commodity:spot"
    assert get_profile("BTCUSDm").mobius_symbol == "BTCUSDT"
    assert get_profile("BTCUSDm").mobius_venue == "binance:spot"
    assert get_profile("USOILm").mobius_symbol == "WTIUSD"
    assert get_profile("USOILm").mobius_venue == "commodity:futures"
    assert get_profile("EURUSDm").mobius_venue == "forex:spot"
    assert get_profile("USDJPYm").mobius_venue == "forex:spot"


def test_smc_intervals_are_clipped_to_venue_support():
    """⚠️ SMC 周期必须按 venue 能力裁剪 —— 请求不支持周期返回 **400 而非降级**。

    事故风险：若不裁剪，forex 品种每轮 3 个周期（4h/15m/5m）全部 400，
    SMC 静默变成"永远 unavailable"，而不是"少一个周期"。
    """
    want = ("1h", "4h", "15m", "5m")
    # 全套支持的品种：一个都不该丢
    for sym in ("XAUUSDm", "BTCUSDm"):
        p = get_profile(sym)
        assert p.smc_intervals(want) == want, f"{sym} 不该丢周期"
    # 只支持 1h/1d 的品种：只能留 1h
    for sym in ("USOILm", "EURUSDm", "USDJPYm"):
        p = get_profile(sym)
        got = p.smc_intervals(want)
        assert got == ("1h",), f"{sym}: 裁剪后应只剩 1h，实得 {got}"


def test_smc_intervals_never_returns_unsupported_timeframe():
    """裁剪结果必须是 venue 支持周期的子集（通用不变式）。"""
    for sym, p in PROFILES.items():
        supported = set(p.supported_intervals())
        got = set(p.smc_intervals(("1m", "5m", "15m", "30m", "1h", "4h", "1d")))
        assert got <= supported, f"{sym}: 裁剪后仍有不支持的周期 {got - supported}"


def test_venue_intervals_table_has_no_empty_entries():
    """周期表不得有空条目 —— 空 = 该 venue 什么都取不到（应显式不支持）。"""
    for v, ivs in VENUE_INTERVALS.items():
        assert ivs, f"{v} 周期列表为空"
        assert all(isinstance(t, str) and t for t in ivs)


def test_every_configured_venue_is_in_the_intervals_table():
    """档案里用到的每个 venue 都必须在周期表里有记录（否则裁剪会全丢）。"""
    for sym, p in PROFILES.items():
        if p.mobius_venue is not None:
            assert p.mobius_venue in VENUE_INTERVALS, (
                f"{sym} 使用了未登记周期的 venue {p.mobius_venue}")


def test_has_smc_flag_matches_symbol_presence():
    """`has_smc` 必须与 mobius_symbol 一致（无 SMC 的品种要能显式识别）。"""
    for sym, p in PROFILES.items():
        assert p.has_smc == (p.mobius_symbol is not None)
        assert p.supported_intervals() if p.has_smc else not p.supported_intervals()


def test_fusion_shrinks_rather_than_renormalizes_when_tf_missing():
    """缺周期时必须**收缩**（不重分配）—— 这是 forex/油只有 1h 时的正确行为。

    `aggregate_tf_scores` 除以**声明权重之和**（固定分母），
    缺周期贡献 0 → 总分向 0 收缩（"证据不足时降低置信度"）。
    若改成除以"实际到齐权重和"，等于假装没缺数据，会把单周期观点
    放大到满量程（危险）。
    """
    from gold_agent.fusion.engine import aggregate_tf_scores

    w = {"1h": 1.0, "4h": 0.5, "15m": 0.4, "5m": 0.2}
    full = aggregate_tf_scores(w, {"1h": 3.0, "4h": 3.0, "15m": 3.0, "5m": 3.0})
    only_1h = aggregate_tf_scores(w, {"1h": 3.0, "4h": None, "15m": None, "5m": None})
    # 只有 1h 有分时，总分必须**显著小于**全量（收缩），且 > 0
    assert 0 < only_1h < full, f"缺周期未收缩：{only_1h} vs {full}"
    # 分母固定为 2.1，所以 only_1h 应恰为 3.0*1.0/2.1
    assert only_1h == pytest.approx(3.0 * 1.0 / 2.1, rel=1e-9)


# ══════════════════════════════════════════════════════════════════
# 5. 过滤：magic 是唯一隔离手段
# ══════════════════════════════════════════════════════════════════
def test_machine_magic_filter_uses_profile_magic():
    """`_magic_of(ctx)` 必须按档案取 magic，无档案时退回 CFG.mt5.magic。"""
    from gold_agent.decision.machine import _magic_of

    class _Ctx:
        profile = None

    assert _magic_of(_Ctx()) == CFG.mt5.magic
    for sym, p in PROFILES.items():
        c = _Ctx(); c.profile = p
        assert _magic_of(c) == p.magic, f"{sym}: 过滤 magic 未按档案取"


def test_positions_are_isolated_between_symbols():
    """⚠️ 多品种持仓隔离的真实模拟。

    构造"同一账户内 5 个品种各有持仓"的场景，验证每个品种的过滤
    只认领自己的持仓。这在共用 magic 时**必定失败** ——
    正是本测试要防的事故。
    """
    from gold_agent.decision.machine import _magic_of

    class _Pos:
        def __init__(self, ticket, magic, symbol):
            self.ticket = ticket
            self.magic = magic
            self.symbol = symbol
            self.volume = 0.01

    positions = [_Pos(i, p.magic, sym)
                 for i, (sym, p) in enumerate(PROFILES.items(), start=1)]

    for sym, p in PROFILES.items():
        class _Ctx:
            profile = p
        mine = [x for x in positions if x.magic == _magic_of(_Ctx())]
        assert len(mine) == 1, f"{sym} 认领了 {len(mine)} 个持仓（应恰好 1 个）"
        assert mine[0].symbol == sym, f"{sym} 认领到了 {mine[0].symbol} 的持仓"


def test_deal_feedback_defaults_to_cfg_magic():
    """`DealFeedback` 不传 magic 时用 CFG.mt5.magic（单品种兼容）。"""
    from gold_agent.fusion.bayes import BayesianPool
    from gold_agent.fusion.deal_feedback import DealFeedback
    from gold_agent.risk.position import CircuitBreakers

    fb = DealFeedback(BayesianPool(), CircuitBreakers())
    assert fb.magic == CFG.mt5.magic


def test_deal_feedback_honours_per_symbol_magic():
    """`DealFeedback` 必须按传入 magic 过滤交割单（防止跨品种污染统计）。"""
    from gold_agent.fusion.bayes import BayesianPool
    from gold_agent.fusion.deal_feedback import DealFeedback
    from gold_agent.risk.position import CircuitBreakers

    for sym, p in PROFILES.items():
        fb = DealFeedback(BayesianPool(), CircuitBreakers(),
                          magic=p.magic, symbol=sym)
        assert fb.magic == p.magic
        assert fb.symbol == sym


# ══════════════════════════════════════════════════════════════════
# 6. 下单请求携带正确品种
# ══════════════════════════════════════════════════════════════════
class _FakeSi:
    digits = 3
    point = 0.001
    trade_tick_value = 0.1
    trade_tick_size = 0.001
    filling_mode = 1
    trade_stops_level = 0
    ask = 1.0001
    bid = 0.9999


class _FakeClient:
    """记录被查询的品种，用于验证请求发到了哪个品种。"""
    def __init__(self):
        self.asked: list = []

    def symbol_info(self, symbol=None):
        # 兼容两种签名：executor 会先试带参调用
        self.asked.append(symbol)
        si = _FakeSi()
        si.digits = get_profile(symbol).digits if symbol in PROFILES else 3
        return si


def test_order_request_carries_the_plan_symbol():
    """⚠️ 下单请求必须带 plan 的品种，否则所有单都发到默认品种上。"""
    from gold_agent.mt5.executor import Executor, OrderPlan

    fc = _FakeClient()
    ex = Executor(fc)
    for sym in sorted(PROFILES):
        req = ex._build_request(OrderPlan(
            kind="open_market", direction="LONG", lots=0.01,
            entry=1.0, tp=2.0, sl=0.5, symbol=sym))
        assert req["symbol"] == sym, f"{sym}: 请求品种错为 {req['symbol']}"
    assert sorted(fc.asked[-5:]) == sorted(PROFILES), "未按品种查 symbol_info"


def test_order_request_defaults_to_cfg_symbol_when_absent():
    """不传 symbol 时必须用 CFG.mt5.symbol（单品种兼容，行为不变）。"""
    from gold_agent.mt5.executor import Executor, OrderPlan

    ex = Executor(_FakeClient())
    req = ex._build_request(OrderPlan(kind="open_market", direction="LONG",
                                      lots=0.01, entry=1.0, tp=2.0, sl=0.5))
    assert req["symbol"] == CFG.mt5.symbol


def test_mobius_request_body_uses_profile_venue(monkeypatch):
    """`get_smc` 必须把 venue 放进请求体（否则 BTCUSDm 会查 commodity:spot）。"""
    import asyncio

    from gold_agent.skills import mobius_adapter as MA

    captured: dict = {}

    class _Resp:
        status = 200

        async def json(self):
            return {"current_price": 1.0, "indicators": {},
                    "data_meta": {}}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Session:
        closed = False

        def post(self, url, json=None):
            captured["url"] = url
            captured["body"] = json
            return _Resp()

    p = get_profile("BTCUSDm")
    c = MA.MobiusClient()
    c._session = _Session()
    asyncio.run(c.get_smc(p.mobius_symbol, "1h", limit=10,
                          exchange=p.mobius_exchange, market=p.mobius_market))
    body = captured["body"]
    assert body["exchange"] == "binance", f"exchange 错：{body['exchange']}"
    assert body["market"] == "spot"
    assert body["symbol"] == "BTCUSDT"


# ══════════════════════════════════════════════════════════════════
# 7. 状态隔离与日志归属
# ══════════════════════════════════════════════════════════════════
def test_state_dir_is_shared_when_single_symbol(monkeypatch):
    """⚠️ 单品种时状态目录**必须保持原路径**（data/）。

    否则现有实盘状态（normalizer 预热 / 熔断 / 加仓计数）会"丢失"，
    表现为重启后空仓等预热、熔断记录清零 —— 静默的行为回归。
    """
    monkeypatch.delenv("TRADE_SYMBOLS", raising=False)
    monkeypatch.setenv("MT5_SYMBOL", "XAUUSDm")
    assert CFG.state_path_for("XAUUSDm") == CFG.state_path.parent


def test_state_dir_is_isolated_when_multi_symbol(monkeypatch):
    """⚠️ 多品种时状态必须按品种隔离。

    共用一份会让 A 品种的分数分布污染 B 品种的 z-score 归一化
    （尺度/量纲不同），双方都判错强弱；熔断与盈亏序列也会互相污染。
    """
    monkeypatch.setenv("TRADE_SYMBOLS", "XAUUSDm,BTCUSDm")
    dirs = {s: CFG.state_path_for(s) for s in ("XAUUSDm", "BTCUSDm")}
    assert dirs["XAUUSDm"] != dirs["BTCUSDm"], "多品种状态目录未隔离"
    assert dirs["XAUUSDm"].name == "XAUUSDm"
    assert dirs["BTCUSDm"].name == "BTCUSDm"


def test_trade_symbols_parsing(monkeypatch):
    """`TRADE_SYMBOLS` 解析：未设 -> 单品种；设置 -> 按逗号切分。"""
    monkeypatch.delenv("TRADE_SYMBOLS", raising=False)
    monkeypatch.setenv("MT5_SYMBOL", "XAUUSDm")
    assert CFG.trade_symbols == ("XAUUSDm",)
    assert CFG.multi_symbol is False

    monkeypatch.setenv("TRADE_SYMBOLS", " XAUUSDm, BTCUSDm ,")
    assert CFG.trade_symbols == ("XAUUSDm", "BTCUSDm")
    assert CFG.multi_symbol is True


def test_log_symbol_tag_defaults_off_and_can_be_set():
    """⚠️ 品种日志标签必须默认**关闭**（单品种日志格式不变），可显式开启。"""
    from gold_agent.common import logging_util as LU

    assert LU._symbol is None, "默认应为 None（不加 symbol 字段）"
    LU.set_symbol("BTCUSDm")
    try:
        assert LU._symbol == "BTCUSDm"
        LU.set_symbol("")
        assert LU._symbol is None, "空串应还原为 None"
    finally:
        LU.set_symbol(None)


def test_log_symbol_tagged_before_dedup(tmp_path, monkeypatch):
    """⚠️ 品种标签必须在**去重判定之前**写入。

    否则两个品种的同类记录（其余字段相同）会被误判为"重复"而互相吞掉，
    其中一个品种的日志凭空消失。
    """
    from gold_agent.common import logging_util as LU

    monkeypatch.setattr(LU, "_live", True)
    monkeypatch.setattr(LU, "_silent", False)
    LU._last_line_key.clear(); LU._dup_count.clear()
    p = tmp_path / "t.jsonl"

    LU.set_symbol("XAUUSDm")
    LU.jlog(p, {"event": "risk_decision", "score": 1.0})
    LU.set_symbol("BTCUSDm")
    LU.jlog(p, {"event": "risk_decision", "score": 1.0})
    LU.set_symbol(None)

    lines = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()]
    lines = [x for x in lines if x.get("event") == "risk_decision"]
    assert len(lines) == 2, "两个品种的同类记录被去重吞掉了一条"
    assert {x["symbol"] for x in lines} == {"XAUUSDm", "BTCUSDm"}


# ══════════════════════════════════════════════════════════════════
# 8. 新闻关键词与 LLM 提示词去品种化
# ══════════════════════════════════════════════════════════════════
def test_news_keywords_are_per_symbol_and_gold_unchanged():
    """新闻关键词必须按品种取；黄金的必须与历史完全一致。"""
    from gold_agent.news.collector import _GOLD_KEYWORDS

    assert get_profile("XAUUSDm").news_keywords == _GOLD_KEYWORDS, \
        "黄金关键词被改动 —— 单品种行为会变化"
    for sym in ("BTCUSDm", "USOILm", "EURUSDm", "USDJPYm"):
        kw = get_profile(sym).news_keywords
        assert kw, f"{sym} 关键词为空"
        assert kw != _GOLD_KEYWORDS, f"{sym} 仍在用黄金关键词"


def test_collector_uses_profile_keywords_and_marks_relevance():
    """`Jin10Collector` 必须用本品种关键词判定相关性。"""
    from gold_agent.news.collector import Jin10Collector

    btc = Jin10Collector(symbol="BTCUSDm")
    assert btc.keywords == get_profile("BTCUSDm").news_keywords

    oil = Jin10Collector(symbol="USOILm")
    assert "原油" in oil.keywords and "油价" in oil.keywords


def test_collector_defaults_to_gold_keywords():
    """不传品种时必须退回黄金关键词（单品种兼容，行为不变）。"""
    from gold_agent.news.collector import Jin10Collector, _GOLD_KEYWORDS

    assert Jin10Collector(symbol="XAUUSDm").keywords == _GOLD_KEYWORDS


def test_llm_prompts_are_asset_templated_and_render_per_symbol():
    """⚠️ LLM 提示词不得写死"黄金"。

    写死会让模型在分析比特币/原油时被误导（用黄金的驱动逻辑解释别的品种）。
    同时必须保留 `{asset}` 占位符可渲染，且**渲染后不得残留占位符**。

    ⚠️ 反例（真实踩过）：这些提示词含 JSON 示例（`{"verdict":...}`），
    用 `str.format()` 渲染会 `KeyError: '"verdict"'` —— 于是**每次
    review 调用都抛异常**，LLM 直接不可用。必须用 `replace`。
    本测试显式断言"format 会崩、replace 不崩"，把这个陷阱固化下来。
    """
    from gold_agent.llm import orchestrator as O

    prof = get_profile("XAUUSDm")
    orch = O.Orchestrator(client=None, symbol="XAUUSDm")

    for name in ("_REVIEW_SYSTEM", "_NEWS_SYSTEM", "_ADD_REVIEW_SYSTEM"):
        txt = getattr(O, name)
        assert "{asset}" in txt, f"{name} 缺少 {{asset}} 占位符"
        assert "黄金" not in txt, f"{name} 仍写死'黄金'"
        for sym in sorted(PROFILES):
            o = O.Orchestrator(client=None, symbol=sym)
            rendered = o._render(txt)
            assert "{asset}" not in rendered, f"{name} 渲染后仍有占位符"
            assert get_profile(sym).prompt_asset in rendered, \
                f"{name} 未渲染出 {sym} 的品种名"

    # 黄金渲染结果必须仍含"黄金"（语义不变）
    g = orch._render(O._REVIEW_SYSTEM)
    assert "黄金" in g and "XAUUSD" in g

    # 固化"不能用 format"这个陷阱：含 JSON 示例的提示词用 format 必崩
    with pytest.raises(KeyError):
        O._REVIEW_SYSTEM.format(asset=prof.prompt_asset)
    # 而 replace 正常
    assert "{asset}" not in orch._render(O._REVIEW_SYSTEM)


def test_prompt_asset_is_set_for_all_symbols():
    """每个品种都要有提示词用的展示名。"""
    for sym, p in PROFILES.items():
        assert p.prompt_asset, f"{sym} 缺少 prompt_asset"
        assert p.label, f"{sym} 缺少 label"


def test_every_llm_system_prompt_still_contains_json():
    """⚠️ 所有 `*_SYSTEM` 提示词仍须含 "json"（否则线上 HTTP 400）。

    这条与加仓复核事故（314 次 400、加仓功能静默失效）同源。
    把提示词改成模板时最容易漏掉这个硬性要求，所以在此再锁一次。
    """
    from gold_agent.llm import orchestrator as O

    prompts = {n: getattr(O, n) for n in dir(O)
               if n.endswith("_SYSTEM") and isinstance(getattr(O, n), str)}
    assert prompts
    missing = [n for n, t in prompts.items() if "json" not in t.lower()]
    assert not missing, f"以下提示词缺少 'json'（线上会 400）：{missing}"
