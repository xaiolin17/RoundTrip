"""skills 适配层真实测试（无 mock）：chanlun 引擎 + Mobius SMC。"""
from __future__ import annotations

import asyncio

import pytest

from gold_agent.skills.chanlun_adapter import analyze_tf
from gold_agent.skills.mobius_adapter import MobiusClient


@pytest.mark.asyncio
async def test_chanlun_real_bundle(bundle_factory):
    frames = await bundle_factory()
    for tf in ("5m", "15m", "1h"):
        r = analyze_tf(frames[tf], tf)
        assert r.status == "ok", f"{tf}: {r.error}"
        assert r.quality.get("status") == "pass"
        assert r.definition_mode == "research_proxy"
        assert -3.0 <= r.score <= 3.0


@pytest.mark.asyncio
async def test_mobius_real_and_ratelimit():
    mob = MobiusClient()
    try:
        r1 = await mob.get_smc("XAUUSD", "15m", limit=100)
        assert r1.status in ("ok", "stale"), r1.error
        if r1.status == "ok":
            assert r1.current_price and r1.current_price > 100
            assert isinstance(r1.structures, list)
        # 缓存命中
        r2 = await mob.get_smc("XAUUSD", "15m", limit=100)
        assert r2.status in ("ok", "stale")
        # 不支持的周期 fail-closed
        r3 = await mob.get_smc("XAUUSD", "2m", limit=10)
        assert r3.status == "unavailable"
        assert "unsupported" in r3.error
    finally:
        await mob.close()


@pytest.fixture
def bundle_factory():
    """从真实 MT5 拉一次行情供本测试组复用（返回异步获取函数）。"""
    from gold_agent.mt5.client import MT5Client

    holder = {}

    async def _get():
        if "bundle" not in holder:
            c = MT5Client()
            await c.initialize()
            holder["bundle"] = await c.get_ohlcv()
            holder["client"] = c
        return holder["bundle"].frames

    yield _get

    c = holder.get("client")
    if c:
        c.shutdown()
