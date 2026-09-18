"""主循环入口：py -m gold_agent.runner

live 模式直接真实下单（用户确认）；dry_run 只做决策演练。
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import log_error, log_info, log_warn
from gold_agent.agent.graph import Graph


async def main_async(dry: bool, rounds: int | None) -> None:
    CFG.ensure_dirs()
    if dry:
        CFG.trade_mode = "dry_run"
    graph = Graph.build()
    # 启动自检
    report = await graph.client.doctor()
    if not report.get("ok"):
        print(json.dumps({"fatal": "doctor failed", "report": report}, ensure_ascii=False))
        sys.exit(1)
    log_info(f"doctor ok: {report['checks']['account']}")
    if CFG.trade_mode == "live" and not getattr(graph.client, "_connected", False):
        # doctor 内部线程初始化成功但 _connected 标志未同步；显式补一次
        await graph.client.initialize()

    # 轮号跨进程持久（用户要求：重启不从 1 开始，便于日志对照）
    round_state_path = CFG.state_path.parent / "runner_state.json"
    try:
        n = int(json.loads(round_state_path.read_text(encoding="utf-8")).get("round", 0))
    except Exception:
        n = 0
    try:
        while rounds is None or n < rounds:
            n += 1
            round_state_path.parent.mkdir(parents=True, exist_ok=True)
            round_state_path.write_text(json.dumps({"round": n}), encoding="utf-8")
            summary = await graph.run_round(n)
            # 一行式控制台摘要（信号分 / 动作 / 风控 / 执行），PyCharm 运行窗直接可见
            score = summary.get("score")
            sigma = summary.get("sigma")
            if score is not None:
                line = f"[R{n:>3}] S={score:+.2f} σ={sigma:.2f} → {summary.get('action', '?')}"
                risk = summary.get("risk") or {}
                if not risk.get("ok", True):
                    line += f"  ⛔ {risk.get('reason')}"
                ex = summary.get("execution")
                if ex:
                    line += "  ✓" if ex.get("ok") else f"  ✗ {ex.get('error')}"
                print(line, flush=True)
            else:
                print(json.dumps(summary, ensure_ascii=False, default=str), flush=True)
            interval = CFG.decision.loop_interval_s
            await asyncio.sleep(interval)
    except KeyboardInterrupt:
        log_info("interrupted by user")
    finally:
        with contextlib.suppress(Exception):
            await graph.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="GoldAgent runner")
    ap.add_argument("--dry", action="store_true", help="dry_run mode: 不真实下单")
    ap.add_argument("--rounds", type=int, default=None, help="运行 N 轮后退出（默认无限）")
    args = ap.parse_args()
    asyncio.run(main_async(dry=args.dry, rounds=args.rounds))


if __name__ == "__main__":
    main()
