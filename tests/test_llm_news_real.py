"""LLM/新闻面真实测试（无 mock）。

- runninghub deepseek/deepseek-v4.1-flash 真实结构化输出（关闭思考）
- 金十 search_flash 真实快讯
- 超时/降级路径：人为构造无法满足 schema 的响应场景（超短超时）→ 返回 None
"""
from __future__ import annotations

import asyncio

import pytest

from gold_agent.common.config import CFG, PROJECT_ROOT, LLMConfig
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


# ══════════════════════════════════════════════════════════════════
# 模型与推理开关（用户 2026-10-08 指定）
# ══════════════════════════════════════════════════════════════════
def test_active_model_is_deepseek_flash():
    """项目当前使用 deepseek/deepseek-v4.1-flash。

    ⚠️ 这是**运行时的实际值**（走 RUNNINGHUB_MODEL），不是硬编码断言。
    历史上曾用 glm/glm-5.3-flash —— 那个模型强制思考且关不掉，
    白天 review 中位 60.7 秒超时、成功率仅 22.9%。
    """
    assert CFG.llm.model == "deepseek/deepseek-v4.1-flash", (
        f"当前模型为 {CFG.llm.model!r}，用户要求 "
        f"deepseek/deepseek-v4.1-flash")


def test_reasoning_is_disabled():
    """推理必须是关闭的。

    ⚠️ 关键陷阱：留空（""）表示**不带该参数**，即保持模型默认 = **开启思考**，
    与"关闭推理"完全相反。所以这里断言的是"有值且为 none"。
    实测 none -> 无 reasoning_content；low -> reasoning_content 1506 字符。
    """
    eff = CFG.llm.reasoning_effort
    assert eff, (
        "reasoning_effort 为空 = 不带该参数 = 模型默认开启思考；"
        "关闭推理必须显式设成 'none'")
    assert eff == "none", f"推理等级应为 'none'（关闭），实际 {eff!r}"


def test_config_defaults_match_env_so_switch_survives_missing_env():
    """兜底默认值必须与 .env 一致，否则 .env 缺失时会静默退回旧模型。

    ⚠️ 为什么单独测这个：`.env` 被 .gitignore 忽略、**不入库**。
    若 `config.py` 的默认值仍是旧的 glm 模型，别人克隆后（或 .env 漏行）
    会静默用回"强制思考关不掉"的旧模型，症状是每轮凭空多耗时约 120 秒。
    """
    import inspect
    import os

    src = inspect.getsource(LLMConfig)
    assert 'os.getenv("RUNNINGHUB_MODEL", "deepseek/deepseek-v4.1-flash")' in src, \
        "RUNNINGHUB_MODEL 的兜底默认值不是 deepseek-flash"
    assert 'os.getenv("RUNNINGHUB_REASONING_EFFORT", "none")' in src, \
        "reasoning_effort 的兜底默认值不是 none（留空会开启思考）"
    # .env.example 是入库的模板，必须同步
    tpl = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "RUNNINGHUB_MODEL=deepseek/deepseek-v4.1-flash" in tpl, \
        ".env.example 模板里的模型未同步"
    assert "RUNNINGHUB_REASONING_EFFORT=none" in tpl, \
        ".env.example 模板缺少关闭推理的配置"


def test_request_body_carries_reasoning_none():
    """真正发出去的请求体必须带 reasoning_effort=none。

    只查配置不够 —— 若 client 构建 body 时漏掉该字段，配置再对也没用。
    """
    import inspect
    src = inspect.getsource(RunningHubClient._one_call)
    assert '"model": self.model' in src, "请求体未使用 self.model"
    assert 'body["reasoning_effort"] = CFG.llm.reasoning_effort' in src, \
        "请求体没有带上 reasoning_effort，关闭推理不会生效"
    assert 'if CFG.llm.reasoning_effort:' in src, \
        "reasoning_effort 的注入条件被改动，请确认仍然生效"

