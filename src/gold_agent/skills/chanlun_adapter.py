"""chanlun-trading-system skill 适配器（docs/02 §1）。

本地确定性引擎，vendor/skills/chanlun-trading-system/src 注入 path 后
直接 import chanlun_visual.engine.analyze。

本适配器实现 SKILL.md 的**严格原文自检门（Strict Original Audit Gate）**
--------------------------------------------------------------------
SKILL.md 规定"任何操作性结论之前，过这道门"，共 8 门：

1. `level_gate`     —— 点名 review_level / trade_level / confirm_level / trigger_level
2. `structure_gate` —— 按「包含 → 分型 → 笔 → 线段 → 中枢」顺序构建或引用
3. `type_gate`      —— 归类为 趋势/盘整/中枢延伸/中枢突破/转折/不明
4. `comparison_gate`—— 用背驰时必须点名被比较的两段同向走势，并确认同级别
5. `buy_sell_gate`  —— 上述门通过后，才把结构映射到一/二/三类买卖点
6. `trigger_gate`   —— 要求低级别触发，或显式标注 `trigger_missing`
7. `risk_gate`      —— 先写失效点，再谈收益
8. `downgrade_gate` —— 任一门不过，输出 `proxy_research` 或 `observe`

**被禁止的捷径**（SKILL.md 原文）：指标背离→一买；突破→无回抽的三买；
更高的低点→无一买上下文的二买；30 分钟均线/MACD 状态→当成 30 分钟结构。

不可妥协规则 11/12/13 直接约束打分：
- 规则 11：没点名"前一个同级别趋势"或"下跌+中枢+下跌"的上下文、
  没识别被比较的同向走势之前，**不喊一买/一卖**
- 规则 12：没点名"一买候选 + 它的第一次回抽测试"之前，**不喊二买/二卖**
- 规则 13：没点名"中枢边界、离开、回拉、不回/再入"全部状态之前，**不喊三买/三卖**

旧版适配器直接把 `*_candidate` 映射成 ±1/±2/±3（仅乘 0.6 降权），
**完全跳过了这些门** —— 这是对 skill 契约的违反。本版把未过门的一律降为
`observe`（score 贡献 0），只有过门的候选才计分。
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from gold_agent.common.config import CFG

_VENDOR_SRC = CFG.vendor_dir / "skills" / "chanlun-trading-system" / "src"
if str(_VENDOR_SRC) not in sys.path:
    sys.path.insert(0, str(_VENDOR_SRC))

try:
    from chanlun_visual.engine import analyze as _chanlun_analyze
    CHANLUN_AVAILABLE = True
    _IMPORT_ERROR = ""
except Exception as _e:  # pragma: no cover
    CHANLUN_AVAILABLE = False
    _IMPORT_ERROR = str(_e)

# 结构 → 分数映射（docs/02 §4）。买卖点分数在通过 audit gate 后才生效。
_STRUCTURE_SCORE = {
    "trend_up": 1.0,
    "trend_down": -1.0,
    "center_oscillation": 0.0,
    "center_extension": 0.0,
    "center_breakout": 0.5,   # 方向由 breakout 方向细化
    "transition_zhongyin": 0.0,
    "insufficient_history": 0.0,
    "unknown": 0.0,
}
_SIGNAL_SCORE = {"B1": 1.0, "B2": 2.0, "B3": 3.0, "S1": -1.0, "S2": -2.0, "S3": -3.0}

#: 级别链（SKILL.md 工作流第 1 步）。1h 决策周期下的短线级别链：
#: trade=4h（方向） / confirm=1h（确认） / trigger=15m（触发）
DEFAULT_LEVEL_CHAIN = {"review_level": "4h", "trade_level": "4h",
                       "confirm_level": "1h", "trigger_level": "15m"}

#: 引擎输出的 definition_mode 与我们要求的 mode 的对应（SKILL.md 三种运行模式）
_MODE_ALIASES = {
    "strict_chanlun": "strict_chanlun",
    "structure_proxy": "structure_proxy",
    "segment_proxy": "structure_proxy",
    "research_proxy": "proxy_research",
    "swing_proxy": "proxy_research",
    "indicator_proxy": "proxy_research",
}


@dataclass
class AuditGate:
    """8 门自检结果（SKILL.md「严格原文自检门」）。"""
    level_gate: bool = False
    structure_gate: bool = False
    type_gate: bool = False
    comparison_gate: bool = False
    buy_sell_gate: bool = False
    trigger_gate: bool = False
    risk_gate: bool = False
    downgrade_gate: bool = True
    #: 未过的门名列表
    failed: list[str] = field(default_factory=list)
    #: 降级后的输出模式：strict_chanlun | structure_proxy | proxy_research | observe
    output_mode: str = "observe"
    #: 结构链完整性（包含→分型→笔→线段→中枢）
    chain: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return not self.failed

    def to_dict(self) -> dict:
        return {"gates": {"level": self.level_gate, "structure": self.structure_gate,
                          "type": self.type_gate, "comparison": self.comparison_gate,
                          "buy_sell": self.buy_sell_gate, "trigger": self.trigger_gate,
                          "risk": self.risk_gate, "downgrade": self.downgrade_gate},
                "failed": self.failed, "output_mode": self.output_mode,
                "chain": self.chain, "notes": self.notes}


@dataclass
class ChanlunResult:
    status: str = "unavailable"          # ok | unavailable | bad_input
    structure: str | None = None
    score: float = 0.0
    signals: list[dict] = field(default_factory=list)
    center: dict | None = None
    invalidation: str | None = None
    quality: dict = field(default_factory=dict)
    definition_mode: str = "research_proxy"
    raw: dict = field(default_factory=dict)
    error: str = ""
    computed_at: float = 0.0
    # ---- SKILL.md 契约字段 ----
    #: 级别链（level_gate）
    levels: dict = field(default_factory=lambda: dict(DEFAULT_LEVEL_CHAIN))
    #: 8 门自检结果
    audit: AuditGate = field(default_factory=AuditGate)
    #: 通过门、被计分的信号
    confirmed_signals: list[dict] = field(default_factory=list)
    #: 未过门、降级为 observe 的信号（不计分）
    observed_signals: list[dict] = field(default_factory=list)
    #: 背驰比较的两段（comparison_gate）
    compared_movements: list[str] = field(default_factory=list)
    #: 下一观察点（SKILL.md 第 5 步动作要求）
    next_observation: str | None = None
    #: 代理近似损失（必须如实标注，SKILL.md 规则 7）
    approximation_loss: list[str] = field(default_factory=list)


def df_to_bars(df: pd.DataFrame) -> list[dict]:
    """MT5 DataFrame → chanlun 引擎 bars（时间严格递增、UTC ISO）。

    支持两种形态：time 为列（MT5 collector 输出）或 time 为索引（回放/重采样）。
    """
    out = []
    has_time_col = "time" in df.columns
    for idx, r in df.iterrows():
        ts = r["time"] if has_time_col else idx
        out.append({
            "date": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": float(r["close"]),
            "volume": float(r.get("tick_volume", 0) or r.get("volume", 0) or 0),
        })
    return out


# ---------------------------------------------------------------------------
# 严格原文自检门
# ---------------------------------------------------------------------------
def _audit_gates(raw: dict, structure: str | None, signals: list[dict],
                 center: dict | None, center_raw: dict | None,
                 levels: dict, close: float) -> AuditGate:
    """执行 SKILL.md 的 8 门自检。

    每门对应 SKILL.md 的明文要求；未过的门进入 `failed`，
    并在 `downgrade_gate` 中决定输出模式（绝不输出 buy_confirmed）。
    """
    g = AuditGate()
    layers = raw.get("layers", {}) or {}
    meta = raw.get("meta", {}) or {}
    divergences = layers.get("divergences", []) or []

    # ---- 1) level_gate：点名 trade/confirm/trigger 级别 ----
    g.level_gate = all(levels.get(k) for k in ("trade_level", "confirm_level", "trigger_level"))
    if not g.level_gate:
        g.failed.append("level_gate")

    # ---- 2) structure_gate：包含 → 分型 → 笔 → 线段 → 中枢 ----
    g.chain = {"merged_bars": len(layers.get("merged_bars", []) or []),
               "fractals": len(layers.get("fractals", []) or []),
               "strokes": len(layers.get("strokes", []) or []),
               "segments": len(layers.get("segments", []) or []),
               "centers": len(layers.get("centers", []) or [])}
    # 结构链要求：每一步都有产物（中枢为 0 时结构链不完整）
    g.structure_gate = all(g.chain[k] > 0 for k in ("fractals", "strokes", "segments"))
    if not g.structure_gate:
        g.failed.append("structure_gate")
    if g.chain["centers"] == 0:
        g.notes.append("无有效中枢 → 三买/三卖不可判定（规则 13）")

    # ---- 3) type_gate：同级别状态归类 ----
    g.type_gate = structure not in (None, "", "unknown", "insufficient_history")
    if not g.type_gate:
        g.failed.append("type_gate")

    # ---- 4) comparison_gate：背驰必须点名两段同向走势 ----
    # 没有背驰声明时本门不适用（不阻塞）；有声明则必须能点名 compared_ids 且同级别
    if divergences:
        ok = True
        for d in divergences:
            ids = d.get("compared_ids") or []
            ut = d.get("unit_type")
            # 两段必须存在、且 unit_type 一致（同级别）
            if len(ids) < 2 or not ut:
                ok = False
                break
            g.compared_movements = [str(i) for i in ids]
        g.comparison_gate = ok
        if not ok:
            g.failed.append("comparison_gate")
    else:
        g.comparison_gate = True      # 未使用背驰，门不适用

    # ---- 5) buy_sell_gate：结构映射到买卖点（由调用方按信号逐个校验）----
    # 这里只检查"是否存在可映射的结构基础"；逐个信号的规则 11/12/13 在 _confirm_signal
    g.buy_sell_gate = g.structure_gate and g.type_gate
    if not g.buy_sell_gate:
        g.failed.append("buy_sell_gate")

    # ---- 6) trigger_gate：低级别触发 ----
    # 我们只有本周期数据，无法递归到更低级别 → 如实标注 trigger_missing
    g.trigger_gate = False
    g.notes.append(f"trigger_missing: 未递归到 {levels.get('trigger_level')} 低级别确认"
                   f"（SKILL.md 要求显式标注）")

    # ---- 7) risk_gate：先写失效点 ----
    invalidation = raw.get("state", {}).get("invalidation")
    g.risk_gate = bool(invalidation)
    if not g.risk_gate:
        g.failed.append("risk_gate")

    # ---- 8) downgrade_gate：任一门不过 → proxy_research / observe ----
    engine_mode = _MODE_ALIASES.get(str(meta.get("definition_mode", "")).lower(),
                                    "proxy_research")
    if g.structure_gate and g.type_gate and engine_mode == "strict_chanlun":
        g.output_mode = "strict_chanlun"
    elif g.structure_gate and g.type_gate:
        g.output_mode = "structure_proxy"
    else:
        g.output_mode = "observe"
    # 引擎自报 research_proxy → 我们最高只能到 structure_proxy（不冒充严格缠论）
    if engine_mode == "proxy_research" and g.output_mode == "strict_chanlun":
        g.output_mode = "structure_proxy"
    g.downgrade_gate = g.output_mode != "observe" or not signals
    if g.output_mode == "observe" and signals:
        g.notes.append("结构链不完整 → 所有候选降级为 observe，不计分")
    return g


def _confirm_signal(sig: dict, gate: AuditGate, raw: dict,
                    center_raw: dict | None, close: float) -> tuple[bool, str]:
    """逐信号校验 SKILL.md 不可妥协规则 11/12/13。

    返回 (是否确认计分, 未通过的原因)。
    """
    kind = str(sig.get("kind", "")).rstrip("_candidate")
    layers = raw.get("layers", {}) or {}
    strokes = layers.get("strokes", []) or []
    segments = layers.get("segments", []) or []
    divergences = layers.get("divergences", []) or []

    # 结构链不完整 → 一律 observe（规则 7/8：数据不足时明确降级）
    if gate.output_mode == "observe":
        return False, "structure_chain_incomplete"

    if kind in ("B1", "S1"):
        # 规则 11：必须点名"前一个同级别趋势"或"下跌+中枢+下跌"的上下文，
        # 且必须识别被比较的同向走势。→ 需要存在同级别段与背驰证据。
        if len(segments) < 3:
            return False, "rule11_no_same_level_context(segments<3)"
        if not divergences:
            return False, "rule11_no_compared_movements(divergence missing)"
        d = divergences[-1]
        if len(d.get("compared_ids") or []) < 2:
            return False, "rule11_compared_movements_not_named"
        # 一买需要背驰方向与信号同向（看涨一买 ← bullish 背驰）
        want = "bullish" if kind == "B1" else "bearish"
        if str(d.get("direction")) != want:
            return False, f"rule11_divergence_direction_mismatch({d.get('direction')}!={want})"
        # 规则 6：MACD 等过滤器只调整信心，不定义买卖点 → 背驰须由结构支撑
        if not (d.get("baseline") or {}).get("supports_candidate"):
            return False, "rule11_divergence_not_structurally_supported"
        return True, ""

    if kind in ("B2", "S2"):
        # 规则 12：必须点名"一买候选 + 它的第一次回抽测试"。
        # 引擎输出里若没有一买候选的记录，则二买不可确认。
        hist = raw.get("state", {}).get("signal_history") or []
        has_first = any(str(h.get("kind", "")).rstrip("_candidate") in ("B1", "S1")
                        for h in hist)
        if not has_first:
            # 退路：用段结构近似"一买存在" —— 至少需要 3 段且最近一段与信号同向
            if len(segments) < 3:
                return False, "rule12_no_first_buy_context"
            last_dir = str(segments[-1].get("direction", ""))
            want = "up" if kind == "B2" else "down"
            if last_dir != want:
                return False, f"rule12_no_pullback_test(last_seg={last_dir}!={want})"
        return True, ""

    if kind in ("B3", "S3"):
        # 规则 13：必须点名"中枢边界、离开、回拉、不回/再入"全部状态。
        if center_raw is None:
            return False, "rule13_no_valid_center"
        zg, zd = center_raw.get("zg"), center_raw.get("zd")
        if zg is None or zd is None:
            return False, "rule13_center_bounds_missing"
        if kind == "B3":
            # 三买：价格须**离开中枢上沿**（close > zg）且回拉不回中枢
            if not close > float(zg):
                return False, f"rule13_price_not_above_zg({close:.3f}<={float(zg):.3f})"
        else:
            if not close < float(zd):
                return False, f"rule13_price_not_below_zd({close:.3f}>={float(zd):.3f})"
        # 回拉/不回的状态须有段结构支撑（至少 3 段）
        if len(segments) < 3:
            return False, "rule13_pullback_state_unverified"
        return True, ""

    return False, f"unknown_signal_kind({kind})"


def analyze_tf(df: pd.DataFrame, timeframe: str, symbol: str | None = None,
               levels: dict | None = None) -> ChanlunResult:
    """单周期缠论分析 + 严格原文自检门。

    levels: 级别链（trade/confirm/trigger）。缺省用 DEFAULT_LEVEL_CHAIN。
    """
    result = ChanlunResult(computed_at=time.time())
    result.levels = dict(levels or DEFAULT_LEVEL_CHAIN)
    if not CHANLUN_AVAILABLE:
        result.error = f"chanlun engine import failed: {_IMPORT_ERROR}"
        return result
    try:
        bars = df_to_bars(df)
        raw = _chanlun_analyze(bars, symbol=symbol or CFG.mt5.symbol,
                               timeframe=timeframe, source="mt5")
    except Exception as e:
        result.status = "bad_input"
        result.error = str(e)
        return result
    result.status = "ok"
    result.raw = raw
    meta = raw.get("meta", {})
    result.definition_mode = meta.get("definition_mode", "research_proxy")
    state = raw.get("state", {})
    result.structure = state.get("structure")
    result.quality = raw.get("quality", {})
    invalidation = state.get("invalidation")
    # invalidation 可能是 list（引擎实测返回 list[str]）
    if isinstance(invalidation, list):
        result.invalidation = "; ".join(str(x) for x in invalidation)
    else:
        result.invalidation = invalidation

    centers = raw.get("layers", {}).get("centers", []) or []
    cid = state.get("current_center_id")
    center_raw = None
    for c in centers:
        if c.get("id") == cid:
            center_raw = c
            result.center = {"zg": c.get("zg"), "zd": c.get("zd"),
                             "gg": c.get("gg"), "dd": c.get("dd"),
                             "direction": c.get("direction"),
                             "status": c.get("status"),
                             "id": c.get("id"),
                             "definition_mode": c.get("definition_mode")}
            break
    # 代理近似损失（SKILL.md 规则 7 / 工作台导出契约：必须如实标注）
    if center_raw:
        al = center_raw.get("approximation_loss")
        if isinstance(al, list):
            result.approximation_loss = [str(x) for x in al]
    for seg in (raw.get("layers", {}).get("segments", []) or [])[:1]:
        if seg.get("definition_mode"):
            result.approximation_loss.append(
                f"segment definition_mode={seg['definition_mode']} "
                f"method={seg.get('method')}")

    signals = state.get("candidate_signals", []) or []
    close = float(df["close"].iloc[-1])

    # ---- 执行 8 门自检 ----
    gate = _audit_gates(raw, result.structure, signals, result.center,
                        center_raw, result.levels, close)
    result.audit = gate

    # ---- 结构分（type_gate 未过则不给结构方向）----
    score = 0.0
    if gate.type_gate:
        score = _STRUCTURE_SCORE.get(result.structure or "unknown", 0.0)
        # 突破方向细化
        if result.structure == "center_breakout" and result.center:
            if result.center.get("zg") and close > result.center["zg"]:
                score = abs(score)
            elif result.center.get("zd") and close < result.center["zd"]:
                score = -abs(score)

    # ---- 逐信号过规则 11/12/13 ----
    for sig in signals:
        kind = str(sig.get("kind", ""))
        ok, why = _confirm_signal(sig, gate, raw, center_raw, close)
        rec = {**sig, "audit": "confirmed" if ok else "observe", "audit_reason": why}
        if ok:
            base = _SIGNAL_SCORE.get(kind.rstrip("_candidate"), 0.0)
            if kind.endswith("_candidate"):
                base *= 0.6          # 候选未确认降权
            score += base
            result.confirmed_signals.append(rec)
        else:
            result.observed_signals.append(rec)

    # ---- risk_gate 未过 → 不给方向（先写失效点，再谈收益）----
    if not gate.risk_gate:
        score = 0.0

    result.score = max(-3.0, min(3.0, score))
    result.signals = signals
    # 下一观察点（SKILL.md 工作流第 5 步）
    if result.center:
        result.next_observation = (
            f"观察中枢 {result.center.get('id')} 边界 zg={result.center.get('zg')} / "
            f"zd={result.center.get('zd')} 的离开与回拉状态")
    elif result.invalidation:
        result.next_observation = f"观察失效点: {result.invalidation}"
    return result
