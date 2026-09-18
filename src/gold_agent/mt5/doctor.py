"""MT5 doctor 入口：py -m gold_agent.mt5.doctor"""
from __future__ import annotations

import asyncio
import json

from gold_agent.common.config import CFG
from gold_agent.mt5.client import MT5Client


async def main() -> None:
    CFG.ensure_dirs()
    client = MT5Client()
    try:
        report = await client.doctor()
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    finally:
        client.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
