"""从 MT5 拉取 1m/5m/30m 历史（真实数据，供回放校准）。

用法:
    py scripts/fetch_history2.py                          # 默认品种，全部周期
    py scripts/fetch_history2.py --symbols BTCUSDm,USOILm --tfs 1m
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_agent.common.config import CFG
from gold_agent.mt5.client import MT5Client, TF_MAP

#: 周期 → 请求 bar 数。1m 取满 broker 上限（60000），供 IR 校准用。
PLANS = {"1m": 60000, "5m": 30000, "30m": 20000, "2m": 20000, "10m": 20000, "8h": 4000}


async def main() -> None:
    ap = argparse.ArgumentParser(description="从 MT5 拉历史 bar 到 data/cache/")
    ap.add_argument("--symbols", default="",
                    help="逗号分隔的品种（如 BTCUSDm,USOILm）；不设则用 MT5_SYMBOL")
    ap.add_argument("--tfs", default="",
                    help="逗号分隔的周期；不设则取全部 1m,5m,30m,2m,10m,8h")
    args = ap.parse_args()

    syms = [s.strip() for s in args.symbols.split(",") if s.strip()] or [CFG.mt5.symbol]
    wanted = [t.strip() for t in args.tfs.split(",") if t.strip()] or list(PLANS)
    unknown = [t for t in wanted if t not in PLANS]
    if unknown:
        raise SystemExit(f"未知周期: {unknown}（可选: {list(PLANS)}）")
    plans = {t: PLANS[t] for t in wanted}

    CFG.ensure_dirs()
    client = MT5Client()
    await client.initialize()
    for sym in syms:
        for tf, n in plans.items():
            loop = asyncio.get_running_loop()
            try:
                df = await loop.run_in_executor(client._io_pool, client._copy_rates_sync,
                                                sym, TF_MAP[tf], n)
            except Exception as e:
                print(f"{sym} {tf}: ERR {type(e).__name__}: {e}", flush=True)
                continue
            if df is None or df.empty:
                print(f"{sym} {tf}: EMPTY", flush=True)
                continue
            out = CFG.data_dir / f"{sym}_{tf}.parquet"
            df.to_parquet(out, index=False)
            print(f"{sym} {tf}: {len(df)} rows -> {out.name} "
                  f"({df['time'].iloc[0]} .. {df['time'].iloc[-1]})", flush=True)
    client.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
