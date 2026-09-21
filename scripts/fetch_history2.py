"""从 MT5 拉取 1m/5m/30m 历史（真实数据，供回放校准）。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_agent.common.config import CFG
from gold_agent.mt5.client import MT5Client, TF_MAP


async def main() -> None:
    CFG.ensure_dirs()
    client = MT5Client()
    await client.initialize()
    sym = CFG.mt5.symbol
    plans = {"1m": 60000, "5m": 30000, "30m": 20000, "2m": 20000, "10m": 20000, "8h": 4000}
    for tf, n in plans.items():
        loop = asyncio.get_running_loop()
        try:
            df = await loop.run_in_executor(client._io_pool, client._copy_rates_sync,
                                            sym, TF_MAP[tf], n)
        except Exception as e:
            print(f"{tf}: ERR {type(e).__name__}: {e}", flush=True)
            continue
        if df is None or df.empty:
            print(f"{tf}: EMPTY", flush=True)
            continue
        out = CFG.data_dir / f"{sym}_{tf}.parquet"
        df.to_parquet(out, index=False)
        print(f"{tf}: {len(df)} rows -> {out.name} "
              f"({df['time'].iloc[0]} .. {df['time'].iloc[-1]})", flush=True)
    client.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
