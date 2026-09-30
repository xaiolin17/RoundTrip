# 合规与监管研究资料索引

本目录存放**商用合规**相关的标准文档与调研报告。分两层：

- **标准文档**（本目录，入库）：可直接指导代码/流程的规范。
- **调研报告**（`research-2026/`，入库）：一次性调研产出，供追溯结论出处。
- **原始证据**（仓库根目录的 `_reg/`、`_research/`、`pdf/`、`sources/`，**不入库**）：
  法规原文、监管问答、学术论文的抓取副本。体积大（~80 MB），
  仅本地保留；`.gitignore` 已排除。

## 标准文档

| 文件 | 内容 |
|---|---|
| `2026-commercial-trading-system-standards.md` | 商用交易系统标准（SR 26-2 / DSR / PBO / MinBTL），**代码验收的依据** |

## 调研报告（`research-2026/`）

| 文件 | 内容 |
|---|---|
| `compliance-certification-report-2026.md` | SOC 2 / ISO 27001 等认证标准与成本（1–3 人 EA 供应商视角） |
| `model-monitoring-drift-reconciliation-2026.md` | 模型监控、漂移检测、对账标准（**SR 26-2 取代 SR 11-7** 的出处） |
| `prop-firm-ea-constraints-2026.md` | 自营交易公司的 EA 技术/规则约束（FTMO 200 单上限等） |
| `regulatory-reality-ea-signals-2026.md` | 卖 EA / 信号是否触发 CTA 注册（美国 CFTC/NFA） |
| `uk-regulatory-findings-2026.md` | 英国 FCA 对自动化交易软件与信号的监管（COBS 4 等） |

## 原始证据目录（不入库）

| 目录 | 内容 |
|---|---|
| `_reg/` | 监管原文：EUR-Lex、ESMA、FCA、NFA、CFTC、PRA |
| `_research/` | 学术论文（Bailey/López de Prado 等）、经纪商与平台条款、ISO/SOC 2 资料 |
| `pdf/` | 监管问答与简报 PDF（ESMA Q&A、CFTC 等） |
| `sources/` | 另一批监管抓取（COBS、FCA、支付服务条例） |
| `sources/raw/` | 早期顶层散落抓取件（MiFID II、DORA、RTS 6、FTMO/The5ers FAQ 等），已归档 |
| `research/pdf/` | 量化论文 PDF 与文本（deflated-sharpe、backtest-prob 等） |

> ⚠️ **移动这些目录时必须同步更新引用。**
> `2026-commercial-trading-system-standards.md` 里有 30 处按路径引用的证据
> （如 `` `_research/sr2602a1.txt` ``、`` `research/pdf/ss123.txt` ``）。
> 校验方法：
>
> ```powershell
> # 抽出文档里的反引号路径并逐个检查是否存在
> $py = "C:\Users\admin\AppData\Local\Programs\Python\Python312\python.exe"
> & $py -c @"
> import re, os
> doc = 'docs/compliance/2026-commercial-trading-system-standards.md'
> t = open(doc, encoding='utf-8').read()
> pat = re.compile(r'`([^`\n]*(?:_reg/|_research/|pdf/|sources/)[^`\n]*)`')
> bad = [p for p in sorted(set(pat.findall(t))) if not os.path.exists(p)]
> print('断链:', bad or '无')
> "@
> ```
>
> 当前状态：**30/30 引用全部可达**。
