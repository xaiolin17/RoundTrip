"""runninghub LLM 客户端（docs/03）。

- 不使用 qwen（用户明确要求）；主模型 glm/glm-5.3-flash。
- 并发、超时、预算器、结构化输出 JSON、降级路径。
- 新闻面不再依赖 webSearch 模型；由金十快讯直接给出消息面数据。
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque

import aiohttp

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import llm_log

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
        "key_levels": {"type": "array", "items": {"type": "number"}},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
        "invalidation": {"type": "string"},
    },
    "required": ["verdict", "confidence", "rationale"],
}

NEWS_SCHEMA = {
    "type": "object",
    "properties": {
        "sentiment": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
        "impact": {"type": "number"},
        "note": {"type": "string"},
        "headline_directions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["sentiment", "impact"],
}


class LLMError(RuntimeError):
    pass


class Budget:
    def __init__(self, per_hour: int) -> None:
        self.per_hour = per_hour
        self._calls: deque[float] = deque()

    def allow(self) -> bool:
        now = time.time()
        while self._calls and now - self._calls[0] > 3600:
            self._calls.popleft()
        return len(self._calls) < self.per_hour

    def record(self) -> None:
        self._calls.append(time.time())


class RunningHubClient:
    def __init__(self) -> None:
        cfg = CFG.llm
        if not cfg.api_key:
            raise LLMError("RUNNINGHUB_API_KEY missing; write it to .env")
        self.base_url = cfg.base_url.rstrip("/")
        self.model = cfg.model
        self.api_key = cfg.api_key
        self.budget = Budget(cfg.per_hour_budget)
        self._session: aiohttp.ClientSession | None = None

    async def _ensure(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=CFG.llm.timeout_s),
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"})
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def chat_json(self, system: str, user: str, schema: dict,
                        timeout_s: float | None = None) -> dict | None:
        """结构化输出；失败返回 None（调用方降级），不抛出。"""
        if not self.budget.allow():
            llm_log({"event": "budget_exhausted", "model": self.model})
            return None
        self.budget.record()
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        session = await self._ensure()
        t0 = time.time()
        try:
            async with session.post(f"{self.base_url}/chat/completions", json=body,
                                    timeout=aiohttp.ClientTimeout(total=timeout_s or CFG.llm.timeout_s)) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    llm_log({"event": "http_error", "status": resp.status, "body": text[:500]})
                    return None
                data = await resp.json()
                content = data["choices"][0]["message"]["content"]
                parsed = _extract_json(content)
                llm_log({"event": "chat_ok", "model": self.model,
                         "latency_s": round(time.time() - t0, 2),
                         "user_len": len(user), "parsed_keys": list(parsed) if parsed else None})
                if parsed is None:
                    return None
                # 最小校验
                for req in schema.get("required", []):
                    if req not in parsed:
                        return None
                return parsed
        except Exception as e:
            ename = type(e).__name__
            llm_log({"event": "chat_error", "error_type": ename,
                     "error": str(e) or ename, "latency_s": round(time.time() - t0, 2)})
            return None


def _extract_json(content: str) -> dict | None:
    content = content.strip()
    # ```json 包裹
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
    try:
        v = json.loads(content)
        return v if isinstance(v, dict) else None
    except Exception:
        pass
    # 正则找第一个 { ... } 平衡块
    start = content.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    v = json.loads(content[start:i + 1])
                    return v if isinstance(v, dict) else None
                except Exception:
                    return None
    return None
