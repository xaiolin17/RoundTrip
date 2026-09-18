"""日志工具：JSONL 结构化日志（logs/）。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from gold_agent.common.config import CFG


def jlog(path: Path, record: dict) -> None:
    """追加一条 JSONL 记录。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    record.setdefault("ts", time.time())
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


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
