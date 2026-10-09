"""品种档案（SymbolProfile）：多品种交易的**唯一**参数来源。

为什么需要这个模块
==================
系统原先只做 XAUUSDm，品种相关的量散落在各处硬编码，其中**有些是隐患**：

  · `decision/machine.py`  `_PX_DIGITS = 3`、`_POINT = 0.001`
  · `risk/position.py`     `sl_points = sl_dist / 0.001`
  · `agent/graph.py`       `_point_value()` 里 `0.001 / tick_size`
  · `agent/graph.py`       `get_smc("XAUUSD", ...)` venue 写死 commodity:spot
  · `mt5/executor.py`      `"symbol": CFG.mt5.symbol`
  · `news/collector.py`    `_GOLD_KEYWORDS`
  · `llm/orchestrator.py`  提示词写"你是资深黄金（XAUUSD）交易评审员"

实测后果（真实券商规格 + 真实代码执行）：

  1. **价格规整会错价 → 重演重复下单事故**
     `_PX_DIGITS=3` 对 EURUSDm（digits=5）：
         真实止损 1.12419 --round(,3)--> 1.12400，偏 **19 个 point**。
     这与 2026-09-30 那次"同一持仓重复提交 83 次"是同一类故障：
     提交值与 MT5 存回值永不相等 → 幂等判定不收敛。
     ⚠️ `executor._build_request` 那层**已经正确**用了 `si.digits`，
        所以只有决策层内部自比的路径会错。

  2. **手数换算"碰巧"是对的，但极脆弱**
     `sl_points = sl_dist / 0.001` 与
     `point_value = tick_value * (0.001 / tick_size)`
     两处的 `0.001` **同源自消**，实测 5 个品种下
     `per_lot_risk` 与"正确公式"完全一致。
     → 所以**不能只改一处**：任何一处单独改成按 point 计算，
       立刻产生成百倍的手数误差（EURUSDm 是 100 倍）。

  3. 跟踪止损里的 `_POINT` 除法也同样自消，必须与 (2) 一起改。

设计原则
--------
  · 每个品种一个 `SymbolProfile`，所有品种相关量**只从这里取**。
  · `point`/`digits` 以**券商实际值**为准（MT5 `symbol_info`），
    不是写死的猜测 —— 见 PROFILE 里的券商实测值。
  · Mobius 映射必须按 **venue + symbol** 给出，因为同一个品种在不同
    venue 下名字不同（BTCUSDm → binance:spot 的 `BTCUSDT`），
    且**各 venue 支持的周期不同**（forex 与 commodity:futures 只有 1h/1d）。
  · 缺周期由 `aggregate_tf_scores` 的覆盖率收缩处理（不重分配），
    所以这里只声明"该品种能取到哪些周期"，不伪造数据。
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Mobius venue 实测能力（2026-10-09 用官方 /api/markets 查得）
# ---------------------------------------------------------------------------
# ⚠️ 这张表是**硬事实**，不要凭印象改。各 venue 支持的周期差异极大，
#    直接决定该品种能拿到几个 SMC 周期：
#        binance:spot     1m 5m 15m 1h 4h 1d   ← 只有它能给全套
#        commodity:spot   5m 15m 30m 1h 4h 1d  ← 黄金（当前 status=degraded）
#        commodity:futures 1h 1d                ← 油（WTIUSD）只有两个周期
#        forex:spot       1h 1d                 ← 欧元/日圆只有两个周期
#    请求不支持的周期会返回 **400**（不是降级），所以必须按此表裁剪。
VENUE_INTERVALS: dict[str, tuple[str, ...]] = {
    "binance:spot": ("1m", "5m", "15m", "1h", "4h", "1d"),
    "binance:perp": ("1m", "5m", "15m", "1h", "4h", "1d"),
    "commodity:spot": ("5m", "15m", "30m", "1h", "4h", "1d"),
    "commodity:futures": ("1h", "1d"),
    "forex:spot": ("1h", "1d"),
}


@dataclass(frozen=True)
class SymbolProfile:
    """一个可交易品种的全部品种相关参数。

    `broker_symbol` 是 MT5 侧的名字（券商后缀 m），
    `mobius_*` 是信号源侧的名字 —— 两者**不通用**，必须分开。
    """

    #: MT5 侧品种名（下单/取行情用）
    broker_symbol: str
    #: 展示用简称（日志/提示词）
    label: str
    #: 报价小数位（券商实测）。**所有提交给 MT5 的价格必须按它规整**。
    digits: int
    #: 最小价格变动单位（券商实测）。
    point: float
    #: 该品种的策略 magic（见下方说明）
    magic: int
    #: Mobius SMC 源映射；None 表示该品种无 SMC 数据
    mobius_exchange: str | None = None
    mobius_market: str | None = None
    mobius_symbol: str | None = None
    #: 该品种的新闻关键词（替代原 `_GOLD_KEYWORDS`）
    news_keywords: tuple[str, ...] = ()
    #: 提示词里的品种描述（替代"黄金（XAUUSD）"）
    prompt_asset: str = ""
    #: 每品种单笔风险占净值比例（组合总风险 = 各品种之和，见 risk/portfolio.py）
    risk_pct: float = 0.005
    #: 每品种总手数上限（覆盖 CFG.max_lot）
    max_lot: float = 0.06
    #: 每品种每日最大开仓次数（0 = 不限制）
    max_trades_per_day: int = 0

    # ---------- 派生量 ----------
    @property
    def mobius_venue(self) -> str | None:
        if self.mobius_exchange is None or self.mobius_market is None:
            return None
        return f"{self.mobius_exchange}:{self.mobius_market}"

    @property
    def has_smc(self) -> bool:
        return self.mobius_symbol is not None

    def supported_intervals(self) -> tuple[str, ...]:
        """该品种在 Mobius 上**实际可用**的周期（空元组 = 无 SMC）。"""
        v = self.mobius_venue
        if v is None:
            return ()
        return VENUE_INTERVALS.get(v, ())

    def smc_intervals(self, wanted: tuple[str, ...]) -> tuple[str, ...]:
        """把"想要的周期"裁剪成"该品种真正支持的周期"。

        请求不支持的周期会让 Mobius 返回 400（不是降级），所以必须裁剪。
        """
        ok = set(self.supported_intervals())
        return tuple(tf for tf in wanted if tf in ok)


# ---------------------------------------------------------------------------
# 品种档案表
# ---------------------------------------------------------------------------
# ⚠️ magic 分配：**每个品种必须不同**。原因：全仓库的"我的持仓/挂单"过滤
#    只按 magic 判断（`p.magic == CFG.mt5.magic`），**没有任何一处按 symbol 过滤**。
#    若多品种共用同一 magic：
#      · 每个品种会把**别的品种的持仓**当成自己的
#      · 已用总手数会把所有品种加在一起算 → 加仓额度判定全错
#      · 止损/平仓提案可能发到别的品种的持仓上
#    独立 magic 后，这些过滤逻辑**自动变正确**，无需逐个改判断条件。
#
# ⚠️ XAUUSDm 的 magic 保持 20260918 **不变**：
#    它是当前实盘正在用的值，历史数据（trades.jsonl / MT5 交割单 /
#    research 脚本）全按这个 magic 归档。改动会导致历史无法衔接。
MAGIC_BASE = 20260918

PROFILES: dict[str, SymbolProfile] = {
    # ---- 黄金：现有品种，参数与行为完全保持不变 ----
    "XAUUSDm": SymbolProfile(
        broker_symbol="XAUUSDm", label="黄金",
        digits=3, point=0.001, magic=20260918,
        mobius_exchange="commodity", mobius_market="spot", mobius_symbol="XAUUSD",
        news_keywords=("黄金", "金价", "XAU", "美元", "美联储", "非农", "CPI", "PCE",
                       "利率", "降息", "加息", "地缘", "战争", "关税", "通胀", "就业"),
        prompt_asset="黄金（XAUUSD）",
        risk_pct=0.005, max_lot=0.06),
    # ---- 比特币：合约 1.0、digits=2、point=0.01（券商实测）----
    "BTCUSDm": SymbolProfile(
        broker_symbol="BTCUSDm", label="比特币",
        digits=2, point=0.01, magic=MAGIC_BASE + 1,
        mobius_exchange="binance", mobius_market="spot", mobius_symbol="BTCUSDT",
        news_keywords=("比特币", "BTC", "加密货币", "美联储", "美元", "CPI",
                       "利率", "降息", "加息", "ETF", "监管"),
        prompt_asset="比特币（BTCUSD）",
        risk_pct=0.005, max_lot=0.06),
    # ---- 原油：Mobius 用 commodity:futures 的 WTIUSD（**只有 1h/1d**）----
    #  ⚠️ commodity:spot 下没有油（实测 404），WTIUSD 在 commodity:futures。
    "USOILm": SymbolProfile(
        broker_symbol="USOILm", label="原油",
        digits=3, point=0.001, magic=MAGIC_BASE + 2,
        mobius_exchange="commodity", mobius_market="futures", mobius_symbol="WTIUSD",
        news_keywords=("原油", "油价", "WTI", "布伦特", "OPEC", "欧佩克", "EIA",
                       "库存", "美元", "地缘", "减产", "增产"),
        prompt_asset="原油（WTI）",
        risk_pct=0.005, max_lot=0.06),
    # ---- 欧元：forex:spot 只有 1h/1d；digits=5 是最容易触发错价的品种 ----
    "EURUSDm": SymbolProfile(
        broker_symbol="EURUSDm", label="欧元",
        digits=5, point=0.00001, magic=MAGIC_BASE + 3,
        mobius_exchange="forex", mobius_market="spot", mobius_symbol="EURUSD",
        news_keywords=("欧元", "EUR", "美元", "美联储", "欧洲央行", "ECB", "CPI",
                       "利率", "非农", "通胀"),
        prompt_asset="欧元兑美元（EURUSD）",
        risk_pct=0.005, max_lot=0.06),
    # ---- 日圆：同上，forex:spot 只有 1h/1d ----
    "USDJPYm": SymbolProfile(
        broker_symbol="USDJPYm", label="日圆",
        digits=3, point=0.001, magic=MAGIC_BASE + 4,
        mobius_exchange="forex", mobius_market="spot", mobius_symbol="USDJPY",
        news_keywords=("日圆", "日元", "JPY", "美元", "日本央行", "BOJ", "日银",
                       "利率", "干预", "非农"),
        prompt_asset="美元兑日圆（USDJPY）",
        risk_pct=0.005, max_lot=0.06),
}


def get_profile(symbol: str | None = None) -> SymbolProfile:
    """按品种名取档案。

    未注册的品种**不静默兜底**：多品种下静默用一个错的点值/小数位会
    直接开出错价格的单，且幂等判定不收敛。宁可显式报错。
    """
    if not symbol:
        from gold_agent.common.config import CFG
        symbol = CFG.mt5.symbol
    p = PROFILES.get(symbol)
    if p is None:
        raise KeyError(
            f"未注册的品种 {symbol!r}。请在 symbols.py 的 PROFILES 中登记 "
            f"（需要 digits/point/magic/mobius 映射）。已注册：{sorted(PROFILES)}")
    return p


def profile_by_magic(magic: int) -> SymbolProfile | None:
    for p in PROFILES.values():
        if p.magic == magic:
            return p
    return None


def all_magics() -> tuple[int, ...]:
    return tuple(p.magic for p in PROFILES.values())


def registered_symbols() -> tuple[str, ...]:
    return tuple(PROFILES)
