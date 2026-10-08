# 03 — LLM 编排（llm/）

> ⚠️ **2026-09-20 重大修正**（`research/20_llm_audit.txt` + `research/18_COMMERCIAL_PLAN.md`）：
> 旧架构下 **LLM 在实盘中几乎不参与决策**（review 覆盖率仅 **4.3%**）。
> 现已把 LLM 移到**主路径**，并强制它**按标准 skill 流程执行**。见 §0。

## 0. 修正：LLM 从「罕见加分项」到「主路径确认环节」

### 问题（research/20_llm_audit.txt，881 轮实盘日志）

```
chat_ok                          304   40.7%
news_assessment_failed           152   20.3%
budget_exhausted                 150   20.1%   ← 超出每小时预算被拒
review_failed                    126   16.9%
chat_error                        15    2.0%

LLM review 成功次数 = 38  →  覆盖率 4.3%
```

**根因有三**：
1. `min_interval_min = 15` 分钟节流（60s 循环下理论覆盖率上限 6.7%）
2. `per_hour_budget = 24` 被 news 挤占（review 与 news 共用预算池）
3. `need_llm = |S| >= 0.9` 的前置条件

**后果**：`decision/machine.py` 的 `_decide_flat` 里
`aligned = (verdict == 方向) and conf >= 0.6`；LLM 未调用时 `verdict = None`
→ `aligned = False` → **永远走 place_grid，永远不会市价开仓**。

实测决策类型分布完全吻合：`place_grid = 30` vs `open_market = 16`。
**系统绝大多数时候只能挂限价单，不是用户以为的「LLM 主导决策」。**

### 修法

| 项 | 旧 | 新 |
|---|---|---|
| 评审间隔 | `min_interval_min = 15` | **`0`**（**1m 决策周期**下每轮都评审） |
| 预算 | review+news 共用 24/h | **分离计账**：`per_hour_budget` / `news_per_hour_budget` |
| 触发条件 | `\|S\| >= 0.9` 或持仓 | `\|S_eff\| >= thr−0.6` 或持仓或挂单或 `\|S0\|>0.3` |
| LLM 缺失时 | 默认 `place_grid` | `allow_grid_without_llm=false` → **hold**，等明确表态 |
| 失败重试 | 无 | 重试 `llm.retry` 次（换温度 0） |

**LLM 获得实质权力**：`_decide_flat` 中 `opposed`（verdict 与信号反向且
`conf >= llm_adverse_conf`）→ **直接 hold，不开仓**。这不再是"加分项"，
而是确认环节。

> ⚠️ 这只是**单轮否决**，不要读成"系统总体不开仓"：
> 决策周期为 **1m（60s）**，每轮都重新评审；LLM 不反对时正常走
> `open_market` / `place_grid`。预热 + 权重表修好后实测
> **58% 的轮次产出 `place_grid`**（见 `docs/08 §5`）。
> 真正会让系统"永不开仓"的是另外两件事（都已修）：权重全 0、
> 归一化器未预热 —— 那**不是** LLM 的否决。

### 覆盖率诊断

`Orchestrator.review_coverage` 暴露实测覆盖率，并落 `decision_log` 的
`llm_review` 事件（含 `available` 字段）—— 用于验证修正是否生效。

---

## 1. Provider 配置

- 端点：`RUNNINGHUB_BASE_URL=https://llm.runninghub.cn/v1`（OpenAI 兼容，实测 `/v1/models` 可用）。
- 主模型：`deepseek/deepseek-v4.1-flash`，**关闭思考模式**
  （`RUNNINGHUB_REASONING_EFFORT=none`；界面上叫 off，线上传 `"off"` 会 400）。
  ⚠️ 原用 `glm/glm-5.3-flash` —— 该模型强制思考且无法关闭，实测白天 review
  中位 **60.7 秒**超时、成功率仅 **22.9%**，每轮因此多耗约 120 秒等超时。
  留空该环境变量 = 不带参数 = 模型默认 = **开启思考**，所以必须显式设 `none`。
- Key：`.env` `RUNNINGHUB_API_KEY`（用户写入）。

## 2. 两类 LLM 任务（并发、互不阻塞、独立预算）

### LLM-A：双 skill 分析评审（**按 skill 流程执行**）

输入按两个 vendor skill 的契约组织（`build_review_user`），
**并显式标注缺失项**（SKILL.md 要求"点名缺了哪一步结构"之后才降级）：

- **Skill 1 输入**（chanlun-trading-system）：级别链、`definition_mode`、
  `audit.output_mode`、结构链产物数量、8 门自检未过项、背驰比较的两段、
  中枢 zg/zd/gg/dd、`approximation_loss`、失效点、下一观察点、
  **已确认买卖点 vs 降级为 observe 的信号（含降级原因）**
- **Skill 2 输入**（openmobius-skill）：严格按「SMC field semantics」**7 步顺序**
  组织 —— ① swing/internal trend bias ② 最近结构事件（标注 CHoCH 优先级）
  ③ trailing extremes 的 Strong/Weak 标签 ④ active OB ⑤ active FVG
  ⑥ equal highs/lows ⑦ premium/equilibrium/discount 位置
- **过滤器**（经典指标）：显式标注"只调整信心/仓位，**不定义买卖点**"（规则 6）

**System prompt 强制 skill 流程**（`_REVIEW_SYSTEM`）：

- chanlun 的 8 门自检必须**逐门回答**（`skill_audit.chanlun_gates`）
- 不可妥协规则 6/11/12/13 原文写入 prompt（禁止"MACD 背离→一买"等捷径）
- SMC 的 7 步必须**逐步回答**（`skill_audit.smc_steps`）
- 必须披露 openmobius 的 caveats（pivot 确认延迟 ~50 根、OB 事后修订、
  低波动 FVG 频发、**结构信号不是入场触发器**）
- 概率档位只用 5 个词（very_high/high/medium/low/very_low），**不暴露内部百分比**
- 必须声明 chanlun 运行模式（strict_chanlun / structure_proxy / proxy_research）

输出 JSON（structuredOutputs）：
```json
{"verdict":"bullish|bearish|neutral", "confidence":0..1, "rationale":"...",
 "skill_audit":{"chanlun_mode":"...","chanlun_gates":{...},"smc_steps":{...},
                "probability_tier":"...","caveats_disclosed":true},
 "key_levels":[...], "risk_flags":[...], "invalidation":"...", "next_observation":"..."}
```
禁止输出手数/直接下单指令（架构规则）。

### LLM-B：新闻/消息面

- 数据源：金十 MCP 快讯（token 现成）。
- 输出 JSON：`{sentiment, impact, note, headline_directions}`。
- 影响：**不进入融合**（news 无实测 IR，权重恒 0，见
  `fusion/engine.py` 的显式排除与 `fusion/weights.py` 的等权先验跳过）。
  它走「独立证据」通道，只影响"要不要开、开多大"；
  `impact >= news_impact_close`（默认 0.8）且与持仓反向 → 紧急平仓评估。
- **独立预算**（`news_per_hour_budget`），不再挤占 review 额度。

## 3. 并发与降级

- LLM-A 与 LLM-B `asyncio.gather` 并发；各 `review_timeout_s` / `news_timeout_s` 超时。
- 失败/JSON 解析失败 → 重试 `llm.retry` 次（换温度 0）→ 仍失败 → 该轮 LLM 分量记 0，
  本地融合照常决策。
- **绝不**：同步等待 LLM 阻塞主循环；LLM 结果永不直接生成订单参数。

## 4. 成本与预算

- `config.toml [llm]`：`per_hour_budget`（review）、`news_per_hour_budget`（news）**分开计账**。
- 触顶 → 仅本地决策并记录 `budget_exhausted`（含 `kind` / `used` / `cap`）。
- 所有 prompt/响应完整存 `logs/llm_YYYYMMDD.jsonl`；
  skill 合规审计存 `logs/decision_*.jsonl` 的 `llm_review` 事件。

## 5. 结构化输出策略

- 优先 `structuredOutputs`；fallback：`response_format={"type":"json_object"}`
  → 仍失败用平衡括号提取首个 JSON 对象 → 再失败视为解析失败。
- required 字段缺失视为失败并触发重试（`schema_incomplete` 事件）。
