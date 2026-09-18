"""金十 MCP 快讯采集（docs/07）。

token 从 .env JIN10_TOKEN 读取（与旧脚本一致的 MCP over HTTP 协议）。
失败降级：返回空 NewsView，不阻塞主循环。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiohttp

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import news_log

_GOLD_KEYWORDS = ("黄金", "金价", "XAU", "美元", "美联储", "非农", "CPI", "PCE",
                  "利率", "降息", "加息", "地缘", "战争", "关税", "通胀", "就业")
_HIGH_RISK_KEYWORDS = ("非农", "CPI", "PCE", "FOMC", "议息", "利率决议", "鲍威尔", "PPI")


@dataclass
class NewsItem:
    ts: str
    source: str
    title: str
    level: str = "normal"       # normal | gold | high_risk
    gold_relevant: bool = False


@dataclass
class NewsView:
    items: list[NewsItem] = field(default_factory=list)
    high_risk_window: bool = False
    error: str = ""
    fetched_at: float = 0.0


def _news_age_seconds(ts: str, now: float) -> float | None:
    """快讯时间距今秒数；解析失败返回 None（视为不可判定，不参与高危判定）。"""
    if not ts:
        return None
    try:
        s = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, now - dt.timestamp())
    except Exception:
        return None


class Jin10Collector:
    def __init__(self) -> None:
        self._cache: NewsView | None = None
        self._cache_at = 0.0

    async def fetch(self, force: bool = False) -> NewsView:
        now = time.time()
        if not force and self._cache and now - self._cache_at <= CFG.jin10.cache_ttl_s:
            return self._cache
        view = NewsView(fetched_at=now)
        token = CFG.jin10.token
        if not token:
            view.error = "JIN10_TOKEN missing"
            self._cache, self._cache_at = view, now
            return view
        try:
            payload = await self._mcp_call(token)
            view.items = self._parse(payload)
        except Exception as e:
            view.error = f"jin10 error: {e}"
            news_log({"event": "fetch_error", "error": str(e)})
        for it in view.items:
            if any(k in it.title for k in _HIGH_RISK_KEYWORDS):
                it.level = "high_risk"
                it.gold_relevant = True
            elif any(k in it.title for k in _GOLD_KEYWORDS):
                it.level = "gold"
                it.gold_relevant = True
        recent_hr = False
        for it in view.items:
            if it.level != "high_risk":
                continue
            # 高危窗口只认「最近 30 分钟内」的快讯（用户指定）；旧闻不锁开仓
            age = _news_age_seconds(it.ts, now)
            if age is None or age <= 1800:
                recent_hr = True
                break
        view.high_risk_window = recent_hr
        self._cache, self._cache_at = view, now
        return view

    async def _mcp_call(self, token: str) -> dict:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
            headers = {"Content-Type": "application/json",
                       "Accept": "application/json, text/event-stream",
                       "Authorization": f"Bearer {token}",
                       "User-Agent": "GoldAgent/0.1",
                       "MCP-Protocol-Version": "2025-11-25"}
            # initialize（金十无 session id，每请求独立）
            body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                               "clientInfo": {"name": "goldagent", "version": "0.1"}}}
            async with s.post(CFG.jin10.base_url, json=body, headers=headers) as r:
                await r.text()
            # search_flash 关键词拉取黄金快讯（实测可用；金十无快讯流式推送工具）
            body = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "search_flash", "arguments": {"keyword": "黄金"}}}
            async with s.post(CFG.jin10.base_url, json=body, headers=headers) as r:
                return self._read_sse(await r.text())

    @staticmethod
    def _read_sse(raw: str) -> dict:
        lines = raw.split("\n")
        data_lines = [l for l in lines if l.strip().startswith("data: ")]
        if data_lines:
            return json.loads("\n".join(x.strip()[6:] for x in data_lines))
        return json.loads(raw)

    def _parse(self, payload: dict) -> list[NewsItem]:
        items = []
        result = payload.get("result", {})
        content = result.get("content", [])
        for c in content:
            if c.get("type") != "text":
                continue
            try:
                data = json.loads(c.get("text", "{}"))
            except Exception:
                continue
            rows = data.get("data", {}).get("items", []) if isinstance(data, dict) else []
            for row in rows:
                title = str(row.get("content") or row.get("title") or "")[:200]
                if not title:
                    continue
                items.append(NewsItem(ts=str(row.get("time") or ""),
                                      source="jin10", title=title))
        news_log({"event": "fetched", "count": len(items)})
        return items
