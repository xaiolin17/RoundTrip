"""中枢位置判定单元测试（用户反馈"单子经常挂在中枢中部"）。

背景
----
实测 127 笔真实单子里 123 笔走 `open_market`（`entry=ctx.last_close`），
全链路没有一行代码读中枢。配对零假设检验显示择时与"随机时刻入场"
统计上无法区分（真实中间带 56.6% vs 对照 57.1%）。

用户选定：先加**硬闸**（禁止中部开仓），确认中枢数据落盘正确后，
再做"边际入场 / 突破入场"的方向逻辑。

本文件只测 `risk/zhongshu.py` 的纯函数；决策层的闸在
`test_decision_real.py`。
"""
from __future__ import annotations

from gold_agent.risk.zhongshu import (EDGE_BAND, CenterView, center_of,
                                      edge_side)


class _Res:
    """最小 ChanlunResult 替身。"""

    def __init__(self, zg=None, zd=None, gg=None, dd=None, status="ok",
                 cid="center:5m:test"):
        self.status = status
        self.center = (None if zg is None and zd is None else
                       {"zg": zg, "zd": zd, "gg": gg, "dd": dd, "id": cid})


def test_center_of_picks_primary_tf():
    """5m 优先于 1m（用户选定：5m 为主）。"""
    cv = center_of({"5m": _Res(4140.0, 4120.0), "1m": _Res(4130.0, 4125.0)},
                   4130.0, atr=10.0)
    assert cv.ok
    assert cv.tf == "5m", "必须优先 5m"
    assert (cv.zg, cv.zd) == (4140.0, 4120.0)
    assert cv.width == 20.0


def test_center_of_falls_back_to_1m_when_5m_degenerate():
    """5m 退化（zg==zd）时回退 1m —— 实测 1m 有 18% 退化，必须有兜底。"""
    cv = center_of({"5m": _Res(4129.733, 4129.733),   # 零宽
                    "1m": _Res(4135.0, 4125.0)},
                   4130.0, atr=10.0)
    assert cv.ok, f"应回退到 1m，实际 {cv.reason}"
    assert cv.tf == "1m"
    assert "degenerate" in cv.reason, cv.reason


def test_center_of_rejects_too_narrow():
    """中枢宽度 < min_width_atr × ATR -> 边界在噪音里，不作判据。"""
    cv = center_of({"5m": _Res(4130.05, 4130.0)}, 4130.0, atr=100.0)
    assert not cv.ok
    assert "too_narrow" in cv.reason, cv.reason


def test_center_of_handles_missing_and_bad_input():
    """各种缺失都不得抛错，且必须给出可读原因。"""
    assert not center_of(None, 4130.0).ok
    assert not center_of({}, 4130.0).ok
    assert not center_of({"5m": _Res()}, 4130.0).ok          # center=None
    assert not center_of({"5m": _Res(4140.0, 4120.0)}, 0.0).ok   # 无价格
    assert not center_of({"5m": _Res(4140.0, 4120.0)}, None).ok
    # status 非 ok
    cv = center_of({"5m": _Res(4140.0, 4120.0, status="unavailable")}, 4130.0)
    assert not cv.ok
    assert "unavailable" in cv.reason
    # 垃圾值
    bad = _Res(4140.0, 4120.0)
    bad.center = {"zg": "abc", "zd": None}
    assert not center_of({"5m": bad}, 4130.0).ok


def test_edge_side_classification():
    """贴边 / 中部 / 突破 的分类（band 由 config 控制，默认 0.30）。"""
    def side(px):
        cv = center_of({"5m": _Res(4140.0, 4120.0)}, px, atr=None)
        return edge_side(cv, "LONG")

    assert side(4110.0) == "below"    # 跌破下沿
    assert side(4120.0) == "at_zd"    # 贴下沿
    assert side(4126.0) == "at_zd"    # pos=0.30 边界
    assert side(4130.0) == "mid"      # 正中 -> 禁止区
    assert side(4134.0) == "at_zg"    # pos=0.70 边界
    assert side(4140.0) == "at_zg"    # 贴上沿
    assert side(4150.0) == "above"    # 突破上沿


def test_edge_side_unknown_without_center():
    """没有有效中枢时必须返回 unknown（调用方据此**放行**，保守）。"""
    assert edge_side(CenterView(), "LONG") == "unknown"
    cv = center_of({}, 4130.0)
    assert edge_side(cv, "LONG") == "unknown"


def test_center_view_to_dict_is_log_safe():
    """落盘用 dict 必须是 JSON 可序列化的纯标量，且缺值用 None。"""
    import json

    cv = center_of({"5m": _Res(4140.0, 4120.0, gg=4148.0, dd=4112.0)},
                   4130.0, atr=None)
    d = cv.to_dict()
    assert d["zg"] == 4140.0 and d["zd"] == 4120.0
    assert d["pos"] == 0.5
    assert d["dist_edge"] == 10.0
    json.dumps(d)          # 必须可序列化
    # 无效中枢也要能安全落盘
    json.dumps(center_of({}, 4130.0).to_dict())


def test_edge_band_is_configurable():
    """带宽可配置（默认 0.30 -> 中部 40% 为禁区）。"""
    from gold_agent.common.config import CFG

    assert abs(CFG.risk.zhongshu_edge_band - EDGE_BAND) < 1e-9
    assert CFG.risk.zhongshu_gate is True
    assert tuple(CFG.risk.zhongshu_tfs) == ("5m", "1m")
    assert abs(CFG.risk.zhongshu_min_width_atr - 0.25) < 1e-9


def test_small_timeframes_are_prioritised():
    """用户要求"优先看小周期"：必须优先 5m，不能用大周期中枢判贴边。

    入场择时是 1m/5m 的尺度；用 1h/4h 中枢判"贴边"会离现价太远，
    永远判不出可交易的位置。
    """
    from gold_agent.common.config import CFG

    # 1) 配置里就是小周期在前
    tfs = tuple(CFG.risk.zhongshu_tfs)
    assert tfs[0] == "5m", f"首选必须是 5m，实际 {tfs}"
    assert "1m" in tfs, f"1m 必须作为兜底，实际 {tfs}"
    # 不得出现大周期
    for big in ("1h", "4h", "1d"):
        assert big not in tfs, f"不同周期不应参与贴边判定：{big}"
    # 2) 全部可用时选第一个（5m），不被 1m 抢走
    cv = center_of({"5m": _Res(4140.0, 4120.0),
                    "1m": _Res(4135.0, 4125.0),
                    "1h": _Res(4200.0, 4000.0)}, 4130.0, atr=1.0)
    assert cv.tf == "5m", f"应选 5m，实际 {cv.tf}"
    # 3) 5m 不可用时才回退 1m，并记录尝试顺序
    cv2 = center_of({"5m": _Res(4129.9, 4129.9),      # 退化
                     "1m": _Res(4135.0, 4125.0),      # 有效兜底
                     "1h": _Res(4200.0, 4000.0)},     # 大周期不参与
                    4130.0, atr=1.0)
    assert cv2.tf == "1m", f"5m 退化应回退 1m，实际 {cv2.tf}"
    assert cv2.considered == ("5m", "1m"), cv2.considered


def test_considered_records_attempt_order():
    """considered 必须如实记录尝试过的周期（供事后确认优先级生效）。"""
    cv = center_of({"5m": _Res(4140.0, 4120.0)}, 4130.0, atr=1.0)
    assert cv.considered == ("5m", "1m"), cv.considered
    assert cv.to_dict()["considered"] == ["5m", "1m"]
    # 全部不可用时也要记录
    bad = center_of({}, 4130.0)
    assert bad.considered == ("5m", "1m"), bad.considered
    # 自定义顺序也要如实反映
    cv3 = center_of({"1m": _Res(4140.0, 4120.0)}, 4130.0, atr=1.0,
                    tfs=("1m", "5m"))
    assert cv3.tf == "1m" and cv3.considered == ("1m", "5m")


def test_min_width_atr_is_config_driven():
    """宽度下限必须读配置（不能硬编码），且改配置立即生效。"""
    from gold_agent.common.config import CFG

    old = CFG.risk.zhongshu_min_width_atr
    try:
        # 宽度 20 点，ATR 10 -> 20 >= 0.25*10=2.5 通过
        assert center_of({"5m": _Res(4140.0, 4120.0)}, 4130.0, atr=10.0).ok
        # 把下限提到 5.0 -> 需要宽度 >= 50 点，20 点不够
        CFG.risk.zhongshu_min_width_atr = 5.0
        cv = center_of({"5m": _Res(4140.0, 4120.0)}, 4130.0, atr=10.0)
        assert not cv.ok, "提高下限后应变不可用"
        assert "too_narrow" in cv.reason, cv.reason
    finally:
        CFG.risk.zhongshu_min_width_atr = old
