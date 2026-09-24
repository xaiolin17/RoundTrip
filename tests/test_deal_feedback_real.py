# -*- coding: utf-8 -*-
"""交割单 → 贝叶斯反馈闭环测试（用户报告「无预测符号（未桥接，跳过贝叶斯）」）。

事故背景
--------
用户实盘日志反复出现：

    [WARN] 交割单 2557685340: 无预测符号（未桥接，跳过贝叶斯）

排查发现这条闭环**从未生效过**：
  - `data/trade_stats.json` 里 17 笔已平仓交易 `pred_sign` **全部为 None**
  - `logs/trades.jsonl` 里 `bayes_feedback` 记录 **0 条**
  - 贝叶斯池一直靠先验在跑，从未被实盘结果校准

三处缺陷：
1. **键不匹配**：`poll()` 用平仓 deal 的 `order` 去 pop，而平仓 order 是
   新 ticket（实测 开仓 2557969245 / 平仓 2558130417），
   与开仓时记录的 order ticket 永远不等。
2. **加仓漏记**：`add_layer` 开的是新仓位，但分支里没有记录预测符号。
3. **返回值错误**：`poll()` 返回原始 deal（无 `pnl`/`pred_sign`），
   调用方读 `d["pred_sign"]` 永远拿不到。
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest

from gold_agent.common.config import CFG
from gold_agent.fusion.bayes import BayesianPool
from gold_agent.fusion.deal_feedback import DealFeedback
from gold_agent.risk.position import CircuitBreakers


@pytest.fixture
def state_dir():
    """本机 tmp_path 固定名目录被拒（WinError 5），用项目内临时目录代替。"""
    d = Path(CFG.project_root) / "_test_state_tmp"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)

# 真实结构（实测自 Exness XAUUSDm 交割单）
OPEN_DEAL = {"ticket": 1, "order": 2557969245, "position_id": 2557969245,
             "time": 1000.0, "type": 0, "volume": 0.01, "price": 4300.0,
             "profit": 0.0, "swap": 0.0, "commission": 0.0, "fee": 0.0,
             "symbol": "XAUUSDm", "comment": "goldagent-open",
             "magic": CFG.mt5.magic}
CLOSE_DEAL = {"ticket": 2, "order": 2558130417, "position_id": 2557969245,
              "time": 2000.0, "type": 1, "volume": 0.01, "price": 4314.0,
              "profit": 14.25, "swap": 0.0, "commission": 0.0, "fee": 0.0,
              "symbol": "XAUUSDm", "comment": "goldagent-close",
              "magic": CFG.mt5.magic}


class _FakeClient:
    """只返回离场 deal（与 client._deals_sync 的 entry in (1,2) 过滤一致）。"""

    def __init__(self, close_deal: dict) -> None:
        self._d = close_deal

    async def get_deals(self, since_ts: float) -> list[dict]:
        return [self._d]


def _feedback(state_dir) -> DealFeedback:
    fb = DealFeedback(BayesianPool(), CircuitBreakers(), state_dir=state_dir)
    fb.cursor = 0.0
    return fb


def test_close_order_differs_from_open_order():
    """前提事实：平仓 deal 的 order 与开仓 order 不同（这是事故根因）。"""
    assert CLOSE_DEAL["order"] != OPEN_DEAL["order"]
    # 而 position_id 在两笔 deal 中一致 —— 所以 position_id 才是正确键
    assert CLOSE_DEAL["position_id"] == OPEN_DEAL["position_id"]


def test_pred_sign_bridged_by_position_id(state_dir):
    """核心回归：按 position_id 记录预测符号后，平仓时能取回。"""
    fb = _feedback(state_dir)
    pred_orders = {str(OPEN_DEAL["order"]): -1}      # 做空
    closed = asyncio.run(fb.poll(_FakeClient(CLOSE_DEAL), pred_orders))
    assert len(closed) == 1
    assert closed[0]["pred_sign"] == -1, "预测符号必须能经 position_id 桥接回填"
    assert pred_orders == {}, "桥接后应消费掉该键，避免重复回填"


def test_poll_returns_enriched_records(state_dir):
    """poll() 必须返回带 pnl / direction / pred_sign 的增强记录。

    原实现返回原始 deal -> 调用方 `d.get('pnl', 0)` 恒为 0、
    `d['pred_sign']` 取不到 -> 贝叶斯永远不更新。
    """
    fb = _feedback(state_dir)
    closed = asyncio.run(fb.poll(_FakeClient(CLOSE_DEAL), {"2557969245": 1}))
    d = closed[0]
    for key in ("pnl", "direction", "pred_sign", "position_id"):
        assert key in d, f"返回记录缺少 {key}"
    assert d["pnl"] == pytest.approx(14.25)
    # 平仓 deal type=1(sell) -> 原持仓是 LONG（与 _deal_direction 的约定一致）
    assert d["direction"] == 1


def test_old_order_key_still_works(state_dir):
    """兼容：经纪商 order == position_id 时，旧键格式仍能命中。"""
    fb = _feedback(state_dir)
    deal = {**CLOSE_DEAL, "order": OPEN_DEAL["order"]}
    closed = asyncio.run(fb.poll(_FakeClient(deal), {str(OPEN_DEAL["order"]): 1}))
    assert closed[0]["pred_sign"] == 1


def test_dict_valued_pred_entry(state_dir):
    """兼容：值写成 {"sign": ...} 的旧格式。"""
    fb = _feedback(state_dir)
    closed = asyncio.run(fb.poll(_FakeClient(CLOSE_DEAL),
                                 {"2557969245": {"sign": -1, "pos": "2557969245"}}))
    assert closed[0]["pred_sign"] == -1


def test_missing_pred_yields_none(state_dir):
    """完全没记录时返回 None（调用方据此告警，而不是静默算成 0）。"""
    fb = _feedback(state_dir)
    closed = asyncio.run(fb.poll(_FakeClient(CLOSE_DEAL), {}))
    assert closed[0]["pred_sign"] is None


def test_bayes_pool_updated_from_bridged_outcome(state_dir):
    """端到端：桥接回填的符号真的能驱动贝叶斯 record_outcome。"""
    fb = _feedback(state_dir)
    closed = asyncio.run(fb.poll(_FakeClient(CLOSE_DEAL), {"2557969245": -1}))
    pred = closed[0]["pred_sign"]
    actual = 1 if closed[0]["pnl"] > 0 else -1
    assert (pred, actual) == (-1, 1), "预测做空 + 实际盈利"
    for src in ("kalman_persist", "chanlun", "openmobius_smc", "classic_indicators"):
        fb.bayes.record_outcome(src, pred, actual)
    fb.bayes.save()          # 不得抛异常


def test_record_pred_persists_by_order_ticket(state_dir, monkeypatch):
    """graph._record_pred：成交后按 order ticket 落盘（跨轮次/重启可回填）。"""
    from gold_agent.agent import graph as G

    written: dict = {}

    class _G(G.Graph):
        def _save_pred_orders(self) -> None:      # 拦截落盘
            written.clear()
            written.update(self._pred_orders)

    g = _G.__new__(_G)
    g._pred_orders = {}

    class _Res:
        ok = True
        order = 2557969245

    class _Fused:
        class result:
            score = -1.66

    _G._record_pred(g, _Res(), {"fused": _Fused()})
    assert written == {"2557969245": -1}, "应按 order ticket 记为做空(-1)"


def test_record_pred_skips_without_ticket(state_dir):
    """未返回 order ticket 时跳过并告警，不得写入垃圾键。"""
    from gold_agent.agent import graph as G

    g = G.Graph.__new__(G.Graph)
    g._pred_orders = {}

    class _Res:
        ok = True
        order = 0

    class _Fused:
        class result:
            score = 1.0

    G.Graph._record_pred(g, _Res(), {"fused": _Fused()})
    assert g._pred_orders == {}


def test_graph_has_no_dead_pending_pred():
    """`_pending_pred` 已废弃（内存字典，重启即丢），不得再被引用。

    只检查**可执行代码**：注释/文档字符串里提到这个历史缺陷名是允许的。
    """
    import ast

    from gold_agent.agent import graph as G
    assert not hasattr(G.Graph, "_pending_pred"), "_pending_pred 应已删除"
    tree = ast.parse(open(G.__file__, encoding="utf-8").read())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "_pending_pred" not in names, "graph.py 代码仍引用已删除的 _pending_pred"


def test_bayes_actual_uses_direction_not_pnl_sign():
    """**核心回归**：贝叶斯 actual = 实际价格走势方向 = 持仓方向 × 盈亏符号。

    ⚠️ 事故（用户反馈"信号权重被压制"）：原实现 `actual = 1 if pnl>0
    else -1` 把"盈利"当成"方向对"。做空单盈利时 pnl>0 → actual=+1，
    但价格实际**下跌**（方向=-1）→ pred=-1 ≠ actual=+1 → 盈利做空单
    全被记为"未命中"。实测最近 5 笔盈利做空单（+2.22/+9.04/+2.50/
    +4.36/+6.61）全被误判，贝叶斯池被压到 9胜20负（p=0.31）反向压分，
    508 轮无一达到开仓阈值。修复后 12胜8负（p=0.59）正向支持。
    """
    from gold_agent.agent import graph as G
    # 复刻 graph.py 修复后的 actual 计算（从源码提取语义，防止回归）
    src = open(G.__file__, encoding="utf-8").read()
    assert "actual = direction" in src, "graph.py 必须用方向×盈亏算 actual"
    assert "pnl > 0" in src, "盈亏符号必须参与"
    # 直接验证语义
    calc = lambda pnl, direction: (direction if pnl > 0
                                   else (-direction if pnl < 0 else 0))
    assert calc(2.22, -1) == -1, "做空盈利 = 价格下跌 = actual -1（命中 pred=-1）"
    assert calc(-9.05, -1) == 1, "做空亏损 = 价格上涨 = actual +1（未命中 pred=-1）"
    assert calc(15.06, 1) == 1, "做多盈利 = 价格上涨 = actual +1"
    assert calc(-6.0, 1) == -1, "做多亏损 = 价格下跌 = actual -1"
