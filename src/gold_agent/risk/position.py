"""仓位管理（docs/05 §1-2）与熔断器（§5）。"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import log_info, log_warn


@dataclass
class CircuitBreakers:
    """硬风控熔断（不可被 LLM/状态机绕过，docs/05 §5）。

    P2-2：新增「方向偏置」熔断。research/16 显示系统 3 笔交割单全为 LONG、
    融合分 80.2% 为正——**结构性做多**。近 N 笔同向占比过高即停机复查，
    因为那说明系统不是在择时，而是在单边押注方向。
    """
    consecutive_losses: int = 0
    cooloff_until: float = 0.0
    day_pnl: float = 0.0
    day_key: str = ""
    peak_equity: float = 0.0
    #: ⚠️ 回撤用的**纯交易**权益峰值（累计交易盈亏的历史最高点）。
    #: 与 `peak_equity` 的区别见 `_dd()`：出入金不进这条曲线。
    peak_pnl: float = 0.0
    #: 累计已计入的净出入金（正=入金）。用于把净值折算成纯交易盈亏。
    net_deposits: float = 0.0
    #: 本金锚点是否已定（首次看到净值时锚定）
    anchored: bool = False
    #: 锚定时刻（`time.time()`）。用于识别"锚定之后才被读到的历史出入金"，
    #: 见 `on_cash_flow` 的补偿逻辑。
    anchor_ts: float = 0.0
    martin_disabled_today: bool = False
    #: 近期平仓方向序列（1=LONG, -1=SHORT），用于方向偏置检测
    recent_directions: list = field(default_factory=list)
    direction_bias_halt: bool = False
    direction_bias_reason: str = ""
    extra: dict = field(default_factory=dict)

    def on_cash_flow(self, profit: float, ts: float | None = None) -> None:
        """记一笔出入金（正=入金，负=出金）。

        ⚠️ 为什么必须剔除（2026-10-08 用户报告「从9.30号开始 效益就不好」）：
        旧公式 `dd = (峰值净值 − 当前净值) / 峰值净值` 把**出入金**当成了亏损。
        实测本账户 10-01 13:56 一笔 `-100150.57` 出金使净值 100,000 → 100，
        紧接着 23 轮全部返回 `circuit: max_drawdown 99.0%` ——
        而 magic=20260918 的**真正交易亏损只有 -46.43**，
        即 agent 把自己的风控误判成爆仓并停机。
        出入金是资金调动，不是策略表现。

        一般情况下这里**只累加**净出入金，不动峰值：因为纯交易盈亏
        `equity − net_deposits` 对出入金天然中性 —— 出金使 equity 与
        net_deposits 同额下降，差额不变。故锚定之后发生的出入金
        不需要（也不能）调整峰值。唯一的例外是下面 `ts` 描述的
        "锚定后才补读到的历史流水"，那种情况下峰值必须同额补偿。

        ts: 该笔出入金的成交时间。若它发生在**锚定时刻之前**却是锚定后
        才被读到（例如首次拉取流水失败、下一轮才补上），则它本应已计入
        锚点，必须把峰值同额挪回去，否则 `_pnl_now` 会瞬间偏离峰值一个
        `profit`，凭空造出巨额回撤。方向推导：
            锚点本应 = equity_锚定 − (nd_旧 + profit) = peak_pnl_旧 − profit
        故补偿是 **减**（`peak_pnl -= profit`），不是加。
        实测：迟到入金 +100000 若无补偿会造出 1043% 假回撤，
        补偿方向写反（+=）反而恶化到 2086%；`-=` 后为 0%。
        """
        profit = float(profit)
        if self.anchored and ts is not None and self.anchor_ts and float(ts) < self.anchor_ts:
            self.peak_pnl -= profit
        self.net_deposits += profit

    def _pnl_now(self, equity: float) -> float:
        """净值 → **纯交易累计盈亏**。

        `net_deposits` 是累计净出入金，`equity` 是当前净值，两者口径一致
        （净值 = 本金 + 累计出入金 + 交易盈亏），故二者之差就是纯交易盈亏。
        """
        return float(equity) - self.net_deposits

    def _dd(self, equity: float) -> float:
        """回撤比例 = (纯交易盈亏峰值 − 当前纯交易盈亏) / 当前净值。

        分母用**当前净值**（账户实际规模）而非历史出入金：
        否则净出入金一旦为负，比例会失去意义（本账户净出入金 +425665，
        纯盈亏 -416079，相除得到荒谬的分母）。

        峰值**可以**是负数（锚定时账户已累计亏损）——故只判 `anchored`，
        不能判 `peak_pnl > 0`，否则永远返回 0 而静默失效。
        """
        if not self.anchored:
            return 0.0
        loss = self.peak_pnl - self._pnl_now(equity)
        if loss <= 0.0:
            return 0.0
        return loss / max(float(equity), 1e-9)

    def check(self, account_equity: float, margin_used: float,
              high_risk_window: bool) -> str | None:
        """返回 REJECT 原因；None = 允许开仓。"""
        now = time.time()
        today = time.strftime("%Y-%m-%d")
        if self.day_key and self.day_key != today:
            self.day_key = today
            self.day_pnl = 0.0
            self.martin_disabled_today = False
        elif not self.day_key:
            self.day_key = today
        if self.direction_bias_halt:
            return f"direction_bias_halt: {self.direction_bias_reason}"
        # ---- 连续亏损熔断：冷却到期自动恢复（用户选定）----
        # ⚠️ 事故修复：原实现 cooloff 到期后只放行 cooloff 检查，
        #    但 consecutive_losses 仍 >= n -> 落到下面 L51 永远拦截，
        #    且只有**平仓**才改这个计数器 -> 拦截开仓 -> 无新交易 ->
        #    无平仓 -> 计数器永不归零 -> **永久死锁**。
        #    实测：3958 轮触发后 400+ 轮全部被拦，agent 完全停止交易。
        #    现在：cooloff 到期 -> 连亏计数归零 -> 自动恢复交易。
        if self.cooloff_until and now >= self.cooloff_until:
            log_warn(f"熔断冷却到期：连亏计数 {self.consecutive_losses} 归零，恢复交易")
            self.cooloff_until = 0.0
            self.consecutive_losses = 0
        if now < self.cooloff_until:
            return f"cooloff_until {time.strftime('%H:%M', time.localtime(self.cooloff_until))}"
        if self.consecutive_losses >= CFG.risk.consecutive_loss_n:
            return f"consecutive_losses>={CFG.risk.consecutive_loss_n}"
        if self.day_pnl <= -CFG.risk.daily_loss_stop_pct * account_equity:
            return "daily_loss_stop"
        # ---- 回撤熔断（基于**出入金中性**的纯交易盈亏曲线）----
        # 锚点只定一次。`peak_equity` 是历史净值峰值（旧状态文件里
        # 被自引用 bug 钉在 10000），它隐含的"本金+已实现盈亏"用来给
        # 纯盈亏曲线定起点；出入金已由 `on_cash_flow` 记入 net_deposits。
        pnl_now = self._pnl_now(account_equity)
        if not self.anchored:
            # 锚点 = 当前纯交易盈亏（**不是 0**）：此刻是"起点"，
            # 从下一轮起的净亏损才算回撤。写成 max(...,0) 会在账户已亏损时
            # 凭空造出回撤（例如纯盈亏 -500 锚成 0 → 立刻 -500 回撤）。
            self.peak_pnl = pnl_now
            self.anchored = True
            self.anchor_ts = time.time()
            log_info(f"回撤基准锚定：纯交易盈亏 {pnl_now:.2f}"
                     f"（净值 {account_equity:.2f} 减去净出入金 {self.net_deposits:.2f}）")
        self.peak_pnl = max(self.peak_pnl, pnl_now)
        dd = self._dd(account_equity)
        if dd >= CFG.risk.max_drawdown_halt_pct:
            return f"max_drawdown {dd:.1%}"
        if margin_used > CFG.risk.margin_use_cap * account_equity:
            return "margin_cap"
        if high_risk_window:
            return "news_high_risk_window"
        # 周五深夜不开新仓
        if time.localtime().tm_wday == 4 and time.localtime().tm_hour >= 23 and time.localtime().tm_min >= 30:
            return "friday_late"
        return None

    # ---------- P2-2 方向偏置监控 ----------
    def record_direction(self, direction: str | int | None) -> None:
        """记录一笔平仓的方向（LONG/SHORT 或 1/-1）。"""
        if direction is None:
            return
        if isinstance(direction, str):
            d = 1 if direction.upper() in ("LONG", "BUY") else (
                -1 if direction.upper() in ("SHORT", "SELL") else 0)
        else:
            d = int(direction)
        if d == 0:
            return
        self.recent_directions.append(d)
        win = max(int(CFG.risk.direction_bias_window), 2)
        if len(self.recent_directions) > win:
            del self.recent_directions[: len(self.recent_directions) - win]
        self._check_direction_bias()

    def _check_direction_bias(self) -> None:
        n = len(self.recent_directions)
        if n < max(int(CFG.risk.direction_bias_min_samples), 2):
            return
        longs = sum(1 for d in self.recent_directions if d > 0)
        ratio = max(longs, n - longs) / n
        if ratio > CFG.risk.direction_bias_max:
            side = "LONG" if longs > n - longs else "SHORT"
            self.direction_bias_halt = True
            self.direction_bias_reason = (
                f"{n} 笔中 {ratio:.0%} 为 {side}（阈值 {CFG.risk.direction_bias_max:.0%}）")

    def clear_direction_bias(self) -> None:
        """人工复查后解除偏置停机。"""
        self.direction_bias_halt = False
        self.direction_bias_reason = ""
        self.recent_directions = []

    @property
    def direction_bias_ratio(self) -> float:
        n = len(self.recent_directions)
        if n == 0:
            return 0.0
        longs = sum(1 for d in self.recent_directions if d > 0)
        return max(longs, n - longs) / n

    def deleverage_k(self, account_equity: float) -> float:
        dd = self._dd(account_equity)
        if dd >= CFG.risk.max_drawdown_halt_pct:
            return 0.0
        if dd >= CFG.risk.max_drawdown_deleverage_pct:
            return 0.5
        return 1.0

    def on_trade_closed(self, pnl: float, equity: float,
                        direction: str | int | None = None) -> None:
        today = time.strftime("%Y-%m-%d")
        if self.day_key and self.day_key != today:
            self.day_key = today
            self.day_pnl = 0.0
            self.martin_disabled_today = False
        elif not self.day_key:
            self.day_key = today
        self.day_pnl += pnl
        if pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= CFG.risk.consecutive_loss_n:
                self.cooloff_until = time.time() + CFG.risk.consecutive_loss_cooloff_h * 3600
        else:
            self.consecutive_losses = 0
        # 峰值按**纯交易盈亏**（出入金中性）更新；`peak_equity` 保留为
        # 历史净值峰值的记录，不再参与回撤计算（旧状态里的自引用 bug 见
        # `deal_feedback.poll`）。
        self.peak_equity = max(self.peak_equity, equity)
        if self.anchored:
            self.peak_pnl = max(self.peak_pnl, self._pnl_now(equity))
        self.record_direction(direction)

    # ---------- 持久化 ----------
    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "CircuitBreakers":
        obj = cls()
        for k, v in d.items():
            if hasattr(obj, k):
                setattr(obj, k, v)
        return obj

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "CircuitBreakers":
        if path.exists():
            try:
                return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except Exception as e:
                log_warn(f"熔断器状态读取失败: {e}")
        return cls()


def half_kelly(p: float, b: float) -> float:
    """f* = (p·b − q)/b，返回一半（Half-Kelly）。p=胜率, b=盈亏比。"""
    q = 1 - p
    f = (p * b - q) / b
    return max(0.0, f) * 0.5


def wilson_lower(wins: int, n: int, z: float = 1.96) -> float:
    """Wilson score 置信下界（P2-3）。

    为什么不用点估计：3 笔 1 胜的胜率点估计是 0.333，看起来"还行"；
    但 3 笔样本的 95% 置信区间是 [6%, 79%] —— 它不能支持任何结论。
    Wilson 下界给 0.061，仓位会自动缩到最小。

    research/18 §P2-3：`deal_feedback.current_win_rate()` 在样本 < 10 时
    返回 0.5 冷启动，但 **3 笔就参与 Kelly 计算是危险的**。
    """
    if n <= 0:
        return 0.0
    ph = wins / n
    d = 1 + z * z / n
    c = ph + z * z / (2 * n)
    r = z * math.sqrt(max(ph * (1 - ph) / n + z * z / (4 * n * n), 0.0))
    return max(0.0, (c - r) / d)


def conservative_win_rate(wins: int, n: int, fallback: float = 0.5,
                          min_samples: int | None = None) -> float:
    """用于仓位计算的保守胜率：Wilson 下界 + 样本量门槛（P2-3）。

    样本 < min_samples 时返回 fallback（冷启动），因为此时任何估计都不可信；
    样本足够时返回 Wilson 下界（而非点估计），使小样本自动缩仓。
    """
    thr = CFG.risk.min_deals_for_kelly if min_samples is None else min_samples
    if n < max(int(thr), 1):
        return fallback
    return wilson_lower(wins, n)


def position_lots(equity: float, atr: float, point_value_per_lot: float,
                  win_rate: float, vol_k: float = 1.0,
                  volume_min: float = 0.01, volume_step: float = 0.01,
                  volume_max: float = 10.0,
                  sl_dist: float | None = None,
                  reserve_lots: float = 0.0,
                  point: float = 0.001) -> tuple[float, str | None]:
    """风险预算 + Half-Kelly 上限 + 波动率目标系数。

    返回 (lots, reject_reason)。

    `sl_dist`：**实际**止损距离（价格单位）。缠论结构定价启用后，止损宽度
    由 0.618 回调位决定，与 ATR 无关；仓位必须按同一个距离反推，
    否则单笔风险会随止损加宽等比放大（实测 4h 分型两倍 149 → 单笔
    风险 1.49% 而非预算的 0.5%）。传 None 时退回 ATR 距离（旧行为）。

    `point`：该品种的最小价格变动单位（`SymbolProfile.point`）。默认 0.001
    保持单品种（XAUUSDm）行为不变。

    ⚠️ `point` 与 `point_value_per_lot` 必须**同源**（都来自同一个
       `SymbolProfile.point`）。它们是配套的一对：
           sl_points    = sl_dist / point
           per_lot_risk = sl_points * point_value_per_lot
       代入 `point_value_per_lot = tick_value * (point / tick_size)` 得
           per_lot_risk = sl_dist * tick_value / tick_size
       即 point **在代数上消掉**，结果与品种无关。
       这正是原实现的真实情形：两处各自硬编码 0.001，于是"碰巧正确"。
       实测 5 个品种（含 EURUSDm 的 0.00001）per_lot_risk 与正确公式一致。
       但这是**脆弱的巧合** —— 只改一处会产生成百倍的手数误差
       （EURUSDm 恰好 100 倍）。修改时必须两处一起改。

    最小手数兜底（用户选定）
    ------------------------
    原实现是：算出的手数 < volume_min 就返回 `risk_budget_below_min_lot`
    **拒绝开仓**。但 0.01 手是交易所下限，**不能再往下取整** ——
    于是缩仓系数（vol_k）在仓位已到地板时，从"让仓位变小"变成了
    "不许交易"。

    实测事故：vol_k=0.125（波动下限 0.25 × 分歧 0.5）→ 预算 8.64 USD
    → 止损上限仅 8.6 点，而实际止损 7.5~20.8 点 → 强信号轮次被连续拦截
    （3514/3515）。而 0.01 手 + 20 点止损 = 20.82 USD = 权益的 0.145%，
    **远低于** risk_pct 允许的 0.500%（69.10 USD）——
    系统在拒绝一个风险只有自设上限 29% 的仓位。

    现在：只要 **0.01 手的实际风险仍在名义预算内**（不受 vol_k 压缩影响），
    就按最小手数开仓。缩仓系数不再能阻止交易，硬风控（熔断、Kelly、
    名义预算）依然生效。
    """
    if atr is None or atr <= 0:
        return 0.0, "no_atr"
    nominal_risk_usd = equity * CFG.risk.risk_pct   # 名义预算（不含 vol_k）
    risk_usd = nominal_risk_usd
    # Half-Kelly 上限
    b = CFG.risk.tp_atr_mult / CFG.risk.sl_atr_mult
    f_half = half_kelly(win_rate, b)
    kelly_cap_usd = equity * f_half * 0.10     # 保守：Kelly 折 10% 上限
    risk_usd = min(risk_usd, kelly_cap_usd) if kelly_cap_usd > 0 else risk_usd
    # 波动率目标系数（外部传入 vol_k）
    risk_usd *= vol_k
    if sl_dist is None:
        sl_dist = CFG.risk.sl_atr_mult * atr          # 旧行为：按 ATR
    # ⚠️ 用**该品种的** point，不是硬编码 0.001。必须与
    #    `graph._point_value()` / `machine._point(ctx)` 同源（见 docstring）。
    sl_points = sl_dist / (point or 0.001)
    per_lot_risk = sl_points * point_value_per_lot
    if per_lot_risk <= 0:
        return 0.0, "bad_point_value"
    raw_lots = risk_usd / per_lot_risk
    lots = math.floor(raw_lots / volume_step) * volume_step
    lots = round(lots, 2)
    if lots < volume_min:
        # ---- 最小手数兜底：0.01 手能否被**名义**预算容纳 ----
        min_lot_risk = volume_min * per_lot_risk
        if min_lot_risk <= nominal_risk_usd:
            # 风险可接受，只是缩仓系数把它压到了地板以下 → 按最小手数开
            return round(volume_min, 2), None
        return 0.0, "risk_budget_below_min_lot"
    lots = min(lots, volume_max, CFG.max_lot if CFG.trade_mode == "live" else volume_max)
    # 为**后续加仓**预留额度（用户选定：首仓封顶，保证 5 层加仓可达）。
    # `.env` 写明 `MAX_LOT=0.06 = 基础仓 0.01 + 5×0.01 加仓`，但首仓手数由本函数
    # 独立算出、原实现**不看加仓额度** —— 实测 198 笔首仓里 34 笔直接顶到 0.06，
    # 剩余额度归零，于是 259 次加仓被"总手数上限"拒掉（0 次成功）。
    # 这里把首仓压到"总上限 − 计划加仓额度"，使加仓阶梯真正可达。
    if reserve_lots > 0:
        # ⚠️ 必须先四舍五入再比较：`0.06 − 5×0.01` 在浮点下是
        # 0.009999999999999995，直接跟 0.01 比会判成"放不下"而**跳过预留**
        # （实测：加了预留逻辑但首仓仍是 0.06）。
        head = round(CFG.max_lot - reserve_lots, 2)
        if head >= volume_min:
            lots = min(lots, round(math.floor(round(head / volume_step, 6)) * volume_step, 2))
            lots = round(lots, 2)
    return lots, None


def volatility_k(realized_vol_daily: float | None, atr_daily_ratio: float | None) -> float:
    """docs/05 §2：目标波动 / 实际波动，clamp [0.25, 1.5]，黄金高波动日再 ×0.6。"""
    k = 1.0
    if realized_vol_daily and realized_vol_daily > 0:
        k = CFG.risk.target_vol_daily / realized_vol_daily
        k = float(np.clip(k, 0.25, 1.5))
    if atr_daily_ratio and atr_daily_ratio > 0.02:
        k *= 0.6
    return k
