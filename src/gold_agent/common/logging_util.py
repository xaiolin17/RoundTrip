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

#: 当前品种。多品种单进程运行时，各品种的日志会**交错写入同一文件**，
#: 没有品种标签就无法归属某条记录属于哪个品种（也无法按品种做统计）。
#: 单品种时保持 None，日志格式与改造前**完全一致**（不新增字段）。
_symbol: str | None = None


def set_symbol(sym: str | None) -> None:
    """设置当前品种标签（多品种 runner 在每个品种的轮次前调用）。"""
    global _symbol
    _symbol = str(sym) if sym else None

#: 本进程是否为**实盘 runner**。只有 `runner.main()` 会置 True。
#:
#: ⚠️ 为什么需要这个开关（2026-09-30 二次事故）：
#: `set_silent` 是**自愿**调用的，一旦有人忘了调，研究/回放脚本就会直接
#: 写进生产 `logs/`。实测我自己写的一次性回放脚本忘了调，直接调用
#: `DecisionEngine.decide()`（内部会 `decision_log`），往 09-30 的
#: 生产日志里灌了 **19824 条 `round=1` 的伪造轮次**，覆盖 09-18/09-21/
#: 09-22/09-29/09-30 五天。这些假行和真实轮次交错，让"实盘到底跑了什么"
#: 无法分辨，且会污染一切基于日志的回测与统计。
#:
#: 所以改成**默认拒绝**：只有显式声明自己是实盘进程，才允许写生产 `logs/`。
#: 测试不受影响（`conftest` 会把 `CFG.log_dir` 指向临时目录）。
_live: bool = False

#: 被拒绝的写入次数（便于自检；不写盘，避免"用日志记录日志失败"）
_blocked_writes: int = 0


def set_live(on: bool = True) -> None:
    """声明本进程是实盘 runner，允许写生产日志目录。"""
    global _live
    _live = bool(on)


def _prod_log_dir() -> Path:
    """仓库根下的生产日志目录（`src/gold_agent/common/logging_util.py` -> 上溯 3 层）。"""
    return Path(__file__).resolve().parents[3] / "logs"


def _is_prod_log(path: Path) -> bool:
    try:
        path.resolve().relative_to(_prod_log_dir().resolve())
        return True
    except Exception:
        return False


def blocked_writes() -> int:
    """返回被拒绝的写入次数（供自检/测试断言）。"""
    return _blocked_writes


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
    global _blocked_writes
    if _silent:
        return
    # 非实盘进程禁止写生产日志目录 —— 见 `_live` 的说明。
    # 研究脚本要留档请自己指定输出路径（或用 set_silent 明确静默）。
    if not _live and _is_prod_log(path):
        _blocked_writes += 1
        if _blocked_writes == 1:
            print(f"[WARN] 非实盘进程试图写生产日志 {path}，已拒绝"
                  f"（如需实盘写入请调用 logging_util.set_live()）", file=sys.stderr)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    record.setdefault("ts", time.time())
    record.setdefault("src", _source)
    # 多品种：给每条记录打上品种标签（单品种时不加，保持日志格式不变）。
    # ⚠️ 必须放在**去重 key 之前**：否则两个品种的同类记录（其余字段相同）
    #    会被误判为"重复"而互相吞掉，其中一个品种的日志凭空消失。
    if _symbol:
        record.setdefault("symbol", _symbol)
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
