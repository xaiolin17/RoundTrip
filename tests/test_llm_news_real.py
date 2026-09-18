"""LLM/新闻面真实测试（无 mock）。

- runninghub glm-5.3-flash 真实结构化输出
- 金十 search_flash 真实快讯
- 超时/降级路径：人为构造无法满足 schema 的响应场景（超短超时）→ 返回 None
"""
from __future__ import annotations

import asyncio

import pytest

from gold_agent.common.config import CFG
from gold_agent.llm.client import NEWS_SCHEMA, RunningHubClient
from gold_agent.news.collector import Jin10Collector


@pytest.mark.asyncio
async def test_jin10_real_fetch():
    col = Jin10Collector()
    view = await col.fetch(force=True)
    assert view.error == "", view.error
    assert len(view.items) > 0, "金十快讯应至少返回 1 条"
    assert any(it.gold_relevant for it in view.items)


@pytest.mark.asyncio
async def test_llm_real_structured():
    client = RunningHubClient()
    try:
        out = await client.chat_json(
            "你是测试助手。只输出 JSON。",
            '输出 {"sentiment":"neutral","impact":0.1,"note":"test","headline_directions":[]}',
            NEWS_SCHEMA, timeout_s=60)
        assert out is not None
        assert out["sentiment"] in ("bullish", "bearish", "neutral")
        assert 0 <= float(out["impact"]) <= 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_llm_timeout_degrades():
    """超短超时 → 降级返回 None（不抛异常、不阻塞）。"""
    client = RunningHubClient()
    try:
        out = await client.chat_json(
            "你是测试助手。请输出一个很长的 JSON。",
            "输出包含 500 个字段的 JSON 对象",
            NEWS_SCHEMA, timeout_s=0.001)   # 立即超时
        assert out is None
    finally:
        await client.close()
