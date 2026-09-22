"""决策状态机真实数据回放测试（无 mock）：空仓/持仓/熔断安全态。

覆盖 research/18_COMMERCIAL_PLAN.md 的新增门：
- P1-2 波动 regime 闸
- P1-3 阈值零点校正（S_eff = S − S0）
- LLM 主路径（缺失时不默认放网格）
"""
from __future__ import annotations

import pytest

from gold_agent.common.config import CFG
from gold_agent.decision.machine import (DecisionContext, DecisionEngine,
                                         State, effective_score)
from gold_agent.fusion.engine import FusedEvidence, FusionResult
from gold_agent.mt5.client import PositionRow, PositionsView
from gold_agent.news.collector import NewsView
from gold_agent.risk.gate import RiskGate
from gold_agent.risk.grid import GridState
from gold_agent.risk.position import CircuitBreakers

# 越过开仓阈值的分数。**从 config 派生，不硬编码** ——
# open_threshold 历史上在 1.2/1.3/1.6 之间变动过（P2-1 参数门会回滚它），
# 硬编码会让测试随参数回滚而静默失效。
ABOVE = CFG.decision.open_threshold + 0.4
BELOW = CFG.decision.open_threshold - 0.4


def _ctx(score: float, sigma: float = 0.3, holding: list[PositionRow] | None = None,
         llm: dict | None = None, high_risk: bool = False,
         baseline: float = 0.0, vol_pct: float = 0.9,
         llm_available: bool | None = None,
         regime: str = "trending") -> DecisionContext:
    ev = FusedEvidence(result=FusionResult(score=score, sigma=sigma, regime=regime,
                                           score_baseline=baseline,
                                           vol_percentile=vol_pct))
    pos = PositionsView(positions=holding or [])
    news = NewsView(high_risk_window=high_risk)
    return DecisionContext(ev=ev, positions=pos, news=news, llm=llm,
                           last_close=4350.0, atr=5.0, realized_vol=0.008, round_id=1,
                           llm_available=(bool((llm or {}).get("review"))
                                          if llm_available is None else llm_available))


def test_flat_hold_low_score():
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    p = e.decide(_ctx(score=BELOW))
    assert p.kind == "hold"
    # 阈值来自 config.toml；断言理由包含当前阈值数字
    assert any(str(CFG.decision.open_threshold) in r for r in p.reasons)


def test_flat_hold_high_sigma():
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    p = e.decide(_ctx(score=ABOVE, sigma=1.5))
    assert p.kind == "hold"
    assert any("标准差" in r for r in p.reasons)


def test_flat_hold_news_high_risk():
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    p = e.decide(_ctx(score=ABOVE, high_risk=True))
    assert p.kind == "hold"
    assert any("新闻" in r for r in p.reasons)


def test_flat_open_market_aligned_llm():
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    p = e.decide(_ctx(score=ABOVE, llm={"review": {"verdict": "bullish", "confidence": 0.75}}))
    assert p.kind == "open_market"
    assert p.direction == "LONG"


def test_flat_market_when_not_aligned():
    """未对齐 LLM 但信号够强 → **市价开仓**（用户要求：少用挂单）。

    原断言是 `place_grid`。用户反馈"很难下单"后改为市价主路径：
    实测 `aligned` 是死代码（372 个 review 的 confidence 最大 0.550，
    而 llm_align_conf=0.60），导致 open_market 提案恒为 0。
    现在只要信号够强且 LLM 未明确反对，就走市价。
    """
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    p = e.decide(_ctx(score=-ABOVE, llm={"review": {"verdict": "bullish", "confidence": 0.6}}))
    assert p.kind == "open_market"
    assert p.direction == "SHORT"


def test_order_direction_mapping_is_exhaustive():
    """回归：MT5 订单类型码 → LONG/SHORT 必须**穷举**映射。

    实测事故：`OrderRow.type` 原存 `str(o.type)`（整数码如 "2"），
    而 `machine.py` 用 `"buy" in str(type).lower()` 判方向 ——
    `"buy" in "2"` 恒为 False → **所有挂单都被当成 SHORT**。
    实测一个 `ORDER_TYPE_BUY_LIMIT`(=2) 的做多挂单被判成 SHORT，
    方向完全颠倒：S_eff 为正（看涨）时反而把做多挂单撤掉。
    """
    from gold_agent.mt5.client import _order_direction
    cases = {
        0: "LONG",    # BUY
        1: "SHORT",   # SELL
        2: "LONG",    # BUY_LIMIT
        3: "SHORT",   # SELL_LIMIT
        4: "LONG",    # BUY_STOP
        5: "SHORT",   # SELL_STOP
        6: "LONG",    # BUY_STOP_LIMIT
        7: "SHORT",   # SELL_STOP_LIMIT
        8: "UNKNOWN",  # CLOSE_BY 无方向
    }
    for code, want in cases.items():
        got = _order_direction(code)
        assert got == want, f"类型码 {code} 映射为 {got}，应为 {want}"
    # 旧逻辑必须确实是坏的（防止有人"改回去"）
    assert "buy" not in str(2).lower(), (
        "整数码 2 (BUY_LIMIT) 用字符串猜方向的旧逻辑是错的，不要改回")


def test_single_instance_lock_blocks_second_runner(tmp_path, monkeypatch):
    """回归：同一账号**不得**同时跑两个 main.py。

    实测事故：一个手动启动的 main.py 与一个后台任务同时运行，
    它们共用同一个 MT5 账号和 magic，各自独立决策、各自下单 ——
    网格单会翻倍、撤单会互相打断、`grid_state.json` 会互相覆盖。
    实盘上这是直接的资金风险。

    ⚠️ 不能用 `msvcrt.locking`：它锁的是**当前文件位置起**的字节区间，
      两个句柄初始位置可能不同 → 实测第二个进程照样拿到锁。
      本实现用 `O_CREAT|O_EXCL` + pid 存活检测。
    """
    import os
    import subprocess
    import sys
    from pathlib import Path
    import gold_agent.runner as runner

    monkeypatch.setattr(runner.CFG, "state_path", tmp_path / "state.json",
                        raising=False)
    lock = tmp_path / "runner.lock"

    child = (
        "import sys, pathlib\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1] / 'src')!r})\n"
        "from gold_agent.common.config import CFG\n"
        f"CFG.state_path = pathlib.Path({str(tmp_path / 'state.json')!r})\n"
        "import gold_agent.runner as runner\n"
        "try:\n"
        "    runner._acquire_single_instance_lock(dry=False)\n"
        "    print('GOT_LOCK')\n"
        "except SystemExit as e:\n"
        "    print('BLOCKED', e.code)\n"
    )

    def _run_child():
        r = subprocess.run([sys.executable, "-c", child], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        return (r.stdout or "").strip()

    # 1) 持有者活着 → 必须被拦住
    lock.write_text(str(os.getpid()), encoding="utf-8")
    out = _run_child()
    assert "BLOCKED" in out, f"第二个 runner 未被拦住: {out!r}"
    assert "GOT_LOCK" not in out

    # 2) 持有者已死 → 允许接管（不留死锁文件）
    lock.write_text("999999", encoding="utf-8")
    out = _run_child()
    assert "GOT_LOCK" in out, f"残留锁未被接管: {out!r}"

    # 3) dry_run 不加锁（允许与实盘并存演练）
    assert runner._acquire_single_instance_lock(dry=True) is None


def test_holding_management_not_blocked_by_pending():
    """回归：**有挂单时持仓管理不得被跳过**（严重）。

    实测事故：原实现 `if pending: ... elif not holding: ... else: holding`
    → 只要还挂着网格单，`_decide_holding` 永远不执行 →
    止损、利润回吐平仓、顺势加仓**全部被挂单挡住**。

    实盘证据：持仓 LONG 浮亏 −2.59，S_eff=−1.50 已越过
    exit_threshold=1.2 连续 **12 轮**，日志却一直是
    "pending x1 waiting fill" —— **该平的仓一直没平**。
    """
    from gold_agent.mt5.client import OrderRow
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    pos = PositionRow(ticket=333, symbol="XAUUSDm", type="LONG", volume=0.01,
                      price_open=4350, sl=0, tp=0, profit=-2.59, swap=0, time=0,
                      comment="", magic=CFG.mt5.magic)
    # 一张**同向**挂单（LONG）——它不该阻止持仓止损
    pend = OrderRow(ticket=444, symbol="XAUUSDm", type="LONG", volume=0.01,
                    price_open=4340, sl=0, tp=0, time_setup=0, comment="",
                    magic=CFG.mt5.magic)

    def _ctx_with_pending(score, baseline=0.0):
        c = _ctx(score=score, baseline=baseline, holding=[pos])
        c.positions.pending_orders = [pend]
        return c

    # 连续反向达到 exit_persist_rounds → 必须平仓，不能被挂单挡住
    for _ in range(CFG.decision.exit_persist_rounds - 1):
        p = e.decide(_ctx_with_pending(score=-ABOVE))
    p = e.decide(_ctx_with_pending(score=-ABOVE))
    assert p.kind == "close_position", (
        f"有挂单时持仓管理被跳过（得到 {p.kind}）—— "
        f"止损/平仓逻辑被 pending 掩盖，这是危险的")


def test_pending_cancel_uses_correct_direction():
    """回归：撤挂单的方向判定必须正确（不得把做多挂单当空单撤）。

    ⚠️ 行为已变更（用户要求少用挂单）：**有挂单且信号够强时一律撤单改走市价**。
    原断言"方向一致的挂单 → hold（继续等）"，现在改成撤单 —— 因为挂单
    65.5% 最终被撤销，且会阻塞市价开仓 167 轮。但**撤单方向仍必须正确**，
    这是本测试真正要守住的东西。
    """
    from gold_agent.mt5.client import OrderRow
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))

    def _mk(direction):
        return OrderRow(ticket=555, symbol="XAUUSDm", type=direction, volume=0.01,
                        price_open=4340, sl=0, tp=0, time_setup=0, comment="",
                        magic=CFG.mt5.magic)

    def _ctx_pend(score, direction):
        c = _ctx(score=score)
        c.positions.pending_orders = [_mk(direction)]
        return c

    # 四个组合都必须撤单，且方向 = 原挂单方向（不能颠倒）
    for score, direction in ((ABOVE, "LONG"), (ABOVE, "SHORT"),
                             (-ABOVE, "LONG"), (-ABOVE, "SHORT")):
        p = e.decide(_ctx_pend(score=score, direction=direction))
        assert p.kind == "cancel_pending", (
            f"{direction} 挂单在 S_eff={score:+.2f} 时应撤单改市价，得到 {p.kind}")
        assert p.direction == direction, (
            f"撤单方向必须是 {direction}，得到 {p.direction}（方向颠倒）")


def test_pending_does_not_block_market_entry():
    """回归（用户反馈"很难下单"）：**挂单不得阻塞市价开仓**。

    实测事故：原实现 `elif pending: hold("已有 N 张挂单等待成交")`
    → 挂单存在期间 `_decide_flat` 永不执行 → 强信号被挡 **167 轮**。
    而挂单有效期 4 小时、65.5% 最终被撤销，等于白白错过整段行情。

    现在：强信号 + 有挂单 → 撤掉旧挂单（下一轮市价进），而不是死等。
    """
    from gold_agent.mt5.client import OrderRow
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    pend = OrderRow(ticket=666, symbol="XAUUSDm", type="SHORT", volume=0.01,
                    price_open=4340, sl=0, tp=0, time_setup=0, comment="",
                    magic=CFG.mt5.magic)
    c = _ctx(score=-ABOVE, llm={"review": {"verdict": "neutral", "confidence": 0.35}})
    c.positions.pending_orders = [pend]
    p = e.decide(c)
    assert p.kind != "hold", (
        f"强信号时挂单不该让系统死等（得到 {p.kind}）—— "
        "这正是 open_market 提案恒为 0 的原因之一")
    assert p.kind == "cancel_pending", "应先撤掉旧挂单改走市价"
    assert p.direction == "SHORT"


def test_aligned_is_not_required_for_market_entry():
    """回归：市价开仓**不再要求** confidence 达到 llm_align_conf。

    实测：372 个 review 的 confidence 最大值只有 0.550，平均 0.357，
    而 llm_align_conf=0.60 → `aligned` 永远不可能成立 →
    **open_market 是死代码**（历史提案数 = 0）。
    现在只要信号够强且 LLM 未明确反对即可市价开仓。
    """
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    # 实测最常见的形状：neutral / 0.35
    p = e.decide(_ctx(score=ABOVE,
                      llm={"review": {"verdict": "neutral", "confidence": 0.35}}))
    assert p.kind == "open_market", "conf 未达阈值不应阻止市价开仓"
    # 最高实测值 0.55 也不行（低于 0.60）
    p = e.decide(_ctx(score=ABOVE,
                      llm={"review": {"verdict": "bullish", "confidence": 0.55}}))
    assert p.kind == "open_market"
    # 只有 LLM **明确反对**（达 llm_adverse_conf）才拦
    p = e.decide(_ctx(score=ABOVE,
                      llm={"review": {"verdict": "bearish", "confidence": 0.75}}))
    assert p.kind == "hold"


def test_pending_only_in_mean_revert():
    """用户选定：仅均值回归 regime 挂单，其余市价开仓。"""
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    llm = {"review": {"verdict": "neutral", "confidence": 0.35}}
    p = e.decide(_ctx(score=ABOVE, regime="trending", llm=llm))
    assert p.kind == "open_market", "趋势行情应市价开仓"
    p = e.decide(_ctx(score=ABOVE, regime="mean_reverting", llm=llm))
    assert p.kind == "place_grid", "均值回归行情才挂限价单等回踩"


def test_holding_exit_streak():
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    pos = PositionRow(ticket=111, symbol="XAUUSDm", type="LONG", volume=0.01,
                      price_open=4350, sl=0, tp=0, profit=0, swap=0, time=0,
                      comment="", magic=CFG.mt5.magic)
    # 需要连续 exit_persist_rounds 轮反向（P1-1 已从 3 改为 2）
    for _ in range(CFG.decision.exit_persist_rounds - 1):
        p = e.decide(_ctx(score=-ABOVE, holding=[pos]))
        assert p.kind == "hold"
    p = e.decide(_ctx(score=-ABOVE, holding=[pos]))
    assert p.kind == "close_position"


def test_holding_llm_adverse_close():
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    pos = PositionRow(ticket=222, symbol="XAUUSDm", type="SHORT", volume=0.01,
                      price_open=4350, sl=0, tp=0, profit=0, swap=0, time=0,
                      comment="", magic=CFG.mt5.magic)
    p = e.decide(_ctx(score=-0.5, holding=[pos],
                      llm={"review": {"verdict": "bullish", "confidence": 0.8}}))
    assert p.kind == "close_position"


def test_safe_hold_on_error():
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    # 触发异常：positions 里放非法对象
    p = e.decide(_ctx(score=ABOVE, holding=["bad-object"]))
    assert p.kind == "hold"
    assert e.state == State.SAFE_HOLD


# ══════════════════════════════════════════════════════════════════
# P1-3 阈值零点校正（S_eff = S − S0）
# ══════════════════════════════════════════════════════════════════
def test_effective_score_subtracts_baseline():
    """S_eff = S − S0。"""
    assert effective_score(1.5, 0.5) == pytest.approx(1.0)
    assert effective_score(0.5, 0.5) == pytest.approx(0.0)
    assert effective_score(-1.0, 0.5) == pytest.approx(-1.5)


def test_baseline_prevents_structural_long():
    """P1-3：融合分零点不在 0 时，"中性"不得被当成"偏多"。

    实测融合分均值 +0.52、80.2% 为正（research/16_live_audit.txt）。
    S=+0.52 在旧逻辑下会被当成偏多；减去基线后 S_eff=0 → 应 hold。
    """
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    # 原始 S = 1.0，基线 S0 = 1.0 → S_eff = 0 → hold
    p = e.decide(_ctx(score=1.0, baseline=1.0,
                      llm={"review": {"verdict": "bullish", "confidence": 0.9}}))
    assert p.kind == "hold", "基线校正后无净信号，不应开仓"
    assert any("S_eff" in r for r in p.reasons)


def test_baseline_shifts_direction_decision():
    """基线校正可以把一个"看似看多"的信号翻成看空。

    ⚠️ 阈值从 `CFG.decision.open_threshold` 取，**不硬编码** ——
    否则本测试会随 P2-1 的参数门回滚而失效（它曾假设阈值 1.3，
    回滚到 1.6 后 |S_eff| 就不再越线）。这里验证的是**基线校正机制**。
    """
    thr = CFG.decision.open_threshold
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    # 原始 S 看似看多（> 0），基线把它压到 −(thr+0.3) → 翻成看空
    s0 = 2.5
    s = s0 - (thr + 0.3)
    assert s > 0, "构造前提：原始分仍为正（看似看多）"
    p = e.decide(_ctx(score=s, baseline=s0,
                      llm={"review": {"verdict": "bearish", "confidence": 0.9}}))
    assert p.kind == "open_market", f"应开仓（S_eff={s - s0:.2f} 已越过阈值 {thr}）"
    assert p.direction == "SHORT"


# ══════════════════════════════════════════════════════════════════
# P1-2 波动 regime 闸
# ══════════════════════════════════════════════════════════════════
def test_low_vol_regime_blocks_entry(monkeypatch):
    """P1-2：波动分位低于门槛时不开仓（唯一不依赖方向预测的杠杆）。"""
    monkeypatch.setattr(CFG.decision, "vol_pct_min", 0.5, raising=False)
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    p = e.decide(_ctx(score=ABOVE, vol_pct=0.2,
                      llm={"review": {"verdict": "bullish", "confidence": 0.9}}))
    assert p.kind == "hold"
    assert any("低波动区间" in r for r in p.reasons)


def test_high_vol_regime_allows_entry(monkeypatch):
    monkeypatch.setattr(CFG.decision, "vol_pct_min", 0.5, raising=False)
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    p = e.decide(_ctx(score=ABOVE, vol_pct=0.9,
                      llm={"review": {"verdict": "bullish", "confidence": 0.9}}))
    assert p.kind == "open_market"


# ══════════════════════════════════════════════════════════════════
# LLM 主路径（research/20_llm_audit.txt 的修正）
# ══════════════════════════════════════════════════════════════════
def test_llm_opposed_blocks_entry():
    """LLM 明确反对 → 直接 hold（不再是"加分项"）。

    research/20：旧版 LLM 未调用时 `aligned=False` → 永远走 place_grid，
    实测 place_grid 30 次 vs open_market 16 次。现在 LLM 有实质否决权。
    """
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    p = e.decide(_ctx(score=ABOVE,
                      llm={"review": {"verdict": "bearish", "confidence": 0.9}}))
    assert p.kind == "hold", "LLM 强烈反对时不得开仓"
    # hold 不带方向（与其它 hold 路径一致）；审计线索在 reasons 里
    assert p.direction is None
    assert any("反对" in r for r in p.reasons), "理由中应记录 LLM 反对"


def test_llm_unavailable_no_default_grid(monkeypatch):
    """LLM 缺失时**不再默认挂网格**。

    用户要求少用挂单后，强信号走市价开仓；`allow_grid_without_llm=False`
    这条旧闸只影响"未对齐且非市价路径"的兜底分支。这里验证核心意图：
    LLM 缺失不会退化成"默认挂单"。
    """
    monkeypatch.setattr(CFG.decision, "allow_grid_without_llm", False, raising=False)
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    p = e.decide(_ctx(score=ABOVE, llm=None, llm_available=False))
    assert p.kind != "place_grid", "LLM 缺失时不应默认挂网格"
    assert p.kind == "open_market", "强信号 + 无 LLM 反对 → 市价开仓"


def test_llm_neutral_still_allows_entry():
    """LLM 参与但说中性 → 信号够强就走市价（中性不是反对）。

    原断言是 `place_grid`。现在中性 verdict 不再把交易降级成挂单 ——
    实测 verdict 有 335/372 是 neutral，若中性就挂单，等于几乎只挂单。
    """
    e = DecisionEngine(RiskGate(CircuitBreakers(), GridState()))
    p = e.decide(_ctx(score=ABOVE,
                      llm={"review": {"verdict": "neutral", "confidence": 0.3}}))
    assert p.kind == "open_market", "LLM 中性时强信号应市价开仓"


def test_runner_console_shows_action_on_trade_rounds():
    """回归：**下单轮次**的控制台摘要必须显示动作和方向，不能是 `?`。

    实测 bug：`graph.run_round` 只在 `hold` / `skip_round` / `safe_hold`
    三个分支里设 `summary["action"]`，于是 `place_grid` / `open_market` /
    `cancel_pending` 这些**真正下单**的轮次没有 action →
    控制台打印 `[R2287] S=+1.41 sd=0.49 -> ?  [OK]`。

    恰好是最重要的轮次看不出发生了什么。修法：在 `decide` 之后立刻
    `summary["action"] = prop.kind`。
    """
    import gold_agent.runner as runner

    cases = [
        ("place_grid", "LONG", "挂限价单", "做多"),
        ("open_market", "SHORT", "市价开仓", "做空"),
        ("cancel_pending", "LONG", "撤销挂单", "做多"),
    ]
    for kind, direction, zh_kind, zh_dir in cases:
        out = runner._format_summary(2287, {
            "score": 1.41, "sigma": 0.49, "action": kind,
            "proposal": {"kind": kind, "direction": direction},
            "execution": {"ok": True}})
        assert "?" not in out, f"下单轮次出现了 '?': {out!r}"
        assert zh_kind in out, f"摘要未包含动作 {zh_kind}: {out!r}"
        assert zh_dir in out, f"摘要未包含方向 {zh_dir}: {out!r}"


def test_single_pending_order_console_format():
    """用户要求：取消网格，只挂预测的那一单。

    控制台必须直接给出**那一张**挂单的方向/入场/止损/止盈，
    且不再出现"挂单层数"这种网格措辞。
    """
    import gold_agent.runner as runner

    out = runner._format_summary(2287, {
        "score": 1.48, "sigma": 0.49, "action": "place_grid",
        "last_close": 4349.819,
        "proposal": {"kind": "place_grid", "direction": "LONG"},
        "risk": {"ok": True, "reason": "", "plan": {
            "kind": "place_grid", "direction": "LONG",
            "grid_plan": [{"level": 4349.819, "lots": 0.01,
                           "tp": 4365.882, "sl": 4339.379}]}},
        "execution": {"ok": True}})
    assert "挂限价单" in out, f"未显示单张挂单: {out!r}"
    assert "挂单层数" not in out, f"不应再出现网格措辞: {out!r}"
    assert "做多" in out and "入场 4349.819" in out, f"缺方向/入场: {out!r}"
    assert "止损 4339.379" in out and "止盈 4365.882" in out, f"缺止损止盈: {out!r}"


def test_graph_sets_action_for_every_proposal_kind():
    """回归：`graph` 必须为**所有** proposal kind 设置 `summary["action"]`。

    直接扫源码：`summary["action"] =` 必须出现在 `decide()` 之后的
    无条件位置，而不是只散落在 hold 类分支里。
    """
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]
           / "src" / "gold_agent" / "agent" / "graph.py").read_text(encoding="utf-8")
    assert 'summary["action"] = prop.kind' in src, (
        "graph.py 未在 decide() 后无条件设置 summary['action'] —— "
        "下单轮次会在控制台显示 '?'")


def test_research_replay_does_not_pollute_live_logs(tmp_path, monkeypatch):
    """回归：研究/回放脚本**不得**往实盘 decision 日志写记录。

    实测事故：`DecisionEngine.decide()` 内部会调 `decision_log(...)`，
    所以直接回放历史数据（如 `research/24_oos_open_rate.py`）会往
    `logs/decision_YYYYMMDD.jsonl` 灌入数千条**伪造轮次**
    （round 用的是数据索引：R14847 / R29915 / R44543 …）。
    实测污染量：6172 行里 5900 行是伪造的（95%），
    与实盘 R23xx 交错，导致"实盘到底跑了哪些轮"无法分辨。

    修法：`logging_util.set_silent(True)`。
    """
    from gold_agent.common import logging_util

    # 静默后，任何 jlog 都不得落盘
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(logging_util.CFG, "log_dir", log_dir, raising=False)
    logging_util.set_silent(True)
    try:
        logging_util.decision_log({"event": "decision", "round": 999999})
        logging_util.trade_log({"event": "round_exec", "round": 999999})
    finally:
        logging_util.set_silent(False)

    written = list(log_dir.glob("*.jsonl")) if log_dir.exists() else []
    assert not written, f"静默模式下仍写入了日志文件: {written}"

    # 恢复后必须能正常写（否则静默会把实盘日志也关掉）
    logging_util.set_silent(False)
    logging_util.decision_log({"event": "decision", "round": 1})
    files = list(log_dir.glob("decision_*.jsonl"))
    assert files, "关闭静默后应恢复写日志"
    assert "999999" not in files[0].read_text(encoding="utf-8")


def test_research_scripts_silence_logging():
    """回归：研究脚本必须在导入 DecisionEngine 前调用 set_silent。

    源码扫描 —— 这类"忘了加"的疏漏不会有任何运行期报错，
    只会安静地污染实盘日志，所以必须用测试锁住。
    """
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for p in sorted((root / "research").glob("*.py")):
        text = p.read_text(encoding="utf-8", errors="replace")
        if "DecisionEngine" not in text:
            continue
        if "set_silent" not in text:
            offenders.append(p.name)
    assert not offenders, (
        "以下研究脚本使用了 DecisionEngine 但未静默日志，"
        f"回放会污染实盘 logs/：{offenders}\n"
        "修法：在 import DecisionEngine 之前调用 "
        "logging_util.set_silent(True)")


def test_console_output_never_crashes_on_gbk(monkeypatch):
    """回归：控制台输出**任何字符都不得中断交易循环**。

    实测事故（严重）：`runner.py` 用 `print(f"... {'✓' if ok else ...}")`
    打印执行结果。Windows 控制台是 GBK，`✓`(U+2713) 无法编码 →
    `UnicodeEncodeError` 直接冒泡出主循环 → **进程崩溃**。

    致命之处在于 `✓` **只在执行成功时**才拼接：
    所以进程恰好会在**第一次真正开仓**的那一轮死掉 ——
    日志看起来"能跑"，实际一交易就崩，比不开仓更危险。

    ⚠️ 输出已改为**中文**（用户要求），所以断言从 `isascii()` 改成
    `encode("gbk")`：中文本身在 GBK 字符集内，可以安全输出；
    真正危险的是 `✓`/`⛔` 这类 GBK **之外**的符号。
    这条测试锁住的正是"不得再引入这类符号"。

    本测试跑**真实的格式化函数**（`_format_summary`），
    覆盖成功/失败/被风控拦截等所有拼接分支。
    """
    import io
    import sys
    import gold_agent.runner as runner

    # 1) 所有分支产出的行，必须在 GBK + strict 下可编码
    cases = [
        {"score": 1.25, "sigma": 0.49, "action": "place_grid",
         "execution": {"ok": True}},                       # 成功分支（原崩溃点）
        {"score": 1.25, "sigma": 0.49, "action": "place_grid",
         "execution": {"ok": False, "error": "requote"}},  # 失败分支
        {"score": -1.9, "sigma": 0.5, "action": "hold",
         "risk": {"ok": False, "reason": "max positions"}},  # 风控拦截分支
        {"score": None, "error": "boom"},                  # 无分数分支
        {"score": 0.0, "sigma": 0.49, "action": "hold"},   # 中性
    ]
    lines = [runner._format_summary(2278, c) for c in cases]
    for ln in lines:
        ln.encode("gbk")          # 不可编码则抛 UnicodeEncodeError
        bad = [ch for ch in ln if not _gbk_ok(ch)]
        assert not bad, (
            f"控制台行含 GBK 无法编码的字符 {bad!r} -> 会在 GBK 控制台崩溃: {ln!r}")

    # 2) 真实 print 路径在 GBK + strict stdout 下不得抛异常
    buf = io.BytesIO()
    monkeypatch.setattr(sys, "stdout",
                        io.TextIOWrapper(buf, encoding="gbk", errors="strict"))
    for ln in lines:
        runner._safe_print(ln)
    # ⚠️ 必须在 undo() **之前**取值：undo 会关闭这个 wrapper
    captured = buf.getvalue().decode("gbk", "replace")
    monkeypatch.undo()
    assert "[第2278轮]" in captured, f"输出未写入 stdout: {captured!r}"


def _gbk_ok(ch: str) -> bool:
    """单个字符能否用 GBK 编码（中文可以，`✓`/`⛔` 不行）。"""
    try:
        ch.encode("gbk")
        return True
    except UnicodeEncodeError:
        return False


def test_runner_console_format_is_gbk_safe():
    """回归：`_format_summary` 的输出必须能在 GBK 控制台安全打印。

    上一条测"兜底能扛住"，这条测"**根本不该产生**不可编码字符"。
    直接测函数而非扫源码 —— 因为崩溃字面量出现在**拼接行**上，
    按 `print(` 关键字扫描会漏掉。

    ⚠️ 原断言是 `out.isascii()`。用户要求日志改中文后，
    这个断言必然失败 —— 但**不能简单删掉**，否则 `✓` 类字符会重新溜进来。
    改成"每个字符都能 GBK 编码"：既允许中文，又拦住 GBK 外的符号。
    """
    import gold_agent.runner as runner
    cases = [
        {"score": 1.25, "sigma": 0.49, "action": "place_grid",
         "execution": {"ok": True}},
        {"score": 1.25, "sigma": 0.49, "action": "open_market",
         "execution": {"ok": False, "error": "err"}},
        {"score": 2.0, "sigma": 0.4, "action": "hold",
         "risk": {"ok": False, "reason": "r"}},
        {"score": None},
    ]
    for c in cases:
        out = runner._format_summary(1, c)
        bad = [ch for ch in out if not _gbk_ok(ch)]
        assert not bad, (
            f"_format_summary 产出了 GBK 无法编码的字符 {bad!r} "
            f"-> 会在 GBK 控制台上崩溃: {out!r}")
