"""MT5 适配层真实测试（无 mock）：连接、全周期行情、持仓、账户。"""
from __future__ import annotations

import asyncio

import pytest

from gold_agent.common.config import CFG
from gold_agent.mt5.client import MT5Client, Mt5Error


@pytest.mark.asyncio
async def test_doctor_real():
    c = MT5Client()
    try:
        report = await c.doctor()
        assert report["ok"], report
        assert report["checks"]["account"]["currency"] == "USD"
        assert report["checks"]["symbol"]["name"] == CFG.mt5.symbol
    finally:
        c.shutdown()


@pytest.mark.asyncio
async def test_all_timeframes_real():
    c = MT5Client()
    try:
        bundle = await c.get_ohlcv()
        assert set(bundle.quality.values()) == {"ok"}
        assert set(bundle.frames.keys()) == set(CFG.mt5.timeframes)
        for tf, df in bundle.frames.items():
            assert len(df) == CFG.mt5.bars_per_tf, f"{tf} rows {len(df)}"
            assert df["time"].is_monotonic_increasing
            assert not df[["open", "high", "low", "close"]].isna().any().any()
            assert ((df["close"] <= df["high"]) & (df["close"] >= df["low"])).all()
        assert bundle.tick is not None
        assert bundle.tick.bid > 0 and bundle.tick.ask >= bundle.tick.bid
    finally:
        c.shutdown()


@pytest.mark.asyncio
async def test_positions_and_account_real():
    c = MT5Client()
    try:
        view = await c.get_positions()
        acc = await c.get_account()
        assert acc.equity > 0
        # 全部持仓属于本系统 magic 或手动单均可，但字段必须完整
        for p in view.positions:
            assert p.ticket > 0 and p.type in ("LONG", "SHORT") and p.volume > 0
    finally:
        c.shutdown()
