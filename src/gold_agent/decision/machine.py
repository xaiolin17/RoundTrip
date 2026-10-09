"""决策状态机（docs/06）。

状态: IDLE → PROPOSING → OPEN_LIVE/PENDING_GRID → HOLDING ⇄ GRID_LADDER/MARTIN_REVERSE
     → EXIT → IDLE；异常 → SAFE_HOLD。
LLM 只提供 verdict/confidence 作为证据；订单参数只出自 risk 模块。

research/18_COMMERCIAL_PLAN.md 的三项修正落在本模块：

- **P1-2 波动 regime 闸**：只在 σ 位于滚动高分位时开仓。这是唯一不依赖方向
  预测的杠杆（`12_levers.py` C1：毛边际 +171%，净 NW-t 改善 7 倍）。
- **P1-3 阈值零点校正**：融合分的零点不在 0（实测均值 +0.52）。阈值判断前先减去
  滚动基线 S0，否则 S=+0.52 的"中性"会被当成"偏多"。
- **P1-1 决策周期**：主循环 1m（`loop_interval_s=60`）。
  平仓判据为「尾部 `exit_adverse_window` 轮不一致率」（2026-09-30 起，
  取代原「连续 `exit_persist_rounds` 轮」—— 后者在 46% 基础逆向率下
  纯属噪声触发，实测 129 次 vs 新规则 7 次）。

LLM 在主路径上（research/20 的修正）
-----------------------------------
`20_llm_audit.txt` 显示实盘 LLM review 覆盖率仅 **4.3%**（881 轮中 38 次），
后果是 30 次 place_grid vs 16 次 open_market —— 系统绝大多数时候只能挂限价单。
根因有三：① `min_interval_min=15` 节流 ② 预算被 news 挤占 ③ `|S|>=0.9` 前置条件。

修正后：LLM 评审在每轮决策（1h 周期）都执行，且 **LLM 缺失时不再默认放网格** ——
`allow_grid_without_llm=False` 时直接 hold，等 LLM 明确表态。这使 LLM 从
"罕见的加分项"变成"主路径的确认环节"，同时保留完整的降级路径。
"""
from __future__ import annotations

import collections
import math
import time
from dataclasses import dataclass, field
from enum import Enum

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import decision_log
from gold_agent.common.zh import direction_label, sentiment_label, verdict_label
from gold_agent.fusion.engine import FusedEvidence
from gold_agent.llm.orchestrator import Orchestrator
from gold_agent.mt5.client import PositionsView
from gold_agent.news.collector import NewsView
from gold_agent.risk.gate import Proposal, RiskGate
from gold_agent.risk.zhongshu import center_of, edge_side

#: 报价小数位与 point 的**默认值**，仅当上下文未提供品种档案时使用。
#: ⚠️ 这两个常量原为 XAUUSDm 的硬编码（3 / 0.001），多品种下会出错：
#:    EURUSDm（digits=5）的止损 `1.12419` 按 3 位规整成 `1.12400`，
#:    偏离 **19 个 point** —— 与 2026-09-30"同一持仓重复提交 83 次"
#:    属同一类故障（提交值与 MT5 存回值永不相等 → 幂等判定不收敛）。
#: 现在一律经 `_px(ctx)` / `_point(ctx)` 从 `SymbolProfile` 取实际值，
#: 这两个常量只在无档案的旧调用路径（研究脚本/测试桩）里兜底。
_PX_DIGITS = 3
_POINT = 0.001


def _px(ctx) -> int:
    """该品种的报价小数位（提交 MT5 前必须按它规整）。"""
    p = getattr(ctx, "profile", None)
    return int(getattr(p, "digits", _PX_DIGITS) or _PX_DIGITS)


def _point(ctx) -> float:
    """该品种的 point（最小价格变动单位）。

    ⚠️ 必须与 `point_value_per_lot` 的构造**同源**：两者都由
       `SymbolProfile.point` 推出。历史上它们各自硬编码 0.001，
       乘起来正好自消（实测 5 品种下 per_lot_risk 与正确公式一致）——
       那是**脆弱的巧合**：任何一处单独改成按 point 计算，
       立刻产生成百倍的手数误差（EURUSDm 是 100 倍）。
    """
    p = getattr(ctx, "profile", None)
    return float(getattr(p, "point", _POINT) or _POINT)


def _magic_of(ctx) -> int:
    """本品种的 magic（持仓/挂单过滤用）。

    ⚠️ 每品种 magic 必须唯一，否则各品种会互相认领对方的持仓。
    无档案时退回 `CFG.mt5.magic`（单品种兼容）。
    """
    p = getattr(ctx, "profile", None)
    m = getattr(p, "magic", None)
    return int(m) if m else int(CFG.mt5.magic)


class State(str, Enum):
    IDLE = "IDLE"
    PROPOSING = "PROPOSING"
    OPEN_LIVE = "OPEN_LIVE"
    PENDING_GRID = "PENDING_GRID"
    HOLDING = "HOLDING"
    GRID_LADDER = "GRID_LADDER"
    MARTIN_REVERSE = "MARTIN_REVERSE"
    EXIT = "EXIT"
    SAFE_HOLD = "SAFE_HOLD"


@dataclass
class DecisionContext:
    ev: FusedEvidence
    positions: PositionsView
    news: NewsView
    llm: dict | None                       # review/news_assessment 结果
    last_close: float
    atr: float | None
    realized_vol: float | None
    round_id: int = 0
    position_adds: dict | None = None      # {position_ticket_str: 已加仓次数}（Graph 持久）
    point_value_per_lot: float = 1.0       # 每手每点美元值（移损计算用）
    #: 当前**已用**总手数（本 magic 全部持仓之和）与 broker 允许的总上限。
    #: 决策层据此判断"还有没有加仓额度"，避免提出必然被风控拒掉的加仓。
    used_lots: float = 0.0
    max_lots_cap: float = 0.0
    #: LLM 是否真的被调用并返回了 review（用于区分"LLM 说中性"与"LLM 没参与"）
    llm_available: bool = False
    #: 当前品种档案（SymbolProfile）。多品种下 digits/point 必须按它取 ——
    #: 见模块顶部 `_px` / `_point` 的说明。为 None 时退回旧硬编码默认值，
    #: 使研究脚本与单元测试的旧调用方式继续可用。
    profile: object | None = None


def effective_score(s: float, baseline: float) -> float:
    """P1-3：融合分零点校正。S_eff = S − S0。"""
    return float(s) - float(baseline)


def z_score(s_eff: float, sigma: float) -> float:
    """把有效融合分换成**尺度无关**的 z 值：`z = S_eff / σ`。

    ⚠️ 为什么必须有这一层（2026-09-29 第四次修正，用户指出）：
    融合分是**加权平均** `S = Σwμ/Σw`，故 `sd(S) = 1/√Σw = sigma`。
    旧实现用绝对常数比它（`abs(S) >= 1.3`），于是同一行代码的含义
    随权重漂移：

        Σw=4.17（旧冻结基线）→ σ=0.4895 → |S|≥1.3 实为 |z|≥2.66
        Σw=12.0（等权收缩）  → σ=0.2887 → |S|≥1.3 实为 |z|≥4.50

    结果**权重越大（越有把握）越难开仓**，方向正好反了。用户原话：
    「本来要改的就是权重影响开仓 但是权重即会增大也会减小才对」。

    换成 z 尺度后权重的影响变成双向且方向正确：源越多/越确定 → Σw 大
    → σ 小 → 同样强度的信号 z 更大 → 更容易开，反之更难开。

    `sigma <= 0`（无任何可测源）时返回 0.0，即"不开仓"——
    这是唯一应当空仓的情况；"权重小"只应体现为难开，不应变成绝对不能开。
    """
    sig = float(sigma)
    if not math.isfinite(sig) or sig <= 1e-9:
        return 0.0
    return float(s_eff) / sig


def news_impact(ctx: "DecisionContext") -> tuple[float, str]:
    """提取 LLM 新闻评估的影响度与情绪（news 的**独立证据**通道）。

    返回 `(impact, sentiment)`；无评估时 `(0.0, "")`。

    ⚠️ 为什么 news 走这里而不是走融合权重：
    `weights.py` 的硬规则是「没有实测 IR 数字的源 = 0 权重」，news 从未
    做过 IR 校准，给方向权重就是用未验证信号做方向。但它现在**完全没用**：
    实测 7874 轮 news 从未进入 `per_source`（权重 0 被 `gaussian.fuse`
    排除），LLM 拿到情绪后触发的那次重融合实测融合分一字不变
    （news_score 0 → +1.5 → -1.5，融合分恒为 +1.438195），是空操作。

    所以：**news 不影响融合分，但持有方向上的否决权** —— 用户 2026-10-09
    明确要求"新闻事件可以提供做单方向 而不是停止开仓"，故 `_decide_flat`
    只在新闻情绪与信号方向**冲突**时拦，方向一致则放行。它仍然**不能**
    凭方向自己开仓（无实测 IR，不得投票，也不得替代融合分过 z_min）。
    """
    na = ((ctx.llm or {}).get("news_assessment") or {})
    try:
        impact = float(na.get("impact") or 0.0)
    except (TypeError, ValueError):
        impact = 0.0
    impact = max(0.0, min(1.0, impact))
    return impact, str(na.get("sentiment") or "")


def sentiment_direction(sentiment: str | None) -> str:
    """新闻情绪 → 交易方向；无法判断时返回空串。

    用户 2026-10-09：
    > 我觉得新闻事件可以提供做单方向 而不是停止开仓

    利多 → 做多（LONG），利空 → 做空（SHORT），中性/未知 → 无方向（""）。
    返回空串表示"这条新闻不该参与方向判断"（不得当成中性来放行或拦截）。
    """
    s = (sentiment or "").strip().lower()
    if s == "bullish":
        return "LONG"
    if s == "bearish":
        return "SHORT"
    return ""


class DecisionEngine:
    def __init__(self, risk_gate: RiskGate, llm: Orchestrator | None = None) -> None:
        self.gate = risk_gate
        self.llm = llm
        self.state = State.IDLE
        self._profit_peak: dict[str, float] = {}  # ticket -> 持仓期间浮盈峰值（回吐检测）
        self._score_peak: dict[str, float] = {}   # ticket -> 持仓期间顺向信号峰值
        #: ticket -> 最近 N 轮「行情与持仓方向不一致」的 0/1 滑窗。
        #: 用**比例**而非连续计数：实测 09-23 起 2283 个持仓轮里 46% 逆向，
        #: "连续 3 轮"在随机游走下极易满足（实测触发 129 次），是噪声不是风控。
        self._adverse_hist: dict[str, collections.deque] = {}
        #: 已收窄过止损止盈的 ticket（**一次性**，防棘轮）。
        #: ⚠️ 为什么必须去重：收窄是"按现价再收一档"。若每轮都收，20 → 10 → 5
        #:    → 2.5 → … 会几何式收敛到点差以内，等于**用几十轮慢刀把仓位磨死**，
        #:    比原来的直接平仓更糟。实测未去重时 9 轮就把止损压到 0.25（点差）。
        self._tightened: set[str] = set()

    def _prune_closed(self, holding: list) -> None:
        """清掉已平持仓的峰值状态。

        ⚠️ 这些字典原先**只增不减**：`_profit_peak` / `_score_peak` 按
        `position_ticket` 累积。仓位平掉后条目仍在，进程长期运行
        （本项目是 7×24 常驻）会一直涨，且更隐蔽的危害是 **ticket 复用**：
        MT5 的 ticket 在长时间尺度上会回收，旧峰值会让新仓位一开出来就
        "已经达到过锁盈门槛"，直接触发错误的保本离场。
        实测：日志里已累积 188 个 ticket 且无一被清理。
        """
        live = {str(p.ticket) for p in holding}
        for d in (self._profit_peak, self._score_peak, self._adverse_hist):
            for k in [k for k in d if k not in live]:
                del d[k]
        # 收窄标记也按 ticket 清理（同样存在 MT5 ticket 复用问题）
        for k in [k for k in self._tightened if k not in live]:
            self._tightened.discard(k)

    def decide(self, ctx: DecisionContext) -> Proposal:
        """纯函数式判定一轮行为；执行与对账在 runner。"""
        r = ctx.ev.result
        try:
            # ⚠️ 多品种：过滤必须用**本品种的** magic。
            #    全仓库原先只按 `CFG.mt5.magic` 过滤、**没有一处按 symbol 过滤**。
            #    若各品种共用同一 magic，每个品种会把别的品种的持仓当成自己的
            #    （已用总手数被跨品种求和、止损/平仓提案可能发到别人持仓上）。
            #    `SymbolProfile.magic` 每品种唯一，使这些过滤**自动变正确**。
            _magic = _magic_of(ctx)
            holding = [p for p in ctx.positions.positions if p.magic == _magic]
            pending = [o for o in ctx.positions.pending_orders if o.magic == _magic]
            self._prune_closed(holding)
            # P1-3：所有阈值判定都用校正后的分数
            s_eff = effective_score(r.score, r.score_baseline)
            # ⚠️ **持仓管理优先于挂单**。
            #    原实现是 `if pending: ... elif not holding: ... else: holding`，
            #    于是只要还挂着网格单，`_decide_holding` 就**永远不会执行** ——
            #    止损、利润回吐平仓、顺势加仓全部被挂单挡住。
            #    实测：持仓 LONG 浮亏 −2.59，S_eff=−1.50 已越过
            #    exit_threshold=1.2 连续 12 轮，却一直显示
            #    "pending x1 waiting fill"，**该平的仓一直没平**。
            #    安全逻辑（止损）绝不能被"还在等成交"掩盖。
            if holding:
                prop = self._decide_holding(ctx, holding, s_eff, r.sigma)
                # 持仓不动时，仍要按行情撤掉方向不对的挂单
                if prop.kind == "hold" and pending:
                    cancel = self._pending_cancel(pending, s_eff, r.sigma)
                    if cancel is not None:
                        prop = cancel
            else:
                # ⚠️ 挂单**不再阻塞**开仓判定（用户反馈"很难下单"）。
                #    原实现是 `elif pending: hold("已有挂单等待成交")`，
                #    于是挂单存在期间 `_decide_flat` 永不执行 ——
                #    实测强信号被这条挡住 **167 轮**，而挂单 65.5% 最终被撤销
                #    （有效期 4 小时，等于白白错过整段行情）。
                #    现在：先问决策层该不该开仓；若它要给**市价单**，
                #    就先撤掉旧挂单再市价进（方向由 _decide_flat 决定）。
                prop = self._decide_flat(ctx, s_eff, r.sigma)
                if pending and prop.kind == "open_market":
                    # 有冲突的旧挂单 -> 先撤，下一轮再市价开
                    cancel = self._pending_cancel(pending, s_eff, r.sigma)
                    prop = cancel if cancel is not None else Proposal(
                        kind="cancel_pending", direction=pending[0].type,
                        entry=pending[0].ticket,
                        reasons=["改走市价开仓 -> 撤掉旧挂单"])
                elif pending and prop.kind == "place_grid":
                    # 已有挂单就别重复挂
                    prop = Proposal(kind="hold",
                                    reasons=[f"已有 {len(pending)} 张挂单等待成交"])
        except Exception as e:
            decision_log({"event": "decision_error", "error": str(e),
                          "round": ctx.round_id})
            self.state = State.SAFE_HOLD
            return Proposal(kind="hold", reasons=[f"error: {e}"])
        self.state = State.PROPOSING if prop.kind != "hold" else State.IDLE
        if holding:
            self.state = State.HOLDING if prop.kind == "hold" else self.state
        decision_log({"event": "decision", "round": ctx.round_id,
                      "score": r.score, "score_baseline": r.score_baseline,
                      "score_eff": effective_score(r.score, r.score_baseline),
                      "sigma": r.sigma, "proposal": prop.__dict__})
        return prop

    # ---------- 挂单撤单 ----------
    def _pending_cancel(self, pending, s: float, sigma: float) -> Proposal | None:
        """行情对挂单不利 → 撤单；否则返回 None（继续等待成交）。

        用户要求：**行情不对要删除挂单**。

        ⚠️ 方向必须用 `OrderRow.type`（已由 `client._order_direction`
        映射成 LONG/SHORT）。原实现用 `"buy" in str(type).lower()` 猜，
        而当时 `type` 存的是整数码（"2"），恒为 False →
        **所有挂单都被当成 SHORT** → 一个做多挂单在 S_eff 为正（看涨）时
        反而被判为"不利"而撤掉，方向完全颠倒。
        """
        if not pending:
            return None
        pdir = pending[0].type
        if pdir not in ("LONG", "SHORT"):
            # 方向未知（CLOSE_BY 等）→ 保守起见不撤，交给上层
            return None
        z_p = z_score(s, sigma)
        adverse = (pdir == "LONG" and z_p <= -CFG.decision.z_exit) or \
                  (pdir == "SHORT" and z_p >= CFG.decision.z_exit)
        if adverse or sigma > CFG.fusion.sigma_max:
            why = (f"z={z_p:+.2f} 标准差={sigma:.2f}"
                   if adverse else f"标准差={sigma:.2f}>{CFG.fusion.sigma_max}")
            return Proposal(kind="cancel_pending", direction=pdir,
                            entry=pending[0].ticket,
                            reasons=[f"挂单 {direction_label(pdir)} 转不利：{why}"])
        return None

    # ---------- 空仓 ----------
    def _decide_flat(self, ctx: DecisionContext, s: float, sigma: float) -> Proposal:
        """空仓开仓门。

        s 是**已做零点校正**的有效融合分（P1-3）。
        判定用 z = s/σ（尺度无关），故权重变化会**双向**影响开仓
        （权重↑→σ↓→z↑→更易开），而不是旧的单向收紧。见 `z_score`。
        """
        z = z_score(s, sigma)
        z_min = CFG.decision.z_min
        if sigma > CFG.fusion.sigma_max:
            return Proposal(kind="hold",
                            reasons=[f"标准差 {sigma:.2f} > 上限 {CFG.fusion.sigma_max}"])
        if ctx.news.high_risk_window:
            return Proposal(kind="hold", reasons=["新闻高危窗口"])

        # ---- news「独立证据」通道：重大事件 → 按**方向冲突**决定是否开仓 ----
        # 用户 2026-10-09 原话：
        #   > 我觉得新闻事件可以提供做单方向 而不是停止开仓
        # 选定语义（与用户确认）：**只在与开仓方向冲突时拦，一致就放行**。
        # 即新闻拿到方向上的"否决权"，但不能反过来凭空驱动开仓 ——
        # 它仍不参与融合分（news 无实测 IR，不得投票，见 news_impact docstring）。
        imp, senti = news_impact(ctx)
        news_dir = sentiment_direction(senti)
        if abs(z) >= z_min and news_dir and imp >= CFG.decision.news_impact_block:
            # 只有在**信号本身就够开仓**（|z| 已过阈值）时，新闻冲突才拦。
            # 这样"新闻一致"必然放行，不会出现"新闻说多、系统却因 z 不够而不开"
            # 这种把新闻当方向驱动的副作用。
            this_dir = "LONG" if z > 0 else "SHORT"
            if news_dir != this_dir:
                return Proposal(kind="hold", reasons=[
                    f"新闻与开仓方向冲突：新闻{sentiment_label(senti)}"
                    f"（影响度 {imp:.2f}）看{direction_label(news_dir)}，"
                    f"信号看{direction_label(this_dir)} → 等事件过去"])

        # ---- P1-2 波动 regime 闸（唯一不依赖方向预测的杠杆）----
        vol_pct = getattr(ctx.ev.result, "vol_percentile", 0.5)
        if vol_pct < CFG.decision.vol_pct_min:
            return Proposal(kind="hold",
                            reasons=[f"低波动区间 {vol_pct:.2f} < {CFG.decision.vol_pct_min}"])

        if abs(z) < z_min:
            return Proposal(kind="hold", reasons=[
                f"|z| {abs(z):.2f} < 阈值 {z_min} "
                f"(S_eff={s:+.3f} 标准差={sigma:.3f})"])
        direction = "LONG" if z > 0 else "SHORT"

        # ---- LLM 一致性（主路径确认环节）----
        review = (ctx.llm or {}).get("review") or {}
        verdict = review.get("verdict")
        conf = float(review.get("confidence") or 0)
        want = "bullish" if direction == "LONG" else "bearish"
        # ⚠️ `aligned` 曾是市价开仓的**唯一**条件，但它是死代码：
        #    实测 372 个 review 的 confidence 最大值只有 0.550，
        #    而 llm_align_conf=0.60 -> **永远不可能成立** ->
        #    open_market 提案恒为 0，系统只会挂单（用户反馈"很难下单"）。
        #    LLM 给低置信度是诚实的（它自报 chanlun_mode=structure_proxy、
        #    probability_tier=very_low）。所以市价开仓改为：
        #    **信号够强 且 LLM 没有明确反对** 即可，不再要求 confidence 达标。
        aligned = (verdict == want) and conf >= CFG.decision.llm_align_conf
        opposed = (verdict is not None and verdict != "neutral" and verdict != want
                   and conf >= CFG.decision.llm_adverse_conf)
        reasons = [f"S_eff={s:+.2f} 标准差={sigma:.2f}",
                   f"波动分位={vol_pct:.2f}",
                   f"LLM={verdict_label(verdict)}/{conf:.2f} "
                   f"一致={'是' if aligned else '否'} 可用={'是' if ctx.llm_available else '否'}"]

        # LLM 明确反对且高置信 → 不开仓（这是 LLM 作为确认环节的实质权力）
        if opposed:
            return Proposal(kind="hold",
                            reasons=reasons + [f"LLM 反对 {verdict_label(verdict)}/{conf:.2f}"])

        # ---- 仅均值回归 regime 用挂单；其余一律市价开仓（用户选定）----
        # 用户原话："现在这种很难下单 我们要考虑用直接按照市价开仓 少用挂单"
        # 实测挂单 65.5% 被撤销，且挂单存在期间 `_decide_flat` 不会执行
        # -> 强信号被挂单阻塞 167 轮。
        if CFG.decision.pending_only_in_mean_revert and \
                ctx.ev.result.regime != "mean_reverting":
            # ---- 中枢位置闸（用户反馈"经常在中枢中部下单"）----
            # 实测：123/127 笔真实单子走的就是这一行（entry=市价），
            # 而入场价与中枢完全无关 -> 择时在统计上等价于随机时刻入场。
            # 用户选定先加**硬闸**：中部不开仓，只允许贴边或突破。
            # ⚠️ 取不到有效中枢时**放行**（保守）：宁可维持现状，
            #    也不因为拿不到中枢数据而把系统变成不开仓。
            if CFG.risk.zhongshu_gate:
                cv = center_of(getattr(ctx.ev, "chanlun", None),
                               ctx.last_close, ctx.atr,
                               tfs=tuple(CFG.risk.zhongshu_tfs))
                side = edge_side(cv, direction)
                if side == "mid":
                    return Proposal(kind="hold", reasons=reasons + [
                        f"中枢中部禁止开仓：现价 {ctx.last_close:.2f} 位于 "
                        f"{cv.tf} 中枢 [{cv.zd:.2f}, {cv.zg:.2f}] 的 "
                        f"{cv.pos:.0%} 处（到最近边界仅 {cv.dist_edge:.2f} 点）"
                        f"→ 等回到两端或突破"])
            return Proposal(kind="open_market", direction=direction,
                            entry=ctx.last_close,
                            reasons=reasons + ["非均值回归行情 -> 直接市价开仓"])

        if ctx.ev.result.regime == "mean_reverting":
            # 均值回归：回踩概率高，挂限价单等更好的价
            return Proposal(kind="place_grid", direction=direction, entry=ctx.last_close,
                            reasons=reasons + ["行情为均值回归 -> 挂限价单等回踩"])

        # 关闭了 pending_only_in_mean_revert 时的旧行为：未对齐则挂单
        if not ctx.llm_available and not CFG.decision.allow_grid_without_llm:
            return Proposal(kind="hold",
                            reasons=reasons + ["LLM 不可用 -> 观望（不默认挂单）"])
        return Proposal(kind="place_grid", direction=direction, entry=ctx.last_close,
                        reasons=reasons + ["LLM 未确认 -> 先挂限价单"])

    # ---------- 持仓 ----------
    # ---------- 信号转弱 -> 收窄止损止盈（而非平仓）----------
    def _tighten_levels(self, ctx: DecisionContext, pos, direction: str,
                        s: float, sigma: float
                        ) -> tuple[float, float] | None:
        """把 SL/TP 同时向现价收近一档；无法安全收窄时返回 None。

        用户 2026-09-30：「只修改止损和止盈位置（新止损止盈缩小时不受
        1.2 倍的比例影响）」。

        为什么"收窄"是正确的中性动作：信号转弱时，继续按原 SL 距离持有
        等于**用旧信息承担风险**。把 SL 收近 = 降低单笔风险敞口；
        把 TP 同步收近 = 让目标在当前动能下更可能达成。
        两者都让仓位更快、更便宜地出清，而不是被信号噪声直接砍掉。

        返回 `(new_sl, new_tp)`；**已按 symbol digits 规整**（否则幂等判定
        会因浮点尾数永不收敛 —— 见 `_decide_holding` 移动止损分支的事故）。
        """
        atr = getattr(ctx, "atr", None) or 0.0
        if atr <= 0:
            return None
        # 一次性：同一持仓只收窄一次（否则每轮 ×0.7 会棘轮到点差以内）
        if str(getattr(pos, "ticket", "")) in self._tightened:
            return None
        px = float(getattr(pos, "price_open", 0.0) or 0.0)
        cur = float(getattr(ctx, "last_close", 0.0) or 0.0)
        sl_old = float(getattr(pos, "sl", 0.0) or 0.0)
        if px <= 0 or cur <= 0:
            return None
        # 现价与持仓方向的关系：只在**顺向**（浮盈侧）才收窄，
        # 否则"收窄"会把止损推到现价错误的一侧（MT5 直接 Invalid stops）。
        long_side = direction == "LONG"
        # 目标止损距离：取「原止损距离 × 0.7」与「0.6×ATR」中较小者。
        # ⚠️ 下限是**绝对**值而非比例：实测 XAUUSDm 点差 0.240，
        #    止损必须显著宽于点差，否则会被点差随机打掉（那不是风控是送钱）。
        spread_pad = max(0.25, atr * 0.05)
        old_dist = abs(cur - sl_old) if sl_old else abs(cur - px)
        if old_dist <= 0:
            old_dist = 0.6 * atr
        new_dist = max(min(old_dist * 0.7, 0.6 * atr), spread_pad)
        # 只有真的更"紧"才值得改单；否则返回 None 让上层走原逻辑
        if sl_old and new_dist >= old_dist - 1e-9:
            return None
        new_sl = cur - new_dist if long_side else cur + new_dist
        # TP 同步收近到「新止损距离 × min_rr」——这里**只用它定目标位**，
        # 不做"是否够赔率"的放行判定（收窄动作本身豁免 min_rr，见 gate）。
        tp_old = float(getattr(pos, "tp", 0.0) or 0.0)
        rr = max(float(CFG.decision.signal_exit_tp_rr), 0.0)
        tp_dist = new_dist * rr
        new_tp = cur + tp_dist if long_side else cur - tp_dist
        # 若原 TP 比新目标更近，保留原 TP（不要为了"统一"把目标推远）
        if tp_old and ((long_side and tp_old < new_tp) or
                       (not long_side and tp_old > new_tp)):
            new_tp = tp_old
        # 收窄后 SL 必须仍在**亏损侧**、TP 仍在**盈利侧**，否则 MT5 报
        # 'Invalid stops'。用开仓价而非现价做最终对齐基准。
        if long_side:
            if new_sl >= cur or new_tp <= cur:
                return None
        else:
            if new_sl <= cur or new_tp >= cur:
                return None
        self._tightened.add(str(getattr(pos, "ticket", "")))
        return round(new_sl, _px(ctx)), round(new_tp, _px(ctx))

    def _decide_holding(self, ctx: DecisionContext, holding, s: float, sigma: float) -> Proposal:
        pos = holding[0]
        direction = pos.type
        z = z_score(s, sigma)
        review = (ctx.llm or {}).get("review") or {}
        verdict = review.get("verdict")
        conf = float(review.get("confidence") or 0)
        adverse = (direction == "LONG" and z <= -CFG.decision.z_exit) or \
                  (direction == "SHORT" and z >= CFG.decision.z_exit)
        # 逆向轮（z 与持仓方向符号相反）——用于**窗口不一致率**。
        # 与 `adverse`（越过 z_exit 的强逆向）区分：后者是"信号明确反对"，
        # 前者只是"方向对不上"，两者都要，但用途不同。
        ekey = str(pos.ticket)
        hist = self._adverse_hist.setdefault(ekey, collections.deque(
            maxlen=CFG.decision.exit_adverse_window))
        hist.append(1 if ((direction == "LONG" and z < 0)
                          or (direction == "SHORT" and z > 0)) else 0)
        adverse_llm = (direction == "LONG" and verdict == "bearish" or
                       direction == "SHORT" and verdict == "bullish") and conf >= CFG.decision.llm_adverse_conf
        # ---- 主动平仓闸（用户 2026-09-30）----
        # 只有"窗口内逆向**比例**非常高"才主动平仓，否则一律只改止损止盈。
        # 见 `CFG.decision.exit_adverse_window/rate` 的窗口标定说明。
        n_hist = len(hist)
        rate = (sum(hist) / n_hist) if n_hist else 0.0
        # 样本不足窗口时**不判**（宁可不动，也不在半截数据上下结论）
        full = n_hist >= CFG.decision.exit_adverse_window
        rate_high = full and rate >= CFG.decision.exit_adverse_rate - 1e-9
        if rate_high:
            return Proposal(kind="close_position", direction=direction,
                            entry=pos.ticket,
                            reasons=[f"近 {n_hist} 轮方向不一致率 {rate:.0%} "
                                     f">= {CFG.decision.exit_adverse_rate:.0%}"])
        if adverse_llm:
            return Proposal(kind="close_position", direction=direction, entry=pos.ticket,
                            reasons=[f"LLM 反向 {verdict_label(verdict)}/{conf:.2f}"])
        # 顺势加仓（用户规则：每仓固定 0.01 手，同向最多加 5 次）
        # 阶梯式：分数与置信均须高于上一次；第 3 次起门槛指数递增
        same_side = (direction == "LONG" and s > 0) or (direction == "SHORT" and s < 0)
        adds = getattr(ctx, "position_adds", None) or {}
        rec = adds.get(str(pos.ticket)) or {}
        if isinstance(rec, dict):
            adds_count = int(rec.get("count", 0))
            last_score = rec.get("last_score")
            last_conf = rec.get("last_conf")
        else:                                   # 兼容旧格式 {ticket: n}
            adds_count, last_score, last_conf = int(rec or 0), None, None
        conf_cur = float(review.get("confidence") or 0)
        # 加仓阶梯也在 **z 尺度**上比较（与开仓门同一尺度）。
        # 若混用绝对分与 z，阶梯的"比上次更高"会被权重漂移污染。
        cur = abs(z)
        if last_score is None:
            score_ok = True                     # 首次加仓：只需过开仓阈值
            required = cur
        else:
            last = float(last_score)
            gap = max(cur - last, 0.0)          # 本次相对上次的提升量
            if adds_count < 2:
                required = last + min(gap, 0.1) if gap > 0 else None
                score_ok = required is not None
            else:
                # 第 3 次起：要求 ≥ last + gap×2^(count−1)，gap 取上次差值与 0.1 的大者
                base_gap = max(rec.get("base_gap") or 0.1, 0.1)
                required = last + base_gap * (2 ** (adds_count - 1))
                score_ok = cur >= required
        conf_ok = last_conf is None or conf_cur > float(last_conf)
        # ⚠️ 额度闸：`add_layer` 是**总手数上限**下唯一会失败的方向。
        # 实测：首仓常已用满 `max_lot`（198 单里 24 单直接 0.06），
        # 此时 `room = max_lot − used = 0`，风控必拒。
        # 原实现没有这道闸，于是每轮都提出一个**注定被拒**的加仓：
        # 实测 316 次 add_layer 拒绝中 **259 次**是"总手数上限"，
        # 且失败不写 `position_adds`（只在成功时写）→ 下一轮重新提，
        # 形成"提—拒—再提"的死循环，白耗一轮决策和一次落盘。
        # 这里先算清剩余额度：连最小手数都放不下就直接不提。
        room = (float(getattr(ctx, "max_lots_cap", 0.0) or 0.0)
                - float(getattr(ctx, "used_lots", 0.0) or 0.0))
        room_ok = room >= CFG.min_lot if getattr(ctx, "max_lots_cap", 0.0) else True
        if (same_side and abs(z) >= CFG.decision.z_min
                and sigma <= CFG.fusion.sigma_max
                and adds_count < CFG.risk.max_adds_per_position
                and room_ok and score_ok and conf_ok):
            return Proposal(kind="add_layer", direction=direction, entry=pos.ticket,
                            reasons=[f"加仓 第{adds_count + 1}/{CFG.risk.max_adds_per_position}次 "
                                     f"z={z:+.2f} (需>={required:.2f} 上次={last_score}) "
                                     f"置信={conf_cur:.2f} (上次={last_conf})"])
        # ---- 超短期利润回吐检测（用户选定：改用移动止损锁盈，不再砍掉浮盈）----
        # ⚠️ 事故复盘：原实现是「浮盈从峰值回吐 50% 就**主动平仓**」，
        #    实测把 30%~75% 的浮盈砍掉：
        #       2558982555  MFE $11.63 -> 平在 $2.96（砍 75%）
        #       2558998545  MFE $10.14 -> 平在 $3.09（砍 70%）
        #       2558970297  MFE $12.29 -> 平在 $5.46（砍 56%）
        #    计划 RR 1.28 被实际 RR 0.64 取代，50% 胜率下期望为负。
        #    现在改为：浮盈达到门槛后**推 SL 锁盈**（让利润奔跑），
        #    只有在浮盈从峰值回落到**保本线以下**时才强制离场。
        key_pos = str(pos.ticket)
        peak = self._profit_peak.get(key_pos, 0.0)
        cur_profit = pos.profit
        self._profit_peak[key_pos] = max(peak, cur_profit)
        usd_per_price_unit = (getattr(ctx, "point_value_per_lot", 1.0)
                              / _point(ctx) * pos.volume)
        lock_gap = CFG.decision.lock_profit_gap_usd / max(usd_per_price_unit, 1e-9)
        locked_sl = (pos.price_open + lock_gap
                     if direction == "LONG"
                     else pos.price_open - lock_gap)
        # 浮盈已达门槛 -> 推 SL 到保本上方（锁盈）
        if cur_profit >= CFG.decision.lock_profit_min_usd and pos.profit > 0:
            # ⚠️ 必须先规整到 symbol digits（XAUUSDm=3），否则幂等判定永不收敛。
            # 事故（2026-09-30）：`locked_sl=4178.211333333333` 提交后 MT5 存回
            # `4178.211`，下一轮 `pos.sl < locked_sl`（3.3e-4 的差）恒为真
            # → 每轮重发同一个值，MT5 恒回 `10025 No changes`。
            # 实测同一持仓重复 **83 次**，375 拒 / 35 成（91.5% 纯浪费）。
            locked_sl = round(locked_sl, _px(ctx))
            sl_is_old = (pos.sl is None
                         or (direction == "LONG" and pos.sl < locked_sl)
                         or (direction == "SHORT" and pos.sl > locked_sl))
            if sl_is_old:
                return Proposal(kind="modify_sltp", direction=direction, entry=pos.ticket,
                                tp_struct=locked_sl, reasons=[
                                    f"移动止损锁盈：浮盈 ${cur_profit:.2f}，"
                                    f"止损推至 {locked_sl:.3f}（锁 ${CFG.decision.lock_profit_gap_usd:.0f}）"])
        # 浮盈曾达门槛但已回吐到保本下方 -> 离场（防止盈利单变亏损单）
        if (self._profit_peak[key_pos] >= CFG.decision.lock_profit_min_usd
                and cur_profit < 0):
            return Proposal(kind="close_position", direction=direction, entry=pos.ticket,
                            reasons=[f"锁盈回吐：峰值 ${self._profit_peak[key_pos]:.2f} "
                                     f"-> 现 ${cur_profit:.2f}，保本离场"])
        # 信号回吐检测保留（信号本身转弱时平仓，与移动止损互补）
        # ⚠️ 同样用 z 尺度：峰值与当前值必须同尺度比较，否则权重变化会让
        #    "回吐"判定随 Σw 漂移（旧版混用绝对分，与开仓门不一致）。
        score_peak = self._score_peak.get(key_pos, 0.0)
        same_dir_z = z if direction == "LONG" else -z          # 顺持仓方向的信号 z
        self._score_peak[key_pos] = max(score_peak, same_dir_z)
        reserve_drop = CFG.decision.reserve_drop_z
        signal_giveback = (self._score_peak[key_pos] >= CFG.decision.z_min
                           and same_dir_z <= self._score_peak[key_pos] - reserve_drop)
        if signal_giveback:
            why = (f"信号回吐：峰值 z={self._score_peak[key_pos]:+.2f} "
                   f"-> {same_dir_z:+.2f}")
            # 用户 2026-09-30：「只修改止损和止盈位置」。
            # 信号转弱时**不再主动平仓**，改为把 SL 收到更紧处、TP 同步收近，
            # 让仓位在下一次真实反向波动中自然离场，而不是由信号噪声砍掉。
            tight = self._tighten_levels(ctx, pos, direction, s, sigma)
            if tight is not None:
                return Proposal(kind="modify_sltp", direction=direction,
                                entry=pos.ticket, tp_struct=tight[0],
                                new_tp=tight[1],
                                reasons=[f"{why} -> 收窄止损止盈"
                                         f"（止损 {tight[0]:.3f} 止盈 {tight[1]:.3f}）"])
            if key_pos in self._tightened:
                # 已按本条信号收窄过（一次性，防棘轮）。
                # ⚠️ 此处**必须 hold 而非平仓**：否则"收窄"只是把平仓推迟一轮，
                #    用户要的"只修改止损止盈位置"就没落到实处。
                #    收窄后的止损是**真实存在的离场机制** —— 交给它执行。
                return Proposal(kind="hold",
                                reasons=[f"{why}，已收窄止损止盈，交由止损止盈离场"])
            # 收窄不可行（缺 ATR / 价位异常 / 会越过现价）才退回平仓：
            # 有信号转弱却既不收窄也不离场，是把风险敞口无条件留在场上。
            return Proposal(kind="close_position", direction=direction, entry=pos.ticket,
                            reasons=[why])
        # 新闻反向减仓（阈值走配置：原为硬编码 0.8，见 CFG.decision.news_impact_close）
        na = (ctx.llm or {}).get("news_assessment") or {}
        if na.get("impact", 0) >= CFG.decision.news_impact_close:
            na_dir = {"bullish": "LONG", "bearish": "SHORT", "neutral": None}.get(na.get("sentiment"))
            if na_dir and na_dir != direction:
                return Proposal(kind="close_position", direction=direction, entry=pos.ticket,
                                reasons=[f"新闻不利 影响={na['impact']}"])
        # 持有期检查
        age_h = (time.time() - pos.time) / 3600
        if age_h > CFG.risk.max_holding_h and pos.profit < 0:
            return Proposal(kind="close_position", direction=direction, entry=pos.ticket,
                            reasons=[f"持仓 {age_h:.1f} 小时且亏损"])
        # ---- 保护性移损（用户规则：利润 > $10 时，把 SL 推到盈利 $2 处，锁底搏上限）----
        # `point_value_per_lot` 的单位是「每 **point** / 每手」的美元数
        # （XAUUSDm: point=0.001，值为 0.1，见 position_lots 里
        #  `sl_points * point_value_per_lot`）。
        # 要换算成「每 1.0 价格单位 / 每手」须除以**该品种的** point：
        #     XAUUSDm: 0.1 / 0.001 = $100
        # ⚠️ 这里原先硬编码 `/ _POINT`(=0.001)。多品种下必须用品种实际 point，
        #    否则 EURUSDm（point=0.00001）算出的 usd_per_price_unit 会差 100 倍，
        #    锁盈止损距离随之差 100 倍 → 要么贴太近被扫、要么远到无意义。
        #    注意 `_point(ctx)` 与 `point_value_per_lot` 必须**同源**
        #    （都由 SymbolProfile.point 推出），两者是配套的。
        # ⚠️ 原实现写 `2.0 / (point_value_per_lot * volume)`，漏了 /point，
        #    算出 SL = 开仓价 + 2000（远超现价）→ MT5 报 'Invalid stops'，
        #    移损从未成功过一次。
        # ⚠️ 已删除「保本锁盈」分支（利润 > $10 -> 止损推到开仓价上方 $2），
        #    连同它专用的 `profit_locked_sl` / `sl_still_open` /
        #    第二份 `usd_per_price_unit` 一起删除。
        #    它是**不可达死代码**，证明如下：
        #      · 走到这里要求 SL 仍在**亏损侧**（LONG: sl < price_open）。
        #      · 而上方「移动止损锁盈」分支的条件正是
        #        `profit >= lock_profit_min_usd(8)` 且 SL 仍在亏损侧，命中即 return。
        #      · 于是能到达本行的浮盈必然 < 8 美元，`profit > 10.0` **恒为假**。
        #    实测印证：该分支最后一次触发 09-22 20:23（共 8 次），此后被
        #    「移动止损锁盈」完全取代（411 次），13 天零触发。
        #    用户明确要求"不能放一个没有作用的死代码在那"，故删除。
        return Proposal(kind="hold",
                        reasons=[f"持仓 {direction_label(direction)} {age_h:.1f} 小时 "
                                 f"S_eff={s:+.2f}"])
