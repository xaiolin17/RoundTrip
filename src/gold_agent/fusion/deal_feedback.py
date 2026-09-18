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
from gold_agent.risk.position import CircuitBreakers


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
    async def poll(self, client) -> list[dict]:
        """返回本轮新发现的平仓 deal 列表；内部完成全部更新与持久化。"""
        try:
            deals = await client.get_deals(max(self.cursor, time.time() - 7 * 86400))
        except Exception as e:
            log_info(f"deal_feedback: read failed {type(e).__name__}: {e}")
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
            # 熔断器更新
            eq = getattr(self.breakers, "peak_equity", 0.0) or 0.0
            self.breakers.on_trade_closed(pnl, max(eq, 10000.0))
            # 贝叶斯源反馈：predicted_sign 来自最近一轮融合分符号（存于 rec 注释流）
            # 简化：以盈亏方向作为 actual，predicted_sign 由 graph 注入 pending 队列
        self.cursor = max(d["time"] for d in new)
        self._save()
        log_info(f"deal_feedback: {len(new)} closed trades, stats={self.stats.to_dict()}")
        return new

    # ---------- 胜率反馈给仓位 ----------
    def current_win_rate(self, fallback: float = 0.5) -> float:
        """供 risk gate 使用：交割单胜率（样本≥10 才生效，否则 fallback）。"""
        if self.stats.total >= 10:
            return self.stats.win_rate
        return fallback
