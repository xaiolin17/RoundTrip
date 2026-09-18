# -*- coding: utf-8 -*-
"""pytest 全局夹具：测试运行期的日志与状态写到临时目录，不污染生产 logs/data。

无 mock 原则不变——被测对象仍是真实模块，只是落盘位置隔离（避免测试噪音混入运行日志）。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _isolated_logs(tmp_path_factory):
    """把 CFG.log_dir / state_path 指到本次 pytest 会话的临时目录。"""
    from gold_agent.common.config import CFG

    session_dir = Path(tempfile.mkdtemp(prefix="goldagent-test-"))
    old_log_dir, old_state = CFG.log_dir, CFG.state_path
    CFG.log_dir = session_dir / "logs"
    CFG.log_dir.mkdir(parents=True, exist_ok=True)
    CFG.state_path = session_dir / "data" / "state.json"
    CFG.state_path.parent.mkdir(parents=True, exist_ok=True)
    yield
    CFG.log_dir, CFG.state_path = old_log_dir, old_state
