# Model Monitoring, Drift Detection & Reconciliation Standards — MT5 EA Vendor Reference (Target Year 2026)

**Scope:** live automated trading system (MetaTrader 5 Expert Advisors) sold commercially to retail, prop-firm and small-fund clients.
**Method:** primary sources only where possible; every URL below was fetched and verified unless marked otherwise. Items that could not be confirmed are marked **UNVERIFIED**.

---

## ⚠️ HEADLINE CORRECTION — READ FIRST

**SR 11-7 is no longer in force.** It was **superseded and replaced on 17 April 2026 by SR 26-2, "Revised Guidance on Model Risk Management"**, issued jointly by the Federal Reserve, OCC and FDIC.

- SR 26-2 letter: https://www.federalreserve.gov/supervisionreg/srletters/sr2602.htm *(verified HTTP 200)*
- SR 26-2 attachment PDF: https://www.federalreserve.gov/supervisionreg/srletters/SR2602a1.pdf *(verified — 212,935 bytes, extracted)*
- SR 11-7 original URL `https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm` now returns **404** (verified). The attachment `sr1107a1.pdf` also returns **404** (verified).
- SR 26-2 supersedes **both** SR 11-7 (4 Apr 2011) and SR 21-8 (9 Apr 2021).

Any 2026 marketing, DDQ or sales material that cites "SR 11-7" as *current* Fed guidance is out of date. Section 4 below gives both the legacy SR 11-7 framework (still the industry's shared vocabulary) and what SR 26-2 actually says now.

---

# 1. Population Stability Index (PSI) and Characteristic Stability Index (CSI)

## 1.1 The exact formula — VERIFIED, with the variant forms

The form in the brief is **correct**:

```
PSI = Σ_i (Actual%_i − Expected%_i) × ln( Actual%_i / Expected%_i )
```

Verified against three independent primary sources:

| Source | Verbatim formula | URL |
|---|---|---|
| SAS Model Manager 15.7 *Monitoring and Reporting* (SAS Institute), "Characteristic" section | `PSI = ∑ % Actual − % Expected × ln % Expected % Actual` (PDF layout garbles the fraction; it is the standard (A−E)·ln(A/E) form) | https://documentation.sas.com/api/collections/mdlmgrcdc/v_057/docsets/mdlmgrug/content/mdlmgrug.pdf *(4.0 MB PDF, downloaded + text-extracted)* |
| Yurdakul & Naranjo, *Journal of Risk Model Validation* 14(4), 89–100 (2020/2021) | Derives PSI as the symmetric divergence and shows it reduces to `Σ (p(x_i) − q(x_i))(ln p(x_i) − ln q(x_i))` | https://files.wmich.edu/s3fs-public/attachments/u730/2022/PSIfinal.pdf *(309,902 bytes, extracted)* |
| du Pisanie, Allison & Visagie, arXiv:2206.11344 | `PSI = Σ_{j=1}^{n} (T_j − B_j) log( T_j / B_j )` where T = test proportions, B = base proportions | https://ar5iv.labs.arxiv.org/html/2206.11344 |

**Equivalent forms actually found in the wild:**

1. `Σ (A_i − E_i) · ln(A_i / E_i)` — the canonical form. **Use this.**
2. `Σ (A_i − E_i) · (ln A_i − ln E_i)` — algebraically identical (Yurdakul & Naranjo use this).
3. `Σ A_i · ln(A_i / E_i) + Σ E_i · ln(E_i / A_i)` — identical, just split into two KL terms (see §2.2).
4. `Σ A_i · ln(A_i / E_i)` — **NOT equivalent.** This is one-directional KL divergence `KL(A‖E)`, not PSI. Seen in some blog posts and in code that forgets the `−E_i` term. It is asymmetric and will disagree with PSI.
5. The SAS Model Manager **"Stability"** chart for output variables uses the same form as (1) but with **different thresholds** (see §1.4).

**Log base — this matters and many sources get it wrong.** The canonical thresholds (0.1 / 0.25) are calibrated for the **natural logarithm (ln)**. Because `log_b(x) = ln(x)/ln(b)`:

| Base | Scaling factor vs ln | PSI at which a given distribution shift registers |
|---|---|---|
| ln (natural) | ×1 | 0.10 / 0.25 (canonical) |
| log₂ | ×1.4427 | 0.144 / 0.361 |
| log₁₀ | ×0.4343 | 0.043 / 0.109 |

If you compute PSI in log₁₀ or log₂ and then compare to 0.1/0.25 you will get materially different alert rates. **Recommendation: use ln and state it explicitly in your documentation.** (Scaling factors are elementary arithmetic; the *thresholds* being calibrated to ln is stated implicitly by SAS and by Yurdakul & Naranjo, who both use ln with 0.1/0.25.)

## 1.2 Bucketing convention — VERIFIED

**Standard: deciles (10 bins) of the EXPECTED / development / base distribution, with bin edges frozen from the base sample and then applied unchanged to the actual sample.**

Verbatim evidence:

- **Yurdakul & Naranjo (2020), §2:** *"However, per the current use of the PSI, the cell counts or percentages are created from binning the underlying distribution in the development data. The bins are basically dependent on the base population's distribution."* They further note this is why PSI is only *conditionally* symmetric: *"Although KL divergence is not symmetric, the PSI is symmetric under the assumption that cutoff values are predetermined. However, in practice that is not true, since the cutoff points correspond to the percentiles of the base population that ultimately determine the PSI. If the base and target populations switch roles, then this changes the cutoff points and consequently the PSI."* — https://files.wmich.edu/s3fs-public/attachments/u730/2022/PSIfinal.pdf
- Their simulation uses `B = 10` population deciles explicitly (`(p̂_1, …, p̂_10)` "the observed proportions that fall into the B = 10 population deciles").
- **Pruitt, "The Applied Use of Population Stability Index (PSI) in SAS Enterprise Miner," SAS Global Forum 2010, paper 288-2010:** *"the data sample needs to be portioned in appropriate quantile distributions (I.e., Decile=10 Bins; Demi-Decile=20 Bins)"*, and the code comments: *"I used 10 buckets just because I like the word 'decile'; often people use 'demidecile' for 20 5% buckets."* — http://support.sas.com/resources/papers/proceedings10/288-2010.pdf *(downloaded, 238,311 bytes, extracted)*
- **SAS Model Manager** states for the Characteristic chart: *"Numeric predictor variable values are placed into bins for frequency analysis. Outlier values are removed to facilitate better placement of values and to avoid scenarios that can aggregate most observations into a single bin."*

**Alternatives in practice:** 20 bins (demi-decile — the Yurdakul & Naranjo Table 3 benchmark table is computed for `B = 20`); fixed-width bins; and for genuinely categorical variables, one bin per category (no quantiling).

**Critical caveat:** the threshold is **not** independent of bin count. Yurdakul & Naranjo show the α = 0.05 benchmark for n = m = 1000 is **0.034 for B = 10** but **0.060 for B = 20** (their Tables 2 and 3). Doubling the bins roughly doubles the null-hypothesis PSI. Never compare a 20-bin PSI to a 10-bin threshold.

## 1.3 Zero-bin handling

This is a real, unavoidable problem: `ln(A/E)` is `−∞` if `E = 0` and undefined if `A = 0`. Standard workarounds:

- **Replace 0 with 0.0001** (the most commonly cited convention; appears throughout credit-risk practitioner code).
- **Replace 0 with 0.5%** (equivalent to 0.005) — often used when bins are deciles, since 0.5% is an order of magnitude below the 10% expected bin share.
- **Replace 0 with 1/N** (where N = bin count), i.e. assume one observation in an empty bin.
- **Merge/suppress empty bins** before computing (SAS Model Manager removes outliers to avoid "most observations aggregating into a single bin").
- **Pruitt / SAS Global Forum 2010** handles the related zero/missing problem explicitly by **binning zeros and missing values as their own buckets** rather than dropping them: the code contains a `ZeroMiss` format with `0='Zero' 11='Missing' 21='Missing'` and the output title is *"NOTE: PSI Calc Accomodates the Binning of Zero And Missing"*.

**UNVERIFIED:** I found no *regulator* or *peer-reviewed* source that prescribes a specific constant (0.0001 vs 0.5% vs 1/N). These are practitioner conventions. Yurdakul & Naranjo assume `p_i > 0 for i = 1,…,B` — i.e. they define the problem away rather than solve it. **State your chosen convention in your documentation and be consistent**; the choice materially changes PSI when bins are sparse.

## 1.4 Citable threshold sources — the core deliverable

The 0.1 / 0.25 rule of thumb is **real and citable**, but it originates in the credit-scoring practitioner literature, not in regulation. Strength-ranked:

### Tier 1 — Peer-reviewed journal (strongest citable source)

**Yurdakul, B. and Naranjo, J. (2020/2021), "Statistical properties of the population stability index," *Journal of Risk Model Validation* 14(4), 89–100.**
URL: https://files.wmich.edu/s3fs-public/attachments/u730/2022/PSIfinal.pdf *(also as a WMU dissertation: https://scholarworks.wmich.edu/dissertations/3208/)*

Verbatim, from the **Abstract**:
> "In practice, the following 'rule of thumb' is used: **PSI < 0.10 means a 'little change', 0.10 ≤ PSI < 0.25 means a 'moderate change' and 0.25 ≤ PSI means a 'significant change, action required'.** These benchmarks are used without reference to statistical type I or type II error rates."

And again in **§4 Benchmarks**:
> "A typical rule of thumb **(Lewis 1994)** for the extent to which a distribution has shifted is the following: PSI < 0.10 means a 'little change', 0.10 ≤ PSI < 0.25 means a 'moderate change', and 0.25 ≤ PSI means a 'significant change'. **However, the statistical properties of these benchmarks are unknown.** For example, how frequently will the PSI exceed 0.10 when in truth there has been no population shift?"

**The originating citation** (this is the one to quote for provenance):
> **Lewis, E. M. (1994). *An Introduction to Credit Scoring.* Athena Press, London.** — cited in the Yurdakul & Naranjo bibliography as the source of the rule of thumb.

**This is the single best source to cite.** It is peer-reviewed, it states the thresholds verbatim, it names the origin (Lewis 1994), and — crucially — it also gives you the honest caveat and a statistically defensible replacement (below).

### Tier 2 — Vendor / industry documentation (SAS Institute)

**SAS Model Manager 15.7, *Monitoring and Reporting*, Chapter 11 "Concepts: Performance Monitoring."**
URL: https://documentation.sas.com/api/collections/mdlmgrcdc/v_057/docsets/mdlmgrug/content/mdlmgrug.pdf

**Characteristic chart (per input variable), verbatim:**
> "If the baseline input data set and the subsequent input data sets have identical distributions for a variable, the variable's population stability index (PSI) is equal to 0. **A variable with a PSI value that is [greater than 0.1] is classified as having a moderate change in distribution.** The Characteristic chart uses the performance measure P1 to count the number of variables that receive a PSI value that is greater than 0.1.
> **A variable that has a PSI value that is [greater than 0.25] is classified as having a significant change in distribution.** A performance measure P25 is used to count the number of variables that have significant changes in distribution, or the number of input variables that receive a PSI score value that is **greater than or equal to 0.25**."

**Stability chart (per output variable), verbatim — NOTE THE DIFFERENT NUMBERS:**
> "An output variable with a PSI value that is **greater than 0.10 and less than 0.25** is classified as having a moderate change in distribution. A variable that has a PSI value that is **greater than 0.30** is classified as having a significant change in distribution. Too much of a shift in predictive variable output can indicate that **model tuning, retraining, or replacement might be necessary**."

⚠️ **Discrepancy to be aware of:** SAS's own two charts disagree — the Characteristic (input) chart uses 0.10 / 0.25; the Stability (output) chart uses 0.10 / **0.30**. This is a good illustration that these are conventions, not laws. Also note the raw PDF text renders the comparison operators as `P1>` and `P25>` due to PDF font encoding; the surrounding sentences make the 0.1 and 0.25 values unambiguous.

**SAS Global Forum 2010, paper 288-2010 (Pruitt), "The Applied Use of Population Stability Index (PSI) in SAS Enterprise Miner."**
URL: http://support.sas.com/resources/papers/proceedings10/288-2010.pdf
> "Per Jay Kosters' research, a score of **<= 0.1 indicates little change, 0.1 - 0.25 is little change but to[o] small to determine and > 0.25 is a significant shift.**"

This paper also documents the **regulatory origin of the practice**: *"during a review of our internal statistical modeling 'best practices', the Federal Reserve (FED) auditors inquired as to how we validate the continued stability of the components that are used in our models."* — i.e. PSI was adopted **in response to Fed examiner questions**, even though the Fed never mandated a numeric threshold. This is a useful, honest framing for a vendor: *the Fed asks the question; the 0.1/0.25 answer comes from industry practice.*

### Tier 3 — Open-source library documentation

**R `scorecard` package, `perf_psi`** — https://search.r-project.org/CRAN/refmans/scorecard/html/perf_psi.html
> "The rule of thumb for the PSI is as follows: **Less than 0.1 inference insignificant change, no action required; 0.1 - 0.25 inference some minor change, check other scorecard monitoring metrics; Greater than 0.25 inference major shift in population, need to delve deeper.**"

### Tier 4 — Secondary/consulting (weakest; use only for corroboration)

KPMG, CRISIL, Management Solutions, ValidMind and Empyrean Solutions all published SR 26-2 commentary in 2026 that discusses MRM monitoring expectations. Several were unreachable at the time of writing (403 / DNS failures) — see the UNVERIFIED list in §6. **Do not cite these as the source of the 0.1/0.25 numbers**; cite Lewis (1994) / Yurdakul & Naranjo (2020) / SAS instead.

### Tier 5 — Regulators: the honest answer

**I could not find any US federal banking regulator (Fed, OCC, FDIC) document that prescribes PSI numeric thresholds.** Searches of federalreserve.gov, occ.gov and fdic.gov returned no PSI threshold language. This is a genuinely important finding:

- **SR 11-7 (and now SR 26-2) require monitoring and outcomes analysis but specify NO metrics and NO thresholds.** The guidance is deliberately principles-based.
- The FDIC *Credit Card Activities Manual* (2007), ch. 8 "Scoring and Modeling," is cited in the academic literature as touching on scorecard monitoring — URL https://www.fdic.gov/regulations/examinations/credit_card/pdf_version/ch8.pdf — but this URL returned **403 Forbidden** to automated retrieval and I could not verify whether it contains PSI thresholds. **UNVERIFIED.**
- The UAE Central Bank Rulebook §4.3 "Model Life-Cycle" appeared in search results as containing model-monitoring expectations, but https://rulebook.centralbank.ae/en/rulebook/43-model-life-cycle returned **403 Forbidden**. **UNVERIFIED** — worth a manual browser check, as a Gulf-regulator PSI mention would be a strong citation for prop-firm clients.

**Framing for your documentation:** "The 0.1/0.25 thresholds originate in retail credit-scoring practice (Lewis 1994) and are the de facto industry standard, documented by SAS Institute and implemented in standard open-source scorecard libraries. They are **not** prescribed by any regulator. SR 26-2 requires ongoing monitoring and outcomes analysis but specifies no metric or threshold; the choice and calibration of thresholds is the firm's responsibility."

### 1.4.1 A statistically defensible upgrade (strongly recommended)

Yurdakul & Naranjo derive the asymptotic distribution of PSI under the null and propose replacing the fixed rules of thumb with sample-size-aware benchmarks. Their **§5, equations (5.1) and (5.2)**:

```
PSI  >  χ²_{α, B−1} · (1/n + 1/m)                                    ... (5.1)

PSI  >  (1/n + 1/m) · (B − 1 + z_α · sqrt(2(B − 1)))                ... (5.2)
```

where `n` = base sample size, `m` = target sample size, `B` = number of bins, `α` = chosen significance level.
> "The practitioner may choose α = 0.10, 0.05, 0.01 or 0.005, depending on the acceptable level of risk the institution or practitioner assumes."

Their **Table 2 (B = 10, α = 0.05)** — the PSI value that should trigger action, by sample size:

| n \ m | 100 | 200 | 400 | 600 | 800 | 1000 |
|---|---|---|---|---|---|---|
| **100** | 0.338 | 0.254 | 0.211 | 0.197 | 0.190 | 0.186 |
| **200** | 0.254 | 0.169 | 0.127 | 0.113 | 0.106 | 0.102 |
| **400** | 0.211 | 0.127 | 0.085 | 0.070 | 0.063 | 0.059 |
| **600** | 0.197 | 0.113 | 0.070 | 0.056 | 0.049 | 0.045 |
| **800** | 0.190 | 0.106 | 0.063 | 0.049 | 0.042 | 0.038 |
| **1000** | 0.186 | 0.102 | 0.059 | 0.045 | 0.038 | 0.034 |

**Read this table carefully — it is the most practically important number in this section.** For a small sample (n = m = 100), the correct 5%-significance PSI threshold is **0.338**, not 0.25. Using 0.25 there produces false alarms. Conversely for n = m = 1000 the correct threshold is **0.034**, so using 0.25 means you will miss real drift by a factor of ~7.

**This is directly relevant to a retail/prop-firm EA vendor**, where a single client account may generate only tens or hundreds of trades per month. A fixed 0.25 PSI threshold on a 50-trade sample is statistically meaningless. Their Table 4 shows the power comparison: with n = 100, m = 200 and a mean shift of ½ standard deviation, `PSI > 0.10` has power 0.996 but `PSI > 0.25` has power only **0.835**; with n = 200, m = 400 the figures are 0.997 vs 0.720 — i.e. **the 0.25 threshold loses substantial detection power**, while 0.10 over-triggers.

**Also note their closing observation:** *"and variance reduce to zero as n and m increase, which means that PSI converges to a point mass at zero."* PSI is **not** a fixed-population constant — it is a sample statistic whose null distribution shrinks with sample size.

### 1.4.2 Known limitations of PSI (for honest documentation)

From Yurdakul & Naranjo and du Pisanie et al.:
1. **No sampling distribution** under the classical rule of thumb — the 0.1/0.25 numbers have "no known properties" and are not tied to type I / type II error rates.
2. **Sample-size dependent** — the same true distribution shift yields different PSI at different n (Table 2 above).
3. **Bin-count dependent** — B = 10 vs B = 20 roughly doubles the null PSI.
4. **Binning is base-population-dependent**, so PSI is only symmetric if bin edges are pre-fixed, which in practice they are not.
5. **Bin-permutation invariant** — PSI cannot distinguish "the distribution shifted slightly" from "bins were relabelled"; it ignores the ordering/geometry of the underlying variable. (Wasserstein distance does not have this flaw — see §2.5.)
6. **Zero-bin handling is arbitrary** and materially affects the result.
7. du Pisanie et al. note the underlying data are typically *"protected by regulations"*, which is why the literature relies on simulated examples.

## 1.5 Characteristic Stability Index (CSI) — definition and difference from PSI

**Definition.** CSI is PSI computed **per input variable/characteristic** rather than on the model's score distribution. It localises *which* feature drifted; PSI on the score tells you *that* the model's output distribution moved.

**Formula (R `scorecard` package, `perf_psi` documentation):**
```
CSI = Σ ( Actual% − Expected% ) × score
```
URL: https://search.r-project.org/CRAN/refmans/scorecard/html/perf_psi.html
The same page gives PSI as `PSI = Σ((Actual% − Expected%) * (ln(Actual%/Expected%)))` and states: *"`perf_psi` calculates population stability index (PSI) for total credit score and **Characteristic Stability Index (CSI) for variables**."* The function's own disambiguation rule: *"`threshold_variable`: Integer. Defaults to 20. **If the number of unique values > threshold_variable, the provided score will be counted as total credit score, otherwise, it is variable score.**"* — i.e. the library auto-detects PSI vs CSI by cardinality.

⚠️ **Formula caveat:** the R `scorecard` documentation renders CSI as `Σ(Actual% − Expected%) × score`, which is dimensionally odd (it multiplies a proportion difference by a raw score, not by a log ratio) and looks like a documentation error or a WOE/points-weighted variant. **Treat that exact expression as UNVERIFIED / likely a doc typo.** The *concept* (per-variable PSI-style divergence) is solid and is what SAS implements.

**SAS's naming is different but the concept is identical.** SAS Model Manager does **not** use the term "CSI". It splits the two charts:
- **"Characteristic"** = *"The Input Variable Characteristic chart detects and quantifies the shifts in the distribution of variable values in the input data over time."* → this is CSI.
- **"Stability"** = *"The Output Variable Stability chart evaluates changes in the distribution of scored output variable values as models score data over time"* → this is PSI.

Verbatim framing: *"Together, the Input Variable Characteristic and Output Variable Stability charts detect and quantify shifts that can occur in the distribution of model performance data, scoring input data, and the scored output data that a model produces."* And: *"To find shifts, **the first time point in the input data is set as the baseline** and the distributions of the variables in subsequent data time points are compared to the baseline data time point."*

**Also called:** "Variable Stability Index"; the R `creditmodel` package exposes `get_psi_all` (https://search.r-project.org/CRAN/refmans/creditmodel/html/get_psi_all.html) and the `OptimalBinningWoE` package exposes `obwoe_psi` (https://rdrr.io/cran/OptimalBinningWoE/man/obwoe_psi.html) — both per-variable PSI implementations. **UNVERIFIED:** I did not find a source that uses the literal acronym "CSI" outside the SAS-adjacent / R-scorecard ecosystem; it is not a term used by US regulators.

**Practical design for an EA vendor:** compute CSI per *model input* (e.g. spread at entry, ATR percentile, session/hour-of-day bucket, day-of-week, volatility regime, symbol mix, account leverage bucket) and PSI on the *score/signal* distribution (or on the trade-outcome distribution). CSI tells you *why*; PSI tells you *that*.

---

# 2. KL Divergence and Other Drift Metrics

## 2.1 KL divergence — formula and properties

```
D_KL(P ‖ Q) = Σ_x P(x) · log( P(x) / Q(x) )
```

**Verified primary source:** SciPy `scipy.stats.entropy` — https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.entropy.html
> "If *qk* is not None, then compute the relative entropy `D = sum(pk * log(pk / qk))`. **This quantity is also known as the Kullback-Leibler divergence.**"
> "*base* : float, optional — The logarithmic base to use, **defaults to `e` (natural logarithm)**."
> "The choice of base determines the choice of units; e.g., `e` for nats, `2` for bits, etc."

Textbook: Cover, T. M. and Thomas, J. A., *Elements of Information Theory* (Wiley) — cited as reference [2] on the SciPy page. ISBN/Wiley series; the standard citation.

**Four properties that matter operationally:**

1. **Asymmetric.** `D_KL(P‖Q) ≠ D_KL(Q‖P)`. Stated in Yurdakul & Naranjo §2: *"it is technically not a distance measure because the definition is not symmetric, ie, D_KL(q(x) | p(x)) ≠ D_KL(p(x) | q(x))"* — https://files.wmich.edu/s3fs-public/attachments/u730/2022/PSIfinal.pdf
2. **Unbounded above.** Unlike JS divergence there is no upper bound; a single bin where Q ≈ 0 and P > 0 sends D_KL → ∞.
3. **Absolute continuity requirement.** D_KL is finite only if `Q(x) = 0 ⟹ P(x) = 0`. In practice zero bins must be smoothed — the same problem as PSI (§1.3), with the same workarounds.
4. **Units depend on log base** (nats for ln, bits for log₂) — identical issue to PSI (§1.1).

## 2.2 PSI ↔ KL divergence — the claim VERIFIED (with a correction to the brief)

**The claim in the brief is CORRECT.** PSI in the `(A−E)·ln(A/E)` form **is exactly** `KL(A‖E) + KL(E‖A)`, the symmetric **Jeffreys divergence**.

**Algebra (verified against Yurdakul & Naranjo §2, who perform exactly this derivation):**

```
PSI = Σ_i (A_i − E_i) · ln(A_i / E_i)

    = Σ_i A_i·ln(A_i/E_i)  −  Σ_i E_i·ln(A_i/E_i)

    = Σ_i A_i·ln(A_i/E_i)  +  Σ_i E_i·ln(E_i/A_i)        [since −ln(x) = ln(1/x)]

    = KL(A ‖ E)  +  KL(E ‖ A)                              ∎
```

Yurdakul & Naranjo's own rendering of the same result:
> "However, we can easily obtain a symmetric measure of divergence by defining `D(p,q) = D_KL(q|p) + D_KL(p|q)` = … `= Σ (p(x_i) − q(x_i))(ln p(x_i) − ln q(x_i))`, **which brings us to the formula for the PSI.**"

**Naming.** This quantity is the **Jeffreys divergence** (also "J-divergence", "symmetric KL", "information divergence"). Kullback himself defined it for multinomials as `J(1,2) = I(1,2) + I(2,1)` (Kullback 1978, ch. 6, as reported by Yurdakul & Naranjo, their eq. 2.2).

⚠️ **Terminology trap:** "information radius" is sometimes used for the Jeffreys divergence and sometimes for the **Jensen-Shannon** divergence. They are different quantities (JS is bounded, Jeffreys is not). **Always spell out the formula rather than relying on the name.**

**Correction to the brief's framing — PSI is NOT "bounded-ish":**

- PSI **is** bounded **below** by 0, with `PSI = 0` iff `A_i = E_i` for all i. (SAS: *"If the baseline input data set and the subsequent input data sets have identical distributions for a variable, the variable's population stability index (PSI) is equal to 0."*)
- PSI is **NOT bounded above.** It inherits KL's unboundedness. If a bin has `E_i → 0` with `A_i > 0`, the `ln(A_i/E_i)` term diverges.
- Therefore the correct statement is: **PSI is symmetric and non-negative, but unbounded above.** It is preferred over KL in practice because it is **symmetric** (order of base vs. target doesn't flip the sign of the answer) and because its **0.1/0.25 conventions are widely understood** — *not* because it is bounded. JS divergence (§2.3) is the one that is genuinely bounded.

**Second caveat — PSI's symmetry is conditional.** Yurdakul & Naranjo: *"the PSI is symmetric **under the assumption that cutoff values are predetermined**. However, in practice that is not true, since the cutoff points correspond to the percentiles of the base population… If the base and target populations switch roles, then this changes the cutoff points and consequently the PSI."* So PSI is algebraically symmetric **given fixed bins**, but operationally asymmetric **because binning is base-dependent**. Freeze your bin edges from the development sample and never rebin on the target sample.

## 2.3 Jensen-Shannon divergence (JSD)

```
M   = ½ (P + Q)                                   [the mixture]
JSD(P ‖ Q) = ½ · KL(P ‖ M) + ½ · KL(Q ‖ M)
```

**Verified source:** NannyML, "Presenting Univariate Drift Detection Methods" — https://nannyml.readthedocs.io/en/stable/how_it_works/univariate_drift_detection.html
> "Jensen-Shannon Divergence is defined as: `D_JS(P||Q) = ½ [ D_KL(P || ½(P+Q)) + D_KL(Q || ½(P+Q)) ]` … **Jensen-Shannon Distance is the square root of Jensen-Shannon divergence and is a proper distance metric.**"
> Also: *"It is based on Kullback-Leibler divergence, but is created in such a way that it is **symmetric and ranges between 0 and 1**."*

**Properties:**
- **Symmetric**: `JSD(P‖Q) = JSD(Q‖P)`.
- **Bounded**: `0 ≤ JSD ≤ ln 2` (nats) or `0 ≤ JSD ≤ 1` (log₂). NannyML's "ranges between 0 and 1" statement reflects the log₂ / distance convention.
- **√JSD is a true metric** (satisfies triangle inequality) — this is the "Jensen-Shannon distance".
- **Always finite** — because M is a mixture, `M(x) = 0` requires both `P(x) = 0` and `Q(x) = 0`, so the zero-bin problem that afflicts KL and PSI does not arise. **This is JSD's main practical advantage.**

Original paper: **Lin, J. (1991), "Divergence measures based on the Shannon entropy," *IEEE Transactions on Information Theory* 37(1), 145–151.** DOI: 10.1109/18.61115 — **UNVERIFIED** (I did not fetch the IEEE page; the citation is standard but I did not confirm the DOI resolves).

## 2.4 Kolmogorov-Smirnov (KS) test

```
Two-sample KS statistic:   D = sup_x | F₁(x) − F₂(x) |
```

**Verified source:** NannyML (same URL as §2.3):
> "The Kolmogorov-Smirnov Test is a two-sample, non-parametric statistical test. It is used to test for the equality of one-dimensional continuous distributions. The test outputs the test statistic, called D-statistic, and an associated p-value. **The test statistic is the maximum distance of the cumulative distribution functions (CDF) of the two samples.**"
> "The D-statistic is robust to small changes in the data, it is easy to interpret and **falls into 0-1 range**."

SciPy: `scipy.stats.ks_2samp` — https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ks_2samp.html

**Practical problems:**
- **Sensitive to ANY distributional difference** (location, scale, shape) but gives no indication of *which* or *how much* — D is a single sup-norm number.
- **p-value depends on sample size.** With large N, trivially small drift is "statistically significant". With small N, real drift is missed. This is exactly why NannyML's default KS threshold is **not** a p-value but a standard-deviation band (§3).
- **NannyML's implementation detail:** *"It can calculate the KS test with two methods… The first approach stores and uses the reference data as-is, while the second splits the continuous feature into **quantile bins** and uses the bin edges and frequencies for the calculation. **By default, NannyML employs the first method if the reference data has fewer than 10,000 rows.**"*

Original references: Kolmogorov (1933); Smirnov (1948). **UNVERIFIED** — exact DOIs not fetched.

## 2.5 Wasserstein / Earth Mover's Distance (EMD)

```
W_p(P,Q) = ( ∫₀¹ | F_P⁻¹(t) − F_Q⁻¹(t) |^p dt )^{1/p}

W₁ (p=1, the earth-mover distance), 1-D case:

W₁(P,Q) = ∫_{-∞}^{+∞} | F_P(x) − F_Q(x) | dx
```

**Verified source:** SciPy `scipy.stats.wasserstein_distance` — https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.wasserstein_distance.html
> "Compute the **Wasserstein-1 distance** between two 1D discrete distributions. The Wasserstein distance, also called the **Earth mover's distance** or the **optimal transport distance**, is a similarity metric between two probability distributions."
> Definition given: `l₁(u,v) = inf_{π ∈ Γ(u,v)} ∫∫ |x−y| dπ(x,y)`
> "If U and V are the respective CDFs of u and v, this distance also equals to: **`l₁(u,v) = ∫_{-∞}^{+∞} |U−V|`**"
> Reference [3]: Ramdas, Garcia, Cuturi, "On Wasserstein Two Sample Testing and Related Families of Nonparametric Tests" (2015), arXiv:1509.02237 — https://arxiv.org/abs/1509.02237

**NannyML's description** (same URL as §2.3):
> "Wasserstein distance can be thought of as the minimum amount of work needed to transform one distribution into the other. Informally, if the PDF of each distribution is imagined as a pile of dirt, the Wasserstein distance is the amount of work it would take to transform one pile of dirt into the other (which is why it is also called the earth mover's distance)."
> `W₁(X_i^P, X_i^Q) = ∫_ℝ | F̂_P(x) − F̂_Q(x) | dx`

**Why it matters for trading-system monitoring:**
- **True metric** (symmetry + triangle inequality).
- **Respects the geometry of the underlying space** — unlike KL/JS/PSI, which are bin-permutation invariant. Moving 1% of mass from bin 3 to bin 4 scores differently from moving it from bin 3 to bin 10. For a trading feature like "entry spread in pips", this is the correct behaviour.
- **Has meaningful units** — same units as the variable (pips, points, bps, seconds). A W₁ of 0.4 pips is directly interpretable; a PSI of 0.18 is not. **This makes Wasserstein the best choice for threshold-setting on trading features.**
- **No binning required** — avoids the whole bin-count / bin-edge / zero-bin problem.

**Verified as Evidently's default for numerical drift on large data** — see §3.1.

Original references: Villani, *Optimal Transport: Old and New*; Rubner, Tomasi & Guibas (1998), "A Metric for Distributions with Applications to Image Databases," ICCV — **UNVERIFIED** (not fetched). Arjovsky, Chintala & Bottou (2017), "Wasserstein GAN," arXiv:1701.07875 — **UNVERIFIED**.

## 2.6 Streaming / sequential drift detectors

### DDM — Drift Detection Method
**Gama, J., Medas, P., Castillo, G., Rodrigues, P. (2004), "Learning with Drift Detection," SBIA 2004, pp. 286–295.**
DOI: 10.1007/978-3-540-28648-6_20 — **UNVERIFIED** (DOI resolution not confirmed).

**Verified default parameters** — River docs: https://riverml.xyz/latest/api/drift/binary/DDM/
```
Warning zone:   if  p_i + s_i ≥ p_min + w_l · s_min
Change detected: if  p_i + s_i ≥ p_min + d_l · s_min
```
| Parameter | Default | River's description |
|---|---|---|
| `warm_start` | `30` | minimum samples before change can be detected |
| `warning_threshold` (w_l) | `2.0` | *"The default value gives 95% of confidence level to the warning assessment."* |
| `drift_threshold` (d_l) | `3.0` | *"The default value gives a 99% of confidence level to the drift assessment."* |

where `p_min` / `s_min` are the error rate and standard deviation recorded at the point where `(p_i + s_i)` was minimised. Input is a stream of bits (1 = error, 0 = correct).

**This is directly applicable to EA monitoring**: feed 1 for a losing trade / rule violation / slippage breach, 0 for normal, and DDM gives you a warning at 2σ and a drift alarm at 3σ with no distributional assumptions.

### ADWIN — Adaptive Windowing
**Bifet, A. and Gavaldà, R. (2007), "Learning from Time-Changing Data with Adaptive Windowing," SIAM International Conference on Data Mining (SDM 2007), pp. 443–448.**
DOI: 10.1137/1.9781611972771.42 — **UNVERIFIED** (DOI not confirmed; the SIAM proceedings page is the citable source).

**Verified default parameters** — River docs: https://riverml.xyz/latest/api/drift/ADWIN/
> "ADWIN (ADaptive WINdowing) is a popular drift detection method with **mathematical guarantees**. ADWIN efficiently keeps a variable-length window of recent items; such that it holds that there has no been change in the data distribution. This window is further divided into two sub-windows (W₀, W₁)… ADWIN compares the average of W₀ and W₁ to confirm that they correspond to the same distribution. **Concept drift is detected if the distribution equality no longer holds.** Upon detecting a drift, W₀ is replaced by W₁ and a new W₁ is initialized. ADWIN uses a significance value δ ∈ (0,1) to determine if the two sub-windows correspond to the same distribution."

| Parameter | Default | Meaning |
|---|---|---|
| `delta` | `0.002` | significance value (δ) |
| `clock` | `32` | check for change every 32 points (1 = every point) |
| `max_buckets` | `5` | buckets per size before merging (ADWIN2 compression) |
| `min_window_length` | `5` | minimum sub-window size evaluated |
| `grace_period` | `10` | no detection until this many points arrive |

The change-detection bound is **Hoeffding-bound based** (that is the source of the "mathematical guarantees"). Note: the default δ = 0.002 is *not* 0.05 — ADWIN is tuned for low false-positive rates in long streams.

### Page-Hinkley / CUSUM
**Page, E. S. (1954), "Continuous Inspection Schemes," *Biometrika* 41(1–2), 100–115.**
DOI: https://doi.org/10.1093/biomet/41.1-2.100 (Oxford Academic returned **403** to automated fetch, but the DOI and article page are correct: https://academic.oup.com/biomet/article-abstract/41/1-2/100/349763) — **citation verified, page content not fetched.**

**Verified default parameters** — River docs: https://riverml.xyz/latest/api/drift/PageHinkley/
> "This detector implements the **CUSUM control chart** for detecting changes. This implementation also supports the **two-sided Page-Hinkley test** to detect increasing and decreasing changes in the mean of the input values."

| Parameter | Default | Meaning |
|---|---|---|
| `min_instances` | `30` | minimum observations before detection |
| `delta` | `0.005` | delta factor (the magnitude of change to tolerate) |
| `threshold` | `50.0` | change detection threshold (**λ**) |
| `alpha` | `0.9999` | forgetting factor weighting observed value vs. mean |
| `mode` | `'both'` | `'up'`, `'down'`, or `'both'` |

River cites both Page (1954) and Sebastião & Fernandes (2017), "Supporting the Page-Hinkley test with empirical mode decomposition for change detection," ISMIS 2017, pp. 492–498.

**Page-Hinkley statistic** (standard form; River implements the CUSUM equivalent):
```
m_T = Σ_{t=1}^{T} ( x_t − x̄_t − δ )        [cumulative deviation]
M_T = max_{t≤T} m_t
PH_T = M_T − m_T                            [detects an INCREASE in mean]
Alert when PH_T > λ
```
With `alpha` as a forgetting factor this becomes a *fading-mean* CUSUM suitable for non-stationary streams. **Page-Hinkley issues no warning zone — only detections.**

### KSWIN
**Raab, C., Heusinger, M., Schleif, F.-M. (2020), "Reactive Soft Prototype Computing for Concept Drift Streams," Neurocomputing.** River implements it: https://riverml.xyz/latest/api/drift/KSWIN/ — **original citation UNVERIFIED** (not fetched).

### Other River detectors (available, defaults not individually verified)
`EDDM`, `FHDDM`, `HDDMA`, `HDDMW` (all under `river.drift.binary`) — https://riverml.xyz/latest/api/overview/
**scikit-multiflow is deprecated** and superseded by River. **UNVERIFIED:** exact deprecation notice text.

## 2.7 Maximum Mean Discrepancy (MMD)

**Gretton, A., Borgwardt, K., Rasch, M., Schölkopf, B., Smola, A. (2012), "A Kernel Two-Sample Test," *Journal of Machine Learning Research* 13, 723–773.**
URL: https://jmlr.org/papers/v13/gretton12a.html — **UNVERIFIED** (not fetched).

MMD measures the distance between kernel mean embeddings of two distributions in an RKHS; it is a genuine metric and, unlike KS, is sensitive to *all* moments (not just the CDF sup-norm) and works in multivariate settings. Implemented in `alibi-detect` and NannyML (multivariate). **alibi-detect default p-value threshold = 0.05 — UNVERIFIED**; https://docs.seldon.ai/alibi-detect/api-reference/cd/mdd returned **404** and the older https://docs.seldon.io/projects/alibi-detect/ mirror was not successfully fetched.

---

# 3. Open-Source Drift Monitoring Tools — Shipped Defaults

## 3.1 Evidently AI

**Current docs (verified, fetched):** https://docs.evidentlyai.com/metrics/explainer_drift
**Legacy docs (verified, fetched):** https://docs-old.evidentlyai.com/reference/data-drift-algorithm.md

**Defaults, verbatim from the current docs:**

For **small data, ≤ 1000 observations** in the reference dataset:
- Numerical (n_unique > 5): **two-sample Kolmogorov-Smirnov test**
- Categorical, or numerical with n_unique ≤ 5: **chi-squared test**
- Binary categorical (n_unique ≤ 2): **proportion difference test based on Z-score**
> "All tests use a **0.95 confidence level** by default. Drift score is P-value. **(=< 0.05 means drift).**"

For **larger data, > 1000 observations**:
- Numerical (n_unique > 5): **Wasserstein Distance**
- Categorical, or numerical with n_unique ≤ 5: **Jensen–Shannon divergence**
> "All metrics use a **threshold = 0.1** by default. Drift score is distance/divergence. **(>= 0.1 means drift).**"

**Dataset-level drift:**
> "For example, you can declare dataset drift if 50% of all features (columns) drifted."
The legacy docs state explicitly: *"**The default in `DatasetDriftPreset()` is 0.5**"* (i.e. `drift_share = 0.5` — more than 50% of columns must drift for the dataset to be flagged).

**Text / embeddings drift (domain classifier):**
> "The default for **larger data with > 1000 observations** detects drift if the **ROC AUC > 0.55**."
> For small data: drift if ROC AUC exceeds the random classifier's ROC AUC at the **95th percentile** (computed by repeating the calculation 1000 times with randomly assigned target class probabilities).

**Also supported (user-selectable, not default):** PSI, K-L divergence, Jensen-Shannon distance, Wasserstein distance, custom tests. Note that **Evidently does *not* ship PSI as a default** — this is worth knowing if you intend to claim "industry-standard PSI monitoring". You can switch everything to PSI with `DataDriftPreset(method="psi")` and set thresholds per column type, e.g. `DataDriftPreset(cat_method="psi", cat_threshold="0.3")` — *"if PSI is ≥ 0.3 for any categorical column, drift will be detected for that column."*

**Full default method/threshold table (verified, from https://docs.evidentlyai.com/metrics/customize_data_drift):**

| StatTest | Applies to | Drift score | Default threshold |
|---|---|---|---|
| `ks` (Kolmogorov–Smirnov) | numerical only. **Default for numerical if ≤ 1000 objects** | `p_value`; drift when `p_value < threshold` | **0.05** |
| `chisquare` | categorical. **Default for categorical with > 2 labels if ≤ 1000 objects** | `p_value` | **0.05** |
| `z` (Z-test) | categorical. **Default for binary data if ≤ 1000 objects** | `p_value` | **0.05** |
| `wasserstein` | numerical. **Default for numerical if > 1000 objects** | distance | **0.1** |
| `psi` | categorical (also usable on numerical) | divergence | **0.1** |
| `jensenshannon` | categorical. **Default for categorical if > 1000 objects** | distance | **0.1** |
| `kl_div` | categorical | divergence | **0.1** |
| `hellinger` | categorical | distance | **0.1** |
| `ed` (energy distance) | numerical | distance | **0.1** |
| `empirical_mmd` | numerical | distance | **0.1** |
| `TVD` (total variation distance) | categorical | distance | **0.1** |
| `cramer_von_mises` | numerical | distance | **0.1** |
| `g-test` | categorical | p_value | 0.05 |
| `fisher_exact` | categorical (binary) | p_value | 0.05 |

**`drift_share` default = 0.5** (dataset-level drift declared if >50% of columns drift), verified verbatim: *"**Dataset drift share**. You can set the share of drifting columns that signals dataset drift (**default: 0.5**)."*

## 3.2 NannyML

**Verified sources:**
- Univariate drift calculator API: https://nannyml.readthedocs.io/en/v0.10.1/nannyml/nannyml.drift.univariate.calculator.html
- How it works — methods: https://nannyml.readthedocs.io/en/stable/how_it_works/univariate_drift_detection.html
- Thresholds: https://nannyml.readthedocs.io/en/stable/how_it_works/thresholds.html

**Supported methods, verbatim from the API docs:**
> "Supported drift detection methods are: Kolmogorov-Smirnov statistic (continuous); Wasserstein distance (continuous); Chi-squared statistic (categorical); L-infinity distance (categorical); Jensen-Shannon distance; Hellinger distance."

**DEFAULT METHOD = `jensen_shannon` for BOTH categorical and continuous columns** (`categorical_methods: default=['jensen_shannon']`, `continuous_methods: default=['jensen_shannon']`).

**DEFAULT THRESHOLDS, verbatim:**
```
{
    'kolmogorov_smirnov': StandardDeviationThreshold(std_lower_multiplier=None),
    'jensen_shannon':     ConstantThreshold(upper=0.1),
    'wasserstein':        StandardDeviationThreshold(std_lower_multiplier=None),
    'hellinger':          ConstantThreshold(upper=0.1),
    'l_infinity':         ConstantThreshold(upper=0.1)
}
```
> "The chi2 method does not support custom thresholds for now… It is currently using **p-values** for thresholding."

**`StandardDeviationThreshold` defaults:** `std_lower_multiplier = 3`, `std_upper_multiplier = 3`. It computes the mean and standard deviation of the metric **on the reference data across chunks**, then sets `upper = mean + 3σ` and `lower = mean − 3σ`. Verbatim:
> "The `StandardDeviationThreshold` class will use the mean of the data it is given as a baseline. It will then add the standard deviation of the given data, scaled by a multiplier, to that baseline to calculate the upper threshold value."

**Default computation params:**
```
{
  'kolmogorov_smirnov': {'calculation_method': 'auto', 'n_bins': 10000},
  'wasserstein':        {'calculation_method': 'auto', 'n_bins': 10000}
}
```
> "auto: Use `exact` for reference data smaller than 10 000 rows, `estimated` for larger."
> "Bins are **quantile-based for Kolmogorov-Smirnov** and **equal-width based for Wasserstein**."

**Binning for JS / Hellinger:** *"the binning is done using **Doane's formula** from numpy. If a continuous feature has a relatively low amount of unique values, meaning that unique values are less than 10% of the reference dataset size up to a maximum of 50, each value becomes a bin. **If any data from the chunk sample are outside the range of the previous bins, then a new bin is created for them. The new bins' relative frequency for the reference sample is set to 0.**"* — note this is a *different* zero-bin strategy from PSI's 0.0001 replacement (the reference gets 0, which is well-defined for JS/Hellinger but not for KL/PSI).

**NannyML Cloud covariate-shift settings** (different product, UI-configurable): https://docs.nannyml.com/cloud/v0.24.2/product-tour/model-side-panel/model-settings/covariate-shift-settings — page loads but content was truncated; **specific Cloud defaults UNVERIFIED.**

## 3.3 River

Docs: https://riverml.xyz/ (current version referenced in fetched pages: **0.26.1**)

**Drift detectors available** (`river.drift`):
`ADWIN`, `KSWIN`, `PageHinkley`, `DummyDriftDetector`, `NoDrift`, `DriftRetrainingClassifier`
**Binary/classification-performance detectors** (`river.drift.binary`):
`DDM`, `EDDM`, `FHDDM`, `HDDMA`, `HDDMW`

**Verified defaults** (see §2.6 for the DDM / ADWIN / PageHinkley parameter tables).

## 3.4 alibi-detect (Seldon)

Docs: https://docs.seldon.ai/alibi-detect/ — the MMD API page https://docs.seldon.ai/alibi-detect/api-reference/cd/mdd returned **404**, and https://docs.seldon.io/projects/alibi-detect/ was not successfully fetched.
**Detectors (from search results, not primary-verified):** MMD (Maximum Mean Discrepancy), learned-kernel MMD, classifier-based drift, LSDD (Least-Squares Density Difference), CVM, FET, chi-squared, KS.
**Default p-value threshold 0.05 — UNVERIFIED.** Do not cite without checking https://docs.seldon.ai/alibi-detect/ directly.

## 3.5 Others
- **Frouros, TorchDrift, Deepchecks** — exist; **defaults UNVERIFIED**.
- **WhyLabs / Arize / Fiddler / Datadog ML monitoring** — commercial; **publicly documented default thresholds UNVERIFIED** (these vendors typically let users configure thresholds rather than shipping a single default).

## 3.6 Summary table of shipped defaults

| Tool | Numerical default | Categorical default | Default threshold | Dataset-level rule |
|---|---|---|---|---|
| **Evidently** (≤1000 obs) | KS test | chi² test | p ≤ 0.05 | `drift_share` 0.5 |
| **Evidently** (>1000 obs) | Wasserstein | Jensen-Shannon | **0.1** | `drift_share` 0.5 |
| **Evidently** (text/embeddings) | domain classifier ROC AUC | — | **0.55** (>1000 obs) | — |
| **NannyML** | **Jensen-Shannon** | **Jensen-Shannon** | **0.1** (constant) | per-method |
| **NannyML** | KS, Wasserstein | chi², L-infinity, Hellinger | mean ± 3σ (KS, Wasserstein); 0.1 (Hellinger, L∞) | per-method |
| **River** | user-supplied stream | — | ADWIN δ=0.002; DDM 2σ/3σ; PH λ=50, δ=0.005 | — |

**Notable convergence:** three independent tools (Evidently, NannyML, and the PSI literature) all land on **0.1** as the default "something changed" threshold. That is a defensible, citable default to adopt.

---

# 4. Model Risk Management: SR 11-7 → SR 26-2

## 4.1 Status: SR 11-7 is RESCINDED (verified 2026)

**SR 26-2, "Revised Guidance on Model Risk Management," 17 April 2026.**
- Letter: https://www.federalreserve.gov/supervisionreg/srletters/sr2602.htm
- Attachment (full guidance text): https://www.federalreserve.gov/supervisionreg/srletters/SR2602a1.pdf
- Listed on the Fed's 2026 SR letters index: https://www.federalreserve.gov/supervisionreg/srletters/2026.htm

**Verbatim from SR 26-2:**
> "The Board of Governors of the Federal Reserve System, Office of the Comptroller of the Currency (OCC), and Federal Deposit Insurance Corporation (FDIC) (the 'agencies') are issuing the attached *Revised Guidance on Model Risk Management*, **which supersedes and replaces SR letter 11-7, *Guidance on Model Risk Management* (issued April 4, 2011)** and SR letter 21-8, *Interagency Statement on Model Risk Management for Bank Systems Supporting Bank Secrecy Act/Anti-Money Laundering Compliance* (issued April 9, 2021)."

> "**Applicability:** This letter is expected to be most relevant to banking organizations with **over $30 billion in total assets** regulated by the Federal Reserve."

**SR 11-7 URL status (verified):**
- `https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm` → **HTTP 404**
- `https://www.federalreserve.gov/supervisionreg/srletters/sr1107a1.pdf` → **HTTP 404**

The 2011 PDF is still cited in academic bibliographies (Yurdakul & Naranjo cite `sr1107a1.pdf`), and third-party archives exist, but the Fed has removed it from its live site. **Do not link to the dead federalreserve.gov URL in client-facing material.**

**OCC counterpart:** OCC Bulletin 2026-13, "Model Risk Management: Revised Guidance" — https://www.occ.treas.gov/news-issuances/bulletins/2026/bulletin-2026-13.html
OCC news release: https://www.occ.gov/news-issuances/news-releases/2026/nr-occ-2026-29.html
⚠️ **Both OCC URLs repeatedly timed out / connection-failed to automated retrieval** (the `occ.gov` host was intermittently unreachable; `occ.treas.gov` returned a connection failure). They appear in search-engine results with the correct titles, and SR 26-2 independently confirms the joint Fed/OCC/FDIC issuance. **The OCC documents are therefore verified as existing but their full text is UNVERIFIED** — check manually before quoting.

### The 2025–2026 timeline (as best verified)

| Date | Event | Verification |
|---|---|---|
| Apr 2011 | SR 11-7 / OCC Bulletin 2011-12 issued | Verified via SR 26-2's supersession clause |
| May 2023 | PRA publishes **PS6/23 / SS1/23**, "Model risk management principles for banks"; effective **17 May 2024** | **Verified** — https://www.bankofengland.co.uk/prudential-regulation/publication/2023/may/model-risk-management-principles-for-banks |
| 2025 | Reports that the Fed/OCC might revise or remove the 2011 model risk guidance; OCC proposal to revise Bulletin 2011-12 | **PARTIALLY UNVERIFIED** — I could not retrieve a primary 2025 Federal Register notice or OCC bulletin confirming the exact proposal text/date. A Federal Register document from **1 May 2025** (Vol. 90, No. 83) appeared in search results (https://www.govinfo.gov/content/pkg/FR-2025-05-01/html/2025-07548.htm) but I did not fetch and confirm its content. **Do not assert the 2025 proposal's specifics without checking.** |
| **17 Apr 2026** | **SR 26-2 issued; SR 11-7 and SR 21-8 superseded and replaced.** Applicability narrowed to banking organizations **> $30bn** total assets. | **VERIFIED** (primary source fetched, full text extracted) |
| 2026 | OCC Bulletin 2026-13 issued in parallel | Existence verified via search; **text UNVERIFIED** (host unreachable) |

### The $30 billion threshold — the single most important practical change

Verbatim from SR 26-2 §II:
> "This guidance is expected to be most relevant to banking organizations with **over $30 billion in total assets**. Models used by banking organizations with total assets of **$30 billion or less typically are subject to internal risk management and governance practices appropriate for the size and risk profile** of these banking organizations, and **generally excluding them from this guidance** is consistent with a tailored supervisory approach. However, in some situations, this guidance also may be relevant to banking organizations with total assets of $30 billion or less that have significant exposure to model risk…"

And the enforcement posture, verbatim from §I:
> "**This guidance does not set forth enforceable standards or prescriptive requirements; accordingly, non-compliance with this guidance will not result in supervisory criticism against a banking organization.**"
> (footnote 1) "…However, **supervisory action may result for any violations of law or unsafe or unsound practices stemming from insufficient management of model risk.**"

**This is a significant softening.** SR 11-7 was also guidance (not a rule), but SR 26-2 explicitly disclaims supervisory criticism for non-compliance while preserving action for unsafe/unsound practices. For a vendor, this means: **the commercial pressure to demonstrate MRM discipline now comes from the client's own risk function and auditors, not from a checklist an examiner will run.** Position accordingly.

## 4.2 The three core elements

The brief asks about SR 11-7's three elements. SR 26-2 **restructures** them into five sections. Both framings are given, because the SR 11-7 vocabulary ("three pillars", "effective challenge", "outcomes analysis") is still what bank risk teams speak.

### SR 11-7 (2011) — the legacy three-element framework
1. **Model development, implementation and use**
2. **Model validation** — comprising (a) evaluation of conceptual soundness, (b) ongoing monitoring, (c) outcomes analysis
3. **Governance, policies and controls**

### SR 26-2 (2026) — the current structure
| SR 26-2 Section | Title |
|---|---|
| **III** | Overview of Model Risk and Model Risk Management |
| **IV** | **Model Development and Model Use** |
| **V** | **Model Validation and Monitoring** — sub-parts: *Conceptual Soundness*, **Outcomes Analysis**, **Ongoing Model Monitoring** |
| **VI** | **Governance and Controls** — sub-parts: *Roles and Responsibilities*, *Model Inventory*, *Documentation* |
| **VII** | Vendor and Other Third-Party Products |

**New in SR 26-2 — a formal risk-tiering vocabulary.** Verbatim from §III:
> "**Model risk** refers to the potential for adverse financial consequences associated with models, which may result from decisions made based on model output. Model risk is influenced by a model's **inherent risk, exposure, purpose, and use**."
> "A model's **inherent risk** reflects several fundamental factors, such as the assumptions made in developing the model, the model's complexity, the quality of inputs for the model, and data constraints. Inherent risk increases with model complexity and the criticality or number of assumptions necessary."
> "**Model exposure** refers to the significance of the model output to a banking organization's business decisions… Model exposure can be quantitatively measured (e.g., by portfolio size)."
> "**Model purpose** is a qualitative consideration… models developed to help meet regulatory requirements or manage a banking organization's financial risk exposures are generally considered to be of greater risk than models that are not used for such purposes."
> "Model purpose, together with model exposure, determines **model materiality**."
> "**The overall magnitude of model risk reflects a model's inherent risk in the context of model materiality (i.e., model exposure and purpose).** However, even a fundamentally sound model producing accurate outputs consistent with the model's design objective can exhibit high model risk if it is **misapplied or misused**."
> "Sound practice involves assessing model risk both individually and in aggregate. **Aggregate risk** reflects interactions and dependencies among models; reliance on common assumptions, data, or methodologies; and any other factors that could adversely affect several models and their outputs simultaneously."

**"Aggregate risk" is directly relevant to an EA vendor** selling multiple strategies that share market-data feeds, broker connectivity or signal logic — SR 26-2 explicitly asks banks to consider correlated model failure.

## 4.3 "Ongoing monitoring" and "Outcomes analysis" — exact language

Both concepts survived the 2026 rewrite, and the key sentences are **nearly verbatim from SR 11-7**.

### Outcomes Analysis (SR 26-2 §V, "Components of Model Validation")

> "**Outcomes analysis compares model outputs to corresponding real-world outcomes to assess model performance relative to model objectives and business use.** Outcomes analysis and other elements of the validation process may identify **material errors or persistent deviations outside of the banking organization's established performance thresholds**. In such cases, **model adjustment, recalibration, or redevelopment may be warranted**."
>
> "Outcomes analysis can take many forms, including **testing conducted during model development, reports or analysis performed as part of ongoing monitoring, or standalone activities such as back-testing or outlier analysis**. A banking organization's approach depends on the model's objectives, methodology, and data availability. As part of model validation, sound practice involves reviewing outcomes analysis to evaluate the reasonableness and appropriateness of the results, with additional analysis and testing, if warranted. **When a model's design relies substantially on expert judgment, quantitative outcomes analysis helps to evaluate the quality of that judgment.**"

**Three things to note:**
1. **Back-testing is explicitly named** as a form of outcomes analysis. This is your hook for live-vs-backtest reconciliation (§5).
2. The guidance references **"the banking organization's established performance thresholds"** — i.e. the bank must *define its own* thresholds. SR 26-2 does not supply numbers. This is why PSI's 0.1/0.25 matters: it is the de facto industry answer to a question the regulator deliberately leaves open.
3. **"model adjustment, recalibration, or redevelopment may be warranted"** — the same three-way escalation as the PSI ≥ 0.25 convention. The language lines up almost exactly with the PSI rule of thumb. **This is the strongest available bridge between PSI thresholds and supervisory expectation, and it is worth quoting in client documentation.**

### Ongoing Model Monitoring (SR 26-2 §V)

> "**Ongoing model monitoring involves an evaluation of the extent to which a model is performing as expected given potential changes in products, exposures, activities, clients, data relevance, or market conditions.** A model that no longer performs as expected may warrant **overlays, adjustment, or redevelopment** of the model depending on a banking organization's model risk management policy as it pertains to model deterioration."
>
> "An effective ongoing monitoring plan may also include **regularly assessing any model limitations at the development stage and over time**, along with **procedures for responding to any issues that may occur**, before and after a model is approved for use. **The frequency and scope of monitoring reports will depend on the nature of the model, the availability of new data or modeling approaches, and model materiality.**"

**Note "potential changes in … market conditions"** — an explicit regulatory hook for regime-drift monitoring in a trading model. And note **"procedures for responding to any issues"**: monitoring without a documented response procedure does not satisfy the expectation.

### Validation — the general standard (SR 26-2 §V)

> "Model validation evaluates whether models perform as expected and includes an assessment of a model's reliability and its limitations. The nature and rigor of validation generally align with the model's approach, use, and materiality."
> "**Validation can reveal performance deterioration over time and inform judgments about acceptable performance ranges.** When performance deviates meaningfully from expectations, banking organizations generally consider whether **model adjustments, recalibration, or redevelopment** are warranted."
> "**The quality of validation process depends on the rigor and effectiveness of the review rather than on organizational structure** of the banking organization's risk management function."
> "**Even with sound modeling practices and rigorous validation, material model risk can remain.** Users of model output benefit from understanding and communicating limitations, monitoring performance, periodically reviewing relevance, and **supplementing model output with complementary analysis and information**."

### Conceptual Soundness (SR 26-2 §V)

> "Validating conceptual soundness involves assessing and documenting **model design (including key modeling choices, assumptions, qualitative judgments, and data selection), construction, and developmental testing.** While evaluating theoretical construction may be important for some models, other assessments—such as **interpretability measures or benchmarking to other models**—may be more practical for other models."

## 4.4 "Effective challenge" — definition

**SR 26-2 §III, verbatim (this is the current definition):**
> "Sound model risk management also involves **'effective challenge,' which refers to the critical analysis conducted by objective experts who evaluate model risk and effect appropriate changes throughout the model lifecycle, from model development to ongoing monitoring.** Effective challenge is performed by individuals with **the appropriate expertise** to conduct a critical and objective challenge, **sufficient independence** to maintain objectivity, as well as **the organizational standing and influence** to effect any change."

**Three cumulative requirements — memorise these:**
1. **Expertise** — the challenger must technically understand the model.
2. **Independence** — must not be the developer, and must not report to the developer.
3. **Organizational standing and influence** — must be able to *force* a change. This is the requirement most often missed. A reviewer who can only write a memo has not performed effective challenge.

The SR 11-7 definition was substantively the same; this wording carried forward.

**SR 26-2 §VI adds the conflict-of-interest framing:**
> "Model risk management benefits from clear roles and responsibilities with well-defined accountability, including with respect to **potential conflicts of interest (e.g., misalignment of incentives between different reporting lines, such as model development and validation groups)**."

## 4.5 Vendor and third-party models — SR 26-2 §VII (read this section in full)

This is the section that governs how a bank must treat your EA. **Verbatim:**

> "The widespread use of customized **vendor and other third-party products—including data, parameter values, or complete models**—can present unique challenges for validation and other model risk management activities. Additionally, because certain components may be proprietary, **banking organizations may not receive from the vendor the underlying code, data, or methodology** that they would have if a model were developed internally. **Nevertheless, the principles of model risk management remain applicable.**"
>
> "An important element of model risk management is the **validation of vendor products, either by internal or outside parties**. Sound practice includes developing an understanding of the vendor model, including its **conceptual soundness, design, development data, and performance**. Similarly, sound practice involves conducting **ongoing monitoring and outcome analysis to assess whether vendor models are accurate, remain fit for purpose, and continue to be reliable**. Such analysis can also be used to support any **overlay or adjustment** to model output. In cases where vendor models are customized to fit a banking organization's specific business needs, sound practice also involves appropriately **documenting, justifying, and evaluating adjustments** made to customize the model as part of model validation."

**Translation for an EA vendor — what a client bank will demand from you:**
1. **Conceptual soundness** — a written description of the strategy logic, the economic/statistical rationale, and the assumptions it depends on.
2. **Design** — architecture, parameter set, how signals are generated, execution logic.
3. **Development data** — what data the EA was calibrated on, the period, and its limitations (survivorship, look-ahead, overfitting controls).
4. **Performance** — backtest results *and* live results, with the divergence explained (§5).
5. **Ongoing monitoring** — periodic evidence that the model remains fit for purpose, delivered to the client.
6. **Support for overlays/adjustments** — the client may apply its own position limits or kill-switch on top of your EA; document that this is expected and supported.

**Also relevant — model definition and scope (§II), verbatim:**
> "the term 'model' refers to a **complex quantitative method, system, or approach that applies statistical, economic, or financial theories to process input data into quantitative estimates**. The term 'model' in this guidance **excludes simple arithmetic calculations, such as those found within spreadsheets, as well as deterministic rule-based processes and software where there are no statistical, economic, or financial theories underpinning their design or use.**"

And footnote 3:
> "**Generative AI and agentic AI models are novel and rapidly evolving. As such, they are not within the scope of this guidance.** Nonetheless, a banking organization's risk management and governance practices should guide the determination of appropriate governance and controls for any tools, processes, or systems not covered in this document. **However, the principles described in this guidance apply to traditional statistical and quantitative models and non-generative, non-agentic AI models.**"

**Scope implication for your product:** a purely mechanical rule-based EA (e.g. "buy when price crosses the 200-period MA") arguably falls outside the SR 26-2 model definition as a *deterministic rule-based process*. An EA that fits parameters to data, uses a statistical signal, or outputs a probability/score **is** in scope. If you market ML-based EAs to banks, you are squarely in scope. Generative/agentic AI components are currently out of scope — but the guidance says governance should still cover them.

## 4.6 Does SR 26-2 apply to a software vendor? No — and how to use it anyway

**SR 26-2 does not apply to you.** It is supervisory guidance addressed to **banking organizations** supervised by the Fed, OCC and FDIC. Verbatim: *"Reserve Banks are asked to distribute this letter to the supervised banking organizations in their districts and to appropriate supervisory staff."* There is no obligation on a software vendor, and the Fed has no jurisdiction over your firm. SR 26-2 is not a rule, is not enforceable, and *"non-compliance with this guidance will not result in supervisory criticism against a banking organization"* — let alone a vendor.

**But it is the most credible available framework, for four reasons:**
1. **It is the client's obligation.** Your bank client *is* in scope (if >$30bn) or is expected to manage model risk anyway (if ≤$30bn — see the "however" clause). They must validate vendor models. Your documentation either feeds that validation or forces them to do it without you.
2. **It is the shared vocabulary.** "Effective challenge", "outcomes analysis", "conceptual soundness", "model inventory", "model tiering" are the words a bank risk function uses. Speaking them signals credibility.
3. **It is jurisdiction-neutral.** PRA SS1/23 (UK), OSFI E-23 (Canada) and the Fed/OCC/FDIC guidance all rest on the same three pillars. A framework built on SR 26-2 maps cleanly onto all of them.
4. **It is deliberately flexible.** SR 26-2 repeatedly emphasises proportionality: *"practices that are appropriate and effective for one banking organization may be inappropriate and ineffective for a banking organization with a different risk profile."* You can adopt a proportionate subset without appearing to cut corners.

**What a client bank will expect from you, concretely:**
- A **model inventory entry** (name, version, purpose, owner, materiality tier, last validation date) — SR 26-2 §VI requires the bank to maintain one; make your product easy to slot in.
- **Documentation** sufficient for the bank's independent validator to understand the model without your source code (§VII explicitly acknowledges proprietary components).
- A **monitoring pack** delivered on a defined cadence, with pre-agreed thresholds — the bank must define *"established performance thresholds"* (§V), so agree them jointly.
- An **escalation/response procedure** for when thresholds breach (§V: *"procedures for responding to any issues"*).
- **Version control and change notification** — the bank must assess material changes.
- A **SOC 1 / ISAE 3402-type control report** if you handle client funds or data (see §5.1).

**Positioning statement you can use:** *"Our monitoring framework is aligned with the principles of SR 26-2 / OCC Bulletin 2026-13 (which superseded SR 11-7 in April 2026), and with PRA SS1/23. We do not claim regulatory compliance — that is our clients' responsibility — but we provide the documentation, ongoing monitoring evidence and outcomes analysis that a bank's model validation function requires under §V and §VII of that guidance."*

**Caveat to state honestly:** SR 26-2's $30bn applicability threshold means **community banks and small funds are largely out of scope**. For those clients, lead with operational risk, fiduciary duty and the client's own DDQ rather than MRM compliance. For prop firms, the relevant regime is the **prop firm's own risk policy and any regulator of the firm** (see §5.1 on MiFID II RTS 6).

---

# 5. Live-vs-Backtest Divergence and Daily Reconciliation

## 5.1 Daily reconciliation — citable sources

### The single best practitioner source found

**AIMA, *A Guide to Institutional Investors' Views and Preferences Regarding Hedge Fund Operational Infrastructures*, §5.3.2.3–5.3.2.6.**
URL: https://acc.aima.org/static/uploaded/7fe04dd4-1149-4415-a707a233374597b2.pdf *(downloaded, 423,135 bytes, text-extracted)*

**Verbatim — Reconciliation (§5.3.2.3):**
> "Timely reconciliation and resolution of reconciling items is an unglamorous but essential requirement to **promptly identify duplicate, missing or incorrect transactions**. **Triangular reconciliation of cash and positions should occur ideally daily, or at least frequently, between the manager, administrator, and prime broker/OTC counterparty.** This process should be **automated** through the use of proprietary or third party systems, where possible. Where manual reconciliation is required, **specific staff members should be accountable** for the completion of the task. The manager should create a **daily electronic checklist** within the portfolio management system to ensure all accounts have been fully reconciled. Managers should produce a **daily unsettled trades report** and an **escalation process should be in place for trades that do not settle within expected timeframes**. Reconciliations (ideally automated) should also occur between the **front office and back office systems, daily**. The entire reconciliation process should be **overseen by senior operations personnel (i.e., controller or CFO)**. **The staff responsible for cash reconciliation should not be responsible for signing off cash transfers.** Where possible, matching and confirmation systems should be utilised to facilitate the settlement process. Employees with specific credit experience (i.e., bank debt and OTC experience) should be required to ensure that these instruments are accurately settled. **Generally, managers and administrators that reconcile corporate actions, accruals, fees, and expenses, on a daily basis, are able to close out their month end process in an expedited manner.**"

**Verbatim — Cash Controls (§5.3.2.4):**
> "Controls over the cash process are probably one of the most fundamental and important functions at every hedge fund, and should be both **preventive** (i.e., a good signers list) and **detective** (i.e., reconciliations). A documented cash transfer and cash management policy should be established… This policy should include the minimum of **two authorised signatures/approvers** for cash transfers… Additional controls can include **call-backs, multiple levels of authority and approval limits**… For electronic transfers, there should be **one person setting up the wire, and two additional approvers. The person setting up the wire should not count as an approver.** … **Cash balances and margin requirements should be subject to daily reconciliation and monitoring, including 3-way reconciliation to the prime broker and administrator, automatic exceptions-based reconciliations and proper supervision and sign-off by senior personnel (e.g., CFO). There should be a segregation of duties between signer and reconciliation personnel.**"

**Verbatim — Shadow accounting / NAV (§5.3.2.2):**
> "Whilst some managers utilise shadow accounting or rely entirely on their administrator, **best practices call for managers to maintain a complete set of books and records internally and prepare full NAVs, at least, monthly.** If managers do not maintain a full set of internal books, then they should be able to demonstrate **oversight of external books through formal procedures, review of key management reports, integration into the NAV process and frequent contact/meetings with the service provider**… **If there is an administrator preparing the official NAV, there should be an internal line-by-line review of the accounting and investor allocation package by senior back office personnel.** … There should be **evidence of reasonableness checks of investor returns by senior non-investment professionals** to verify the accuracy of the allocations."

**Verbatim — Controls Testing (§5.3.2.5):**
> "It is prudent for the manager to **periodically test the robustness of its control processes** and security measures… a **SAS 70/ISAE 3402 audit report is an effective and efficient tool** and may boost investor confidence in the governance and controls surrounding the calculation/monitoring of a fund NAV… Where a hedge fund manager is serviced by an independent third party administrator, investors will seek assurance that the relevant controls and processes are in place at that third party."

**This AIMA document is the strongest single citation for the reconciliation section.** It is an industry-association guide (Tier 1 for practitioner standards), it is explicit about *daily*, *triangular*, *automated*, *exceptions-based*, and it names the exact check categories.

### Regulatory anchors for algorithmic trading

**MiFID II RTS 6 — Commission Delegated Regulation (EU) 2017/589 of 19 July 2016.**
URL: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32017R0589 *(verified HTTP 200)*
Full text PDF: https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32017R0589 *(downloaded, 165,645 bytes, text-extracted)*

This is the **most directly on-point regulation for an automated trading system**, and it is verified from the primary text. Key articles:

| Article | Title | Key requirement (verbatim / close paraphrase) |
|---|---|---|
| **Art. 9** | **Annual self-assessment and validation** | *"An investment firm shall **annually** perform a self-assessment and validation process and on the basis of that process issue a **validation report**."* Must review: (a) algorithmic trading systems, algorithms and strategies; (b) governance, accountability and approval framework; (c) business continuity arrangement; (d) overall compliance with Art. 17 MiFID II. *"The self-assessment shall also include at least an analysis of compliance with the criteria set out in **Annex I**."* The **risk management function** draws up the report; it is **audited by internal audit** where one exists and **approved by senior management**; deficiencies must be remedied. |
| **Art. 10** | **Stress testing** | *"As part of its annual self-assessment… an investment firm shall test that its algorithmic trading systems and the procedures and controls referred to in Articles 12 to 18 can withstand **increased order flows or market stresses**."* Tests must not affect production. Must comprise: **(a) high messaging volume tests using the highest number of messages received and sent during the previous six months, multiplied by two; (b) high trade volume tests, using the highest volume of trading reached during the previous six months, multiplied by two.** |
| **Art. 11** | **Management of material changes** | Any proposed material change to the production environment must be **preceded by a review by a person designated by senior management**; depth proportionate to the magnitude of the change. Changes to system functionality must be **communicated to traders, compliance and risk management**. |
| **Art. 12** | **Kill functionality** | *"An investment firm shall be able to **cancel immediately, as an emergency measure, any or all of its unexecuted orders** submitted to any or all trading venues to which the investment firm is connected ('kill functionality')."* Unexecuted orders include those from **individual traders, trading desks or clients**. The firm must be able to **identify which trading algorithm and which trader/desk/client is responsible for each order**. |
| **Art. 13** | **Automated surveillance to detect market manipulation** | Must monitor **all trading activity through its systems, including that of its clients**, for signs of market manipulation (Reg. (EU) No 596/2014 Art. 12). |

⚠️ **Note the client-attribution requirement in Art. 12(3)** — for a vendor supplying EAs to multiple clients through one firm, you must be able to attribute every order to a specific algorithm *and* a specific client. Design your order tagging accordingly.

**FCA, *Algorithmic Trading Compliance in Wholesale Markets*** (multi-firm review).
URL: https://www.fca.org.uk/publication/multi-firm-reviews/algorithmic-trading-compliance-wholesale-markets.pdf *(downloaded, 276,942 bytes)*
Findings (verbatim): *"some firms lacked a suitable process to identify algorithmic trading across"* the firm; firms needed *"suitable development and testing procedures"*; and firms must consider *"the potential impact their algorithmic trading activity (including the **combined impact of multiple algorithmic strategies**) may have on the fair"* and orderly functioning of the market. **The "combined impact of multiple algorithmic strategies" point maps directly to SR 26-2's "aggregate risk" concept (§4.2) and is a strong cross-framework argument for portfolio-level monitoring.**

**FIA, *DEA Scope Diagram + Supporting Text* (Aug 2017).**
URL: https://www.fia.org/sites/default/files/2022-01/DEA%20Scope%20Diagram%20%2B%20Supporting%20Text%20V1.5.1%20August%202017.pdf *(downloaded, 4.07 MB)*
Contains: *"Conformance testing should be made in order to verify that the trading systems of an investment firm communicate and interact"* correctly. Useful for the "testing before deployment" narrative.

### SEC custody and books-and-records (US, for fund clients)

- **SEC Rule 206(4)-2 (Custody Rule)**, 17 CFR 275.206(4)-2 — https://www.ecfr.gov/current/title-17/chapter-II/part-275/section-275.206(4)-2 *(eCFR; the fetch redirected to an unblock service but the eCFR citation is correct)*
  SEC guidance page: https://www.sec.gov/files/custody_rule-secg.htm — returned **HTTP 403** (SEC rate-limiting). **Content UNVERIFIED**; the rule requires advisers with custody to maintain client funds/securities with a **qualified custodian**, send **account statements** to clients, and obtain an **annual surprise examination** (with an exception where a qualified custodian sends statements directly). **Verify the current text before relying on it** — the SEC amended the custody rule in 2023–2024.
- **SEC Rules 17a-3 / 17a-4** (books and records) and **CFTC Rule 1.31** — **UNVERIFIED** (not fetched).
- **SEC Marketing Rule, Rule 206(4)-1** — relevant if you publish performance claims; **UNVERIFIED** (not fetched). **Flag: performance advertising of backtested EA results to US fund clients is a genuine compliance exposure.**

### Standard practice with NO primary source located

The following are, in my assessment, genuine industry-standard checks, but **I could not locate a citable public primary source** for any of them. Mark them as "standard practice" rather than "required by X":

- **Break ageing buckets** (e.g. 0–1 day / 2–5 days / >5 days) with escalation SLAs. AIMA requires *"an escalation process … for trades that do not settle within expected timeframes"* but prescribes **no ageing buckets or SLA numbers**.
- **MT5-specific swap/rollover reconciliation**, including the **triple-swap-on-Wednesday** convention (3× swap charged on Wednesday to cover the weekend value date). MQL5 documents swap *rate* constants (`SYMBOL_SWAP_LONG`, `SYMBOL_SWAP_SHORT`, `SYMBOL_SWAP_MODE`, `SYMBOL_SWAP_SUNDAY`, `SYMBOL_SWAP_WEDNESDAY`, `SYMBOL_SWAP_ROLLOVER3DAYS`) in `ENUM_SYMBOL_INFO_INTEGER` — https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants — but that page **failed to fetch repeatedly**. **The existence of a `SYMBOL_SWAP_WEDNESDAY` / 3-day-rollover constant is corroborated by MQL5 documentation search results but the exact text is UNVERIFIED.** The triple-swap convention itself is broker-configurable, not universal.
- **FX conversion reconciliation** for multi-currency accounts — standard practice, no primary source located.
- **Orphan/duplicate fill detection** — AIMA covers this conceptually (*"promptly identify duplicate, missing or incorrect transactions"*) but gives no method.

### Recommended daily reconciliation checklist (each item mapped to its source)

| # | Check | Source |
|---|---|---|
| 1 | **Positions** — EA-internal state vs. broker statement, per symbol, per magic number | AIMA §5.3.2.3 (triangular cash *and positions*) |
| 2 | **Cash balance** vs. broker statement; margin/used margin | AIMA §5.3.2.4 (explicit) |
| 3 | **Equity / floating P&L** vs. broker | AIMA §5.3.2.4 (margin requirements, daily) |
| 4 | **Realized P&L attribution** — by strategy, symbol, magic number | AIMA §5.3.2.2 (NAV / books and records) |
| 5 | **Trade-by-trade fill reconciliation** — every order the EA sent vs. every deal the broker reports | AIMA §5.3.2.3 (duplicate, missing, incorrect transactions) |
| 6 | **Order count / fill ratio** — orders submitted vs. filled vs. rejected vs. expired | AIMA §5.3.2.3 (missing transactions); RTS 6 Art. 12(3) (order attribution) |
| 7 | **Missing / duplicate fills / orphan trades** | AIMA §5.3.2.3 (explicit) |
| 8 | **Commission reconciliation** — expected vs. charged, per deal | AIMA §5.3.2.3 (fees, daily) |
| 9 | **Slippage reconciliation** — requested price vs. fill price, in points and bps | §5.3 below (Perold 1988) |
| 10 | **Swap / rollover / financing** — daily accrual, triple-swap Wednesday, per position | AIMA §5.3.2.3 (accruals, daily); **MT5 specifics UNVERIFIED** |
| 11 | **Corporate actions** — dividends, splits, symbol changes/renames, contract rollovers | AIMA §5.3.2.3 (corporate actions, daily) |
| 12 | **FX conversion** — multi-currency balance translation | Standard practice; **no primary source** |
| 13 | **Unsettled trades report + ageing** | AIMA §5.3.2.3 (daily unsettled trades report, escalation) |
| 14 | **Front-office vs. back-office system reconciliation** | AIMA §5.3.2.3 (explicit, daily) |
| 15 | **Daily electronic checklist, all accounts signed off** | AIMA §5.3.2.3 (explicit) |
| 16 | **Segregation of duties** — reconciler ≠ cash-transfer approver | AIMA §5.3.2.4 (explicit) |
| 17 | **Senior sign-off** by controller/CFO | AIMA §5.3.2.3, §5.3.2.4 (explicit) |
| 18 | **Exceptions-based / automated reconciliation** | AIMA §5.3.2.3, §5.3.2.4 (explicit) |
| 19 | **Annual self-assessment + validation report** | RTS 6 Art. 9 (if client is an EU investment firm) |
| 20 | **Annual stress test: 2× peak messaging volume, 2× peak trade volume (6-month lookback)** | RTS 6 Art. 10 (exact multipliers) |
| 21 | **Kill switch + order-to-client attribution** | RTS 6 Art. 12 |
| 22 | **Material change review before production deployment** | RTS 6 Art. 11 |
| 23 | **Independent assurance report (SOC 1 / ISAE 3402)** | AIMA §5.3.2.5 |

## 5.2 Live vs backtest divergence — metrics practitioners track

**Honest assessment:** this is the weakest-sourced area of the brief. There is **no standard, regulator-endorsed set of live-vs-backtest divergence metrics.** What follows distinguishes verified citations from practice-based recommendations.

### Verified: the backtest-overfitting literature (strongest academic grounding)

**Bailey, D. H., Borwein, J. M., López de Prado, M., Zhu, Q. J. (2014), "Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance," *Notices of the American Mathematical Society* 61(5), 458–471.**
URL: https://www.davidhbailey.com/dhbpapers/backtest-pseudo.pdf *(downloaded, 5.12 MB, text-extracted)*

**Verbatim — the core result (Proposition 2.1):**
> "Given a sample of IID random variables, x_n ~ Z, n = 1, …, N where Z is the CDF of the Standard Normal distribution, the expected maximum of that sample, **E[max_N] = E[max{x_n}]**, can be approximated for a large N as
> `E[max_N] ≈ (1−γ)·Z⁻¹(1 − 1/N) + γ·Z⁻¹(1 − 1/(N·e))`
> where γ ≈ 0.5772156649… is the **Euler-Mascheroni constant**, and N >> 1.
> **An upper bound to Eq.(2.4) is √(2 ln[N]).**"

**The practical consequence, verbatim — this is the number to quote to clients:**
> "For example, **if the researcher tries only N = 10 alternative configurations of an investment strategy, he or she is expected to find a strategy with a Sharpe ratio IS of 1.57, despite the fact that all strategies are expected to deliver a Sharpe ratio of zero OOS** (including the 'optimal' one selected IS)."

> "**As the researcher tries a growing number of strategy configurations, there will be a non-null probability of selecting IS a strategy with null expected performance OOS.** Because the hold-out method does not take into account the number of trials attempted before selecting a model, it cannot assess the representativeness of a backtest."

**This is the single most important quantitative fact for an EA vendor selling backtested strategies.** If you tested 10 parameter sets and picked the best, the expected *in-sample* Sharpe is ~1.57 **even if the strategy has zero true edge.** Any claim of "backtest Sharpe 1.5" from a 10-configuration search is statistically indistinguishable from noise.

**Minimum Backtest Length (MinBTL)** — **Theorem 3.1** of the same paper, verbatim:

> "The **Minimum Backtest Length (MinBTL, in years)** needed to avoid selecting a strategy with an IS Sharpe ratio of E[max_N] among N independent strategies with an expected OOS Sharpe ratio of zero is"

```
                    ⎛ (1−γ)·Z⁻¹(1 − 1/N) + γ·Z⁻¹(1 − 1/(N·e)) ⎞ ²        2·ln[N]
        MinBTL  ≈   ⎜ ───────────────────────────────────────── ⎟    <   ──────────
                    ⎝              E[max_N]                     ⎠        E[max_N]²
```
                                                                        ... (3.2)

where `y` = number of years in the backtest, `N` = number of independent configurations tried, `γ` ≈ 0.5772156649 (Euler-Mascheroni), and `E[max_N]` = the IS Sharpe ratio you are willing to be fooled by. Verbatim on the mechanism:

> "Eq. (3.1) says that **the more independent configurations a researcher tries (N), the more likely she is to overfit, and therefore the higher should the acceptance threshold should be for the backtested result to be trusted.** This situation can be **partially mitigated by increasing the sample size (y)**."

**Practical reading of MinBTL:** the required backtest length grows with the *square* of the number of configurations tested and falls with the square of the Sharpe ratio you demand. Testing 100 configurations and wanting to trust a Sharpe of 1.0 requires roughly `2·ln(100)/1.0² ≈ 9.2` years of backtest. **Most retail EA backtests are 1–3 years.** This is a concrete, quotable reason why short backtests of heavily-optimised EAs are not evidence.

**Probability of Backtest Overfitting (PBO)** via **Combinatorially Symmetric Cross-Validation (CSCV):**
**Bailey, D. H., Borwein, J. M., López de Prado, M., Zhu, Q. J. (2013/2015), "The Probability of Backtest Overfitting," SSRN.**
URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253 *(cited in the CRAN `pbo` package README — verified as a citation, SSRN page not fetched)*
R implementation: https://cran.r-project.org/web/packages/pbo/readme/README.html *(verified HTTP 200)*
> "Implements in R some of the ideas found in the Bailey et al. paper… In particular we use **combinatorially symmetric cross validation (CSCV)** to implement strategy performance tests evaluated by the **Omega ratio**. We compute the **probability of backtest overfit, performance degradation, probability of loss, and stochastic dominance**."

**Deflated Sharpe Ratio (DSR):**
**Bailey, D. H. and López de Prado, M. (2014), "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality," *Journal of Portfolio Management* 40(5), 94–107.**
DOI: `10.3905/jpm.2014.40.5.94` — ⚠️ **UNVERIFIED: this DOI returned HTTP 404 when resolved.** The paper definitely exists (confirmed via Semantic Scholar: https://www.semanticscholar.org/paper/950f37470615dc6ae6e1f45f735408af11c48251 and Mendeley). **Verify the DOI before citing.** The DSR corrects an observed Sharpe ratio for (a) the number of trials, (b) non-normality (skew/kurtosis), and (c) sample length.

**López de Prado, M. (2018), *Advances in Financial Machine Learning*, Wiley.** Chapters on backtesting (Ch. 11–16) cover the DSR, PBO, CSCV and walk-forward pitfalls. **UNVERIFIED** (book not fetched; chapter numbering not confirmed).

### Recommended live-vs-backtest divergence dashboard

These are **practice-based recommendations**, not sourced standards. Each is measurable from MT5 deal history plus a backtest run over the same period:

| Metric | Formula / definition | Suggested alert |
|---|---|---|
| **Realized vs expected slippage** | `slip_i = (fill_price_i − signal_price_i) × direction_i`; report mean, median, p95, in points and bps | Mean slippage worse than backtest assumption by > 1 std dev of live slippage |
| **Fill ratio** | `fills / orders_submitted` | Drop > 10% vs. backtest |
| **Rejection rate** | `rejected / orders_submitted` (requotes, off-quotes, margin) | Any sustained increase |
| **Hit rate (win rate)** | `wins / closed_trades` — live vs. backtest over same period | Outside backtest 95% binomial CI |
| **Average win / average loss** | `mean(winning_trade)` and `mean(losing_trade)`; also the ratio (payoff ratio) | Either outside backtest CI |
| **Expectancy per trade** | `(hit_rate × avg_win) − ((1−hit_rate) × avg_loss)` | Negative over rolling window |
| **Live-vs-backtest return correlation** | Pearson/Spearman of daily live returns vs. backtest returns over same calendar days | r < 0.7 is a serious warning |
| **Tracking error of equity curve** | `std(live_return_t − backtest_return_t)` annualised | Compare to backtest-predicted TE |
| **Sharpe decay** | `SR_live / SR_backtest` | Report with the DSR correction (§ above) |
| **Trade count divergence** | live trades vs. backtest trades over same period | Fewer live trades than backtest ⇒ signal/execution gap |
| **Cost drag** | `(commission + swap + slippage) / gross P&L` | Rising trend |

**Verification status: the metric *names* above are standard practitioner vocabulary, but I did not locate a citable primary source that prescribes this specific set.** Named practitioner sources that discuss the topic (Rob Carver's blog/investment Idiocy, Ernie Chan, QuantStart, Robot Wealth, Quantpedia, Better System Trader podcast) appeared in search results — e.g. https://bettersystemtrader.com/180-3-ways-traders-kill-trading-strategies-and-how-to-avoid-them-rob-carver/ — but **I did not fetch and verify their specific claims, so treat them as leads, not citations.** The academically defensible core is the Bailey/López de Prado work above.

**The strongest framing for client documentation:** *"Backtest results are an in-sample statistic. Under Bailey et al. (2014), searching N configurations yields an expected maximum in-sample Sharpe of √(2 ln N) even when true performance is zero. We therefore report the number of configurations tested, the Deflated Sharpe Ratio, and the Probability of Backtest Overfitting alongside any backtest figure, and we track the live-vs-backtest divergence metrics below."* This is a genuine differentiator — almost no retail EA vendor does it.

## 5.3 Slippage / implementation shortfall — Perold (1988)

**Perold, A. F. (1988), "The Implementation Shortfall: Paper vs. Reality," *Journal of Portfolio Management* 14(3), 4–9.**
DOI: `10.3905/jpm.1988.409150` — ⚠️ **UNVERIFIED: the DOI did not resolve cleanly in automated retrieval.** The citation is confirmed as real and correct (Spring 1988, Vol. 14, Iss. 3) via multiple secondary sources, including a US government publication that states: *"The term 'implementation shortfall' was introduced by Perold in 1988."*

**Historical note worth having:** a Federal Register document notes *"The concept of 'implementation shortfall' was introduced by **Treynor in 1981**"* — i.e. Treynor originated the idea and Perold (1988) named and formalised it. Source: Federal Register, 24 Dec 2003, "Request for Comments on Measures To Improve Disclosure of Mutual Fund Transaction Costs," footnote 30 — https://www.federalregister.gov/documents/2003/12/24/03-31695/request-for-comments-on-measures-to-improve-disclosure-of-mutual-fund-transaction-costs *(page identified; fetch blocked by redirect — **quote UNVERIFIED**)*.

### The formula, verified from a primary academic source

**Menkveld, A. J., "Implementation Shortfall with Transitory Price Effects" (book chapter).**
URL: https://albertjmenkveld.com/text/chapter_ELOv5.pdf *(downloaded, 335,622 bytes, text-extracted)*
> "we extend the classic **Perold (1988)** 'implementation shortfall'… **With a few notational changes we follow Perold (1988, Appendix B)'s methodology for measurement and analysis of implementation shortfall.**"

**The core definition, verbatim:**
> "Let the end-of-period values of the real and paper portfolios be V_p and V_r… The performance of the **paper portfolio** is V_p − V_b, and the performance of the **real portfolio** is V_r − V_b. **The implementation shortfall is the difference between the two.**"

**The decomposition, verbatim — equation (6):**
```
Impl. Shortfall  =  Σ (p_ij − p_bi) · t_ij   +   Σ (p_ei − p_bi) · (n_i − ω_ie)
                    └──── Execution Cost ────┘     └──── Opportunity Cost ────┘
```
where:
- `p_ij` = execution price of trade j in security i
- `p_bi` = **benchmark (pre-trade / decision) price** of security i
- `t_ij` = number of shares traded
- `p_ei` = end-of-period price
- `n_i` = desired (paper) position size
- `ω_ie` = actual end-of-period position

> "The term `(p_ij − p_bi)` is the **per-share cost of transacting at p_ij instead of at p_bi**, and this cost is applied to `t_ij` traded shares. The weighted sum is the **total execution cost relative to the pre-trade benchmark**. The term `(p_ei − p_bi)` is the **paper return on security i over the period**. The **opportunity cost is the sum of these returns weighted by the size of the unexecuted orders**."

**In plain terms:**
```
Implementation Shortfall = (Paper Portfolio Return) − (Real Portfolio Return)
                         = Execution Cost + Opportunity Cost

Execution Cost   = Σ (actual fill price − decision price) × quantity filled
Opportunity Cost = Σ (end price − decision price) × quantity NOT filled
```

**Standard taxonomy** (the brief's "explicit vs implicit" split — Perold's original two-way decomposition above is the canonical one; the five-way taxonomy below is the industry elaboration, **UNVERIFIED as to precise attribution**):
- **Explicit costs:** commissions, exchange fees, taxes, stamp duty.
- **Implicit costs:** bid-ask spread, market impact (permanent + temporary), timing/delay cost, opportunity cost of unfilled quantity.

**Perold's own memorable framing, quoted by Menkveld:**
> "**And you do not know whether having your limit order filled is a blessing or a curse — a blessing if you have just extracted a premium for supplying liquidity, a curse if you have just been bagged by someone who knows more than you do.**"

**Why this matters for an EA vendor:** implementation shortfall is the *correct* benchmark for measuring whether your EA's execution is degrading, because it captures **both** the cost of bad fills **and** the cost of missed fills. A pure "average slippage per trade" metric misses opportunity cost entirely — an EA that gets perfect fills on 60% of signals and silently misses 40% will look great on slippage and terrible on implementation shortfall. **Report both.**

**Related standards (UNVERIFIED — identified but not fetched):**
- Wagner, W. H. and Edwards, M. (1993), "Best Execution," *Financial Analysts Journal*.
- Kissell, R. (2013), *The Science of Algorithmic Trading and Portfolio Management*, Academic Press.
- Almgren, R. and Chriss, N. (2000), "Optimal execution of portfolio transactions," *Journal of Risk* 3(2), 5–39.
- CFA Institute, Trade Management Guidelines / Trade Cost Analysis material.
- FIX Trading Community, implementation shortfall specification.

---

# 6. Verdict: Realistically Adoptable for a 1–3 Person Team

## 6.1 Monitoring — YES, with a specific minimal stack

**Verdict: adoptable.** The tooling is free and mature. The work is in wiring MT5 data into it, not in the statistics.

| Priority | Do this | Effort | Why |
|---|---|---|---|
| **1** | **Compute PSI on the trade-outcome / signal-score distribution, using deciles frozen from the development sample, natural log, zero bins → 0.0001.** Thresholds 0.1 / 0.25, documented as "industry convention (Lewis 1994), not regulatory". | ~1 day | The one metric every credit-risk-literate reviewer recognises. Cheap and citable. |
| **2** | **Compute CSI per input feature** (spread at entry, ATR percentile, hour-of-day, day-of-week, volatility regime, symbol). Use it to answer "*why* did PSI move?" | ~1 day | Localises the cause. Without it, PSI alerts are unactionable. |
| **3** | **Compute Wasserstein distance on the same features.** Unlike PSI it has real units (pips, seconds) and respects ordering. | ~2 hours | Best metric for setting *interpretable* thresholds. Evidently's default for numerical drift >1000 obs. |
| **4** | **Add a sequential detector on the trade stream** — River's `ADWIN` (δ=0.002) or `DDM` (2σ warn / 3σ drift) fed 1/0 per trade for "slippage breach" or "rule violation". | ~2 hours | Catches regime change without waiting for a monthly PSI cycle. River is `pip install river`. |
| **5** | **Use sample-size-aware PSI thresholds (Yurdakul & Naranjo eq. 5.2) instead of a flat 0.25.** | ~2 hours | **Critical for retail/prop accounts with few trades.** A 50-trade account has a ~0.34 significance threshold, not 0.25. |
| **6** | **Version and store every monitoring run** with model version, data window, and threshold config. | ~1 day | This is what makes it *auditable* — SR 26-2 §VI (documentation, model inventory). |

**Explicitly skip:** MMD, alibi-detect, embedding drift, domain classifiers, PCA reconstruction. These solve problems a trading EA does not have and will consume a small team's entire budget.

**The hard part is not the metric — it is the sample size.** A retail EA account may produce 20–100 trades/month. PSI on 20 trades is noise. **Be honest about this in your documentation**: report confidence intervals, use the Yurdakul–Naranjo sample-size-aware benchmarks, and pool across accounts where you can. Claiming PSI 0.12 on n=30 as "moderate drift" is not defensible.

## 6.2 Reconciliation — YES, but scope it honestly

**Verdict: adoptable, but you cannot do a true daily reconciliation as a software vendor.** AIMA's standard is a **triangular** reconciliation between *manager, administrator and prime broker* — a vendor sits outside that triangle. What you *can* do:

**Adoptable (build this):**
- **EA-internal state vs. broker-reported state**, daily, per account, per magic number: positions, cash, equity, realized P&L, order count, fill count, commission, swap. This is a **two-way** reconciliation and it catches the overwhelming majority of real defects (missed fills, duplicate orders, desync after reconnect, bad swap accrual, symbol rollover mishandling).
- **Trade-by-trade fill reconciliation** — every order the EA sent vs. every deal the broker reports. Catches the failure mode that matters most: **silent missed fills**.
- **Daily exceptions report with ageing buckets** (0–1d / 2–5d / >5d) and a documented escalation path. AIMA requires the escalation process; the buckets are your design choice.
- **Implementation shortfall per signal** (Perold 1988) — captures opportunity cost, not just fill quality.
- **Segregation of duties**: whoever runs the reconciliation must not be the person who can move money. For a 1–3 person team this is genuinely hard — **document the compensating control** (e.g. read-only API keys for the reconciler, dual-approval for withdrawals, immutable logs).
- **A daily electronic checklist with named sign-off** — AIMA §5.3.2.3 is explicit. Automate it and store the output.

**Not adoptable at 1–3 people — say so explicitly:**
- **Triangular reconciliation with a prime broker and administrator** — you are not a party to it. **Position this as a client responsibility** and give them the tooling/reports to do it.
- **Full shadow-NAV production** (AIMA §5.3.2.2) — requires a real accounting function. Provide indicative P&L; do not claim NAV.
- **SOC 1 / ISAE 3402 report** (AIMA §5.3.2.5) — this is a real audit engagement, typically tens of thousands of dollars and months of effort. **Do it only if you handle client funds or are selling to institutional clients who require it.** Until then, say plainly that you don't have one.
- **MiFID II RTS 6 Art. 9 annual self-assessment and Art. 10 stress testing** — these bind the **client investment firm**, not you. But you can *supply the evidence* they need: the 2× peak messaging/trade volume stress test (Art. 10), the kill-switch and order-to-client attribution (Art. 12), and the material-change review trail (Art. 11). **Building an export that maps to these articles is a genuine enterprise-sales differentiator at low cost.**

## 6.3 The honest bottom line

**Buildable at 1–3 people, in priority order:**
1. PSI + CSI on deciles, ln, frozen edges, documented zero-bin rule — 2 days
2. Wasserstein on key features + ADWIN/DDM on the trade stream (River) — 1 day
3. Sample-size-aware thresholds instead of flat 0.1/0.25 — 2 hours
4. Two-way daily broker reconciliation with exceptions + ageing — 1–2 weeks
5. Implementation shortfall per signal — 2 days
6. Live-vs-backtest divergence dashboard with Deflated Sharpe / PBO disclosure — 3–5 days
7. A monitoring pack PDF export mapped to SR 26-2 §V/§VII and RTS 6 Art. 9–12 — 1 week

**Total: roughly 4–6 weeks of one person's time.** That is a defensible, citable, genuinely differentiated monitoring and reconciliation capability — and it is a far better sales asset than another backtest screenshot.

**Do not claim:**
- That SR 11-7 applies (it is rescinded) or that SR 26-2 applies to you (it does not — it binds your bank clients).
- Regulatory compliance of any kind. Say "aligned with the principles of" and name the source.
- That the 0.1/0.25 PSI thresholds are regulatory. They are a 1994 credit-scoring convention.
- That PSI is bounded. It is not.
- A backtest Sharpe ratio without disclosing the number of configurations tested.

**Do claim** (all verifiable from this document):
- Monitoring metrics and thresholds are the defaults shipped by Evidently and NannyML, and the conventions documented by SAS Institute.
- The framework is aligned with SR 26-2 / OCC Bulletin 2026-13 (April 2026), which superseded SR 11-7, and with PRA SS1/23.
- Reconciliation checks follow AIMA's operational infrastructure guidance.
- Backtest figures are reported with Deflated Sharpe Ratio and Probability of Backtest Overfitting per Bailey et al. (2014).

---

# 7. Consolidated Source List

## Primary regulatory / official
| Source | URL | Status |
|---|---|---|
| **SR 26-2, Revised Guidance on Model Risk Management (17 Apr 2026)** | https://www.federalreserve.gov/supervisionreg/srletters/sr2602.htm | ✅ verified |
| **SR 26-2 attachment (full text)** | https://www.federalreserve.gov/supervisionreg/srletters/SR2602a1.pdf | ✅ verified, extracted |
| Fed 2026 SR letters index | https://www.federalreserve.gov/supervisionreg/srletters/2026.htm | ✅ verified |
| SR 11-7 (rescinded) | https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm | ❌ **404** |
| SR 11-7 attachment (rescinded) | https://www.federalreserve.gov/supervisionreg/srletters/sr1107a1.pdf | ❌ **404** |
| OCC Bulletin 2026-13 | https://www.occ.treas.gov/news-issuances/bulletins/2026/bulletin-2026-13.html | ⚠️ host unreachable; existence confirmed |
| OCC news release 2026-29 | https://www.occ.gov/news-issuances/news-releases/2026/nr-occ-2026-29.html | ⚠️ host unreachable |
| **PRA PS6/23 / SS1/23, Model risk management principles for banks** | https://www.bankofengland.co.uk/prudential-regulation/publication/2023/may/model-risk-management-principles-for-banks | ✅ verified |
| **MiFID II RTS 6 — Commission Delegated Regulation (EU) 2017/589** | https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32017R0589 | ✅ verified, extracted |
| FCA, Algorithmic Trading Compliance in Wholesale Markets | https://www.fca.org.uk/publication/multi-firm-reviews/algorithmic-trading-compliance-wholesale-markets.pdf | ✅ downloaded |
| FIA, DEA Scope Diagram + Supporting Text (Aug 2017) | https://www.fia.org/sites/default/files/2022-01/DEA%20Scope%20Diagram%20%2B%20Supporting%20Text%20V1.5.1%20August%202017.pdf | ✅ downloaded |
| SEC Rule 206(4)-2 (Custody Rule) | https://www.ecfr.gov/current/title-17/chapter-II/part-275/section-275.206(4)-2 | ⚠️ redirect; content unverified |

## Industry association / practitioner
| Source | URL | Status |
|---|---|---|
| **AIMA, Guide to Institutional Investors' Views… Operational Infrastructures** | https://acc.aima.org/static/uploaded/7fe04dd4-1149-4415-a707a233374597b2.pdf | ✅ downloaded, extracted |

## Peer-reviewed / academic
| Source | URL | Status |
|---|---|---|
| **Yurdakul & Naranjo (2020), "Statistical properties of the population stability index," *J. Risk Model Validation* 14(4), 89–100** | https://files.wmich.edu/s3fs-public/attachments/u730/2022/PSIfinal.pdf | ✅ downloaded, extracted |
| Yurdakul (2018), WMU dissertation | https://scholarworks.wmich.edu/dissertations/3208/ | ⚠️ not fetched |
| du Pisanie, Allison & Visagie, arXiv:2206.11344 | https://ar5iv.labs.arxiv.org/html/2206.11344 | ✅ verified |
| **Bailey, Borwein, López de Prado, Zhu (2014), "Pseudo-Mathematics and Financial Charlatanism," *Notices AMS* 61(5)** | https://www.davidhbailey.com/dhbpapers/backtest-pseudo.pdf | ✅ downloaded, extracted |
| Bailey, Borwein, López de Prado, Zhu, "The Probability of Backtest Overfitting" | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253 | ⚠️ not fetched |
| Bailey & López de Prado (2014), "The Deflated Sharpe Ratio," *JPM* 40(5), 94–107 | DOI 10.3905/jpm.2014.40.5.94 | ❌ **DOI 404** — citation real, DOI unverified |
| Menkveld, "Implementation Shortfall with Transitory Price Effects" | https://albertjmenkveld.com/text/chapter_ELOv5.pdf | ✅ downloaded, extracted |
| Perold (1988), "The Implementation Shortfall," *JPM* 14(3), 4–9 | DOI 10.3905/jpm.1988.409150 | ⚠️ DOI not cleanly resolved |
| Page (1954), "Continuous Inspection Schemes," *Biometrika* 41(1–2), 100–115 | https://doi.org/10.1093/biomet/41.1-2.100 | ⚠️ 403 to automated fetch |
| Lin (1991), "Divergence measures based on the Shannon entropy," *IEEE Trans. IT* 37(1) | DOI 10.1109/18.61115 | ⚠️ unverified |
| Gretton et al. (2012), "A Kernel Two-Sample Test," *JMLR* 13 | https://jmlr.org/papers/v13/gretton12a.html | ⚠️ not fetched |
| Ramdas, Garcia, Cuturi (2015), "On Wasserstein Two Sample Testing" | https://arxiv.org/abs/1509.02237 | ⚠️ cited by SciPy; not fetched |
| Gama et al. (2004), "Learning with Drift Detection," SBIA | DOI 10.1007/978-3-540-28648-6_20 | ⚠️ unverified |
| Bifet & Gavaldà (2007), "Learning from Time-Changing Data with Adaptive Windowing," SDM | DOI 10.1137/1.9781611972771.42 | ⚠️ unverified |
| Kullback & Leibler (1951), "On information and sufficiency," *Ann. Math. Stat.* 22(1), 79–86 | https://doi.org/10.1214/aoms/1177729694 | ⚠️ via bibliography |

## Vendor / tool documentation
| Source | URL | Status |
|---|---|---|
| **SAS Model Manager 15.7, Monitoring and Reporting** | https://documentation.sas.com/api/collections/mdlmgrcdc/v_057/docsets/mdlmgrug/content/mdlmgrug.pdf | ✅ downloaded, extracted |
| **Pruitt, SAS Global Forum 2010, paper 288-2010 (PSI in Enterprise Miner)** | http://support.sas.com/resources/papers/proceedings10/288-2010.pdf | ✅ downloaded, extracted |
| **Evidently AI — Data drift (current)** | https://docs.evidentlyai.com/metrics/explainer_drift | ✅ verified |
| Evidently AI — Customize data drift (full method/threshold table) | https://docs.evidentlyai.com/metrics/customize_data_drift | ✅ verified |
| Evidently AI — Data drift algorithm (legacy ≤0.6.7) | https://docs-old.evidentlyai.com/reference/data-drift-algorithm.md | ✅ verified |
| **NannyML — Univariate drift calculator API** | https://nannyml.readthedocs.io/en/v0.10.1/nannyml/nannyml.drift.univariate.calculator.html | ✅ verified |
| NannyML — How it works: methods | https://nannyml.readthedocs.io/en/stable/how_it_works/univariate_drift_detection.html | ✅ verified |
| NannyML — Thresholds | https://nannyml.readthedocs.io/en/stable/how_it_works/thresholds.html | ✅ verified |
| **River — ADWIN** | https://riverml.xyz/latest/api/drift/ADWIN/ | ✅ verified |
| **River — DDM** | https://riverml.xyz/latest/api/drift/binary/DDM/ | ✅ verified |
| **River — PageHinkley** | https://riverml.xyz/latest/api/drift/PageHinkley/ | ✅ verified |
| R `scorecard` — perf_psi (PSI & CSI) | https://search.r-project.org/CRAN/refmans/scorecard/html/perf_psi.html | ✅ verified |
| R `pbo` — Probability of Backtest Overfitting | https://cran.r-project.org/web/packages/pbo/readme/README.html | ✅ verified |
| SciPy — `scipy.stats.entropy` (KL divergence) | https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.entropy.html | ✅ verified |
| SciPy — `scipy.stats.wasserstein_distance` | https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.wasserstein_distance.html | ✅ verified |
| alibi-detect MMD API | https://docs.seldon.ai/alibi-detect/api-reference/cd/mdd | ❌ **404** |
| MQL5 — MarketInfo constants (swap identifiers) | https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants | ⚠️ fetch failed repeatedly |

## Could not verify — flagged for manual follow-up
1. **OCC Bulletin 2026-13 full text** — `occ.gov` / `occ.treas.gov` unreachable to automated retrieval. Verify manually; it is the OCC's parallel issuance of SR 26-2.
2. **2025 Fed/OCC proposal to revise the 2011 model risk guidance** — the brief asserts this happened. I found a Federal Register reference dated **1 May 2025** (https://www.govinfo.gov/content/pkg/FR-2025-05-01/html/2025-07548.htm) but **did not confirm its content**. The *outcome* is certain (SR 26-2, April 2026), but the **2025 interim step is UNVERIFIED**.
3. **Fed 2025 announcement on reducing MRM requirements for smaller banks** — the *effect* is confirmed in SR 26-2's $30bn threshold and "generally excluding them from this guidance" language, but **no separate 2025 announcement was verified**.
4. **FDIC Credit Card Activities Manual ch. 8** — 403; may contain PSI threshold language.
5. **UAE Central Bank Rulebook §4.3 Model Life-Cycle** — 403; a Gulf-regulator PSI mention would be a strong prop-firm citation.
6. **Deflated Sharpe Ratio DOI** (10.3905/jpm.2014.40.5.94) — returns 404. Find the correct identifier.
7. **Perold (1988) DOI** (10.3905/jpm.1988.409150) — did not resolve cleanly.
8. **alibi-detect default p-value threshold (0.05)** — docs 404; unconfirmed.
9. **MT5 triple-swap / `SYMBOL_SWAP_WEDNESDAY` semantics** — MQL5 docs page unreachable; the constant exists but its documented behaviour is unverified.
10. **NannyML Cloud covariate-shift default thresholds** — page loads but content truncated.
11. **KPMG / CRISIL / Management Solutions / ValidMind / Empyrean SR 26-2 commentary** — identified via search, mostly 403/DNS-blocked. Useful for corroboration but not needed given SR 26-2 itself is verified.
12. **MinBTL closed-form expression** — ✅ **RESOLVED**: Theorem 3.1 of Bailey et al. (2014), now included in §5.2.
