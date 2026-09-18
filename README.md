# GoldAgent — XAUUSDm 自动交易智能体

> ⚠️ live 模式会对 MT5 账户**真实下单**，市场风险自负。

LangChain + LangGraph 编排的黄金交易智能体：MT5 多周期行情 → 双 skill 并发分析 → 数学融合 → 风控门 → MT5 真实下单。

## 启动

```
py main.py
```

- `.env` 中 `TRADE_MODE=live` 即真实下单；`--dry` 演练不下单；`--rounds N` 限轮次
- 首次使用先体检：`py -m gold_agent.mt5.doctor`

## 日志

`logs/` 下 JSONL：`decision_日期.jsonl`（信号分解 / 决策）、`trades.jsonl`（风控与成交）、`llm_日期.jsonl`、`news_日期.jsonl`。

## 详细设计

见 `docs/00-architecture.md`（必读）→ 01–08：MT5 适配、skill 接入、LLM 编排、信号融合、仓位风控、决策状态机、新闻面、测试计划。
