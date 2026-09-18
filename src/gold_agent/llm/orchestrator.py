"""LLM 编排：双 skill 评审 + 新闻面（并发，独立超时与降级）。"""
from __future__ import annotations

import asyncio
import time

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import llm_log
from gold_agent.fusion.engine import FusedEvidence
from gold_agent.llm.client import NEWS_SCHEMA, REVIEW_SCHEMA, RunningHubClient
from gold_agent.news.collector import NewsView

_REVIEW_SYSTEM = """你是资深黄金（XAUUSD）交易评审员。你会收到：
1. 缠论（chanlun）结构分析摘要
2. ICT/SMC（openmobius）结构信号
3. 本地数学融合分数 S 与不确定度 sigma
4. 关键价位与经典指标
5. 最近财经快讯
规则：
- 只允许引用输入中出现的数字/价位，禁止编造价格或"预测未来"。
- 输出严格 JSON：{"verdict":"bullish|bearish|neutral","confidence":0..1,"rationale":"...","key_levels":[...],"risk_flags":[...],"invalidation":"..."}
- confidence < 0.4 时 verdict 应为 neutral。
- 不要输出交易手数或下单指令。
"""

_NEWS_SYSTEM = """你是财经新闻分析师。给你一组最近黄金市场相关快讯。
输出严格 JSON：{"sentiment":"bullish|bearish|neutral","impact":0..1,"note":"一句话","headline_directions":["bullish|bearish|neutral", ...]}
impact 表示对金价短期方向的影响强度；不确定时低分。不要编造新闻标题之外的信息。"""


def build_review_user(ev: FusedEvidence, news: NewsView | None, last_close: float) -> str:
    lines = [f"当前价: {last_close:.2f}"]
    r = ev.result
    lines.append(f"融合分数 S={r.score:+.2f} sigma={r.sigma:.2f} regime={r.regime} hurst={r.hurst} 分歧={r.disagreement}")
    for s in r.per_source:
        lines.append(f"  源 {s['name']}: score={s['score']} sigma={s['sigma']} status={s['status']} bayes={s['bayes']}")
    for tf, cr in ev.chanlun.items():
        if cr.status == "ok":
            lines.append(f"chanlun[{tf}]: structure={cr.structure} score={cr.score:+.2f} "
                         f"center={cr.center} invalidation={cr.invalidation}")
            for sig in cr.signals[:3]:
                lines.append(f"  信号: {sig.get('kind')} @ {sig.get('price')}")
    if ev.mobius is not None and ev.mobius.status != "unavailable":
        structs = [f"{s.get('kind')}/{s.get('bias')}@{s.get('pivot_price')}" for s in ev.mobius.structures[-4:]]
        lines.append(f"openmobius SMC[{ev.mobius.status}]: {structs}")
        actives = [ob for ob in ev.mobius.order_blocks if ob.get("status") == "active"]
        if actives:
            lines.append(f"  active OB: {[(round(o['top'],2), round(o['bottom'],2), o['bias']) for o in actives[:3]]}")
    if ev.indicators is not None:
        i = ev.indicators
        lines.append(f"指标: macd={i.macd_score:+.2f} rsi={i.rsi_score:+.2f} ma={i.ma_score:+.1f} "
                     f"atr={i.atr}")
    if news and news.items:
        lines.append("最近快讯:")
        for it in news.items[:8]:
            lines.append(f"  [{it.ts}] {it.title}")
    return "\n".join(lines)


def build_news_user(news: NewsView) -> str:
    lines = []
    for it in news.items[:15]:
        lines.append(f"[{it.ts}] ({it.level}) {it.title}")
    if not lines:
        lines.append("（无可用快讯）")
    return "\n".join(lines)


class Orchestrator:
    """LLM-A（评审）+ LLM-B（新闻面）并发调度。"""

    def __init__(self, client: RunningHubClient | None = None) -> None:
        self.client = client
        self._last_review_at = 0.0
        self._init_error: str = ""

    def _ensure_client(self) -> bool:
        if self.client is not None:
            return True
        try:
            from gold_agent.llm.client import RunningHubClient
            self.client = RunningHubClient()
            return True
        except Exception as e:
            self._init_error = str(e)
            return False

    async def review_and_news(self, ev: FusedEvidence, news: NewsView,
                              last_close: float, force_review: bool = False) -> dict:
        """返回 {review: dict|None, news_assessment: dict|None}，失败项为 None。"""
        if not self._ensure_client():
            llm_log({"event": "client_init_fail", "error": self._init_error})
            return {"review": None, "news_assessment": None}
        need_review = force_review or (time.time() - self._last_review_at >= CFG.llm.min_interval_min * 60)
        tasks = {}
        if need_review:
            tasks["review"] = asyncio.create_task(self.client.chat_json(
                _REVIEW_SYSTEM, build_review_user(ev, news, last_close),
                REVIEW_SCHEMA, timeout_s=CFG.llm.review_timeout_s))
        tasks["news_assessment"] = asyncio.create_task(self.client.chat_json(
            _NEWS_SYSTEM, build_news_user(news), NEWS_SCHEMA, timeout_s=CFG.llm.news_timeout_s))
        keys = list(tasks)
        results = await asyncio.gather(*[tasks[k] for k in keys], return_exceptions=True)
        out: dict = {k: None for k in keys}
        for k, v in zip(keys, results):
            if isinstance(v, dict):
                out[k] = v
                if k == "review":
                    self._last_review_at = time.time()
            else:
                llm_log({"event": f"{k}_failed", "error": str(v)})
        return out
