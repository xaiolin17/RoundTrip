"""openmobius skill 适配器（docs/02 §2）。

Mobius Quant API 仅作 SMC 结构信号源（用户确认）：
- 进程内 aiohttp 调用 /api/indicators calc=[{name:"smc"}]
- 令牌桶限速 10 req/min + LRU 缓存 TTL 60s + stale 降级（≤300s 旧值 ×0.7 权重）

字段采集对齐 SKILL.md 的「SMC field semantics」咨询顺序
------------------------------------------------------
openmobius SKILL.md 规定按 7 步顺序使用 SMC 字段：

1. **Trend bias**：`swing_trend` vs `internal_trend`，同号=强趋势，异号=潜在反转/区间
2. **Most recent structural event**：`kind: BOS`（延续）vs `CHoCH`（反转），
   **CHoCH 优先级高于 BOS**
3. **Trailing extremes labels**：`Strong High`+`Weak Low`=确认看跌结构；反之看涨
4. **Active Order Blocks**（status=active）
5. **Active Fair Value Gaps**
6. **Equal highs / equal lows**（止损簇流动性）
7. **Premium / equilibrium / discount placement**

旧版 `_fill` 只取了 swing_structures / order_blocks_swing / fair_value_gaps，
并把 premium_zone / discount_zone 硬置 None —— 导致第 3、6、7 步完全无法执行。
本版采集全部字段，使 LLM 能按 skill 规定的顺序分析。

SKILL.md 的 Caveats 也在此如实记录（swing pivot 确认延迟、OB 事后修订、
低波动 FVG 频发、结构信号非入场触发器），供 prompt 披露。
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
    # ---- 结构事件 ----
    structures: list[dict] = field(default_factory=list)          # swing_structures
    internal_structures: list[dict] = field(default_factory=list)  # internal_structures
    swing_pivots: list[dict] = field(default_factory=list)
    internal_pivots: list[dict] = field(default_factory=list)
    # ---- 区域 ----
    order_blocks: list[dict] = field(default_factory=list)         # order_blocks_swing
    order_blocks_internal: list[dict] = field(default_factory=list)
    fvgs: list[dict] = field(default_factory=list)
    equal_highs: list[dict] = field(default_factory=list)
    equal_lows: list[dict] = field(default_factory=list)
    # ---- 状态标签（SKILL.md 第 3、7 步）----
    trailing_extremes: dict | None = None
    premium_zone: dict | None = None
    equilibrium_zone: dict | None = None
    discount_zone: dict | None = None
    alerts_last_bar: dict = field(default_factory=dict)
    # ---- 元数据 ----
    current_price: float | None = None
    last_bar_age_s: float | None = None
    stale: bool = False
    error: str = ""
    computed_at: float = 0.0

    # ---------- SKILL.md 咨询顺序的派生量 ----------
    @property
    def last_swing_event(self) -> dict | None:
        """最近一次 swing 结构事件（第 2 步）。"""
        return self.structures[-1] if self.structures else None

    @property
    def last_internal_event(self) -> dict | None:
        return self.internal_structures[-1] if self.internal_structures else None

    def trend_bias(self) -> tuple[int, int]:
        """(swing_bias, internal_bias)，各 ∈ {-1,0,1}（第 1 步）。"""
        def _bias(ev: dict | None) -> int:
            if not ev:
                return 0
            b = str(ev.get("bias", "")).lower()
            return 1 if b in ("bull", "bullish") else (-1 if b in ("bear", "bearish") else 0)
        return _bias(self.last_swing_event), _bias(self.last_internal_event)

    def zone_of(self, price: float | None) -> str:
        """当前价在 premium / equilibrium / discount 哪一区（第 7 步）。"""
        if price is None:
            return "unknown"
        for name, z in (("premium", self.premium_zone),
                        ("equilibrium", self.equilibrium_zone),
                        ("discount", self.discount_zone)):
            if z and z.get("top") is not None and z.get("bottom") is not None:
                if float(z["bottom"]) <= price <= float(z["top"]):
                    return name
        return "unknown"

    def extreme_labels(self) -> tuple[str | None, str | None]:
        """(top_label, bottom_label)，如 ('Weak High', 'Strong Low')（第 3 步）。"""
        te = self.trailing_extremes or {}
        return te.get("top_label"), te.get("bottom_label")

    def active_order_blocks(self, kind: str = "swing") -> list[dict]:
        """第 4 步：仅 status=active 的 OB。"""
        src = self.order_blocks if kind == "swing" else self.order_blocks_internal
        return [ob for ob in src if str(ob.get("status", "")).lower() == "active"]

    def active_fvgs(self) -> list[dict]:
        """第 5 步：仅 status=active 的 FVG。"""
        return [f for f in self.fvgs if str(f.get("status", "")).lower() == "active"]


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
        """采集全部 SMC objects 字段（旧版只取 3 个，导致 skill 第 3/6/7 步无法执行）。"""
        ind_key = next(iter(data.get("indicators", {})), None)
        meta = data.get("data_meta", {}) or {}
        out.stale = bool(meta.get("stale"))
        # 数据新鲜度（SKILL.md 要求披露 last_bar_age_seconds / is_stale）
        as_of = meta.get("data_as_of_ms")
        if as_of:
            out.last_bar_age_s = max(0.0, time.time() - float(as_of) / 1000.0)
        if ind_key is None:
            return
        objs = data["indicators"][ind_key].get("objects", {}) or {}
        out.structures = objs.get("swing_structures", []) or []
        out.internal_structures = objs.get("internal_structures", []) or []
        out.swing_pivots = objs.get("swing_pivots", []) or []
        out.internal_pivots = objs.get("internal_pivots", []) or []
        out.order_blocks = objs.get("order_blocks_swing", []) or []
        out.order_blocks_internal = objs.get("order_blocks_internal", []) or []
        out.fvgs = objs.get("fair_value_gaps", []) or []
        out.equal_highs = objs.get("equal_highs", []) or []
        out.equal_lows = objs.get("equal_lows", []) or []
        out.trailing_extremes = objs.get("trailing_extremes") or None
        out.premium_zone = objs.get("premium_zone") or None
        out.equilibrium_zone = objs.get("equilibrium_zone") or None
        out.discount_zone = objs.get("discount_zone") or None
        out.alerts_last_bar = objs.get("alerts_last_bar") or {}

    def score(self, res: MobiusResult, last_price: float) -> float:
        """docs/02 §4：CHoCH=±2, BOS=±1.5, OB+FVG 交汇=±1, premium/discount ±0.5。"""
        return _score_fn(res, last_price)


def _score_fn(res: "MobiusResult", last_price: float) -> float:
    """SMC 结构打分（独立函数，引擎直接复用）。

    ⚠️ 本函数是**有符号累加**，因此天然带有标的漂移方向的常数偏移：
    黄金长期上行 → bull 结构持续累积 → 实测 88% 为正、均值 +1.2604。
    这个偏移**必须**由 `fusion/normalize.SourceNormalizer` 的滚动 z-score 消除
    （research/18 P0-1）。本函数只负责把结构映射到方向分，不做去偏。

    打分按 SKILL.md 的咨询顺序加权：
    - 第 2 步 CHoCH（反转，优先级高于 BOS）权重 2.0；BOS（延续）权重 1.5
    - 越近的结构事件权重越高（最近 1 条 ×1.0，往前 ×0.7 / ×0.5）
    - 第 3 步 trailing extremes 的 Strong/Weak 标签给出结构确认（±0.5）
    - 第 4/5 步 active OB / FVG 与现价的位置关系（±1.0，两者交汇再 +0.5）
    - 第 7 步 premium 区做空加成、discount 区做多加成（±0.5）
    """
    if res.status == "unavailable" or not res.structures:
        return 0.0
    w = 0.7 if res.status == "stale" else 1.0
    score = 0.0

    # ---- 第 2 步：最近结构事件（CHoCH > BOS），近端加权 ----
    recency = (1.0, 0.7, 0.5)
    for i, s in enumerate(reversed(res.structures[-3:])):
        bias = s.get("bias")
        kind = s.get("kind")
        v = 2.0 if kind == "CHoCH" else (1.5 if kind == "BOS" else 0.0)
        score += (v if bias == "bull" else -v) * recency[i]

    # ---- 第 3 步：trailing extremes 的 Strong/Weak 标签 ----
    top_label, bottom_label = res.extreme_labels()
    if top_label and bottom_label:
        strong_top = "Strong" in str(top_label)
        strong_bottom = "Strong" in str(bottom_label)
        # Strong High + Weak Low = 确认看跌结构；Strong Low + Weak High = 看涨
        if strong_top and not strong_bottom:
            score -= 0.5
        elif strong_bottom and not strong_top:
            score += 0.5

    # ---- 第 4/5 步：active OB / FVG 与现价的关系 ----
    ob_hit = 0
    for ob in res.active_order_blocks("swing"):
        if ob.get("bias") == "bull" and ob.get("bottom") and last_price <= ob["bottom"] * 1.002:
            score += 1.0
            ob_hit += 1
        elif ob.get("bias") == "bear" and ob.get("top") and last_price >= ob["top"] * 0.998:
            score -= 1.0
            ob_hit -= 1
    fvg_hit = 0
    for f in res.active_fvgs():
        if f.get("bias") == "bull" and f.get("bottom") and last_price <= f["bottom"] * 1.002:
            score += 1.0
            fvg_hit += 1
        elif f.get("bias") == "bear" and f.get("top") and last_price >= f["top"] * 0.998:
            score -= 1.0
            fvg_hit -= 1
    # OB 与 FVG 同向交汇 → 额外加成（docs/02 §4）
    if ob_hit and fvg_hit and (ob_hit > 0) == (fvg_hit > 0):
        score += 0.5 if ob_hit > 0 else -0.5

    # ---- 第 7 步：premium / discount 区 ----
    zone = res.zone_of(last_price)
    if zone == "premium":
        score -= 0.5      # premium 区做空加成
    elif zone == "discount":
        score += 0.5      # discount 区做多加成

    return max(-3.0, min(3.0, score * w))
