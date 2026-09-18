# GoldAgent — XAUUSDm 自动交易智能体（D:\RoundTrip）

> ⚠️ **风险声明**：本项目会对 MT5 账户**真实下单**（live 模式）。所有分析、仓位与风控均尽力工程化，但市场风险无法消除，盈亏自负。

## 目标

构建一个以 LangChain 1.2 + LangGraph 编排的黄金交易智能体：

1. **数据**：本机 MetaTrader5（`D:\MT5\terminal64.exe`）获取 XAUUSDm 的 1m/2m/5m/10m/15m/30m/1h/4h/8h/1d 多周期 OHLCV 与指标；Mobius Quant API（openmobius skill）作为交叉校验源（1m/5m/15m/30m/1h/4h/1d，匿名限速 10 req/min）。
2. **分析**：两个 skill **并发**调用
   - `vendor/skills/openmobius-skill`（ICT/SMC 结构信号，走 Mobius API + 知识库）
   - `vendor/skills/chanlun-trading-system`（分型/笔/线段/中枢/背驰，纯本地确定性引擎）
   - 加上本地数学融合（卡尔曼滤波、贝叶斯模型平均、高斯加权融合）
3. **新闻面**：金十 MCP 快讯（token 已有）+ 带 webSearch 的备用 LLM 模型，为每次分析提供实时消息面辅助。
4. **决策**：LangGraph 状态机定义当前行为（持仓→评判是否主动平仓；空仓→是否多/空开仓；支持有限网格与反向马丁，带硬性熔断）。
5. **执行**：MT5 真实下单（live，最小手数起步，硬风控兜底）。

## 目录

```
docs/           AI 开发与分析文档（先写后建）— 必读顺序 00→08
vendor/skills/  两个 skill 的副本（copy，勿删原位置）
src/gold_agent/ 源码
  mt5/          MT5 适配（行情/持仓/下单，asyncio 包装）
  skills/       openmobius(限速+缓存) 与 chanlun 引擎适配
  llm/          runninghub OpenAI 兼容客户端、并发调度
  news/         金十快讯 + webSearch 新闻面
  fusion/       卡尔曼 / 贝叶斯 / 高斯融合
  risk/         仓位（Half-Kelly、波动率目标、ATR 风险预算）、网格马丁、熔断
  decision/     状态机与行动定义
  agent/        LangChain 1.2 agent + LangGraph 编排
  common/       配置、日志、类型
tests/          真实数据测试（无 mock）
data/cache/     行情缓存（parquet）
logs/           运行日志（JSONL）
```

## 快速开始

```powershell
py -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env   # 填入 RUNNINGHUB_API_KEY
py -m gold_agent.mt5.doctor   # MT5 连接与账户体检
py -m gold_agent.runner       # 主循环
```

## 硬性规则（来自用户需求）

- 耗时的 LLM 并发/算法分析**异步执行**，不同步等待主循环。
- 不使用模拟数据；测试全部基于真实行情（parquet 历史 + MT5 实时）。
- 先 docs（交互逻辑与数据契约）→ 再模块 → 再测试。
- LLM 超时/失败自动降级为本地融合结果，绝不死等。
- live 下单前必须通过风控门（总敞口、连亏熔断、单笔风险预算）。
