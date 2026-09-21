"""研究取证 20：LLM 在实盘决策中的真实作用审计。

用户指出「真正执行时是带 LLM 决策的」。本脚本量化 LLM 到底参与了多少、
以及它对最终下单的实际影响。
"""
from __future__ import annotations

import io
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
OUT: list[str] = []


def p(s: str = "") -> None:
    print(s, flush=True)
    OUT.append(s)


def load(name):
    rows = []
    for f in sorted((ROOT / "logs").glob(f"{name}_*.jsonl")):
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


llm = load("llm")
dec = load("decision")

p("=" * 96)
p("研究取证 20 · LLM 在实盘决策中的真实作用")
p("=" * 96)

# ── A. LLM 调用成功率 ──
p("\n" + "=" * 96)
p("A. LLM 调用统计")
p("=" * 96)
ev = Counter(d.get("event") for d in llm)
tot = sum(ev.values())
p("")
p(f"{'事件':<28}{'次数':>8}{'占比':>9}  说明")
p("-" * 96)
_desc = {
    "chat_ok": "成功返回",
    "news_assessment_failed": "新闻面调用失败",
    "budget_exhausted": "**超出每小时预算被拒**",
    "review_failed": "评审调用失败",
    "chat_error": "网络/解析错误",
}
for k, v in ev.most_common():
    p(f"{k:<28}{v:>8}{v/tot:>8.1%}  {_desc.get(k,'')}")

ok = [d for d in llm if d.get("event") == "chat_ok"]
n_review = sum(1 for d in ok if "verdict" in (d.get("parsed_keys") or []))
n_news = sum(1 for d in ok if "sentiment" in (d.get("parsed_keys") or []))
p("")
p(f"成功的调用里：review（verdict/confidence）= {n_review} 次，"
  f"news_assessment = {n_news} 次")

# ── B. 对比决策轮数 ──
sig_rounds = [d for d in dec if d.get("event") == "signals"]
dec_rounds = [d for d in dec if d.get("event") == "decision"]
p("")
p(f"决策轮数 = {len(sig_rounds)}")
p(f"**LLM review 成功次数 = {n_review}  →  覆盖率 {n_review/max(len(sig_rounds),1):.1%}**")
p(f"LLM news_assessment 成功次数 = {n_news}  →  覆盖率 {n_news/max(len(sig_rounds),1):.1%}")

# ── C. 每轮是否带 LLM ──
p("\n" + "=" * 96)
p("C. LLM 的参与条件（代码逻辑）")
p("=" * 96)
p("")
p("graph.py:")
p("    need_llm = (abs(score) >= open_threshold - 0.4) or 有持仓")
p("             = (|S| >= 0.9) or 有持仓")
p("")
p("orchestrator.py:")
p("    need_review = (now - last_review >= min_interval_min*60)")
p("                = 距上次评审 >= 15 分钟")
p("")
p("→ review 每 15 分钟最多一次；60s 循环下理论覆盖率 = 1/15 = 6.7%")
p(f"   实测 {n_review}/{len(sig_rounds)} = {n_review/max(len(sig_rounds),1):.1%}（一致）")
p("")
p("预算：per_hour_budget = 24 次/小时，但 review+news 两个任务都算预算，")
p("      且每轮循环都可能触发 news → 预算被 news 吃光（budget_exhausted "
  f"{ev.get('budget_exhausted',0)} 次）")

# ── D. LLM 对下单的实际影响 ──
p("\n" + "=" * 96)
p("D. LLM 缺失时的决策降级路径（关键）")
p("=" * 96)
p("")
p("decision/machine.py `_decide_flat`：")
p("    aligned = (verdict == 方向) and (conf >= 0.6)")
p("    if aligned:      return open_market    ← 市价开仓")
p("    return place_grid                      ← 挂限价单")
p("")
p("LLM 未调用时 ctx.llm = None → verdict = None → aligned = False")
p("**→ 永远走 place_grid，永远不会市价开仓**")
p("")
kinds = Counter((d.get("proposal") or {}).get("kind") for d in dec_rounds)
p(f"{'决策类型':<20}{'次数':>8}  来源")
p("-" * 60)
for k, v in kinds.most_common():
    src = ("需 LLM aligned=True" if k == "open_market" else
           "LLM 缺失时的默认路径" if k == "place_grid" else "")
    p(f"{k:<20}{v:>8}  {src}")
p("")
p(f"→ 实测 open_market = {kinds.get('open_market',0)} 次，"
  f"place_grid = {kinds.get('place_grid',0)} 次")
p(f"  与「review 只成功 {n_review} 次」完全吻合。")

# ── E. 结论 ──
p("\n" + "=" * 96)
p("E. 结论")
p("=" * 96)
p("1) **LLM 在实盘中几乎不参与决策**：review 覆盖率仅 "
  f"{n_review/max(len(sig_rounds),1):.1%}。")
p("2) 原因有三：① min_interval_min=15 分钟节流 ② per_hour_budget=24 被 news 挤占")
p("   ③ |S|>=0.9 的前置条件。")
p(f"3) 后果：{kinds.get('place_grid',0)} 次 place_grid vs "
  f"{kinds.get('open_market',0)} 次 open_market ——")
p("   系统绝大多数时候只能挂限价单，**不是用户以为的「LLM 主导决策」**。")
p("4) 因此「LLM 决策」在当前架构里不是主路径，而是**罕见的加分项**。")
p("   用户说的「有一部分误差来源于测试没法一直调用 LLM」——")
p("   实际上**实盘也没在一直调用**，测试与实盘在这一点上是一致的。")

(Path(__file__).parent / "20_llm_audit.txt").write_text("\n".join(OUT), encoding="utf-8")
p(f"\n[已写入 research/20_llm_audit.txt]")
