"""贝叶斯模型平均（docs/04 §2）：按滚动命中率更新每源权重。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import math
import time

import numpy as np

from gold_agent.common.config import CFG


@dataclass
class SourceStats:
    hits: int = 0
    misses: int = 0
    # Dirichlet 先验 α=β=1

    @property
    def n(self) -> int:
        return self.hits + self.misses

    def p(self) -> float:
        return (self.hits + 1.0) / (self.n + 2.0)   # Beta(1,1) 后验均值


class BayesianPool:
    """维护每信号源滚动命中统计并给出 log_odds 权重。"""

    def __init__(self, window: int | None = None, state_path: Path | None = None) -> None:
        self.window = window or CFG.fusion.bayes_window
        self.state_path = state_path or (CFG.project_root / "data" / "bayes_state.json")
        self._stats: dict[str, SourceStats] = {}
        self._recent: dict[str, list[int]] = {}
        self._load()

    # ---------- 持久化 ----------
    def _load(self) -> None:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                for k, v in data.get("stats", {}).items():
                    self._stats[k] = SourceStats(hits=v.get("hits", 0), misses=v.get("misses", 0))
                for k, v in data.get("recent", {}).items():
                    self._recent[k] = v[-self.window:]
            except Exception:
                pass

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "saved_at": time.time(),
            "stats": {k: {"hits": s.hits, "misses": s.misses} for k, s in self._stats.items()},
            "recent": {k: v[-self.window:] for k, v in self._recent.items()},
        }
        self.state_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # ---------- 更新 ----------
    def record_outcome(self, source: str, predicted_sign: int, actual_sign: int) -> None:
        """predicted_sign/actual_sign ∈ {-1,0,1}；0 视为不计入。"""
        if predicted_sign == 0 or actual_sign == 0:
            return
        st = self._stats.setdefault(source, SourceStats())
        rec = self._recent.setdefault(source, [])
        hit = 1 if predicted_sign == actual_sign else 0
        rec.append(hit)
        if len(rec) > self.window:
            # 滚动窗口内重算（去掉最旧）
            removed = rec.pop(0)
            # 简化：总量重算成本可接受；保证窗口语义
            st.hits = st.misses = 0
            for h in rec:
                if h:
                    st.hits += 1
                else:
                    st.misses += 1
        else:
            if hit:
                st.hits += 1
            else:
                st.misses += 1

    # ---------- 权重 ----------
    def weight(self, source: str) -> float:
        st = self._stats.get(source)
        if st is None or st.n < 20:
            return 1.0    # 冷启动等权
        p = st.p()
        # logit 缩放：p 越偏离 0.5 权重越高，clamp [0.1, 3]
        logit = math.log(p / (1 - p))
        return float(np.clip(0.5 + abs(logit), 0.1, 3.0))

    def hit_rate(self, source: str) -> float:
        st = self._stats.get(source)
        return st.p() if st and st.n else 0.5

    def sample_count(self, source: str) -> int:
        st = self._stats.get(source)
        return st.n if st else 0

    def evidence(self, source: str, score: float, strength: float) -> float:
        """对数域证据：w · log(p/(1-p)) · sign · strength。

        ⚠️ 负向钳制（用户选定）：表现差的源（p<0.5）会给负证据，
        实测 9胜20负（p=0.32）时 logit=-0.74，分数为正时每个源压
        -0.94，4 源叠加把融合分拉低 0.3~0.5，配合信号源走弱导致
        508 轮无一达到开仓阈值。现在负证据最多压到
        -`bayes_evidence_floor`，避免"越亏越反向投票"的自我强化；
        正证据不钳制（表现好的源应充分投票）。
        """
        st = self._stats.get(source)
        if st is None or st.n < 20 or score == 0:
            return 0.0
        p = st.p()
        logit = math.log(p / (1 - p))
        sign = 1.0 if score > 0 else -1.0
        raw = self.weight(source) * logit * sign * min(abs(strength), 1.0)
        # 负证据钳制：最多反向压 evidence_floor（正证据不限）
        if raw < 0:
            return float(max(raw, -CFG.fusion.bayes_evidence_floor))
        return float(raw)
