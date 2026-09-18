# GoldAgent —  自动交易智能体

> ⚠️ live 模式会对 MT5 账户**真实下单**，市场风险自负。

LangChain + LangGraph 编排的交易智能体：多周期行情 → skill 并发分析 → 数学融合 → 风控门 → MT5 真实下单。

## 启动

```
py main.py
```

- `.env` 中 `TRADE_MODE=live` 即真实下单；`--dry` 演练不下单；`--rounds N` 限轮次

## 日志

`logs/` 下 JSONL：`decision_日期.jsonl`（信号分解 / 决策）、`trades.jsonl`（风控与成交）、`llm_日期.jsonl`、`news_日期.jsonl`。


