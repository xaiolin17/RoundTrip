# -*- coding: utf-8 -*-
"""贝叶斯证据负向钳制回归测试（用户选定：表现差的源不能无限反打）。"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from gold_agent.common.config import CFG
from gold_agent.fusion.bayes import BayesianPool


@pytest.fixture
def state_dir():
    """本机 tmp_path 固定名目录被拒（WinError 5），用项目内临时目录。"""
    d = Path(CFG.project_root) / "_bayes_floor_tmp"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _pool(tmp_state) -> BayesianPool:
    return BayesianPool(window=300, state_path=tmp_state)


def test_negative_evidence_is_clamped(state_dir):
    """回归：9胜20负（p=0.32）的源，正分数证据必须被钳制。

    事故：贝叶斯池 9胜20负 -> evidence 的 logit=-0.74 -> 分数为正时
    每个源压 -0.94，4 源叠加把融合分拉低 0.3~0.5，配合信号源走弱
    导致 508 轮无一达到开仓阈值 1.3。
    """
    bp = _pool(state_dir / "b.json")
    for _ in range(9):
        bp.record_outcome("kalman_persist", 1, 1)
    for _ in range(20):
        bp.record_outcome("kalman_persist", 1, -1)
    ev = bp.evidence("kalman_persist", 1.0, 1.0)
    assert ev >= -CFG.fusion.bayes_evidence_floor - 1e-9, (
        f"负证据 {ev:.3f} 必须被钳制到 -{CFG.fusion.bayes_evidence_floor}")
    assert ev <= 0.0, "表现差的源不应给正证据"


def test_positive_evidence_not_clamped(state_dir):
    """表现好的源（20胜9负 p=0.68）正证据应充分投票。"""
    bp = _pool(state_dir / "b.json")
    for _ in range(20):
        bp.record_outcome("chanlun", 1, 1)
    for _ in range(9):
        bp.record_outcome("chanlun", 1, -1)
    ev = bp.evidence("chanlun", 1.0, 1.0)
    assert ev > CFG.fusion.bayes_evidence_floor, (
        f"正证据 {ev:.3f} 不应被钳制")


def test_cold_start_still_zero(state_dir):
    """样本 <20 的冷启动源：证据必须为 0（等权）。"""
    bp = _pool(state_dir / "b.json")
    for _ in range(10):
        bp.record_outcome("classic", 1, 1)
    assert bp.evidence("classic", 1.0, 1.0) == 0.0


def test_evidence_floor_config_present():
    assert hasattr(CFG.fusion, "bayes_evidence_floor")
    assert CFG.fusion.bayes_evidence_floor > 0
