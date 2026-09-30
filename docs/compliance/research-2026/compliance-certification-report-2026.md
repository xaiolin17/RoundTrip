# Compliance Certification Standards for a 1–3 Person MT5 EA Vendor — 2026 Research Report

**Prepared:** 20 September 2026 · **Target year:** 2026 · **Subject:** small (1–3 person) B2B SaaS / on-prem vendor of MetaTrader 5 Expert Advisors selling to retail traders, prop firms, and small funds.

**Source policy:** primary sources (AICPA, EUR-Lex, ISO/IEC catalogue mirrors, FINRA, SEC/Federal Register, CSSF) preferred and fetched directly. Items I could not confirm against a primary source are explicitly marked **UNVERIFIED**. Two structural limitations: (1) `iso.org` returns HTTP 403 to automated fetchers, and (2) `sec.gov` rate-limits automated access — where this happened I used official mirrors (Federal Register/GovInfo, IEC webstore, national standards-body stores) and say so.

---

## 1. SOC 2 (AICPA)

### 1.1 What SOC 2 is, and the AICPA's own pages

SOC (System and Organization Controls) is **not a certification** — it is a suite of **attestation engagements** performed by a licensed CPA firm, producing a **report**, not a certificate. AICPA's definition: *"System and Organization Controls (SOC) is a suite of service offerings CPAs may provide in connection with system-level controls of a service organization or entity-level controls of other organizations."*

- AICPA SOC suite landing page: <https://www.aicpa-cima.com/resources/landing/system-and-organization-controls-soc-suite-of-services>
  (the legacy path `https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2` 301-redirects here)
- SOC 2 topic hub: <https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2>
- **Trust Services Criteria document (the authoritative criteria text):**
  <https://www.aicpa-cima.com/resources/download/2017-trust-services-criteria-with-revised-points-of-focus-2022>
  Full title: *"2017 Trust Services Criteria for Security, Availability, Processing Integrity, Confidentiality, and Privacy (With Revised Points of Focus — 2022)"*. Published by the AICPA's **Assurance Services Executive Committee (ASEC)**. File: `Trust-services-criteria.pdf` (554.3 KB). Page dated 30 Sep 2023. **Free AICPA account required to download** — I could not retrieve the PDF body without registering, so criteria counts below are corroborated from secondary sources (see 1.3).
- The criteria are also codified as **AICPA TSP Section 100** (*Trust Services Criteria*), part of AICPA's Attestation Standards (AT-C 105 / 205 / 206 are the underlying attestation standards).

**Important 2026 context — the AICPA is actively warning about low-quality SOC 2.** As of September 2026 the AICPA SOC landing page carries a formal notice that it *"is looking into allegations published anonymously about the business practices of a compliance vendor that offers Systems and Organization Control (SOC) services,"* warning that it will refer unlicensed firms to state boards of accountancy, and stating *"SOC services should be thoroughly evaluated by service organizations and CPA firms."* Related AICPA/Journal of Accountancy items surfaced on that page:

- "Promises of 'fast and easy' threaten SOC credibility" — *Journal of Accountancy*, 1 Feb 2026: <https://www.journalofaccountancy.com/issues/2026/feb/promises-of-fast-and-easy-threaten-soc-credibility/>
- "The risks of quick-turn SOC engagements and what CPAs should know" — 30 Apr 2026
- "AICPA guides peer reviewers to address SOC 2 risks" — 14 May 2026: <https://www.journalofaccountancy.com/issues/2026/may/aicpa-guides-peer-reviewers-to-address-soc-2-risks/>
- "Ethics Staff Insights: Business arrangements with SOC tool providers" — 13 Apr 2026: <https://www.aicpa-cima.com/resources/article/esi-soc>

**Practical implication:** auditor quality/peer-review enrolment is now a live procurement issue. A buyer's security team in 2026 has grounds to ask *which* CPA firm issued the report and whether it is peer-reviewed. Cheap "SOC 2 in 2 weeks" reports are exactly what the AICPA is flagging.

### 1.2 The five Trust Services Criteria — required vs optional

| Category | Required? | Criteria count (of 61 total) |
|---|---|---|
| **Security** (a.k.a. **Common Criteria**, the "CC" series) | **REQUIRED — mandatory in every SOC 2 report** | **33** |
| Availability | Optional (elective) | ~3 |
| Processing Integrity | Optional (elective) | ~5 |
| Confidentiality | Optional (elective) | ~2 |
| Privacy | Optional (elective) | ~18 |

**Security is the only required category.** Source (secondary but explicit and consistent): Vanta, *Guide to SOC 2 Trust Services Criteria* — <https://www.vanta.com/collection/soc-2/soc-2-trust-service-criteria> — *"Security is required because its criteria are the shared foundation the other four categories build on. That's also why it's called the common criteria. Those 33 criteria are common to all five categories, so Availability, Confidentiality, Processing Integrity, and Privacy each layer additional criteria on top of Security rather than standing alone. You can't scope Availability without Security. The reverse works fine."* Same page: *"Together, the five categories contain 61 individual criteria. Thirty-three of those sit under Security. The remaining 28 are distributed across the other four."* Corroborated by Compyl: <https://compyl.com/blog/what-is-the-soc-2-security-criteria/> — *"Security is the only mandatory criteria for all SOC 2 audits."*

> The per-category breakdown (3/5/2/18) is my arithmetic from the 61−33=28 remainder and is **UNVERIFIED** at the individual-category level; the **33 / 9-groups / 61-total** figures are the ones to rely on.

**The exact AICPA wording confirming "required"** lives in TSP Section 100 §100.12–100.13 (the Security category is mandatory; the other four are elected by management). I could not read the paywalled/registered PDF to quote it verbatim — **UNVERIFIED as a direct quotation**, though the substance is not in dispute.

### 1.3 The 33 common criteria — verified structure

Your hypothesis is **CORRECT**: **33 common criteria across 9 categories, numbered CC1.1 through CC9.2.**

Vanta (same URL as above): *"The Security category breaks into nine groups. Each group contains individually testable criteria, numbered as CC1.1, CC1.2, and so on through CC9.2."* The nine groups:

| Group | Name | Criteria |
|---|---|---|
| CC1 | Control environment | CC1.1–CC1.5 (5) |
| CC2 | Communication and information | CC2.1–CC2.3 (3) |
| CC3 | Risk assessment | CC3.1–CC3.4 (4) |
| CC4 | Monitoring activities | CC4.1–CC4.2 (2) |
| CC5 | Control activities | CC5.1–CC5.3 (3) |
| CC6 | Logical and physical access controls | CC6.1–CC6.8 (8 — largest group) |
| CC7 | System operations | CC7.1–CC7.5 (5) |
| CC8 | Change management | CC8.1 (1) |
| CC9 | Risk mitigation | CC9.1–CC9.2 (2) |
| | **Total** | **33** |

CC1–CC5 derive from the **COSO internal control framework**, which the AICPA adopted as the structural backbone of the common criteria.

**Current version in force:** the **2017 Trust Services Criteria, with Revised Points of Focus — 2022** is the operative edition as of September 2026. No 2025 or 2026 revision of the TSC was found. Note the naming trap: the document is still titled "**2017** Trust Services Criteria" even though the points of focus were revised in 2022 — the 2022 revision changed *points of focus* (implementation guidance), not the criteria themselves. **UNVERIFIED:** I could not confirm from AICPA directly that no newer revision exists as of Sept 2026, because the download is gated.

### 1.4 Type I vs Type II — the exact definitional difference

| | **Type I** | **Type II** |
|---|---|---|
| What is opined on | **Design and implementation** of controls **as of a specified date** ("suitably designed") | **Design *and operating effectiveness*** of controls **throughout a specified period** |
| Time dimension | **Point in time** | **Period of time** |
| Tests of operating effectiveness | **None** | **Required** — sampling, walkthroughs, evidence across the whole window |
| Typical report cadence | One-off / stepping stone | **Annual**, no gaps between reports |

Source: Vanta, *SOC 2 Type 1 vs Type 2* — <https://www.vanta.com/collection/soc-2/soc-2-type-1-vs-type-2>
- *"SOC 2 Type 1 report: Assesses security controls at a single point in time and verifies the design of your systems, tools, and security strategies."*
- *"SOC 2 Type 2 report: Assesses controls over 3–12 months and verifies operational effectiveness."*
- *"During a SOC 2 Type 1 audit... this type of report assesses the design of your systems, tools, and strategies... However, a SOC 2 Type 1 report won't cover how effective your controls are given that they're not tested during this type of audit."*
- *"Audit duration: Type 2 audit windows vary—3, 6, 9, or 12 months—longer windows signal stronger maturity."*

**Observation period — citable source for the 3-month practical minimum:**

URM Consulting (UK consultancy, ISO 27001/SOC 2 specialists), *"How long is the SOC 2 Type 2 reporting period?"* — <https://www.urmconsulting.com/faq/how-long-is-the-soc-2-type-2-reporting-period>

> *"For an initial SOC 2 audit, there is a degree of flexibility in the reporting period. Ideally, your initial reporting period will be 12 months, as a longer period provides greater assurance. However, if you do not have 12 months' worth of evidence to provide to your auditor, shorter reporting periods are also acceptable. It will need to be long enough that operational effectiveness can be demonstrated and validated, and **3 months is typically the shortest reporting period that CPA firms will accept**. A 6-month reporting period for an initial report is also common."*
>
> *"SOC 2 auditing is generally an annual process, with SOC 2 reports being considered 'valid' for 12 months. As such, once you have your initial report in place, subsequent reports will need to be produced 12 months afterwards, covering the 12 months since your previous audit, and **clients will expect there to be no gaps between reports**."*

Corroborated: SOC2Auditors.org (<https://soc2auditors.org/soc-2-auditors-usa/>) — *"Type 2 audits require an observation period of 3-12 months (most commonly 3 months for startups), plus 4-6 weeks for reporting."*

**Practical sequence for a small vendor:** Type I (≈4–8 weeks once controls exist) → immediately open the Type II observation window → 3-month window → Type II report. Total elapsed kickoff-to-Type-II-report ≈ **5–7 months** on the fast path.

### 1.5 Bridge letters

A **bridge letter** (also "gap letter") is a **short formal letter issued by the service organization itself** — *not* by the auditor — covering the period between the **end date of the last SOC 2 report** and the **current date** (or the customer's fiscal year-end). It states that controls have remained effective and that there have been **no material changes** to the system or the control environment since the report period ended.

- TrustCloud, *Master the SOC 2 bridge letter* — <https://www.trustcloud.ai/soc-2/what-is-a-soc-2-bridge-letter-with-examples/>: *"An SOC 2 bridge letter is a short, formal document issued by a service organization to cover the gap between the end of its last SOC 2 report period and the current date... The bridge letter affirms that the controls remain effective and no significant changes have impacted the organization's security posture."* And: *"**The service organization itself is responsible for issuing the SOC 2 bridge letter.** While the SOC 2 audit is conducted by an independent CPA firm, the bridge letter is a self-attestation by the organization."* Typical coverage: *"typically no more than three months."*

**Why buyers ask:** SOC 2 reports are retrospective and considered "valid" for ~12 months (URM, above). A buyer signing in, say, month 14 after your report period closed has no assurance for months 13–14. The bridge letter is the cheap stopgap. **Critical caveat for a 1–3 person vendor:** because it is a **self-attestation with no auditor involvement**, sophisticated buyers treat it as weak evidence and many enterprise/prop-firm security reviewers now simply require a **continuous chain of Type II reports with no gaps** instead. Do not plan to run on bridge letters indefinitely.

### 1.6 Realistic cost and timeline, 2025–2026

**Auditor (CPA firm) fees — the most reliable published ranges:**

| Source | Type I | Type II |
|---|---|---|
| SOC2Auditors.org, Aug 2026 snapshot of **172 attestation-capable CPA firms** — <https://soc2auditors.org/soc-2-auditors-usa/> | **$10,000–$140,000** (all firms) | **$15,500–$200,000** (all firms) |
| Same, by firm tier (2026) | — | Assurance specialists **$15.5K–$50K**; full-service CPA firms **$30K–$80K**; Big Four **$65K–$200K** |
| Compyl, *How Much Does SOC 2 Compliance Cost* (2026) — <https://compyl.com/blog/how-much-does-soc-2-compliance-cost/> | **$5,000–$25,000** (boutique/regional) | **$12,000–$60,000** (boutique/regional) |
| Safeguard, *SOC 2 Audit Cost 2026* — <https://safeguard.sh/resources/blog/how-much-does-a-soc-2-audit-cost> | **$10,000–$30,000** | **$20,000–$60,000** |

**Best-fit line for a 1–3 person vendor:** Security-only scope, ≤50 employees, 3-month Type II window → **Type I ≈ $8,000–$15,000; Type II ≈ $15,000–$25,000.** Safeguard states this directly: *"A company scoping only the Security (Common Criteria) with a 3-month window and under 50 employees might pay closer to $15,000-$25,000."* Named low-cost entry points: **Zero Day CPA from ~$7K Type 2**, **KirkpatrickPrice under $20K Type 2** (SOC2Auditors.org).

**Compliance-automation platforms (annual subscription, separate from audit):**

- **Secureframe** — published floor: *"Fundamentals — Starting at $7,000/year"*: <https://secureframe.com/pricing> (Complete/Defense tiers are quote-only)
- **Vanta** — **no public pricing**; page says *"Request a free demo today to discuss your business needs and get personalized pricing"*: <https://www.vanta.com/pricing> . Third-party transaction data (Vendr) puts Vanta around **$10,000–$30,000+/yr**; Compyl and Safeguard both quote **$7,000–$33,000/yr** for this class of platform.
- **Drata** — pricing page blocks automated access; third-party estimates **$10,000–$30,000+/yr** (Safeguard).

**Total first-year program cost:**

| Source | Range |
|---|---|
| Compyl (2026) | **$30,000–$150,000** all-in; boutique path **$20,000–$60,000** |
| Safeguard (2026) | **$30,000–$100,000+** year one; **$20,000–$50,000/yr** recurring |
| Safeguard, lean path | Under **$20,000** total possible by skipping automation and using a small regional CPA firm for a narrow-scope Type I |
| Compyl, Drata-derived | ~**$28,000** first-year total for a **25-person** startup |

**Realistic budget for a 1–3 person vendor, Security-only scope, no automation platform:** **$25,000–$45,000 year one** ($15K–$25K Type II audit + $5K–$15K penetration test + $3K–$8K readiness/gap help + tooling/training), then **$20,000–$35,000/yr** recurring. With a platform (Vanta/Drata/Secureframe), add $7K–$20K/yr but subtract meaningful internal hours. **Penetration testing is effectively mandatory** for a credible Security-criteria report: **$5,000–$15,000**, typically annual (Safeguard; Compyl).

**Hidden cost:** internal labor. Safeguard: *"a compliance owner can spend 10-20 hours a week for 2-3 months during initial rollout."* For a 1–3 person team this is the binding constraint, not cash.

**Timeline:** Type I **2–6 weeks** after controls are in place; Type II requires the **3-month observation window** plus **4–6 weeks** reporting; kickoff-to-Type-II-report **6–12 months** in practice (Compyl; SOC2Auditors.org).

### 1.7 Is there "SOC 2 for startups" / AICPA scoping guidance for small companies?

- **AICPA guidance specifically for startups: NOT FOUND — UNVERIFIED.** The AICPA publishes SOC resources for *service organizations* generally, not a startup-specific scoping guide. There is no AICPA "SOC 2 for startups" publication that I could locate.
- **Vendor-published startup guidance exists but is marketing, not authoritative:** Drata, *SOC 2 Compliance for Startups* — <https://drata.com/learn/soc-2/compliance-for-startups> (**UNVERIFIED** — page returned HTTP 403 to my fetcher).
- **The real scoping levers** (all corroborated by the cost sources above, and they matter far more than any "startup guide"):
  1. **Scope to Security only.** Every elective category adds criteria and audit cost. Compyl: *"Each Trust Services Criteria added beyond Security can raise audit fees 15-40%."*
  2. **Scope the system boundary narrowly** — the MT5 EA product and its supporting infrastructure, not the whole company. Safeguard: *"Scope reduction — certifying only the specific product or business unit that customers actually care about, rather than the entire company — is the single biggest lever smaller companies pull to keep costs down."*
  3. **Choose a 3-month Type II window** for the first report.
  4. **Decide scope *before* signing the audit engagement letter** — *"expanding scope mid-engagement almost always costs more than scoping correctly from the start"* (Safeguard).
- **Distinctly relevant AICPA-adjacent option:** the AICPA also publishes **SOC for Cybersecurity** and **SOC for Supply Chain** — <https://www.aicpa-cima.com/resources/landing/system-and-organization-controls-soc-suite-of-services> — but these are rarely what buyers ask for; SOC 2 remains the commercial default.

---

## 2. ISO/IEC 27001:2022

### 2.1 What it is and the exact designation

- **Full title:** *Information security, cybersecurity and privacy protection — Information security management systems — Requirements*
- **Designation / edition:** **ISO/IEC 27001:2022** (third edition), published **October 2022**; approved **25 October 2022**.
- **Publishers:** ISO and IEC jointly, via **ISO/IEC JTC 1/SC 27** (Information security, cybersecurity and privacy protection).
- **ICS classification:** **03.100.70** (Management systems) and **35.030** (IT Security).
- **Length:** 21 pages (English).
- **ISO catalogue URLs (canonical):**
  - <https://www.iso.org/standard/27001.html> — standard-number landing page
  - <https://www.iso.org/standard/82875.html> — the **2022 edition record** (ISO publication ID `82875`)
  - **⚠️ UNVERIFIED by direct fetch:** `iso.org` returns **HTTP 403** to automated clients (Cloudflare challenge). Both URLs are correct and widely cited, but I verified the bibliographic data (title, edition, approval date, ICS, page count, and the ID `82875`) through official mirrors instead:
    - IEC Webstore: <https://webstore.iec.ch/en/publication/79694>
    - GSO/DGSM standards store record `iso:pub:std:IS:82875`: <https://dgsm.gso.org.sa/store/standards/iso:pub:std:IS:82875/?lang=en>

**Amendments / corrigenda as of Sept 2026:**
- **ISO/IEC 27001:2022/Amd 1:2024**, published **23 February 2024**, Edition 3, amends ISO/IEC 27001:2022. Source: Finnish Standards Association store — <https://store.sfs.fi/en/isoiec-27001-2022amd-1-2024>. This is the **ISO "climate action changes" amendment** (the standard Annex SL climate clause added across ISO management-system standards). **UNVERIFIED:** I confirmed the amendment's existence, date and that it amends 27001:2022, but could not open the amendment text to confirm its subject matter is climate action.
- National adoptions track it: **DS/EN ISO/IEC 27001:2023/A1:2024** — <https://webshop.ds.dk/en/standard/M384109/ds-en-iso-iec-27001-2023-a1-2024>; **LVS EN ISO/IEC 27001:2023/A1:2025** — <https://www.lvs.lv/en/products/165558>.
- **No ISO/IEC 27001:2025 or :2026 edition exists** as of September 2026. **2022 remains the current edition.**

### 2.2 The 2022 Annex A restructuring — **your numbers are exactly right**

**Verified: 93 controls, 4 themes, Organizational=37, People=8, Physical=14, Technological=34.**

| Theme | Clause range | Count |
|---|---|---|
| **Organizational** | A.5.1 – A.5.37 | **37** |
| **People** | A.6.1 – A.6.8 | **8** |
| **Physical** | A.7.1 – A.7.13 | **14** |
| **Technological** | A.8.1 – A.8.34 | **34** |
| | | **93** |

Sources (three independent, consistent):
- **Secureframe**, *ISO 27001 Controls: A Guide to Annex A* — <https://secureframe.com/hub/iso-27001/controls> — *"A 5.1-5.37: Organizational controls; A 6.1-6.8: People controls; A 7.1-7.13: Physical controls; A 8.1-8.34: Technological controls."* and *"Clause 5: Organizational Controls (37 controls); Clause 6: People Controls (8 controls); Clause 7: Physical Controls (14 controls); Clause 8: Technological Controls (34 controls)."*
- **SureCloud**, *ISO 27001 Annex A Controls: Enterprise Implementation Guide* — <https://www.surecloud.com/resource-hub/iso-27001-annex-a-enterprise-implementation> — *"ISO 27001:2022 reduced Annex A from 114 controls across 14 domains to 93 controls across four themes: Organisational (37), People (8), Physical (14), and Technological (34)."*
- **ISMS.online**, *ISO 27001 Annex A Controls* — <https://www.isms.online/iso-27001/annex-a-controls/> (used to verify the 11 new controls, below)

**2013 baseline confirmed:** ISO/IEC 27001:2013 Annex A had **114 controls across 14 clauses/domains (A.5–A.18)**. ISO/IEC 27001:2013 is now formally listed as **"Withdrawn"** — <https://store.sfs.fi/en/isoiec-27001-2013-3>.

**How 114 → 93 happened** (Secureframe): *"none of the previous controls were removed. 57 were simply merged into 24 controls, 1 control was split into 2, 11 new controls were added, and the remaining 58 controls are mostly unchanged with minor contextual updates."*

**The 11 new controls — verified exactly (number + name), from ISMS.online:**

| # | Control | Name |
|---|---|---|
| 1 | **A.5.7** | Threat intelligence |
| 2 | **A.5.23** | Information security for use of cloud services |
| 3 | **A.5.30** | ICT readiness for business continuity |
| 4 | **A.7.4** | Physical security monitoring |
| 5 | **A.8.9** | Configuration management |
| 6 | **A.8.10** | Information deletion |
| 7 | **A.8.11** | Data masking |
| 8 | **A.8.12** | Data leakage prevention |
| 9 | **A.8.16** | Monitoring activities |
| 10 | **A.8.23** | Web filtering |
| 11 | **A.8.28** | Secure coding |

Your hypothesized list was correct on all eleven. Note **A.5.23 (cloud services)** and **A.8.28 (secure coding)** are the two that bite hardest for a software vendor; **A.5.30 (ICT readiness for business continuity)** is the one most often missed by tiny teams.

### 2.3 Main body clauses 4–10

**Top-level structure confirmed** (Clauses 1–3 are *Scope*, *Normative references*, *Terms and definitions*; the auditable requirements are Clauses 4–10):

| Clause | Title |
|---|---|
| **4** | Context of the organization |
| **5** | Leadership |
| **6** | Planning |
| **7** | Support |
| **8** | Operation |
| **9** | Performance evaluation |
| **10** | Improvement |

**Primary-source quote on non-excludability** — from the official ISO scope abstract (GSO mirror of ISO pub 82875, <https://dgsm.gso.org.sa/store/standards/iso:pub:std:IS:82875/?lang=en>):

> *"This document specifies the requirements for establishing, implementing, maintaining and continually improving an information security management system within the context of the organization... The requirements set out in this document are generic and are intended to be applicable to all organizations, regardless of type, size or nature. **Excluding any of the requirements specified in Clauses 4 to 10 is not acceptable when an organization claims conformity to this document.**"*

That last sentence is the single most important scoping fact for a 1–3 person team: **you can exclude Annex A controls (with justification in the Statement of Applicability), but you cannot exclude Clauses 4–10.** Every ISMS process — internal audit, management review, competence, documented information — must exist regardless of headcount.

**Sub-clause titles (4.1–4.4, 5.1–5.3, 6.1–6.3, 7.1–7.5, 8.1–8.3, 9.1–9.3, 10.1–10.2):** the standard set is 4.1 Understanding the organization and its context; 4.2 Understanding the needs and expectations of interested parties; 4.3 Determining the scope of the ISMS; 4.4 Information security management system; 5.1 Leadership and commitment; 5.2 Policy; 5.3 Organizational roles, responsibilities and authorities; 6.1 Actions to address risks and opportunities (6.1.1 General, 6.1.2 Information security risk assessment, 6.1.3 Information security risk treatment); 6.2 Information security objectives and planning to achieve them; 6.3 Planning of changes; 7.1 Resources; 7.2 Competence; 7.3 Awareness; 7.4 Communication; 7.5 Documented information; 8.1 Operational planning and control; 8.2 Information security risk assessment; 8.3 Information security risk treatment; 9.1 Monitoring, measurement, analysis and evaluation; 9.2 Internal audit; 9.3 Management review; 10.1 Continual improvement; 10.2 Nonconformity and corrective action. **UNVERIFIED against the standard text** — the standard is paywalled and I did not purchase it; these titles are consistent across certification-body and consultancy sources but I did not obtain a primary citation for each.

### 2.4 Certification cost and timeline for a small company

**Stage 1 vs Stage 2** (TrustCloud, <https://www.trustcloud.ai/iso-27001/how-much-does-iso-27001-cost/>):
> *"Stage 1 involves reviewing documentation and ensuring your policies and plans align with ISO 27001. If no major issues are found, you move on to Stage 2, which focuses on the actual implementation of those controls. The auditor will evaluate evidence of risk treatment, employee training, incident response practices, and operational effectiveness."*

**Audit days and fees:**

| Item | Figure | Source |
|---|---|---|
| 50-person, single-site: **4–6 audit days** total (Stage 1 + Stage 2) | at **$2,000–$3,500/day** | Safeguard |
| Certification body Stage 1 + Stage 2 combined | **$10,000–$30,000** | Safeguard |
| ≤10 employees | **~$10,000** audit, **~5 days** | TrustCloud |
| <100 employees, certified auditors | **$5,000–$18,000** | TrustCloud |
| Surveillance audits (years 2 and 3) | **$5,000–$12,000/yr** (TrustCloud: ~$7,500) | Safeguard; TrustCloud |
| Recertification (year 3) | same order as initial: **$8,000–$30,000** | TrustCloud |
| Compliance automation (Vanta/Drata/Secureframe/Sprinto) | **$7,000–$33,000/yr** | Safeguard; Secureframe floor **$7,000/yr** |
| Gap analysis / readiness assessment | **$5,000–$20,000** (TrustCloud: $5,000–$6,000) | Safeguard; TrustCloud |
| Consultant | **~$1,500/day** (TrustCloud also cites ~$140/hr for internal-audit help) | TrustCloud |
| Penetration testing (A.8.29) | **$5,000–$15,000**, often annual | Safeguard |
| Security awareness training platform | **$1,500–$5,000/yr** (TrustCloud: ~$1,000/yr) | Safeguard; TrustCloud |
| Internal labor | **200–400 hours** over a 3–6 month readiness period | Safeguard |

**Totals:**
- Safeguard: a **40-person SaaS** first certification ≈ **$20,000–$45,000 year one**; 300-person ≈ $100,000+. Overall range **$20,000–$80,000**.
- TrustCloud: **~$10,000** (small orgs) to **$100,000+** (enterprise).
- **Best estimate for a 1–3 person, cloud-only, single-product vendor:** **$12,000–$30,000 year one** (audit $8K–$18K + gap analysis $5K–$6K + tooling $0–$7K + pentest $5K), then **$8,000–$15,000/yr** for surveillance + tooling. Automation platforms are **not** required at this size and are often poor value for a 3-person team.

**Timeline:** **3–6 months** of readiness work, then Stage 1 → (typically 2–8 weeks gap) → Stage 2 → certificate. **Realistic kickoff-to-certificate: 5–9 months.**

**Recertification cycle:** 3-year cycle — Stage 1+2 in year 0, surveillance audits in years 1 and 2, full recertification in year 3 (TrustCloud).

### 2.5 The ISO 27001:2013 → :2022 transition deadline — **your date is correct**

**Verified: ISO/IEC 27001:2013 certificates were withdrawn on 31 October 2025.**

URM Consulting, *The Timeline for Transitioning to ISO 27001:2022* (based on a joint URM/BSI webinar) — <https://urmconsulting.com/blog/the-timeline-for-transitioning-to-iso-27001-2022>:

> *"**ISO 27001:2013 certificates will be withdrawn on 31 October 2025** and, after this point, only ISO 27001:2022 certificates will be valid. However, in practice, the deadline for transition is earlier than this for many organisations. **From 1 May 2024, all initial and recertification visits must be conducted against ISO 27001:2022**, so if you are due to recertify on or after this date, you will need to have completed your transition in time for your recertification visit."*

Corroborated: the Finnish Standards Association lists **ISO/IEC 27001:2013 as "Withdrawn"** — <https://store.sfs.fi/en/isoiec-27001-2013-3>.

**What this means in September 2026:** the transition window is **closed and in the past**. There is no longer any choice — **ISO/IEC 27001:2022 is the only certifiable edition.** Any vendor still advertising an "ISO 27001:2013 certificate" is advertising a dead credential. For a new entrant this is actually good news: you certify directly to 2022 with no legacy baggage.

**UNVERIFIED:** the specific **IAF resolution number** that set the 3-year transition (commonly cited as IAF Resolution 2022-15) — `iaf.nu` blocked automated fetches, and IAF itself **ceased operations on 01 January 2026**, its site now being an archive: *"IAF ceased operations on 01 January 2026. This website is a legacy site maintained for archival/reference purposes only. For current information, please visit the Global Accreditation Cooperation Incorporated Website"* — <https://iaf.nu/en/iaf-documents/?cat=8>. Successor body: <https://globalaccreditationcooperationincorporated.org>. The **31 Oct 2025 date and the 1 May 2024 cutoff are verified**; the resolution number is not.

### 2.6 Scope reduction for a 1–3 person vendor

- **The Statement of Applicability (SoA) is mandatory** under **Clause 6.1.3**. For each of the 93 Annex A controls it must record the include/exclude decision and a **risk-based justification**. Source: SureCloud (above).
- **You can exclude controls, but not Clauses 4–10.** See the ISO scope quote in §2.3.
- **Blanket exclusions are a classic audit finding.** SureCloud: *"Exclusions are only defensible where the risk assessment doesn't identify a relevant risk, or where legal, regulatory, or contractual requirements don't mandate the control... **Blanket exclusions without risk-based justification are a common audit finding.**"*
- **Fully cloud-hosted does *not* mean you can exclude the Physical theme (A.7, 14 controls).** You still have offices, laptops, and possibly home working; A.7.4 (physical security monitoring), A.7.7 (clear desk/clear screen), A.7.9 (security of assets off-premises) and A.7.14 (secure disposal/reuse of equipment) are routinely applicable. However, controls tied to **your own data centres** can be excluded with justification if you hold no such facilities — that is a legitimate, defensible exclusion. **UNVERIFIED:** I found no certification-body publication explicitly blessing a "no physical controls at all" ISMS; treat any such claim with suspicion.
- **For an MT5 EA vendor specifically**, the highest-leverage controls are A.8.25–A.8.31 (secure development lifecycle, secure coding, security testing, outsourced development, separation of environments, change management) and A.5.23 (cloud services). These map almost 1:1 onto what a broker or prop firm will actually probe in a code-security review.

---

## 3. Institutional buyer expectations in 2026

### 3.1 Is SOC 2 / ISO 27001 actually expected or required?

**Verdict: yes, but the strength of the evidence varies sharply by buyer type, and I could not find a hard, primary, quantified statistic.**

**What I could verify:**

- **FINRA's 2026 Annual Regulatory Oversight Report — "Third-Party Risk Landscape"** is the strongest US regulatory signal. FINRA's own page: <https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/third-party-risk> (the 2025 edition is at `.../2025-finra-annual-regulatory-oversight-report/third-party-risk`). ACA Group's summary (9 Jan 2026, <https://www.acaglobal.com/industry-insights/finra-releases-2026-oversight-report-highlighting-ai-cybersecurity-and-compliance-risks/>) reports FINRA's guidance to member firms:
  > *"Rising cyberattacks and service outages among third-party vendors pose the potential for wide-scale disruption. To mitigate these risks, firms should: **Conduct initial and ongoing due diligence of vendor-supported systems.** Maintain a detailed inventory of vendor services, connected systems, and the firm data vendors can access."*
  and that *"Effective practices emphasize cross-functional coordination among cybersecurity, AML, and **vendor risk teams**, supported by controls that are formally documented, implemented, and tested."*

- **SEC Division of Examinations — 2026 Examination Priorities** (press release <https://www.sec.gov/newsroom/press-releases/2025-132-sec-division-examinations-announces-2026-priorities>; **UNVERIFIED by direct fetch — sec.gov returned HTTP 403**). Via KPMG's regulatory alert (<https://kpmg.com/us/en/articles/2025/sec-2026-priorities-examinations-and-perspectives-reg-alert.html>):
  > *"**Continued Focus:** Examinations will continue to focus on **operational resiliency, third-party oversight**, and all aspects of AML programs."*
  > Under **Regulation S-P**: exam focus includes *"**Oversight of third-party vendors**"* and *"progress toward upcoming compliance requirements for an incidence response program covering unauthorized access to or use of a customer's information."*
  > Under **Regulation SCI**: *"**Management of third-party vendor risk** and proper identification of vendor systems that qualify as SCI systems or **indirect SCI systems**."*

- **FINRA Regulatory Notice 21-29** (outsourcing / third-party vendor supervision) — <https://www.finra.org/rules-guidance/notices/21-29>. Fetched successfully (HTTP 200). The notice addresses member firms' responsibilities when they outsource activities, and cites *Notice 05-48* as guidance on *"a member's responsibilities if the member outsources certain activities."* **UNVERIFIED:** I could not confirm at line level that Notice 21-29 explicitly names "SOC 2 reports" — the page is long and nav-heavy in the fetch. Treat the specific SOC 2 reference as plausible but unconfirmed.

**What I could NOT verify (mark UNVERIFIED):**
- **No AICPA, ISACA, Vanta or Drata survey statistic** quantifying "X% of enterprise buyers require SOC 2" was retrievable. Vanta's **State of Trust Report** (<https://www.vanta.com/state-of-trust/global>) surveys **3,500 business and IT leaders** globally, but its published headline findings are about AI risk and "security theatre," not certification procurement: **61%** *"spend more time posturing than protecting"*; **59%** *"say AI risks outpace their expertise"*; **95%** *"say AI is making their security teams more effective."* Nothing directly on SOC 2/ISO 27001 procurement mandates.
- **CAIQ (Cloud Security Alliance)** and **SIG (Shared Assessments)** — I could not fetch <https://sharedassessments.org/sig/> (returned 208 chars) or the CSA CAIQ page (connection closed). Their status as de facto requirements is **UNVERIFIED** here, though both are widely used in vendor security questionnaires.

**Practical read for this vendor:** retail traders will never ask. **Prop firms and small funds will ask via a security questionnaire** and will accept a clear, well-evidenced answer even without a certificate. **Brokers and regulated entities** are the ones whose examiners are pushing third-party oversight, and those are the buyers who will want a report. The regulatory pressure is real and documented; the "everyone requires SOC 2" claim is marketing.

### 3.2 What broker / prop-firm due diligence actually asks for

Synthesizing the FINRA 2026 guidance and the SEC 2026 priorities above, the concrete asks are:
1. **Vendor inventory** — what services you provide, what systems you connect to, and **what firm/customer data you can access** (FINRA 2026, verbatim above).
2. **Initial *and ongoing* due diligence** — not a one-time onboarding check (FINRA 2026, verbatim above).
3. **Documented, implemented and tested controls** — the phrase "formally documented, implemented, and tested" is the hook that a SOC 2 Type II or ISO 27001 certificate satisfies most cheaply.
4. **Incident notification and response** — driven by Reg S-P's incident response program requirements (SEC 2026 priorities).
5. **Audit/inspection rights and subcontracting disclosure** — for EU-facing buyers, mandated by DORA Art. 30 (see §4).
6. **Substitutability / exit** — whether the buyer can migrate away from you (DORA Art. 29; mirrored in SEC operational-resiliency exams).

**UNVERIFIED:** I could not retrieve a concrete, published prop-firm or broker vendor-onboarding form, third-party risk policy, or security-review checklist. A search surfaced a brokerage-tech vendor blog on "SOC 2 vs ISO 27001: Broker Vendor Checklist" (<https://brokeret.com/blog/soc2-vs-iso27001-brokerage-tech-vendor-questions-crm-trading-platform>) but the page returned no extractable content. **No named prop firm (FTMO, Topstep, Apex, etc.) was confirmed to publish a SOC 2 mandate.**

### 3.3 SEC / FINRA third-party vendor risk — primary sources

| Instrument | Status / relevance to a small EA vendor | URL |
|---|---|---|
| **FINRA Rule 3110 (Supervision)** | Obligation sits on the **member firm**, not on you. Firms must supervise associated persons and activities, including outsourced functions. | <https://www.finra.org/rules-guidance/rulebooks/finra-rules/3110> |
| **FINRA Rule 3120 (Supervisory Control System)** | Member-firm obligation to test and report on supervisory controls; a vendor may be asked to supply evidence. | <https://www.finra.org/rules-guidance/rulebooks/finra-rules/3120> |
| **FINRA Regulatory Notice 21-29** | Outsourcing/third-party supervision guidance for member firms. | <https://www.finra.org/rules-guidance/notices/21-29> |
| **FINRA 2026 Annual Regulatory Oversight Report — Third-Party Risk Landscape** | Current FINRA expectations: initial + ongoing vendor due diligence, vendor inventory, data-access mapping. | <https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/third-party-risk> |
| **SEC Regulation S-P (17 CFR Part 248), 2024 amendments** | Adds **service-provider oversight** and an **incident response program** duty on covered institutions. FINRA issued a compliance-date reminder on **14 Nov 2025**. | FINRA advisory: <https://www.finra.org/rules-guidance/guidance/sec-regulation-s-p-compliance-date-reminder-20251114> |
| **SEC Rule 17a-4 (17 CFR 240.17a-4)** | Records-retention rule binding **broker-dealers**. Relevant to you only as a *customer requirement*: firms may demand WORM-capable storage, audit trails and retention of electronic records in your product. | <https://www.ecfr.gov/current/title-17/chapter-II/part-240/subject-group-ECFR7de5c9d3c6c6c6c/section-240.17a-4> |
| **SEC Cybersecurity Risk Management Rule for broker-dealers, File No. S7-06-23** | **WITHDRAWN.** Confirmed in the Federal Register: *"The Commission is formally withdrawing certain notices of proposed rulemaking issued between March 2022 and November 2023. **The Commission does not intend to issue final rules with respect to these proposals.**"* File No. **S7-06-23** is listed among the withdrawn items. Published **90 FR 25531**, 17 June 2025. | <https://www.govinfo.gov/content/pkg/FR-2025-06-17/html/2025-11110.htm> · SEC docket page: <https://www.sec.gov/rules-regulations/2025/06/cybersecurity-risk-management-rule-broker-dealers-clearing-agencies-major-security-based-swap> |
| **Regulation SCI (17 CFR 242.1000 et seq.)** | Applies to **SCI entities** (SROs, clearing agencies, plan processors, and certain large ATSs). **A 1–3 person EA vendor is not an SCI entity.** But SEC 2026 priorities flag *"vendor systems that qualify as SCI systems or **indirect SCI systems**"* — meaning your broker-dealer customer may treat your software as in-scope and push obligations down to you. | KPMG summary: <https://kpmg.com/us/en/articles/2025/sec-2026-priorities-examinations-and-perspectives-reg-alert.html> |
| **SEC cyber disclosure rules (Form 8-K Item 1.05; Reg S-K Item 106)** | Apply to **public reporting companies only**. A private vendor has no disclosure obligation. **UNVERIFIED** by direct fetch of the adopting release. | — |

**Key 2026 finding:** the SEC's broker-dealer cybersecurity rule (S7-06-23) is **dead** — formally withdrawn June 2025. Anyone still citing it as a looming obligation is out of date. The live pressure is instead **Reg S-P oversight + Reg SCI vendor scoping + exam priorities**, all of which operate **through your customers**, not directly on you.

**Reg S-P compliance dates: UNVERIFIED.** I could not retrieve the Federal Register text (cross-origin redirect to `unblock.federalregister.gov`). The commonly cited dates — **3 December 2025** for larger entities and **3 June 2026** for smaller entities — are **not confirmed** here. Note that if the June 2026 date is right, it has **already passed** as of this report.

---

## 4. DORA — Regulation (EU) 2022/2554

**Primary text (all quotes below are from the official OJ text):**
- ELI: <https://eur-lex.europa.eu/eli/reg/2022/2554/oj>
- CELEX: <https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32022R2554>
- Full HTML (fetched and parsed for this report): <https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32022R2554>
- OJ citation: **OJ L 333/1, 27.12.2022**; Regulation (EU) 2022/2554 of the European Parliament and of the Council of **14 December 2022** on digital operational resilience for the financial sector.

### 4.1 Applicability — Article 64

**Verified verbatim from Article 64 ("Entry into force and application"):**
> *"This Regulation shall enter into force on the twentieth day following that of its publication in the Official Journal of the European Union. **It shall apply from 17 January 2025.**"*

Your date is correct. **DORA has been fully applicable since 17 January 2025** — it is live, enforceable law, roughly 20 months old as of this report.

### 4.2 Who DORA applies to — Article 2

**Article 2(1)** lists 21 categories, points **(a)–(u)**. Points (a)–(t) are collectively defined by **Article 2(2)** as **"financial entities"**; point **(u)** is **"ICT third-party service providers."**

(a) credit institutions; (b) payment institutions (incl. exempted under Directive (EU) 2015/2366); (c) account information service providers; (d) electronic money institutions (incl. exempted under Directive 2009/110/EC); (e) **investment firms**; (f) crypto-asset service providers authorised under MiCA and issuers of asset-referenced tokens; (g) central securities depositories; (h) central counterparties; (i) **trading venues**; (j) trade repositories; (k) **managers of alternative investment funds**; (l) **management companies**; (m) data reporting service providers; (n) insurance and reinsurance undertakings; (o) insurance intermediaries, reinsurance intermediaries and ancillary insurance intermediaries; (p) institutions for occupational retirement provision; (q) credit rating agencies; (r) administrators of critical benchmarks; (s) crowdfunding service providers; (t) securitisation repositories; **(u) ICT third-party service providers.**

**Article 2(3) — out of scope entirely:** (a) AIF managers referred to in Art 3(2) of Directive 2011/61/EU; (b) insurance/reinsurance undertakings referred to in Art 4 of Directive 2009/138/EC; (c) IORPs with ≤15 members total; (d) persons exempted under Arts 2 and 3 of Directive 2014/65/EU (MiFID II); (e) insurance/reinsurance/ancillary intermediaries that are **microenterprises or SMEs**; (f) post office giro institutions (Art 2(5)(3) of Directive 2013/36/EU).

**Article 2(4):** Member States **may exclude** entities referred to in Art 2(5), points (4)–(23) of Directive 2013/36/EU located in their territory (with notification to the Commission).

### 4.3 Does DORA apply to a small non-EU software vendor? — **Yes, but only indirectly, through the contract**

This is the crux, and the answer is precise:

1. **You are almost certainly not a "financial entity."** A 1–3 person MT5 EA vendor is not any of Art 2(1)(a)–(t) unless it is itself an authorised investment firm, AIFM, etc.
2. **You are an "ICT third-party service provider"** under Art 2(1)(u) — a category listed in the scope article.
3. **But DORA imposes almost no direct obligations on ICT third-party service providers as such.** The direct obligations in Chapters II–IV (ICT risk management, incident reporting, resilience testing) fall on **financial entities**. The only direct obligations on a TPP arise if it is **designated critical** under Art 31 — which is aimed at hyperscalers, not at a three-person EA shop (see §4.5).
4. **Therefore DORA reaches you through your customer's contract and their due-diligence process.** The financial entity must (Art 28(4)(d)) *"undertake all due diligence on prospective ICT third-party service providers and ensure throughout the selection and assessment processes that the ICT third-party service provider is suitable"*, and must (Art 30) put mandatory clauses in your contract. **EU/non-EU establishment is irrelevant to this** — Art 29 expressly contemplates contractual arrangements with providers *"established in a third country"* and requires the financial entity to consider third-country insolvency law, data recovery constraints, and *"compliance with Union data protection rules and the effective enforcement of the law in that third country."*

**So: DORA will show up as a set of contractual demands and a due-diligence questionnaire from your EU financial-entity customers — not as a regulator knocking on your door.**

### 4.4 Article 28 — general principles for ICT third-party risk

- **Art 28(1)(a):** financial entities *"shall, at all times, remain fully responsible for compliance with, and the discharge of, all obligations under this Regulation"* even when using ICT services. **Outsourcing does not transfer regulatory responsibility** — this is why buyers push so hard.
- **Art 28(1)(b):** proportionality — nature, scale, complexity and importance of ICT dependencies; criticality of the service; impact on continuity.
- **Art 28(2):** financial entities (other than those under Art 16(1) and other than **microenterprises**) must adopt and regularly review an **ICT third-party risk strategy**, including a policy on ICT services supporting critical or important functions.
- **Art 28(3) — the Register of Information.** Financial entities must *"maintain and update at entity level, and at sub-consolidated and consolidated levels, a register of information in relation to all contractual arrangements on the use of ICT services provided by ICT third-party service providers."* Contracts must be documented, **distinguishing those supporting critical or important functions from those that do not**. They report **at least yearly** to competent authorities on new arrangements, provider categories, contract types, and services/functions provided; must make the **full register available on request**; and must **inform the competent authority in a timely manner about any planned arrangement supporting a critical or important function**. **→ Practical consequence for you: your customer must record your contract in a structured regulatory register. Expect to be asked for LEI, contract reference, subcontractor chains, data locations and function criticality.**
- **Art 28(4):** before contracting, financial entities must (a) assess whether the arrangement supports a critical or important function; (b) assess whether supervisory conditions for contracting are met; (c) identify and assess all relevant risks **including ICT concentration risk**; (d) **undertake all due diligence on the prospective provider**; (e) identify and assess conflicts of interest.
- **Art 28(5) — THE COMPLIANCE-CERTIFICATION HOOK.** Verbatim:
  > *"Financial entities may only enter into contractual arrangements with ICT third-party service providers that **comply with appropriate information security standards**. When those contractual arrangements concern critical or important functions, financial entities shall, prior to concluding the arrangements, **take due consideration of the use, by ICT third-party service providers, of the most up-to-date and highest quality information security standards**."*

  **This is the single sentence in DORA that makes ISO/IEC 27001:2022 (or an equivalent, e.g. SOC 2) commercially load-bearing for a vendor like you.** Note it says "most up-to-date" — which, given the 31 Oct 2025 withdrawal, now **excludes ISO 27001:2013**.
- **Art 28(6):** audit/inspection rights exercised on a risk-based approach, with frequency and scope pre-determined, *"adhering to **commonly accepted audit standards**."*
- **Art 28(7):** contracts must be terminable on (a) significant breach of law/regulation/contract; (b) circumstances capable of altering performance, including material changes affecting the arrangement or the provider; (c) **evidenced weaknesses in the provider's overall ICT risk management**, especially as to availability, authenticity, integrity and confidentiality of data; (d) where the competent authority can no longer effectively supervise the financial entity.
- **Art 28(8):** **exit strategies** required for critical/important functions — documented, tested, reviewed periodically; must allow exit without disruption, without limiting regulatory compliance, and without detriment to client service continuity; must identify alternative solutions and transition plans for secure data transfer.
- **Art 28(9):** ESAs to develop ITS for register-of-information templates (→ CIR (EU) 2024/2956, §4.6).

### 4.5 Article 29, Article 30, Article 31

**Article 29 — Preliminary assessment of ICT concentration risk at entity level.** Before contracting for critical/important functions, the financial entity must consider whether the arrangement would mean (a) contracting a provider **not easily substitutable**, or (b) multiple arrangements with the same or closely connected providers. Where **subcontracting** is possible, they must weigh the benefits and risks, *"in particular in the case of an ICT subcontractor established in a third-country,"* consider insolvency-law provisions and urgent data-recovery constraints, consider Union data protection compliance and law enforcement in the third country, and assess how *"potentially long or complex chains of subcontracting"* affect monitoring and supervisory ability. **→ If you subcontract any part of your service (hosting, support, telemetry), expect to disclose the full chain.**

**Article 30 — Key contractual provisions.** This is the article that will land in your contract redlines.

*Art 30(1):* rights and obligations clearly allocated **in writing**; the **full contract shall include the SLAs and be documented in one written document**, available on paper or in another downloadable, durable and accessible format. *(→ One document. Side letters and scattered order forms are non-compliant.)*

*Art 30(2) — minimum elements for **all** ICT contracts (nine items):*
- **(a)** clear and complete description of all functions and ICT services, indicating **whether subcontracting of a critical/important function (or material parts) is permitted** and the conditions applying;
- **(b)** **the locations (regions or countries) where functions/services are provided and where data is processed, including storage location**, plus a requirement to **notify the financial entity in advance of any change**;
- **(c)** provisions on **availability, authenticity, integrity and confidentiality** of data, including personal data;
- **(d)** provisions ensuring **access, recovery and return in an easily accessible format** of personal and non-personal data on insolvency, resolution, discontinuation of business, or termination;
- **(e)** **service level descriptions**, including updates and revisions;
- **(f)** obligation on the provider to **assist at no additional cost (or at an ex-ante determined cost) when an ICT incident related to the service occurs**;
- **(g)** obligation to **fully cooperate with competent authorities and resolution authorities**, including persons appointed by them;
- **(h)** **termination rights and minimum notice periods**;
- **(i)** conditions for the provider's **participation in the financial entity's ICT security awareness programmes and digital operational resilience training** (per Art 13(6)).

*Art 30(3) — additional mandatory elements where the service supports a **critical or important function**:*
- **(a)** full SLAs with **precise quantitative and qualitative performance targets** enabling effective monitoring and corrective action;
- **(b)** notice periods and reporting obligations, including **notification of any development that might materially impact the provider's ability to meet SLAs**;
- **(c)** requirements to **implement and test business contingency plans** and maintain ICT security measures, tools and policies at an appropriate level;
- **(d)** obligation to **participate and fully cooperate in the financial entity's TLPT** (threat-led penetration testing, Arts 26–27);
- **(e)** **the right to monitor on an ongoing basis**, entailing: (i) **unrestricted rights of access, inspection and audit** by the financial entity, an appointed third party, **and the competent authority**, with the right to take copies of relevant on-site documentation, *"the effective exercise of which is not impeded or limited by other contractual arrangements or implementation policies"*; (ii) the right to agree alternative assurance levels where other clients' rights are affected; (iii) the provider's obligation to **fully cooperate during on-site inspections and audits** by competent authorities, the Lead Overseer, the financial entity or an appointed third party; (iv) the obligation to provide details on **scope, procedures and frequency** of such inspections and audits;
- **(f)** **exit strategies**, in particular a **mandatory adequate transition period** during which the provider continues providing the functions/services, allowing the financial entity to migrate to another provider or in-house solutions.

*Art 30(3), second subparagraph — the microenterprise derogation, which matters for a tiny vendor's small customers:* *"By way of derogation from point (e), the ICT third-party service provider and the financial entity that is a **microenterprise** may agree that the financial entity's rights of access, inspection and audit can be **delegated to an independent third party, appointed by the ICT third-party service provider**, and that the financial entity is able to request information and assurance on the ICT third-party service provider's performance from the third party at any time."* **→ This is the mechanism by which a small vendor can substitute a SOC 2 / ISO 27001 report for direct customer audit rights.** It applies only where the customer is a microenterprise.

*Art 30(4):* parties *"shall consider the use of standard contractual clauses developed by public authorities for specific services."*

*Art 30(5):* ESAs to develop RTS on subcontracting elements in Art 30(2)(a), submitted to the Commission by 17 July 2024.

**Article 31 — Designation of critical ICT third-party service providers (CTPPs).**
- **Art 31(1):** the ESAs, through the Joint Committee and on recommendation of the **Oversight Forum**, designate CTPPs and appoint a **Lead Overseer**.
- **Art 31(2) — designation criteria:** (a) **systemic impact** on stability, continuity or quality of financial services if the provider failed, taking into account the number of financial entities and total assets served; (b) **systemic character/importance of the reliant financial entities** (number of G-SIIs/O-SIIs, and their interdependence with other financial entities); (c) **reliance on the provider for critical or important functions**, *"irrespective of whether financial entities rely on those services directly or indirectly, through subcontracting arrangements"*; (d) **degree of substitutability** — lack of real alternatives, market share, technical complexity/sophistication including proprietary technology, and difficulty of migrating data and workloads.
- **Art 31(3):** where the provider belongs to a group, criteria are assessed on the group as a whole.
- **Art 31(5):** notification; provider may submit a **reasoned statement within 6 weeks**; oversight starts no later than one month after notification; **the provider must notify its financial-entity clients of the designation**.
- **Art 31(8) — exclusions:** designation does not apply to (i) financial entities providing ICT services to other financial entities; (ii) providers subject to oversight frameworks supporting TFEU Art 127(2) tasks; (iii) **ICT intra-group service providers**; (iv) **providers supplying ICT services solely in one Member State to financial entities active only in that Member State**.
- **Art 31(9):** ESAs to **establish, publish and update yearly the list of CTPPs at Union level**.
- **Art 31(11):** a non-designated provider **may apply to be designated** as critical; decision within 6 months.
- **Art 31(12):** financial entities may only use a **third-country CTPP** if it has **established a subsidiary in the Union within 12 months following designation**.

**Reality check:** a 1–3 person EA vendor will **never** be designated critical. The Art 31(2) criteria are about systemic impact measured in numbers of financial entities and total assets served, G-SII/O-SII reliance, and non-substitutability. The first CTPP list was published **18 November 2025** and reportedly names **19 providers** — AWS, Microsoft, Google Cloud, Deutsche Telekom, Oracle, SAP, IBM, Accenture, Bloomberg, Capgemini and others. **UNVERIFIED against the ESA primary list** — the EBA and ESMA pages I attempted returned HTTP 404/empty, and the 19-provider figure comes from a secondary consultancy guide (<https://www.surecloud.com/resource-hub/dora-compliance-guide>). The **existence** of a published Art 31(9) list in late 2025 is consistent across multiple secondary sources; the exact count and membership are not primary-verified here.

### 4.6 The Register of Information and the ESA implementing technical standards

**Legal basis:** **Article 28(9)**, second subparagraph, of Regulation (EU) 2022/2554.

**Instrument: Commission Implementing Regulation (EU) 2024/2956 of 29 November 2024** *"laying down implementing technical standards for the application of Regulation (EU) 2022/2554 ... with regard to standard templates for the register of information."*
- OJ publication: **2 December 2024** (L series, 2024/2956)
- URLs: <https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32024R2956> · ELI: <http://data.europa.eu/eli/reg_impl/2024/2956/oj>
- **Entry into force:** *"on the twentieth day following that of its publication in the Official Journal"* → approximately **22 December 2024**. It is *"binding in its entirety and directly applicable in all Member States."*
- Recital (1) states the purpose: the register is *"essential for the financial entities' internal ICT risk management, for the effective supervision of the financial entities by their competent authorities, and for the establishment and conduct of oversight of the critical ICT third-party providers by the Lead Overseer,"* and for the annual CTPP designation process.

**The standard templates (Annex I) — verified verbatim from the regulation's Article 1:**

| Template | Content |
|---|---|
| **B_01.01** | General information on the financial entity maintaining the register (entity / sub-consolidated / consolidated) |
| **B_01.02** | General information on the entities in the consolidation |
| **B_01.03** | Identification of branches of financial entities located outside the home country |
| **B_02.01** | General information on the contractual arrangements |
| **B_02.02** | Specific information on the contractual arrangements |
| **B_02.03** | Links between intra-group contractual arrangements and arrangements with non-group ICT TPPs, using contractual reference numbers, where part of the supply chain is intra-group |
| **B_03.01** | Entities signing the contractual arrangements with the direct ICT TPPs |
| **B_03.02** | Identification of the ICT TPPs signing the contractual arrangements |
| **B_03.03** | Entities signing the arrangements for providing ICT services to other entities in the consolidation |
| **B_04.01** | Entities making use of the ICT services provided |
| **B_05.01** | Direct ICT TPPs **and subcontractors** |
| **B_05.02** | The ICT **service supply chain** |
| **B_06.01** | Identification of functions |
| **B_07.01** | Assessment of the ICT services supporting a **critical or important function** or material parts thereof |

Notable data requirements confirmed in the text: the **date of entry into force of the contractual arrangement using ISO 8601 (yyyy–mm–dd)**; **LEI** identifiers for financial entities and providers (with EUID used as specified in Art 9 of CIR (EU) 2021/1042); and for **B_07.01**, substitutability is captured with a field where **"not substitutable" or "highly complex substitutability"** triggers additional mandatory reporting (B_07.01.0060 mandatory in that case). All ICT TPPs in the same supply chain share the same **contractual arrangement reference number**.

**First reporting cycle (verified):** The **Joint ESA decision published 8 November 2024** required competent authorities to submit registers of information to the ESAs **by 30 April 2025**. National example — **CSSF (Luxembourg)**, *"DORA – Submission timeframe for register of information – eDesk Portal open as of 1 April 2025"* (<https://www.cssf.lu/en/2025/04/dora-submission-timeframe-for-register-of-information-edesk-portal-open-as-of-1-april-2025/>): financial entities submitted to the CSSF **between 1 and 15 April 2025**, with a **reference date of 31 March 2025**; resubmissions before 30 April 2025; ESAs ran a second validation round during May 2025. Files must be **plain CSV enclosed in a .zip** with a predefined folder structure and naming convention. Reporting is **at least yearly** (Art 28(3)), so expect a recurring annual cycle.

**→ What this means for you as a vendor:** your customer's compliance team must populate B_02.01/B_02.02/B_05.01/B_05.02/B_07.01 with data **about your contract and your subcontracting chain**. The practical move is to pre-empt this: maintain a standing "DORA data sheet" with your legal entity name and LEI (if any), registered address, the exact service description, all processing/storage locations, your subcontractor list, whether the service supports a critical or important function, and substitutability/exit information. This is cheap to produce and makes you an easy vendor to keep.

### 4.7 DORA penalties — a correction worth noting

**Verified from the DORA text:**
- **Art 35(6)–(8)** applies to **critical** ICT third-party service providers only: on non-compliance with Lead Overseer measures, after at least 30 calendar days' notice, the Lead Overseer adopts a decision imposing a **periodic penalty payment**, on a **daily basis**, for **no more than six months**, of up to **1% of the average daily worldwide turnover** of the CTPP in the preceding business year.
- **Art 50** (Administrative penalties and remedial measures) requires Member States to lay down penalties and confers powers on competent authorities including: ordering cessation of conduct; requiring temporary or permanent cessation of practices; **"adopt any type of measure, including of pecuniary nature"**; requiring data traffic records; and issuing public notices identifying the person and the breach. Art 50(5) extends measures to **members of the management body and other responsible individuals**.
- **Art 51** governs exercise of those powers; **Art 52** allows Member States to use criminal penalties instead; **Art 53** covers publication of penalties.

**UNVERIFIED / likely incorrect as commonly stated:** the widely repeated figures *"financial entities face fines of up to 2% of total annual worldwide turnover or €10 million, and individual senior managers up to €1 million"* (e.g. SureCloud, <https://www.surecloud.com/resource-hub/dora-compliance-guide>) are **NOT in Articles 50–53 of DORA**. DORA leaves penalty amounts to Member States' national law. Those numbers closely resemble GDPR/other-sector figures and should not be quoted as DORA penalties without checking the relevant national implementing law. **Treat as UNVERIFIED.**

---

## 5. Verdicts: realistically adoptable for a 1–3 person team?

### SOC 2 — **ADOPTABLE, but only in a narrow-scope, staged form. Realistic. Best first credential if your buyers are US-centric.**

**Verdict: GO — as SOC 2 Type II, Security (Common Criteria) only, 3-month initial window, narrow system boundary.**

- **Why it works at this size:** Security-only scoping means **33 controls** — genuinely tractable for three people, most of which are process and configuration hygiene rather than engineering projects. There is no certification body, no accreditation, no mandatory ISMS — just a CPA firm testing controls you already largely need.
- **Realistic year-one cost: $25,000–$45,000** (audit $15K–$25K + pentest $5K–$15K + readiness $3K–$8K + tooling $0–$7K). Recurring: **$20,000–$35,000/yr**.
- **Realistic timeline: 5–7 months** to a Type II report (2–4 weeks scoping/readiness → 4–6 weeks to Type I → 3-month observation window → 4–6 weeks reporting).
- **The binding constraint is not money — it is founder hours.** 10–20 hrs/week for 2–3 months is a real fraction of a 3-person team. Budget for it explicitly or it will slip.
- **Skip the automation platform initially.** At $7K–$33K/yr, Vanta/Drata/Secureframe are poor value for a 3-person team with a small control set. A disciplined spreadsheet + a good auditor is defensible for year one; revisit at renewal if headcount grows.
- **Do not run on Type I + bridge letters long-term.** Sophisticated buyers want an unbroken chain of Type II reports. Type I is a 4–8 week bridge to a deal, not a destination.
- **Do vet your auditor.** Given the AICPA's 2026 public warnings about "fast and easy" SOC 2 and unlicensed/un-peer-reviewed firms, choose a CPA firm that is **enrolled in peer review** and can show SOC 2 reports that have survived buyer scrutiny. A cheap report from a questionable firm is worse than no report.

### ISO/IEC 27001:2022 — **ADOPTABLE, and arguably the better long-term fit — but heavier in process overhead. Best first credential if your buyers are EU/UK/APAC or EU-regulated.**

**Verdict: GO, but plan for 6–9 months and accept genuine management-system overhead.**

- **Why it fits:** ISO 27001 has no headcount floor and no minimum control set — the **Statement of Applicability** lets you exclude controls that don't apply, with justification. A cloud-only, single-product vendor can legitimately run a lean ISMS.
- **The hard constraint:** **Clauses 4–10 cannot be excluded** (verified from the ISO scope abstract). You must have a documented ISMS, risk assessment and treatment, competence records, internal audit, and management review. For a 3-person team, "internal audit" and "management review" mean **one founder auditing the others' work and minuting a review meeting** — legal, common, and cheap, but it must actually happen and be evidenced.
- **Realistic year-one cost: $12,000–$30,000** (audit $8K–$18K + gap analysis $5K–$6K + tooling $0–$7K + pentest $5K). Recurring: **$8,000–$15,000/yr** (surveillance ~$7.5K + tooling/training).
- **Realistic timeline: 5–9 months** — 3–6 months readiness, then Stage 1 → Stage 2.
- **Certify directly to :2022.** The 2013 transition window closed **31 October 2025**; there is no legacy decision to make. Only work with a **certification body accredited for ISO/IEC 27001:2022**.
- **A.5.23 (cloud services), A.5.30 (ICT readiness for business continuity), and A.8.25–A.8.31 (secure development)** are the controls that will consume most of your effort — and conveniently, they are exactly what a broker or prop firm's technical reviewer will probe.
- **If you must choose one:** SOC 2 if your pipeline is US broker-dealers/prop firms; **ISO 27001 if your pipeline is EU/UK** — because it is the standard DORA Art 28(5) points at ("most up-to-date and highest quality information security standards"), and it is recognised in the EU in a way SOC 2 is not. **The cheapest correct answer for a 3-person team is usually one, not both**, with a mapped control set so the second follows in 12–18 months.

### DORA-readiness — **HIGHLY ADOPTABLE. This is a contract-and-paperwork exercise, not a certification. Weeks, not months.**

**Verdict: DO THIS FIRST — it is by far the highest return per hour of the three, and it is a prerequisite for selling to any EU financial entity.**

- **You do not need to "comply with DORA."** You are not a financial entity; you will never be a designated CTPP. DORA reaches you **only through your customers' contracts and due diligence**.
- **What to actually do, in priority order:**
  1. **Build a "DORA data sheet"** covering the Art 30(2) and register-of-information fields: legal entity name and LEI (if any), exact service description, **all locations where services are provided and data is processed/stored** (Art 30(2)(b)), full **subcontractor list** (Art 30(2)(a), Art 29), whether the service supports a critical or important function, and substitutability/exit information (template B_07.01). **Cost: a day or two.**
  2. **Update your standard contract** to include the Art 30(2) nine elements and, if you serve critical/important functions, the Art 30(3) additional elements. Expect to concede **audit and inspection rights** (Art 30(3)(e)) — but note the **microenterprise derogation** in Art 30(3): for microenterprise customers you can offer a **SOC 2 / ISO 27001 report from an independent third party** in place of direct audit rights. **This is the strongest single argument for getting one of the two certifications.**
  3. **Write a short business continuity / exit plan** and be ready to describe data return in an accessible format on termination or insolvency (Art 30(2)(d), Art 30(3)(f)). Subcontract a real DR plan, not a paragraph.
  4. **Set up incident notification** — commit to notifying customers of material incidents, and note that you may be asked to assist **at no additional cost or at an ex-ante determined cost** (Art 30(2)(f)). Price this into contracts up front rather than absorbing it later.
  5. **Be ready for annual repetition** — the register of information is reported **at least yearly** (Art 28(3)), and your customers will re-ask.
- **Cost: near zero in cash; 3–10 working days of effort.** The expensive parts (audit rights, TLPT participation under Art 30(3)(d), full SLAs with quantitative targets under Art 30(3)(a)) are **contractual concessions, not projects** — decide your positions deliberately rather than conceding them in a redline.
- **The trap to avoid:** treating DORA as a certification to be purchased. It is not. Vendors selling "DORA certification" are selling training. **There is no DORA certification.** What your customers need from you is contractual compliance and honest, well-organised evidence — which a SOC 2 Type II or ISO 27001 certificate then underwrites.

### One-line summary

| | Cost (yr 1) | Time to first artifact | Recurring | Verdict for 1–3 people |
|---|---|---|---|---|
| **DORA-readiness** | ~$0 | **1–2 weeks** | ~0 | **Do now.** Contract + data sheet. Unlocks EU financial-entity conversations. |
| **SOC 2 Type II** (Security only, 3-mo) | **$25K–$45K** | **5–7 months** | $20K–$35K/yr | **Do if US-centric buyers.** Most recognised by prop firms/brokers. |
| **ISO/IEC 27001:2022** | **$12K–$30K** | **5–9 months** | $8K–$15K/yr | **Do if EU/UK buyers.** Cheaper, but real ISMS process overhead. |

---

## Appendix — full source list

**AICPA / SOC 2**
- <https://www.aicpa-cima.com/resources/landing/system-and-organization-controls-soc-suite-of-services>
- <https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2>
- <https://www.aicpa-cima.com/resources/download/2017-trust-services-criteria-with-revised-points-of-focus-2022>
- <https://www.aicpa-cima.com/resources/article/esi-soc>
- <https://www.journalofaccountancy.com/issues/2026/feb/promises-of-fast-and-easy-threaten-soc-credibility/>
- <https://www.journalofaccountancy.com/issues/2026/may/aicpa-guides-peer-reviewers-to-address-soc-2-risks/>
- <https://www.vanta.com/collection/soc-2/soc-2-trust-service-criteria>
- <https://www.vanta.com/collection/soc-2/soc-2-type-1-vs-type-2>
- <https://www.urmconsulting.com/faq/how-long-is-the-soc-2-type-2-reporting-period>
- <https://www.trustcloud.ai/soc-2/what-is-a-soc-2-bridge-letter-with-examples/>
- <https://compyl.com/blog/what-is-the-soc-2-security-criteria/>
- <https://compyl.com/blog/how-much-does-soc-2-compliance-cost/>
- <https://safeguard.sh/resources/blog/how-much-does-a-soc-2-audit-cost>
- <https://soc2auditors.org/soc-2-auditors-usa/>
- <https://secureframe.com/pricing>
- <https://www.vanta.com/pricing>
- <https://drata.com/learn/soc-2/compliance-for-startups>

**ISO/IEC 27001**
- <https://www.iso.org/standard/27001.html> · <https://www.iso.org/standard/82875.html> *(403 to fetchers)*
- <https://webstore.iec.ch/en/publication/79694>
- <https://dgsm.gso.org.sa/store/standards/iso:pub:std:IS:82875/?lang=en>
- <https://store.sfs.fi/en/isoiec-27001-2022amd-1-2024> · <https://store.sfs.fi/en/isoiec-27001-2013-3>
- <https://webshop.ds.dk/en/standard/M384109/ds-en-iso-iec-27001-2023-a1-2024>
- <https://secureframe.com/hub/iso-27001/controls>
- <https://www.surecloud.com/resource-hub/iso-27001-annex-a-enterprise-implementation>
- <https://www.isms.online/iso-27001/annex-a-controls/>
- <https://urmconsulting.com/blog/the-timeline-for-transitioning-to-iso-27001-2022>
- <https://iaf.nu/en/iaf-documents/?cat=8> · <https://globalaccreditationcooperationincorporated.org>
- <https://safeguard.sh/resources/blog/iso-27001-certification-cost-breakdown>
- <https://www.trustcloud.ai/iso-27001/how-much-does-iso-27001-cost/>
- <https://www.strongdm.com/blog/iso-27001-certification-cost>

**SEC / FINRA**
- <https://www.finra.org/rules-guidance/rulebooks/finra-rules/3110>
- <https://www.finra.org/rules-guidance/rulebooks/finra-rules/3120>
- <https://www.finra.org/rules-guidance/notices/21-29>
- <https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/third-party-risk>
- <https://www.finra.org/rules-guidance/guidance/reports/2025-finra-annual-regulatory-oversight-report/third-party-risk>
- <https://www.finra.org/rules-guidance/guidance/sec-regulation-s-p-compliance-date-reminder-20251114>
- <https://www.acaglobal.com/industry-insights/finra-releases-2026-oversight-report-highlighting-ai-cybersecurity-and-compliance-risks/>
- <https://www.sec.gov/newsroom/press-releases/2025-132-sec-division-examinations-announces-2026-priorities> *(403 to fetchers)*
- <https://kpmg.com/us/en/articles/2025/sec-2026-priorities-examinations-and-perspectives-reg-alert.html>
- <https://www.govinfo.gov/content/pkg/FR-2025-06-17/html/2025-11110.htm> *(withdrawal of S7-06-23)*
- <https://www.sec.gov/rules-regulations/2025/06/cybersecurity-risk-management-rule-broker-dealers-clearing-agencies-major-security-based-swap>
- <https://www.ecfr.gov/current/title-17/chapter-II/part-240/subject-group-ECFR7de5c9d3c6c6c6c/section-240.17a-4>

**DORA**
- <https://eur-lex.europa.eu/eli/reg/2022/2554/oj>
- <https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32022R2554>
- <https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32022R2554>
- <https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32024R2956> · <http://data.europa.eu/eli/reg_impl/2024/2956/oj>
- <https://www.cssf.lu/en/2025/04/dora-submission-timeframe-for-register-of-information-edesk-portal-open-as-of-1-april-2025/>
- <https://www.surecloud.com/resource-hub/dora-compliance-guide>
