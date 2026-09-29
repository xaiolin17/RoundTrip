"""信号源权重：按实测 IR（信息比率）分配，禁止手填（research/18 P0-2）。

本模块的**两次**行为更正（都来自实测，别再退回旧行为）
======================================================

第一次（2026-09-29 早）：「校准文件是装饰性的」
------------------------------------------------
`load()` 无条件用 `BASELINE_IR` 兜底常数覆盖任何 `verified=False` 的源，
于是 `research/21_source_ir.py` 无论测出什么，权重都不变（实测：写入一份
"四个源全部未通过"的校准文件，四个源权重一模一样）。

第一次修法是引入 `CFG.fusion.source_ir_policy` 二选一：

  · `baseline_fallback`  文件未通过 → 用 `BASELINE_IR` 兜底。
                         **校准结果无法影响权重**（就是上面那个缺陷）。
  · `authoritative`      文件即终审：未通过 → **0 权重**。
                         代价：当前校准下四个源全部未通过 → 融合分恒为 0
                         → **系统不会开仓**。

第二次（2026-09-29 晚）：两个选项**都是错的**
---------------------------------------------
用户指出：`authoritative` 下 `BASELINE_IR` 永不被读取，`baseline_fallback`
下校准文件永不影响权重 —— **两个方案都必然留下一段死代码**，商用项目不能这样。
这个批评是对的，而且根因比"选哪个"更深：

  **把统计估计做成了二值开关。**

实测支撑（本模块的设计依据，`research/25_ir_recalibration.md` §12）：

  · 判定门的功效极低。三源独立样本只有 316~380，实测 t 为
    +0.31 / +0.17 / +0.67；而两双侧 α=0.05 下要 80% 功效需要真实 t ≥ 2.80。
    **"没有源通过"不等于"没有源有技能"**，只说明这个样本量分辨不出来。
  · 更关键：**源与源之间的差异本身就不显著**。用 DerSimonian-Laird
    估计量做方差分解：
        skill = t_obs − 方向匹配对照均值 = −0.19 / −0.35 / +0.17
        Q = 0.1429, df = 2  →  Q < df  →  tau^2 = 0
        lambda = tau^2/(tau^2 + s^2) = 0
    `tau^2 = 0` 的含义是：观测到的源间差异**不比纯抽样噪声更大**。
    既然数据分辨不出源的高下，那**任何**按这组数据重排权重的公式
    都是在拟合噪声 —— 包括"按实测 IR 排序加权"。

正确做法：精度加权收缩（经验贝叶斯）
------------------------------------
把两个被焊在一起的问题拆开：

  ① **可测性**（`measurable`）—— 事实判断，不是显著性检验。
     `openmobius_smc` 的分数来自离线桩 `_mobius_synthetic_scores`，
     Mobius API 无历史回放，**根本没有历史数据可测**。
     → 无数据 ⇒ 无权重。这条保留，且不依赖任何统计显著性。

  ② **技能差异**（`lambda` 加权）—— 估计量，**永不做硬 0**：

        w_i = lambda · w_measured_i + (1 − lambda) · w_prior_i

     `w_prior`   = 已知源等权（无信息先验的最大熵解）
     `w_measured`= 按 skill 归一后的 (skill/skill_max)^2 × W_SCALE
     `lambda`    = tau^2 / (tau^2 + s^2)，由 DL 估计量从**数据**算出

  这样校准**永远**影响权重，影响多少由它自身的信息量决定：

     lambda = 0  → 数据分不出高下 → 等权（当前状态）
     lambda → 1  → 数据足以排序   → 完全采用实测排序

  并且它是**可证伪的**：k=3 时 `Q > df = 2` 即触发。例如 skill 为
  (−1.0, 0, +1.0) 时 Q = 2.0 尚不够，(−1.35, 0, +1.35) 时 Q = 3.645 > 2
  → tau^2 = 0.8225 → lambda = 0.451，实测排序自动接管权重。

  **没有死代码**：`w_prior` 与 `w_measured` 在每个源上都实际参与计算
  （lambda 是权重，不是开关）；`lambda` 会随数据移动。
  这不是"为了让它跑起来"加的旁路 —— 它是这组数据下唯一的正确答案。

`BASELINE_IR` 已删除
--------------------
那张表声称 kalman = 0.28 出自 `research/11`，而该文件写的是
`kalman_trend n=59879 毛 NW-t=+3.31` → `IR = 3.31/sqrt(59879) = 0.01353`。
**0.28 比它自己的出处大 20.7 倍**，且正是这个假数字把排序做成了
`kalman > chanlun > classic`（research/21 实测恰好相反）。它不是"有出处的
基线表"，是伪造的先验。文件缺失时的正确答案是 `lambda` 无输入 → 等权，
而不是一张编造的表。

权重公式
--------
`w = IR²`，与 `1/sigma²` 同形（IR = 均值/标准误，故 IR² = 1/SE²），
但 sigma 换成**实测**标准误而非手填常数。

⚠️ **量纲陷阱（曾导致系统永不开仓）**
--------------------------------------
research/18 §P0-2 的 `IR = 0.28/0.05/0.03` 是**相对量级**，不是逐笔信息比率。
直接代入 `w = IR²` 得 `w(kalman) = 0.0784`，而 `sigma_max = 0.8` 要求
`Σw ≥ 1.5625`，差两个数量级 → 融合分虽非零但 σ 巨大 → 永不开仓。
故归一到「最强源 = 1.0」再平方：`w = (IR/IR_max)² × W_SCALE`。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import log_info, log_warn

#: 校准状态文件名。这里只做"文件名/字段名"的约定，**不放任何数值**。
IR_STATE_FILE = "source_ir.json"

#: 无实测数据可依的源的权重。0 = 不可测，不得参与方向决策。
UNMEASURABLE_WEIGHT = 0.0

#: 权重尺度。`w = (IR/IR_max)² × W_SCALE`。
#:
#: 取 4.0 的依据：σ 闸门 `sigma_max = 0.8` 要求 Σw ≥ 1/0.8² = 1.5625。
#: 最强源取 1.0 × W_SCALE = 4.0 → 单源 σ = 0.5，稳稳过闸；
#: 两三个源同时有效时 σ 更小。既不会因 σ 过大而永不开仓，
#: 也不会让单一源独占全部权重。
W_SCALE = 4.0

#: 试验族规模（DSR 需要）。每新增一个被评估过的源/参数 +1。
#: 由 research/21_source_ir.py 写入 IR 文件；此处仅默认值。
DEFAULT_TRIALS = 1

#: `lambda` 达到此值即认为"数据已经能把源排出高下"。
#: 用于决定是否发出"未校准模式"告警，**不参与权重计算**
#: （权重永远走 `lambda · w_measured + (1−lambda) · w_prior` 连续式）。
LAMBDA_CALIBRATED = 0.5

#: **结构性**不可测的源：数据源本身没有历史数据，与统计显著性无关。
#:
#: `openmobius_smc`：Mobius API **不提供历史回放**，`research/21_source_ir.py`
#: 只能用离线桩 `_mobius_synthetic_scores`（5 根摆动枢轴 → BOS/CHoCH）产出
#: 分数序列。桩的表现不是该源在实盘上的表现，因此**无法校准**，
#: 权重恒为 0 —— 这是关于"数据源能力"的事实判断，不是"没通过检验"。
#:
#: ⚠️ 与 `verified` 的区别：`verified=False` 只说明"这个样本量下测不出
#:    显著技能"（当前三个真实源都是这个状态，但它们是**可测**的）；
#:    本集合里的源是"**根本测不了**"。把这两者混为一谈正是被修掉的缺陷。
NO_HISTORY_SOURCES = frozenset({"openmobius_smc"})


@dataclass
class SourceIR:
    """单个源的实测 IR 与其统计证据。

    ⚠️ `ir` / `measurable` 是**参与加权的那两个字段**。

      · `measurable`  该源有没有**可测的历史数据**（事实）。
                      False → 0 权重。注意这**不是显著性判定**：
                      `openmobius_smc` 是离线桩，无历史回放，属事实性不可测。
      · `skill`       实测 t 超出方向匹配对照均值的部分（估计量）。
                      由 DL 估计量聚合成 `lambda` 后决定谁拿多少权重。
                      它**永远不会**单独把某个源打成 0 权重。

    审计字段（`file_*`）保留校验文件的原始记录，供日志比对。
    """
    name: str
    ir: float = 0.0
    nw_t: float = 0.0
    n_obs: int = 0
    source_script: str = ""
    #: 该源有无可测历史数据。False → 权重 0（不可测，不是"不显著"）。
    measurable: bool = False
    #: 实测 t 减去方向匹配对照均值 = 超出"同样多空比例、方向随机重排"的部分。
    skill: float = 0.0
    #: 该源的双侧置换 p 值（仅审计/诊断用，**不参与**权重计算）。
    ctrl_p: float = float("nan")
    #: 独立（非重叠）样本数，用于 DL 估计量的抽样方差。
    n_independent: int = 0
    ir_max: float = 0.0          # 同批次最强源的 IR（用于归一）
    #: 数值出处：`"measured"`（校准文件）/ `"equal_prior"`（无信息先验等权）/
    #: `"unmeasurable"`（无历史数据 → 0 权重）。
    basis: str = "measured"
    #: `data/source_ir.json` 里的原始实测记录（无论最终是否采用）。
    file_ir: float | None = None
    file_measurable: bool | None = None
    file_nw_t: float | None = None
    file_n_obs: int | None = None
    #: 收缩的两个端点与最终权重，由 `WeightTable._refresh_weights()` 回填。
    #: `w = lambda · w_measured + (1 − lambda) · w_prior`。
    w_prior: float = 0.0
    w_measured: float = 0.0
    w_final: float = 0.0
    #: `w_final` 是否已由 `_refresh_weights()` 算过。未算过（例如测试里
    #: 直接构造 `SourceIR`）时退化为等权先验，而不是静默变成 0 权重。
    w_set: bool = False

    @property
    def weight(self) -> float:
        """最终权重。不可测 → 0；未经过收缩计算 → 等权先验（`W_SCALE`）。"""
        if not self.measurable:
            return UNMEASURABLE_WEIGHT
        return self.w_final if self.w_set else W_SCALE


@dataclass
class WeightTable:
    """全源权重表。

    权重 = `lambda · w_measured + (1 − lambda) · w_prior`，两者都由本表算出。
    """
    sources: dict[str, SourceIR] = field(default_factory=dict)
    trials: int = DEFAULT_TRIALS
    calibrated_at: float = 0.0
    path: Path | None = None
    #: DL 估计量算出的收缩系数 tau^2/(tau^2+s^2) ∈ [0,1]。
    #: 0 = 数据分辨不出源的高下（等权）；1 = 完全采用实测排序。
    lam: float = 0.0
    #: DL 的 Q 统计量与自由度（审计：为什么 lambda 是这个值）。
    q_stat: float = 0.0
    q_df: int = 0
    #: 估计出的源间真实方差（tau^2 = max(0,(Q−df)/C)）。
    tau2: float = 0.0

    def get(self, name: str) -> SourceIR:
        return self.sources.get(name) or SourceIR(name=name, measurable=False)

    def _refresh_weights(self) -> None:
        """用 DL 收缩把 `w_final` 写到每个源上（唯一的权重计算入口）。

        `tau^2 = max(0, (Q − df)/C)`，`lambda = tau^2/(tau^2 + s^2)`。
        抽样方差按 `s^2 = 1` 取：`skill` 是 t 尺度上的量，其标准误为 1
        （对照均值由 200 次置换估出，只额外贡献约 1/200，可忽略）。
        """
        # 结构性命中优先：无历史回放的源即使文件声称 measurable 也强制 0。
        # （离线桩偶然跑出好数字不构成校准依据。）
        for name, s in self.sources.items():
            if name in NO_HISTORY_SOURCES:
                s.measurable = False
        cand = [s for s in self.sources.values()
                if s.measurable and math.isfinite(s.skill)]
        k = len(cand)

        # ---- w_measured：按 skill 归一后平方（负 skill 视为 0，不做反向）----
        smax = max((s.skill for s in cand), default=0.0)
        for s in cand:
            s.ir_max = smax
            s.w_measured = (float((max(0.0, s.skill) / smax) ** 2 * W_SCALE)
                            if smax > 0 else 0.0)
            # ---- w_prior：无信息先验 = 已知源等权（最大熵）----
            s.w_prior = W_SCALE

        # ---- lambda：DerSimonian-Laird 方差分解 ----
        if k >= 2:
            sk = [s.skill for s in cand]
            s2 = 1.0
            w = 1.0 / s2
            theta = sum(w * x for x in sk) / (k * w)
            q = sum(w * (x - theta) ** 2 for x in sk)
            df = k - 1
            c = k * w - (k * w * w) / (k * w)      # Σw − Σw²/Σw
            self.q_stat, self.q_df = float(q), int(df)
            self.tau2 = float(max(0.0, (q - df) / c)) if c > 0 else 0.0
        else:
            # 单源（或没有可测源）：无从谈"源间差异" → 无信息 → 等权
            self.q_stat, self.q_df, self.tau2 = 0.0, 0, 0.0
        self.lam = float(self.tau2 / (self.tau2 + 1.0))

        for s in self.sources.values():
            if not s.measurable:
                s.w_final = UNMEASURABLE_WEIGHT
                s.w_set = True
                s.basis = "unmeasurable"
                continue
            s.w_final = float(self.lam * s.w_measured
                              + (1.0 - self.lam) * s.w_prior)
            s.w_set = True

    def weight(self, name: str) -> float:
        return self.get(name).weight

    def is_measurable(self, name: str) -> bool:
        return self.get(name).measurable

    def total_weight(self, names: list[str]) -> float:
        return float(sum(self.weight(n) for n in names))

    def describe(self, names: list[str] | None = None) -> dict:
        """给日志用的逐源权重快照（含 `lambda` 收缩的全部中间量）。

        必须能审计"这个权重怎么来的"：
          · `w_prior` / `w_measured` / `w` 三者 + `lambda` 可复算最终权重
          · `skill` / `ctrl_p` / `n_independent` 是统计依据
          · `basis` 区分实测、等权先验、不可测
        """
        keys = names or list(self.sources)
        out = {}
        for k in keys:
            s = self.get(k)
            out[k] = {"ir": s.ir, "w": round(self.weight(k), 6),
                      "measurable": s.measurable,
                      "skill": round(s.skill, 4),
                      "ctrl_p": (None if not math.isfinite(s.ctrl_p)
                                 else round(s.ctrl_p, 4)),
                      "n_independent": s.n_independent,
                      "nw_t": s.nw_t, "n": s.n_obs,
                      "script": s.source_script,
                      "basis": s.basis,
                      "w_prior": round(s.w_prior, 4),
                      "w_measured": round(s.w_measured, 4),
                      "lambda": round(self.lam, 4),
                      "file_ir": s.file_ir,
                      "file_measurable": s.file_measurable}
        return out

    # ---------- 持久化 ----------
    @classmethod
    def load(cls, path: Path | None = None) -> "WeightTable":
        """读 `data/source_ir.json` 并用 DL 收缩算出权重。

        文件缺失/损坏 → **不是**退回某张手填表（那正是被删掉的
        `BASELINE_IR` 的错），而是 `lambda = 0` → 已知源等权。
        等权是无信息下的最大熵答案，且它同样会随数据变化。
        """
        p = path or (CFG.project_root / "data" / IR_STATE_FILE)
        tbl = cls(path=p)
        if not p.exists():
            log_warn(f"source_ir.json 不存在（{p}）→ 无实测输入，"
                     f"已知源按等权先验分配（lambda=0）。"
                     f"运行 research/21_source_ir.py --write 可生成。")
            return tbl._apply_equal_prior()
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            log_warn(f"source_ir.json 解析失败: {e} → 无实测输入，"
                     f"已知源按等权先验分配（lambda=0）")
            return tbl._apply_equal_prior()
        tbl.trials = int(d.get("trials", DEFAULT_TRIALS))
        tbl.calibrated_at = float(d.get("calibrated_at", 0.0))
        # ---- 旧格式检查：必须显式带 `measurable` ----
        # ⚠️ 不能用 `verified` 顶替（那正是被修掉的缺陷）：`verified` 是**统计
        #    显著性判定**，当前三源都因样本量不足而为 false，但它们的分数序列
        #    是真实历史数据算出来的、**可测**。旧版把"不显著"当成"不可测"，
        #    于是权重全 0、系统不开仓 —— 把估计量当成了开关。
        #    文件缺该字段 = schema 过旧，无法判定可测性 → 退回等权先验
        #    （仍然可交易，且不编造任何按源的数字）。
        rows = d.get("sources") or {}
        missing = [n for n, rec in rows.items() if "measurable" not in rec]
        if missing:
            log_warn(
                f"source_ir.json 缺少 measurable 字段（{len(missing)} 个源："
                f"{'、'.join(sorted(missing))}）—— 该文件是旧格式，"
                f"无法区分「不可测」与「不显著」，故本次不使用其按源数字，"
                f"已知源按等权先验分配（系统照常开仓）。"
                f"请重跑 research/21_source_ir.py --write 生成新格式。")
            return tbl._apply_equal_prior()
        for name, rec in rows.items():
            tbl.sources[name] = SourceIR(
                name=name,
                ir=float(rec.get("ir", 0.0)),
                nw_t=float(rec.get("nw_t", 0.0)),
                n_obs=int(rec.get("n_obs", 0)),
                source_script=str(rec.get("source_script", "")),
                measurable=bool(rec.get("measurable", False)),
                skill=float(rec.get("skill", 0.0)),
                ctrl_p=float(rec.get("tb_ctrl_p", float("nan"))),
                n_independent=int(rec.get("tb_n_independent", 0)),
                basis="measured",
                file_ir=float(rec.get("ir", 0.0)),
                file_measurable=bool(rec.get("measurable", False)),
                file_nw_t=float(rec.get("nw_t", 0.0)),
                file_n_obs=int(rec.get("n_obs", 0)),
            )
        tbl._refresh_weights()
        _log_weight_state(tbl)
        return tbl

    def _apply_equal_prior(self) -> "WeightTable":
        """无校准文件：已知源按等权先验分配（`lambda = 0`）。

        ⚠️ 这里**没有**任何 IR 数值 —— 旧版在这里塞了一张 `BASELINE_IR`
        （kalman 0.28 等），其中 kalman 的 0.28 比它自己的出处大 20.7 倍，
        是伪造的先验。等权同样给出非零权重、系统照常开仓，
        但不需要编造任何数字。
        """
        for name in DECISION_SOURCES:
            if name == "news":
                continue          # news 走独立证据通道，从不参与方向加权
            if name in NO_HISTORY_SOURCES:
                self.sources[name] = SourceIR(
                    name=name, ir=0.0, measurable=False, skill=0.0,
                    basis="unmeasurable",
                    source_script="数据源无历史回放 → 无法校准 → 0 权重")
                continue
            self.sources[name] = SourceIR(
                name=name, ir=0.0, measurable=True, skill=0.0,
                basis="equal_prior",
                source_script="无校准文件 → 等权先验（无信息，未编造 IR）")
        self._refresh_weights()
        return self

    def save(self, path: Path | None = None) -> None:
        p = path or self.path or (CFG.project_root / "data" / IR_STATE_FILE)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "calibrated_at": self.calibrated_at,
            "trials": self.trials,
            "sources": {k: {"ir": v.ir, "nw_t": v.nw_t, "n_obs": v.n_obs,
                            "measurable": v.measurable, "skill": v.skill,
                            "source_script": v.source_script}
                        for k, v in self.sources.items()},
        }, ensure_ascii=False, indent=1), encoding="utf-8")


def _log_weight_state(tbl: WeightTable) -> None:
    """把权重来源与收缩强度打进日志（GBK 安全，不用特殊符号）。"""
    n_meas = sum(1 for s in tbl.sources.values() if s.measurable)
    tot = sum(s.w_final for s in tbl.sources.values() if s.measurable)
    detail = "、".join(
        f"{k} 权重 {s.w_final:.3f}（实测 {s.w_measured:.3f} / 先验 {s.w_prior:.3f}）"
        for k, s in sorted(tbl.sources.items()) if s.measurable)
    if tbl.lam >= LAMBDA_CALIBRATED:
        log_info(f"权重校准：收缩系数 {tbl.lam:.3f}（Q={tbl.q_stat:.3f} "
                 f"自由度={tbl.q_df}）—— 数据已能分辨源的高下，采用实测排序。"
                 f"{detail}。总权重 {tot:.3f}")
    else:
        log_warn(
            f"权重未校准模式：收缩系数 {tbl.lam:.3f}（Q={tbl.q_stat:.3f} "
            f"自由度={tbl.q_df}，源间差异不显著于抽样噪声）"
            f"—— {n_meas} 个可测源按等权先验分配，非零权重保证可交易。"
            f"{detail}。总权重 {tot:.3f}。"
            f"风险层按未校准模式降仓（decision.uncalibrated_lot_mult）。")


#: 参与方向决策的源名（与 fusion/engine.py 构造的 SourceView.name 一致）
DECISION_SOURCES = ("kalman_persist", "chanlun", "openmobius_smc",
                    "classic_indicators", "news")
