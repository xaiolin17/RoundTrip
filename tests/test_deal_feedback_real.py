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
    """注意：贝叶斯池用 state_dir 下的隔离文件，避免读写实盘
    `data/bayes_state.json`（git 跟踪文件），否则断言依赖实盘历史、且会污染。"""
    fb = DealFeedback(BayesianPool(state_path=Path(state_dir) / "bayes.json"),
                      CircuitBreakers(), state_dir=state_dir)
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
    """graph._record_pred：成交后按 order ticket 落盘（跨轮次/重启可回填）。

    ⚠️ 按源调权重（用户选定方案）后，值从 int 升级为
    {"fused": 融合分符号, "src": {源名: 该源分数符号}}。
    """
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
    assert written["2557969245"]["fused"] == -1, "融合分符号应记为做空(-1)"
    assert written["2557969245"]["src"] == {}, "无 per_source 时 src 快照为空字典"


def _snapshot(per_source, score=-1.66, ticket=2557969245):
    """构造 _record_pred 输入并返回落盘快照（复用 _G 拦截落盘）。"""
    from gold_agent.agent import graph as G

    written: dict = {}

    class _G(G.Graph):
        def _save_pred_orders(self) -> None:
            written.clear()
            written.update(self._pred_orders)

    g = _G.__new__(_G)
    g._pred_orders = {}

    class _Res:
        ok = True
        order = ticket

    class _Result:
        pass

    _Result.score = score
    _Result.per_source = per_source

    class _Fused:
        result = _Result()

    _G._record_pred(g, _Res(), {"fused": _Fused()})
    return written


def test_per_source_pred_snapshot(state_dir):
    """**核心**：快照必须记录**每个源自己**的分数符号，而非融合分符号。

    原实现只存融合分符号 -> 平仓时 4 源喂同一个 pred_sign ->
    4 源 stats 永远相同 -> 权重永远相同，贝叶斯只是"整体信任度"。
    """
    snap = _snapshot([
        {"name": "kalman_persist", "score": -1.2, "w": 0.5},
        {"name": "chanlun", "score": 0.4, "w": 0.3},          # 与融合分相反
        {"name": "openmobius_smc", "score": 0.0, "w": 0.2},   # 无方向
    ])["2557969245"]
    assert snap["fused"] == -1
    assert snap["src"]["kalman_persist"] == -1
    assert snap["src"]["chanlun"] == 1, "与融合分方向相反的源必须保留自己的符号"
    assert snap["src"]["openmobius_smc"] == 0, "分数 0 -> 无方向 -> 不计入"


def test_zero_score_source_skipped(state_dir):
    """被排除（zero_weight/未验证）的源不给方向，符号记 0 -> 不计入贝叶斯。"""
    snap = _snapshot([
        {"name": "kalman_persist", "score": 1.0, "w": 0.5},
        {"name": "classic_indicators", "score": 0.9, "w": 0.0,
         "excluded": "zero_weight"},
    ])["2557969245"]
    assert snap["src"]["kalman_persist"] == 1
    assert snap["src"]["classic_indicators"] == 0, "excluded 源不得给方向"


def test_poll_passes_src_preds_through(state_dir):
    """poll() 必须把 src_preds 透传给调用方（否则按源记账拿不到每源符号）。"""
    fb = _feedback(state_dir)
    snap = {"fused": -1, "src": {"kalman_persist": -1, "chanlun": 1}}
    closed = asyncio.run(fb.poll(_FakeClient(CLOSE_DEAL), {"2557969245": snap}))
    d = closed[0]
    assert d["pred_sign"] == -1, "pred_sign 取 fused（兼容旧逻辑）"
    assert d["src_preds"] == snap["src"], "src_preds 必须原样透传"


def test_bayes_per_source_independent(state_dir):
    """**核心**：两个源方向不同 -> 平仓后命中率分化（这正是用户要的行为）。

    `CLOSE_DEAL` 是**平掉一笔盈利多单**（type=1=sell 平仓 -> 原持仓 LONG），
    pnl>0 -> actual = 持仓方向 = +1（价格上涨）。
    kalman 预测 -1（未命中）、chanlun 预测 +1（命中）-> stats 必须不同。
    """
    fb = _feedback(state_dir)
    snap = {"fused": -1, "src": {"kalman_persist": -1, "chanlun": 1}}
    closed = asyncio.run(fb.poll(_FakeClient(CLOSE_DEAL), {"2557969245": snap}))
    d = closed[0]
    pnl, direction = d["pnl"], d["direction"]
    actual = direction if pnl > 0 else (-direction if pnl < 0 else 0)
    assert direction == 1, "平仓 deal type=1(sell) -> 原持仓为做多"
    assert actual == 1, "做多盈利 -> 价格上涨 -> actual +1"
    for src in ("kalman_persist", "chanlun"):
        pred = d["src_preds"].get(src)
        assert pred in (1, -1), f"{src} 当轮应有方向"
        fb.bayes.record_outcome(src, pred, actual)
    k = fb.bayes._stats["kalman_persist"]
    c = fb.bayes._stats["chanlun"]
    assert (k.hits, k.misses) == (0, 1), "kalman 预测做空但价格上涨 -> 未命中"
    assert (c.hits, c.misses) == (1, 0), "chanlun 预测做多且价格上涨 -> 命中"
    assert (k.hits, k.misses) != (c.hits, c.misses), "各源命中率必须独立分化"


def test_old_int_value_backward_compat(state_dir):
    """旧纯 int 值（`{"ticket": 1}`）平仓仍能记账，src_preds 为空。"""
    fb = _feedback(state_dir)
    closed = asyncio.run(fb.poll(_FakeClient(CLOSE_DEAL), {"2557969245": -1}))
    assert closed[0]["pred_sign"] == -1
    assert closed[0]["src_preds"] == {}


def test_old_dict_value_backward_compat(state_dir):
    """旧 `{"sign": ...}` 字典值平仓仍能记账（新格式无 sign 键也能兜底）。"""
    fb = _feedback(state_dir)
    closed = asyncio.run(fb.poll(_FakeClient(CLOSE_DEAL),
                                 {"2557969245": {"sign": -1, "pos": "2557969245"}}))
    assert closed[0]["pred_sign"] == -1
    assert closed[0]["src_preds"] == {}


def test_legacy_pred_falls_back_to_fused_per_source(state_dir):
    """旧数据无 src 快照 -> 只给**有 IR 权重**的源退回融合分记账，不丢数据。

    ⚠️ 兜底不能覆盖全部 DECISION_SOURCES：`news` 走独立证据通道、IR 表权重为 0，
    一旦在本池攒够样本，`bayes.evidence()`（用池内权重，非 IR 表权重）就会开始
    给它产生证据 —— 违背 weights.py 的硬规则"没有实测 IR 的源 = 0 权重"。
    （`openmobius_smc` 无离线历史但走 PRIOR_ONLY：有权重、可记账，
    故这里只作 `news` 的前置断言。）兜底填的还是**别的源的方向**，更要守住。
    """
    from gold_agent.fusion.engine import FusionEngine
    from gold_agent.fusion.weights import DECISION_SOURCES

    fb = _feedback(state_dir)
    closed = asyncio.run(fb.poll(_FakeClient(CLOSE_DEAL), {"2557969245": -1}))
    d = closed[0]
    src_preds = d["src_preds"] or {}
    assert src_preds == {}, "旧 int 值应无 src 快照"

    engine = FusionEngine()          # 真实 IR 权重表
    weighted = [s for s in DECISION_SOURCES if engine.weights.weight(s) > 0]
    unweighted = [s for s in DECISION_SOURCES if engine.weights.weight(s) <= 0]
    assert unweighted, "本用例前提：存在 0 权重源（news 走独立证据通道）"

    actual = 1                       # 平掉盈利多单 -> 价格上涨
    expected = {s: d["pred_sign"] for s in weighted}   # 旧数据兜底：用融合分
    for src, p in expected.items():
        if p in (1, -1):
            fb.bayes.record_outcome(src, p, actual)

    assert set(fb.bayes._stats) == set(weighted), \
        "旧记录应只更新有 IR 权重的源（不丢数据，且不给 0 权重源喂样本）"
    for s in unweighted:
        assert s not in fb.bayes._stats, f"0 权重源 {s} 不得被兜底记账"


def test_source_names_use_decision_sources_not_hardcoded():
    """graph.py 的记账源名必须取自 DECISION_SOURCES，不得硬编码。

    ⚠️ 为什么：原实现硬编码 4 个源名，而 `DECISION_SOURCES` 有 5 个
    （多一个 `news`）。一旦 `news` 拿到非零权重，它会进入开仓快照
    （per_source 里有），却因为不在硬编码元组里而**永远不被记账**
    -> 该源的贝叶斯统计永远停在先验，权重永远不更新。
    单一出处可以避免这种"加了源忘了改记账"的漂移。
    """
    import ast

    from gold_agent.agent import graph as G
    from gold_agent.fusion.weights import DECISION_SOURCES

    src = open(G.__file__, encoding="utf-8").read()
    assert '"kalman_persist", "chanlun"' not in src, \
        "不得再硬编码源名元组（会漏掉 news）"
    # news 必须在决策源里（否则上面的漂移论证不成立）
    assert "news" in DECISION_SOURCES, "DECISION_SOURCES 应包含 news"

    # DECISION_SOURCES 必须被真正引用两次：新格式遍历 + 旧数据兜底过滤
    tree = ast.parse(src)
    refs = [n for n in ast.walk(tree)
            if isinstance(n, ast.Name) and n.id == "DECISION_SOURCES"]
    assert len(refs) >= 2, \
        "新格式与旧数据兜底两条路径都必须引用 DECISION_SOURCES"


def test_legacy_fallback_filters_zero_weight_sources():
    """**关键**：旧数据兜底必须按 IR 权重过滤，0 权重源永不被喂样本。

    这是行为约束而非实现细节，所以直接断言源码里的过滤条件存在，
    并配合 test_legacy_pred_falls_back_to_fused_per_source 验证语义。
    """
    from gold_agent.agent import graph as G

    src = open(G.__file__, encoding="utf-8").read()
    assert "self.fusion.weights.weight(s) > 0" in src, \
        ("旧数据兜底必须只喂有 IR 权重的源；"
         "否则 news（走独立证据通道、权重为 0）攒够样本后会产生证据，"
         "违背 weights.py '不可测源 = 0 权重' 的硬规则")


def test_missing_key_in_nonempty_snapshot_is_skipped(state_dir):
    """**关键语义**：快照非空但缺某源 = 该源当轮没参与 -> 跳过，不兜底。

    与"快照为空 = 旧数据 -> 兜底"是两回事。若这里也兜底，等于把融合分
    （别的源的合成方向）算到该源头上，会污染它的命中率。
    """
    from gold_agent.fusion.weights import DECISION_SOURCES

    fb = _feedback(state_dir)
    # 快照非空，但只有 kalman / chanlun 参与（news 当轮 news_score==0 未加入，
    # classic 可能被 excluded）
    snap = {"fused": -1, "src": {"kalman_persist": -1, "chanlun": 1}}
    closed = asyncio.run(fb.poll(_FakeClient(CLOSE_DEAL), {"2557969245": snap}))
    d = closed[0]
    src_preds = d["src_preds"]
    assert src_preds, "本场景快照非空"
    actual = 1
    # 镜像 graph.py 的新格式分支：缺键 -> None -> 跳过
    preds = {s: src_preds.get(s) for s in DECISION_SOURCES}
    for src, p in preds.items():
        if p in (1, -1):
            fb.bayes.record_outcome(src, p, actual)
    assert set(fb.bayes._stats) == {"kalman_persist", "chanlun"}, \
        "未参与的源不得被记账（否则命中率被污染）"


def test_snapshot_covers_news_source(state_dir):
    """`_record_pred` 快照的 src 键应覆盖 per_source 提供的每个源（含 news）。"""
    snap = _snapshot([
        {"name": "kalman_persist", "score": 1.0, "w": 0.5},
        {"name": "news", "score": -0.7, "w": 0.3},
    ])["2557969245"]
    assert snap["src"]["news"] == -1, "news 若参与必须有独立符号"
    assert snap["src"]["kalman_persist"] == 1


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
