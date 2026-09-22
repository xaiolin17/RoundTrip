"""主循环入口：py -m gold_agent.runner

live 模式直接真实下单（用户确认）；dry_run 只做决策演练。
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import subprocess
import sys

from gold_agent.common.config import CFG
from gold_agent.common.logging_util import log_error, log_info, log_warn
from gold_agent.common.zh import direction_label, kind_label, reason_label
from gold_agent.agent.graph import Graph


def _zh_reason(reason: str | None) -> str:
    """把风控拒绝理由翻成中文（**仅用于显示，不改动源码里的理由码**）。

    `gate.py` / `position.py` 产出的理由分两类：
      · 固定码（`no_atr` / `grid_layers_empty` …）→ 查表翻译；
      · 带数值的句子（`max_lot cap: 0.01+0.01 > 0.01`）→ 逐条替换关键字，
        保留原始数字（数字是诊断的关键，不能丢）。

    ⚠️ 为什么翻译只放在这一层：这些理由码是**机器可读的标识**，
    `tests/test_risk_real.py` 直接断言 `rej == "risk_budget_below_min_lot"`、
    `"circuit" in res.reason`。把码本身改成中文会让测试失败，
    也会让日志检索/告警规则失配。所以源码保持英文码，显示层翻译。
    """
    if not reason:
        return "未说明原因"
    code = reason_label(reason)
    if code != reason:
        return code
    out = reason
    for en, zh in (
        ("max_lot cap", "总手数上限"),
        ("adds capped at", "加仓次数已达上限"),
        ("pending", "已有挂单"),
        ("already waiting", "在等待成交"),
        ("grid base", "网格基准手数"),
        ("circuit", "熔断"),
        ("disagreement", "源间分歧"),
        ("unhandled kind", "未处理的动作类型"),
        ("no_atr", "无 ATR 数据"),
        ("bad_point_value", "点值无效"),
        ("risk_budget_below_min_lot", "风险预算不足最小手数"),
        ("grid_layers_empty", "网格层数为空"),
        ("grid_exposure_cap", "网格总敞口超上限"),
        ("direction_bias_halt", "方向偏置停机"),
        ("cooloff_until", "冷却至"),
        ("daily_loss_stop", "当日亏损停机"),
        ("consecutive_losses", "连续亏损停机"),
        ("friday_late", "周五尾盘不开仓"),
        ("drawdown_halt", "回撤停机"),
    ):
        out = out.replace(en, zh)
    return out


def _fmt_price(v) -> str:
    """价格格式化：黄金 3 位小数；非数值原样返回。"""
    try:
        return f"{float(v):.3f}"
    except (TypeError, ValueError):
        return str(v)


def _src_suffix(plan: dict) -> str:
    """标出止损止盈的定价来源（LLM 压力位 / 结构位 / ATR 兜底）。

    用户要求止损止盈看压力位，由 LLM 判断 —— 必须让人一眼看出
    这一轮的价位到底来自哪里，不能含糊。
    """
    src = plan.get("sl_source") or ""
    tp = plan.get("tp_source") or ""
    if not src and not tp:
        return ""
    parts = []
    for s in (src, tp):
        if s.startswith("llm_support"):
            parts.append("支撑位")
        elif s.startswith("llm_resistance"):
            parts.append("压力位")
        elif s.startswith("llm_hint"):
            parts.append("LLM建议")
        elif s.startswith("chanlun"):
            parts.append("缠论结构")
        elif s.startswith("atr"):
            parts.append("ATR兜底")
    uniq = []
    for x in parts:
        if x not in uniq:
            uniq.append(x)
    return "（" + "/".join(uniq) + "）" if uniq else ""


def _order_lines(summary: dict) -> list[str]:
    """把本轮**可执行的价位**渲染成缩进的多行文本。

    用户要求：每轮都要能直接看到「预测方向 + 入场位置 + 止损止盈」。

    三种形态的价位来源不同，必须分别处理：
      · `place_grid`  —— 价位在 `risk.plan.grid_plan`（多层），
                         每层各有自己的 entry/tp/sl；
      · `open_market` —— `risk.plan` 里有 tp/sl，但**入场价是执行时
                         才由 executor 取 bid/ask**，所以 plan 里没有 entry；
                         这里回退用 `summary["last_close"]` 作为参考价；
      · `add_layer`   —— 加仓单自带结构 SL/TP（原实现不带，会开成裸仓），
                        入场用原持仓开仓价作参考。

    ⚠️ 被风控拦截时没有 `risk.plan`，此时返回空列表 ——
    不能拿 proposal 里的价位冒充"将要下单的价位"。
    """
    risk = summary.get("risk") or {}
    plan = risk.get("plan") or {}
    kind = plan.get("kind") or summary.get("action")
    direction = plan.get("direction") or (summary.get("proposal") or {}).get("direction")
    d = direction_label(direction)
    out: list[str] = []

    if kind == "place_grid":
        layers = plan.get("grid_plan") or []
        if len(layers) == 1:
            # 用户要求：取消网格，只挂预测的那一单
            # 入场价 = 0.618 回调带（回调到位、反弹概率大）
            ly = layers[0]
            tf = plan.get("pullback_tf") or ""
            bn, bf = plan.get("band_near"), plan.get("band_far")
            if tf and bn is not None and bf is not None:
                tag = "（%s 回调带 %.3f~%.3f）" % (tf, min(bn, bf), max(bn, bf))
            elif plan.get("entry_source") == "own_swing":
                tag = "（自研回调带）"
            else:
                tag = ""
            out.append(f"    挂限价单 {d} {ly.get('lots')}手 "
                       f"入场 {_fmt_price(ly.get('level'))}{tag} "
                       f"止损 {_fmt_price(ly.get('sl'))} "
                       f"止盈 {_fmt_price(ly.get('tp'))}"
                       + _src_suffix(plan))
            return out
        out.append(f"    挂单层数: {len(layers)}")
        for i, ly in enumerate(layers, 1):
            out.append(f"      第{i}层 {d} {ly.get('lots')}手 "
                       f"入场 {_fmt_price(ly.get('level'))} "
                       f"止损 {_fmt_price(ly.get('sl'))} "
                       f"止盈 {_fmt_price(ly.get('tp'))}")
        return out

    if kind == "open_market":
        # 市价单：plan 无 entry，用最后收盘价作为参考入场
        ref = summary.get("last_close")
        out.append(f"    {d} {plan.get('lots')}手 入场 市价"
                   + (f"（参考 {_fmt_price(ref)}）" if ref is not None else "")
                   + f" 止损 {_fmt_price(plan.get('sl'))} "
                     f"止盈 {_fmt_price(plan.get('tp'))}"
                   + _src_suffix(plan))
        return out

    if kind == "add_layer":
        # 加仓现在自带结构止损止盈（原实现不带 → 裸仓）
        if plan.get("sl") or plan.get("tp"):
            out.append(f"    {d} {plan.get('lots')}手 市价加仓"
                       f" 止损 {_fmt_price(plan.get('sl'))} "
                       f"止盈 {_fmt_price(plan.get('tp'))}"
                       + _src_suffix(plan))
        else:
            out.append(f"    {d} {plan.get('lots')}手 市价加仓"
                       f"（止损止盈沿用原持仓）")
        return out

    if kind == "modify_sltp":
        out.append(f"    {d} 止损移动至 {_fmt_price(plan.get('new_sl'))}")
        return out

    return out


def _format_summary(n: int, summary: dict) -> str:
    """把一轮的 summary 拼成控制台摘要（中文，可含价位明细）。

    ⚠️ **字符集约束**：Windows 控制台默认 GBK。
    中文在 GBK 内，可安全输出；但 `✓`(U+2713)、`⛔`(U+26D4) **不在** GBK 内，
    拼进来会让 `print` 抛 `UnicodeEncodeError`。

    实测事故（严重）：原实现写作
    ``line += "  ✓" if ex.get("ok") else ...``，
    `✓` **只在执行成功时**才拼接 —— 所以进程恰好会在
    **第一次真正开仓**的那一轮崩溃。日志看起来"能跑"，
    实际一交易就死，比不开仓更危险。

    所以：**用纯中文标签表达成功/失败，不用装饰性符号。**
    `_safe_print` 仍保留三级编码兜底，作为最后一道防线。

    抽成纯函数是为了让测试能直接覆盖这条拼接路径
    （在 print 行上做源码扫描会漏掉上一行的字面量）。
    """
    score = summary.get("score")
    sigma = summary.get("sigma")
    if score is None:
        return json.dumps(summary, ensure_ascii=False, default=str)
    prop = summary.get("proposal") or {}
    direction = prop.get("direction")
    action = summary.get("action", "?")
    act = kind_label(action)
    # 下单轮次必须能一眼看出方向（否则控制台只剩一个动作名）
    if direction and action not in ("hold", "skip_round", "safe_hold"):
        act = f"{act} {direction_label(direction)}"
    line = f"[第{n}轮] 融合分={score:+.2f} 标准差={sigma:.2f} -> {act}"
    risk = summary.get("risk") or {}
    if not risk.get("ok", True):
        line += f"  【被风控拦截】{_zh_reason(risk.get('reason'))}"
        return line
    # 通过风控（或无需风控）时，把价位明细附在后面
    details = _order_lines(summary)
    ex = summary.get("execution")
    if ex:
        line += "  【执行成功】" if ex.get("ok") else f"  【执行失败】{ex.get('error')}"
    if details:
        return line + "\n" + "\n".join(details)
    return line


def _safe_print(line: str) -> None:
    """打印到控制台，**任何编码问题都不得中断交易循环**。

    Windows 控制台默认 GBK。若 stdout 无法编码某字符（`✓`、`σ`、`⛔`、
    中文在纯 ASCII 终端下等），`print` 会抛 `UnicodeEncodeError`。
    实测事故：这行 print 在**第一次开仓**时把整个进程打崩
    （`✓` 只在执行成功时拼接）—— 系统"能跑"但一交易就死。

    兜底顺序：原样 → 替换不可编码字符 → 纯 ASCII 转义。
    """
    for attempt in (line,
                    line.encode(sys.stdout.encoding or "ascii", "replace").decode(
                        sys.stdout.encoding or "ascii", "replace"),
                    line.encode("ascii", "backslashreplace").decode("ascii")):
        try:
            print(attempt, flush=True)
            return
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        except Exception:
            return


def _acquire_single_instance_lock(dry: bool):
    """确保同一账号只有一个 main.py 在跑。返回锁文件句柄（失败则退出）。

    ⚠️ 实测事故：两个 main.py 同时运行（一个手动启动、一个后台任务），
    它们**共用同一个 MT5 账号和 magic**，各自独立决策、各自下单 ——
    网格单会翻倍、撤单会互相打断、`grid_state.json` 会互相覆盖。
    实盘上这是直接的资金风险，必须在启动时就拦住。

    做法：原子创建 `data/runner.lock`（`O_CREAT|O_EXCL`）并写入自己的 pid。
    已存在时读 pid 判断该进程是否还活着：
      - 活着 → 拒绝启动（exit 2）
      - 已死（崩溃残留）→ 接管，不会留下需要手工清理的死锁文件

    ⚠️ 不用 `msvcrt.locking`：它锁的是**当前文件位置起**的字节区间，
      两个句柄的初始位置可能不同，实测第二个进程照样能拿到锁。

    `dry_run` 不加锁（允许与实盘并存做演练）。
    """
    if dry:
        return None
    lock_path = CFG.state_path.parent / "runner.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            if os.name == "nt":
                out = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True, text=True, errors="replace")
                return str(pid) in (out.stdout or "")
            os.kill(pid, 0)              # POSIX：信号 0 只探测存在性
            return True
        except Exception:
            return False

    for _ in range(2):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
        except FileExistsError:
            old = -1
            with contextlib.suppress(Exception):
                old = int(lock_path.read_text(encoding="utf-8").strip() or -1)
            if _pid_alive(old):
                _safe_print(f"【致命】已有另一个 main.py 在运行（进程号={old}），"
                            f"共用同一 MT5 账号与 magic。")
                _safe_print("【致命】拒绝启动：两个进程会重复下单并互相覆盖网格状态。"
                            "请先停止另一个。")
                sys.exit(2)
            # 残留锁（进程已死）→ 清掉后重试一次
            _safe_print(f"【警告】发现残留锁文件（进程号={old} 已不存在）-> 接管")
            with contextlib.suppress(Exception):
                lock_path.unlink()
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        return lock_path
    _safe_print("【致命】无法获取 runner.lock")
    sys.exit(2)


async def main_async(dry: bool, rounds: int | None) -> None:
    CFG.ensure_dirs()
    if dry:
        CFG.trade_mode = "dry_run"
    lock_path = _acquire_single_instance_lock(dry)
    graph = Graph.build()
    # 启动自检
    report = await graph.client.doctor()
    if not report.get("ok"):
        print(json.dumps({"fatal": "doctor failed", "report": report}, ensure_ascii=False))
        sys.exit(1)
    log_info(f"启动自检通过：{report['checks']['account']}")
    if CFG.trade_mode == "live" and not getattr(graph.client, "_connected", False):
        # doctor 内部线程初始化成功但 _connected 标志未同步；显式补一次
        await graph.client.initialize()

    # 轮号跨进程持久（用户要求：重启不从 1 开始，便于日志对照）
    round_state_path = CFG.state_path.parent / "runner_state.json"
    try:
        n = int(json.loads(round_state_path.read_text(encoding="utf-8")).get("round", 0))
    except Exception:
        n = 0
    try:
        while rounds is None or n < rounds:
            n += 1
            round_state_path.parent.mkdir(parents=True, exist_ok=True)
            round_state_path.write_text(json.dumps({"round": n}), encoding="utf-8")
            # 市场休市检测（周六全天 / 周日早段 MT5 无新K线 → 空转烧限额，跳过）
            try:
                st_now = graph.client.symbol_info_tick() if hasattr(graph.client, "symbol_info_tick") else None
            except Exception:
                st_now = None
            if st_now is None:
                # 周六 05:00 UTC 到 周日 21:00 UTC 视为休市（黄金 CFD 常规）
                import datetime as _dt
                _utc = _dt.datetime.now(_dt.timezone.utc)
                if _utc.weekday() == 5 or (_utc.weekday() == 6 and _utc.hour < 21):
                    _safe_print(f"【休市】{_utc:%Y-%m-%d %H:%M} UTC 市场休市，跳过本轮")
                    await asyncio.sleep(max(CFG.decision.loop_interval_s * 10, 600))
                    continue
            summary = await graph.run_round(n)
            # 一行式控制台摘要（信号分 / 动作 / 风控 / 执行），PyCharm 运行窗直接可见
            _safe_print(_format_summary(n, summary))
            interval = CFG.decision.loop_interval_s
            await asyncio.sleep(interval)
    except KeyboardInterrupt:
        log_info("已被用户中断")
    finally:
        with contextlib.suppress(Exception):
            await graph.close()
        # 释放单实例锁（进程崩溃时残留锁会被下一个进程识别为 stale 并接管）
        if lock_path is not None:
            with contextlib.suppress(Exception):
                lock_path.unlink()


def main() -> None:
    ap = argparse.ArgumentParser(description="GoldAgent runner")
    ap.add_argument("--dry", action="store_true", help="dry_run mode: 不真实下单")
    ap.add_argument("--rounds", type=int, default=None, help="运行 N 轮后退出（默认无限）")
    args = ap.parse_args()
    asyncio.run(main_async(dry=args.dry, rounds=args.rounds))


if __name__ == "__main__":
    main()
