"""LLM 编排：双 skill 评审 + 新闻面（并发，独立超时与降级）。

本模块让 LLM **按标准分析 skill 执行**，而不是自由发挥
------------------------------------------------------------------
两个 vendor skill 都定义了强制流程，旧版 prompt 没有约束 LLM 遵守：

**chanlun-trading-system SKILL.md**
- 「严格原文自检门」8 门：level / structure / type / comparison / buy_sell /
  trigger / risk / downgrade
- 「输出模板」四段：级别 / 结构 / 信号 / 动作（动作须含 basis/trigger/
  invalidation/next watch）
- 不可妥协规则 5：「每个入场都要写明：依据、触发、失效点、下一个观察点」
- 不可妥协规则 6：MACD/RSI/量等过滤器**只调整信心/等待纪律/仓位**，
  **不定义缠论买卖点**
- 禁止的捷径：指标背离→一买；突破→无回抽的三买；更高的低点→无一买上下文的二买
- 三种运行模式必须**先声明用的是哪种**（strict_chanlun / structure_proxy /
  proxy_research），并如实标注"近似损失"

**openmobius-skill SKILL.md**
- 「SMC field semantics」7 步咨询顺序：① swing vs internal trend bias
  ② 最近结构事件（**CHoCH 优先级高于 BOS**）③ trailing extremes 的 Strong/Weak 标签
  ④ active Order Blocks ⑤ active FVG ⑥ equal highs/lows ⑦ premium/equilibrium/
  discount 位置
- 「Caveats」必须披露：swing pivot 确认延迟约 50 根、OB 会被后续 bar 修订、
  低波动 regime 下 FVG 频发、**结构信号不是入场触发器**
- 共享规则 2：每个确认的形态必须引用检索到的规则
- 共享规则 4：不确定时明确说"uncertain — <原因>"，不猜测
- 共享规则 6：概率档位 5 级（very_high/high/medium/low/very_low），
  **不向用户暴露内部百分比**

本模块的 prompt 把这些流程写进 system message，并要求 LLM 在 rationale 中
**逐步走完**对应 skill 的检查项；输出 JSON schema 相应扩展了 `skill_audit` 字段。

降级（docs/03 §3 不变）
-----------------------
失败/JSON 解析失败 → 重试 1 次（换温度 0）→ 仍失败 → 该轮 LLM 分量记 0，
本地融合照常决策。**绝不**同步等待 LLM 阻塞主循环；LLM 结果永不直接生成订单参数。
"""
from __future__ import annotations

import asyncio
import time

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import llm_log
from gold_agent.fusion.engine import FusedEvidence
from gold_agent.llm.client import NEWS_SCHEMA, REVIEW_SCHEMA, RunningHubClient
from gold_agent.news.collector import NewsView

# ---------------------------------------------------------------------------
# LLM-A：双 skill 分析评审
# ---------------------------------------------------------------------------
_REVIEW_SYSTEM = """你是资深黄金（XAUUSD）交易评审员，同时执行两个标准分析 skill。
你必须**严格按 skill 规定的流程**分析，不得跳步、不得用捷径。

═══ 必须遵守的通用纪律 ═══
- 只允许引用输入中出现的数字/价位，**禁止编造价格**或"预测未来"。
- 不确定时明确写 "uncertain — <原因>"，不要猜测（openmobius 共享规则 4）。
- 不要输出交易手数或下单指令（架构规则：订单参数只出自 risk 模块）。
- confidence < 0.4 时 verdict 必须为 neutral。

═══ Skill 1: chanlun-trading-system ═══
必须走完「严格原文自检门」并在 skill_audit.chanlun_gates 中逐门回答：
1. level_gate       —— 点名 trade_level / confirm_level / trigger_level（输入已给）
2. structure_gate   —— 引用「包含→分型→笔→线段→中枢」链的产物数量
3. type_gate        —— 归类：趋势/盘整/中枢延伸/中枢突破/转折/不明
4. comparison_gate  —— 若用背驰，**必须点名被比较的两段同向走势**并确认同级别；
                       没有背驰就写 "not_used"
5. buy_sell_gate    —— 只有上述门通过后，才可映射到一/二/三类买卖点
6. trigger_gate     —— 低级别触发是否存在；缺失就写 "trigger_missing"
7. risk_gate        —— **先写失效点**，再谈收益
8. downgrade_gate   —— 任一门不过 → 输出 observe/proxy_research，**不得**说 buy_confirmed

不可妥协规则（违反即为分析无效）：
- 规则 6：MACD/RSI/量/均线等过滤器**只调整信心、等待纪律或仓位**，
  **绝不定义缠论买卖点**。禁止"MACD 底背离 → 一买"。
- 规则 11：没点名"前一个同级别趋势"或"下跌+中枢+下跌"上下文、
  没识别被比较的同向走势之前，**不喊一买/一卖**。
- 规则 12：没点名"一买候选 + 它的第一次回抽测试"之前，**不喊二买/二卖**。
- 规则 13：没点名"中枢边界、离开、回拉、不回/再入"全部状态之前，**不喊三买/三卖**。
- 必须声明运行模式：strict_chanlun / structure_proxy / proxy_research，
  并如实标注近似损失（输入里的 definition_mode / approximation_loss）。

═══ Skill 2: openmobius-skill（ICT/SMC）═══
必须按「SMC field semantics」的 **7 步咨询顺序**分析，
在 skill_audit.smc_steps 中逐步回答：
1. swing_trend vs internal_trend：同号=强趋势，异号=潜在反转或区间
2. 最近结构事件是 BOS（延续）还是 CHoCH（反转）——
   **CHoCH 作为前瞻信号优先级高于 BOS**
3. trailing extremes 的 Strong/Weak 标签：
   Strong High + Weak Low = 确认看跌结构；Strong Low + Weak High = 确认看涨
4. active Order Blocks：bull OB 在价格下方=支撑候选；bear OB 在上方=阻力候选；
   离现价越近越相关
5. active Fair Value Gaps（三根 bar 的不平衡区，价格倾向回补）
6. equal highs / equal lows：止损簇流动性，聪明钱常在反转前扫掉
7. 现价在 premium / equilibrium / discount 哪一区：
   bull 有利入场在 discount，short 有利入场在 premium，equilibrium 观望

必须披露的 caveats（openmobius 规定）：
- swing pivot 只在形成后约 50 根才确认，近期 pivot 可能仍会调整
- Order Block 是事后反推的，新形成的 OB 可能被后续 bar 修订
- 低波动 regime 下 FVG 触发频繁，需谨慎对待 FVG 数量
- **所有事件都是结构信号，不是入场触发器**；它们补充但不替代风控

概率档位只用这 5 个词，**不要暴露内部百分比**：
very_high / high / medium / low / very_low

═══ 压力位/支撑位（决定止损止盈，必须认真给）═══
止损止盈**看压力位/支撑位**，不看 ATR。你必须基于上面两个 skill 的输出，
显式给出价位（只允许引用输入里出现过的数字，或由它们直接推得的价位）：

- `support_levels`：**支撑位**列表，按离现价从近到远排。
  来源优先级：SMC bull Order Block 下沿 > bull FVG 下沿 > equal lows
  > 缠论中枢 zd/dd。
- `resistance_levels`：**压力位**列表，同样从近到远。
  来源优先级：SMC bear Order Block 上沿 > bear FVG 上沿 > equal highs
  > 缠论中枢 zg/gg。
- `sl_hint` / `tp_hint`：你认为最合适的止损/止盈价（可选，但强烈建议给）。
- `level_reason`：一句话说明这些位是怎么选出来的（点名用了哪个 skill 的哪一步）。

⚠️ 你的输出是**位置建议**，不是订单指令。本地风控会据此配套计算最终
sl/tp 并做方向、最小距离、盈亏比校验；你**不要**输出手数。

═══ 输出 ═══
严格 JSON（structuredOutputs）：
{"verdict":"bullish|bearish|neutral",
 "confidence":0..1,
 "rationale":"...",
 "skill_audit":{
   "chanlun_mode":"strict_chanlun|structure_proxy|proxy_research|not_used",
   "chanlun_gates":{"level_gate":"...","structure_gate":"...","type_gate":"...",
                    "comparison_gate":"...","buy_sell_gate":"...","trigger_gate":"...",
                    "risk_gate":"...","downgrade_gate":"..."},
   "smc_steps":{"trend_bias":"...","last_event":"...","extremes":"...",
                "order_blocks":"...","fvg":"...","equal_hl":"...","zone":"..."},
   "probability_tier":"very_high|high|medium|low|very_low",
   "caveats_disclosed":true|false},
 "support_levels":[数字...],
 "resistance_levels":[数字...],
 "sl_hint":数字,
 "tp_hint":数字,
 "level_reason":"...",
 "key_levels":[...],
 "risk_flags":[...],
 "invalidation":"...",
 "next_observation":"..."}
rationale 必须说明你**依据的是哪个 skill 的哪一步**，以及哪些步骤缺失/降级。
"""

_NEWS_SYSTEM = """你是财经新闻分析师。给你一组最近黄金市场相关快讯。

输出严格 JSON：
{"sentiment":"bullish|bearish|neutral",
 "impact":0..1,
 "note":"一句话",
 "headline_directions":["bullish|bearish|neutral", ...]}

impact 表示对金价短期方向的影响强度；不确定时低分。
**不要编造新闻标题之外的信息**（openmobius 无编造原则）。
若快讯为空或与黄金无关，sentiment 必须为 neutral 且 impact 为 0。"""


def _fmt_num(x, nd: int = 2) -> str:
    try:
        return f"{float(x):.{nd}f}"
    except Exception:
        return str(x)


def build_review_user(ev: FusedEvidence, news: NewsView | None, last_close: float) -> str:
    """构造评审输入：按 skill 要求的字段组织，并**显式标注缺失项**。

    SKILL.md 要求"点名缺了哪一步结构"之后才降级 —— 所以缺失必须写进输入，
    让 LLM 有能力执行 downgrade_gate，而不是靠猜。
    """
    lines = [f"当前价: {_fmt_num(last_close)}"]
    r = ev.result
    lines.append(
        f"融合分数 S={r.score:+.2f}（零点校正后 S_eff="
        f"{r.score - r.score_baseline:+.2f}，滚动基线 S0={r.score_baseline:+.2f}）"
        f" sigma={r.sigma:.2f} regime={r.regime} hurst={r.hurst} "
        f"分歧={r.disagreement} 波动分位={r.vol_percentile:.2f}")

    # ---- 源权重透明度（哪些源被排除、为什么）----
    lines.append("信号源（weight=实测 IR² 权重，0 = 未验证不参与方向）:")
    for s in r.per_source:
        lines.append(
            f"  源 {s['name']}: score={s.get('score')} "
            f"raw={s.get('raw_score')} sigma={s.get('sigma')} "
            f"status={s['status']} bayes={s.get('bayes')} "
            f"w={s.get('w')} ir={s.get('ir')}"
            + (f" [{s['excluded']}]" if s.get("excluded") else ""))

    # ---- Skill 1 输入：缠论（按输出模板组织）----
    lines.append("")
    lines.append("═══ Skill 1 输入: chanlun-trading-system ═══")
    if not ev.chanlun:
        lines.append("  （无缠论结果 → chanlun_mode 应为 not_used）")
    for tf, cr in ev.chanlun.items():
        if cr.status != "ok":
            lines.append(f"chanlun[{tf}]: status={cr.status} error={cr.error}")
            continue
        a = cr.audit
        lines.append(f"chanlun[{tf}]: structure={cr.structure} score={cr.score:+.2f}")
        lines.append(f"  级别: {cr.levels}")
        lines.append(f"  definition_mode={cr.definition_mode} "
                     f"audit.output_mode={a.output_mode}")
        lines.append(f"  结构链: {a.chain}")
        lines.append(f"  自检门未过: {a.failed or '（全部通过）'}")
        if a.notes:
            lines.append(f"  自检备注: {a.notes}")
        if a.compared_movements:
            lines.append(f"  背驰比较的两段: {a.compared_movements}")
        if cr.center:
            c = cr.center
            lines.append(f"  当前中枢 {c.get('id')}: zg={c.get('zg')} zd={c.get('zd')} "
                         f"gg={c.get('gg')} dd={c.get('dd')} "
                         f"definition={c.get('definition_mode')}")
        if cr.approximation_loss:
            lines.append(f"  近似损失(approximation_loss): {cr.approximation_loss[:3]}")
        lines.append(f"  失效点(invalidation): {cr.invalidation}")
        lines.append(f"  下一观察点: {cr.next_observation}")
        if cr.confirmed_signals:
            lines.append(f"  ✅ 已确认买卖点（过了规则 11/12/13）: "
                         f"{[(s.get('kind'), s.get('price')) for s in cr.confirmed_signals]}")
        if cr.observed_signals:
            lines.append(f"  ⚠️ 降级为 observe（未过门）: "
                         f"{[(s.get('kind'), s.get('audit_reason')) for s in cr.observed_signals]}")

    # ---- Skill 2 输入：SMC（按 7 步咨询顺序组织）----
    lines.append("")
    lines.append("═══ Skill 2 输入: openmobius-skill（ICT/SMC，按 7 步顺序）═══")
    mob_items = (ev.mobius.items() if isinstance(ev.mobius, dict)
                 else ((("15m", ev.mobius),) if ev.mobius is not None else ()))
    any_mob = False
    for tf, mr in mob_items:
        if mr is None or mr.status == "unavailable":
            lines.append(f"openmobius[{tf}]: status=unavailable error={mr.error if mr else ''}")
            continue
        any_mob = True
        sb, ib = mr.trend_bias()
        top_lbl, bot_lbl = mr.extreme_labels()
        zone = mr.zone_of(last_close)
        lines.append(f"openmobius[{tf}][{mr.status}] 价格={_fmt_num(mr.current_price)} "
                     f"数据年龄={_fmt_num(mr.last_bar_age_s, 0)}s stale={mr.stale}")
        lines.append(f"  ① trend bias: swing={sb:+d} internal={ib:+d} "
                     f"({'强趋势' if sb == ib and sb != 0 else '潜在反转/区间' if sb != ib else '中性'})")
        ev_last = mr.last_swing_event
        iv_last = mr.last_internal_event
        lines.append(f"  ② 最近结构事件: swing={ev_last} | internal={iv_last} "
                     f"（CHoCH 优先级高于 BOS）")
        lines.append(f"  ③ trailing extremes: top={top_lbl} bottom={bot_lbl}")
        active_ob = mr.active_order_blocks("swing")
        lines.append(f"  ④ active swing OB x{len(active_ob)}: "
                     f"{[( _fmt_num(o.get('bottom')), _fmt_num(o.get('top')), o.get('bias')) for o in active_ob[-3:]]}")
        active_fvg = mr.active_fvgs()
        lines.append(f"  ⑤ active FVG x{len(active_fvg)}: "
                     f"{[(_fmt_num(f.get('bottom')), _fmt_num(f.get('top')), f.get('bias')) for f in active_fvg[-3:]]}")
        lines.append(f"  ⑥ equal highs x{len(mr.equal_highs)} equal lows x{len(mr.equal_lows)}: "
                     f"EH={[_fmt_num(e.get('level')) for e in mr.equal_highs[-2:]]} "
                     f"EL={[_fmt_num(e.get('level')) for e in mr.equal_lows[-2:]]}")
        lines.append(f"  ⑦ zone: 现价在 {zone} 区 "
                     f"(premium={mr.premium_zone} equilibrium={mr.equilibrium_zone} "
                     f"discount={mr.discount_zone})")
        alerts = {k: v for k, v in (mr.alerts_last_bar or {}).items() if v}
        if alerts:
            lines.append(f"  最近一根触发的告警: {list(alerts)}")
    if not any_mob:
        lines.append("  （无可用 SMC 结构 → smc_steps 应为 uncertain）")

    # ---- 经典指标（仅作过滤器，不定义买卖点）----
    if ev.indicators is not None:
        i = ev.indicators
        lines.append("")
        lines.append("过滤器（规则 6：只调整信心/仓位，**不定义买卖点**）:")
        lines.append(f"  加速度={i.momentum_accel:+.2f} tick买盘={i.tick_imbalance:+.2f} "
                     f"量价压力={i.vol_pressure:+.2f} 收缩={i.range_compression:+.2f} "
                     f"atr={i.atr} 日波动={i.realized_vol_daily}")

    if news and news.items:
        lines.append("")
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
    """LLM-A（评审）+ LLM-B（新闻面）并发调度。

    research/20 的修正：review 与 news **分开计账预算**，且 1h 决策周期下
    `min_interval_min=0` —— 每轮都评审。这使 LLM 从"4.3% 覆盖率的罕见加分项"
    变成主路径的确认环节。
    """

    def __init__(self, client: RunningHubClient | None = None) -> None:
        self.client = client
        self._last_review_at = 0.0
        self._init_error: str = ""
        self.review_calls = 0
        self.review_failures = 0

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
                REVIEW_SCHEMA, timeout_s=CFG.llm.review_timeout_s, kind="review"))
        tasks["news_assessment"] = asyncio.create_task(self.client.chat_json(
            _NEWS_SYSTEM, build_news_user(news), NEWS_SCHEMA,
            timeout_s=CFG.llm.news_timeout_s, kind="news"))
        keys = list(tasks)
        results = await asyncio.gather(*[tasks[k] for k in keys], return_exceptions=True)
        out: dict = {k: None for k in keys}
        for k, v in zip(keys, results):
            if isinstance(v, dict):
                out[k] = v
                if k == "review":
                    self._last_review_at = time.time()
                    self.review_calls += 1
            else:
                if k == "review":
                    self.review_failures += 1
                llm_log({"event": f"{k}_failed", "error": str(v)})
        return out

    # ---------- 覆盖率诊断（research/20 的验收指标） ----------
    @property
    def review_coverage(self) -> float:
        total = self.review_calls + self.review_failures
        return self.review_calls / total if total else 0.0
