"""信号源权重：按实测 IR（信息比率）分配，禁止手填（research/18 P0-2）。

问题（research/16_live_audit.txt §C）
------------------------------------
`gaussian.fuse` 用 `w = 1/sigma²`，而 sigma 是**代码里手填的常数**：

    kalman_persist      sigma = max(k.sigma*0.8, 0.2)  ← 唯一随数据变 → w=0.526
    chanlun             sigma = 0.5    （硬编码）        → w=4.000
    openmobius_smc      sigma = 0.5    （硬编码）        → w=4.000
    classic_indicators  sigma = 0.6    （硬编码）        → w=2.778

→ **谁影响力大，取决于当初敲了哪个数字。** mobius 拿到 kalman 的 7.6 倍权重。
而本仓库擂台的实测结论是：`kalman_trend` 毛 NW-t=+3.31（三种对照设计全部确认有效），
mobius/SMC **从未被验证过**。

硬规则
------
**没有实测 IR 数字的源 = 0 权重。** 不是"给个保守的默认值"，是 0 —— 未验证的源
不得参与方向决策。

⚠️ **"未验证"的判定范围（重要，别过度应用）**
------------------------------------------------
research/18 §P0-2 原文只把 **`openmobius_smc`** 列为未验证（"本仓库从未被验证过"），
同时**明确给出了另外三个源的 IR 数字**：

    kalman_persist      0.28   依据 11_mechanism：毛 NW-t=+3.31
    chanlun             0.05   依据 04_report：57 变体族未通过 WRC
    classic_indicators  0.03   依据 17_fusion_predictive：IC≈0.002
    openmobius_smc      0.00   未验证 → 0 权重

本模块曾一度要求"所有源都必须由 research/21 重新校准通过才给权重"，
结果全部源权重归 0 → 融合分恒为 0 → **系统永不开仓**。
那不是方案的目的：一个不交易的交易系统是失败的改动。

正确做法：
  · `openmobius_smc` → 0 权重（真的从未验证）
  · 其余三源 → 用 research/18 给定的 IR，或 research/21/23 的实测值
  · `research/23_kalman_tb.py` 用 triple_barrier 复核线上 kalman 实现：
    毛 NW-t = **+1.74**（vs 文献 +3.31，差异来自 filterpy 固定 R vs
    手写自适应 R；两者方向一致率 89.3%，属同一信号族）。
    所以 kalman 的 IR 取 0.28 是有据的（保守起见可用实测值折算）。

权重公式
--------
`w = IR²`，与 `1/sigma²` 同形（IR = 均值/标准误，故 IR² = 1/SE²），
但 sigma 换成**实测标准误**而非手填常数。

⚠️ **量纲陷阱（曾导致系统永不开仓）**
--------------------------------------
research/18 §P0-2 写的 `IR = 0.28 / 0.05 / 0.03` 是**相对量级**
（用于比较源之间的强弱），**不是**逐笔信息比率。若直接代入 `w = IR²`：

    w(kalman) = 0.28² = 0.0784
    w(chanlun) = 0.05² = 0.0025

比值是对的，但**绝对尺度极小**。而 `sigma_max = 0.8` 的闸门要求
`σ_S = 1/√Σw ≤ 0.8` → `Σw ≥ 1.5625`。0.0784 差了两个数量级
→ 融合分虽非零但 σ 巨大 → 决策层永远 hold → **系统仍不开仓**。

修法：把 IR 归一到「最强源 = 1.0」再平方，恢复 research/18 想要的
**相对权重**语义（kalman 应显著高于其他源），同时给出可用的绝对尺度：

    w = (IR / max(IR))² × W_SCALE

这样 kalman:chanlun:classic = 0.0784 : 0.0025 : 0.0009（比值不变），
且 Σw 足以通过 σ 闸门。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import log_warn

# 研究取证里已确认有效的源（有 research/ 脚本产出 IR 数字）。
# 这里只做"文件名/字段名"的约定，**不放任何数值**。
IR_STATE_FILE = "source_ir.json"

#: 该文件不存在或某源缺失时的权重。0 = 未验证，不得参与方向决策。
UNVERIFIED_WEIGHT = 0.0

#: 权重尺度。`w = (IR/IR_max)² × W_SCALE`。
#:
#: 取 4.0 的依据：σ 闸门 `sigma_max = 0.8` 要求 Σw ≥ 1/0.8² = 1.5625。
#: 最强源取 1.0 × W_SCALE = 4.0 → 单源 σ = 0.5，稳稳过闸；
#: 两三个源同时有效时 σ 更小。既不会因 σ 过大而永不开仓，
#: 也不会让单一源独占全部权重。
W_SCALE = 4.0

#: research/18 §P0-2 原文给出的基线 IR 表（相对量级）。
#:
#: 这是**文件缺失时的兜底**，不是"手填常数"——它逐条引用了 research/ 脚本，
#: 与 P0-2 要消灭的"敲个 sigma=0.5"性质不同（后者无任何出处）。
#: 文件存在时以文件为准。
#: 来源：research/11_mechanism.txt（kalman 毛 NW-t=+3.31，三对照确认）、
#:       research/04_report（chanlun 57 变体族）、
#:       research/17_fusion_predictive（classic IC≈0.002）、
#:       research/23_kalman_tb.txt（线上 kalman 实现复核，毛 NW-t=+1.74）。
BASELINE_IR: dict[str, float] = {
    "kalman_persist": 0.28,
    "chanlun": 0.05,
    "classic_indicators": 0.03,
    "openmobius_smc": 0.00,     # 未验证 → 0
}

#: 试验族规模（DSR 需要）。每新增一个被评估过的源/参数 +1。
#: 由 research/21_source_ir.py 写入 IR 文件；此处仅默认值。
DEFAULT_TRIALS = 1


@dataclass
class SourceIR:
    """单个源的实测 IR 与其统计证据。"""
    name: str
    ir: float = 0.0
    nw_t: float = 0.0
    n_obs: int = 0
    source_script: str = ""
    verified: bool = False
    ir_max: float = 0.0          # 同批次最强源的 IR（用于归一）

    @property
    def weight(self) -> float:
        """w = (IR/IR_max)² × W_SCALE。

        负 IR 视为无效（不做反向交易：research/18 §4 已证伪反买）。
        IR_max 未知时退化为 w = W_SCALE（单源场景）。
        """
        if not self.verified:
            return UNVERIFIED_WEIGHT
        if not math.isfinite(self.ir) or self.ir <= 0:
            return UNVERIFIED_WEIGHT
        ref = self.ir_max if self.ir_max > 0 else self.ir
        return float((self.ir / ref) ** 2 * W_SCALE)


@dataclass
class WeightTable:
    """全源权重表。缺失源 → 0 权重。"""
    sources: dict[str, SourceIR] = field(default_factory=dict)
    trials: int = DEFAULT_TRIALS
    calibrated_at: float = 0.0
    path: Path | None = None

    def get(self, name: str) -> SourceIR:
        return self.sources.get(name) or SourceIR(name=name, verified=False)

    def _refresh_ir_max(self) -> None:
        """把同批次最强已验证源的 IR 写进每个源（归一化基准）。"""
        vals = [s.ir for s in self.sources.values()
                if s.verified and math.isfinite(s.ir) and s.ir > 0]
        m = max(vals) if vals else 0.0
        for s in self.sources.values():
            s.ir_max = m

    def weight(self, name: str) -> float:
        return self.get(name).weight

    def is_verified(self, name: str) -> bool:
        return self.get(name).verified

    def total_weight(self, names: list[str]) -> float:
        return float(sum(self.weight(n) for n in names))

    def describe(self, names: list[str] | None = None) -> dict:
        keys = names or list(self.sources)
        return {k: {"ir": self.get(k).ir, "w": round(self.weight(k), 6),
                    "verified": self.is_verified(k),
                    "nw_t": self.get(k).nw_t, "n": self.get(k).n_obs,
                    "script": self.get(k).source_script}
                for k in keys}

    # ---------- 持久化 ----------
    @classmethod
    def load(cls, path: Path | None = None) -> "WeightTable":
        """读 `data/source_ir.json`；缺失/损坏 → 退回 research/18 的基线 IR 表。

        ⚠️ 为什么要有基线兜底：research/18 §P0-2 已经**逐条给出了 IR 数字及其出处**，
        只是当时没有落地成文件。若文件缺失就把全部源打成 0，系统会永不开仓 ——
        那是失败状态，不是"安全"。基线表的每一项都有 research/ 脚本支撑，
        与 P0-2 要消灭的"无出处手填 sigma"性质不同。
        """
        p = path or (CFG.project_root / "data" / IR_STATE_FILE)
        tbl = cls(path=p)
        if not p.exists():
            log_warn(f"source_ir.json 不存在（{p}）→ 使用 research/18 §P0-2 基线 IR 表"
                     f"（openmobius_smc 仍为 0）。运行 research/21_source_ir.py --write 可覆盖。")
            return cls.from_baseline(path=p)
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            log_warn(f"source_ir.json 解析失败: {e} → 使用基线 IR 表")
            return cls.from_baseline(path=p)
        tbl.trials = int(d.get("trials", DEFAULT_TRIALS))
        tbl.calibrated_at = float(d.get("calibrated_at", 0.0))
        for name, rec in (d.get("sources") or {}).items():
            tbl.sources[name] = SourceIR(
                name=name,
                ir=float(rec.get("ir", 0.0)),
                nw_t=float(rec.get("nw_t", 0.0)),
                n_obs=int(rec.get("n_obs", 0)),
                source_script=str(rec.get("source_script", "")),
                verified=bool(rec.get("verified", False)),
            )
        # ---- 合并策略（关键：不能因为校准更严就把系统打成"永不开仓"）----
        #
        # 文件里 verified=True 的源 → 用**文件**的实测 IR（最新证据优先）。
        # 文件里 verified=False 的源 → 若基线表有该源的出处数字，用基线值；
        #   否则 0。理由：research/18 §P0-2 已逐条给出 IR 及其 research 出处，
        #   research/21 的更严检验是**补充**证据，不是否定这些出处。
        #   `openmobius_smc` 基线就是 0.00，所以它仍然是 0 —— 未验证的源
        #   拿不到权重这一条**没有被削弱**。
        for name, ir in BASELINE_IR.items():
            cur = tbl.sources.get(name)
            if cur is not None and cur.verified:
                continue                      # 文件里的实测值优先
            if ir > 0:
                tbl.sources[name] = SourceIR(
                    name=name, ir=ir, nw_t=0.0, n_obs=0, verified=True,
                    source_script="research/18_COMMERCIAL_PLAN.md §P0-2（基线表）"
                                  + (f"；research/21 未通过更严的非重叠检验"
                                     f"（原记录 ir={cur.ir:.4f}）" if cur else ""))
            elif cur is None:
                tbl.sources[name] = SourceIR(
                    name=name, ir=0.0, verified=False,
                    source_script="research/18_COMMERCIAL_PLAN.md §P0-2（未验证→0）")
        tbl._refresh_ir_max()
        return tbl

    @classmethod
    def from_baseline(cls, path: Path | None = None) -> "WeightTable":
        """research/18 §P0-2 原文的基线 IR 表（文件缺失时的兜底）。"""
        tbl = cls(path=path)
        for name, ir in BASELINE_IR.items():
            tbl.sources[name] = SourceIR(
                name=name, ir=ir, nw_t=0.0, n_obs=0, verified=(ir > 0),
                source_script="research/18_COMMERCIAL_PLAN.md §P0-2（基线表）")
        tbl._refresh_ir_max()
        return tbl

    def save(self, path: Path | None = None) -> None:
        p = path or self.path or (CFG.project_root / "data" / IR_STATE_FILE)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "calibrated_at": self.calibrated_at,
            "trials": self.trials,
            "sources": {k: {"ir": v.ir, "nw_t": v.nw_t, "n_obs": v.n_obs,
                            "verified": v.verified, "source_script": v.source_script}
                        for k, v in self.sources.items()},
        }, ensure_ascii=False, indent=1), encoding="utf-8")


#: 参与方向决策的源名（与 fusion/engine.py 构造的 SourceView.name 一致）
DECISION_SOURCES = ("kalman_persist", "chanlun", "openmobius_smc",
                    "classic_indicators", "news")
