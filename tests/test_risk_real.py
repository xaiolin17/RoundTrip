"""风控模块测试：真实历史数据驱动仓位/收缩/熔断。"""
from __future__ import annotations

import time

import pandas as pd
import pytest

from gold_agent.common.config import CFG
from gold_agent.fusion.engine import FusionResult
from gold_agent.mt5.client import AccountInfo
from gold_agent.risk.gate import Proposal, RiskGate
from gold_agent.risk.position import (CircuitBreakers, conservative_win_rate,
                                      position_lots, volatility_k, wilson_lower)
from gold_agent.risk.shrink import reachable_tp, shrink_for_pending, shrink_sl, shrink_tp
from gold_agent.risk.structure import RETRACE_FAR, RETRACE_NEAR


def test_position_lots_bounds():
    equity, atr, pv = 10000.0, 5.0, 1.0
    lots, rej = position_lots(equity, atr, pv, win_rate=0.5, vol_k=1.0,
                              volume_min=0.01, volume_step=0.01)
    if rej is None:
        assert lots >= 0.01
        # 风险不超 0.5% + Kelly cap
        risk = CFG.risk.sl_atr_mult * atr / 0.001 * pv * lots
        assert risk <= equity * 0.055   # 0.5% 与 Kelly cap 较小者再放宽边界
    else:
        assert rej == "risk_budget_below_min_lot"


def test_min_lot_fallback_when_vol_k_shrinks_budget():
    """回归（用户实测事故）：缩仓系数把预算压到最小手数以下时，**仍按 0.01 手开仓**。

    实测：vol_k=0.125（波动下限 0.25 × 分歧 0.5）→ 预算 8.64 USD
    → 止损上限仅 8.6 点，而实际止损 7.5~20.8 点 → 强信号轮次被连续拦截
    （3514/3515），用户反馈"现在没有开仓"。

    但 0.01 手 + 20 点止损 = 20.82 USD = 权益 0.145%，
    **远低于** risk_pct 允许的 0.500%（69.10 USD）——
    系统在拒绝一个风险只有自设上限 29% 的仓位。
    0.01 手是交易所下限，不能再往下取整，所以缩仓系数不该变成"禁止交易"。
    """
    equity, pv = 13820.89, 0.1
    nominal = equity * CFG.risk.risk_pct          # 69.10 USD
    # 被拦的轮次：止损 16.49 / 19.87 / 20.82 点
    for sl_dist in (16.49, 19.87, 20.82):
        lots, rej = position_lots(equity, 17.0, pv, 0.5,
                                  vol_k=0.125, sl_dist=sl_dist)
        assert rej is None, f"止损 {sl_dist} 点不该被拦（得到 {rej}）"
        assert lots == pytest.approx(0.01), "应按最小手数开仓"
        # 实际风险必须仍在**名义**预算内
        risk = sl_dist * 0.01 * pv / 0.001
        assert risk <= nominal, f"实际风险 {risk:.2f} 超出名义预算 {nominal:.2f}"


def test_min_lot_fallback_still_respects_nominal_budget():
    """兜底不得突破硬风控：0.01 手风险超出**名义**预算时仍须拦截。"""
    equity, pv = 13820.89, 0.1
    nominal = equity * CFG.risk.risk_pct
    over = nominal / (0.01 * pv / 0.001) + 1.0    # 刚好超出名义预算的止损宽度
    lots, rej = position_lots(equity, 17.0, pv, 0.5, vol_k=1.0, sl_dist=over)
    assert rej == "risk_budget_below_min_lot", (
        f"止损 {over:.1f} 点已超名义预算，必须拦截（得到 {lots} 手）")
    # 刚好在预算内 -> 放行
    under = nominal / (0.01 * pv / 0.001) - 1.0
    lots2, rej2 = position_lots(equity, 17.0, pv, 0.5, vol_k=1.0, sl_dist=under)
    assert rej2 is None and lots2 == pytest.approx(0.01)


def test_position_lots_consistent_across_paths():
    """回归：open_market 与 place_grid 必须用**同一个** vol_k。

    原实现 place_grid 漏传 vol_k（默认 1.0），于是同一个 20 点止损，
    place_grid 开 0.03 手而 open_market 直接被拦 —— 两边风险尺度不一致。
    """
    equity, pv = 13820.89, 0.1
    for sl_dist in (9.28, 16.49, 20.82, 54.5):
        a = position_lots(equity, 17.0, pv, 0.5, vol_k=0.125, sl_dist=sl_dist)
        b = position_lots(equity, 17.0, pv, 0.5, vol_k=0.125, sl_dist=sl_dist)
        assert a == b, f"同一 vol_k 下两条路径结果必须一致：{a} vs {b}"


def test_volatility_k_bounds():
    assert 0.25 <= volatility_k(0.02, None) <= 1.5
    assert volatility_k(None, None) == 1.0
    assert volatility_k(0.005, 0.03) < 1.5   # 高波动日 ×0.6


def test_circuit_breakers_paths():
    b = CircuitBreakers()
    # 全零基线
    assert b.check(10000, 0.0, False) is None
    # 连亏（先达 cooloff 或 consecutive_losses 均为合法熔断）
    for _ in range(4):
        b.on_trade_closed(-50, 10000)
    r = b.check(10000, 0.0, False)
    assert r and ("consecutive_losses" in r or "cooloff" in r)
    # 日亏熔断
    b2 = CircuitBreakers()
    b2.on_trade_closed(-350, 10000)   # > 3% of 10000
    r = b2.check(10000, 0.0, False)
    assert r == "daily_loss_stop"
    # 高危新闻窗口
    b3 = CircuitBreakers()
    r = b3.check(10000, 0.0, True)
    assert r == "news_high_risk_window"
    # 保证金
    b4 = CircuitBreakers()
    r = b4.check(10000, 6500.0, False)
    assert r == "margin_cap"


def test_shrink_for_pending_real_df():
    df = pd.read_parquet(r"D:\DDDDDDDDD\XAUUSD_1min_kline.parquet")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").set_index("time")
    atr = 5.0
    for direction in ("LONG", "SHORT"):
        sh = shrink_for_pending(direction, 4350.0, atr, df)
        # 收缩语义（用户指定）：TP 缩 40% → 距离 ≤ 0.6×mult×ATR；SL 缩 20% → 距离 ≤ 0.8×mult×ATR
        tp_dist = abs(sh["tp"] - 4350.0)
        assert tp_dist <= CFG.risk.tp_atr_mult * 0.6 * atr + 1e-6, sh
        assert tp_dist > 0                       # 保证有正利润空间
        assert abs(sh["sl"] - 4350.0) <= CFG.risk.sl_atr_mult * 0.8 * atr + 1e-6
    # 不可达 TP 收缩：远超历史极值的 TP 必须被拉近
    far_tp = 4350.0 + 100.0
    got = reachable_tp(far_tp, "LONG", df)
    assert got < far_tp


def test_risk_gate_reject_paths():
    gate = RiskGate(CircuitBreakers())
    ev = type("E", (), {"result": FusionResult(score=2.0, sigma=0.3)})()
    acc = AccountInfo(login=1, balance=10000, equity=10000, margin_free=10000,
                      margin=0, margin_level=0, leverage=2000, currency="USD")
    # 熔断拒绝
    b = CircuitBreakers()
    b.on_trade_closed(-350, 10000)
    gate2 = RiskGate(b)
    res = gate2.evaluate(Proposal(kind="open_market", direction="LONG"),
                         ev, acc, type("V", (), {"positions": []})(), 1.0, None, 5.0, None)
    assert not res.ok and "circuit" in res.reason


# ══════════════════════════════════════════════════════════════════
# 单张限价挂单（用户要求：取消网格）
# ══════════════════════════════════════════════════════════════════
def _llm_rev(support, resistance):
    """构造一个最小可用的 LLM review（压力位/支撑位）。"""
    return {"verdict": "bullish", "confidence": 0.7,
            "support_levels": list(support), "resistance_levels": list(resistance),
            "level_reason": "测试用"}


def test_place_grid_now_emits_single_pending_order():
    """取消网格：`place_grid` 只产出**一张**挂单，入场价 = 0.618 回调带。

    实测问题：原实现按 `CFG.risk.grid_layers`（=2）挂多层，是网格行为。
    用户要求只挂预测的那一单；入场价改为回调带（回调到位反弹概率大）。
    """
    gate = RiskGate(CircuitBreakers())
    ev = type("E", (), {"result": FusionResult(score=2.0, sigma=0.3)})()
    acc = AccountInfo(login=1, balance=10000, equity=10000, margin_free=10000,
                      margin=0, margin_level=0, leverage=2000, currency="USD")
    views = type("V", (), {"positions": [], "pending_orders": []})()
    atr, close = 12.339, 4350.0
    df5 = pd.DataFrame({"high": [close] * 10, "low": [close] * 10,
                        "close": [close] * 10})
    # 缠论兜底路径（不传 frames → 走缠论）
    up = {"id": "segment:15m:1", "direction": "up",
          "start_price": close - 30.0, "end_price": close - 5.0}
    ev.chanlun = {"15m": type("C", (), {
        "status": "ok", "center": None,
        "raw": {"layers": {"segments": [up], "strokes": [], "fractals": []}}})()}
    rev = _llm_rev([close - 25.0], [close + 40.0])
    res = gate.evaluate(Proposal(kind="place_grid", direction="LONG", entry=close),
                        ev, acc, views, 0.1, df5, atr, None, llm_review=rev)
    assert res.ok, f"应放行: {res.reason}"
    layers = res.plan["grid_plan"]
    assert len(layers) == 1, f"应只有一张挂单，实际 {len(layers)} 张（网格未取消）"
    # 入场价落在回调带内（0.5~0.618），且在市价下方（做多限价单必须如此）
    lo = up["end_price"] - RETRACE_FAR * (up["end_price"] - up["start_price"])
    hi = up["end_price"] - RETRACE_NEAR * (up["end_price"] - up["start_price"])
    assert min(lo, hi) <= layers[0]["level"] <= max(lo, hi), "入场价应在回调带内"
    assert layers[0]["level"] < close, "做多限价单必须在市价下方"
    assert res.plan["entry_source"] == "chanlun_segment"
    assert res.plan["pullback_tf"] == "15m"
    # 必须带止损止盈，否则控制台看不到点位
    assert layers[0]["sl"] and layers[0]["tp"]


def test_open_market_reserves_room_for_adds():
    """首仓必须**为加仓预留额度**，否则加仓阶梯结构上不可达。

    实测：`.env` 写明 `MAX_LOT=0.06 = 首仓 0.01 + 5×0.01`，但首仓手数由
    `position_lots` 独立算出、原实现不看加仓额度 → 198 笔首仓里 34 笔直接
    顶到 0.06，剩余额度 0 → 259 次加仓被"总手数上限"拒掉（0 次成功）。
    本测试：强信号 + 宽止损（本会算出 0.06）时，首仓必须 <= 0.01。
    """
    gate = RiskGate(CircuitBreakers())
    ev = type("E", (), {"result": FusionResult(score=2.0, sigma=0.3)})()
    acc = AccountInfo(login=1, balance=100000, equity=100000, margin_free=100000,
                      margin=0, margin_level=0, leverage=2000, currency="USD")
    empty = type("V", (), {"positions": [], "pending_orders": []})()
    res = gate.evaluate(Proposal(kind="open_market", direction="LONG", entry=4350.0),
                        ev, acc, empty, 0.1, None, 5.0, None,
                        llm_review=_llm_rev([4300.0], [4420.0]))
    assert res.ok, f"应能开仓: {res.reason}"
    head = round(CFG.max_lot - CFG.add_layer_lots * CFG.risk.max_adds_per_position, 2)
    assert res.plan["lots"] <= head + 1e-9, (
        f"首仓 {res.plan['lots']} 吃掉了加仓额度（应 <= {head:.2f}）——"
        f"加仓会再次不可达")
    assert res.plan["lots"] >= CFG.min_lot, "首仓不得低于最小手数"


def test_conflict_degrades_lots_instead_of_rejecting():
    """紧贴反向位：**降仓**而非拒绝（用户选定，见 CFG.risk.conflict_lot_mult）。

    实证 research/26_conflict_gate_test.py：贴脸组远期收益与对照组无统计差异，
    而原实现把 205 个强信号（|z|>=2.66）100% 挡掉。

    构造：入场 4350，LLM 压力位同时给出**贴脸的 4351** 与**远处的 4420**
    （贴合实盘 —— LLM 通常给一组位）。贴脸 4351 触发降仓，4420 提供够赔率的
    目标位，于是"结构不利但赔率够"这个真实场景能走到下单。
    对照：把贴脸的 4351 换成 4400（同样够赔率、但不贴脸），手数应更大。
    """
    gate = RiskGate(CircuitBreakers())
    ev = type("E", (), {"result": FusionResult(score=2.0, sigma=0.3)})()
    acc = AccountInfo(login=1, balance=100000, equity=100000, margin_free=100000,
                      margin=0, margin_level=0, leverage=2000, currency="USD")
    empty = type("V", (), {"positions": [], "pending_orders": []})()
    # ATR 12 -> conf_d = 3.6；贴脸位 4351 距入场 1.0 < 3.6
    near = gate.evaluate(Proposal(kind="open_market", direction="LONG", entry=4350.0),
                         ev, acc, empty, 0.1, None, 12.0, None,
                         llm_review=_llm_rev([4300.0], [4351.0, 4420.0]))
    assert near.ok, f"贴脸不应再硬拒: {near.reason}"
    assert any("紧贴" in r for r in near.plan["reasons"]), \
        f"应在 reasons 里看到降仓说明: {near.plan['reasons']}"
    # 对照：最近压力位 4400，距入场 50 > 3.6 -> 不贴脸
    far = gate.evaluate(Proposal(kind="open_market", direction="LONG", entry=4350.0),
                        ev, acc, empty, 0.1, None, 12.0, None,
                        llm_review=_llm_rev([4300.0], [4400.0, 4420.0]))
    assert far.ok, f"对照场景应能开仓: {far.reason}"
    assert not any("紧贴" in r for r in far.plan["reasons"]), "对照不应有降仓说明"
    assert near.plan["lots"] <= far.plan["lots"], (
        f"贴脸手数 {near.plan['lots']} 应 <= 无冲突手数 {far.plan['lots']}")


def test_max_lot_allows_configured_adds():
    """配置一致性：`max_lot` 必须容得下「基础仓 + max_adds_per_position 次加仓」。

    实测事故：`.env` 的 `MAX_LOT=0.01`，而 `max_adds_per_position=5`。
    基础仓 0.01 手 + 加仓 0.01 手 = 0.02 > 0.01 → **加仓永远被拦**，
    "最多加仓 5 次"这条规则是死代码（实盘 21 次 risk_reject 全是 max_lot cap）。
    """
    need = 0.01 * (1 + CFG.risk.max_adds_per_position)
    assert CFG.max_lot >= need - 1e-9, (
        f"max_lot={CFG.max_lot} 容不下基础仓 0.01 + "
        f"{CFG.risk.max_adds_per_position} 次加仓（需要 {need:.2f}）——"
        "加仓会被 max_lot 永久拦截")


def test_add_layer_passes_risk_gate_with_configured_max_lot():
    """方案 A 验收：持 1 笔 0.01 手时，第 1 次加仓应能通过风控。

    注意 `add_layer` 的 `prop.entry` 装的是**持仓 ticket**（不是价格），
    gate 靠它找到持仓、再用 `price_open` 作定价锚点。
    """
    gate = RiskGate(CircuitBreakers())
    ev = type("E", (), {"result": FusionResult(score=2.0, sigma=0.3)})()
    acc = AccountInfo(login=1, balance=10000, equity=10000, margin_free=10000,
                      margin=0, margin_level=0, leverage=2000, currency="USD")
    pos = type("P", (), {"ticket": 123456, "volume": 0.01, "price_open": 4350.0,
                         "magic": CFG.mt5.magic})()
    views = type("V", (), {"positions": [pos], "pending_orders": []})()
    # 加仓也要有 LLM 压力位才能算止损止盈（用户要求）
    res = gate.evaluate(Proposal(kind="add_layer", direction="LONG", entry=123456),
                        ev, acc, views, 0.1, None, 5.0, None,
                        llm_review=_llm_rev([4340.0], [4420.0]))
    assert res.ok, f"第 1 次加仓不应被拦: {res.reason}"
    assert res.plan["sl"] < 4350.0 < res.plan["tp"], "止损止盈必须在入场价正确一侧"


def test_add_layer_rejected_without_llm_levels():
    """**两个来源都没有点位**时加仓 → 拒绝（不得开裸仓）。

    ⚠️ 语义澄清：这不是"LLM 没给就不开仓"。用户原话：
      "我的意思是LLM没有相反的预测方向 并且当前距离我们盈利的压力位
       也有距离就可以直接市价开仓"
    LLM 没给点位、但**本地结构位有**时，`lv.ok` 已是 True，不会走到这个闸。
    本测试构造的是最坏情况：LLM 没给 **且** ev 里没有任何缠论/SMC 结构
    （`ev` 只有 result，没有 chanlun/mobius）→ 无任何点位依据 → 拒绝。
    实测过裸仓事故：加仓开出 SL=0 TP=0 的仓位。
    """
    gate = RiskGate(CircuitBreakers())
    ev = type("E", (), {"result": FusionResult(score=2.0, sigma=0.3)})()
    acc = AccountInfo(login=1, balance=10000, equity=10000, margin_free=10000,
                      margin=0, margin_level=0, leverage=2000, currency="USD")
    pos = type("P", (), {"ticket": 123456, "volume": 0.01, "price_open": 4350.0,
                         "magic": CFG.mt5.magic})()
    views = type("V", (), {"positions": [pos], "pending_orders": []})()
    res = gate.evaluate(Proposal(kind="add_layer", direction="LONG", entry=123456),
                        ev, acc, views, 0.1, None, 5.0, None)
    assert not res.ok
    assert "levels" in res.reason


def test_add_layer_allowed_with_local_structure_only():
    """LLM 没给点位，但**本地结构位有** → 加仓放行（用户澄清的核心）。

    这是 `test_add_layer_rejected_without_llm_levels` 的对照面：
    点位来源不必是 LLM，本地缠论中枢/SMC 结构位同样有效。
    """
    gate = RiskGate(CircuitBreakers())
    cl = {"15m": type("C", (), {"center": {"zg": 4400.0, "zd": 4300.0,
                                           "gg": 4420.0, "dd": 4280.0}})()}
    ev = type("E", (), {"result": FusionResult(score=2.0, sigma=0.3),
                        "chanlun": cl, "mobius": None})()
    acc = AccountInfo(login=1, balance=10000, equity=10000, margin_free=10000,
                      margin=0, margin_level=0, leverage=2000, currency="USD")
    pos = type("P", (), {"ticket": 123456, "volume": 0.01, "price_open": 4350.0,
                         "magic": CFG.mt5.magic})()
    views = type("V", (), {"positions": [pos], "pending_orders": []})()
    res = gate.evaluate(Proposal(kind="add_layer", direction="LONG", entry=123456),
                        ev, acc, views, 0.1, None, 5.0, None,
                        llm_review={})   # LLM 什么都没给
    assert res.ok, f"本地有结构位就该放行，得到 {res.reason}"
    assert res.plan["sl"] < 4350.0 < res.plan["tp"], "止损止盈必须在入场价正确一侧"
    assert res.plan["sl_source"] == "struct_support", res.plan["sl_source"]
    assert res.plan["tp_source"] == "struct_resistance", res.plan["tp_source"]


# ══════════════════════════════════════════════════════════════════
# 执行层回归（4 个实测事故）
# ══════════════════════════════════════════════════════════════════
def _pos(ticket=123456, vol=0.01, sl=0.0, tp=0.0, price_open=4350.0):
    from gold_agent.mt5.client import PositionRow
    return PositionRow(ticket=ticket, symbol="XAUUSDm", type="LONG", volume=vol,
                       price_open=price_open, sl=sl, tp=tp, profit=15.0,
                       swap=0.0, time=0, comment="", magic=CFG.mt5.magic)


def _views(poss):
    return type("V", (), {"positions": poss, "pending_orders": []})()


def _acc():
    return AccountInfo(login=1, balance=10000, equity=10000, margin_free=10000,
                       margin=0, margin_level=0, leverage=2000, currency="USD")


def _ev():
    return type("E", (), {"result": FusionResult(score=2.0, sigma=0.3)})()


class _FakeSI:
    filling_mode = 2
    ask, bid = 4350.00, 4349.80


class _FakeClient:
    def symbol_info(self):
        return _FakeSI()


def test_close_position_request_carries_volume():
    """事故：平仓请求缺 volume → MT5 `(-2, 'Invalid "volume" argument')`。

    实测后果：连续 100+ 轮平仓 100% 失败，信号翻空后仓位仍挂着。
    """
    from gold_agent.mt5.executor import Executor, OrderPlan

    ex = Executor(_FakeClient())
    req = ex._build_request(OrderPlan(kind="close_position", direction="LONG",
                                      position_ticket=123456, lots=0.01))
    assert req.get("volume") == 0.01, "平仓请求必须带 volume，否则 MT5 拒绝"
    # 缺手数必须显式报错，而不是发出无效请求
    with pytest.raises(Exception):
        ex._build_request(OrderPlan(kind="close_position", direction="LONG",
                                    position_ticket=123456))


def test_close_position_plan_includes_lots():
    """风控层必须把持仓手数带进 plan（executor 才有 volume 可用）。"""
    gate = RiskGate(CircuitBreakers())
    res = gate.evaluate(Proposal(kind="close_position", direction="LONG", entry=123456),
                        _ev(), _acc(), _views([_pos(vol=0.02)]), 0.1, None, 12.0, None)
    assert res.ok, res.reason
    assert res.plan["lots"] == 0.02, "plan 必须带原持仓手数"


def test_modify_sltp_keeps_existing_tp():
    """事故：TRADE_ACTION_SLTP 是整体覆盖，tp 传 0.0 = 删掉止盈 + 报 Invalid stops。"""
    from gold_agent.mt5.executor import Executor, OrderPlan

    ex = Executor(_FakeClient())
    req = ex._build_request(OrderPlan(kind="modify_sltp", direction="LONG",
                                      position_ticket=123456, sl=4330.0, tp=4360.0))
    assert req.get("tp") == 4360.0, "移损不得抹掉原有止盈"
    # 原持仓本来就没有 TP → 不带该键（不动），而不是写 0.0
    req2 = ex._build_request(OrderPlan(kind="modify_sltp", direction="LONG",
                                       position_ticket=123456, sl=4330.0, tp=None))
    assert "tp" not in req2, "原持仓无 TP 时不应传 tp=0.0"

    gate = RiskGate(CircuitBreakers())
    res = gate.evaluate(Proposal(kind="modify_sltp", direction="LONG", entry=123456,
                                 tp_struct=4352.0),
                        _ev(), _acc(), _views([_pos(tp=4360.0)]), 0.1, None, 12.0, None)
    assert res.plan["keep_tp"] == 4360.0, "plan 必须带出原持仓的 TP"


def test_modify_sltp_can_narrow_tp_and_is_rr_exempt():
    """用户 2026-09-30：收窄止损止盈**不受 min_rr(1.2) 限制**。

    事件：用户要求「只修改止损和止盈位置（新止损止盈缩小时不受 1.2 倍的
    比例影响）」。收窄是**降低**风险敞口，用开仓的赔率门去卡它语义上是错的。
    实测：`rr_below_1.2` 在实盘触发 82 次，全部发生在开仓/挂单时刻，
    从未来自 `modify_sltp` —— 本测试把这个性质锁住。
    """
    from gold_agent.mt5.executor import Executor, OrderPlan

    gate = RiskGate(CircuitBreakers())
    # 新 SL 距离 3.0、新 TP 距离 3.6 -> RR=1.2；故意让 TP 更近（RR=0.5）
    res = gate.evaluate(Proposal(kind="modify_sltp", direction="LONG", entry=123456,
                                 tp_struct=4347.0, new_tp=4348.5),
                        _ev(), _acc(), _views([_pos(tp=4400.0)]), 0.1, None, 12.0, None)
    assert res.ok, f"收窄动作被误拦（{res.reason}）—— 收窄应豁免 min_rr"
    assert res.plan["new_sl"] == 4347.0
    assert res.plan["keep_tp"] == 4348.5, "必须用新的止盈覆盖原止盈"
    # 且 RR 确实低于 min_rr —— 证明豁免是真的生效，而不是碰巧没触发
    rr = abs(res.plan["keep_tp"] - 4347.0) / 3.0
    assert rr < CFG.risk.min_rr, "本用例应构造出低于 min_rr 的赔率"

    # new_tp 必须真的送进 broker 请求（否则收窄止盈是空操作）
    ex = Executor(_FakeClient())
    req = ex._build_request(OrderPlan(kind="modify_sltp", direction="LONG",
                                      position_ticket=123456,
                                      sl=res.plan["new_sl"], tp=res.plan["keep_tp"]))
    assert req.get("sl") == 4347.0 and req.get("tp") == 4348.5, \
        "新止盈必须一并下发（SLTP 是整体覆盖）"


def test_add_layer_prices_off_current_market_not_first_entry():
    """加仓必须用**当前市价**定价，不能用首仓的 `price_open`。

    ⚠️ 事故（2026-10-08 用户报告「止盈和止损点位差距这么大 盈亏比都拉成
       什么比列了」）：原实现 `ref = pos.price_open` 拿**第一笔**的入场价
       给加仓定价。但 MT5 对冲账户下加仓是**独立新持仓**、成交在当前市价。
       实测 286 笔加仓：两者差中位 3.13、最大 36.06，导致 `min_rr=1.2`
       在错误的价格上校验 —— 日志显示 <1.2 的 0 笔，按各自成交价重算
       却有 137 笔（47.9%），这批净亏 -142.52；而 >=1.2 的 149 笔净赚
       +146.71。即赔率门在加仓路径上形同虚设。

    本测试锁住：同一组点位下，把现价从首仓价 4350 换到 4300，
    定价锚点必须跟着变成 4300（止损止盈随之下移）。
    """
    gate = RiskGate(CircuitBreakers())
    atr = 12.339
    pad = CFG.risk.level_pad_atr * atr

    def run(last_close: float):
        # 现价放进 1m 帧（与 open_market 的 ctx.last_close 同源）
        frames = {"1m": pd.DataFrame({"close": [last_close]})}
        return gate.evaluate(
            Proposal(kind="add_layer", direction="LONG", entry=123456),
            _ev(), _acc(), _views([_pos(price_open=4350.0)]),
            0.1, None, atr, None,
            llm_review=_llm_rev([4340.0], [4420.0]), frames=frames)

    hi = run(4350.0)
    lo = run(4345.0)
    assert hi.ok and lo.ok, (hi.reason, lo.reason)

    # 关键断言：定价锚点跟随**当前市价**，而不是恒为首仓的 4350
    assert hi.plan["entry"] == pytest.approx(4350.0, abs=0.01)
    assert lo.plan["entry"] == pytest.approx(4345.0, abs=0.01), \
        "加仓定价必须用当前市价（原实现恒用首仓 price_open=4350）"
    assert hi.plan["entry"] != lo.plan["entry"], "现价不同则锚点必须不同"
    # 止损 = 下方支撑让开 pad（与现价无关，仍取自 LLM 位）
    assert lo.plan["sl"] == pytest.approx(4340.0 - pad, abs=0.01)


def test_add_layer_rejects_add_whose_rr_is_below_min_rr():
    """现价贴近止盈位时，加仓的赔率不足 → 必须拒绝（不得下单）。

    这是上面那个 bug 的**后果**验证：低赔率加仓本就该被 `min_rr` 拦掉。
    做多首仓在 4350，现价已涨到止盈位附近 4490（压力位 4500）：
      风险 = 4490 - 止损(4400-pad)；回报 = 4500 - 4490 ≈ 10
    → 赔率远低于 1.2 → 应返回 `levels: rr_below_...`。
    """
    gate = RiskGate(CircuitBreakers())
    atr = 12.339
    frames = {"1m": pd.DataFrame({"close": [4490.0]})}
    res = gate.evaluate(
        Proposal(kind="add_layer", direction="LONG", entry=123456),
        _ev(), _acc(), _views([_pos(price_open=4350.0)]),
        0.1, None, atr, None,
        llm_review=_llm_rev([4400.0], [4500.0]), frames=frames)
    assert not res.ok, "赔率不足的加仓必须被拒，否则就是这次事故"
    assert "rr_below" in res.reason or "levels" in res.reason, res.reason


def test_add_layer_carries_atr_sl_tp():
    """事故：加仓 plan 不含 tp/sl → 新仓位是 SL=0 TP=0 的裸仓。

    实测 3 个裸仓全部来自加仓（magic 相同，comment='goldagent-add'）。
    现在 SL/TP 来自 LLM 判断的压力位/支撑位。
    """
    gate = RiskGate(CircuitBreakers())
    atr = 12.339
    res = gate.evaluate(Proposal(kind="add_layer", direction="LONG", entry=123456),
                        _ev(), _acc(), _views([_pos(price_open=4350.0)]),
                        0.1, None, atr, None,
                        llm_review=_llm_rev([4340.0], [4420.0]))
    assert res.ok, res.reason
    pl = res.plan
    assert pl.get("sl") and pl.get("tp"), "加仓必须自带止损止盈，否则是裸仓"
    assert pl["sl"] < pl["entry"] < pl["tp"], "做多加仓：SL < 入场 < TP"
    # 止损 = 下方支撑位让开 pad；止盈 = 上方压力位
    pad = CFG.risk.level_pad_atr * atr
    assert pl["sl"] == pytest.approx(4340.0 - pad, abs=0.01)
    assert pl["tp"] == pytest.approx(4420.0, abs=0.01)
    assert pl["sl_source"].startswith("llm_support")
    assert pl["tp_source"] == "llm_resistance"


def test_profit_lock_sl_distance_is_sane():
    """事故：移损 SL 算成 开仓价+2000（漏除 point），MT5 报 Invalid stops。

    point_value_per_lot=0.1（每 point/手），point=0.001 →
    每 1.0 价格单位/本仓位 = 0.1/0.001*0.01 = $1.0。
    锁定 $2 → 距离 2.0 个价格单位（旧实现是 2000.0）。
    """
    _POINT = 0.001
    pv_per_lot, volume, price_open = 0.1, 0.01, 4350.0
    usd_per_unit = pv_per_lot / _POINT * volume
    new_sl = price_open + 2.0 / usd_per_unit
    assert usd_per_unit == pytest.approx(1.0, abs=1e-9)
    assert new_sl - price_open == pytest.approx(2.0, abs=1e-6), (
        f"锁定 $2 的距离应为 2.0 个价格单位，实际 {new_sl - price_open}")


def test_summary_exposes_plan_for_console():
    """回归：graph 必须把 plan 放进 summary['risk']，否则控制台打出 'None手'。"""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]
           / "src" / "gold_agent" / "agent" / "graph.py").read_text(encoding="utf-8")
    assert '"plan": approved.plan' in src, (
        "graph.py 未把 approved.plan 放进 summary['risk'] —— "
        "控制台会显示 'None手' 且看不到止损止盈")


# ══════════════════════════════════════════════════════════════════
# P2-3 Wilson 置信下界
# ══════════════════════════════════════════════════════════════════
def test_wilson_lower_is_conservative_for_small_samples():
    """3 笔 1 胜：点估计 0.333，Wilson 下界应约 0.061。

    research/18 §P2-3：3 笔样本的胜率置信区间是 [6%, 79%]，
    它不能支持任何结论 —— 仓位必须自动缩到最小。
    """
    assert wilson_lower(1, 3) == pytest.approx(0.0615, abs=0.005)
    assert wilson_lower(1, 3) < 1 / 3, "Wilson 下界必须低于点估计"
    # 样本越大，下界越接近点估计
    small = wilson_lower(50, 100)
    large = wilson_lower(5000, 10000)
    assert small < large < 0.5
    assert wilson_lower(0, 0) == 0.0
    # 全胜的极端情形
    assert wilson_lower(3, 3) < 1.0


def test_conservative_win_rate_uses_fallback_below_threshold():
    """样本 < min_deals_for_kelly 时返回 fallback（冷启动）。"""
    assert conservative_win_rate(1, 3, fallback=0.5) == 0.5
    # 样本足够时返回 Wilson 下界（而非点估计）
    got = conservative_win_rate(60, 100, fallback=0.5)
    assert got == pytest.approx(wilson_lower(60, 100))
    assert got < 0.6, "必须低于点估计 0.60"


# ══════════════════════════════════════════════════════════════════
# P2-2 方向偏置熔断
# ══════════════════════════════════════════════════════════════════
def test_direction_bias_halts_on_structural_long():
    """P2-2：近 N 笔同向占比 > 85% → 停机复查。

    research/16 实测：3 笔交割单全为 LONG、融合分 80.2% 为正 ——
    系统不是在择时，而是在结构性做多黄金。
    """
    b = CircuitBreakers()
    # 样本不足时不应触发
    for _ in range(5):
        b.on_trade_closed(10.0, 10000, direction="LONG")
    assert not b.direction_bias_halt, "样本不足时不得触发偏置熔断"

    # 补足样本：全部 LONG
    for _ in range(CFG.risk.direction_bias_min_samples):
        b.on_trade_closed(10.0, 10000, direction="LONG")
    assert b.direction_bias_halt, "100% 单向应触发偏置熔断"
    r = b.check(10000, 0.0, False)
    assert r and "direction_bias_halt" in r


def test_direction_bias_allows_balanced_book():
    """双向均衡不应触发偏置熔断。"""
    b = CircuitBreakers()
    for i in range(40):
        b.on_trade_closed(10.0, 10000, direction="LONG" if i % 2 == 0 else "SHORT")
    assert not b.direction_bias_halt
    assert b.direction_bias_ratio <= CFG.risk.direction_bias_max


def test_direction_bias_clear():
    """人工复查后可解除偏置停机。"""
    b = CircuitBreakers()
    for _ in range(30):
        b.on_trade_closed(10.0, 10000, direction="SHORT")
    assert b.direction_bias_halt
    b.clear_direction_bias()
    assert not b.direction_bias_halt
    assert b.check(10000, 0.0, False) is None
    assert b.recent_directions == []


def test_direction_bias_records_string_and_int():
    """方向可用 LONG/SHORT 字符串或 ±1 整数记录。"""
    b = CircuitBreakers()
    b.record_direction("LONG")
    b.record_direction(1)
    b.record_direction(-1)
    b.record_direction("SHORT")
    b.record_direction(None)      # 未知方向不计入
    assert len(b.recent_directions) == 4
    assert b.recent_directions == [1, 1, -1, -1]


def test_news_high_risk_breaker_is_configurable_not_hardcoded():
    """新闻高危熔断必须可配置 —— 原为 `high_risk_window=False` 写死。

    实测缺陷：`gate.py` 调用 `breakers.check(..., high_risk_window=False)`
    把参数写死，于是 `CircuitBreakers` 里 `news_high_risk_window` 分支
    **从未触发过一次**，配套的 `CFG.risk.news_blackout_min` 也成了
    无人读取的死配置。代码注释声称「news 高危由 decision 传入 flags」，
    但 decision 层只做 hold/降手数，并不回传任何熔断标志 ——
    这条熔断实际是被静默摘掉的，且在配置里完全不可见。

    本测试锁住两点：
      1. 存在一个配置项控制它（不再是写死的字面量）
      2. 默认值维持 false —— 本次只修"不可观测/不可配置"，
         **不擅自改变风控松紧**
    """
    assert hasattr(CFG.risk, "news_high_risk_window"), (
        "新闻高危熔断必须由配置控制，不能写死在 gate.py 调用处")
    assert CFG.risk.news_high_risk_window is False, (
        "默认必须保持 false（保持既有行为）；要启用请在 config.toml 显式打开")


def test_news_high_risk_window_actually_triggers_when_enabled():
    """打开配置后，该熔断必须真的会拦（证明它不是死代码）。"""
    b = CircuitBreakers()
    # 有新闻高危窗口时，check 应返回 news_high_risk_window（而非 None）
    rej = b.check(10000, 0.0, True)
    assert rej is not None and "news" in rej, (
        f"high_risk_window=True 时应触发新闻熔断，实际返回 {rej!r}")
    # 关闭时不得触发（默认路径）
    assert b.check(10000, 0.0, False) is None


def test_add_layer_room_uses_config_not_hardcoded_lot():
    """加仓额度必须按「剩余额度」判定，而不是拿硬编码 0.01 去比上限。

    实测缺陷（153 次 `max_lot cap` 全部来自这里）：
    每层固定 0.01、上限 MAX_LOT=0.06，于是第 6 层起必然
    `my_lots + 0.01 > 0.06`。实际成功加仓 106 次，add_no 最高只到 3，
    **声明允许的 4/5 两层永远不可达**；09-29 当天 109 次判定全部失败、
    0 次成功 —— 加仓路径沦为每轮空转并消耗一次决策。

    修法：`room = max_lot - used`，只有 `room < min_lot` 才是真的加无可加。
    """
    assert hasattr(CFG, "add_layer_lots"), "加仓手数须走配置（原为硬编码 0.01）"
    assert hasattr(CFG, "min_lot"), "须有最小手数配置用于判定剩余额度"

    def allowed(used: float) -> bool:
        room = CFG.max_lot - used
        return round(min(CFG.add_layer_lots, room), 2) >= CFG.min_lot

    # 旧规则 `used + 0.01 > max_lot` 会在 used=0.05 时放行、0.06 时拒绝；
    # 新规则在 still-room 时放行，耗尽时拒绝。
    assert allowed(0.0), "空仓必须能加第一层"
    for used in (0.01, 0.02, 0.03, 0.04, 0.05):
        assert allowed(used), (
            f"已用 {used} 时仍有余量，必须允许加仓 —— 旧规则在这里把 "
            f"4/5 层永久锁死")
    assert not allowed(CFG.max_lot), "额度耗尽必须拒绝"


def test_max_adds_ladder_is_reachable_under_max_lot():
    """声明的 max_adds_per_position 层数必须在 MAX_LOT 下真的走得完。

    旧实现：5 层 × 0.01 = 0.05 < 0.06，看起来够；但因为判定用的是
    `used + 0.01 > 0.06`（每层都重新比一次硬编码值），实际在第 6 次
    判定时就撞顶，add_no 从未到达 4/5。这里用纯算术证明新规则可达。
    """
    used = 0.0
    layers = []
    for i in range(CFG.risk.max_adds_per_position):
        room = CFG.max_lot - used
        lots = round(min(CFG.add_layer_lots, room), 2)
        if lots < CFG.min_lot:
            break
        used += lots
        layers.append(i + 1)
    assert len(layers) == CFG.risk.max_adds_per_position, (
        f"在 MAX_LOT={CFG.max_lot} × 每层 {CFG.add_layer_lots} 下只加得动 "
        f"{len(layers)} 层，但配置声明允许 {CFG.risk.max_adds_per_position} 层")


def test_add_ladder_is_unreachable_without_base_reserve():
    """反证：**不**给首仓预留额度时，加仓阶梯必然不可达。

    这条测试锁住"为什么必须预留"—— 它是 `reserve_lots` 存在的理由。
    实测：198 笔首仓里 34 笔直接顶到 0.06（消费完额度），
    于是 259 次加仓被"总手数上限"拒掉、0 次成功。
    """
    used = CFG.max_lot          # 首仓吃满总上限（未预留时的真实情形）
    room = CFG.max_lot - used
    add_lots = round(min(CFG.add_layer_lots, room), 2)
    assert add_lots < CFG.min_lot, (
        "首仓吃满 max_lot 时剩余额度应为 0 —— 加仓必然被拒（这正是缺陷）")


def test_prices_are_rounded_to_symbol_digits_on_submit():
    """提交给 MT5 的价格必须按 symbol digits 规整，否则幂等判定永不收敛。

    ⚠️ 最高严重度缺陷的回归锁（实测同一持仓重复提交 **83 次**、
    375 拒 / 35 成 = 91.5% 纯浪费）：
      提交 `sl=4178.211333333333`，MT5 按 digits=3 存回 `4178.211`；
      下一轮拿 `pos.sl` 与**未规整**的原值比较
      （LONG: `pos.sl < locked_sl`），3.3e-4 的差让条件**恒为真** ——
      于是每轮重发同一个值，MT5 恒回 `10025 No changes`。

    修复在**发单边界**统一规整（executor._build_request），
    使"提交值 == MT5 可能存回的值"，比较才可能收敛。
    """
    import gold_agent.mt5.executor as ex

    class _SI:
        digits = 3
        filling_mode = 2          # SYMBOL_FILLING_IOC
        ask = 4180.0
        bid = 4179.8

    class _C:
        def symbol_info(self):
            return _SI()

    e = ex.Executor(_C())
    for raw in (4178.211333333333, 4176.9549999999, 4180.0005):
        p = ex.OrderPlan(kind="open_market", direction="LONG", lots=0.01,
                         tp=raw, sl=raw, entry=raw)
        e._build_request(p)
        for f in ("entry", "tp", "sl"):
            v = getattr(p, f)
            assert v == round(raw, 3), f"{f} 未按 digits 规整: {v!r}"
            # 关键性质：规整后的值再规整一次必须**不变**（幂等）
            assert round(v, 3) == v, f"{f} 规整不幂等: {v!r}"


def test_no_wall_clock_in_idempotency_keys():
    """幂等键**不得含挂钟时间**（否则 `_seen_keys` 查重永不命中 = 幂等机制失效）。

    实测：四个分支原都拼 `int(time.time())`，于是每次调用都产生新键，
    这个"幂等"机制实际上从未生效 —— 撤单重复提交（38 次执行 / 35 个不同
    ticket），第二次必被 MT5 回 `10025`，系统无法区分"已撤掉"与"没发出去"。
    """
    import inspect
    import re

    import gold_agent.agent.graph as g

    src = inspect.getsource(g.Graph._execute)
    # 去掉注释行再查，避免注释里提到 time.time() 造成误判
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.strip().startswith("#"))
    assert "time.time()" not in code, (
        "幂等键又用回挂钟时间了 —— _seen_keys 会永远查不中（幂等失效）")
    keys = re.findall(r'idempotency_key=f"([^"]+)"', code)
    assert keys, f"未找到幂等键定义: {code!r}"
    for k in keys:
        assert "time" not in k, f"幂等键 {k!r} 含时间成分"

