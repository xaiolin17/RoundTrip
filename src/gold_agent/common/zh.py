# -*- coding: utf-8 -*-
"""中文标签映射：把控制台/日志里的英文枚举翻成中文。

为什么单独成模块：`kind` / `direction` 这些枚举值同时出现在
控制台摘要（`runner._format_summary`）、风控理由（`risk.gate`）
和决策理由（`decision.machine`）三处。若各自硬编码中文，
一旦新增 kind 就会出现"某处显示英文、某处显示中文"的不一致。

⚠️ **GBK 约束**：Windows 控制台默认 GBK。中文本身在 GBK 字符集内，
可以安全使用；但 `✓`(U+2713)、`⛔`(U+26D4) 等符号**不在** GBK 内，
拼接进控制台行会让 `print` 抛 `UnicodeEncodeError`。
实测事故：`✓` 只在执行成功时才拼接 → 进程恰好在**第一次开仓**
那一轮崩溃。所以本模块只提供纯中文标签，不引入装饰性符号。
"""
from __future__ import annotations

#: 提案/动作类型 → 中文
KIND_LABELS: dict[str, str] = {
    "open_market": "市价开仓",
    "place_grid": "挂限价单",
    "add_layer": "顺势加仓",
    "close_position": "平仓",
    "modify_sltp": "移动止损",
    "cancel_pending": "撤销挂单",
    "hold": "观望",
    "skip_round": "跳过本轮",
    "safe_hold": "安全观望",
    "place_pending": "挂限价单",
}

#: 方向 → 中文
DIRECTION_LABELS: dict[str, str] = {
    "LONG": "做多",
    "SHORT": "做空",
}

#: 固定拒绝码 → 中文（`risk.position.position_lots` 等的返回值）
REASON_LABELS: dict[str, str] = {
    "no_atr": "无 ATR 数据",
    "bad_point_value": "点值无效",
    "risk_budget_below_min_lot": "风险预算不足最小手数",
    "grid_layers_empty": "网格层数为空",
    "grid_exposure_cap": "网格总敞口超上限",
}

#: LLM 评审结论 → 中文（用于理由串）
VERDICT_LABELS: dict[str, str] = {
    "bullish": "看多",
    "bearish": "看空",
    "neutral": "中性",
}


def kind_label(kind: str | None) -> str:
    """动作类型的中文名；未知类型原样返回（便于发现新增枚举未登记）。"""
    if not kind:
        return "未知"
    return KIND_LABELS.get(kind, kind)


def direction_label(direction: str | None) -> str:
    """方向的中文名；无方向返回"无"。"""
    if not direction:
        return "无"
    return DIRECTION_LABELS.get(direction, direction)


def reason_label(code: str | None) -> str:
    """固定拒绝码的中文名；未知码原样返回。"""
    if not code:
        return ""
    return REASON_LABELS.get(code, code)


def verdict_label(verdict: str | None) -> str:
    """LLM 结论的中文名；None 显示"未评审"。"""
    if not verdict:
        return "未评审"
    return VERDICT_LABELS.get(verdict, verdict)
