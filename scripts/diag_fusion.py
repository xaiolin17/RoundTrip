import asyncio, sys, json
sys.path.insert(0, r"D:\RoundTrip\src")
from gold_agent.mt5.client import MT5Client
from gold_agent.skills.chanlun_adapter import analyze_tf
from gold_agent.skills.mobius_adapter import MobiusClient
from gold_agent.fusion.engine import FusionEngine

async def main():
    c = MT5Client(); await c.initialize()
    b = await c.get_ohlcv(300)
    cl = {}
    for tf in ("1m","5m","15m","1h","4h"):
        df = b.frames.get(tf)
        if df is not None and len(df):
            cl[tf] = await asyncio.to_thread(analyze_tf, df, tf)
    mc = MobiusClient()
    mobs = {}
    for tf in ("1m","5m","15m","1h"):
        mobs[tf] = await mc.get_smc("XAUUSD", tf, limit=200)
    fe = FusionEngine()
    ev = fe.fuse_all(b.frames, cl, mobs)
    print(json.dumps({
        "score": round(ev.result.score,3), "sigma": round(ev.result.sigma,3),
        "regime": ev.result.regime, "disagreement": ev.result.disagreement,
        "chanlun_tf": {tf: r.score for tf, r in cl.items()},
        "mobius_tf": {tf: (r.status if r is not None else None) for tf, r in mobs.items()},
        "per_source": ev.result.per_source,
    }, ensure_ascii=False, indent=1, default=str))
asyncio.run(main())
