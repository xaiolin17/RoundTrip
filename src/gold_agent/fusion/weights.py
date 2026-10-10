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

  ① **证据基础**（`measurable`）—— 事实判断，不是显著性检验。
     `openmobius_smc` 的离线分数来自桩 `_mobius_synthetic_scores`（Mobius API
     无历史回放），桩技能不可采信 → 无实测排序可依。但它**不是**"无数据 ⇒
     无权重"：该源的实盘分数是真实的，只是没有离线历史可预先校准。
     → 给**中庸**先验权重（`PRIOR_ONLY_WEIGHT`，小而非零），由贝叶斯层按实盘
       命中率在线调节（见 `PRIOR_ONLY_SOURCES`）。

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
from typing import Callable

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

#: `PRIOR_ONLY_SOURCES` 的**权重下限**（"入场券"，不是固定值）。
#:
#: 为什么不给满额起点：该源没有离线历史可校准，真实技能未知。给满额会让
#: 一个未经校准的源与已实测源平起平坐 —— 实测回放显示，其离线桩的噪声会把
#: 融合分稀释到 IC/命中率双双跌破下限。给 0.1 的"入场券"权重：足以让它进入
#: 融合、进贝叶斯池，又小到在**尚无实盘成绩可依**时不会主导方向。
#:
#: ⚠️ 2026-10-10 语义变更（用户选定）：0.1 不再是**固定值**，而是**下限**。
#:    原先 `w_final = (1 − lambda_eff) × 0.1` 只能减、不能增 —— 用户设它的本意
#:    是"给贝叶斯层留一个动态调节入口"，但贝叶斯层只改**分数**（`bc`）、
#:    不改权重，于是权重恒为 0.1，方向对再多也调不动。
#:    现在该源权重由**实盘滚动命中率**在线驱动（见 `PRIOR_ONLY_MAX_WEIGHT`
#:    与 `WeightTable.refresh_online`）：成绩好则向上长、直到与已实测源平权。
#:
#: 量纲：n < 20（尚无成绩）时 w = 0.1 → Σw = 3×4.0 + 0.1 = 12.1 → σ ≈ 0.2875，
#: 与不给该源时的 0.2887 几乎一致 —— 冷启动阶段几乎不改变开仓门槛。
PRIOR_ONLY_WEIGHT = 0.1

#: `PRIOR_ONLY_SOURCES` 的权重**上限**。用户 2026-10-10 选定 = 满额 `W_SCALE`：
#: 实盘成绩足够好时允许它与已实测源平权（Σw 最大 = 3×4.0 + 4.0 = 16.0
#: → σ ≈ 0.25，仍稳稳低于 `sigma_max = 0.8` 的闸门）。
PRIOR_ONLY_MAX_WEIGHT = W_SCALE

#: 在线驱动的最低样本量。与 `BayesianPool.weight()` 的冷启动门槛一致
#: （n < 20 时贝叶斯层本身也不产生证据，权重理应停在"入场券"）。
PRIOR_ONLY_MIN_SAMPLES = 20

#: 样本量置信度吃满所需的样本数 = 贝叶斯滚动窗口（窗口满 → 样本最可信）。
#: 增长比例 = 超额命中率 × clip((n − MIN)/(FULL − MIN), 0, 1)：
#: 刚过 20 单不放量（避免"侥幸对了几单"被噪声放大成权重），
#: 窗口满（n = FULL）才吃满上限。
PRIOR_ONLY_FULL_SAMPLES = max(int(CFG.fusion.bayes_window),
                              PRIOR_ONLY_MIN_SAMPLES + 1)

#: 试验族规模（DSR 需要）。每新增一个被评估过的源/参数 +1。
#: 由 research/21_source_ir.py 写入 IR 文件；此处仅默认值。
DEFAULT_TRIALS = 1

#: `lambda` 达到此值即认为"数据已经能把源排出高下"。
#: 用于决定是否发出"未校准模式"告警，**不参与权重计算**
#: （权重永远走 `lambda · w_measured + (1−lambda) · w_prior` 连续式）。
LAMBDA_CALIBRATED = 0.5

#: **只有先验、没有离线技能估计**的源（历史数据不可得，但有实盘分数）。
#:
#: `openmobius_smc`：Mobius API **不提供历史回放**，`research/21_source_ir.py`
#: 只能用离线桩 `_mobius_synthetic_scores`（5 根摆动枢轴 → BOS/CHoCH）产出
#: 分数序列。桩的表现不是该源在实盘上的表现，因此**无法离线校准**，桩跑出的
#: skill 不可采信（该桩实测 skill=+1.525，若不隔离会因"唯一正 skill"抢走全部
#: 权重）。但把它按"无数据 ⇒ 无权重"处理同样不对：它的分数在实盘是真实的，
#: 只是没有离线历史可以事先校准。
#:
#: 处理方式：给**中庸**先验权重（`PRIOR_ONLY_WEIGHT`，小而非零），
#: 但**不采信其离线桩 skill**：
#:
#:   · `skill` 强制置 0，且**排除出 DL 方差分解**（它的 0 是假设、不是测量，
#:     掺进去会污染 Q 统计量）；
#:   · 因此它拿 `PRIOR_ONLY_WEIGHT` 起步（中庸**下限**，非满额），并由实盘
#:     滚动命中率**在线**驱动：成绩好则权重向上长到 `PRIOR_ONLY_MAX_WEIGHT`；
#:   · `measurable=True` → 有非零权重 → 参与融合、记入贝叶斯命中率池。
#:
#: ⚠️ 与 `verified` 的区别：`verified=False` 只说明"这个样本量下测不出
#:    显著技能"（当前三个真实源都是这个状态，但它们是**可测**的）；
#:    本集合里的源是"**没有离线历史可测**"，故只给先验、不给实测排序。
PRIOR_ONLY_SOURCES = frozenset({"openmobius_smc"})


@dataclass
class SourceIR:
    """单个源的实测 IR 与其统计证据。

    ⚠️ `ir` / `measurable` 是**参与加权的那两个字段**。

      · `measurable`  该源是否进入方向加权（事实判断，**不是**显著性判定）。
                      False → 0 权重（如 `news` 走独立证据通道）。
                      True 有两种：有离线历史 → 参与 DL 排序；或实盘有分数
                      但无离线历史（`PRIOR_ONLY_SOURCES`）→ 以下限
                      `PRIOR_ONLY_WEIGHT` 起步，由实盘命中率在线放大。
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
    #: `"prior_only"`（无离线历史 → 只给中庸先验、由贝叶斯层在线调节）/
    #: `"unmeasurable"`（无历史数据且不参与决策 → 0 权重）。
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
    #: `PRIOR_ONLY` 源的**在线驱动**中间量（仅供审计/日志）：
    #: `online_p` 滚动命中率、`online_n` 样本量、`online_frac` 增长比例 ∈ [0,1]。
    #: 满足 `w_final = PRIOR_ONLY_WEIGHT
    #:              + (PRIOR_ONLY_MAX_WEIGHT − PRIOR_ONLY_WEIGHT) × online_frac`。
    #: ⚠️ 这三个字段**不参与** DL 方差分解，也不写回 `w_measured`
    #: （写回会让 `has_measured_ranking` 意外翻真，进而把 lam_eff 从 0 抬起，
    #: 反而改变**其它**三个已实测源的权重 —— 那是本变更不该有的副作用）。
    online_p: float = float("nan")
    online_n: int = 0
    online_frac: float = 0.0

    @property
    def weight(self) -> float:
        """最终权重。不可测 → 0；未经过收缩计算 → 先验（`PRIOR_ONLY` 源取
        中庸先验 `PRIOR_ONLY_WEIGHT`，其余取等权先验 `W_SCALE`）。"""
        if not self.measurable:
            return UNMEASURABLE_WEIGHT
        if self.w_set:
            return self.w_final
        return PRIOR_ONLY_WEIGHT if self.name in PRIOR_ONLY_SOURCES else W_SCALE


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
    #: **实际施加**的收缩系数。等于 `lam`，**除非**实测排序为空
    #: （所有可测源 skill ≤ 0 → `w_measured` 全 0）时为 0。
    #: 为什么必须与 `lam` 分开：见 `_refresh_weights` 与 `has_measured_ranking`。
    lam_eff: float = 0.0
    #: 在线命中率提供者：`name -> (滚动命中率, 样本量)`；返回 None = 无数据。
    #: 由 `FusionEngine` 绑定到贝叶斯池 —— 权重层**不** import 贝叶斯模块，
    #: 只约定这个最小接口（避免把"命中率从哪来"的策略耦合进权重层）。
    #: 未绑定时（如测试里直接 `WeightTable.load()`）取 `PRIOR_ONLY_WEIGHT` 起步，
    #: 与历史行为完全一致。
    online_provider: Callable[[str], tuple[float, int] | None] | None = None

    def get(self, name: str) -> SourceIR:
        """取源的记录。**表里没有的源**返回可测性未知的空记录（0 权重）。

        `basis="absent"` 而不是 `"measured"`：一个从未出现在校准文件里的源
        （如 `news`）没有任何实测证据，把它标成 "measured" 会让审计日志
        谎称它有出处。这正是本项目反复出问题的模式（日志显示 provenance，
        但 provenance 是编的），故显式区分。
        """
        return self.sources.get(name) or SourceIR(name=name, measurable=False,
                                                  basis="absent")

    def _refresh_weights(self) -> None:
        """用 DL 收缩把 `w_final` 写到每个源上（唯一的权重计算入口）。

        `tau^2 = max(0, (Q − df)/C)`，`lambda = tau^2/(tau^2 + s^2)`。
        抽样方差按 `s^2 = 1` 取：`skill` 是 t 尺度上的量，其标准误为 1
        （对照均值由 200 次置换估出，只额外贡献约 1/200，可忽略）。
        """
        # 先验源优先：无离线历史回放的源，隔离其离线桩 skill（置 0），给等权
        # 先验，并**排除出 DL 方差分解** —— 它的 0 是假设、不是测量，掺进去
        # 会污染 Q 统计量。（桩偶然跑出 +1.525 这类好数字不构成校准依据。）
        for name, s in self.sources.items():
            if name in PRIOR_ONLY_SOURCES:
                s.measurable = True
                s.skill = 0.0
        cand = [s for s in self.sources.values()
                if s.measurable and math.isfinite(s.skill)
                and s.name not in PRIOR_ONLY_SOURCES]
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

        # ---- 收缩：只有"实测排序"确实存在时才施加 ----
        # 若所有可测源 skill ≤ 0，w_measured 全被夹到 0（"负 skill 视为 0，
        # 不做反向"），此时"实测排序"是空的：按 lam 收缩不改变任何源之间的
        # 相对权重，只是把 Σw 乘上 (1−lam)。而 σ_S = 1/√Σw，于是 σ 被抬高、
        # z=|S|/σ 变小、开仓更难 —— 这正是"源间差异越显著反而越难开仓"的
        # 反直觉症状（B4）。故此处令有效收缩系数为 0（退化为等权先验）；
        # `self.lam` 仍保留 DL 原值，供审计与"未校准"判定（engine.uncalibrated）使用。
        self.lam_eff = float(self.lam if self.has_measured_ranking else 0.0)

        for s in self.sources.values():
            if not s.measurable:
                s.w_final = UNMEASURABLE_WEIGHT
                s.w_set = True
                s.basis = "unmeasurable"
                continue
            if s.name in PRIOR_ONLY_SOURCES:
                # 无离线技能估计 → 权重由**实盘滚动命中率**在线驱动（用户
                # 2026-10-10 选定）：命中率越高、样本越多，权重从
                # PRIOR_ONLY_WEIGHT（下限）线性长到 PRIOR_ONLY_MAX_WEIGHT。
                # ⚠️ `w_measured` 必须保持 0：它一旦 > 0 会让
                # `has_measured_ranking` 意外翻真 → lam_eff 从 0 抬起 →
                # 波及**其它**三个已实测源的权重（本变更不该有的副作用）。
                # 在线量单独记在 `online_*` 字段，不进 DL 方差分解。
                s.ir_max = 0.0
                s.w_measured = 0.0
                s.w_prior = PRIOR_ONLY_WEIGHT
                frac, p, n = self._online_frac(s.name)
                s.online_p, s.online_n, s.online_frac = p, n, frac
                s.w_final = float(PRIOR_ONLY_WEIGHT
                                  + (PRIOR_ONLY_MAX_WEIGHT
                                     - PRIOR_ONLY_WEIGHT) * frac)
                s.w_set = True
                s.basis = "prior_only"
                continue
            s.w_final = float(self.lam_eff * s.w_measured
                              + (1.0 - self.lam_eff) * s.w_prior)
            s.w_set = True

    def _online_frac(self, name: str) -> tuple[float, float, int]:
        """算出 `PRIOR_ONLY` 源的在线增长比例 `frac ∈ [0,1]` 与中间量。

        `frac = 超额命中率 × 样本量置信度`：

          · 超额命中率 = `clip((p − 0.5)/0.5, 0, 1)`
            —— p 是贝叶斯池的 Beta(1,1) 后验均值 `(命中+1)/(样本+2)`；
            0.5 是"抛硬币"基线，命中率不超过它就不放量。
          · 样本量置信度 = `clip((n − MIN)/(FULL − MIN), 0, 1)`
            —— n < MIN（20）时 0（尚无成绩，停在入场券）；n ≥ FULL（窗口满）
            时 1（吃满上限）。中间线性过渡，避免"侥幸对了几单"被噪声放大。

        返回 `(frac, p, n)`；无 provider 或无数据时返回 `(0.0, nan, 0)`。
        """
        if self.online_provider is None:
            return 0.0, float("nan"), 0
        try:
            got = self.online_provider(name)
        except Exception as e:              # provider 由 engine 注入，别让它拖垮权重层
            log_warn(f"在线命中率提供者调用失败（{name}）：{e} → 该源权重停在"
                     f"下限 {PRIOR_ONLY_WEIGHT}")
            return 0.0, float("nan"), 0
        if not got:
            return 0.0, float("nan"), 0
        p, n = float(got[0]), int(got[1])
        if not math.isfinite(p) or n <= 0:
            return 0.0, float("nan"), 0
        span = PRIOR_ONLY_FULL_SAMPLES - PRIOR_ONLY_MIN_SAMPLES
        conf = ((n - PRIOR_ONLY_MIN_SAMPLES) / span) if span > 0 else 1.0
        conf = float(min(1.0, max(0.0, conf)))
        excess = float(min(1.0, max(0.0, (p - 0.5) / 0.5)))
        return excess * conf, p, n

    def refresh_online(self) -> bool:
        """按最新实盘命中率重算 `PRIOR_ONLY` 源权重。有变化才记日志。

        ⚠️ 为什么需要它：`_refresh_weights()` 只在 `load()` / `_apply_equal_prior()`
        时调用一次 —— 进程内权重**不会**随实盘成绩变动。而本轮改造的核心正是
        "让命中率驱动权重"，故必须每轮开仓前重新拉一次在线命中率。

        返回是否发生了权重变化（供调用方决定要不要落盘/记日志）。
        """
        before = {n: self.get(n).weight for n in PRIOR_ONLY_SOURCES}
        self._refresh_weights()
        after = {n: self.get(n).weight for n in PRIOR_ONLY_SOURCES}
        changed = [n for n in before if abs(after[n] - before[n]) > 1e-9]
        if changed:
            detail = "、".join(
                f"{n} 权重 {before[n]:.3f} → {after[n]:.3f}"
                f"（滚动命中率 {self.get(n).online_p:.3f}"
                f"/{self.get(n).online_n} 单，增长比例 "
                f"{self.get(n).online_frac:.3f}；下限 {PRIOR_ONLY_WEIGHT:.1f}"
                f" 上限 {PRIOR_ONLY_MAX_WEIGHT:.1f}）"
                for n in sorted(changed))
            log_info(f"权重在线刷新（由实盘命中率驱动）：{detail}。"
                     f"总权重 {sum(self.weight(n) for n in DECISION_SOURCES):.3f}")
        return bool(changed)

    def weight(self, name: str) -> float:
        return self.get(name).weight

    def is_measurable(self, name: str) -> bool:
        return self.get(name).measurable

    @property
    def has_measured_ranking(self) -> bool:
        """是否**真的**存在可用的实测排序：至少一个可测源拿到正的实测权重。

        ⚠️ 为什么不能只看 `lam`：`lam` 由 DL 估计量从源间**离散度**算出
        （`Q > df` 即 > 0），与实测值的**符号**无关。当所有可测源 `skill <= 0`
        时，`_refresh_weights` 把 `w_measured` 全部夹到 0（"负 skill 视为 0，
        不做反向"）—— 此时"实测排序"是**空的**。即使 `lam >= LAMBDA_CALIBRATED`，
        也不能说"数据已能分辨源的高下 / 采用实测排序"：没有排序可"采用"，
        最终权重只是 `(1−lam)×等权先验`。

        实测案例（2026-10）：USDJPYm 上三源 skill 均非正，但 Q=4.627 < df 之上
        → `lam=0.568 > 0.5`。若只看 `lam`，日志会谎称"采用实测排序"，
        风险层也会误判为"已校准"而不降仓。
        """
        return any(s.measurable and s.w_measured > 0.0
                   for s in self.sources.values())

    def total_weight(self, names: list[str]) -> float:
        return float(sum(self.weight(n) for n in names))

    def describe(self, names: list[str] | None = None) -> dict:
        """给日志用的逐源权重快照（含 `lambda` 收缩的全部中间量）。

        必须能审计"这个权重怎么来的"：
          · `w_prior` / `w_measured` / `w` 三者 + `lambda_effective` 可复算最终权重
          · `skill` / `ctrl_p` / `n_independent` 是统计依据
          · `basis` 区分实测、等权先验、不可测
        `lambda` 是 DL 原始估计；`lambda_effective` 是**真正施加**的收缩系数
        （实测排序为空时为 0）。复算用 `lambda_effective`。

        ⚠️ `basis == "prior_only"` 的源例外：它的权重由实盘命中率**在线**驱动，
        不复算自 `w_prior`/`w_measured`（`w_measured` 恒 0）。审计该源须用
        `online_p` / `online_n` / `online_frac`：
        `w = PRIOR_ONLY_WEIGHT + (PRIOR_ONLY_MAX_WEIGHT − PRIOR_ONLY_WEIGHT) × online_frac`。
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
                      "lambda_effective": round(self.lam_eff, 4),
                      "file_ir": s.file_ir,
                      "file_measurable": s.file_measurable,
                      "online_p": (None if not math.isfinite(s.online_p)
                                   else round(s.online_p, 4)),
                      "online_n": s.online_n,
                      "online_frac": round(s.online_frac, 4)}
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

    @classmethod
    def load_for_symbol(cls, symbol: str | None) -> "WeightTable":
        """按品种加载源 IR 权重表：优先 `data/<品种>/source_ir.json`，
        缺失则回退共享的 `data/source_ir.json`。

        ⚠️ 为什么要按品种：源 IR 是**该品种**上实测出来的技能，
        黄金的趋势性 ≠ 欧元的均值回归。共用一份会把 A 品种校准出的
        源排序套到 B 品种身上 —— 不报错，只是安静地用错权重。

        单品种模式下 `CFG.state_path_for()` 返回 `data/`，与共享路径
        **等价** → 直接走 `load()`，与历史行为完全一致（数值零变化）。
        """
        shared = CFG.project_root / "data" / IR_STATE_FILE
        if not symbol:
            return cls.load(shared)
        sym_path = CFG.state_path_for(symbol) / IR_STATE_FILE
        if sym_path == shared:
            return cls.load(shared)          # 单品种：按品种 == 共享
        if sym_path.exists():
            log_info(f"{symbol} 使用按品种权重表：{sym_path}")
            return cls.load(sym_path)
        log_info(f"{symbol} 无按品种权重表（{sym_path} 不存在）→ 回退共享表 "
                 f"{shared}；如需按品种校准请运行 "
                 f"research/21_source_ir.py --symbol {symbol} --write")
        return cls.load(shared)

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


def _format_source_weight(k: str, s: SourceIR) -> str:
    """单源权重的一句话说明（GBK 安全）。

    ⚠️ `prior_only` 源**不能**用"实测 x / 先验 y"渲染：它的 `w_measured` 恒 0，
    最终权重由实盘命中率在线驱动，`(1−lam)×先验` 复算不成立 —— 照旧渲染会让
    日志谎报权重来源（本项目反复出问题的模式）。
    """
    if s.basis == "prior_only":
        p = "无" if not math.isfinite(s.online_p) else f"{s.online_p:.3f}"
        return (f"{k} 权重 {s.w_final:.3f}（中庸先验下限 {PRIOR_ONLY_WEIGHT:.1f}"
                f" 起，按实盘命中率在线增长：增长比例 {s.online_frac:.3f}、"
                f"滚动命中率 {p}/{s.online_n} 单、上限 {PRIOR_ONLY_MAX_WEIGHT:.1f}）")
    return (f"{k} 权重 {s.w_final:.3f}"
            f"（实测 {s.w_measured:.3f} / 先验 {s.w_prior:.3f}）")


def _log_weight_state(tbl: WeightTable) -> None:
    """把权重来源与收缩强度打进日志（GBK 安全，不用特殊符号）。"""
    n_meas = sum(1 for s in tbl.sources.values() if s.measurable)
    tot = sum(s.w_final for s in tbl.sources.values() if s.measurable)
    detail = "、".join(
        _format_source_weight(k, s)
        for k, s in sorted(tbl.sources.items()) if s.measurable)
    if tbl.lam >= LAMBDA_CALIBRATED and tbl.has_measured_ranking:
        log_info(f"权重校准：收缩系数 {tbl.lam:.3f}（Q={tbl.q_stat:.3f} "
                 f"自由度={tbl.q_df}）—— 数据已能分辨源的高下，采用实测排序。"
                 f"{detail}。总权重 {tot:.3f}")
    elif tbl.lam >= LAMBDA_CALIBRATED:
        # 源间差异显著（Q > df）**但**各源实测技能均非正 → 实测权重全为 0，
        # 没有排序可"采用"。不能沿用上一支的"采用实测排序"（那是谎话）。
        # 此时也**不施加收缩**：收缩只会等比压低 Σw、抬高 σ（B4），故
        # 有效收缩系数为 0，权重取满额等权先验。
        log_warn(
            f"权重未校准模式：DL 收缩系数 {tbl.lam:.3f}（Q={tbl.q_stat:.3f} "
            f"自由度={tbl.q_df}）—— 源间差异虽显著，但各源实测技能均非正，"
            f"实测权重全为 0，无实测排序可用；按 B4 口径不施加收缩"
            f"（有效收缩系数 {tbl.lam_eff:.3f}），权重取等权先验。"
            f"{detail}。总权重 {tot:.3f}。"
            f"风险层按未校准模式降仓（decision.uncalibrated_lot_mult）。")
    else:
        log_warn(
            f"权重未校准模式：收缩系数 {tbl.lam:.3f}（Q={tbl.q_stat:.3f} "
            f"自由度={tbl.q_df}，源间差异不显著于抽样噪声）"
            f"—— {n_meas} 个可测源按先验分配（普通源等权 W_SCALE，无离线"
            f"历史的源取中庸先验 PRIOR_ONLY_WEIGHT），非零权重保证可交易。"
            f"{detail}。总权重 {tot:.3f}。"
            f"风险层按未校准模式降仓（decision.uncalibrated_lot_mult）。")


#: 参与方向决策的源名（与 fusion/engine.py 构造的 SourceView.name 一致）
DECISION_SOURCES = ("kalman_persist", "chanlun", "openmobius_smc",
                    "classic_indicators", "news")
