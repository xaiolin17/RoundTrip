"""中枢位置判定（用户反馈：单子经常挂在中枢中部）。

用户原话
========
> 现在的单子下单位置没选好呢  要么在中枢两端下中枢的单子  要么做突破的单子
> 我经常看到中枢中部位置就下单了
> 还是以周期1m和5m为主

问题诊断（实测，见本模块 docstring 末尾）
======================================
实测 127 笔真实单子里 **123 笔**走的是 `非均值回归行情 -> 直接市价开仓`，
即 `decision/machine.py` 的：

    Proposal(kind="open_market", entry=ctx.last_close, ...)

入场价 = 上一根 1m 收盘价 = **价格此刻恰好在哪里**，全链路没有任何一行
代码读中枢。量化结果（配对零假设检验）：

    真实入场落在中枢/区间中间 60% 的比例   56.6%
    随机时刻按市价入场的对照比例          57.1%   （差 −0.5pp，不显著）

即系统择时与"随机时刻入场"在统计上**无法区分**——这正是"缺失中枢位置
逻辑"的必然结果。用户看到的"在中枢中部下单"是**真的**：到最近边缘的中位
距离 14.1 点，比整笔交易的止损距离（中位 9.78 点）还大。

周期选择（用户选定：5m 为主，1m 退化时回退 5m）
============================================
实测各周期中枢质量（1m 56815 根 / 5m 11383 根 / 15m 3795 根真实 MT5）：

    周期   宽度中位   /ATR   退化(zg==zd)
    1m      4.25      2.14    22/120 (18%)   <- 噪声大且会退化
    5m      9.43      1.77    29/118 (25%)
    15m    21.00      2.28    27/113 (24%)

所以优先 5m；1m 仅当 5m 拿不到有效中枢时兜底——1m 宽度太窄，
它自己的中枢边界往往落在噪音里，不能单独作为决策依据。

⚠️ 已知上游限制（本模块无法解决，如实记录）
==========================================
1. 中枢由 vendor 引擎的 `center_overlap_proxy`（滑动 3 段重叠）产出，
   **不是严格缠论中枢**；同一批 K 线可能产出多个高度重叠的中枢，
   `current_center_id` 指向的那个未必是交易员眼中的中枢。
   因此本模块只做**边界距离**判定，不声称级别归属正确。

   实测这个顾虑是**真实的**：走查 13 个 5m 窗口，
   `layers.centers` 有 8 次只给 1 个、**5 次给了 2~3 个**；
   其中 5 个窗口存在 ≥2 个"可用"中枢，与"离现价最近的那个"相比，
   **2/5 (40%) 会得出不同的贴边结论**（一个判 `above`、
   另一个判 `at_zg`）。样本很小，只作方向性证据，但说明
   "取 `current_center_id`"与"取最近中枢"不是等价选择。
   本模块目前沿用 adapter 的 `current_center_id`（改动最小、
   与既有分数口径一致），是否改取最近中枢需单独评估。

   用户选定"优先看小周期"：默认 `PRIMARY_TFS = ("5m", "1m")`，
   短周期中枢反应更快、更贴近入场择时的尺度。

2. `chanlun_adapter.trigger_gate` 恒为 False 并标注 `trigger_missing`。
   ⚠️ **更正一处早先的错误说法**：它**不会**限制 `output_mode`。
   `output_mode` 只由 `structure_gate`/`type_gate` + vendor 的
   `definition_mode` 决定（实测：两项都过、`failed=[]`、`all_passed=True`
   时，`output_mode` 仍是 `structure_proxy`，因为 vendor 自报
   `definition_mode = "research_proxy"`）。
   所以 trigger_gate 是**如实披露能力边界**，不影响分数、不阻塞下单。

3. 拿不到有效中枢时本模块返回 `ok=False`，调用方（决策层）**放行**。
   实测覆盖率（13 个 5m 窗口走查）：11/13 (84.6%) 能取到可用中枢，
   其中 9 次由 5m 提供、2 次回退 1m。所以闸的有效覆盖约 85%，
   剩余 15% 维持原有行为。
"""
from __future__ import annotations

from dataclasses import dataclass

#: 优先使用的周期（用户选定：5m 为主，1m 兜底）。
#: 用户强调"优先看小周期" —— 入场择时是 1m/5m 的尺度，
#: 用大周期（1h/4h）中枢判"贴边"会离现价太远而永不触发。
PRIMARY_TFS: tuple[str, ...] = ("5m", "1m")
#: 中枢宽度相对 ATR 的最小可用倍数（默认值；运行时以配置为准）。
#: 低于此值说明中枢被压扁，边界落在噪音里，拿它判断"靠近边缘"没有意义。
MIN_WIDTH_ATR = 0.25


def _min_width_atr() -> float:
    """宽度下限倍数，取 config.toml `[risk] zhongshu_min_width_atr`。"""
    try:
        from gold_agent.common.config import CFG
        return float(getattr(CFG.risk, "zhongshu_min_width_atr", MIN_WIDTH_ATR))
    except Exception:
        return MIN_WIDTH_ATR


@dataclass
class CenterView:
    """某周期的中枢视图 + 现价相对它的位置。"""
    ok: bool = False
    reason: str = ""
    tf: str = ""
    zg: float | None = None       # 上沿
    zd: float | None = None       # 下沿
    gg: float | None = None       # 最高点
    dd: float | None = None       # 最低点
    cid: str | None = None
    width: float = 0.0
    #: 现价在中枢内的归一化位置：0 = 贴下沿 zd，1 = 贴上沿 zg。
    #: <0 表示已跌到下沿之下，>1 表示已突破上沿之上。
    pos: float | None = None
    #: 到最近边界的距离（点数，恒 >= 0）
    dist_edge: float | None = None
    #: 本次尝试过的周期（按优先级）。用于确认"优先小周期"确实生效：
    #: `("5m","1m")` 表示先看 5m，退化/过窄/缺失时才回退 1m。
    considered: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        """落盘用（日志白名单放开后写进 signals 事件）。"""
        return {"tf": self.tf, "zg": self.zg, "zd": self.zd,
                "gg": self.gg, "dd": self.dd, "id": self.cid,
                "width": round(self.width, 3) if self.width else None,
                "pos": round(self.pos, 4) if self.pos is not None else None,
                "dist_edge": (round(self.dist_edge, 3)
                              if self.dist_edge is not None else None),
                "considered": list(self.considered) or None,
                "reason": self.reason or None}


def _f(v) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def center_of(chanlun_results: dict | None, last_close: float | None,
              atr: float | None = None,
              tfs: tuple[str, ...] = PRIMARY_TFS) -> CenterView:
    """按优先级取第一个**有效**中枢，并算出现价在其中的位置。

    有效性要求：`zg`/`zd` 都存在、`zg > zd`（否则是退化的零宽中枢）、
    且宽度 >= `MIN_WIDTH_ATR × ATR`（否则边界在噪音里）。

    返回 `ok=False` 时 `reason` 说明为什么拿不到，供日志与拒绝码使用。
    """
    out = CenterView()
    out.considered = tuple(tfs)
    if last_close is None or last_close <= 0:
        out.reason = "no_price"
        return out
    if not chanlun_results:
        out.reason = "no_chanlun"
        return out
    why: list[str] = []
    for tf in tfs:
        res = chanlun_results.get(tf)
        if res is None:
            why.append(f"{tf}:missing")
            continue
        if getattr(res, "status", "") != "ok":
            why.append(f"{tf}:{getattr(res, 'status', 'unknown')}")
            continue
        c = getattr(res, "center", None) or {}
        zg, zd = _f(c.get("zg")), _f(c.get("zd"))
        if zg is None or zd is None:
            why.append(f"{tf}:no_center")
            continue
        width = zg - zd
        if width <= 1e-9:
            # 退化中枢：上下沿相等（实测 1m 有 18% 是这种），无法定位
            why.append(f"{tf}:degenerate")
            continue
        if atr and atr > 0 and width < _min_width_atr() * atr:
            why.append(f"{tf}:too_narrow({width:.2f}"
                       f"<{_min_width_atr() * atr:.2f})")
            continue
        # 有效中枢
        out.ok = True
        out.tf = tf
        out.considered = tuple(tfs)
        out.zg, out.zd = zg, zd
        out.gg, out.dd = _f(c.get("gg")), _f(c.get("dd"))
        out.cid = c.get("id")
        out.width = width
        out.pos = (last_close - zd) / width
        out.dist_edge = min(abs(last_close - zd), abs(last_close - zg))
        if why:
            out.reason = "ok(跳过 " + ",".join(why) + ")"
        return out
    out.reason = "no_usable_center(" + ",".join(why) + ")" if why else \
        "no_usable_center"
    out.considered = tuple(tfs)
    return out


#: 判定为"贴边"的归一化带宽（两端各此比例，中间为禁区）。
#: 默认取配置值（config.toml `[risk] zhongshu_edge_band`），缺失时 0.30。
def _edge_band() -> float:
    try:
        from gold_agent.common.config import CFG
        return float(getattr(CFG.risk, "zhongshu_edge_band", EDGE_BAND))
    except Exception:
        return EDGE_BAND


EDGE_BAND = 0.30


def edge_side(cv: CenterView, direction: str) -> str:
    """判断现价相对中枢的位置类别（供决策层做边际/突破判定）。

    返回：
      `at_zd`    贴下沿（做多的边际入场区）
      `at_zg`    贴上沿（做空的边际入场区）
      `mid`      中枢中部 —— **用户明确不希望在这里开仓**
      `below`    已跌破下沿（向下突破）
      `above`    已突破上沿（向上突破）
      `unknown`  取不到有效中枢
    """
    if not cv.ok or cv.pos is None:
        return "unknown"
    if cv.pos < 0:
        return "below"
    if cv.pos > 1:
        return "above"
    band = _edge_band()
    if cv.pos <= band:
        return "at_zd"
    if cv.pos >= 1.0 - band:
        return "at_zg"
    return "mid"
