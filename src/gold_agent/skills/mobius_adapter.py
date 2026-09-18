"""openmobius skill 适配器（docs/02 §2）。

Mobius Quant API 仅作 SMC 结构信号源（用户确认）：
- 进程内 aiohttp 调用 /api/indicators calc=[{name:"smc"}]
- 令牌桶限速 10 req/min + LRU 缓存 TTL 60s + stale 降级（≤300s 旧值 ×0.7 权重）
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import aiohttp

from gold_agent.common.config import CFG


@dataclass
class MobiusResult:
    status: str = "unavailable"     # ok | stale | unavailable
    score: float = 0.0
    structures: list[dict] = field(default_factory=list)   # swing_structures
    order_blocks: list[dict] = field(default_factory=list)
    fvgs: list[dict] = field(default_factory=list)
    premium_zone: dict | None = None
    discount_zone: dict | None = None
    current_price: float | None = None
    last_bar_age_s: float | None = None
    stale: bool = False
    error: str = ""
    computed_at: float = 0.0


class _TokenBucket:
    """10 req/min 令牌桶，等待上限由调用方超时控制。"""

    def __init__(self, rate_per_min: int) -> None:
        self.capacity = max(1, rate_per_min)
        self.tokens = float(self.capacity)
        self.rate = rate_per_min / 60.0
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, timeout: float = 5.0) -> bool:
        async with self._lock:
            deadline = time.monotonic() + timeout
            while True:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return True
                if now >= deadline:
                    return False
                await asyncio.sleep(max(0.0, min(1.0, (1 - self.tokens) / self.rate)))


class MobiusClient:
    SUPPORTED_INTERVALS = ("1m", "5m", "15m", "30m", "1h", "4h", "1d")

    def __init__(self) -> None:
        self._bucket = _TokenBucket(CFG.mobius.rate_per_min)
        self._cache: dict[tuple[str, str], tuple[float, dict]] = {}
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": "GoldAgent/0.1"})
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_smc(self, symbol: str, interval: str, limit: int = 200) -> MobiusResult:
        """interval 必须在 SUPPORTED_INTERVALS 内，否则返回 unavailable（不抛错）。"""
        out = MobiusResult(computed_at=time.time())
        if interval not in self.SUPPORTED_INTERVALS:
            out.error = f"interval {interval} unsupported by mobius"
            return out
        key = (symbol, interval)
        cached = self._cache.get(key)
        if cached and time.time() - cached[0] <= CFG.mobius.cache_ttl_s:
            out.status = "ok"
            out.current_price = cached[1].get("current_price")
            self._fill(out, cached[1])
            return out
        ok = await self._bucket.acquire(timeout=5.0)
        if not ok:
            if cached and time.time() - cached[0] <= CFG.mobius.stale_max_age_s:
                out.status = "stale"
                self._fill(out, cached[1])
                return out
            out.error = "rate_limit_timeout_no_cache"
            return out
        body = {"exchange": "commodity", "market": "spot", "symbol": symbol,
                "interval": interval, "limit": limit, "calc": [{"name": "smc"}]}
        try:
            session = await self._ensure_session()
            async with session.post(f"{CFG.mobius.base_url}/api/indicators?explain=false",
                                    json=body) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._cache[key] = (time.time(), data)
                    out.status = "ok"
                    out.current_price = data.get("current_price")
                    self._fill(out, data)
                elif resp.status in (429, 403):
                    if cached and time.time() - cached[0] <= CFG.mobius.stale_max_age_s:
                        out.status = "stale"
                        self._fill(out, cached[1])
                    else:
                        out.error = f"mobius http {resp.status}"
                else:
                    out.error = f"mobius http {resp.status}"
        except Exception as e:
            out.error = f"mobius error: {e}"
            if cached and time.time() - cached[0] <= CFG.mobius.stale_max_age_s:
                out.status = "stale"
                self._fill(out, cached[1])
        return out

    def _fill(self, out: MobiusResult, data: dict) -> None:
        ind_key = next(iter(data.get("indicators", {})), None)
        out.stale = bool(data.get("data_meta", {}).get("stale"))
        if ind_key is None:
            return
        objs = data["indicators"][ind_key].get("objects", {})
        out.structures = objs.get("swing_structures", [])
        out.order_blocks = objs.get("order_blocks_swing", [])
        out.fvgs = objs.get("fair_value_gaps", [])
        # 最新一行的 premium/dispatch 区（从 indicators 表 data 末行拿不到 zone 时用 objects）
        out.premium_zone = None
        out.discount_zone = None

    def score(self, res: MobiusResult, last_price: float) -> float:
        """docs/02 §4：CHoCH=±2, BOS=±1.5, OB+FVG 交汇=±1, premium/discount ±0.5。"""
        return _score_fn(res, last_price)
        if res.status == "unavailable" or not res.structures:
            return 0.0
        w = 0.7 if res.status == "stale" else 1.0
        score = 0.0
        for s in res.structures[-3:]:
            bias = s.get("bias")
            kind = s.get("kind")
            v = 0.0
            if kind == "CHoCH":
                v = 2.0
            elif kind == "BOS":
                v = 1.5
            score += v if bias == "bull" else -v
        # 最新 active OB + FVG 与现价关系
        for ob in res.order_blocks:
            if ob.get("status") == "active":
                if ob.get("bias") == "bull" and ob.get("bottom") and last_price <= ob["bottom"] * 1.002:
                    score += 1.0
                elif ob.get("bias") == "bear" and ob.get("top") and last_price >= ob["top"] * 0.998:
                    score -= 1.0
        for f in res.fvgs:
            if f.get("status") == "active":
                if f.get("bias") == "bull" and f.get("bottom") and last_price <= f["bottom"] * 1.002:
                    score += 1.0
                elif f.get("bias") == "bear" and f.get("top") and last_price >= f["top"] * 0.998:
                    score -= 1.0
        return max(-3.0, min(3.0, score * w))


def _score_fn(res: "MobiusResult", last_price: float) -> float:
    """独立打分函数（引擎直接复用，避免方法绑定歧义）。"""
    if res.status == "unavailable" or not res.structures:
        return 0.0
    w = 0.7 if res.status == "stale" else 1.0
    score = 0.0
    for s in res.structures[-3:]:
        bias = s.get("bias")
        kind = s.get("kind")
        v = 2.0 if kind == "CHoCH" else (1.5 if kind == "BOS" else 0.0)
        score += v if bias == "bull" else -v
    for ob in res.order_blocks:
        if ob.get("status") == "active":
            if ob.get("bias") == "bull" and ob.get("bottom") and last_price <= ob["bottom"] * 1.002:
                score += 1.0
            elif ob.get("bias") == "bear" and ob.get("top") and last_price >= ob["top"] * 0.998:
                score -= 1.0
    for f in res.fvgs:
        if f.get("status") == "active":
            if f.get("bias") == "bull" and f.get("bottom") and last_price <= f["bottom"] * 1.002:
                score += 1.0
            elif f.get("bias") == "bear" and f.get("top") and last_price >= f["top"] * 0.998:
                score -= 1.0
    return max(-3.0, min(3.0, score * w))
