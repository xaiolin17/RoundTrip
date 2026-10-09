"""组合级（多品种）风险闸。

为什么需要这个模块
==================
单品种时"每品种风控"**恰好等于**"账户风控" —— 因为账户里只有这一个品种。
所以原设计里没有任何组合级概念，这不是疏忽，而是当时不需要。

多品种后下列风险是**新出现**的，逐品种风控**结构上无法覆盖**：

1. **风险预算被倍数放大。**
   每品种各自按 `risk_pct`（0.5%）独立算手数。5 个品种同时开仓 =
   单次总风险 **2.5%**，而不是 0.5%。而且品种间可能高度相关
   （黄金/原油/欧元都受美元与实际利率驱动），相关性高时
   等于**同一个方向下了 5 倍注** —— "分散"是名义上的，不是实质上的。

2. **熔断口径失效。**
   各品种的 `CircuitBreakers` 只看自己的盈亏序列。组合整体回撤 12% 时，
   若每个品种各自都只回撤了 3%，就**没有任何一个品种触发熔断** ——
   总亏损已经很大，系统却认为"一切正常"。这是本模块最关键的职责。

3. **保证金集中。**
   逐品种的 `margin_use_cap` 各自判断，多品种并发下单可能一起
   把可用保证金吃光，导致强平或后续信号无法执行。

4. **同向集中。**
   "5 个品种都看多"在宏观上是一个仓位，不是五个。缩仓只能减损，
   不能消除"判断错就全错"的结构性风险，所以同向数超限按**拒开**处理。

设计原则
--------
· **只收紧、不放松**：本模块只在逐品种风控已通过的前提下**再拒绝**
  或**再缩仓**，绝不会让本来会被拒的单通过。
· **单品种时全部空操作**（见 `_is_active`），所以现有黄金实盘行为不变。
· 拒绝码保持英文（项目约定：机器可读的码不翻译，显示层翻译）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import log_warn


@dataclass
class PortfolioVerdict:
    """组合闸的判定结果。"""

    ok: bool
    reason: str | None = None
    #: 按比例缩放手数（1.0 = 不缩）
    lot_mult: float = 1.0


@dataclass
class PortfolioState:
    """组合闸的**跨品种**输入快照，由 runner 汇总后传入。"""

    #: 各品种**已持仓**的风险预算（占净值比例），不含本次要开的这一笔
    risk_by_symbol: dict[str, float] = field(default_factory=dict)
    #: 各品种当前持仓方向：{品种: "LONG"|"SHORT"|None}
    direction_by_symbol: dict[str, str | None] = field(default_factory=dict)
    #: 各品种保证金占用（账户货币）
    margin_by_symbol: dict[str, float] = field(default_factory=dict)
    #: 账户净值
    equity: float = 0.0
    #: 组合**纯交易盈亏**（净值 − 净出入金）
    pnl_now: float = 0.0


def _is_active() -> bool:
    """单品种时组合闸**全部空操作**。

    ⚠️ 这条保证多品种支持不改变现有黄金实盘行为 ——
    单品种下所有闸直接放行，与改造前逐字节一致。
    """
    return CFG.multi_symbol


class PortfolioRisk:
    """组合级风险闸（跨品种）。"""

    def __init__(self, symbols: tuple[str, ...] | None = None) -> None:
        self.symbols = tuple(symbols) if symbols else tuple(CFG.trade_symbols)
        self.peak_pnl: float = 0.0
        self.anchored: bool = False
        #: 各品种**最近一次观测到**的持仓方向：{品种: "LONG"|"SHORT"|None}。
        #
        # ⚠️ 为什么需要这个共享登记表：同向集中闸（"5 个品种都看多其实是
        #    一个仓位"）必须看到**其它**品种的方向。但各品种是 asyncio
        #    并发跑的，每个 Graph 只看得到自己的持仓（按 magic 过滤），
        #    拿不到别人的。故由各品种每轮**上报**自己观测到的方向，
        #    再从这里读取全局视图。
        #
        # ⚠️ 这是**近似**：并发下读到的是"最近一次"的值，可能比当前
        #    实际持仓**晚一轮**（60 秒）。对同向集中判定是可接受的 ——
        #    持仓方向不会在 60 秒内大规模翻转，且该闸本身是保守的
        #    （宁可误判为集中而拒开，不可漏放）。真正的持仓仍以
        #    `st["positions"]`（按 magic 过滤）为准，用于别的用途。
        self.directions: dict[str, str | None] = {
            s: None for s in self.symbols}

    def report_direction(self, symbol: str, direction: str | None) -> None:
        """某品种上报它观测到的自身持仓方向（每轮调用一次）。"""
        self.directions[symbol] = direction

    def direction_map(self) -> dict[str, str | None]:
        """全局方向视图（含所有品种，未观测到的为 None）。"""
        return dict(self.directions)

    # ---------- 组合回撤 ----------
    def update_pnl(self, pnl_now: float) -> None:
        """更新组合纯交易盈亏并维护峰值。

        ⚠️ 首个观测值直接作为锚点（**不是 0**）：与 `CircuitBreakers`
        同理 —— 若锚成 0，账户已经亏损时会凭空造出一段回撤，
        启动即熔断。
        """
        if not self.anchored:
            self.peak_pnl = float(pnl_now)
            self.anchored = True
        self.peak_pnl = max(self.peak_pnl, float(pnl_now))

    def drawdown(self, pnl_now: float, equity: float) -> float:
        """组合回撤（占净值比例）。"""
        if equity <= 0:
            return 0.0
        return max(0.0, (self.peak_pnl - float(pnl_now)) / float(equity))

    # ---------- 主判定 ----------
    def check_for(self, symbol: str, this_risk: float,
                  state: PortfolioState,
                  this_direction: str | None = None) -> PortfolioVerdict:
        """开新仓前的组合闸。

        `symbol`         ：本次要开的品种。
        `this_risk`      ：**本笔**的单笔风险（占净值比例）。
        `state`          ：组合快照，其中 `risk_by_symbol` **不含**本笔。
        `this_direction` ：**本笔要开的方向**（"LONG"/"SHORT"）。

        ⚠️ `this_direction` 必须由调用方显式传入，**不能**从
        `state.direction_by_symbol[symbol]` 推 —— 那个字段是
        "该品种**已有持仓**的方向"，而正在开新仓时它恰恰是 `None`
        （还没有持仓）。早先的实现就是去读它，于是同向集中闸
        **永远不触发**（测试实测：3 个品种已做多，第 4 个再做多仍放行）。
        这是在最需要它的时刻静默失效 —— 典型的接线错误。

        ⚠️ 判据是"**含本笔**"的合计风险，不是"当前已有"的风险 ——
        否则最后一笔永远能通过，总风险总能超标。
        """
        if not _is_active():
            return PortfolioVerdict(ok=True)          # 单品种：空操作

        # ---- 1. 组合总回撤熔断（最关键：各品种各自未到线时由它兜底）----
        dd = self.drawdown(state.pnl_now, state.equity)
        cap_dd = CFG.risk.portfolio_drawdown_halt_pct
        if dd >= cap_dd:
            log_warn(f"组合回撤熔断：{dd:.1%} >= {cap_dd:.1%}，暂停开新仓")
            return PortfolioVerdict(ok=False,
                                    reason=f"portfolio_drawdown {dd:.1%}")

        # ---- 2. 组合总风险预算 ----
        # 排除本品种：本笔风险由 this_risk 单独给出，若把该品种的旧仓风险
        # 也计进来会与"本笔"重复，导致过早缩仓。
        have = sum(float(v) for k, v in state.risk_by_symbol.items()
                   if k != symbol)
        cap_risk = CFG.risk.portfolio_risk_cap
        total = have + max(0.0, float(this_risk))
        if total > cap_risk + 1e-12:
            room = max(0.0, cap_risk - have)
            if this_risk <= 1e-12 or room <= 1e-12:
                log_warn(f"组合风险预算已满：{have:.3%} / {cap_risk:.1%}，拒绝开仓")
                return PortfolioVerdict(ok=False,
                                        reason="portfolio_risk_exhausted")
            mult = min(1.0, room / float(this_risk))
            log_warn(f"组合总风险 {total:.2%} 超预算 {cap_risk:.1%}"
                     f"，本笔手数缩至 {mult:.0%}")
            return PortfolioVerdict(ok=True, lot_mult=mult,
                                    reason=f"portfolio_risk_scale {mult:.2f}")

        # ---- 3. 同向品种数上限 ----
        # 用**本笔要开的方向**（this_direction），不是该品种已有持仓的方向。
        limit = int(CFG.risk.portfolio_max_same_direction)
        d = this_direction
        if limit > 0 and d:
            n = sum(1 for k, v in state.direction_by_symbol.items()
                    if k != symbol and v
                    and str(v).upper() == str(d).upper())
            if n >= limit:
                log_warn(f"同向（{d}）已有 {n} 个品种，达到上限 {limit}，拒绝开仓")
                return PortfolioVerdict(
                    ok=False,
                    reason=f"portfolio_same_direction {d}={n}>={limit}")

        # ---- 4. 组合保证金 ----
        if state.margin_by_symbol:
            used = sum(float(v) for v in state.margin_by_symbol.values())
            mcap = CFG.risk.portfolio_margin_cap
            if state.equity > 0 and used > mcap * state.equity:
                log_warn(f"组合保证金占用 {used:.0f} 超上限 "
                         f"{mcap:.0%} 净值，拒绝开仓")
                return PortfolioVerdict(ok=False, reason="portfolio_margin_cap")

        return PortfolioVerdict(ok=True)


def build_state(symbols, positions_by_symbol, equity: float, pnl_now: float,
                risk_pct: float) -> PortfolioState:
    """由各品种的持仓汇总出组合快照。

    `positions_by_symbol`：{品种: 方向 or None}（有持仓才非 None）。
    `risk_pct`：单品种单笔风险占净值比例（`SymbolProfile.risk_pct`）。

    ⚠️ 这是**近似**：把每个已持仓品种都按其满额 `risk_pct` 计入。
    精确值需按各自实际 SL 距离反推，但那要逐品种查 MT5，
    且组合层拿不到统一口径。用满额计入是**保守**方向
    （高估已用风险 → 更早缩仓），符合"只收紧"原则。
    """
    risk = {s: float(risk_pct) for s, d in positions_by_symbol.items() if d}
    return PortfolioState(
        risk_by_symbol=risk,
        direction_by_symbol=dict(positions_by_symbol),
        margin_by_symbol={},
        equity=float(equity), pnl_now=float(pnl_now))
