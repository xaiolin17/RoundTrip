# 07 — 新闻/消息面接入（news/）

用户要求：每一次分析尽可能带最新消息/财经新闻辅助评判。

> ⚠️ **2026-09-20 修正**（`research/20_llm_audit.txt`）：news 与 review
> **共用预算**导致 review 被挤占（150 次 `budget_exhausted`，
> review 覆盖率被压到 **4.3%**）。现已**分开计账**。见 §5。

## 1. 数据源（优先级）

1. **金十 MCP**（`https://mcp.jin10.com/mcp`，token 在 `.env`）
   - `initialize` → `tools/call`（快讯/日历接口）。
   - 拉最近 30 分钟快讯；关键词分级（宏观/利率/地缘/黄金）。
2. **LLM-B 快评**（`glm-5.3-flash`，结构化输出）
   - 仅当金十失败或需要解读时调用；
   - **system prompt 含禁止编造规则**（`_NEWS_SYSTEM`）：
     只依据给定的快讯标题，不得虚构标题或数据。
3. 均失败 → 本轮无新闻分量（日志记录 `news_assessment_failed`）。

## 2. 处理管线

```
fetch (每轮, 30s TTL 缓存) → 分级打标(规则) →
  LLM-B 快评(与 LLM-A 并发, 独立超时): {sentiment, impact, note, headline_directions} →
  作为**独立贝叶斯证据项**并入融合 + 高危事件表(非农/CPI/FOMC)
```

**新闻分进入融合的方式**：`fuse_all(..., news_score=...)`，
作为一路证据参与加权。⚠️ 它同样受 P0-1 约束 ——
新闻分也要过 `SourceNormalizer` 去均值，否则"长期看多黄金的新闻基调"
会变成又一个结构性偏置源。

## 3. 高危事件行为

- 事件公布前后 15 分钟：禁开仓（`docs/05` 熔断表）。
- 突发 `impact ≥ 0.9`：立即触发持仓紧急评估（不等待常规心跳）。
- `impact ≥ news_impact_close`（默认 0.8，**已走配置**）且与持仓反向 → 平仓评估（`docs/06 §3.2`）。

## 4. 契约

```python
@dataclass
class NewsView:
    items: list[NewsItem]      # {ts, source, title, level, gold_relevant}
    sentiment: str|None        # LLM-B 结论
    impact: float|None         # 0..1
    high_risk_window: bool     # 是否处于高危静默窗口
```

## 5. 预算分离（P0 修正的一部分）

| | 旧 | 新 |
|---|---|---|
| 预算池 | review + news 共用 24/h | `per_hour_budget`（review）与 `news_per_hour_budget`（news）**分开** |
| 挤占 | news 吃满 → review 150 次 `budget_exhausted` | 互不影响 |
| 触顶记录 | 只记 `budget_exhausted` | 记 `budget_exhausted` + `kind` + `used` + `cap`（可审计是哪一类触顶） |

测试：金十真实拉取断言；LLM-B 用真实 key + 真实新闻标题跑通结构化输出（无 mock）。
