# -*- coding: utf-8 -*-
"""交割单反馈闭环（用户要求：根据交割单历史的胜率/盈亏不断调整程序中参数权重）。

每轮运行时：
1. 读取自上次游标以来的平仓 deal（entry in (1,2)，magic 匹配）。
2. 对每笔交易：
   - 累计统计（胜率、平均盈亏、盈亏比）写入 data/trade_stats.json；
   - 更新 CircuitBreakers（day_pnl、连亏计数、peak_equity）；
   - 给各信号源记录 outcome：用当轮融合分符号 vs 该笔盈亏方向。
3. 游标持久化到 data/deals_cursor.json，防止重复计数。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import log_info
from gold_agent.fusion.bayes import BayesianPool
from gold_agent.risk.position import CircuitBreakers, wilson_lower


def _deal_direction(d: dict) -> int | None:
    """从交割单推断方向（1=LONG, -1=SHORT）。用于 P2-2 方向偏置监控。

    MT5 deal 的 `type` 字段：0=buy, 1=sell。平仓 deal 的 type 与持仓方向相反，
    因此优先用显式的 `direction`/`pos_type` 字段，退回用 `type` 反推。
    """
    for key in ("direction", "pos_type", "position_type"):
        v = d.get(key)
        if isinstance(v, str):
            u = v.upper()
            if u in ("LONG", "BUY", "0"):
                return 1
            if u in ("SHORT", "SELL", "1"):
                return -1
        elif isinstance(v, int):
            return 1 if v == 0 else -1
    t = d.get("type")
    if t is None:
        return None
    # 平仓 deal：type=1(sell) 意味着原本是 LONG，反之亦然
    if isinstance(t, int):
        return 1 if t == 1 else -1
    u = str(t).upper()
    if u in ("SELL", "1"):
        return 1
    if u in ("BUY", "0"):
        return -1
    return None


@dataclass
class TradeStats:
    total: int = 0
    wins: int = 0
    losses: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total if self.total else 0.0

    @property
    def profit_factor(self) -> float:
        return (self.gross_profit / abs(self.gross_loss)) if self.gross_loss else (
            float("inf") if self.gross_profit else 0.0)

    def to_dict(self) -> dict:
        return {"total": self.total, "wins": self.wins, "losses": self.losses,
                "gross_profit": round(self.gross_profit, 2),
                "gross_loss": round(self.gross_loss, 2),
                "win_rate": round(self.win_rate, 4),
                "profit_factor": round(self.profit_factor, 4) if self.profit_factor != float("inf") else None}


class DealFeedback:
    """交割单 → 统计/熔断/贝叶斯的闭环。"""

    def __init__(self, bayes: BayesianPool, breakers: CircuitBreakers,
                 state_dir: Path | None = None) -> None:
        self.bayes = bayes
        self.breakers = breakers
        d = state_dir or (CFG.project_root / "data")
        d.mkdir(parents=True, exist_ok=True)
        self.stats_path = d / "trade_stats.json"
        self.cursor_path = d / "deals_cursor.json"
        self.stats = TradeStats()
        self.history: list[dict] = []
        self.cursor = 0.0
        self.last_pred_by_position: dict[str, int | None] = {}
        self._load()

    # ---------- 持久化 ----------
    def _load(self) -> None:
        if self.stats_path.exists():
            try:
                data = json.loads(self.stats_path.read_text(encoding="utf-8"))
                self.stats = TradeStats(total=data.get("total", 0), wins=data.get("wins", 0),
                                        losses=data.get("losses", 0),
                                        gross_profit=data.get("gross_profit", 0.0),
                                        gross_loss=data.get("gross_loss", 0.0))
                self.history = data.get("history", [])
            except Exception:
                pass
        if self.cursor_path.exists():
            try:
                self.cursor = json.loads(self.cursor_path.read_text(encoding="utf-8")).get("cursor", 0.0)
            except Exception:
                pass

    def _save(self) -> None:
        self.stats_path.write_text(json.dumps(
            {**self.stats.to_dict(), "history": self.history[-200:]}, ensure_ascii=False),
            encoding="utf-8")
        self.cursor_path.write_text(json.dumps({"cursor": self.cursor}), encoding="utf-8")

    # ---------- 主流程 ----------
    async def poll(self, client, pred_orders: dict | None = None) -> list[dict]:
        """返回本轮新发现的平仓 deal 列表；内部完成全部更新与持久化。

        pred_orders: {order_id_str: predicted_sign} 挂单→成交桥接（graph 维护）。
        网格限价成交的仓位没有 open_market 记录，必须经 order_id 桥接找回预测符号。
        """
        try:
            deals = await client.get_deals(max(self.cursor, time.time() - 7 * 86400))
        except Exception as e:
            log_info(f"交割单反馈: 读取失败 {type(e).__name__}: {e}")
            return []
        new = [d for d in deals if d["time"] > self.cursor and d.get("magic") == CFG.mt5.magic]
        if not new:
            if deals:
                self.cursor = max(d["time"] for d in deals)
                self._save()
            return []
        for d in new:
            pnl = d["profit"] + d["swap"] + d["commission"] + d.get("fee", 0.0)
            self.stats.total += 1
            if pnl >= 0:
                self.stats.wins += 1
                self.stats.gross_profit += pnl
            else:
                self.stats.losses += 1
                self.stats.gross_loss += pnl
            rec = {**d, "pnl": round(pnl, 2), "ts": time.time()}
            self.history.append(rec)
            # 熔断器更新（P2-2：同时记录方向，供方向偏置监控）
            eq = getattr(self.breakers, "peak_equity", 0.0) or 0.0
            direction = _deal_direction(d)
            self.breakers.on_trade_closed(pnl, max(eq, 10000.0), direction=direction)
            rec["direction"] = direction
            # 预测符号：优先 order 桥接（网格单），其次 position 桥（市价单，由 graph 注入 rec["pred"]）
            pred = d.get("pred")
            if pred is None and pred_orders:
                pred = pred_orders.pop(str(d.get("order")), None)
            rec["pred_sign"] = pred
            self.last_pred_by_position[str(d.get("position_id"))] = pred
        self.cursor = max(d["time"] for d in new)
        self._save()
        log_info(f"交割单反馈: 新增 {len(new)} 笔已平仓交易，统计={self.stats.to_dict()}")
        return new

    # ---------- 胜率反馈给仓位 ----------
    def current_win_rate(self, fallback: float = 0.5) -> float:
        """供 risk gate 使用（P2-3）。

        样本 < `risk.min_deals_for_kelly`（默认 10）→ fallback 冷启动；
        样本足够 → **Wilson 置信下界**而非点估计。3 笔 1 胜的点估计是 0.333，
        Wilson 下界只有 0.061，仓位会自动缩到最小。
        """
        if self.stats.total >= CFG.risk.min_deals_for_kelly:
            return wilson_lower(self.stats.wins, self.stats.total)
        return fallback

    def win_rate_point(self) -> float:
        """点估计（仅用于展示/日志，不用于仓位）。"""
        return self.stats.win_rate

    def win_rate_wilson(self) -> float:
        """Wilson 下界（样本不足时仍给出数值，供审计）。"""
        return wilson_lower(self.stats.wins, self.stats.total)
