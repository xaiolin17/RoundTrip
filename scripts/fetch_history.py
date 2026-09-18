"""从 MT5 拉取长历史数据到 data/cache（真实数据，供回放校准）。

策略：1m 只有最近数日；用 15m/1h/4h 拉长历史，回放校准用 15m 决策点。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_agent.common.config import CFG
from gold_agent.mt5.client import MT5Client


async def main() -> None:
    CFG.ensure_dirs()
    client = MT5Client()
    await client.initialize()
    sym = CFG.mt5.symbol
    # 15m × 4960 根 ≈ 2 年（broker 上限内）；1h × 4000；4h × 2000；1d × 1500
    plans = {"15m": 4960, "1h": 4000, "4h": 2000, "1d": 1500}
    for tf, n in plans.items():
        from gold_agent.mt5.client import TF_MAP
        loop = asyncio.get_running_loop()
        df = await loop.run_in_executor(client._io_pool, client._copy_rates_sync, sym, TF_MAP[tf], n)
        if df is None or df.empty:
            print(f"{tf}: EMPTY")
            continue
        out = CFG.data_dir / f"{sym}_{tf}.parquet"
        df.to_parquet(out, index=False)
        print(f"{tf}: {len(df)} rows -> {out} ({df['time'].iloc[0]} .. {df['time'].iloc[-1]})")
    client.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
