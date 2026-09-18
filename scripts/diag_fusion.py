# -*- coding: utf-8 -*-
"""诊断：实时拉一轮数据，打印各信号源分数/sigma/贝叶斯权重与最终融合结果。只读，不下单。"""
from __future__ import annotations

import asyncio
import json
import sys
sys.path.insert(0, r"D:\RoundTrip\src")

from gold_agent.mt5.client import MT5Client
from gold_agent.skills.chanlun_adapter import analyze_tf
from gold_agent.skills.mobius_adapter import MobiusClient
from gold_agent.fusion.engine import FusionEngine

TFS = ["1m", "2m", "5m", "10m", "15m", "30m", "1h", "4h", "8h", "1d"]


async def main() -> None:
    client = MT5Client()
    await client.initialize()
    bundle = await client.get_ohlcv(300)

    cl = {}
    for tf in ("15m", "1h", "4h"):
        df = bundle.frames.get(tf)
        if df is not None and len(df):
            cl[tf] = await asyncio.to_thread(analyze_tf, df, tf)

    mc = MobiusClient()
    mob = await mc.get_smc("XAUUSD", "15m", limit=200)

    fe = FusionEngine()
    ev = fe.fuse_all(bundle.frames, cl, mob)

    last = float(bundle.frames["15m"]["close"].iloc[-1])
    print(json.dumps({
        "last_close_15m": round(last, 3),
        "score": round(ev.result.score, 4),
        "sigma": round(ev.result.sigma, 4),
        "regime": ev.result.regime,
        "hurst": round(ev.result.hurst, 3) if ev.result.hurst else None,
        "disagreement": ev.result.disagreement,
        "chanlun_scores": {tf: r.score for tf, r in cl.items()},
        "per_source": ev.result.per_source,
    }, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
