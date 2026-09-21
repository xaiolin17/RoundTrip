"""信号源归一化与滚动基线（research/18_COMMERCIAL_PLAN.md P0-1 / P1-2 / P1-3）。

为什么需要这一层
----------------
`mobius_adapter._score_fn` 对 SMC 结构做**有符号累加但不减基准**。黄金长期上行
→ bull 结构持续累积、bear 结构很快被覆盖 → 实测 88% 为正、均值 +1.2604。
这个 +1.26 **不是预测，是偏置**（research/16_live_audit.txt）。

同类问题在 `classic_indicators`（63.3% 为正）与 `chanlun`（52.4%）上同样存在，
只是幅度小。任何"有符号累加"的打分器都会继承标的的漂移方向。

本模块提供三个纯函数式滚动统计量，全部**只看历史、不看未来**（无前视）：

1. `SourceNormalizer` —— 按源滚动 z-score 去均值，消除结构性常数偏移。
2. `RollingPercentile` —— 当前波动率在近 N 根中的滚动分位（P1-2 波动 regime 闸）。
3. `RollingBaseline`  —— 融合分自身的滚动均值（P1-3 阈值零点校正）。

预热期语义
----------
样本不足 `min_periods` 时**返回 0.0（不给方向）**，宁可空仓也不输出未校准的方向。
这比"用 3 个样本估均值"安全得多。

幂等性
------
`fuse_all` 在同一轮可能被调用多次（本地融合一次、拿到新闻面后再融合一次）。
`obs_id` 保证同一观测只入缓冲区一次，避免重复计数把滚动统计量拉偏。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

# z-score 截断：|z|>3 视为异常值，避免单轮极值主导融合
Z_CLIP = 3.0


class SourceNormalizer:
    """按信号源维护滚动均值/标准差，消除结构性常数偏移。

    用法::

        nz = SourceNormalizer(win=1440, min_periods=240)
        z = nz.normalize("openmobius_smc", raw_score, obs_id=round_id)
    """

    def __init__(self, win: int = 1440, min_periods: int = 240,
                 clip: float = Z_CLIP) -> None:
        self.win = max(int(win), 2)
        self.min_periods = max(int(min_periods), 2)
        self.clip = float(clip)
        self._buf: dict[str, list[float]] = {}
        self._last_obs: dict[str, int] = {}      # source -> 最近一次入缓冲的 obs_id
        self._cache: dict[str, float] = {}       # source -> 该 obs_id 的归一化结果

    # ---------- 主接口 ----------
    def normalize(self, name: str, x: float, obs_id: int | None = None) -> float:
        """返回去均值后的 z-score；预热期或退化情形返回 0.0。

        obs_id 相同 → 直接返回上次结果，不重复入缓冲（同轮多次融合幂等）。
        """
        if not math.isfinite(x):
            return 0.0
        if obs_id is not None and self._last_obs.get(name) == obs_id:
            return self._cache.get(name, 0.0)

        b = self._buf.setdefault(name, [])
        b.append(float(x))
        if len(b) > self.win:
            del b[: len(b) - self.win]
        if obs_id is not None:
            self._last_obs[name] = obs_id

        if len(b) < self.min_periods:
            self._cache[name] = 0.0
            return 0.0
        arr = np.asarray(b, dtype=float)
        sd = float(arr.std())
        if sd < 1e-9:
            # 常数源：没有任何信息量，给 0 而不是 0/0
            self._cache[name] = 0.0
            return 0.0
        z = float(np.clip((x - arr.mean()) / sd, -self.clip, self.clip))
        self._cache[name] = z
        return z

    # ---------- 诊断（验收用） ----------
    def mean(self, name: str) -> float:
        b = self._buf.get(name) or []
        return float(np.mean(b)) if b else 0.0

    def positive_ratio(self, name: str) -> float:
        """原始分（未归一）为正的比例 —— 验收标准要求 ∈ [40%, 60%]。"""
        b = self._buf.get(name) or []
        if not b:
            return 0.0
        return float(np.mean([1.0 if v > 0 else 0.0 for v in b]))

    def count(self, name: str) -> int:
        return len(self._buf.get(name) or [])

    def peek(self, name: str, x: float) -> float:
        """**只读**归一化：用当前缓冲算 z-score，但**不入缓冲、不改缓存**。

        用途：预热时把历史原始分转成与运行时同尺度的归一化分
        （`engine._score_from_raw`）。必须只读 —— 预热循环里
        每个时间点都要用同一份缓冲评估，若用 `normalize()` 会边算边写入，
        导致越靠后的样本窗口越"新鲜"，与运行时行为不一致。
        """
        if not math.isfinite(x):
            return 0.0
        b = self._buf.get(name) or []
        if len(b) < self.min_periods:
            return 0.0
        arr = np.asarray(b, dtype=float)
        sd = float(arr.std())
        if sd < 1e-9:
            return 0.0
        return float(np.clip((x - arr.mean()) / sd, -self.clip, self.clip))

    def warm(self, name: str) -> bool:
        return self.count(name) >= self.min_periods

    def prime(self, name: str, values) -> int:
        """用**历史分数序列**预热缓冲区，返回入缓冲的样本数。

        ⚠️ 为什么必须有这个：`min_periods` 是「观测次数 = 决策轮数」。
        1m 决策周期下 240 轮 = 4 小时。如果不预热，系统启动后**前 4 小时
        所有源都返回 0.0** → 融合分恒为 0 → 永不开仓。
        实盘实测：跑 180 轮后 count=180 < 240，score 全程为 0.0。
        「等 4 小时自然预热」在 1m 短线场景下等于「启动即瘫痪」。

        做法：把历史各轮算出的 raw score 直接灌进缓冲（只保留最近 win 个），
        使系统**第一轮**就能给出有效的归一化分。

        正确性：这些历史分数由**同一套无前视代码**在已收盘的 bar 上算出，
        与实盘逐轮累积得到的缓冲区在分布上一致（同一估计量、同一窗口）。
        实盘重启时 `load_state` 会优先恢复真实缓冲区，prime 只作兜底。
        """
        arr = [float(v) for v in values if math.isfinite(float(v))]
        if not arr:
            return 0
        b = self._buf.setdefault(name, [])
        b.extend(arr)
        if len(b) > self.win:
            del b[: len(b) - self.win]
        # 预热后清掉该源的幂等缓存，让下一轮重新计算
        self._last_obs.pop(name, None)
        self._cache.pop(name, None)
        return len(b)

    def prime_from(self, series: dict[str, list[float]]) -> dict[str, int]:
        """批量预热。series = {source_name: [历史 raw score, ...]}"""
        return {n: self.prime(n, v) for n, v in series.items()}

    # ---------- 持久化（实盘重启不丢预热） ----------
    def to_dict(self) -> dict:
        return {"win": self.win, "min_periods": self.min_periods, "clip": self.clip,
                "buf": {k: v[-self.win:] for k, v in self._buf.items()},
                "last_obs": self._last_obs}

    @classmethod
    def from_dict(cls, d: dict) -> "SourceNormalizer":
        obj = cls(win=d.get("win", 1440), min_periods=d.get("min_periods", 240),
                  clip=d.get("clip", Z_CLIP))
        obj._buf = {k: [float(x) for x in v] for k, v in (d.get("buf") or {}).items()}
        obj._last_obs = {k: int(v) for k, v in (d.get("last_obs") or {}).items()}
        return obj

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict()), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "SourceNormalizer":
        if path.exists():
            try:
                return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                pass
        return cls()


class RollingPercentile:
    """滚动分位：当前值在近 `win` 个观测中的分位（0..1）。"""

    def __init__(self, win: int = 1440, min_periods: int = 240) -> None:
        self.win = max(int(win), 2)
        self.min_periods = max(int(min_periods), 2)
        self._buf: list[float] = []
        self._last_obs: int | None = None
        self._cache: float = 0.5

    def update(self, x: float, obs_id: int | None = None) -> float:
        """入缓冲并返回当前分位；预热期返回 0.5（中性，不误杀）。"""
        if not math.isfinite(x):
            return self._cache
        if obs_id is not None and self._last_obs == obs_id:
            return self._cache
        self._buf.append(float(x))
        if len(self._buf) > self.win:
            del self._buf[: len(self._buf) - self.win]
        if obs_id is not None:
            self._last_obs = obs_id
        if len(self._buf) < self.min_periods:
            self._cache = 0.5
            return 0.5
        arr = np.asarray(self._buf, dtype=float)
        self._cache = float((arr <= x).mean())
        return self._cache

    def count(self) -> int:
        return len(self._buf)

    def peek(self, x: float) -> float:
        """**只读**分位：用当前缓冲算，但**不入缓冲**。

        预热时必须用它 —— 若用 `update()` 边算边写，再调 `prime()`
        就会把同一批样本**灌两遍**（实测 301 步 → buf=602）。
        """
        if not math.isfinite(x):
            return 0.5
        if len(self._buf) < self.min_periods:
            return 0.5
        arr = np.asarray(self._buf, dtype=float)
        return float((arr <= x).mean())

    def prime(self, values) -> int:
        """用历史观测预热（避免启动后 min_periods 轮内返回中性 0.5）。"""
        arr = [float(v) for v in values if math.isfinite(float(v))]
        if not arr:
            return len(self._buf)
        self._buf.extend(arr)
        if len(self._buf) > self.win:
            del self._buf[: len(self._buf) - self.win]
        self._last_obs = None
        return len(self._buf)

    def to_dict(self) -> dict:
        return {"win": self.win, "min_periods": self.min_periods,
                "buf": self._buf[-self.win:], "last_obs": self._last_obs}

    @classmethod
    def from_dict(cls, d: dict) -> "RollingPercentile":
        obj = cls(win=d.get("win", 1440), min_periods=d.get("min_periods", 240))
        obj._buf = [float(x) for x in (d.get("buf") or [])]
        obj._last_obs = d.get("last_obs")
        return obj

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict()), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "RollingPercentile":
        if path.exists():
            try:
                return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                pass
        return cls()


class RollingBaseline:
    """融合分滚动均值 S0（P1-3）。

    融合分的零点不在 0 时，`|S| < thr` 的判据是错的：S=+0.52 的"中性"会被当成
    "偏多"。开仓阈值判断前先减掉这个滚动基线。
    """

    def __init__(self, win: int = 1440, min_periods: int = 240) -> None:
        self.win = max(int(win), 2)
        self.min_periods = max(int(min_periods), 2)
        self._buf: list[float] = []
        self._last_obs: int | None = None
        self._cache: float = 0.0

    def update(self, s: float, obs_id: int | None = None) -> float:
        if not math.isfinite(s):
            return self._cache
        if obs_id is not None and self._last_obs == obs_id:
            return self._cache
        self._buf.append(float(s))
        if len(self._buf) > self.win:
            del self._buf[: len(self._buf) - self.win]
        if obs_id is not None:
            self._last_obs = obs_id
        if len(self._buf) < self.min_periods:
            self._cache = 0.0
            return 0.0
        self._cache = float(np.mean(self._buf))
        return self._cache

    @property
    def value(self) -> float:
        return self._cache

    def count(self) -> int:
        return len(self._buf)

    def prime(self, values) -> int:
        """用历史融合分预热基线（避免启动后 min_periods 轮内基线为 0）。"""
        arr = [float(v) for v in values if math.isfinite(float(v))]
        if not arr:
            return len(self._buf)
        self._buf.extend(arr)
        if len(self._buf) > self.win:
            del self._buf[: len(self._buf) - self.win]
        self._last_obs = None
        if len(self._buf) >= self.min_periods:
            self._cache = float(np.mean(self._buf))
        return len(self._buf)

    def to_dict(self) -> dict:
        return {"win": self.win, "min_periods": self.min_periods,
                "buf": self._buf[-self.win:], "last_obs": self._last_obs}

    @classmethod
    def from_dict(cls, d: dict) -> "RollingBaseline":
        obj = cls(win=d.get("win", 1440), min_periods=d.get("min_periods", 240))
        obj._buf = [float(x) for x in (d.get("buf") or [])]
        obj._last_obs = d.get("last_obs")
        return obj

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict()), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "RollingBaseline":
        if path.exists():
            try:
                return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                pass
        return cls()
