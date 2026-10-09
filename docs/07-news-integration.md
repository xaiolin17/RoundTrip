# 07 — 新闻/消息面接入（news/）

用户要求：每一次分析尽可能带最新消息/财经新闻辅助评判。

> ⚠️ **2026-09-20 修正**（`research/20_llm_audit.txt`）：news 与 review
> **共用预算**导致 review 被挤占（150 次 `budget_exhausted`，
> review 覆盖率被压到 **4.3%**）。现已**分开计账**。见 §5。

## 1. 数据源（优先级）

1. **金十 MCP**（`https://mcp.jin10.com/mcp`，token 在 `.env`）
   - `initialize` → `tools/call`（快讯/日历接口）。
   - 拉最近 30 分钟快讯；关键词分级（宏观/利率/地缘/黄金）。
2. **LLM-B 快评**（`deepseek/deepseek-v4.1-flash`，结构化输出，关闭思考）
   - 仅当金十失败或需要解读时调用；
   - **system prompt 含禁止编造规则**（`_NEWS_SYSTEM`）：
     只依据给定的快讯标题，不得虚构标题或数据。
3. 均失败 → 本轮无新闻分量（日志记录 `news_assessment_failed`）。

## 2. 处理管线

```
fetch (每轮, 30s TTL 缓存) → 分级打标(规则) →
  LLM-B 快评(与 LLM-A 并发, 独立超时): {sentiment, impact, note, headline_directions} →
  高危事件表(非农/CPI/FOMC) + 方向冲突闸(见 §2 表格) + 落盘可测量
```

**新闻分不进入融合**（⚠️ 本节曾写"作为一路证据参与加权"，已过时）：
`fuse_all` 的 `news_score` 参数是**已废弃的兼容参数** —— news 无实测 IR，
按 `fusion/weights.py` 的硬规则权重为 0，会被 `gaussian.fuse` 标为 excluded
并排除出加权。实测：`news_score` 取 0 / +1.5 / -1.5，融合分恒为 `+1.438195`，
即那次重融合是**纯空操作**（`graph.py` 里的调用点已注释掉）。
锁住该语义的测试：`test_fusion_replay.py::test_news_score_no_longer_changes_fusion`。

news 的真实权力边界（**用户 2026-10-09 修订**）：

| 影响度 | 行为 |
|---|---|
| `≥ news_impact_block`（0.7）**且与开仓方向冲突** | 不开新仓（等事件过去） |
| `≥ news_impact_block` 且与开仓方向一致 | **放行**（不再一律拦） |
| `≥ news_impact_reduce`（0.4） | 新仓手数 × `news_impact_lot_mult` |
| `≥ news_impact_close`（0.8）且与持仓反向 | 平仓评估 |

用户原话：

> 我觉得新闻事件可以提供做单方向 而不是停止开仓

即 news 拿到**方向上的否决权**（冲突才拦），但仍**不驱动开仓** ——
信号本身 |z| 必须先过 `z_min`，否则新闻无权开仓
（`machine.sentiment_direction` 只做情绪→方向映射，不产生分数）。

⚠️ **可测量性**：新闻结论原先**从未落盘**（`news_*.jsonl` 只有
`{"event":"fetched","count":150}`，LLM 日志只记 `parsed_keys`），
导致"新闻方向准不准"无法回溯。现已由
`orchestrator._log_news_verdict` 写入 `sentiment`/`impact`/`headline_directions`
分布；`research/27_news_direction.py` 负责测量前瞻命中率与 t 值。
⚠️ 金十 `search_flash` **只返回当前快讯、无历史窗口**，故新闻**无法回溯补测**，
只能等实盘积累 assessment 后测量（当前样本为 0，不可结论）。

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
