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
    """做多但紧贴**LLM 压力位**（< 0.3×ATR）-> 结构不支持追多 -> 拒。

    ⚠️ 2026-09-23 修正：冲突检测只对 LLM 给的位判定。原实现对
    本地结构位（缠论/SMC）也判，但 196 个未聚合位太密，1m SMC 位
    常距价格 0.3 点——实测 10 轮被拦 8 轮拦错（价格穿过"支撑"
    继续下跌，做空本可获利 0.8~4.1 点）。
    """
    rev = {"support_levels": [4324.0], "resistance_levels": [4338.5]}
    lv = trade_levels("LONG", 4338.0, rev, None, atr=12.0)
    assert not lv.ok and lv.reason == "fusion_vs_levels_conflict"


def test_long_allowed_when_resistance_far():
    """做多但 LLM 压力位离得远（> 0.3×ATR）-> 放行。"""
    rev = {"support_levels": [4300.0], "resistance_levels": [4340.0]}
    lv = trade_levels("LONG", 4316.0, rev, None, atr=12.0)
    assert lv.ok


def test_short_conflict_when_support_too_close():
    """做空但紧贴**LLM 支撑位**（< 0.3×ATR）-> 结构不支持追空 -> 拒。"""
    rev = {"support_levels": [4330.5], "resistance_levels": [4348.0]}
    lv = trade_levels("SHORT", 4332.0, rev, None, atr=12.0)
    assert not lv.ok and lv.reason == "fusion_vs_levels_conflict"


def test_short_allowed_when_support_far():
    """做空但 LLM 支撑位离得远（> 0.3×ATR）-> 放行。"""
    rev = {"support_levels": [4300.0], "resistance_levels": [4350.0]}
    lv = trade_levels("SHORT", 4330.0, rev, None, atr=12.0)
    assert lv.ok


def test_conflict_ignores_local_structure_noise():
    """回归：本地结构位（缠论/SMC 噪音）不再触发冲突检测。

    实测事故：4364-4376 轮做空，入场 4335-4339，本地 1m SMC 位
    4335.20/4338.77（距入场 0.13~3.0 点）被当成"紧贴支撑"拦截，
    但价格直接穿过继续下跌 0.8~4.1 点——8/10 拦错。
    现在只对 LLM 给的位判定，这些轮次应放行。
    """
    ev = _ev({"zg": 4348.0, "zd": 4335.0, "gg": 4360.0, "dd": 4330.0})
    rev = {"support_levels": [4328.82, 4322.83, 4310.16],
           "resistance_levels": [4348.48, 4357.06]}
    lv = trade_levels("SHORT", 4336.0, rev, ev, atr=14.8)
    assert lv.ok, "本地结构位 4335 不应触发冲突，LLM 位 4328.82 距入场够远"


def test_conflict_check_ignored_without_atr():
    """无 ATR 数据时不做矛盾检测（无法判定距离），走原有校验路径。"""
    rev = {"support_levels": [4324.0], "resistance_levels": [4338.5]}
    lv = trade_levels("LONG", 4338.0, rev, None, atr=None)
    assert lv.reason != "fusion_vs_levels_conflict", "无 ATR 不应触发矛盾检测"


# ========== 三、移动止损锁盈配置 ==========
def test_lock_profit_config_present():
    """用户选定：移动止损锁盈（替代回吐平仓）的配置必须存在。"""
    assert hasattr(CFG.decision, "lock_profit_min_usd")
    assert hasattr(CFG.decision, "lock_profit_gap_usd")
    assert CFG.decision.lock_profit_min_usd > 0
    assert CFG.decision.lock_profit_gap_usd > 0
