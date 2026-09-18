# -*- coding: utf-8 -*-
"""手动 live 测试开仓：直接按当前融合分方向开 0.01 手真实单（用户指令：直接真实开仓测试）。

流程：
1. 跑一轮完整分析（数据→skills→融合），取当前 S 符号作为方向。
2. 走完整风控门（熔断/仓位/TP/SL）——不是绕过风控。
3. 市价单真实开仓，最小手数。
4. 打印成交结果与后续交割单反馈预期。

用法: py scripts\manual_open.py
"""
from __future__ import annotations

import asyncio
import json
import sys
sys.path.insert(0, r"D:\RoundTrip\src")

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import log_info, trade_log
from gold_agent.mt5.client import MT5Client
from gold_agent.mt5.executor import Executor, OrderPlan
from gold_agent.skills.chanlun_adapter import analyze_tf
from gold_agent.skills.mobius_adapter import MobiusClient
from gold_agent.fusion.engine import FusionEngine
from gold_agent.risk.position import CircuitBreakers, position_lots, volatility_k


async def main() -> None:
    CFG.ensure_dirs()
    client = MT5Client()
    await client.initialize()

    # --- 账户与持仓检查 ---
    acc = await client.get_account()
    poss = await client.get_positions()
    held = [p for p in poss.positions if p.magic == CFG.mt5.magic]
    print(json.dumps({"account": {"balance": acc.balance, "equity": acc.equity},
                      "existing_positions": len(held)}, ensure_ascii=False))
    if held:
        print("已有本策略持仓，跳过开仓（单仓位策略）。")
        return

    # --- 分析（与主循环相同管线）---
    bundle = await client.get_ohlcv()
    cl = {tf: await asyncio.to_thread(analyze_tf, bundle.frames[tf], tf)
          for tf in ("5m", "15m", "1h")}
    mob = await MobiusClient().get_smc("XAUUSD", "15m", limit=200)
    fe = FusionEngine()
    ev = fe.fuse_all(bundle.frames, cl, mob)
    s, sigma = ev.result.score, ev.result.sigma
    direction = "LONG" if s > 0 else "SHORT"
    atr = ev.indicators.atr if ev.indicators else None
    print(json.dumps({"score": round(s, 3), "sigma": round(sigma, 3),
                      "direction": direction, "atr": round(atr, 3) if atr else None},
                     ensure_ascii=False))

    if atr is None or atr <= 0:
        print("无 ATR，放弃。")
        return

    # --- 风控：完整仓位计算（0.01 手最小）---
    breakers = CircuitBreakers.load(CFG.state_path.parent / "breakers.json")
    reject = breakers.check(acc.equity, acc.margin / max(acc.equity, 1e-9),
                            high_risk_window=False)
    if reject:
        print(f"风控熔断拦截: {reject}")
        return
    vol_k = volatility_k(ev.indicators.realized_vol_daily if ev.indicators else None, None)
    if ev.result.disagreement:
        vol_k *= 0.5
    lots, rej = position_lots(acc.equity, atr, 1.0, 0.5, vol_k=vol_k)
    lots = max(0.01, lots) if not rej else 0.01   # 手动测试强制最小手数
    lots = round(lots, 2)

    si = client.symbol_info()
    entry = si.ask if direction == "LONG" else si.bid
    sl_dist = CFG.risk.sl_atr_mult * atr
    tp_dist = CFG.risk.tp_atr_mult * atr
    tp = entry + tp_dist if direction == "LONG" else entry - tp_dist
    sl = entry - sl_dist if direction == "LONG" else entry + sl_dist

    plan = OrderPlan(kind="open_market", direction=direction, lots=lots,
                     tp=round(tp, 3), sl=round(sl, 3),
                     comment="goldagent-manual-test",
                     idempotency_key=f"manual-{int(asyncio.get_event_loop().time())}")
    print(json.dumps({"plan": {"direction": direction, "lots": lots,
                               "entry": round(entry, 3), "tp": round(tp, 3),
                               "sl": round(sl, 3)}}, ensure_ascii=False))

    ex = Executor(client)
    res = await ex.execute(plan)
    print(json.dumps({"execution": {"ok": res.ok, "retcode": res.retcode,
                                    "deal": res.deal, "order": res.order,
                                    "price": res.price, "volume": res.volume,
                                    "error": res.error}}, ensure_ascii=False))

    if res.ok:
        # 成交对账
        await asyncio.sleep(2)
        view = await client.get_positions()
        mine = [p for p in view.positions if p.magic == CFG.mt5.magic]
        print(json.dumps({"verify": {"positions": len(mine),
                                     "tickets": [p.ticket for p in mine],
                                     "profits": [round(p.profit, 2) for p in mine]}},
                         ensure_ascii=False))
        trade_log({"event": "manual_open_verified", "plan": plan.__dict__})


if __name__ == "__main__":
    asyncio.run(main())
