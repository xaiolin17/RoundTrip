# -*- coding: utf-8 -*-
"""pytest 全局夹具：测试运行期的日志与状态写到临时目录，不污染生产 logs/data。

无 mock 原则不变——被测对象仍是真实模块，只是落盘位置隔离（避免测试噪音混入运行日志）。
"""
from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

import pytest

#: 历史会话保留个数。`.pytest_tmp` 曾**只增不减**：每跑一次 pytest 就多一个
#: `run-*` 目录（实测累积 105 个 / 9.6 MB），而里面只是被隔离的测试日志，
#: 没有任何保留价值。保留最近几次便于排查失败用例，更早的自动清掉。
_KEEP_RUNS = 3


def _prune_old_runs(local: Path) -> None:
    """清掉 `.pytest_tmp` 里过期的会话目录，只留最近 `_KEEP_RUNS` 个。

    ⚠️ 为什么放在建新目录**之前**：这样即使本次会话随后崩溃，
    目录数也有上界（最多 `_KEEP_RUNS + 1`），不会无限增长。
    """
    try:
        runs = sorted((p for p in local.glob("run-*") if p.is_dir()),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        for p in runs[_KEEP_RUNS:]:
            shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass          # 清理失败绝不能影响测试本身


def _session_dir() -> Path:
    """优先在仓库内建临时目录（沙箱/受限环境常禁止写系统 TEMP），失败再退回系统临时目录。"""
    local = Path(__file__).resolve().parents[1] / ".pytest_tmp"
    try:
        local.mkdir(parents=True, exist_ok=True)
        _prune_old_runs(local)
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


@pytest.fixture(scope="session", autouse=True)
def _never_trade_live():
    """⚠️ 强制测试进程**绝不能真实下单**（`TRADE_MODE=dry_run`）。

    事故（2026-10-09，我自己的过错）：
    `.env` 里是 `TRADE_MODE=live`，而此前 `conftest` **只隔离了日志与状态
    目录，没有碰 `trade_mode`**。`Executor.execute()` 的守卫是
    `if CFG.trade_mode == "dry_run": return 未发送` —— 于是 live 下直接
    `order_send`。而端到端测试会调用**真实的** `Graph.run_round()`
    （它跑完采集→分析→融合→风控→执行全链路）。

    后果（实测账户里真实存在）：
        ticket=2659117653 BTCUSDm magic=20260918 11:38:27 开仓
        ticket=2659179879 EURUSDm magic=20260918 11:57:52 开仓
        ticket=2659226006 EURUSDm magic=20260921 12:16:00 开仓
    这三笔是**测试跑出来的实盘仓位**，不是 runner 的决策。

    所以把 `trade_mode` 钉死为 `dry_run`：即使某个测试真的走到
    `execute()`，也只会返回"未发送"，绝不碰真实账户。
    需要验证真实下单链路的测试应显式 monkeypatch 这一项。
    """
    from gold_agent.common.config import CFG

    old_mode = CFG.trade_mode
    CFG.trade_mode = "dry_run"
    yield
    CFG.trade_mode = old_mode


@pytest.fixture(autouse=True)
def _assert_not_live():
    """每条测试入口再兜一层：发现 `live` 立即失败，而不是悄悄下单。"""
    from gold_agent.common.config import CFG

    assert CFG.trade_mode != "live", (
        "测试期 trade_mode 变成了 live —— 这会真实下单！"
        "必须由 `_never_trade_live` 钉成 dry_run。")
    yield
