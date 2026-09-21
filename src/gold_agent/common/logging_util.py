"""日志工具：JSONL 结构化日志（logs/）。"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from gold_agent.common.config import CFG

#: 静默开关：研究脚本 / 测试跑回放时**不得**污染实盘日志。
#: 实测事故：`research/24_oos_open_rate.py` 与 OOS 测试直接调用
#: `DecisionEngine.decide()`，而 `decide()` 内部会 `decision_log(...)` ——
#: 于是 4 个预热点 × 600 轮 = 数千条**伪造轮次**（R14847/R29915/R44543…）
#: 混进了 `logs/decision_YYYYMMDD.jsonl`，与真实轮次（R23xx）交错，
#: 让"实盘到底跑了哪些轮"无法分辨。
#:
#: 用法：研究/测试脚本开头调用 `set_silent(True)`；
#: 或设环境变量 `GOLD_AGENT_NO_FILE_LOG=1`（对子进程也生效）。
_silent: bool = os.environ.get("GOLD_AGENT_NO_FILE_LOG", "") not in ("", "0", "false")

#: 记录来源，便于事后区分实盘 / 研究 / 测试产生的日志
_source: str = os.environ.get("GOLD_AGENT_LOG_SOURCE", "live")


def set_silent(on: bool = True) -> None:
    """开启后 `jlog` 不再写文件（用于研究回放与测试）。"""
    global _silent
    _silent = bool(on)


def is_silent() -> bool:
    return _silent


def set_source(src: str) -> None:
    """标注后续日志的来源（live / research / test）。"""
    global _source
    _source = str(src)


def jlog(path: Path, record: dict) -> None:
    """追加一条 JSONL 记录；连续相同 payload 自动去重（休市/数据停更时不灌日志）。"""
    if _silent:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    record.setdefault("ts", time.time())
    record.setdefault("src", _source)
    # 去重：按 (event, 业务内容) 判断（ts 除外），连续重复只写一条，段尾补汇总
    key = json.dumps({k: v for k, v in record.items() if k != "ts"},
                     ensure_ascii=False, sort_keys=True, default=str)
    if _last_line_key.get(path.name) == key:
        _dup_count[path.name] = _dup_count.get(path.name, 0) + 1
        return
    if _dup_count.get(path.name):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"event": "dedup_summary",
                                "last_event": _last_event.get(path.name),
                                "suppressed": _dup_count[path.name],
                                "ts": record["ts"]}, ensure_ascii=False) + "\n")
        _dup_count[path.name] = 0
    _last_line_key[path.name] = key
    _last_event[path.name] = record.get("event")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


_last_line_key: dict[str, str] = {}
_dup_count: dict[str, int] = {}
_last_event: dict[str, str] = {}


def log_info(msg: str, **kw) -> None:
    print(f"[INFO] {msg}", **{k: v for k, v in kw.items() if False}, file=sys.stderr)


def log_warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr)


def log_error(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


def decision_log(record: dict) -> None:
    jlog(CFG.log_dir / f"decision_{time.strftime('%Y%m%d')}.jsonl", record)


def trade_log(record: dict) -> None:
    jlog(CFG.log_dir / "trades.jsonl", record)


def llm_log(record: dict) -> None:
    jlog(CFG.log_dir / f"llm_{time.strftime('%Y%m%d')}.jsonl", record)


def news_log(record: dict) -> None:
    jlog(CFG.log_dir / f"news_{time.strftime('%Y%m%d')}.jsonl", record)
