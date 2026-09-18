"""网格/马丁组状态管理（docs/05 §3-4）。"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import log_warn


@dataclass
class GridLayer:
    level: float
    lots: float
    sl: float
    tp: float
    ticket: int | None = None
    filled: bool = False


@dataclass
class GridGroup:
    direction: str                    # LONG | SHORT
    base_lots: float
    atr_at_creation: float
    layers: list[GridLayer] = field(default_factory=list)
    created_at: float = 0.0
    kind: str = "grid"                # grid | martin_reverse
    closed: bool = False


@dataclass
class GridState:
    active_group: GridGroup | None = None
    reverse_group: GridGroup | None = None
    last_reversal_day: str = ""

    @property
    def total_lots(self) -> float:
        v = 0.0
        for g in (self.active_group, self.reverse_group):
            if g and not g.closed:
                v += sum(l.lots for l in g.layers if l.filled)
        return v

    def can_open_grid(self, direction: str) -> bool:
        if self.active_group is None or self.active_group.closed:
            return True
        return False

    def can_open_reverse(self) -> bool:
        if self.reverse_group is None or self.reverse_group.closed:
            return not self.martin_capped_today()
        return False

    def martin_capped_today(self) -> bool:
        return self.last_reversal_day == time.strftime("%Y-%m-%d") and False

    # ---------- 持久化 ----------
    def to_dict(self) -> dict:
        def g2d(g):
            if g is None:
                return None
            return {"direction": g.direction, "base_lots": g.base_lots,
                    "atr": g.atr_at_creation, "kind": g.kind, "closed": g.closed,
                    "layers": [l.__dict__ for l in g.layers]}
        return {"active_group": g2d(self.active_group),
                "reverse_group": g2d(self.reverse_group),
                "last_reversal_day": self.last_reversal_day}

    @classmethod
    def from_dict(cls, d: dict) -> "GridState":
        st = cls()
        def d2g(x):
            if not x:
                return None
            g = GridGroup(direction=x["direction"], base_lots=x["base_lots"],
                          atr_at_creation=x.get("atr", 1.0), kind=x.get("kind", "grid"),
                          closed=x.get("closed", False))
            g.layers = [GridLayer(**l) for l in x.get("layers", [])]
            return g
        st.active_group = d2d = d2g(d.get("active_group"))
        st.reverse_group = d2g(d.get("reverse_group"))
        st.last_reversal_day = d.get("last_reversal_day", "")
        return st

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "GridState":
        if path.exists():
            try:
                return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except Exception as e:
                log_warn(f"grid state load failed: {e}")
        return cls()
