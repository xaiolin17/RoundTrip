# -*- coding: utf-8 -*-
"""熔断死锁 + 移动止损锁盈 + 融合分与压力位矛盾 三项回归测试。"""
from __future__ import annotations

import time

import pytest

from gold_agent.common.config import CFG
from gold_agent.risk.levels import trade_levels
from gold_agent.risk.position import CircuitBreakers


# ========== 一、熔断死锁修复 ==========
def test_breaker_recovers_after_cooloff_expires():
    """核心回归：4 连亏触发冷却后，冷却到期必须**自动恢复**。

    事故：原实现冷却到期只放行 cooloff 检查，但 consecutive_losses 仍 >=4
    落到下一道检查 -> 永久拦截；而计数器只有平仓才改 -> 开仓被拦 -> 无平仓
    -> 永不归零 -> **永久死锁**（实测 3958 轮后 400+ 轮全被拦）。
    """
    b = CircuitBreakers()
    for _ in range(4):
        b.on_trade_closed(-10, 10000)
    assert b.consecutive_losses == 4
    assert b.check(10000, 0.0, False) is not None, "4 连亏应触发熔断"
    # 冷却到期
    b.cooloff_until = time.time() - 1
    assert b.check(10000, 0.0, False) is None, "冷却到期必须自动恢复"
    assert b.consecutive_losses == 0, "连亏计数必须归零"
    assert b.cooloff_until == 0.0


def test_breaker_still_blocks_within_cooloff():
    b = CircuitBreakers()
    for _ in range(4):
        b.on_trade_closed(-10, 10000)
    b.cooloff_until = time.time() + 3600
    r = b.check(10000, 0.0, False)
    assert r and "cooloff" in r


def test_breaker_resets_on_win():
    b = CircuitBreakers()
    for _ in range(3):
        b.on_trade_closed(-10, 10000)
    b.on_trade_closed(20, 10000)
    assert b.consecutive_losses == 0
    assert b.check(10000, 0.0, False) is None


# ========== 二、融合分与压力位矛盾 ==========
def _ev(center: dict):
    return type("E", (), {"chanlun": {"15m": type("C", (), {"center": center})()},
                          "mobius": None})()


def test_long_conflict_when_resistance_too_close():
    """做多但紧贴上方压力位（< 1×ATR）-> 结构不支持追多 -> 拒。"""
    ev = _ev({"zg": 4340.0, "zd": 4324.0, "gg": 4360.0, "dd": 4320.0})
    lv = trade_levels("LONG", 4338.0, {}, ev, atr=12.0)
    assert not lv.ok and lv.reason == "fusion_vs_levels_conflict"


def test_long_allowed_when_resistance_far():
    ev = _ev({"zg": 4340.0, "zd": 4300.0, "gg": 4360.0, "dd": 4296.0})
    lv = trade_levels("LONG", 4316.0, {}, ev, atr=12.0)
    assert lv.ok


def test_short_conflict_when_support_too_close():
    """做空但紧贴下方支撑位（< 1×ATR）-> 结构不支持追空 -> 拒。"""
    ev = _ev({"zg": 4348.0, "zd": 4330.0, "gg": 4360.0, "dd": 4328.0})
    lv = trade_levels("SHORT", 4332.0, {}, ev, atr=12.0)
    assert not lv.ok and lv.reason == "fusion_vs_levels_conflict"


def test_short_allowed_when_support_far():
    ev = _ev({"zg": 4350.0, "zd": 4300.0, "gg": 4360.0, "dd": 4296.0})
    lv = trade_levels("SHORT", 4330.0, {}, ev, atr=12.0)
    assert lv.ok


def test_conflict_check_ignored_without_atr():
    """无 ATR 数据时不做矛盾检测（无法判定距离），走原有校验路径。"""
    ev = _ev({"zg": 4340.0, "zd": 4324.0, "gg": 4360.0, "dd": 4320.0})
    lv = trade_levels("LONG", 4338.0, {}, ev, atr=None)
    assert lv.reason != "fusion_vs_levels_conflict", "无 ATR 不应触发矛盾检测"


# ========== 三、移动止损锁盈配置 ==========
def test_lock_profit_config_present():
    """用户选定：移动止损锁盈（替代回吐平仓）的配置必须存在。"""
    assert hasattr(CFG.decision, "lock_profit_min_usd")
    assert hasattr(CFG.decision, "lock_profit_gap_usd")
    assert CFG.decision.lock_profit_min_usd > 0
    assert CFG.decision.lock_profit_gap_usd > 0
