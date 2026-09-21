# -*- coding: utf-8 -*-
"""pytest 全局夹具：测试运行期的日志与状态写到临时目录，不污染生产 logs/data。

无 mock 原则不变——被测对象仍是真实模块，只是落盘位置隔离（避免测试噪音混入运行日志）。
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest


def _session_dir() -> Path:
    """优先在仓库内建临时目录（沙箱/受限环境常禁止写系统 TEMP），失败再退回系统临时目录。"""
    local = Path(__file__).resolve().parents[1] / ".pytest_tmp"
    try:
        local.mkdir(parents=True, exist_ok=True)
        d = local / f"run-{int(time.time())}-{id(object()) % 100000}"
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        return Path(tempfile.mkdtemp(prefix="goldagent-test-"))


@pytest.fixture(scope="session", autouse=True)
def _isolated_logs(tmp_path_factory):
    """把 CFG.log_dir / state_path 指到本次 pytest 会话的临时目录。"""
    from gold_agent.common.config import CFG

    session_dir = _session_dir()
    old_log_dir, old_state = CFG.log_dir, CFG.state_path
    CFG.log_dir = session_dir / "logs"
    CFG.log_dir.mkdir(parents=True, exist_ok=True)
    CFG.state_path = session_dir / "data" / "state.json"
    CFG.state_path.parent.mkdir(parents=True, exist_ok=True)
    yield
    CFG.log_dir, CFG.state_path = old_log_dir, old_state
