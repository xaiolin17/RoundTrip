# -*- coding: utf-8 -*-
"""组合级（多品种）风险闸的真实测试。

核心契约有两条，缺一不可：
  1. **单品种时必须空操作** —— 否则会改变现有黄金实盘行为；
  2. **多品种时必须真的拦住** —— 否则是摆设。

第 2 条里最关键的是**组合回撤**：各品种的 `CircuitBreakers` 只看自己的
盈亏，组合整体巨亏而各品种各自未到线时，只有这一层能兜住。
"""
from __future__ import annotations

import pytest

from gold_agent.common.config import CFG
from gold_agent.risk.portfolio import (PortfolioRisk, PortfolioState,
                                       build_state)


@pytest.fixture
def multi(monkeypatch):
    """切到多品种模式（组合闸生效）。"""
    monkeypatch.setenv("TRADE_SYMBOLS", "XAUUSDm,BTCUSDm,USOILm,EURUSDm,USDJPYm")
    assert CFG.multi_symbol is True
    return CFG


@pytest.fixture
def single(monkeypatch):
    """单品种模式（组合闸必须空操作）。"""
    monkeypatch.delenv("TRADE_SYMBOLS", raising=False)
    monkeypatch.setenv("MT5_SYMBOL", "XAUUSDm")
    assert CFG.multi_symbol is False
    return CFG


# ══════════════════════════════════════════════════════════════════
# 契约 1：单品种空操作
# ══════════════════════════════════════════════════════════════════
def test_single_symbol_always_passes_even_when_limits_blown(single):
    """⚠️ 单品种时即使把所有限制都堆满也必须放行。

    这是"多品种支持不改变现有黄金实盘行为"的直接证据。
    若这条失败，说明改造把黄金的风控收紧了 —— 属于未授权的行为变更。
    """
    pf = PortfolioRisk(("XAUUSDm",))
    pf.update_pnl(-100000.0)          # 组合巨亏
    st = PortfolioState(
        risk_by_symbol={"XAUUSDm": 9.99},          # 风险爆表
        direction_by_symbol={"XAUUSDm": "LONG"},
        margin_by_symbol={"XAUUSDm": 9e9},         # 保证金爆表
        equity=10000.0, pnl_now=-99999.0)
    v = pf.check_for("BTCUSDm", 9.99, st)
    assert v.ok is True and v.lot_mult == 1.0
    assert v.reason is None


def test_single_symbol_budgets_equal_configured_values(single):
    """⚠️ 单品种时 LLM 预算必须**等于原配置**（60/24/24）。

    若这里变小，黄金的 LLM 可用率会下降 → 拿不到压力位 → 无法开仓。
    """
    b = CFG.per_symbol_budgets(1)
    assert b["review"] == CFG.llm.per_hour_budget == 60
    assert b["news"] == CFG.llm.news_per_hour_budget == 24
    assert b["add_review"] == CFG.llm.add_review_per_hour_budget == 24


# ══════════════════════════════════════════════════════════════════
# 契约 2a：组合回撤熔断（最关键）
# ══════════════════════════════════════════════════════════════════
def test_portfolio_drawdown_halts_when_symbols_individually_fine(multi):
    """⚠️ 本模块存在的**核心理由**：各品种各自未到线，组合已需熔断。

    场景：5 个品种各亏 2.4%（各自远低于 12% 的单品种熔断线），
    但组合合计回撤 12% → 必须熔断。单品种风控**结构上抓不到**这种情况。
    """
    monkeypatch_risk = CFG.risk
    cap = monkeypatch_risk.portfolio_drawdown_halt_pct
    assert cap == 0.12

    pf = PortfolioRisk(("XAUUSDm", "BTCUSDm"))
    equity = 10000.0
    pf.update_pnl(0.0)                         # 组合峰值 0
    # 组合现已亏 12%
    st = PortfolioState(risk_by_symbol={}, direction_by_symbol={},
                        margin_by_symbol={}, equity=equity,
                        pnl_now=-cap * equity)
    v = pf.check_for("XAUUSDm", 0.005, st)
    assert v.ok is False, "组合回撤 12% 竟然放行"
    assert v.reason and "portfolio_drawdown" in v.reason


def test_portfolio_drawdown_below_cap_allows(multi):
    """回撤低于上限必须放行（不能变成"永远熔断"）。"""
    pf = PortfolioRisk(("XAUUSDm",))
    equity = 10000.0
    pf.update_pnl(0.0)
    st = PortfolioState(equity=equity, pnl_now=-0.05 * equity)   # 5% < 12%
    v = pf.check_for("XAUUSDm", 0.005, st)
    assert v.ok is True


def test_portfolio_drawdown_anchor_is_first_observation_not_zero(multi):
    """⚠️ 回撤锚点必须是**首个观测值**，不能锚成 0。

    若锚成 0，账户已亏损时会凭空造出回撤 → 启动即熔断。
    这与 `CircuitBreakers` 里已修复的同类 bug 一致。
    """
    pf = PortfolioRisk(("XAUUSDm",))
    pf.update_pnl(-3000.0)                 # 启动时已亏 3000
    assert pf.peak_pnl == -3000.0, "峰值被错锚成 0"
    # 此刻回撤应为 0（起点），不是 30%
    assert pf.drawdown(-3000.0, 10000.0) == 0.0


# ══════════════════════════════════════════════════════════════════
# 契约 2b：总风险预算
# ══════════════════════════════════════════════════════════════════
def test_portfolio_risk_exhausted_rejects(multi):
    """已有风险已占满预算时，新仓必须被**拒绝**（不是缩到 0 手）。"""
    cap = CFG.risk.portfolio_risk_cap
    pf = PortfolioRisk(("XAUUSDm", "BTCUSDm"))
    st = PortfolioState(
        risk_by_symbol={"XAUUSDm": cap},          # 已占满
        direction_by_symbol={"XAUUSDm": "LONG"},
        equity=10000.0, pnl_now=0.0)
    v = pf.check_for("BTCUSDm", 0.005, st)
    assert v.ok is False
    assert v.reason == "portfolio_risk_exhausted"


def test_portfolio_risk_scales_lots_when_partially_available(multi):
    """预算只剩一半时，应**按比例缩手数**而不是直接拒绝。

    信号本身有效，只是总风险超额 —— 缩仓能保留机会同时守住预算。
    """
    cap = CFG.risk.portfolio_risk_cap          # 0.01
    pf = PortfolioRisk(("XAUUSDm", "BTCUSDm"))
    # 已有 0.0075（预算的 75%），本笔 0.005 -> 合计 0.0125 超 0.01
    st = PortfolioState(
        risk_by_symbol={"XAUUSDm": cap * 0.75},
        direction_by_symbol={"XAUUSDm": "LONG"},
        equity=10000.0, pnl_now=0.0)
    v = pf.check_for("BTCUSDm", 0.005, st)
    assert v.ok is True, "应缩仓而不是拒绝"
    assert v.lot_mult < 1.0
    # 缩后总风险应恰好落在预算内：0.0075 + 0.005*mult == 0.01 -> mult = 0.5
    assert v.lot_mult == pytest.approx(0.5, rel=1e-6)
    assert v.reason and "portfolio_risk_scale" in v.reason


def test_portfolio_risk_within_budget_passes_unchanged(multi):
    """总风险在预算内时必须原样放行（不缩仓、不拒绝）。"""
    pf = PortfolioRisk(("XAUUSDm",))
    st = PortfolioState(risk_by_symbol={}, direction_by_symbol={},
                        equity=10000.0, pnl_now=0.0)
    v = pf.check_for("XAUUSDm", 0.005, st)
    assert v.ok is True and v.lot_mult == 1.0


def test_portfolio_risk_excludes_own_symbol_to_avoid_double_count(multi):
    """⚠️ 合计"已有风险"必须**排除本品种**，否则同一品种的旧仓与本笔重复计入。

    这会让本品种第二次开仓（如加仓）被过早缩仓 —— 实测区分：
      · 正确（排除自己）：已有 0.005，本笔 0.005，合计 0.01 == 上限 -> 放行；
      · 错误（含自己）  ：已有 0.01（0.005+0.005），合计 0.015 > 上限 -> 缩仓。
    """
    cap = CFG.risk.portfolio_risk_cap
    pf = PortfolioRisk(("XAUUSDm",))
    st = PortfolioState(
        risk_by_symbol={"XAUUSDm": cap},       # 本品种旧仓
        direction_by_symbol={"XAUUSDm": "LONG"},
        equity=10000.0, pnl_now=0.0)
    v = pf.check_for("XAUUSDm", cap, st)       # 本笔也是 cap
    # 排除自己后 have=0，合计 = cap == 上限 -> 放行（不缩）
    assert v.ok is True
    assert v.lot_mult == 1.0, f"自己把自己算重了（mult={v.lot_mult}）"


# ══════════════════════════════════════════════════════════════════
# 契约 2c：同向集中
# ══════════════════════════════════════════════════════════════════
def test_same_direction_limit_rejects(multi):
    """⚠️ 同向品种数超限必须**拒绝**（不是缩仓）。

    "5 个品种都看多"在宏观上是一个仓位。缩仓只能减损，
    不能消除"方向判断错就全错"的结构性风险。
    """
    limit = CFG.risk.portfolio_max_same_direction
    assert limit == 3
    pf = PortfolioRisk(("XAUUSDm", "BTCUSDm", "USOILm", "EURUSDm"))
    st = PortfolioState(
        risk_by_symbol={},
        direction_by_symbol={"XAUUSDm": "LONG", "BTCUSDm": "LONG",
                             "USOILm": "LONG", "EURUSDm": None},
        equity=10000.0, pnl_now=0.0)
    v = pf.check_for("EURUSDm", 0.005, st)
    # 本笔若为 LONG，则同向已有 3 个 >= limit -> 拒绝
    st.direction_by_symbol["EURUSDm"] = "LONG"
    v = pf.check_for("EURUSDm", 0.005, st)
    assert v.ok is False
    assert v.reason and "portfolio_same_direction" in v.reason


def test_opposite_direction_not_limited(multi):
    """反向不受同向上限约束（对冲方向不该被拦）。"""
    pf = PortfolioRisk(("XAUUSDm", "BTCUSDm", "USOILm", "EURUSDm"))
    st = PortfolioState(
        risk_by_symbol={},
        direction_by_symbol={"XAUUSDm": "SHORT", "BTCUSDm": "SHORT",
                             "USOILm": "SHORT", "EURUSDm": "LONG"},
        equity=10000.0, pnl_now=0.0)
    v = pf.check_for("EURUSDm", 0.005, st)
    assert v.ok is True, "反向开仓被同向限制误拦"


def test_same_direction_limit_zero_disables_gate(multi, monkeypatch):
    """上限设为 0 = 关闭该闸（可配置性验证）。"""
    monkeypatch.setattr(CFG.risk, "portfolio_max_same_direction", 0)
    pf = PortfolioRisk(("XAUUSDm", "BTCUSDm", "USOILm", "EURUSDm"))
    st = PortfolioState(
        risk_by_symbol={},
        direction_by_symbol={"XAUUSDm": "LONG", "BTCUSDm": "LONG",
                             "USOILm": "LONG", "EURUSDm": "LONG"},
        equity=10000.0, pnl_now=0.0)
    assert pf.check_for("EURUSDm", 0.005, st).ok is True


# ══════════════════════════════════════════════════════════════════
# 契约 2d：保证金
# ══════════════════════════════════════════════════════════════════
def test_portfolio_margin_cap_rejects(multi):
    """组合保证金超上限必须拒绝（逐品种 margin_use_cap 抓不到合计）。"""
    mcap = CFG.risk.portfolio_margin_cap
    pf = PortfolioRisk(("XAUUSDm", "BTCUSDm"))
    equity = 10000.0
    st = PortfolioState(
        risk_by_symbol={},
        direction_by_symbol={},
        margin_by_symbol={"XAUUSDm": mcap * equity * 0.6,
                          "BTCUSDm": mcap * equity * 0.6},   # 合计 1.2×上限
        equity=equity, pnl_now=0.0)
    v = pf.check_for("USOILm", 0.005, st)
    assert v.ok is False
    assert v.reason == "portfolio_margin_cap"


# ══════════════════════════════════════════════════════════════════
# LLM 预算按品种平分
# ══════════════════════════════════════════════════════════════════
def test_budgets_split_across_symbols(multi):
    """多品种时 LLM 预算必须按品种数平分（每品种独立池）。"""
    b5 = CFG.per_symbol_budgets(5)
    assert b5["review"] == 60 // 5 == 12
    assert b5["news"] == 24 // 5 == 4
    assert b5["add_review"] == 24 // 5 == 4
    # 每个池子都必须 >= 1（否则该品种完全没有 LLM）
    for n in range(1, 11):
        b = CFG.per_symbol_budgets(n)
        assert all(v >= 1 for v in b.values()), f"n={n} 出现 0 预算池：{b}"


def test_budgets_never_zero_for_many_symbols(multi):
    """品种数很大时也不得出现 0 预算（0 会让该品种永远没有 LLM）。"""
    b = CFG.per_symbol_budgets(100)
    assert all(v >= 1 for v in b.values()), b


def test_client_accepts_custom_budgets(single):
    """`RunningHubClient` 必须接受外部传入的预算（多品种按品种分池用）。"""
    from gold_agent.llm.client import RunningHubClient

    c = RunningHubClient(budgets={"review": 7, "news": 3, "add_review": 2})
    assert c.budgets["review"].per_hour == 7
    assert c.budgets["news"].per_hour == 3
    assert c.budgets["add_review"].per_hour == 2


def test_client_defaults_match_config(single):
    """不传 budgets 时必须用配置值（单品种兼容）。"""
    from gold_agent.llm.client import RunningHubClient

    c = RunningHubClient()
    assert c.budgets["review"].per_hour == CFG.llm.per_hour_budget
    assert c.budgets["news"].per_hour == CFG.llm.news_per_hour_budget
    assert c.budgets["add_review"].per_hour == CFG.llm.add_review_per_hour_budget


# ══════════════════════════════════════════════════════════════════
# build_state 汇总
# ══════════════════════════════════════════════════════════════════
def test_build_state_counts_only_symbols_with_positions(multi):
    """只有**有持仓**的品种才计入已用风险。"""
    st = build_state(
        symbols=("XAUUSDm", "BTCUSDm", "USOILm"),
        positions_by_symbol={"XAUUSDm": "LONG", "BTCUSDm": None,
                             "USOILm": "SHORT"},
        equity=10000.0, pnl_now=0.0, risk_pct=0.005)
    assert set(st.risk_by_symbol) == {"XAUUSDm", "USOILm"}
    assert st.equity == 10000.0
    assert st.direction_by_symbol["BTCUSDm"] is None


def test_build_state_uses_conservative_full_risk(multi):
    """⚠️ 已用风险按**满额** risk_pct 计入（保守方向）。

    精确值需按各品种实际 SL 距离反推，组合层拿不到。
    满额计入会**高估**已用风险 → 更早缩仓，符合"只收紧"原则。
    """
    st = build_state(("XAUUSDm", "BTCUSDm"),
                     {"XAUUSDm": "LONG", "BTCUSDm": "SHORT"},
                     equity=10000.0, pnl_now=0.0, risk_pct=0.005)
    assert st.risk_by_symbol == {"XAUUSDm": 0.005, "BTCUSDm": 0.005}
    assert sum(st.risk_by_symbol.values()) == pytest.approx(0.01)
