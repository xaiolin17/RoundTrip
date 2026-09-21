"""runninghub LLM 客户端（docs/03）。

- 主模型 deepseek/deepseek-v4.1-flash，**关闭思考模式**
  （`reasoning_effort="none"`；界面上叫 off，线上传 "off" 会 400）。
  换模型与关思考的原因：原 glm/glm-5.3-flash 强制思考无法关闭，
  白天 review 中位 60.7 秒超时、成功率仅 22.9%，
  每轮因此耗时 121 秒（其中 120 秒是等超时）。
- 并发、超时、**分离预算器**、结构化输出 JSON、降级路径。

research/20 的修正
------------------
旧版 review 与 news 共用一个 24 次/小时的预算池，news 每轮都可能触发 →
把 review 的额度吃光（budget_exhausted 150 次），review 覆盖率只剩 4.3%。
本版按 `kind` 分离预算：`review` 与 `news` 各自独立计账。

重试策略（docs/03 §3）
----------------------
失败/解析失败 → 重试 `CFG.llm.retry` 次（温度 0）→ 仍失败 → 返回 None，
调用方降级（该轮 LLM 分量记 0，本地融合照常决策）。
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
        # skill 契约：LLM 必须走完两个 skill 的检查项
        "skill_audit": {
            "type": "object",
            "properties": {
                "chanlun_mode": {"type": "string"},
                "chanlun_gates": {"type": "object"},
                "smc_steps": {"type": "object"},
                "probability_tier": {"type": "string"},
                "caveats_disclosed": {"type": "boolean"},
            },
        },
        "key_levels": {"type": "array", "items": {"type": "number"}},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
        "invalidation": {"type": "string"},
        "next_observation": {"type": "string"},
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
    """按 kind 分离的滚动小时预算器（research/20）。"""

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

    @property
    def used(self) -> int:
        now = time.time()
        while self._calls and now - self._calls[0] > 3600:
            self._calls.popleft()
        return len(self._calls)


class RunningHubClient:
    def __init__(self) -> None:
        cfg = CFG.llm
        if not cfg.api_key:
            raise LLMError("RUNNINGHUB_API_KEY missing; write it to .env")
        self.base_url = cfg.base_url.rstrip("/")
        self.model = cfg.model
        self.api_key = cfg.api_key
        # 分离预算：review 与 news 各自独立，互不挤占
        self.budgets: dict[str, Budget] = {
            "review": Budget(cfg.per_hour_budget),
            "news": Budget(cfg.news_per_hour_budget),
        }
        self._session: aiohttp.ClientSession | None = None

    def _budget(self, kind: str) -> Budget:
        return self.budgets.setdefault(kind, Budget(CFG.llm.per_hour_budget))

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
                        timeout_s: float | None = None,
                        kind: str = "review") -> dict | None:
        """结构化输出；失败返回 None（调用方降级），不抛出。

        kind: "review" | "news" —— 决定使用哪个预算池。
        """
        budget = self._budget(kind)
        if not budget.allow():
            llm_log({"event": "budget_exhausted", "model": self.model, "kind": kind,
                     "used": budget.used, "cap": budget.per_hour})
            return None
        budget.record()

        attempts = max(1, int(CFG.llm.retry) + 1)
        last_err = ""
        for attempt in range(attempts):
            # 重试时换温度 0（docs/03 §3）
            temp = 0.2 if attempt == 0 else 0.0
            parsed, err = await self._one_call(system, user, schema, timeout_s, temp, kind)
            if parsed is not None:
                # 最小校验：required 字段必须存在
                missing = [r for r in schema.get("required", []) if r not in parsed]
                if not missing:
                    return parsed
                last_err = f"missing required fields: {missing}"
                llm_log({"event": "schema_incomplete", "kind": kind, "missing": missing})
            else:
                last_err = err
        llm_log({"event": "chat_failed_after_retry", "kind": kind, "error": last_err})
        return None

    async def _one_call(self, system: str, user: str, schema: dict,
                        timeout_s: float | None, temperature: float,
                        kind: str) -> tuple[dict | None, str]:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": temperature,
        }
        # 关闭思考模式（用户要求）。界面上叫 off，线上取值是 "none"。
        # 留空则不带该参数，保持模型默认行为。
        if CFG.llm.reasoning_effort:
            body["reasoning_effort"] = CFG.llm.reasoning_effort
        session = await self._ensure()
        t0 = time.time()
        try:
            async with session.post(
                    f"{self.base_url}/chat/completions", json=body,
                    timeout=aiohttp.ClientTimeout(total=timeout_s or CFG.llm.timeout_s)) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    llm_log({"event": "http_error", "status": resp.status,
                             "kind": kind, "body": text[:500]})
                    return None, f"http {resp.status}"
                data = await resp.json()
                content = data["choices"][0]["message"]["content"]
                parsed = _extract_json(content)
                llm_log({"event": "chat_ok", "model": self.model, "kind": kind,
                         "latency_s": round(time.time() - t0, 2),
                         "reasoning_effort": CFG.llm.reasoning_effort or "default",
                         "user_len": len(user),
                         "parsed_keys": list(parsed) if parsed else None})
                if parsed is None:
                    return None, "json_parse_failed"
                return parsed, ""
        except Exception as e:
            ename = type(e).__name__
            llm_log({"event": "chat_error", "kind": kind, "error_type": ename,
                     "error": str(e) or ename, "latency_s": round(time.time() - t0, 2)})
            return None, f"{ename}: {e}"


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
