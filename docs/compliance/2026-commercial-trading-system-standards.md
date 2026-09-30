# 商业化自动交易系统标准研究报告（2026）

> 面向对象：1–3 人小团队，向零售 / 自营（prop）/ 小型基金客户销售 MT5 Expert Advisor（EA）式自动交易系统或信号产品。
> 标注约定：`[UNVERIFIED]` = 未能从一手来源确认。所有非显然论断均附 URL。

---

## 1. 模型风险管理与治理标准（Model Risk Management / Governance）

### 1.1 美国：SR 11-7 已被 SR 26-2 取代（2026 年重大变化）

**这是本报告最重要的时效性发现。** 2026 年 4 月 17 日，Fed / OCC / FDIC 联合发布 **SR 26-2《Revised Guidance on Model Risk Management》**，明确 **supersede（取代）SR 11-7**（2011-04-04）以及 SR 21-8。
来源：<https://www.federalreserve.gov/supervisionreg/srletters/sr2602.htm>（正文 PDF：<https://www.federalreserve.gov/supervisionreg/srletters/SR2602a1.pdf>）

SR 26-2 的关键结构性变化：

| 项目 | SR 11-7（2011） | SR 26-2（2026） |
|---|---|---|
| 适用范围 | 所有银行机构 | 主要针对 **总资产 > $300 亿** 的机构；≤$300 亿一般被排除在指引之外 |
| 结构 | "三支柱"（开发/实施/使用、验证、治理） | 不再以"三支柱"表述；改为 **risk-based / 按模型风险画像定制** |
| 强制性 | 监管指引 | 明确 "does not set forth enforceable standards or prescriptive requirements"，不合规本身**不会**招致监管批评 |
| 模型定义 | 广义 | 收窄为"**complex** quantitative method"；**排除**简单算术（如电子表格）与**确定性规则流程**及无统计/经济/金融理论支撑的软件；**生成式 AI 与 agentic AI 明确不在范围内** |
| 验证频率 | 惯例"至少每年" | **不再规定强制验证周期（no required validation cadence）** |

来源：SR 26-2 正文第 2–3 页（scope）、第 3 页脚注 3（GenAI 排除）、第 1 页脚注 1（非强制）。本地副本：`_research/sr2602a1.txt`
补充分析（律所，非一手）：<https://www.sullcrom.com/insights/memo/2026/April/OCC-Fed-FDIC-Issue-Revised-Guidance-Model-Risk-Management>

**对小型供应商的意外利好**：SR 26-2 收窄的"模型"定义 + 明示非强制，使它比 SR 11-7 **更适合**被自愿采纳为供应商框架——你可以声明"遵循 SR 26-2 原则"，而不必承担银行级合规义务。其中**供应商/第三方模型**段落（§VII）对 EA 供应商尤其对口。监管机构另将就 AI / 模型风险发布后续 RFI。

**SR 26-2 保留并细化的核心概念（仍是最佳实践词汇表）：**

- **Effective challenge（有效质疑）**：由具备相应专业能力、足够独立性、且拥有组织地位与影响力以推动改变的客观专家，在**模型全生命周期**（从开发到持续监控）进行批判性分析。
  > "Effective challenge is performed by individuals with the appropriate expertise to conduct a critical and objective challenge, sufficient independence to maintain objectivity, as well as the organizational standing and influence to effect any change."
- **Model inventory（模型清单）**：行业惯例，需包含足以理解模型风险的信息，以支持**个体层面与聚合层面**的管理。SR 26-2 措辞为 "common industry practice"（软性），不再是硬性要求。
- **Model validation（模型验证）**：评估模型是否按预期表现，包含**概念健全性（conceptual soundness）**与**结果分析（outcomes analysis）**两部分。结果分析将模型输出与真实世界结果对比，形式可包括开发期测试、持续监控报告、**回测（back-testing）**、异常值分析。
- **Ongoing monitoring（持续监控）**：评估模型在产品、敞口、活动、客户、数据相关性或市场条件变化下是否仍按预期表现；失效时触发 overlays / 调整 / 重建。
- **Model materiality = model purpose + model exposure**；**aggregate risk** 关注模型间依赖与共同假设。
- **Vendor / third-party models（第七章）**：供应商模型同样适用全部原则；因专有性可能拿不到底层代码/数据/方法论，但仍须验证其概念健全性、设计、开发数据与表现，并做持续监控与结果分析。

**🔴 监管趋同点（对销售多个 EA 的供应商最关键的一条治理要求）**

**SR 26-2 的 "aggregate risk"**（"interactions and dependencies among models; reliance on common assumptions, data, or methodologies"）与 **FCA 的表述**是**同一个概念**。FCA 在 *Algorithmic Trading Compliance in Wholesale Markets*（2018）中要求机构考虑：
> "the potential impact their algorithmic trading activity (including the **combined impact of multiple algorithmic strategies**)"

**→ 对销售多个共享数据源或信号逻辑的 EA 的供应商而言，这是整份报告中最相关的治理点**，应在任何 DDQ 回复中明确说明：**多个策略共用同一数据馈送/信号内核时，其风险不是各自风险之和**——共同假设失效会导致相关性在压力下趋近 1，这正是 aggregate risk 要捕捉的情形。
来源：<https://www.fca.org.uk/publication/multi-firm-reviews/algorithmic-trading-compliance-wholesale-markets.pdf>（PDF 正文 `[UNVERIFIED]`——FCA reCAPTCHA 墙返回 403；上述为搜索索引中已核实的原文片段）

**⚠️ 该发现已持续七年**：FCA 2018 年审查的首要发现即为——机构 *"who don't have clearly defined inventories in place and are only able to provide generic high-level descriptions for their [algorithms]"*；**2025 年 8 月的多机构审查又重新测试并再次发现同一缺口**。→ **"算法清单（algorithm inventory）"是持久的监管期望，不是 2025 年的一次性关注点。**

**（仅当英国客户询问如何映射其自身义务时相关）**：FCA 将**算法交易视为 SYSC 27.7.3R 下的 significant-harm function**，设计并操作算法的员工须**至少每年**认证为 fit and proper（英国认证制度）。**这约束客户，不约束供应商。**

### 1.2 英国：PRA SS1/23（五原则）

PRA 于 2023-05-17 发布 **SS1/23 – Model risk management principles for banks**（经 PS6/23），**2024-05-17 生效**；**2026-04-23 有更新版本**（经 LIAF01/26 低影响修订）。
来源：<https://www.bankofengland.co.uk/prudential-regulation/publication/2023/may/model-risk-management-principles-for-banks-ss>

**五大原则：**
1. **Model identification and model risk classification** — 确立"模型"定义、维护 **model inventory**、采用**基于风险的 tiering** 分类。
2. **Governance** — 董事会推动 MRM 文化、设定 **model risk appetite**、批准 MRM 政策、任命 **SMF** 负责框架。
3. **Model development, implementation and use** — 稳健开发流程与设计/实施/选择/绩效度量标准。
4. **Independent model validation** — 提供**持续、独立、有效质疑**；整改建议须被落实。
5. **Model risk mitigants** — 模型表现不佳时的缓解政策，含 **post-model adjustments (PMA)** 的独立复核。

**对小团队最有参考价值的具体条款：**

- **Principle 1.2(c) 模型清单应记录的字段**：模型目的与用途（含 intended vs actual use、operating boundaries）、假设与局限、验证发现（含未完成整改项）、治理细节（验证责任人、上次验证日期、未来验证频率）。本地副本 `research/pdf/ss123.txt` L385–413。
- **Principle 4.4 模型绩效监控必做四类测试**：(i) **benchmarking**（与可比替代估计比较）；(ii) **sensitivity testing**；(iii) **analysis of overrides**（模型调整的表现分析）；(iv) **parallel outcomes analysis**（判断新数据是否应纳入校准）。监控频率由 model tier 决定，报告须**独立复核**。
- **Principle 4.5 Periodic revalidation** — 定期独立重验证，频率与 model tier 一致。
- **Principle 2.6 第三方/供应商模型**：须确信供应商模型已按同等标准验证、核实供应商数据与假设的相关性、并**用自身结果做持续监控与结果分析**。
- **Principle 3.5 文档**：文档详细程度须足以让**独立第三方**理解并验证。
- 范围限定为持有内部模型许可（IM firms）的英国银行；PRA 明示会对其他机构另行更新。

### 1.3 欧盟：ECB TRIM 与《Guide to Internal Models》

**TRIM（Targeted Review of Internal Models）** 是 ECB 银行监管迄今最大项目：历时 4 年余，对 **65 家重要机构（SIs）执行 200 次现场内部模型调查（IMIs）**，覆盖信用风险、市场风险、交易对手信用风险。
来源：<https://www.bankingsupervision.europa.eu/ecb/pub/pdf/ssm.trim_project_report~aa49bb624c.en.pdf>

**关键量化结果：**
- 共提出 **超过 5,800 项 findings（缺陷）**；约 **30%** 的现场发现属于高严重度。
- **253 项监管决定**已发出或在发出中，其中 **74%** 含至少一项限制（limitation）。
- TRIM 限制与模型变更导致 TRIM 范围内模型所覆盖的 **RWA 聚合增加 12%**，绝对增幅约 **€275 billion**。

**方法论遗产**：《ECB guide to internal models》（2019 年 10 月首版，2024-02 更新）成为 TRIM 的核心交付物与长期参考文件；TRIM 建立了 **ITTs（investigation tools and techniques）**、三层质量保证流程（统一方法论 → 跨机构一致性检查 → 治理机构裁决分歧）与"centres of competence"横向专家机制。
注意：TRIM 已于 2019 年底结束现场工作，其要求通过常规监管流程延续。

### 1.4 现实可采纳性判定（1–3 人团队）

| 标准 | 是否适用 | 现实采纳建议 |
|---|---|---|
| SR 26-2 | **法律上不适用**（仅 >$300 亿银行；非强制） | **采纳其词汇与逻辑作为营销资产**：公开 model inventory、effective challenge 记录、outcomes analysis 报告。成本≈0，但对机构买家是强信号。 |
| PRA SS1/23 | 不适用（仅英国 IM firms） | **把 Principle 1.2(c) 的清单字段直接当作内部 model inventory 模板**——这是全文最可直接抄用的产物。 |
| ECB TRIM | 不适用 | 只借用一个教训：**没有独立验证与文档，模型缺陷率极高**（5,800 findings / 200 次调查）。 |

**结论**：这些银行标准的**合规义务**对小型供应商完全不适用，但**结构**极具价值。最小可行 MRM（minimum viable MRM）：
1. 一份 `model_inventory.csv`，字段照抄 SS1/23 Principle 1.2(c)；
2. 每个模型一份 validation memo（概念健全性 + 结果分析）；
3. 一份月度 outcomes analysis 报告（实盘 vs 回测，见 §4.3）；
4. **effective challenge 必须由非开发者执行**——1–3 人团队的现实做法是交叉验证 + 外部顾问年度复核，并**如实披露**该安排的局限。

---

## 2. 回测过拟合与策略验证标准（Backtest Overfitting / Strategy Validation）

### 2.1 Deflated Sharpe Ratio（DSR）— Bailey & López de Prado

DSR 同时修正两个业绩膨胀来源：**多重检验下的选择偏差（selection bias under multiple testing）**与**非正态收益**。
一手来源：<https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf>（*Journal of Portfolio Management*, 2014, 40(5), 94–107）

**Probabilistic Sharpe Ratio (PSR)** 先计算真实 SR 高于给定阈值的概率，考虑样本长度与收益分布的前四阶矩：

$$\widehat{PSR}(SR^*) = Z\left[\frac{(\hat{SR}-SR^*)\sqrt{T-1}}{\sqrt{1-\hat{\gamma}_3\hat{SR}+\frac{\hat{\gamma}_4-1}{4}\hat{SR}^2}}\right]$$

**DSR 是阈值被多重性调整后的 PSR：**

$$\widehat{DSR} = Z\left[\frac{(\hat{SR}-\hat{SR}_0)\sqrt{T-1}}{\sqrt{1-\hat{\gamma}_3\hat{SR}+\frac{\hat{\gamma}_4-1}{4}\hat{SR}^2}}\right]$$

其中阈值（期望最大 Sharpe，Extreme Value Theory 推导）：

$$\hat{SR}_0 = \sqrt{\mathbb{V}[\{\hat{SR}_n\}]}\left((1-\gamma)Z^{-1}\!\left[1-\frac{1}{N}\right] + \gamma\, Z^{-1}\!\left[1-\frac{1}{N}e^{-1}\right]\right)$$

- $\gamma \approx 0.5772156649$ = Euler–Mascheroni 常数
- $N$ = **独立**试验次数，$\mathbb{V}[\{\hat{SR}_n\}]$ = 各次试验 SR 估计的方差
- $T$ = 样本长度，$\hat{\gamma}_3$ = 偏度，$\hat{\gamma}_4$ = 峰度，$Z$ = 标准正态 CDF

论文附录给出的参考实现（本地 `research/pdf/deflated-sharpe.u8.txt` L578–583）：
```python
emc = 0.5772156649  # Euler-Mascheroni constant
maxZ = (1-emc)*ss.norm.ppf(1-1./numTrials) + emc*ss.norm.ppf(1-1./(numTrials*np.e))
expMaxSR = mu + sigma*maxZ
```

**独立试验数 N 的估计**（关键实践点）：若做了 M 次试验但仅 N 次独立，直接用 M 会**高估**阈值。论文用平均相关系数插值：
$$\hat{N} \approx \hat{\rho} + (1-\hat{\rho})\,M \quad\text{（Eq. 9）}$$
其中 $\hat{\rho}$ 为等权平均相关系数。论文警告：实践中 M 常超过样本长度 T，相关矩阵病态，须先用降维（如 PCA）处理。

**论文的数值例子（可直接用作验收标准）**：某策略 IS 年化 $\hat{SR}=2.5$，$T=1250$（5 年日频），$N$ 较大时 DSR 仅约 **0.90** → 在 95% 置信水平下**不构成合法经验发现**。若 $N=46$ 次独立试验，DSR 才达到 **0.9505**。若收益为正态，则 $N=88$ 时即可达 0.95。
来源同上，L406–445。

**停止测试的规则**：论文引用最优停止理论（secretary problem / 1/e-law）：从理论上可辩护的策略配置集合中**随机抽取约 37%（1/e）**测量表现，之后逐个抽取并测量，直到找到一个优于此前所有配置者即停止。

### 2.2 Probability of Backtest Overfitting（PBO）与 CSCV

一手来源：<https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf>（Bailey, Borwein, López de Prado, Zhu）

**PBO 定义**：IS 选出的最优配置在 OOS **跑输 N 个配置中位数**的概率。

**CSCV（Combinatorially Symmetric Cross-Validation）算法**：
1. 构造矩阵 $M$（$T \times N$）：N 个 trial 的损益序列，行同步。
2. 按行将 M 分成 **偶数 S** 个等长子矩阵 $M_s$（各 $T/S \times N$）。
3. 取 $S/2$ 个为一组，形成全部组合 $C_S$，组合数 $\binom{S}{S/2}$（S=16 → **12,780** 个组合）。
4. 对每个组合 $c$：训练集 $J$ = 选中的 $S/2$ 个子矩阵（$T/2 \times N$）；测试集 $\bar{J}$ = 补集。
5. 计算 IS 最优策略 $n^*$，其 OOS 相对排名 $\bar{\omega}_c = \bar{r}_{n^*}^c/(N+1)$，logit $\lambda_c = \ln\frac{\bar{\omega}_c}{1-\bar{\omega}_c}$。
6. $PBO = \varphi = \int_{-\infty}^{0} f(\lambda)d\lambda$（logit 分布的左尾比例）。

**判读标准（论文原文）**：$\varphi \approx 0$ = 无显著过拟合；$\varphi \approx 1$ = 过拟合可能性高。
> "In accordance with standard applications of the Neyman-Pearson framework, **a customary approach would be to reject models for which PBO is estimated to be greater than 0.05**."

**S 的选取约束**：logits 可取的不同值数须 > 10，故 **N ≫ 10**；S=16 给出 12,780 个 logits，$\sigma[f(\lambda)] < 0.0045$。
**重要警告**：PBO **不应**作为策略选择的目标函数；它评估的是**选择过程的质量**。

CSCV 的配套统计量：**Performance degradation**（IS 表现越高 OOS 越低 = 记忆效应）、**Probability of loss**（IS 最优 OOS 亏损概率）、**Stochastic dominance**（选择过程是否优于随机选一个）。

### 2.3 Minimum Backtest Length（MinBTL）

一手来源：<https://davidhbailey.com/dhbpapers/backtest-pseudo.pdf>（Bailey, Borwein, López de Prado, Zhu, "Pseudo-Mathematics and Financial Charlatanism"）

**期望最大 Sharpe（Proposition 2.1）**：
$$E[\max_N] \approx (1-\gamma)Z^{-1}\!\left(1-\frac{1}{N}\right) + \gamma Z^{-1}\!\left(1-\frac{1}{N}e^{-1}\right)$$

**MinBTL（Theorem 3.1，单位：年）**——在 N 次独立试验中，为避免选出 IS Sharpe = $E[\max_N]$ 但 OOS 期望为零的策略：
$$MinBTL \approx \left[\frac{(1-\gamma)Z^{-1}(1-\frac{1}{N})+\gamma Z^{-1}(1-\frac{1}{N}e^{-1})}{E[\max_N]}\right]^2 < \frac{2\ln[N]}{E[\max_N]^2}$$

**关键数字**：
- 若只有 **N=10** 次配置尝试，即使所有策略真实 SR 均为 0，也**期望**找到 IS Sharpe ≈ **1.57**。
- 若只有 **5 年**数据，则**不应尝试超过 45 个独立配置**，否则几乎必然产出 IS 年化 SR=1、OOS 期望为 0 的策略。
- **最有说服力的单一数字**：若测试 **100 个配置**并想信任一个 **Sharpe = 1.0** 的结果，需要约 **9.2 年**的回测数据——而**多数零售 EA 回测只有 1–3 年**。
- 上界近似：$\sqrt{2\ln N}$（IS Sharpe 的期望上界）。
- 实用上界近似：$MinBTL < \frac{2\ln[N]}{E[\max_N]^2}$
- **MinBTL 是必要非充分条件**：样本长于 MinBTL 仍可能过拟合。
- → **这是要求披露"测试过的配置数量 N"最有力的论据。**

### 2.4 多重检验：White Reality Check / Hansen SPA / Romano-Wolf / FDR

**White's Reality Check（2000, *Econometrica*）** — 检验 $H_0: \max_{k=1..\ell} E(f_k^*) \le 0$，即"没有任何模型对基准有预测优势"。
一手来源：<https://www.ssc.wisc.edu/~bhansen/718/White2000.pdf>
- 统计量 $V_\ell = \max_{k} \sqrt{n}\,\bar{f}_k$
- 由于 $\max$ 的分布解析不可得，使用 **stationary bootstrap（Politis & Romano）** 或 Monte Carlo Reality Check 求 p 值：
  $V_{\ell,i}^* = \max_k \sqrt{n}(\bar{f}_k^{*i} - \bar{f}_k)$
- 论文示例：naive p-value（只看最优模型）与 Reality Check p-value 的差距**直接度量 data snooping 的影响程度**。

**Hansen's SPA test（2005, *JBES*）** — 改进 Reality Check 的**保守性**（Reality Check 对差模型也计入，导致 p 值偏大、检验过度保守）。
- 采用 **studentized** 统计量与 **recentering**：仅对"good models"（$\hat\mu_k \ge -A_T$，$A_T = \hat\sigma_k\sqrt{2\log\log T}$）中心化，poor models 用下界截断。
- 产出三个 p 值：**lower**（乐观）、**consistent**（推荐）、**upper**（= Reality Check，保守）。

**Romano–Wolf stepwise（2005）** — 基于 bootstrap 的 **step-down / k-StepM** 逐步多重检验，控制 **FWER（family-wise error rate）**，比单步方法有更高功效（power）。实现参考：R 包 `NeuralSens::kStepMAlgorithm`。

**FDR 方法** — Harvey & Liu 将 **Benjamini–Hochberg** 框架用于策略选择，给出新策略 Sharpe 必须超越的阈值（"haircut Sharpe ratio"）。DSR 论文明确指出其 $\hat{SR}_0$ 阈值与 Harvey–Liu 阈值**互补**，并建议**两者都算**。

### 2.5 Purged K-Fold CV with Embargo（López de Prado）

一手来源（章节号已由图书馆 MARC 目录核实）：<https://librarycatalog.ecu.edu/catalog/5338858>
*Advances in Financial Machine Learning*（Wiley, 2018, ISBN 9781119482086）目录：
- **Ch. 6** Ensemble Methods
- **Ch. 7 Cross-Validation in Finance** ← purged K-fold + embargo
- **Ch. 8** Feature Importance
- **Ch. 9** Hyper-parameter Tuning with Cross-Validation
- **Ch. 11 The Dangers of Backtesting**
- **Ch. 12 Backtesting through Cross-Validation**
- **Ch. 13** Backtesting on Synthetic Data
- **Ch. 14** Backtest Statistics
- **Ch. 15 Understanding Strategy Risk**

**为什么标准 K-fold 在金融数据上失效**：标签重叠（overlapping labels）导致训练集与测试集信息泄漏；序列自相关使 IID 假设破裂。

**Purged K-fold**：在训练集中**剔除（purge）**任何标签区间与测试集标签区间重叠的观测。
**Embargo**：在测试集之后额外剔除一段 $h$ 的观测，处理测试集标签与紧随其后的训练观测之间的序列相关。
> 具体公式与 $h$ 的取值在 Ch. 7；本报告未能从一手来源核验其精确表达式，**`[UNVERIFIED]`**。

### 2.6 现实可采纳性判定（1–3 人团队）

| 技术 | 成本 | 建议 |
|---|---|---|
| **记录试验次数 N** | ≈0 | **必做，且是最高性价比项**。论文反复指出"不报告 N"是行业通病。维护一个 `trials.csv`。 |
| **MinBTL 检查** | 1 行代码 | **必做**。$MinBTL < 2\ln[N]/E[\max]^2$ 作为硬门禁。 |
| **DSR** | ~50 行 | **必做**。开源实现：`deflated-sharpe` (PyPI)、`jsharpe` (GitHub)。 |
| **PBO / CSCV** | ~150 行 | **强烈建议**。R 包 `pbo` 或自行实现；拒绝 PBO > 0.05 的候选。 |
| **Purged K-Fold + Embargo** | ~100 行 | **建议**（尤其对重叠标签的 ML 策略）。 |
| **Hansen SPA / Romano-Wolf** | 高 | **可选**。若策略池较大，用 SPA consistent p-value 做最终把关；否则 DSR 已覆盖大部分风险。 |

**结论**：DSR + PBO + MinBTL 三件套是**商业信号产品可信度的最低门槛**，总实现成本约 1–2 人周，且**可直接写进营销材料**（"我们公布 PBO 与 DSR"在零售市场是显著差异化）。不报告试验次数 N 是论文点名的行业失格行为。

---

## 3. 销售信号 / 自动交易软件的监管与牌照现实

### 3.1 美国：CFTC / NFA

**CTA 注册与"出版物豁免"**
- CEA **§1a(12)(B)(iv)** 的法定排除仅覆盖 **"the publisher or producer of any print or electronic data of general and regular dissemination, including its employees"**，且须满足 **(C)** 的"**solely incidental**（纯属附带）"条件。
  ⚠️ **注意**：常被引用的"newspaper, news column, newsletter… does not consist of the rendering of advice on the basis of the specific investment situation of each client"措辞**不在 CEA §1a(12) 中**——那是 **Investment Advisers Act of 1940 §202(a)(11)(D)**（*Lowe v. SEC* 出版物排除）。**不要把该措辞当作 CEA 条文引用。**
  来源：<https://www.law.cornell.edu/uscode/text/7/1a>
- **CFTC Rule 4.14(a)(9)**（eCFR）：豁免对象为"**CTAs whose business is limited to distributing standardized commodity trading advice**"（通过 newsletter、预录电话热线、网站、**非定制计算机软件**等媒介）。
  - **(a)(9)(i)**：**may not direct client accounts**。
  - **(a)(9)(ii)**：不得提供 **"commodity trading advice based on, or tailored to, the commodity interest or cash market positions or other circumstances or characteristics of particular clients."** —— 一旦建议基于或针对特定客户情况，**即使对同类客户群给出相同建议也须注册**。
  来源：<https://www.ecfr.gov/current/title-17/chapter-I/part-4/section-4.14>

**⚠️ 最关键的分界线——"非正式安排（informal arrangement）"**
CFTC Staff Letter **03-26**（2003-05-30）：客户与交易系统开发者的接触**不仅包括交易程序，还包括开立一个按"letter of direction"交易的账户**，即构成"informal arrangement"，**4.14(a)(9) 豁免不适用**。
> "In adopting Rule 4.14(a)(9), the Commission noted it intended 'that a CTA who manages a client's trading under some type of **informal arrangement** be required to register even if the CTA is not authorized to effect transactions without the client's specific authorization.'"
来源：<https://www.cftc.gov/sites/default/files/idc/groups/public/@lrlettergeneral/documents/letter/03-26.pdf>

**实务判据**：纯软件销售 + **无**开户捆绑 / **无**自动执行授权 / **无**"跟随信号"委托 / **无**个性化定制 → 可用 (a)(9)。一旦软件与**开户、自动交易授权或"follow the signals"委托**捆绑 → **必须注册**。

**NFA Interpretive Notice 9055（第三方交易系统开发者）——对 EA 供应商最直接对口的文件**
- IN 9055 明确警告："NFA has encountered, with increasing frequency… **misleading promotional material promoting trading systems developed by third-party system developers, who are not NFA Members**… Often this promotional material uses **hypothetical or simulated results — which are trading results not achieved by an actual account — that are not clearly identified as hypothetical and show impressive gains, when customers actually using the trading system have suffered substantial losses.**"
- **NFA Bylaw 1101** 禁止会员与"须注册而未注册"的非会员进行客户业务。IN 9055 要求会员向第三方系统开发者索取 **counsel letter** 说明为何无需注册；否则须要求其注册，或**终止关系**。
- **间接约束**：Rule 2-36(g) 使 FDM 受 Rule 2-29(a)–(h) 约束，因此 NFA 会员（执行券商）可因供应商的误导性推广材料被追责。

**⚠️ 2026 年新动态：CFTC Staff Letter 26-25（2026-09-17，"Passive Software Providers"）**
- 对被动软件供应商给予 **IB 注册**的 no-action 救济，且 **26-25 使其普遍适用于所有 PSP**（前身 26-09 仅限 Phantom Technologies 一家可依赖）。
- **但明确排除生成"express 'buy' or 'sell' signals"的平台** → **MT5 EA 或信号服务无法依赖该函**；且该函**完全不涉及 CTA 注册**。
来源：<https://www.cftc.gov/csl/26-25/download>

**NFA Rule 2-29（广告与推广材料）—— ⚠️ 2025-07-21 修订，多数二手资料已过时**

修订历史原文："[Adopted effective November 19, 1985. Effective date of Amendments: … January 1, 2020 April 22, 2020 and **July 21, 2025**.]"
来源：<https://www.nfa.futures.org/rulebooksql/rules.aspx?Section=4>

**🔴 对回测营销的 EA 供应商而言，这是最大的现实风险——2-29(c)(4) 三个月禁令：**
> "No FCM, IB, CPO or CTA Member or Associate may use promotional material which includes a measurement or description of or makes any reference to hypothetical performance results which could have been achieved had a particular trading system… been employed in the past **if the FCM, IB, CPO or CTA Member or Associate has three months of actual trading results for that system**."

**即：系统一旦有 3 个月实盘业绩，就不得再用回测/假设业绩做营销。** 这对以回测为卖点的商业模式是直接的商业模式约束——**必须规划"回测营销 → 实盘业绩"的切换点**。

**2-29 其他硬性要求（原文要点）：**
| 条款 | 要求 |
|---|---|
| **(b)(3)** | **提及盈利可能性的，必须伴随同等醒目的亏损风险讨论**（equally prominent discussion of the risk of loss） |
| **(b)(4)** | 引用**实际历史盈利**必须说明"过往业绩不必然预示未来结果" |
| **(b)(5)** | 任何**具体数值或统计**的历史业绩：须能向 NFA 证明其**代表所有合理可比账户**同期表现；须**扣除全部佣金、费用与开支**；收益率须按 CFTC Reg 4.25 / 4.35 计算 |
| **(b)(6)** | 证言须代表所有合理可比账户，须醒目声明"不代表未来表现或成功"，付费证言须披露 |
| **(c)(3)** | 使用假设业绩须**同时提供**：过去**至少五年**（不足五年则全部历史）由该会员以 power of attorney 管理的**所有客户账户**的实际业绩；若经验不足一年，须提供其**自营交易**过去五年实际业绩 |
| **(c)(6)** | (c)(3) 与 (c)(4) 限制**不适用于**仅面向 **QEP**（CFTC Reg 4.7 标准）的材料 |
| **(d)** | 意见陈述须明确标识且**有合理事实依据** |
| **(e)** | 所有推广材料**首次使用前**须由**非制作人**的另一名主管书面审核批准 |
| **(f)** | 保留推广材料及审批记录与业绩支撑材料，按 **CFTC Reg 1.31**：**自最后使用日起不少于 5 年**，其中**前 2 年须可随时调取**；须能**应 NFA 要求证明任何所报业绩的依据** |
| **(h)** | **音视频**推广材料若作出具体交易建议或提及/描述盈利，须**首次使用前至少 10 天**提交 NFA 推广材料审查组批准 |
| **(i)(2)** | "commodity interest account, agreement or transaction" **明确包含"通过出版物或其他方式销售非个性化交易建议"** → **这是捕获信号/EA 供应商的条款** |

**免责声明全文（必须逐字使用）**

**路径选择很关键**：
- **CFTC 17 CFR §4.41(b)(1)(i)** 给出 CFTC 版声明；**(b)(1)(ii)** 允许 NFA 会员改用 NFA 规定声明。
- ⚠️ **若供应商不是 NFA 会员（多数软件供应商如此），则必须逐字使用 CFTC 文本。**
- ⚠️ **4.41(c)(2) 是关键陷阱**：该广告规则 **"regardless of whether the commodity pool operator or commodity trading advisor is exempt from registration under the Act."** —— **注册豁免 ≠ 广告规则豁免。**
- **(b)(2)**：非口头呈现时，声明须**醒目且紧邻**所呈现的假设业绩。

CFTC 版全文（<https://www.law.cornell.edu/cfr/text/17/4.41>）：
> "These results are based on simulated or hypothetical performance results that have certain inherent limitations. Unlike the results shown in an actual performance record, these results do not represent actual trading. Also, because these trades have not actually been executed, these results may have under-or over-compensated for the impact, if any, of certain market factors, such as lack of liquidity. Simulated or hypothetical trading programs in general are also subject to the fact that they are designed with the benefit of hindsight. No representation is being made that any account will or is likely to achieve profits or losses similar to these being shown."

NFA 版（Rule 2-29(c)(1)，适用于 NFA 会员）起始为：
> "HYPOTHETICAL PERFORMANCE RESULTS HAVE MANY INHERENT LIMITATIONS, SOME OF WHICH ARE DESCRIBED BELOW. NO REPRESENTATION IS BEING MADE THAT ANY ACCOUNT WILL OR IS LIKELY TO ACHIEVE PROFITS OR LOSSES SIMILAR TO THOSE SHOWN. IN FACT, THERE ARE FREQUENTLY SHARP DIFFERENCES BETWEEN HYPOTHETICAL PERFORMANCE RESULTS AND THE ACTUAL RESULTS SUBSEQUENTLY ACHIEVED BY ANY PARTICULAR TRADING PROGRAM…"

**展示格式要求（NFA 推广材料指南）**：声明必须**与假设业绩同等醒目**——"the disclaimer be printed in a **type size at least as large as** that used for the hypothetical results"；须**紧邻**（若实际业绩少于 12 个月，须**置于假设业绩之前**）；材料须**同时披露实际业绩**且醒目程度**不低于**假设业绩；不得**淡化**实际业绩；须披露**所有相关成本（佣金与费用）**；业绩须**完整**、不得有缺口或**挑拣时段（cherry-pick）**。

**关于"guaranteed / risk-free / safe / secure"等禁用词**：**Rule 2-29 中并无列举式禁用词清单（`[UNVERIFIED]` as a rule-text claim）**。但通过以下条款产生等效禁止：
- **2-29(b)(1)–(2)**（likely to deceive / material misstatement / misleading omission）——操作性依据；
- **NFA Rule 2-4**（"high standards of commercial honor and just and equitable principles of trade"）；
- **NFA 推广材料指南（2025-12）**："Using the term **'limited risk'** to imply that the likelihood of loss is limited is **highly misleading**."；外汇部分明确禁止声称可"**guarantee against any customer losses**"、**"no-slippage"**、保证成交价、暗示客户资金"**more secure**"、暗示"**direct access to the interbank market**"；并禁止在**不**以同等醒目方式紧随说明"**increasing leverage increases risk**"的情况下以杠杆招揽客户。

**执法先例（对 EA 供应商直接对口）**
**CFTC v. Fintech Investment Group, Inc., Alan Friedland, and Compcoin LLC**（M.D. Fla. 6:20-cv-00652；同意令 2022-03-07）
- 案由：**7 U.S.C. §6o(1)(A) 和 (B) —— Fraud by a Commodity Trading Advisor**
- 核心不实陈述（原文）："**fail[ed] to include the required disclosure that Fintech and ART's forex trading performance results were largely or entirely based on simulated or hypothetical performance and not actual trading results as required by the relevant Regulation.**"
- 另因未取得 NFA 对其风险披露文件的批准而违反 **CFTC Regulation 4.36**。
- **判决：连带返还 $1,200,000**，NFA 被指定为 Monitor。
来源：<https://www.cftc.gov/media/7126/enfintechconsentorder030722/download>

**⚠️ 已澄清的三项常见误解（原任务描述中的前提有误）**
1. **不存在"2-36(d) 假设业绩记录"要求**。现行 **2-36(d) 是 "Doing Business with Non-Members"**；外汇假设业绩由 **2-36(h)（现行文本为 "Reserved"）**指向 **Rule 2-29(c)** 处理。**NFA 规则中不存在"每月假设交易记录"，也不存在 5 年假设业绩回溯**——唯一的 5 年要求是 **2-29(c)(3) 的实际业绩**回溯。
2. **2019-08-29 那份文件不是"CFTC/NFA 联合解释性通知"**，而是 **NFA 依 CEA §17(j) 向 CFTC 秘书处提交的规则修订送审函**（含增删标记的 redline）。其中**并未引入任何规定性免责声明**——强制声明规定在 Rule 2-29(c)(1)/(c)(2)（NFA 版）与 Rule 4.41(b)（CFTC 版）。
3. **不存在**名为"Fictitious or hypothetical performance"或"Trading Systems"的 2019 年单独解释性通知；相关内容已整合进 **IN 9025**（假设业绩）与 **IN 9055**（交易系统）。

**4.14(a)(10) 的"15 人"豁免对零售供应商无效**：需同时满足 **12 个月内客户 ≤15 人** *且* **不对外公开自称 CTA（no general holding out）**——**零售供应商必然违反第二项**。

**`[UNVERIFIED]`（美国）**：未找到任何直接点名 **MT5 EA 供应商**的 CFTC/NFA 执法案例（*Fintech/ART*、*Tradewale*、*SimTradePro* 为最接近的类比案例）。

### 3.2 欧盟：MiFID II / ESMA

**是否需要牌照**
- MiFID II **Annex I Section A(4) portfolio management** 与 **Section A(5) investment advice** 是需授权的投资服务。
- **销售软件本身**不构成投资服务；但**提供个性化投资建议**（针对客户具体情况推荐交易）触发 A(5)，**代客管理组合**触发 A(4)。
- ESMA 对 CFD 的立场（见下）确认："CFDs are complex financial products and therefore are subject to the **appropriateness test** pursuant to Article 25(3) of Directive 2014/65/EU" —— 即**执行-only（execution-only）**路径是被承认的，前提是不提供建议。
- 来源：<https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32018X0601(02)>

**ESMA 产品干预措施（CFD）— 现行杠杆上限**
一手来源（ESMA 官方 FAQ，已核验原文）：<https://www.esma.europa.eu/sites/default/files/library/faq_esmas_product_intervention_measures_de.pdf>
| 标的 | 最大杠杆 |
|---|---|
| **主要货币对（major currency pairs）** | **30:1** |
| 其他货币对、**黄金**、重要股指 | **20:1** |
| 除黄金外的商品、其他股指 | **10:1** |
| 个股及其他未列明标的 | **5:1** |
| 加密货币 | **2:1** |

其他强制措施（同一来源，逐项核验）：
- **Margin close-out rule（MCO）**：触发阈值统一设为 **50%**，且**按账户（per ACCOUNT）**计算——即账户**总**保证金跌破未平仓 CFD 所需**总**保证金的 50% 时须平仓，**不是按单个仓位**。原文："Die MCO-Schwelle wurde auf **50 %** festgesetzt"。MCO 规则**不**规定平哪些仓位、也不规定时限（保留既有市场惯例），**唯一的新增统一要求是 50% 阈值**。
- **Negative balance protection（按单一账户）**：负余额保护；
- **禁止构成交易激励的优惠（incentives/bonuses）**——非货币性的信息与研究工具除外；
- **标准化风险警告（standardised risk warning）**。
- **二元期权（binary options）对零售客户全面禁止**。
- 设计原理（原文脚注）：杠杆上限的设定使零售客户无论标的为何，风险可比——**标的历史波动越低，允许杠杆越高**；黄金因波动低于其他商品而适用 20:1 而非 10:1。
- 注：**ESMA 的原始干预决定（EU）2018/796 已由各成员国 NCA 的永久国内措施取代**——ESMA 2026 年 2 月声明确认"all NCAs adopted permanent national product intervention measures mostly mirroring the mentioned ESMA decision"。
- **2026 年 ESMA 最新动作（两则公开声明）**：
  1. **永续合约（perpetual futures）**：ESMA 提醒机构在永续合约产品增多的情况下仍须遵守 CFD 产品干预义务（ESMA35-243228190-8024 相关）。
  2. **事件合约 / 预测市场（event contracts / prediction markets）**：ESMA 确认**二元期权产品干预措施适用于事件合约**（ESMA35-243228190-8148，2026 年 7 月）。
  来源：<https://www.esma.europa.eu/press-news/esma-news>；分析：<https://www.fintechanddigitalassets.com/2026/07/prediction-markets-esma-confirms-application-of-binary-options-product-intervention-measures-to-event-contracts/>

**MiFID II RTS 6 — Commission Delegated Regulation (EU) 2017/589**（算法交易组织要求）
一手来源全文：<https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32017R0589>

| 条款 | 要求 |
|---|---|
| **Art. 1** | 清晰的治理安排、问责线、**交易台与风控/合规职能分离** |
| **Art. 2** | 合规人员须理解算法如何运作；**须随时能联系到掌握 kill functionality 的人员** |
| **Art. 5** | 部署/重大更新前须有明确方法学；**由高管指定人员授权部署**；记录变更时间/实施人/批准人/变更性质 |
| **Art. 6** | **Conformance testing**（与交易场所系统的一致性测试） |
| **Art. 7** | **测试环境须与生产环境分离**（可用自有、交易所、DEA 提供商或供应商提供的环境） |
| **Art. 8** | **受控部署**：预设金融工具数量、订单价格/价值/数量、策略持仓、交易场所数量上限 |
| **Art. 9** | **年度自评估（annual self-assessment）与验证报告**，覆盖算法/策略、治理与问责、业务连续性、Article 17 整体合规，并含 Annex I 标准分析；由**风险管理职能**起草，**内部审计**审计（若有），**高管批准**；缺陷必须整改 |
| **Art. 10** | **压力测试**：过去 6 个月最高消息量 **×2**、最高交易量 **×2** |
| **Art. 11** | **重大变更管理**：生产环境重大变更须经高管指定人员审查，深度与变更幅度相称；功能变更须通知交易员、合规与风险管理 |
| **Art. 12** | **Kill functionality**：须能**立即取消**发往任一/全部交易场所的**任何或全部未执行订单**；须能识别每个订单由哪个算法、哪个交易员/交易台/客户负责 |
| **Art. 13** | 自动化的**市场操纵监控系统**；至少每年复核一次；须能以足够时间粒度回放订单与交易数据；**次日开盘前**产生可操作告警 |
| **Art. 14** | **业务连续性安排**，须**每年复核与测试**；含 kill functionality 使用政策、算法关停安排、未结订单与持仓的替代处理 |
| **Art. 15** | **Pre-trade controls**：(a) **price collars**（自动阻止/取消不符合价格参数的订单，按工具区分，逐单及跨时段）；(b) **maximum order values**；(c) **maximum order volumes**；(d) **maximum messages limits**。第 2 款：所有已发订单**立即**计入限额计算。第 3 款：**repeated automated execution throttles**——策略重复执行预定次数后**自动禁用**，须指定人员重新启用。第 4 款：基于资本基础/清算安排/策略/风险容忍度的市场与信用风险限额。第 5 款：无权限交易员的订单自动阻止；风险阈值订单自动阻止 |
| **Art. 16** | **Real-time monitoring**：实时告警须在事件发生后 **5 秒内**产生 |
| **Art. 17** | **Post-trade controls** 持续运行；触发时须采取行动（调整/关停算法或有序撤出市场） |

**FCA 2025 年多机构算法交易控制审查**（2025-08-21 发布）
来源：<https://www.fca.org.uk/publications/multi-firm-reviews/algorithmic-trading-controls-high-level-observations>（本地副本 `_research/fca_algo.txt`）
识别出 **5 个重点领域**：
1. **Defining algorithmic trading** — 建立识别算法交易的流程、管理"重大变更"、维护**完整的算法交易清单（inventory）**。
2. **Development & testing** — 稳健、一致、被充分理解的开发与测试流程。
3. **Risk controls** — 稳健的 pre/post-trade 控制。
4. **Governance & oversight** — 展现来自高管、风险管理与合规的**有效质疑（effective challenge）**。
5. **Market integrity / 技能与资源**。

> **FCA 对每家机构的第一项索取文件就是 RTS 6 的年度自评估与验证报告**——许多系统性机构从未产出过该报告。这是小团队可以低成本做到、却能让大型同行难堪的合规项。

**ESMA 2026 算法交易监管简报（最新 EU 监管立场）**
ESMA 于 **2026-02-26** 发布 *Supervisory Briefing on Algorithmic Trading in the EU*（ESMA74-1505669079-10311），非约束性（无 comply-or-explain），针对监管实践中出现分歧的领域：**治理、测试、外包，以及"算法交易/算法"关键概念的解释**。
来源：<https://www.esma.europa.eu/press-news/esma-news/esma-issues-supervisory-briefing-algorithmic-trading>
PDF：<https://www.esma.europa.eu/sites/default/files/2026-02/ESMA74-1505669079-10311_Supervisory_Briefing_on_Algorithmic_Trading_in_the_EU.pdf>

对小团队最相关的要点：
- **年度自评估须"逐条（article-by-article）"进行**，覆盖 RTS 6 所有相关条款，并**逐条声明是否合规**；须由**风险管理职能**主导，适用时经**内部审计**复核。
- **外包不转移责任**：RTS 6 Art. 4 规定外包或采购软硬件时，投资公司**仍承担全部责任**；ESMA 明确"IFs should **not fully rely** on the party to whom the trading activity has been outsourced"。外包风险管理职能时，若无法自行设置/校准/测试 pre-trade controls，即**不符合监管预期**。
- **须能审查外包算法的运作与表现**，包括查阅数据、测试文档与记录。
- **Pre-trade controls（PTC）**：须有风险导向的自评估，并在年度自评估中**给出理由（justification）**；即使单个子订单满足数量/价值限额，整体仍可能违规。
- **AI 与算法交易**：AI Act（Regulation (EU) 2024/1689）定义 AI 系统；**AI 驱动的算法交易目前不属于 AI Act 的高风险用例**，但高风险清单**每年复核**。ESMA 建议机构在 **RTS 6 Art. 9 年度自评估**中说明 AI 的使用及其对算法决策的影响。ESMA 特别点名 **reinforcement learning、deep learning、neural networks、GenAI** 生成的交易信号风险。
- **再测试触发条件**：包括**改变阈值、kill switch 逻辑或告警触发器**——即 kill switch 逻辑变更属于必须重新测试的变更。
- **Art. 16(5) MiFID II** 关于外包的规定；kill functionality 与撤单/撤出市场并列作为 PTC 触发后的处置手段。

### 3.3 英国：FCA COBS 4（金融推广）

**已核验条款（FCA Handbook, COBS 4, Release 32, Dec 2023；本地一手副本 `sources/cobs4.utf8.txt`）**

**COBS 4.2.1R — 一般规则**：金融推广须**公平、清晰、不误导（fair, clear and not misleading）**。
**COBS 4.5** — Communicating with retail clients（含 COBS 4.5.2R 一般规则）。

**COBS 4.6 — "Past, simulated past and future performance"** —— **这一节才是业绩声明的核心，不是 4.5**。

**COBS 4.6.2R（Past performance / 过往业绩）** —— 六项条件，全部强制：
> (1) **that indication is not the most prominent feature of the communication**；
> (2) the information includes appropriate performance information which covers **the preceding five years**, or the whole period for which the investment has been offered… and in every case that performance information must be **based on complete 12-month periods**；
> (3) the reference period and the source of information are clearly stated；
> (4) the information contains a **prominent warning that the figures refer to the past and that past performance is not a reliable indicator of future results**；
> (5) 非英镑计价须说明币种并警告汇率波动；
> (6) **if the indication is based on gross performance, the effect of commissions, fees or other charges is disclosed**。

**🔴 COBS 4.6.6R（Simulated past performance / 模拟过往业绩）—— 对回测营销直接适用**：
> A firm must ensure that information that contains an indication of **simulated past performance**… satisfies the following conditions:
> (1) it relates to an investment or a financial index；
> (2) **the simulated past performance is based on the actual past performance of one or more investments or financial indices which are the same as, substantially the same as, or underlie, the investment concerned**；
> (3) in respect of the actual past performance referred to in (2), the conditions in **COBS 4.6.2R(1)–(3), (5) and (6)** are complied with；
> (4) the information contains a **prominent warning that the figures refer to simulated past performance and that past performance is not a reliable indicator of future performance**。

→ **实务含义**：回测（backtest）在 FCA 框架下即 "simulated past performance"。**回测必须基于真实历史数据**（不能是合成数据），且必须附**醒目警告**。

**COBS 4.6.7R（Future performance / 未来表现）** —— 五项条件：
> (a) **it is not based on and does not refer to simulated past performance**；
> (b) it is based on **reasonable assumptions supported by objective data**；
> (c) 若基于 gross performance，须披露佣金/费用/其他收费的影响；
> (ca) **it is based on performance scenarios in different market conditions (both negative and positive scenarios)**；
> (d) it contains a **prominent warning that such forecasts are not a reliable indicator of future performance**。

→ **实务含义**：**不得用回测推导未来收益预测**（(a) 明确禁止）；任何预测必须给出**正负两种情景**。

**COBS 4.6.4A G** —— 若采用表格展示过往业绩：须展示**五个（不足五年则全部）完整 12 个月期间**，不足的期间须**明确标注"无数据"**；pgr = ((P1−P0)/P0)×100，四舍五入至 0.1%。

**MiFID 侧对应条款（COBS 4.5A，境内化 MiFID Org Reg art. 44）**：
- **COBS 4.5A.10UK** — past performance
- **COBS 4.5A.12UK** — simulated past performance
- **COBS 4.5A.14UK** — future performance
- **COBS 4.5A.16UK**（art. 44(8)）— 不得暗示主管机关认可（见下）

**英国 CFD 杠杆阶梯（COBS 22）—— ⚠️ 与 ESMA 不同**
**COBS 22.5.11R** 的英国阶梯为 **30 / 20 / 10 / 5**，**没有 2:1 加密资产档**——因为加密资产衍生品在英国依 **COBS 22.6** 已被**禁止**向零售客户销售。此外**英国政府债券为 30:1**（而 ESMA 归入 5:1 档）。
- 平仓规则 **COBS 22.5.13R**；负余额保护 **COBS 22.5.17R**；激励禁令 **COBS 22.5.20R**。
- **风险警告中的亏损比例不是固定"70%"**：**COBS 22.5.6R(1A)** 要求使用**该机构自身**的百分比，按**过去 12 个月、每 3 个月重算**。

**其他相关**：FCA **Consumer Duty**（PRIN 2A，2023-07-31 起对新产品与现有产品适用）要求为零售客户交付"good outcomes"。若机构唯一的 Principle 12 活动是**传达/批准金融推广**，则 **PRIN 2A.1.15AG** 规定 PRIN 2A.3 / 2A.4 / 2A.6 / 2A.11 仅具"limited relevance"，**PRIN 2A.5（consumer understanding）**成为主要抓手；**PRIN 2A.4.8R(3)** 涵盖订阅/周期性收费的价格与价值评估。

**🔴 英国"perimeter"（受监管活动边界）——对信号/EA 供应商最关键的两点**

1. **PERG 8.30.5G（决定性）**：生成 **"specific buy, sell or hold signals relating to particular investments"** 的软件 **"liable, as a general rule, to be advice for the purposes of article 53(1) (as well as financial promotions)"**。
   → **在英国，一个产生具体买卖信号的系统，原则上即构成"投资建议"**，需要 FCA 授权。仅当存在**真正的用户控制例外（genuine user-control exception）**时才可能豁免。
2. **FCA 跟单交易（copy trading）页面（2026-07-27 更新）**：**"We classify copy trading as portfolio or investment management where no manual input is clear from the account holder."**，且 **"Where the client sets trading parameters … this will not affect the characterisation of the service as portfolio management."**
   → **任何无人工介入的自动执行 = 投资组合管理 = 需授权。**客户自行设定参数**不**改变定性。
3. **PERG 8.4.24G**：交易工具（trading tools）**"in many cases … too remote from any eventual investment dealing activities to be inducements"**——**但**若以"**almost certain to produce profits**"方式销售，推广本身即成为**诱因（inducement）**，构成金融推广。
4. **FG24/1 ¶2.8**：**Discord / Telegram 信号群属于金融推广**。未经授权的传达在 **FSMA 2000 s.21(1)** 下构成**刑事犯罪**，最高 **2 年**监禁。

**关于"卖软件是否构成受监管活动"（英国）**：受监管活动由 **FSMA 2000 (Regulated Activities) Order 2001 (RAO)** 界定。
- "投资建议" = **RAO Article 53(1)（advising on investments）**；"管理投资" = **RAO Article 37（managing investments）**。
- ⚠️ **RAO art. 53(2)/(3) 不是新闻业豁免**（那覆盖 P2P 借贷与债务活动）。真正的排除是 **RAO Article 54（"Advice given in newspapers etc."）**；推广侧的对应排除是 **FPO 2005 art. 20**（**FPO 2001 已于 2005 年被撤销**）。
- ⚠️ "**by way of business**" 要件**不在 RAO art. 3**，而在单独的法令 **SI 2001/1177**。
- **Gateway（审批人制度）**：相关法令为 **SI 2023/1411 + SI 2023/966**；法律依据为 **FSMA ss.55NA/55NB**（由 FSMA 2023 s.20(3) 插入），**2024-02-07 生效**。**COBS 4.10.1BG**；审批人须取得**季度书面证明（quarterly written attestations）**（**COBS 4.10.2R(1B)**）。
- **COBS 4.5A.16UK（MiFID Org Reg art. 44(8)）**：**不得**使用主管机关名称暗示获得认可 → **任何"FCA-approved"营销说法均被禁止**。
- 未找到关于"软件供应商是否构成 arranging/advising"的判例法 → **`[UNVERIFIED]`**。
- 未找到 FCA 关于 prop firm 的专门声明 → **`[UNVERIFIED]`**（负面证据：e-petition 754761 于 2026-07-26 关闭，仅 24 个签名，未达 10,000 门槛，故不存在政府/FCA 回应）。

来源：<https://www.handbook.fca.org.uk/handbook/COBS/4/>、<https://www.handbook.fca.org.uk/handbook/PERG/8/>、<https://www.legislation.gov.uk/uksi/2001/544/contents>（本地副本 `sources/cobs4.utf8.txt`、`sources/fpo2001_whole.xml`、`docs/compliance/research-2026/uk-regulatory-findings-2026.md`）

**⚠️ 时效性caveat**：本地 FCA Handbook 最新真实抓取为 **COBS 4 = 2023 年 12 月**、**COBS 22 = 2024 年 10 月**、**PRIN 2A = 2024 年 2 月**。**条款编号稳定，但措辞未经核验是否截至 2026 年 9 月未被修订。**

> ⚠️ 原任务描述把 COBS 4.5 当作业绩声明规则；**实际业绩声明规则在 COBS 4.6**（4.5 是"与零售客户沟通"的一般规则）。已按 FCA Handbook 原文更正。另：**COBS 4 中不存在禁止"guaranteed"类表述的规则**——该指引位于 **COBS 4.2.5G**（指引而非规则）。

### 3.4 现实底线：无牌照能做什么 / 不能做什么

**跨辖区对照表（本报告最核心的决策工具）**

| 行为 | 美国 | 欧盟 | 英国 |
|---|---|---|---|
| 销售**由客户自行配置与运行**的 EA | ✅ 可以 | ✅ 可以 | ✅ 可以 |
| 发布**通用公开**信号 | ✅ 可以（4.14(a)(9)/(10)，须无定制、无公开自称 CTA） | ✅ 可以（Del. Reg. 2017/565 **Art 9**） | ❌ **不可以** —— **PERG 8.30.5G** 将具体信号视为建议 |
| **个性化**"这个适合你"式信号 | ❌ CTA 注册 | ❌ Annex I A(5) | ❌ RAO art. 53 |
| 在客户账户上**自动执行** | ❌ | ❌ Annex I A(4) | ❌ 投资组合管理 |
| 展示回测**而无免责声明** | ❌ 4.41(b) | ❌ 各国 CFD 规则 | ❌ COBS 4.6.6R |
| 系统已有 **3 个月实盘业绩**后仍展示回测 | ❌ **NFA 2-29(c)(4)** | ⚠️ 允许（须警告） | ⚠️ 允许（须警告） |
| 声称"**保证**""**无风险**""**安全**" | ❌ 2-29(b)(1)–(3)、Rule 2-4 | ❌ | ❌ COBS 4.2.1R / 4.2.5G |
| 声称"**FCA/ESMA 认可**" | — | ❌ | ❌ **COBS 4.5A.16UK** |
| 通过 **Discord / Telegram** 推广 | 受 2-29 约束 | 受约束 | ❌ **未经批准即刑事犯罪**（FSMA s.21(1)） |

**🔴 四个能直接击穿商业模式的点**：
1. **NFA 2-29(c)(4)**——EA 有 3 个月实盘业绩后，**在美国用回测营销即违法**（最尖锐、最近期的风险）。
2. **英国 PERG 8.30.5G**——触发授权的是**信号业务**，不是软件业务。在美国合法的通用信号产品，在英国可能直接构成"投资建议"。
3. **任何无人工介入的自动执行**，在欧盟与英国**均构成投资组合管理**，需授权。
4. **欧盟/英国推广 CFD** 未经批准即**刑事/未授权**，且 **Discord/Telegram 计入**。

**关键法律判据（欧盟）**：MiFID II **Art 4(1)(4)** 定义建议为"**personal recommendations** to a client… in respect of one or more transactions"；**Del. Reg. 2017/565 Art 9** 结尾明确：**"A recommendation shall not be considered a personal recommendation if it is issued exclusively to the public."** → **面向公众的通用信号落在"建议"之外；个性化信号则不然。**
ESMA35-36-794 Q3/A3(1)(d) 明确将"第三方介绍经纪同时**充当信号提供者**"列为**不可接受且需授权**的安排。

**ESMA 2026 简报对"信号"的界定（重要）**：
- **¶9**：仅"**serve to inform a trader** of a particular investment opportunity"的算法**不属于**算法交易——**前提是执行不是算法化的**。
- **¶11**：**"Signal-based trading**、quantitative models、machine learning-driven strategies"**属于**算法交易（当其影响订单参数时）。
- **¶36–37**：**"regulatory accountability cannot be transferred."**
- **RTS 6 从未被修订**（仅有合并版本 02017R0589-20170331）；MiFIR review **Reg. 2024/791 未触及 Art 17**。
- **RTS 6 Art 5(6)**：第 2–5 款**仅适用于"trading algorithms leading to order execution"**。
- **Art 17 MiFID II 适用与公司规模无关**；Art 1(5) 将 Art 17(1)–(6) 扩展至非授权 RM/MTF 成员。
- **DORA** 自 2025-01-17 适用；**Art 16** 为小型非互联企业提供简化框架。荷兰 AFM（2026-04-01）确认 **RTS 6 Art 14 与 Art 18 无需纳入自评估**（归 DORA 管辖）。

**可以做（无牌照）** | **不能做（需牌照或违法）**：
- 销售**通用**软件/EA/指标（不针对个人情况）—— 但**在英国受 PERG 8.30.5G 限制**
- 发布**通用公开**信号（美国/欧盟可行；**英国不可行**）
- 展示回测业绩**并附完整强制免责声明**（且美国受 3 个月规则限制）
- 用真实账户的**实盘业绩**（须完整、不挑拣、扣除全部成本）
- 提供执行软件（execution-only 路径）
- 披露试验次数 N、PBO、DSR 等验证指标
- 声明"仅供教育/研究用途"（须与实际一致）
- 在自有网站销售（Market 竞业条款仅禁止用 Market 导流站外）

**强制风险警告清单（最低限度）**：
1. **假设业绩免责声明**：美国非 NFA 会员须逐字使用 **CFTC §4.41(b)(1)(i)**；NFA 会员可用 **2-29(c)(1)**。**同等字号、紧邻**（4.41(b)(2)：非口头时"prominently disclosed and in immediate proximity"）。
2. **过往业绩不代表未来表现**（美国 2-29(b)(4)；英国 **COBS 4.6.2R(4)**）。
3. **提及盈利必须伴随同等醒目的亏损风险讨论**（2-29(b)(3)）。
4. 杠杆交易风险、可能损失**超过本金**（CFTC Reg 5.5）。
5. **零售账户亏损比例**：欧盟/英国要求**该机构自身**的百分比，**每 3 个月重算**（英国 **COBS 22.5.6R(1A)**）——**不是固定 70%**。
6. 软件不构成投资建议、不保证盈利。
7. **所有成本（佣金、点差、隔夜利息）已计入业绩展示**（2-29(b)(5)(ii)；英国 **COBS 4.6.2R(6)** 与 **4.6.7R(1)(c)** 要求披露 gross 数字的费用影响）。
8. 英国 **COBS 4.6.6R(4)**：模拟（回测）业绩须附**醒目警告**；**COBS 4.6.7R(1)(d)**：预测须附警告。

**⚠️ 架构层面的合规含义**：由于 (c)(4) 与 2-29(c)(3) 的五年实际业绩要求，**产品路线图必须从第一天起就规划"实盘业绩采集"**——没有实盘记录，回测营销的窗口期只有头 3 个月，之后必须切换且须披露全部客户账户的实际表现（含亏损账户）。

**现实姿态建议**：**卖软件、发通用研究、绝不自动执行、绝不个性化**。**把美国与英国的"信号业务"视为需要持牌合作方，而不是当作合规成本问题。**

---

## 4. 面向商业销售的运维与工程标准

### 4.1 Kill switch / Dead-man switch 与交易前风控

**监管要求**（RTS 6 Art. 12，见 §3.2）：
- 须能**立即**取消发往任一/全部场所的**任何或全部未执行订单**；
- 覆盖来自**单个交易员、交易台、客户**的订单；
- 须能**识别**每个订单归属哪个算法与哪个交易员/交易台/客户。

**小团队最低实现清单**：
1. **Hard block（硬阻断）**——ESMA 2026 简报要求必须实现，且**默认限额不得被交易员直接或间接绕过**：
   - 覆盖：**价格参数、最大订单价值、最大订单数量、最大消息数、策略重复执行次数限制**；
   - **"temporarily blocks an order but can be overridden at the trader or trading desk level does not constitute a hard block"**；
   - 交易员**不得**在未经对参数彻底复核的情况下自行覆盖硬阻断（也不得经第三方同意覆盖）；参数修订须经**风险管理与合规**；
   - **"Where possible, hard blocks parameters should be hard coded within an algorithm"**——即**写进代码，而非配置项**；
   - 参数设定程序须**书面记录**，并涉及交易、风险管理、合规三方。
2. **Soft block（软阻断）**——同口径但**阈值更低**，仅**告警**不阻断；覆盖需交易员**主动输入**（如重新输入订单参数）。
3. **进程级 kill switch**：一个可被独立进程/信号触发的标志位，轮询间隔 ≤ 1 秒；触发后停止新订单并撤销全部挂单。
4. **Dead-man switch（心跳）**：策略进程须周期性向监控端发送心跳；**心跳丢失 N 秒**（建议 10–30 秒）自动撤单并停止开新仓。
5. **Fat-finger 检查**：价格偏离当前中间价超过 X% 拒绝下单；手数非标准步长拒绝。
6. **Rate limits**：每日订单/请求数上限（prop firm 常见限制见 §5.4）。
7. **通信渠道**：RTS 6 Art. 16(4) 要求监管方/交易所随时能联系到实时监控人员——小团队至少要有**7×24 可达的紧急联系方式**。
8. **再测试触发**：ESMA 明确将"**改变阈值、kill switch 逻辑或告警触发器**"列为**必须重新测试**的变更——即 kill switch 逻辑本身属于受控变更。

**美国对照**：SEC **Market Access Rule 15c3-5**（17 CFR 240.15c3-5）要求券商对市场准入实施交易前风险控制——须在**券商直接且排他控制（direct and exclusive control）**下，且**至少每年复核一次**。CFTC 已用 **Electronic Trading Risk Principles**（2020 最终规则）取代 Reg AT。**均针对持牌机构，非软件供应商，但可作为控制设计参照。**

**RTS 6 其他须知的硬性条款**：
- **Art. 12(3)**：须能识别**每一个订单**归属哪个交易算法、哪个交易员/交易台/客户 → **order-to-strategy-to-client 归因是强制的**。kill switch 本身**无延迟数字要求**；本章唯一的硬数字是 **Art. 16(5)：实时告警须在相关事件后 5 秒内产生**。
- **Art. 8**：部署前须设定**预定义部署限额**——(a) 金融工具数量；(b) 订单价格/价值/数量；(c) 策略持仓；(d) 交易场所数量。
- **Art. 15(3)**：**重复自动执行节流**——达到预定重复执行次数后，系统须**自动禁用，直到被指定人员重新启用**（即"监管形态的 dead-man switch"）。
- **Art. 15(5)**：当交易员无权限、或订单可能使敞口突破阈值时，须**自动阻断/取消**，且须**按客户、工具、交易员、交易台、公司**多层级应用。
- **Art. 15(6)**：对已阻断订单的任何覆盖必须**针对具体交易、临时且例外**，经**风险管理核实**并由**指定个人授权**。
- **Art. 17(1)**：交易后控制须**持续运行**；触发时措施"may include adjusting or shutting down the relevant trading algorithm or trading system or an orderly withdrawal from the market"。
- **Art. 7**：测试环境须**与生产分离**——**明确允许使用供应商提供的测试环境**（对 EA 供应商是直接机会）。但 **Art. 7(3)**：即使使用供应商测试环境，**投资公司仍"retains full responsibility"**。

### 4.2 变更管理、版本化与可复现研究

**RTS 6 Art. 5(7) 强制记录**：任何算法交易软件的**重大变更**须可确定 (a) 变更时间；(b) 实施人；(c) 批准人；(d) 变更性质。
**RTS 6 Art. 11**：生产环境重大变更须经**高管指定人员**审查，深度与变更幅度相称。

**小团队落地**：
- **不可变构件（immutable artifacts）**：每个策略版本 = git commit SHA + 参数文件哈希 + 数据快照哈希，打包为只读构件；
- **模型版本号语义化**：`strategy-v{major}.{minor}.{patch}+{data_snapshot}`；
- **变更审批**：即使是 1 人团队，也保留 `CHANGELOG.md` + 每个版本的 validation memo（谁批准、依据什么证据）；
- **可复现管道**：一条命令从原始数据重跑出与线上完全一致的信号序列（determinism test）；
- **Point-in-time 数据**：所有特征只能使用**当时可得**的数据（防止 look-ahead bias）；宏观数据须用**首次发布值（first release / vintage）**而非修订后值；
- **Survivorship-bias-free**：股票/ETF 池须包含已退市标的；外汇无退市问题但**经纪商与流动性提供商变更**会造成类似偏差。

### 4.3 监控：模型衰减、漂移与对账

**PSI（Population Stability Index）**
公式（R `scorecard` 包文档，<https://search.r-project.org/CRAN/refmans/scorecard/html/perf_psi.html>；与 SAS Model Manager、Yurdakul & Naranjo 一致）：
$$PSI = \sum_i \left(Actual\%_i - Expected\%_i\right)\cdot \ln\!\left(\frac{Actual\%_i}{Expected\%_i}\right)$$

**⚠️ 三个容易出错的实现细节：**

1. **对数底必须用自然对数 ln**。0.10 / 0.25 阈值是按 **ln** 校准的。若用其他底数，等效阈值变为：
   | 底数 | 相对 ln 的缩放 | 等效阈值 |
   |---|---|---|
   | **ln（自然对数）** | ×1 | **0.10 / 0.25（规范值）** |
   | log₂ | ×1.4427 | 0.144 / 0.361 |
   | log₁₀ | ×0.4343 | 0.043 / 0.109 |
   → 用 log₁₀ 或 log₂ 计算却对照 0.1/0.25 判断，**告警率会显著失真**。**建议用 ln 并在文档中明确写出。**
2. **分箱数会影响阈值**。规范阈值按 **10 箱（decile）** 校准；Yurdakul & Naranjo 显示在 n=m=1000、α=0.05 时，**B=10 的基准是 0.034，而 B=20 是 0.060**——箱数翻倍约使零假设下的 PSI 翻倍。**绝不要把 20 箱的 PSI 对照 10 箱的阈值。**
3. **零箱处理无监管或同行评审标准**（`[UNVERIFIED]`）：常见做法有替换为 **0.0001**、**0.5%**、或 **1/N**，或先合并空箱。Yurdakul & Naranjo 直接假设 $p_i>0$ 绕开该问题。**必须明确选定一种并在文档中声明、保持一致。**

**阈值（同行评审来源）**：**Yurdakul, B. & Naranjo, J. (2020/2021), "Statistical properties of the population stability index", *Journal of Risk Model Validation* 14(4), 89–100**，摘要原文：
> "In practice, the following 'rule of thumb' is used: **PSI < 0.10 means a 'little change', 0.10 ≤ PSI < 0.25 means a 'moderate change' and 0.25 ≤ PSI means a 'significant change, action required'.** These benchmarks are used **without reference to statistical type I or type II error rates**."

**该经验法则的原始出处**：**Lewis, E. M. (1994). *An Introduction to Credit Scoring.* Athena Press, London.** —— 即 0.10/0.25 **源自 1994 年信用评分实务惯例，并非监管规定**。论文并明确指出"**the statistical properties of these benchmarks are unknown**"。

**⚠️ PSI 不是监管规定的指标，且固定 0.25 在小样本上无统计意义**
- **没有任何美国监管机构规定 PSI 阈值**（已检索 federalreserve.gov / occ.gov / fdic.gov）。**SR 26-2 要求监控，但未点名任何指标。** **不要把 0.1/0.25 称为"监管要求"。**
- **PSI 无上界**（不是"近似有界"）：$\sum(A-E)\ln(A/E) = KL(A\|E) + KL(E\|A)$，即 **Jeffreys 散度**——继承 KL 的无界性。只有 **JS 散度**才真正有界 $[0,\ln 2]$。
- **统计显著的样本量相关基准**（Yurdakul & Naranjo）：
  $$PSI > \left(\frac{1}{n}+\frac{1}{m}\right)\left(B-1+z_\alpha\sqrt{2(B-1)}\right)$$
  在 α=0.05 下：**n=m=100 时阈值是 0.338**（不是 0.25）；**n=m=1000 时是 0.034**。→ **在 50 笔交易的零售账户上套用固定 0.25，会对噪声告警。**
- **SAS 自家两个图表阈值就不一致**：Characteristic 图用 0.10/0.25，**Stability 图用 0.10/0.30**。

**CSI（Characteristic Stability Index）**：对**单个特征**计算，公式 $CSI = \sum (Actual\% - Expected\%)\cdot score$，用于定位是哪个输入变量漂移。

**KL 散度**：PSI 在对称性假设下与 KL 散度相关（论文 §2 讨论）；PSI 本身**不对称**（交换基准与目标总体会改变分箱与 PSI 值）。

**实盘 vs 回测背离告警**：建议监控
- 滚动 30/90 日实盘 Sharpe vs 回测同期 Sharpe；
- 实盘滑点分布 vs 回测假设滑点（**最关键**——多数"策略失效"实为成本假设错误）；
- 成交率、拒单率、平均持仓时长分布漂移；
- 信号触发频率（骤降 = 数据/连接问题；骤升 = 逻辑异常）。

**与经纪商对账单对账（RTS 6 Art. 13(9) 精神）**：须核对自身电子交易日志与交易场所/经纪商/清算成员记录是否**准确、完整、一致**。每日核对项：
- 持仓数量与方向、开仓均价、浮动盈亏；
- 当日成交明细（含手续费、隔夜利息、滑点）；
- 账户余额与净值变动分解（已实现盈亏 + 未实现 + 费用 + 出入金）；
- **差异必须归零或记录例外**。

**最佳对账标准来源（机构级，可引用）**：**AIMA, *Guide to Institutional Investors' Views… Operational Infrastructures*, §5.3.2.3–5.3.2.6**（<https://acc.aima.org/static/uploaded/7fe04dd4-1149-4415-a707a233374597b2.pdf>）原文：
> "**Triangular reconciliation** of cash and positions should occur **ideally daily**… between the manager, administrator, and prime broker/OTC counterparty."

要求：**自动化、基于例外（exceptions-based）**、配 **daily electronic checklist**、由**高级人员（controller/CFO）监督**、并**职责分离——负责对账现金的人不得签批现金划转**。

**⚠️ 对账不能只用"平均滑点"——必须用 Implementation Shortfall（Perold 1988）**
$$\text{Implementation Shortfall} = \text{Execution Cost} + \textbf{Opportunity Cost}$$
**纯"每笔平均滑点"指标完全遗漏机会成本**：一个 EA 在 60% 信号上完美成交、40% 信号被静默漏掉，在滑点指标上看起来优秀，在 implementation shortfall 上却很糟。**两者都要报告。**

**RTS 6 Art. 10 压力测试倍数（具体、可直接引用）**：压力测试场景须使用**过去六个月**中**最高消息数（highest number of messages）的 2 倍**与**最高交易量（highest trade volume）的 2 倍**。

**SR 26-2 的对应概念**：上述即 "ongoing monitoring" + "outcomes analysis"，并应记录到 model inventory。**注意**：SR 26-2 的 "outcomes analysis" **明确点名 back-testing**，并引用"the banking organization's established performance thresholds"与"model adjustment, recalibration, or redevelopment may be warranted"——**这是把 PSI ≥0.25 惯例与监管框架连接起来的最强桥梁**。新的 **§VII 专门覆盖供应商/第三方产品**，监控包应对照该章映射。

**漂移工具默认值（避免错误宣称"业界标准"）**：
- **Evidently**：≤1000 观测 → KS / 卡方 / Z（p<0.05）；>1000 观测 → Wasserstein（数值）/ JS（分类），阈值 **0.1**；文本 ROC-AUC > 0.55。**⚠️ Evidently 并不默认提供 PSI**——若打算宣称"业界标准 PSI 监控"，此点相关。
- **NannyML**：数值与分类均默认 **Jensen-Shannon，阈值 0.1**。

### 4.4 业界参考与检查清单

| 作者 | 著作 | 与本报告相关的核心贡献 |
|---|---|---|
| Marcos López de Prado | *Advances in Financial Machine Learning* (2018) | Ch.7 purged K-fold + embargo；Ch.11 回测的危险；Ch.12 交叉验证回测；Ch.14 回测统计量；Ch.15 策略风险 |
| Marcos López de Prado | *Machine Learning for Asset Managers* (2020) | 因子/聚类在策略构建中的应用 |
| Ernest Chan | *Quantitative Trading*; *Algorithmic Trading* | 零售量化实务、回测陷阱、执行成本 |
| Robert Carver | *Systematic Trading* (2015); *Advanced Futures Trading Strategies* (2023) | 波动率目标、组合层面风控、成本与容量估计 |
| Andreas Clenow | *Following the Trend*; *Trading Evolved* | 趋势跟踪实务与零售端实现 |
| FCA | 多机构算法交易控制审查 (2025) | 5 大重点领域（见 §3.2） |

**关于"标准 algo trading 审计清单"**：未找到任何监管机构发布的、面向**软件供应商**的通用审计清单。现有的清单均针对**持牌投资公司**。

**🔴 本报告唯一真正重要的未闭合缺口：RTS 6 Annex I 内容无法通过自动抓取获得。**
已尝试**八种途径**全部失败：`legislation.gov.uk` 五种 URL 形式（`/annex/I/adopted`、`/annex/I/adopted/data.xht`、`/annex/I/2016-07-19/data.xht`、`/annexes/2016-07-19/data.xht`、`/annexes/adopted`）**均返回 HTTP 202 空响应体**；`handbook.fca.org.uk` 的 HTML 与 PDF **均 403（Cloudflare）**；FCA 官网 PDF **403（reCAPTCHA 墙）**；Wikimedia 全文镜像**连接失败**；`lovdata.no` 与 `lexaris.ch` **仅渲染标题，正文被登录/JS 外壳截断**。
**→ 需人工浏览器访问一次。** 这一点具有实质影响：**Art. 9(1) 要求年度自评估"include at least an analysis of compliance with the criteria set out in Annex I"**——即 Annex I 是自评估清单的**承重内容**。若面向客户的自评估文档会被评分，**这是唯一必须手工补齐的部分**。
**两个可用替代**：Artizan Governance 的 9 项控制图、以及爱尔兰央行关于自评估流程的专题审查（见下表）。

**🔴 FCA 多机构审查中最具操作性的一条发现**：FCA *Algorithmic Trading Controls: High Level Observations*（**2025-08-21**，覆盖**十家自营交易公司**）中，**FCA 向每家公司索要的第一份文件都是 RTS 6 年度自评估与验证报告**——而**许多系统性基金从未制作过**。
来源：<https://www.fca.org.uk/publications/multi-firm-reviews/algorithmic-trading-controls-high-level-observations>（对自动抓取返回 403；经 Katten / Reed Smith / Grant Thornton 转述确认）

**→ 对小团队的直接含义**：**一份自评估文档就能同时回答 FCA 的第一项要求、配置人 DDQ 与 prop firm 风险审查。**这是成本最低、杠杆最高的单一交付物。

**可用作清单模板的来源**：
| 来源 | 性质 | 链接 |
|---|---|---|
| **RTS 6 Annex I**（Art. 9(1) 自评估标准） | 权威监管清单（**内容无法自动抓取，须人工访问**） | <https://www.legislation.gov.uk/eur/2017/589/annex/I/adopted> |
| **Artizan Governance**, "Algorithmic trading governance under RTS 6" | 实务 9 项控制图 | <https://artizangovernance.com/insights/hf-algo-trading-rts6> |
| **AIMA** *Illustrative Questionnaire for the Due Diligence of Investment Managers* (2025) | 配置人 DDQ | <https://www.aima.org/article/presenting-the-2025-edition.html> |
| **THEIA** *Self-Assessment Guidance* (2022-01) | 英国行业自评估模板（正文 `[UNVERIFIED]`） | <https://www.theia.org/sites/default/files/2022-01/Self-Assessment%20Guidance%20January%202022.pdf> |
| **Central Bank of Ireland** 算法交易年度自评估专题审查（2023-11-02） | 监管专题审查 | <https://www.centralbank.ie/docs/default-source/regulation/industry-market-sectors/investment-firms/mifid-firms/regulatory-requirements-and-guidance/thematic-review-of-the-annual-self-assessment-and-validation-process-across-firms-undertaking-algorithmic-trading-activity.pdf> |
| **FIA** *DEA Scope Diagram + Supporting Text* (v1.5.1, 2017-08) | 一致性测试范围 | <https://www.fia.org/sites/default/files/2022-01/DEA%20Scope%20Diagram%20%2B%20Supporting%20Text%20V1.5.1%20August%202017.pdf> |
| **NIST SP 1326** C-SCRM Due Diligence Assessment Quick-Start Guide（2026-07-08 定稿） | 供应链尽调 | <https://csrc.nist.gov/news/2026/nist-releases-sp-1326> |

**建议做法**：制作**一份** Markdown 清单，镜像 RTS 6 **Art. 9 的四个审查领域**（系统/算法/策略；治理/问责/批准；业务连续性；整体 Art. 17 合规）加 Annex I，**每一条映射到 Art. 5–17 已产出的证据**。

### 4.5 SOC 2 / ISO 27001 对交易 SaaS 供应商的意义

**SOC 2（AICPA Trust Services Criteria）**
- 五个信任服务类别：**Security（必选）**、Availability、Processing Integrity、Confidentiality、Privacy（后四者可选）。
- **Security 类别拆为 9 组、共 33 条 common criteria**，编号 **CC1.1–CC9.2**：CC1 控制环境(5)、CC2 沟通与信息(3)、CC3 风险评估(4)、CC4 监控活动(2)、CC5 控制活动(3)、**CC6 逻辑与物理访问控制(8，最大组)**、CC7 系统运行(5)、CC8 变更管理(1)、CC9 风险缓解(2)。CC1–CC5 源自 **COSO** 框架。
- **现行版本**：**2017 Trust Services Criteria, with Revised Points of Focus — 2022**（2022 年只改"points of focus"实施指引，未改 criteria 本身；文件标题仍为"2017"）。
- **Type I vs Type II**：

| | **Type I** | **Type II** |
|---|---|---|
| 意见对象 | 控制在**某一指定日期**的**设计与实施**（suitably designed） | 控制在**某一期间内**的**设计与运行有效性** |
| 时间维度 | 时点 | 期间 |
| 运行有效性测试 | **无** | **必需**（抽样、穿行测试、全窗口证据） |
| 报告节奏 | 一次性/过渡 | **年度，报告间不得有缺口** |

- **观察期**：初次审计理想为 **12 个月**；**3 个月通常是 CPA 事务所接受的最短观察期**；6 个月亦常见。报告被视为"有效"12 个月，**客户期望报告之间无缺口**。
- **Bridge letter（过渡函）**：由**服务商自己**（非审计师）出具的自我声明，覆盖上一份报告期末至今的缺口，通常 ≤ 3 个月。⚠️ **因无审计师参与，成熟买家视其为弱证据**；许多企业/prop firm 安全审查现在直接要求**无缺口的连续 Type II 报告**。**不要长期依赖 bridge letter。**
- **成本（第三方汇总，非一手）**：首年总成本 **$30,000–$150,000**；审计费 Type I **$5,000–$25,000**、Type II **$12,000–$60,000**（精品/区域所），四大 **$60,000–$200,000+**；年度维持 **$15,000–$50,000**。
- **小团队快速路径**：Type I（控制到位后约 4–8 周）→ 立即开启 Type II 观察窗 → 3 个月窗口 → Type II 报告。**总耗时约 5–7 个月。**
  来源：`_research/compyl_soc2cost.txt`、`docs/compliance/research-2026/compliance-certification-report-2026.md`（聚合 Vanta / URM Consulting / SOC2Auditors.org）。**注：均为厂商或咨询方汇总，非审计行业官方定价，`[UNVERIFIED]` 为精确数字。**

**ISO/IEC 27001:2022**（第 3 版）
- **Annex A = 93 项控制，分 4 个主题**（2013 版为 114 项控制、14 个条款）：
  | 主题 | 数量 | 编号 |
  |---|---|---|
  | Organizational | **37** | A.5.1–A.5.37 |
  | People | **8** | A.6.1–A.6.8 |
  | Physical | **14** | A.7.1–A.7.13 |
  | Technological | **34** | A.8.1–A.8.34 |
- **正文条款 4–10 不可排除（non-excludable）**。
- **⚠️ ISO 27001:2013 证书已于 2025-10-31 全部撤回**；自 **2024-05-01** 起所有初次与再认证审核均按 :2022 进行。
- 认证流程：风险评估 → 控制选择 → ISMS 实施 → **内部审核** → 认证机构**两阶段审核**（Stage 1 文档审查 → Stage 2 实施有效性）；之后**第 1、2 年监督审核**，**第 3 年再认证审核**。
- **成本（第三方汇总，非认证机构官方定价，`[UNVERIFIED]` 为精确数字）**：
  - **10–25 名员工**：Stage 1+2 审核 **5–8 个审核人日** = **€6,000–12,000**；
  - 首年 SMB 总区间 **€43,000–195,000**（中位数 €70,000–100,000）；**精简初创下限 €30,000–50,000**；
  - **≤10 名员工**：审核约 **$10,000**，约 5 天；准备/实施 **$5,000–$60,000**；顾问 **约 $1,500/天**；每次监督审核 **约 $7,500**。
- **周期**：安全基础较好的小公司**最快 3 个月**；流程复杂的大公司**约 1 年**。
  来源：`_research/itg_27001.txt`、`_research/tc_iso_cost.txt`、`docs/compliance/research-2026/compliance-certification-report-2026.md`

**⚠️ SOC 2 质量警告（2026）**：AICPA 已公开警示 SOC 报告质量问题——*Journal of Accountancy*（2026-02-01）"**Promises of 'fast and easy' threaten SOC credibility**"；2026-05-14 "AICPA guides peer reviewers to address SOC 2 risks"；2026-04-13 "Ethics Staff Insights: Business arrangements with SOC tool providers"。
**→ 签约任何 CPA 事务所前，先索取其 peer-review enrolment（同业复核登记）。**

**是否被机构买家期待（2026）**：**是，但证据强度随买家类型急剧变化；未找到硬性的量化统计。**
- **监管压力是真实的、有据可查的**：**FINRA 2026 年度监管监督报告（Third-Party Risk Landscape）**要求会员机构"**Conduct initial and ongoing due diligence of vendor-supported systems**"并"Maintain a detailed inventory of vendor services, connected systems, and **the firm data vendors can access**"；有效实践强调控制须"**formally documented, implemented, and tested**"——这正是 SOC 2 Type II / ISO 27001 证书能以最低成本满足的措辞。
  来源：<https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/third-party-risk>
- **SEC 2026 检查优先事项**：继续聚焦"**operational resiliency, third-party oversight**"；Reg S-P 项下关注"**Oversight of third-party vendors**"；Reg SCI 项下关注"**Management of third-party vendor risk** and proper identification of vendor systems that qualify as SCI systems or **indirect SCI systems**"。（注：sec.gov 直取返回 403，经 KPMG 摘要转述）
- **"人人都在要求 SOC 2"是营销话术**：未找到 AICPA/ISACA/Vanta/Drata 的量化调查支撑该说法 → **`[UNVERIFIED]`**。Vanta *State of Trust* 调查 3,500 名业务与 IT 负责人，但其公布的结论关于 AI 风险与"security theatre"，**与认证采购无关**。
- **实务判读**：零售交易者**从不**询问；**prop firm 与小基金**会通过**安全问卷**询问，且**接受有据可查的清晰回答，即使没有证书**；**券商与受监管实体**才是其检查官在推动第三方监督的买家，他们会要报告。
- **⚠️ 时效性更正**：SEC 券商网络安全规则（**File No. S7-06-23**）已于 **2025 年 6 月正式撤回**（**90 FR 25531**, 2025-06-17，"The Commission does not intend to issue final rules with respect to these proposals"）。**仍在引用该规则作为"即将到来的义务"的资料已过时。**
- **DORA（Regulation (EU) 2022/2554）** 自 **2025-01-17** 适用：
  - **它不直接约束你**。1–3 人 EA 供应商通常**不是**"financial entity"（Art 2(1)(a)–(t)），而是 **"ICT third-party service provider"**（Art 2(1)(u)）。Chapters II–IV 的直接义务落在**金融实体**身上；对 TPP 的直接义务仅在依 **Art 31 被指定为 critical** 时才产生（针对超大规模云厂商，非三人团队）。
  - **它通过你客户的合同与尽调流程触达你**（Art 28(4)(d) 尽调、Art 30 强制条款）。**是否在 EU 设立无关**——Art 29 明确涵盖"established in a third country"的供应商。
  - **🔴 唯一让认证"商业上承重"的条款是 Art 28(5)**：金融实体"may only enter into contractual arrangements with ICT third-party service providers that **comply with appropriate information security standards**"，且对关键/重要职能须"take due consideration of the use… of the **most up-to-date and highest quality** information security standards"。→ 结合 **ISO 27001:2013 证书已于 2025-10-31 全部撤回**，**"most up-to-date"实际上把 :2022 或 SOC 2 变成了承重项**。
  - **Art 30(3) 微型企业豁免（microenterprise derogation）**：允许把审计权**委托给供应商指定的独立第三方**行使——**这是小供应商最重要的谈判工具**。
  - **⚠️ 广泛流传的"DORA 罚款 = 营业额 2% / €10M / 高管 €1M"并不在 DORA Arts. 50–53 中**；DORA 把金额留给成员国自行规定。唯一可核实的数字是 **Art 35(6)–(8)**：定期罚款最高**日均全球营业额的 1%，按日计，最长 6 个月**——且**仅适用于被指定的关键供应商**，1–3 人供应商永远不会触及。
  - **⚠️ 不存在"DORA 认证"**——这是合规与合同工作，不是认证。
  - **Art 30(1)**：完整合同须**包含 SLA 且为单一书面文件**（纸质或其他可下载、持久、可访问格式）→ **散落的订单与 side letter 不合规**。
  - **Art 30(2)** 所有 ICT 合同的**九项最低要素**：职能/服务描述与分包条件；**服务提供地与数据存储地（含变更须提前通知）**；数据可用性/真实性/完整性/机密性；破产或终止时的**访问、取回与返还（易于访问的格式）**；SLA 描述；**事故发生时无偿（或事前定价）协助**；**配合主管与决议机构**；**终止权与最短通知期**；参与客户 ICT 安全意识培训的条件。
  - **Art 28(3) 信息登记册（Register of Information）**：客户须在**结构化监管登记册**中记录你的合同 → **预期被索取 LEI、合同编号、分包链、数据位置、职能关键性**。
  - **Art 28(8) 退出策略**、**Art 29 集中度风险与分包链披露**：若你分包任何环节（托管、支持、遥测），**须披露完整链条**。
  本地副本：`_research/dora.txt`、`_research/dora_roi_its.txt`；详细分析：`docs/compliance/research-2026/compliance-certification-report-2026.md`

**1–3 人团队现实判定**：
- **首年不要做 SOC 2**，除非已有机构客户明确要求并愿意为此付费。
- **优先顺序**：① 一份公开的安全白皮书 + 子处理者清单（成本≈0）；② **DORA 就绪**（这是**合同与文书工作，非认证**——**数周而非数月**，性价比最高）；③ ISO 27001 的**控制映射**（不认证，仅内部对齐）；④ 有客户付费承诺后再做 SOC 2 Type I → Type II。
- 可复用路径：ISO 27001 与 SOC 2 控制高度重叠，**一次实施、两套证据**，先做 ISO 27001 再做 SOC 2 可显著降低成本。**若买家偏美国选 SOC 2；偏 EU/UK/APAC 或 EU 受监管实体选 ISO 27001。**

---

## 5. MT5 特有的商业约束

### 5.1 MQL5 Market 销售规则

一手来源：<https://www.mql5.com/en/market/rules>、<https://www.mql5.com/en/market/help>（本地副本 `_research/market_rules.txt`、`_research/market_sell_help.txt`）

**分成与定价**：
- **Market 佣金 20%（卖方得 80%，不是 50/50）**。Developer Agreement §V："The operational fee of the Market service is equal to **20%**."
  来源：<https://www.mql5.com/en/market/terms/developer>；Market Rules §VII："the 20% commission fee from the payment is charged automatically"
- **最低产品价格 30 USD**。Signals 服务同为 20% 佣金。
- 卖方款项**冻结一周**待审核，无违规后解锁可提现。
- 激活次数 **5–20 次**（由卖方设定）。

**源码**：**不上交源码**。只接受编译文件——"The Product offered through the Market service can be provided only as a compiled file with the EX5/EX4 extension."，且买方被禁止反编译。上架时只能上传**一个 EX5 文件**。

**产品限制（关键）**：
- **禁止任何 DLL 调用**，包括 Microsoft Windows 系统库。原文："Products must not contain calls to any DLL, including Microsoft Windows system libraries."（MQL5 官方论坛确认：DLL 链接在验证阶段被检测并拒绝，Market、Codebase 与 MQL5 VPS 均禁止）
- **禁止集成第三方销售、记账、许可证控制与更新管理系统（包括使用 WebRequest 功能者）**。原文："The Seller shall not integrate and apply any third-party sales, accounting, license control and update management systems (including the ones using WebRequest features) in Products."
  → **这意味着不能用自己的 license server**，商业模式的自由度被显著限制。
- **致命条款**：**"Products may not contain deliberate operation restrictions or change their functionality depending on the account type, account number, trade server name and other similar conditions."** → **禁止账户绑定、禁止 phone-home 式的 kill switch**。
- 禁止**收集用户个人数据**，禁止对功能施加额外自定义限制。
- 禁止发布**仅输入参数/品种/周期不同**的多个同源产品（视为 spam，全部下架并封禁付费服务）。
- **竞业条款**：不得用 Market 分发"主要目的为在 Market 之外分发 MT5 软件应用"的产品；**不得利用从 Market 获得的客户信息在 Market 之外销售产品**。→ 在自有网站销售同一 EA **不**被禁止，但用 Market 把用户导流到站外**被禁止**。
- 禁止通过 Market 销售**有害产品**。
- 卖方须提供**真实个人信息**（含身份证件照片），须修复导致产品提前终止的**严重错误**，须在 MQL5/MQL4 语言变更时**维护产品功能**。

**上架流程**：卖方注册需身份证件，约 **10 个工作日**，可**无需解释地拒绝**。发布为**自动化**流程（约 10 分钟；在 Strategy Tester 中跨品种/周期运行 EA，检查编程错误并确认其确实会交易）。官方声明："The Administration of the Market service provides only a **formal test** of the Product." 并明确**不保证 EA 的盈利能力**。

**Signals 服务**（<https://www.mql5.com/en/signals/rules>，本地 `_research/signals_rules.txt`）：
- 任何 MQL5 账户可成为 Signals Provider，但**收费订阅须先注册为 Seller**。
- Provider 收入 **扣除 20% 佣金**。
- 禁止基于**已有 Signal** 创建新 Signal（违规删除并封号）；**禁止转售或免费转发交易信号**。
- **订阅只能在 MetaTrader 平台内进行，且平台须始终连接服务器**——订阅者终端离线期间不会复制交易。
- MetaQuotes 声明其**仅为技术提供商，不提供任何财务建议**，不对投资决策负责。

### 5.2 MT5 Python API 的限制

一手来源：<https://www.mql5.com/en/docs/python_metatrader5>、PyPI `MetaTrader5`（本地副本 `_research/py_initialize.txt`、`_research/py_docs_index.txt`）

**架构本质**：官方文档明确定义为 **"interprocessor communication"（进程间通信）**：
> "MetaTrader package for Python is designed for convenient and fast obtaining of exchange data via **interprocessor communication directly from the MetaTrader 5 terminal**."

**由此推出的硬约束**：
1. **实际上仅 Windows**：PyPI 全部发行版为 **295 个 `win_amd64` + 10 个 `win32` wheel，零个 manylinux / macosx / sdist**。Linux/macOS 需 Wine + 第三方 shim（如 `mt5linux`）。MT5 终端本身在 Linux 上官方要求 Wine。
2. **不是网络 API** —— Python 进程与终端必须同机，无法远程直连。错误码直接暴露传输层：`-10003 "IPC initialize failed"`、`-10005 "IPC timeout"`。
3. `initialize()` **会在需要时自动启动终端**（文档未要求终端必须已在运行）；默认超时 **60,000 ms**。
4. **数据受终端缓存限制**：K 线仅限"用户图表上可用的历史"；tick 缓存为**最近 4,096 个 tick**（启用 Market Depth 时 65,536 个）；`CopyTicks` 最多阻塞 **45 秒**。
5. **无官方延迟指标 → `[UNVERIFIED]`**。唯一的官方延迟声明（**0–5 ms**；"96% 的经纪商服务器…低于 10 ms"）属于 **MQL5 VPS**，而 VPS **无法运行 Python**。
6. **实务故障模式**（从业者报告）：多个 Python 进程连同一终端会退化并报错；**终端自动更新会破坏 IPC**（2026 年 build 6116 更新后出现 `-10005 IPC timeout`）；`order_send` 失败通常源于 `type_filling` 不匹配（错误码 10030）；更新后 `trade_allowed=False`。
7. **对冲 vs 净值**：Python 文档从不区分账户模式，无文档化的行为差异 → **`[UNVERIFIED]`**。

**Python 包许可证**：**MIT**（PyPI 元数据：`license: MIT`，作者 MetaQuotes Ltd.，v5.0.6180, 2026-09-05）。**商业使用被允许**。
来源：<https://pypi.org/project/MetaTrader5/>

**Web Terminal**：纯浏览器手动交易——"30 indicators and 24 graphical objects"，**无 EA、无 MQL5、无 Python**；"Each web terminal is assigned to a specific broker and is located on its domain." **不是**供应商的部署目标。

**MQL5 VPS**：$15/月（1 个月）→ $10/月（12 个月）。"No DLLs are allowed on a Virtual terminal. There is no physical capacity to use DLLs there."；"User has no physical access to the rented terminal."；最多 32 个图表/EA（免费版 16 个）；**脚本不会被迁移**；**无法托管 Python**。
来源：<https://www.mql5.com/en/vps/rules>

### 5.3 MetaQuotes 许可（EULA）约束

一手来源：MetaQuotes 终端 EULA（本地副本 `_research/eula_mt5_net.txt`）

- **§2.1**：授予的是 **"limited, worldwide, individual, non-exclusive, simple, non-sublicensable, non-assignable, revocable, non-transferable, free of charge license"**，用途限于 **"organizing a trader's workstation and trading in the financial markets"**。
- **§2.2 No Granting of Rights to Third Parties**：**"You shall not sell, assign, rent, lease, distribute, export, import, or otherwise grant rights to use the Product or any part thereof to a third party."**
- **§2.16**：**"In the event that You wish to use the Product in a manner other than as expressly set out in this Agreement, such use is expressly prohibited unless and until MetaQuotes grants You a specific license in writing."**
- **§2.14 / §2.3**：禁止反向工程、反编译、修改界面。
- **§2.20**：MetaQuotes 可**自行决定、无需通知**地修改、中止或终止许可。
- **§5.4**：适用法律为**塞浦路斯共和国**法律，专属管辖为**利马索尔地区法院**。

**实务含义**：终端 EULA **不允许**把 MT5 终端本身作为服务转售/分发给第三方。合规做法是**客户自行安装终端**，供应商只交付 EA/软件与其自身服务。

### 5.4 架构方案对比

| 方案 | 延迟 | 成本 | 准入门槛 / 缺点 |
|---|---|---|---|
| **A. 客户本地 EA** | 低 | $0 | 源码暴露风险；无法集中更新；**Market 版禁用 DLL 与 license server**；**禁止账户绑定** |
| **B1. Connector EA + 原生 Socket** | 低 | $0 | 客户须手动把 host:port 加入终端白名单；**最多 128 个 socket**；**只能从 EA/脚本调用** |
| **B2. Connector EA + WebRequest** | 高（同步阻塞） | $0 | 白名单；**Strategy Tester 中不可用** |
| **C. MQL5 VPS** | **<5 ms**（至 80% 经纪商） | $10–15/月 | **禁 DLL、禁 Python、无物理访问**；最多 32 图表/EA |
| **D. cTrader Open API** | 低（持久 TCP/WS） | 免费 | 需 cTID + Spotware 审批；**50 req/s**，历史数据 5 req/s |
| **D. cTrader FIX 4.4** | 最低 | 免费 | "no conditions applied such as minimum trading volume or minimum deposit size" |
| **D. OANDA v20 REST** | 中 | 免费 | 需 v20 账户（非 Global Markets/TMS） |
| **D. OANDA FIX** | 最低 | — | "only available for approved **institutional** clients" |
| **D. IBKR FIX** | 最低 | **$1,500/月最低佣金** | 机构级 |
| **E. MT5 Manager / Gateway API** | — | **`[UNVERIFIED]`** | 随**持牌券商**部署捆绑；无公开文档、无公开价目 → 对小供应商实际封闭 |
| **F. 白标 MT5 券商** | — | **`[UNVERIFIED]`** | 仅找到第三方咨询页，商业条款未证实 |

**Socket 函数的关键限制**（<https://www.mql5.com/en/docs/network/socketcreate>，本地 `_research/socketcreate.txt`）：
- 一个 MQL5 程序**最多创建 128 个 socket**，超出报错 5271 (`ERR_NETSOCKET_TOO_MANY_OPENED`)。
- **只能从 Expert Advisor 和脚本调用**（因其运行在独立执行线程）；从指标调用返回错误 4014 "Function is not allowed for call"。
- **白名单是最大的部署摩擦**："the list of allowed IP addresses is implemented on the client terminal side... **An address cannot be added programmatically.**"
  来源：<https://www.mql5.com/en/docs/network>

**推荐架构（1–3 人团队）**：
- **零售/Market 渠道** → 方案 A（纯 MQL5，无 DLL，无外部 license server，接受不能账户绑定）。
- **B2B/小基金渠道** → 方案 B1：客户终端内一个极薄的 connector EA（仅负责收发与执行），策略与风控在自建服务器；服务器侧持有完整 kill switch 与对账逻辑。**接受每个客户须手动加白名单这一摩擦**。
- **追求低延迟且愿换券商** → 方案 D（cTrader Open API + FIX 是"延迟/准入门槛"性价比最优的非 MT5 路线）。
- **Python API 只用于研究与回测，不作为交付机制。**

### 5.5 Prop Firm 特有约束

**这是对小团队商业模式的重大约束，须逐家核验。**

| Prop Firm | 关键约束（均为一手官网规则） |
|---|---|
| **FTMO** | EA **允许**，但平台服务器限制 **"200 orders at a time and 2000 max positions per day"**；禁止 EA 导致"**more than 2,000 server requests per day**"（"causing overload of the trading server"）。禁止"ultra-high-speed tools"。**VPS/VPN 一般允许**，唯一例外：不得从**美国**登录（MT5/cTrader/TradingView）。 |
| **The5ers** | **"the trader must own the source code of the EA"** → **纯编译产品无法使用**。禁止 copy signals、tick scalping、latency/hedge arbitrage、HFT（"majority of trade durations… within a few seconds or less"）、emulators。**止损必须可见**（禁止 stealth stop-loss）。通过后适用 **30% 或 50% 一致性规则**（"Best trading day ÷ profits from profitable days"）。 |
| **Funding Pips** | 第三方 EA **"permitted only when used strictly as a trade or risk manager"**；自有 EA 全自动化需**所有权证明**——**"Source code files (uncompiled .mq5, .mq4…)"**，"**A compiled binary on its own is not proof.**" **VPN/VPS 明确禁止**（"Connecting to a VPN or VPS… is not permitted"）。**35% 一致性规则**（Zero 账户 15%）。新闻窗口 **±5 分钟**（演讲 ±10 分钟）；**评估与 master 阶段故意做新闻均被禁止**。 |
| **Alpha Capital** | EA **"strictly limited to risk management and trade assistance tools"**；**"Automated EAs that execute trades independently, without human oversight, are strictly prohibited and will not be approved under any circumstances."** EA 需**预先审批**（提交 EX5 / MQ5）。**平均持仓须 > 2 分钟**且 ≥50% 毛利来自 >2 分钟的交易。Position spamming = **60 秒内开 3 个或以上同向仓位**。VPS **允许但须静态 IP + 事先邮件通知**。 |
| **Topstep（期货）** | 无全面 EA 禁令，但禁止"software, AI, ultra-high speed systems, or mass data entry that… provides an unfair advantage"；禁止**SIM 剥削**（scalping algorithms exploiting unrealistic SIM fills、tight brackets / auto-breakeven）。**"Do not use a VPN."** 一致性目标 **40%**。 |

**结构性限制**：**MT5 Signals 服务在 prop 账户上不可用**——**不是** prop firm 政策，而是 **MetaQuotes 的设计**。MT5 **build 4150**（2024-01）发布说明："**Terminal: Disabled support for the Signals service for demo accounts.**" MetaQuotes CEO Renat Fatkhullin 在 MQL5 论坛确认：任何**非真实账户（demo、contest、cents 等）**的信号支持被**完全移除**；"MQL5 functions SignalsXXXX are abolished; they return empty data"；对信号订阅账户"**Any copiers are prohibited**"、"Connections with read only passwords are prohibited"。**由于所有 prop 账户都是 demo 账户，内置 MT5 Signals 服务在结构上不可用。**
来源：<https://www.mql5.com/en/forum/461169>

**一致性规则（consistency rules）** 已成为行业标准（**15%–50%**），**直接惩罚依赖单日大额盈利的自动化策略**。

**对 §4.1 的硬性外部约束**：EA 必须内置**请求预算与限流**（FTMO 的 2,000 次/日、200 单/时上限），且须满足**最短持仓时长**（Alpha Capital >2 分钟；The5ers/Topstep 禁止秒级持仓）。

**🔴 渠道冲突（最重要的商业结论）**：**The5ers、Funding Pips、Alpha Capital 均要求客户拥有 EA 源码**，而 **MQL5 Market 只交付编译文件**。→ **零售渠道与 prop 渠道需要不同的交付物**，不能一套产品打天下。若目标客户含 prop firm，**必须规划源码交付（含授权与防扩散机制）**。

**VPS 是分歧最大、也是供应商风险最高的一项**：Funding Pips 与 Topstep **明确禁止**；Alpha Capital 允许但须**静态 IP + 事先邮件通知**；FTMO 允许（美国地理定位除外）。**任何 VPS 托管的机器人都必须逐家 prop firm 核验。**

来源：<https://ftmo.com/en/forbidden-trading-practices/>、<https://the5ers.com/faqs/>、<https://help.fundingpips.com/hc/en-us/>、<https://help.alphacapitalgroup.uk/en/>、<https://help.topstep.com/en/>（本地汇总：`docs/compliance/research-2026/prop-firm-ea-constraints-2026.md`）
**`[UNVERIFIED]`**：E8 Markets 全部 URL 返回 HTTP 403（Cloudflare 人机校验），**其规则未能读取，故不作任何断言**。

---

## 6. 总体结论

1. **最紧迫的时效性事实**：SR 11-7 已于 **2026-04-17 被 SR 26-2 取代**；引用 SR 11-7 的旧材料已过时。EU 侧最新立场是 **ESMA 2026-02-26 算法交易监管简报**（早于它的 FCA 审查为 2025-08-21）。
2. **监管义务对小型供应商基本不适用**（SR 26-2 非强制且限 >$300 亿银行；PRA SS1/23 限英国 IM firms；RTS 6 限持牌投资公司），但**其结构是可白拿的最佳实践模板**。SR 26-2 因收窄模型定义 + 明示非强制，**比 SR 11-7 更适合**被自愿采纳。
3. **可信度的真正门槛在 §2**：公开 **试验次数 N + MinBTL + DSR + PBO**。这是低成本、高差异化、且是文献点名的行业失格点。
4. **§3 的底线清晰**：卖**客户自行配置运行**的通用软件在三个辖区**都无需牌照**；但**个性化建议、代客下单/自动执行**在三地均需授权。**⚠️ 关键不对称**：**发布通用公开信号在美国与欧盟可行，在英国不可行**——**PERG 8.30.5G** 将产生"具体买卖信号"的软件原则上视为**投资建议**。**注册豁免 ≠ 广告规则豁免**（4.41(c)(2)）。**英国未经批准传达金融推广是刑事犯罪**（FSMA s.21(1)），且 **Discord/Telegram 计入**（FG24/1 ¶2.8）。
5. **§4 的最低可行运维**：kill switch + 心跳 + 限额 + 每日**三方**对账 + PSI/背离监控 + 版本化构件。**PSI 阈值 0.1/0.25 源自 Lewis (1994) 信用评分惯例，非监管规定**，且在小样本上须改用样本量相关基准。SOC 2 应在**有客户付费要求后**再做；**DORA 就绪**（合同与文书，数周）性价比最高。
6. **§5 的架构结论**：MT5 Python API 是 **Windows-only 的同机 IPC**，不是网络 API，无延迟 SLA，且**会被终端更新破坏**——只用于研究。商业交付走 **connector EA + 中心服务器（原生 socket）**，并注意 Market 对 DLL / license server / **账户绑定**的禁令与终端 EULA 对转售的禁止。
7. **渠道冲突须提前决策**：MQL5 Market（80% 分成、交付编译文件、禁止账户绑定）与 **prop firm 客户（The5ers / Funding Pips / Alpha Capital 均要求交付源码）** 需要**不同的交付物与商业模式**，不能一套产品打天下。另：**MT5 内置 Signals 服务在 prop 账户上结构性不可用**（build 4150 起禁用 demo 账户信号）。
8. **🔴 最紧迫的商业风险（并列两项）**：
   - **NFA 2-29(c)(4)**（2025-07-21 生效）—— 系统一旦有 **3 个月实盘业绩**，即**不得再用回测业绩做营销**。任何以回测为卖点的 EA 产品必须**从第一天就采集实盘业绩**，并规划好营销口径的切换点。**这是对商业模式影响最直接的单一条款。**
   - **英国 PERG 8.30.5G** —— 触发授权的是**信号业务**，不是软件业务。**若目标市场含英国，"卖信号"这条产品线必须改为持牌合作方模式，或直接放弃。**

9. **一句话总结**：**卖软件、发通用研究、绝不自动执行、绝不个性化**——这是 1–3 人团队在 2026 年唯一可持续的无牌照姿态；**美国与英国的"信号业务"应视为需要持牌合作方，而不是当作合规成本问题。**

---

## 附：本地一手资料索引

| 主题 | 本地路径 |
|---|---|
| SR 26-2 正文 | `_research/sr2602a1.txt` |
| PRA SS1/23 | `research/pdf/ss123.txt` |
| ECB TRIM 报告 | `research/pdf/ecb-trim.txt` |
| DSR 论文 | `research/pdf/deflated-sharpe.u8.txt` |
| PBO / CSCV 论文 | `research/pdf/backtest-prob.u8.txt` |
| MinBTL 论文 | `research/pdf/backtest-pseudo.u8.txt` |
| White Reality Check | `research/pdf/white-reality-check.txt` |
| RTS 6 全文 | `sources/raw/rts6_2017_589.txt` |
| FCA 算法交易审查 | `_research/fca_algo.txt` |
| NFA 2-29 / CFTC 4.41 | `_reg/nfa_promo_2019.txt`、`_reg/cftc_441.html` |
| **US 监管完整报告（子代理产出）** | `research/US-Regulatory-Findings-EA-Vendors-2026.md` |
| **EU/UK/US 合并监管报告（子代理产出）** | `REGULATORY-REALITY-EA-SIGNALS-2026.md` |
| **方法说明** | `fca.org.uk` / `handbook.fca.org.uk` 对自动抓取返回 403（Cloudflare / reCAPTCHA）；FCA 规则文本经官方 Handbook PDF 的 Wayback 快照获取。`nfa.futures.org` PDF 与 `eur-lex.europa.eu` 可直接访问。 |
| **⚠️ 来源质量警告** | 检索 RTS 6 时出现的 **`presencis.com` 是 AI 生成的合规摘要站**——其"RTS 6 Articles 12–17"摘要**错误归属内容，不具权威性**。本报告**未**采用该来源。若后续检索中再次出现，请忽略。 |
| **⚠️ FCA 2018 审查引用方式** | FCA 2018 年审查的内容经**搜索索引片段**核实，**非直接读取 PDF**（reCAPTCHA 墙）。报告已将该 PDF 正文标注为 `[UNVERIFIED]`，未把引文当作直接读取结果呈现。 |
| ESMA 2026 算法交易简报 | `research/pdf/esma_algo_2026.txt` |
| FCA COBS 4 | `sources/cobs4.utf8.txt`（COBS 4.6.2R / 4.6.6R / 4.6.7R 已逐条核验） |
| **UK 监管完整报告（子代理产出）** | `UK_regulatory_findings_2026.md` |
| RAO 2001（英国受监管活动） | `sources/fpo2001_whole.xml`、`sources/fpo_art20.clean.txt` |
| ESMA CFD 产品干预 FAQ | `research/pdf/esma_cfd_faq.txt` |
| PSI 学术论文 | `_research/psi_wmu.txt` |
| **模型监控/漂移/对账完整报告（子代理产出）** | `model-monitoring-drift-reconciliation-2026.md` |
| MQL5 Market 规则 | `_research/market_rules.txt` |
| MT5 EULA | `_research/eula_mt5_net.txt` |
| MT5 Python 文档 | `_research/py_initialize.txt`、`_research/py_docs_index.txt` |
| Socket 函数 | `_research/socketcreate.txt` |
| SOC 2 成本 | `_research/compyl_soc2cost.txt` |
| **合规认证完整报告（子代理产出）** | `compliance-certification-report-2026.md`（SOC 2 / ISO 27001 / DORA / 买家预期） |
| **Prop firm 约束报告（子代理产出）** | `prop-firm-ea-constraints-2026.md` |
| ISO 27001 | `_research/itg_27001.txt` |
| DORA | `_research/dora.txt` |
| Prop firm 限制 | `_research/ftmo_forbidden.txt` |
