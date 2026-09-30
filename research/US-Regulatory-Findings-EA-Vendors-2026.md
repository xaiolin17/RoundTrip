# US Regulatory Findings — Automated Trading Software (MT5 EAs) & Signals Vendors

**Research date:** 2026-09-20 · **Target year:** 2026 · All sources verified HTTP 200 on 2026-09-20 unless marked UNVERIFIED.
**Primary sources used:** ecfr.gov, cftc.gov, nfa.futures.org, law.cornell.edu, govinfo.gov.

---

## 0. THREE CORRECTIONS TO THE BRIEF (read first)

These materially change the compliance analysis and contradict premises in the request.

| Premise in brief | Finding |
|---|---|
| **"2-36(d) — hypothetical performance record requirement for forex … 5 years … monthly record of all hypothetical trades"** | **WRONG PARAGRAPH.** Current NFA Compliance Rule **2-36(d) is "Doing Business with Non-Members"** — a Bylaw 1101-style prohibition on carrying forex accounts for non-NFA-members. The **forex hypothetical-results requirement is 2-36(h)**. There is **no "monthly record of all hypothetical trades"** anywhere in NFA's rules or interpretive notices, and **no 5-year hypothetical performance record**. The only 5-year figure in Rule 2-29 is the **actual** performance look-back in **2-29(c)(3)**. See §2. |
| **"The 2019 CFTC/NFA joint interpretive notice on 'Use of Promotional Material' … issued 29 August 2019"** | The 29 Aug 2019 document at the cited NFA URL is **not a joint interpretive notice**. It is **NFA's submission letter to the CFTC Secretary** under CEA §17(j), transmitting proposed redline amendments (additions underscored, deletions struck through). Its content is the *redline of the rules and notices*, not a clean notice. The underlying notices (9003, 9025, 9033, etc.) are what became effective. See §3. |
| **"the CFTC's 2024 amendments to Part 4 (there was a 2024 rulemaking — 89 FR 78813)"** | The correct citation is **89 FR 78793** (Vol. 89, No. 187, Thu. Sept. 26, 2024), spanning **78793–78815**. 89 FR 78813 is a page *within* that document. It is **not** a CTA-registration rulemaking. See §5.4. |

---

## 1. NFA COMPLIANCE RULE 2-29 — FULL TEXT

**Source (primary):** https://www.nfa.futures.org/rulebooksql/rules.aspx?Section=4 (HTML) · https://www.nfa.futures.org/rulebooksql/rulespdf.aspx?Section=4 (PDF)
Both fetched successfully (HTTP 200); PDF text extracted via `pdftotext -layout`.

**Adoption/amendment history as printed in the rulebook:**
> "[Adopted effective November 19, 1985. Effective date of Amendments: February 1, 1996 August 29, 1996 March 28, 2000 July 24, 2000 December 4, 2000 August 21, 2001 May 1, 2004 February 1, 2010 January 1, 2020 April 22, 2020 and **July 21, 2025**.]"

⚠️ **Note the July 21, 2025 amendment** — after the 2019/2020 amendments. Most secondary commentary describes the pre-2025 text.

### Rule 2-29(a) — General Prohibition
> "No FCM, IB, CPO or CTA Member or Associate shall make any communication related to its commodity interest business that:
> (1) operates as a fraud or deceit
> (2) employs or is part of a high-pressure approach or
> (3) makes any statement that commodity interest trading is appropriate for all persons."

### Rule 2-29(b) — Content of Promotional Material
> "No FCM, IB, CPO or CTA Member or Associate shall use any promotional material that:
> **(1)** is likely to deceive the public
> **(2)** contains any material misstatement of fact or which the Member or Associate knows omits a fact if the omission makes the promotional material misleading
> **(3)** **mentions the possibility of profit unless accompanied by an equally prominent discussion of the risk of loss**
> **(4)** **includes any reference to actual past trading profits without mentioning that past results are not necessarily indicative of future results**
> **(5)** includes any specific numerical or statistical information about the past performance of any actual accounts (including rate of return) unless:
>   (i) such information is and can be demonstrated to NFA to be representative of the actual performance for the same time period of all reasonably comparable accounts
>   (ii) the performance is presented net of all commissions, fees and expenses (see Interpretive Notice 9003 for a limited exception) and
>   (iii) in the case of rate of return figures, such figures are calculated in a manner consistent with CFTC Regulation 4.25 for commodity pools and with CFTC Regulation 4.35, as modified by NFA Compliance Rule 2-34(a), for figures based on separate accounts or
> **(6)** includes a testimonial that is not representative of all reasonably comparable accounts, does not prominently state that the testimonial is not indicative of future performance or success, and does not prominently state that it is a paid testimonial (if applicable)."

### Rule 2-29(c) — Hypothetical Results

**(c)(1)** — Mandatory disclaimer (see §1.1 for verbatim text), required of:
> "Any FCM, IB, CPO or CTA Member or Associate who uses promotional material which includes a measurement or description of or makes any reference to hypothetical performance results which could have been achieved had a particular trading system of the FCM, IB, CPO or CTA Member or Associate been employed in the past"

**(c)(2)** — Multi-advisor composite: a *different* prescribed disclaimer must be used **instead of** the (c)(1) disclaimer (verbatim at §1.2).

**(c)(3)** — Actual-results pairing requirement:
> "…must include in the promotional material comparable information regarding:
> (i) past performance results of all customer accounts directed by the FCM, IB, CPO or CTA Member pursuant to a power of attorney over at least **the last five years** or over the entire performance history if less than five years
> (ii) if the FCM, IB, CPO or CTA Member has less than one year of experience in directing customer accounts, past performance results of its proprietary trading over at least the last five years or over the entire performance history if less than five years."

**(c)(4)** — The three-month bar:
> "No FCM, IB, CPO or CTA Member or Associate may use promotional material which includes a measurement or description of or makes any reference to hypothetical performance results which could have been achieved had a particular trading system of the FCM, IB, CPO or CTA Member or Associate been employed in the past **if the FCM, IB, CPO or CTA Member or Associate has three months of actual trading results for that system**."

**(c)(5)** — Cross-reference: must adhere to Interpretive Notice 9025.

**(c)(6)** — QEP carve-out: (c)(3) and (c)(4) restrictions and related parts of IN 9025 "shall not apply to promotional material directed exclusively to persons who meet the standards of a 'Qualified Eligible Person' (QEP) under CFTC Regulation 4.7."

**(c)(7)** — **Extracted performance / QEP:** for QEP-only material referencing "extracted performance (i.e., performance where a Member or Associate highlights one or more components of its overall past trading results)", the Member may use either the (c)(1) disclaimer "or other language that appropriately describes the performance shown and the limitations of such performance."

**(c)(8)** — Composite performance record, QEP-only: same either/or option with the (c)(2) disclaimer.

### Rule 2-29(d) — Statements of Opinion
> "Statements of opinion included in promotional material of an FCM, IB, CPO or CTA Member must be clearly identifiable as such and must have a reasonable basis in fact."

### Rule 2-29(e) — Supervisory Requirements
> "Every FCM, IB, CPO and CTA Member shall adopt and enforce written procedures to supervise its Associates and employees for compliance with this Rule. **Prior to its first use, all promotional material (as defined in paragraph (i) of this Rule) shall be reviewed and approved, in writing, by an officer, general partner, sole proprietor, branch office manager or other supervisory employee other than the individual who prepared such material** (unless such material was prepared by the only individual qualified to review and approve such material). If the Member is registered as a broker-dealer under Section 15(b)(11) of the Exchange Act and the promotional material specifically refers to security futures products, the individual reviewing and approving the promotional material must be a designated security futures principal."

### Rule 2-29(f) — Recordkeeping  ← **the recordkeeping paragraph the brief asked about**
> "Copies of all promotional material along with a record of the review and approval required under paragraph (e) of this Rule and supporting materials for any results described under paragraphs (b)(5)-(6) or (c) of this Rule must be maintained by each FCM, IB, CPO and CTA Member and **be available for examination for the periods specified in CFTC Regulation 1.31, measured from the date of the last use**. Each Member who uses promotional material of the types described in paragraph (b)(5)-(6) or (c) of this Rule **shall demonstrate the basis for any reported results to NFA upon request**."

**Retention period (CFTC Reg 1.31, eCFR):** https://www.ecfr.gov/current/title-17/chapter-I/part-1/section-1.31
- Records kept "for a period of **not less than five years** from the date on which the record was created."
- "A records entity shall keep regulatory records exclusively created and maintained on paper **readily accessible for no less than two years**."
→ **Practical answer: 5 years from date of last use; first 2 years readily accessible.**

### Rule 2-29(g) — Filing with NFA
> "NFA may require any Member FCM, IB, CPO and CTA for any specified period to file copies of all promotional material with NFA promptly after its first use."

### Rule 2-29(h) — Audio and Video Promotional Material ← **pre-approval requirement**
> "No FCM, IB, CPO or CTA Member shall use or directly benefit from any promotional material that uses audio or video content to make any specific trading recommendation or refer to or describe the extent of any profit obtained in the past or that can be achieved in the future **unless the Member submits the advertisement to NFA's Promotional Material Review Team for its review and approval at least 10 days prior to first use** or such shorter period as NFA may allow in particular circumstances."

### Rule 2-29(i) — Definitions
> "**(1)** For purposes of this Rule 'promotional material' includes: (i) any text of a standardized oral presentation, or any communication for publication in any newspaper, magazine or similar medium, or for broadcast over television, radio, internet or other electronic medium, which is disseminated or directed to the public concerning a commodity interest account, agreement or transaction (ii) any standardized form of report, letter, electronic communication (e.g., email, text message or instant message), circular, memorandum, presentation or publication that is disseminated or directed to the public concerning a commodity interest account, agreement or transaction and (iii) any other written material disseminated or directed to the public for the purpose of soliciting a commodity interest account, agreement or transaction.
> **(2)** 'Commodity interest account, agreement or transaction' includes commodity interest accounts, transactions and orders, commodity pool participations, agreements to direct or guide trading in commodity interest accounts, and **agreements and transactions involving the sale, through publications or otherwise, of non-personalized trading advice concerning commodity interests**."

⚠️ **(i)(2) is the hook that captures signals/EA vendors**: "sale … of non-personalized trading advice" is expressly within "commodity interest account, agreement or transaction."

### Rule 2-29(j) — Security Futures Products
13 enumerated sub-requirements (j)(1)–(j)(13), including (j)(9) trading-program cumulative performance history / "unproven" statement, and (j)(13) 10-day pre-use NFA submission for mass-media material. Full text available at the Section=4 URL. *(Only relevant if the vendor's material specifically refers to security futures products.)*

### 1.1 Rule 2-29(c)(1) — PRESCRIBED HYPOTHETICAL DISCLAIMER (VERBATIM)
> "HYPOTHETICAL PERFORMANCE RESULTS HAVE MANY INHERENT LIMITATIONS, SOME OF WHICH ARE DESCRIBED BELOW. NO REPRESENTATION IS BEING MADE THAT ANY ACCOUNT WILL OR IS LIKELY TO ACHIEVE PROFITS OR LOSSES SIMILAR TO THOSE SHOWN. IN FACT, THERE ARE FREQUENTLY SHARP DIFFERENCES BETWEEN HYPOTHETICAL PERFORMANCE RESULTS AND THE ACTUAL RESULTS SUBSEQUENTLY ACHIEVED BY ANY PARTICULAR TRADING PROGRAM.
>
> ONE OF THE LIMITATIONS OF HYPOTHETICAL PERFORMANCE RESULTS IS THAT THEY ARE GENERALLY PREPARED WITH THE BENEFIT OF HINDSIGHT. IN ADDITION, HYPOTHETICAL TRADING DOES NOT INVOLVE FINANCIAL RISK, AND NO HYPOTHETICAL TRADING RECORD CAN COMPLETELY ACCOUNT FOR THE IMPACT OF FINANCIAL RISK IN ACTUAL TRADING. FOR EXAMPLE, THE ABILITY TO WITHSTAND LOSSES OR TO ADHERE TO A PARTICULAR TRADING PROGRAM IN SPITE OF TRADING LOSSES ARE MATERIAL POINTS WHICH CAN ALSO ADVERSELY AFFECT ACTUAL TRADING RESULTS. THERE ARE NUMEROUS OTHER FACTORS RELATED TO THE MARKETS IN GENERAL OR TO THE IMPLEMENTATION OF ANY SPECIFIC TRADING PROGRAM WHICH CANNOT BE FULLY ACCOUNTED FOR IN THE PREPARATION OF HYPOTHETICAL PERFORMANCE RESULTS AND ALL OF WHICH CAN ADVERSELY AFFECT ACTUAL TRADING RESULTS."

**Additional mandatory statement where the Member has <1 year experience:**
> "(THE MEMBER) HAS HAD LITTLE OR NO EXPERIENCE IN TRADING ACTUAL ACCOUNTS FOR ITSELF OR FOR CUSTOMERS. BECAUSE THERE ARE NO ACTUAL TRADING RESULTS TO COMPARE TO THE HYPOTHETICAL PERFORMANCE RESULTS, CUSTOMERS SHOULD BE PARTICULARLY WARY OF PLACING UNDUE RELIANCE ON THESE HYPOTHETICAL PERFORMANCE RESULTS."

### 1.2 Rule 2-29(c)(2) — COMPOSITE (MULTI-ADVISOR) DISCLAIMER (VERBATIM)
> "THIS COMPOSITE PERFORMANCE RECORD IS HYPOTHETICAL AND THESE TRADING ADVISORS HAVE NOT TRADED TOGETHER IN THE MANNER SHOWN IN THE COMPOSITE. HYPOTHETICAL PERFORMANCE RESULTS HAVE MANY INHERENT LIMITATIONS, SOME OF WHICH ARE DESCRIBED BELOW. NO REPRESENTATION IS BEING MADE THAT ANY MULTI-ADVISOR MANAGED ACCOUNT OR POOL WILL OR IS LIKELY TO ACHIEVE A COMPOSITE PERFORMANCE RECORD SIMILAR TO THAT SHOWN. IN FACT, THERE ARE FREQUENTLY SHARP DIFFERENCES BETWEEN A HYPOTHETICAL COMPOSITE PERFORMANCE RECORD AND THE ACTUAL RECORD SUBSEQUENTLY ACHIEVED.
>
> ONE OF THE LIMITATIONS OF A HYPOTHETICAL COMPOSITE PERFORMANCE RECORD IS THAT DECISIONS RELATING TO THE SELECTION OF TRADING ADVISORS AND THE ALLOCATION OF ASSETS AMONG THOSE TRADING ADVISORS WERE MADE WITH THE BENEFIT OF HINDSIGHT BASED UPON THE HISTORICAL RATES OF RETURN OF THE SELECTED TRADING ADVISORS. THEREFORE, COMPOSITE PERFORMANCE RECORDS INVARIABLY SHOW POSITIVE RATES OF RETURN. ANOTHER INHERENT LIMITATION ON THESE RESULTS IS THAT THE ALLOCATION DECISIONS REFLECTED IN THE PERFORMANCE RECORD WERE NOT MADE UNDER ACTUAL MARKET CONDITIONS AND, THEREFORE, CANNOT COMPLETELY ACCOUNT FOR THE IMPACT OF FINANCIAL RISK IN ACTUAL TRADING. FURTHERMORE, THE COMPOSITE PERFORMANCE RECORD MAY BE DISTORTED BECAUSE THE ALLOCATION OF ASSETS CHANGES FROM TIME TO TIME AND THESE ADJUSTMENTS ARE NOT REFLECTED IN THE COMPOSITE."

**<1 year allocating experience add-on:**
> "(THE MEMBER) HAS HAD LITTLE OR NO EXPERIENCE ALLOCATING ASSETS AMONG PARTICULAR TRADING ADVISORS. BECAUSE THERE ARE NO ACTUAL ALLOCATIONS TO COMPARE TO THE PERFORMANCE RESULTS FROM THE HYPOTHETICAL ALLOCATION, CUSTOMERS SHOULD BE PARTICULARLY WARY OF PLACING UNDUE RELIANCE ON THESE RESULTS."

### 1.3 ⚠️ On the specific prohibited words: "guaranteed / insured / safe / secure / risk-free / no-risk / hedge / safe harbor"

**NOT FOUND in Rule 2-29 itself, nor in IN 9003, 9025, 9033, 9037, 9039, or 9043.** There is no enumerated banned-word list in NFA Compliance Rule 2-29. **UNVERIFIED as a rule-text claim.**

What *does* exist is functionally-equivalent prohibition through:
- **Rule 2-29(b)(1)–(2)** (likely to deceive / material misstatement / misleading omission) — the operative hook.
- **Rule 2-29(b)(3)** (profit mention requires equally prominent risk-of-loss discussion).
- **NFA Rule 2-4 — Just and Equitable Principles of Trade** (the "high standards of commercial honor" hook the brief asked for):
  > "Members and Associates shall observe **high standards of commercial honor and just and equitable principles of trade** in the conduct of their commodity futures business and swaps business."
  Source: https://www.nfa.futures.org/rulebooksql/rules.aspx?Section=4
  *(Also NFA Compliance Rule 2-36(c) for forex: "Forex Dealer Members and their Associates shall observe high standards of commercial honor and just and equitable principles of trade in the conduct of their forex business.")*
- **NFA Promotional Material Guide (Dec. 2025), "Limited risk" guidance** — the closest thing to an express prohibition:
  > "Using the term 'limited risk' to imply that the likelihood of loss is limited is highly misleading. Any discussion of limited risk must make it clear that the term refers to the amount of the loss but not the likelihood of loss."
  > Communications indicating options trading involves "Limited risk" or "No margin calls" "[w]ill be considered misleading unless it adequately discloses that such characteristics apply to long options only."
  Source: https://www.nfa.futures.org/members/member-resources/files/promo-material-guide.pdf
- **Forex-specific (Promotional Material Guide, "Forex Related Communications"):**
  > "Members and APs may not represent that they can either **guarantee against any customer losses** or that they can **guarantee only limited customer losses**."
  > "No Member or AP may represent that it offers trading with **'no-slippage'** or that it **guarantees the price at which a transaction will be executed or filled**, unless: [it can demonstrate all orders for all customers were executed at the price initially quoted; and no authority exists to adjust customer accounts so as to change the execution price]."
  > "No Member of AP may represent that forex funds deposited with a Forex Dealer Member (FDM) are given special protection under bankruptcy laws or represent or imply that any assets necessary to satisfy its obligations to customers are **more secure** because that Member keeps some of all of those assets at a regulated entity in the United States or a money center country."
  > "No Member or AP may represent or imply that a customer will have **direct access to the interbank-market**…"
  > "Members and APs may not solicit customers based on the leverage available unless they balance any discussion regarding the advantages of leverage by closely preceding or following it with an equally prominent disclosure that **increasing leverage increases risk**."

**Bottom line for the vendor:** "guaranteed," "risk-free," "safe," "secure," "no-risk" are not separately enumerated, but any of them in promotional material is actionable under 2-29(b)(1)/(2) as "likely to deceive the public" or a "material misstatement of fact," and (b)(3) independently requires an equally prominent risk-of-loss discussion wherever profit is mentioned.

---

## 2. NFA COMPLIANCE RULE 2-36 — REQUIREMENTS FOR FOREX TRANSACTIONS

**Source:** https://www.nfa.futures.org/rulebooksql/rules.aspx?Section=4 (PDF text extracted)
**Amendment history as printed:** "[Adopted effective June 28, 2002. Effective dates of amendments: December 1, 2003 November 30, 2005 February 13, 2007 October 25, 2007 April 1, 2009 October 18, 2010 October 1, 2011 January 4, 2016 March 29, 2017 March 31, 2017 April 5, 2018 September 30, 2019 January 1, 2020 and **March 18, 2026**.]"
⚠️ Note the **March 18, 2026** amendment — very recent.

### Full paragraph map (current text)
| ¶ | Heading |
|---|---|
| (a) | General Prohibition |
| (b) | Fraud and Related Matters — (1)–(6) |
| (c) | **Just and Equitable Principles of Trade** |
| (d) | **Doing Business with Non-Members** |
| (e) | Supervision — (1)–(2) |
| (f) | BASIC Disclosure |
| (g) | **Communications with the Public and Promotional Material** |
| (h) | **Reserved** |
| (i) | Customer Accounts |
| (j) | FDM Chief Compliance Officer |
| (k) | CFTC Forex Regulations |
| (l) | Customer Information and Risk Disclosure — (1)–(9) |
| (m) | Risk Management Program |
| (n) | Public Disclosure by Forex Dealer Members |
| (o) | Disclosure of Transaction Data to Customers |
| (p) | Transaction Disclosures |
| (q) | Scope |
| (r) | Exemptions for Certain Transactions |
| (s) | Definitions — (1)–(5) |

### 2.36(c) — Just and Equitable Principles of Trade (VERBATIM)
> "Forex Dealer Members and their Associates shall observe high standards of commercial honor and just and equitable principles of trade in the conduct of their forex business."

⚠️ **2-36(c) is NOT the forex promotional-material paragraph.** It is the "commercial honor" hook. The brief's premise that 2-36(c) contains the forex risk warning and "substantial risk of loss" language is **incorrect**.

### 2-36(d) — Doing Business with Non-Members (VERBATIM, opening)
> "No Member may carry a forex account for, accept a forex order or account from, handle a forex transaction for or on behalf of, receive compensation (directly or indirectly) for forex transactions from, or pay compensation (directly or indirectly) for forex transactions to any non-Member of NFA, or suspended Member, that is required to be registered with the Commission as an FCM, RFED, IB, CPO, or CTA in connection with its forex activities and that is acting in respect to the account, order, or transaction for a forex customer, a forex pool or participant therein, a forex client of a commodity trading advisor, or any other person unless: (1) the non-Member is a member of another futures association registered under Section 17 of the Act or is exempted from this prohibition by Board resolution or (2) the suspended Member is exempted from this prohibition by the Appeals Committee."

### 2-36(g) — Communications with the Public and Promotional Material (VERBATIM) ← **the real forex promo paragraph**
> "Forex Dealer Members and, as applicable, Associates of Forex Dealer Members must comply with **sections (a) through (h) of NFA Compliance Rule 2-29** and the Interpretive Notices related to these provisions. **The Member Oversight Department may require any Forex Dealer Member for any specified period to file copies of all promotional material with NFA for its review and approval at least 10 days prior to its first use** or such shorter period as NFA may allow."

### 2-36(h) — **Reserved** (VERBATIM, current text)

### 2.1 ⚠️ The forex hypothetical-results requirement — what the 2019 amendment actually did

The **29 Aug 2019 §17(j) submission letter** (https://www.nfa.futures.org/news/PDF/CFTC/08292019-CR-2-29-CR-2-36-Interp-Notices-Use-of-Promotional-Material.pdf) shows the redline. In the *proposed* redline, former paragraph (h) "Hypothetical Results" was **struck through** and the new (h) read:

> **(h) Hypothetical Results Reserved**
> "Any Member who uses promotional material that includes a measurement or description or makes any reference to hypothetical forex transaction performance results that could have been achieved had a particular trading system of the Member or Associate been employed in the past must comply with **Compliance Rule 2-29(c) and the related Interpretive Notice as if the performance results were for transactions in on-exchange futures contracts**."

**Net effect:** forex hypothetical results are governed by **Rule 2-29(c)**, applied as if the forex results were on-exchange futures. The current rulebook prints (h) as **"Reserved."** The substantive obligation therefore lives in **2-29(c)**, not 2-36.

### 2.2 ⚠️ "Hypothetical performance record" — DOES NOT EXIST

Searched exhaustively across four primary sources:
- NFA Rulebook Section 4 (Compliance Rules, incl. Rule 2-36)
- NFA Rulebook Section 9 (all Interpretive Notices)
- NFA Promotional Material Guide (Dec. 2025)
- The 29 Aug 2019 CFTC submission letter

**Result: zero hits for "hypothetical performance record", "monthly record", or "record of all hypothetical" as a defined record type.**
- The only string match is incidental prose in the Promo Guide: "Members or APs who use hypothetical performance records which show…" (i.e., generic reference to a *record of hypothetical results*, not a defined regulatory artifact).
- **No 5-year hypothetical record exists.** The only 5-year requirement is the look-back for **actual** performance under **2-29(c)(3)(i)–(ii)**.
- **No requirement that a hypothetical record be "examined" or "reviewed"** by an accountant or NFA. The obligation is **2-29(f)**: maintain supporting materials and "demonstrate the basis for any reported results to NFA upon request."

**Conclusion: the brief's premise is UNVERIFIED and appears to be a conflation of 2-29(c)(3) (5-year *actual* performance) with 2-29(f) (recordkeeping / demonstrate basis on request).**

### 2.3 Forex risk warning / "substantial risk of loss"

The forex risk disclosure is **not in Rule 2-36 text**; 2-36(l)(4) incorporates it by reference:
> "The risk disclosure to be provided to the customer shall include at least the following: (i) the Risk Disclosure Statement required by **CFTC Regulation 5.5**, if the Member is required by that Regulation to provide it and (ii) the Risk Disclosure Statement required by **CFTC Regulation 4.34**, if the Member is required by that Regulation to provide it."

**CFTC Reg 5.5 prescribed statement (eCFR, VERBATIM opening):**
https://www.ecfr.gov/current/title-17/chapter-I/part-5/section-5.5
> "OFF-EXCHANGE FOREIGN CURRENCY TRANSACTIONS INVOLVE THE LEVERAGED TRADING OF CONTRACTS DENOMINATED IN FOREIGN CURRENCY CONDUCTED WITH A FUTURES COMMISSION MERCHANT OR A RETAIL FOREIGN EXCHANGE DEALER AS YOUR COUNTERPARTY. **BECAUSE OF THE LEVERAGE AND THE OTHER RISKS DISCLOSED HERE, YOU CAN RAPIDLY LOSE ALL OF THE FUNDS YOU DEPOSIT FOR SUCH TRADING AND YOU MAY LOSE MORE THAN YOU DEPOSIT.**"

⚠️ The exact phrase "**substantial risk of loss**" does **not** appear in Rule 2-36 or Reg 5.5. **UNVERIFIED** as a quoted regulatory phrase in these instruments.

### 2.4 Does Rule 2-36 apply to a firm that merely sells forex trading SOFTWARE (not advice)?

**Analysis from primary text:**
- **Rule 2-36(q) Scope:** "This rule governs forex transactions as defined in Bylaw 1507(b)."
- Every operative obligation in 2-36 runs to a "**Forex Dealer Member**" (FDM) or "**Associate of a Forex Dealer Member**" — see (a), (b), (e), (f), (g), (i), (j), (m), (n), (o), (p). "Dealer" is defined in 2-36(s)(3) as a person who holds itself out as a dealer, makes a market, regularly enters into forex transactions as ordinary course for its own account, or is commonly known in the trade as a dealer or market maker.
- **A software/signals vendor that does not make a market, deal, or act as counterparty is not an FDM** and therefore is **not directly subject to Rule 2-36**.
- **However**, 2-36(g) binds FDMs to Rule 2-29(a)–(h), and **NFA Interpretive Notice 9055** makes an NFA Member (e.g., the FDM/IB that executes for the vendor's users) responsible for the vendor's misleading promotional material under **direct, agency, or supervisory** theories. So a software vendor selling into the NFA-member distribution channel is *indirectly* constrained.
- Separately, **NFA Bylaw 1101** prohibits Members from transacting customer business with a non-Member required to be registered. IN 9055 instructs Members to obtain a **counsel letter** from the third-party system developer explaining why registration is not required, and absent that, to require registration/membership or **terminate the relationship**.
- **Independent of 2-36**, a US-facing software/signals vendor's own promotional material is squarely subject to **CFTC Rule 4.41** if it is a CPO/CTA or principal thereof — see §4 — and **Rule 4.41(c)(2)** applies "**[r]egardless of whether the commodity pool operator or commodity trading advisor is exempt from registration under the Act.**"

**Answer: No, Rule 2-36 does not directly reach a pure software vendor; but Rule 4.41 can, and the NFA-member channel imposes indirect responsibility via IN 9055 + Bylaw 1101.**

---

## 3. THE 2019 CFTC/NFA DOCUMENT — WHAT IT ACTUALLY IS

**URL:** https://www.nfa.futures.org/news/PDF/CFTC/08292019-CR-2-29-CR-2-36-Interp-Notices-Use-of-Promotional-Material.pdf (HTTP 200, 306,785 bytes, 153k chars extracted)

**It is a §17(j) submission letter**, not a joint interpretive notice. Header:
> "August 29, 2019 — Via Federal Express and E-mail (Ckirkpatrick@cftc.gov) — Mr. Christopher J. Kirkpatrick, Secretary, Office of the Secretariat, Commodity Futures Trading Commission… **Re: National Futures Association: Proposed Amendments to NFA Compliance Rule 2-29: Communications with the Public and Promotional Material, NFA Compliance Rule 2-36: Requirements for Forex Transactions, Related Interpretive Notices and other Technical Amendments to NFA Requirements**"

Key procedural text:
> "NFA's Board of Directors ('Board') unanimously approved the proposed amendments at its meeting on August 15, 2019."
> "NFA is invoking the 'ten-day' provision of Section 17(j) of the CEA and plans to issue a Notice to Members establishing an effective date for this proposal as early as ten days after receipt of this submission by the Commission…"
> "**PROPOSED AMENDMENTS (additions are underscored and deletions are stricken through)**"

⚠️ **There is no prescribed disclaimer introduced by this document.** The mandatory hypothetical disclaimers are **NFA-prescribed** in Rule 2-29(c)(1)/(c)(2) (see §1.1–1.2), and the separate **CFTC**-prescribed cautionary statement is in **Rule 4.41(b)** (see §4). **Rule 4.41(b)(1)(ii)** expressly allows, as an alternative to the CFTC statement, "[a] statement prescribed pursuant to rules promulgated by a registered futures association pursuant to section 17(j) of the Act" — that is the pathway by which the NFA disclaimers satisfy 4.41(b).

### 3.1 The 2019 amendments — interpretive notices touched
From the letter's amendment list (thirteen interpretive notices): **9003, 9009, 9025, 9033, 9034 (reserved), 9037, 9038, 9039, 9042, 9043, 9053, 9055, 9063**.

### 3.2 Is there a separate 2019 notice on "Fictitious or hypothetical performance" or "Trading Systems"?
**No separate 2019 interpretive notice with those titles exists.** The hypothetical-performance content is consolidated in **IN 9025**; the trading-systems content is in **IN 9055** (2004, revised). **UNVERIFIED / not found.**

---

## 4. NFA INTERPRETIVE NOTICES (primary, current)

Source: https://www.nfa.futures.org/rulebooksql/rules.aspx?Section=9 (HTTP 200)

### IN 9003 — Compliance Rule 2-29: Communications with the Public and Promotional Material
> "(Board of Directors, effective November 19, 1985; revised July 24, 2000; January 1, 2020; April 22, 2020 and **March 18, 2026**.)"

Key holdings:
- **Scope is broad:** "The definition of 'promotional material' set forth in Compliance Rule 2-29 is broad and is intended to apply to **all forms of communication with the public** by an FCM, IB, CPO or CTA Member or Associate without exception if the communication relates in any way to solicitation of an account, agreement or transaction…"
- **Standard for deception:** "(b)(1) bans material likely to deceive the public. **Proof of violation of this subsection does not require proof of a specific intent to deceive.** This Subsection instead places the burden on the Member to determine whether the material is likely to be deceptive in effect."
- **Omissions:** knowledge requirement for omissions, but "**knowledge can be inferred from a pattern of failures to include a material fact**."
- **Equal prominence (b)(3):** "the discussion of the risk of loss is clearly displayed and is **not downplayed or hidden**." Not required to be as long as the profit discussion.
- **Past results (b)(4):** must state past results are not necessarily indicative of future results.
- **Model accounts (b)(5):** "An FCM, IB, CPO or CTA Member or Associate **could not, for example, advertise the performance of a 'model' account unless that performance is representative of all reasonably comparable accounts.**"
- **QEP + hypothetical:** "even for promotional material directed exclusively to QEPs, if not including the past performance information required under Compliance Rule 2-29(c)(3) would make the promotional material misleading, then a Member may be subject to discipline under Compliance Rule 2-29(b)(1)."
- **Recordkeeping (f):** "this Section contains a requirement that FCM, IB, CPO and CTA Members who use hypothetical performance results be prepared to **demonstrate to NFA's satisfaction the basis for such results**. This means that these Members must **maintain the records necessary to document how the hypothetical results were calculated.**"

### IN 9025 — Use of Promotional Material Containing Hypothetical Performance Results
> "(Board of Directors, February 1, 1996; revised August 29, 1996, January 1, 2020 and **March 20, 2020**)"

This is the operative hypothetical-performance notice. Key requirements:
- **Prominence:** "the disclaimer must be displayed **as prominently as the hypothetical results themselves**. Generally, this would require that the disclaimer be printed in **a type size at least as large as that used for the hypothetical results**." "the disclaimer should **immediately precede, or follow** the hypothetical performance results. Whenever the Member or Associate has **less than 12 months of actual results, the disclaimer must immediately precede** the hypothetical performance results." "if the promotional material contains several pages of hypothetical performance results, then the Member or Associate **may need to include this disclaimer more than once**."
- **Material assumptions:** "must also describe in the promotional material **all of the material assumptions** that were made in preparing the hypothetical results. At a minimum, the description of material assumptions must cover points such as **initial investment amount, reinvestment or distribution of profits, commission charges, management and incentive fees, and a general discussion of how performance was calculated** (e.g., based on settlement prices, real time pricing)." Plus "all material disclosures necessary to place the hypothetical results in their proper context, which in most instances may go well beyond the prescribed disclaimer."
- **Calculation method:** "must calculate hypothetical performance results **in a manner consistent with that required under Part 4 of the CFTC's Regulations**."
- **Actual vs hypothetical:** "when any Member or Associate utilizes promotional material that contains both hypothetical and actual performance results, **the actual results must be presented with at least the same prominence devoted to the hypothetical results**. Hypothetical and actual performance results must be **appropriately identified, presented separately, discussed in an equally balanced manner and calculated pursuant to the same rate of return method.** Furthermore, the promotional material **must not contain any statement that places undue emphasis on the hypothetical performance results**, for example, by discounting or downplaying the significance of any actual performance results."
- **⚠️ "live"/"real-time" disguise — directly relevant to EA vendors:** "There have also been instances in which Members or Associates have attempted to **disguise hypothetical performance results by referring to the performance with terms such as 'live' or 'real-time' results.** In many cases, the intention of these ambiguous references are intended to give the appearance that hypothetical performance is actual performance."
- **"pro forma" is misleading:** "In the past, Members have referred to these composite performance records as **pro forma results; however, NFA's Board of Directors believes the pro forma label is misleading.**" "Members and Associates must **appropriately label any composite performance record for a multi-advisor managed account or pool as hypothetical and not pro forma.**"
- **Extracted performance:** "hindsight analysis may be misleading as applied to the presentation of **extracted performance** in which a Member or Associate **selects one component of its overall past trading results to highlight** to customers." Permitted only when prior disclosure documents designated the percentage of assets committed to that component. "any promotional material referring to extracted results must **clearly label those results as such** and must **disclose in an equally prominent fashion the overall actual trading results from which the extracted results were drawn.**"
- **Pro forma for fee/commission adjustment is permitted:** "a Member or Associate **may use pro forma results to adjust for differences in commissions and fees** as long as the pro forma results are not calculated in a misleading manner and the assumptions used to arrive at the pro forma results are clearly disclosed."
- **Burden:** "Pursuant to NFA Compliance Rule 2-29(f), Members and Associates presenting hypothetical results in their promotional material must be able to **demonstrate to NFA's satisfaction the validity of the presentation** of the results. **The greater the emphasis on dramatic hypothetical profits, the greater the Member's burden** in demonstrating the validity of the presentation."

### IN 9033 — Compliance Rule 2-29: Deceptive Advertising
> "(Board of Directors, June 4, 1996; revised January 1, 2020)"

Enumerated deceptive practices (each an express violation): **Claims Regarding Seasonal Trades and Historical Price Moves · Cherry Picked Trades · Profit Projections · Use of Mathematical Leverage Examples · Use of Price Moves in One Product to Solicit Investment for a Different Product · Use of Arbitrary Leverage Level · Use of Third-Party Index Performance.**

Notable quotes:
- "**One common theme of deceptive or misleading promotional material is the suggestion of a strong likelihood of reaping dramatic profits by investing with the Member firm when, in fact, nothing in the Member's past experience provides any basis for those claims.**"
- Profit Projections: "Members have claimed that, based on current market conditions, customers can '**turn $10,000 into $40,000**,' or profits of a similar magnitude. Again, however, the Member has not achieved the projected profits for its customers in the past."
- "Members **may not** use any promotional material or make any solicitation referencing dramatic profits that could be achieved in the future or could have been achieved in the past by trading in commodity interest contracts for a particular commodity market **unless the Member can demonstrate to NFA that, based on the past performance of its customers, those claims are not misleading.**"
- "Failure to provide adequate documentation will constitute **prima facie evidence that the promotional material is misleading.**"

### IN 9009 — Review of Promotional Material Prior to Its First Use ← **the "submission to NFA" answer**
> "(Staff, May 1, 1989; revised July 1, 2000; January 1, 2020 and **March 18, 2026**.)"

> "NFA offers a program to review the promotional material of an FCM, IB, CPO or CTA Member prior to its first use. **This program is voluntary and no Member is required to file promotional material with NFA prior to using the material unless otherwise required to do so by an NFA rule or directive.** In addition, the use of this program in no way lessens the requirement that Members review, approve and supervise the use of all of their promotional material. **A Member may not rely on or attempt to use NFA staff's review to meet its promotional material supervisory obligations under NFA Compliance Rule 2-29.**"
> "Any Member wishing to use the pre-review program must submit promotional material to the Member Oversight Department through NFA's electronic Promotional Material Filing System **at least 14 calendar days prior to its first intended use.**"

**Mandatory (non-voluntary) NFA pre-use submission triggers:**
1. **Rule 2-29(h)** — audio/video content making a specific trading recommendation or referencing past/future profits → **10 days prior to first use** (NFA's Promotional Material Review Team).
2. **Rule 2-36(g)** — NFA "may require any Forex Dealer Member for any specified period to file copies of all promotional material with NFA for its review and approval **at least 10 days prior to its first use**."
3. **Rule 2-29(j)(13)** — security futures products mass-media material → 10 days.
4. **Rule 2-29(g)** — NFA may require filing "promptly after its first use."

**Answer to "must forex promotional material be submitted to NFA for review?":** There is **no blanket pre-approval requirement**. It is (a) **voluntary** under IN 9009 (14 days), and (b) **discretionary/on-demand** under 2-36(g) (10 days) and 2-29(g). Only **audio/video** material referencing recommendations or profits is **mandatorily** pre-filed under 2-29(h).

### IN 9037 — Guidance on the Use and Supervision of Websites, Social Media and Other Electronic Communications
> "(Board of Directors, August 19, 1999; revised January 1, 2020)"

- "Any communication related to a commodity interest account, agreement or transaction that is posted by or on behalf of an FCM, IB, CPO or CTA Member on a website, social media page or another internet-based forum that can be viewed by the general public **or a closed community that includes current and potential customers, falls within the definition of promotional material**…"
- "Personal websites, social media pages or other internet-based forums of Associates, employees or agents that are used in connection with their commodity interest activities **constitute promotional material of the Member** and must be covered by the Member's supervisory program."
- "**promptly take down any post that violates NFA rules** (e.g., a deceptive, misleading or fraudulent post) and **ban users for egregious or repeat violations**."
- "If a Member solicits leads through another party's website, social media or other forum, **the Member will be responsible for supervising the content of such platforms** and will be subject to an NFA disciplinary action for any content that violates NFA rules."
- Hyperlink chain: "Members who seek to circumvent NFA promotional material and supervision rules by using a chain of hyperlinks to a 'remote' website… **may be held accountable**."

### IN 9043 — Use of Past or Projected Performance
> "(Board of Directors, August 21, 2001 and January 1, 2020)"

- "**Annual rates of return may not be used in any promotional material unless they are based on 12 consecutive months of actual performance**, and they must be calculated in a manner consistent with CFTC Regulation 4.25. … Furthermore, the promotional material must state that **past results are not necessarily indicative of future results.**"
- Performance must be **current**: "it must cover at least the most recent 12-month period or must include the performance in its entirety if less than 12 months. … the Member or Associate **may not include gaps or otherwise cherry-pick the periods** for which it discloses performance."
- Records: "must identify the trades and accounts that were used in calculating performance, describe how and why those transactions and accounts were selected, and demonstrate how the results are representative of all reasonably comparable accounts."
- Projected performance: must disclose/adjust for all relevant costs; "must have a **reasonable basis in fact**"; "**All material assumptions made in projecting performance must be clearly identified**"; risks must be balanced.

### IN 9055 — NFA Bylaw 1101, Compliance Rules 2-9 and 2-29: Third-Party Trading System Developers ← **MOST DIRECTLY ON POINT FOR EA VENDORS**
> "(Board of Directors, August 19, 2004; effective January 10, 2005; September 19, 2016 and January 1, 2020)"
> Full title: "**GUIDELINES RELATING TO THE REGISTRATION OF THIRD-PARTY TRADING SYSTEM DEVELOPERS AND THE RESPONSIBILITY OF NFA MEMBERS FOR PROMOTIONAL MATERIAL THAT PROMOTES THIRD-PARTY TRADING SYSTEM DEVELOPERS AND THEIR TRADING SYSTEMS**"

- "These trading systems typically are **computerized programs that generate signals as to when to buy and sell** commodity futures and options contracts."
- **Registration:** "In March 2000, the CFTC adopted CFTC Rule 4.14(a)(9) to create an exemption from the CEA's registration requirements for CTAs that provide **standardized advice by means of media such as newsletters, pre-recorded telephone hotlines, Internet web sites, and non-customized computer software.**"
- "To qualify for the exemption, under Rule 4.14(a)(9)(i) a CTA **may not direct client accounts**."
- "Rule 4.14(a)(9)(ii) also provides that, to qualify for the exemption, a CTA may not provide 'commodity trading advice based on, or tailored to, the commodity interest or cash market positions or other circumstances or characteristics of particular clients.' **So long as the CTA's advice is based on or tailored to such information, the CTA is required to register even if it gives the same advice to groups of similarly situated clients.**"
- **Context test:** "if the advice is provided in a **book or a periodical**, that factor may weigh **against** a finding that the CTA is providing advice 'based on or tailored to' the characteristics of particular clients. On the other hand, if the advice is provided to a particular client **in a face-to-face communication or over the telephone**, that factor may weigh **in favor of** a finding…"
- **Cites CFTC Staff Letter 03-26 (May 30, 2003):** "the clients' contact with the AP/trading system developer included not only the trading program, but also the opening of a trading account that would be traded pursuant to a 'letter of direction,' there was an '**informal arrangement**', for which the exemption provided under Rule 4.14(a)(9) was not intended. … registration as a CTA was required of either the IB or the AP."
- **⚠️ The core vendor warning:** "NFA has encountered, with increasing frequency in recent years, **misleading promotional material promoting trading systems developed by third-party system developers, who are not NFA Members**… Often this promotional material uses **hypothetical or simulated results — which are trading results not achieved by an actual account — that are not clearly identified as hypothetical and show impressive gains, when customers actually using the trading system have suffered substantial losses.** In this and other contexts, **both NFA and the Commission have brought numerous enforcement actions charging fraud in the use of such promotional material.**"
- Three liability theories for the NFA Member: **Direct Responsibility** (Member prepared/distributed it), **Agency Responsibility** (developer is Member's agent), **Supervisory Responsibility under Rule 2-9** (linking, recommending, or referral agreement).
- "**Member firms should not seek to circumvent NFA's promotional material requirements by relying upon the unregistered status of the third-party trading system developer.**"

### Promotional Material Guide (Dec. 2025)
**URL:** https://www.nfa.futures.org/members/member-resources/files/promo-material-guide.pdf (HTTP 200)
Full title: "**A Guide to Communications with the Public and Promotional Material for FCMs, FDMs, IBs, CPOs and CTAs**"
> "**December 2025 Revisions:** NFA updated the contents to incorporate the retraction of the Interpretive Notice regarding disclosure requirements for NFA Members engaging in virtual currency activities."

**"NFA considers the following data to be hypothetical":**
> "• A trade or series of trades that were not actually executed for one account, • Paper or simulated trading, • Combining the performance of several advisors who have not traded together, and • **Applying arithmetic calculations to actual performance (e.g., modifying actual results for a different leverage level).**"
> "**It is misleading to refer to results as 'real-time' simply because a system was tested using a live data-feed. Similarly, it is misleading to refer to hypothetical results as 'pro-forma.'** These results should be prominently labeled 'hypothetical'…"
> "**Hypothetical results may not be used for any trading program that has at least three months of actual client or proprietary performance.**"
> "**Hypothetical performance for a new trading program must be for a program that is significantly different from other programs with actual results.**"
> "The basis for the hypothetical results and the underlying theory that generated them **must be demonstrated to NFA upon request.**"

The Guide also reproduces both mandatory disclaimers verbatim (matching Rule 2-29(c)(1)/(c)(2)), the <1-year add-ons, and the composite add-on.

**Forex third-party system developer warning (Guide, verbatim):**
> "Members may also be subject to discipline for promotional material promoting forex trading systems developed by third parties. For example, a Member has **direct responsibility** for misleading promotional material if the Member prepares or distributes it; has **agency responsibility** if the trading system developer is an agent of the Member under established principles of agency law; and has **supervisory responsibility** if the Member fails to supervise its own employees when linking to a third-party trading system developer's website, recommending a third-party's trading system, or entering into a referral agreement with a third-party system developer."

---

## 5. CFTC RULE 4.41 — ADVERTISING (FULL TEXT, eCFR)

**Source:** https://www.ecfr.gov/current/title-17/chapter-I/part-4/subpart-A/section-4.41 (HTTP 200)
Title: "**§ 4.41 Advertising by commodity pool operators, commodity trading advisors, and the principals thereof.**"
**Authority:** 7 U.S.C. 1a, 2, 6(c), 6b, 6c, 6l, 6m, 6n, 6o, 12a, and 23.
**Source:** 46 FR 26013, May 8, 1981, as amended at 46 FR 63035 (Dec. 30, 1981); 60 FR 38192 (July 25, 1995); 72 FR 8109 (Feb. 23, 2007).
⚠️ Note: eCFR states "**No changes found for this content after 1/03/2017.**" (eCFR display: title 17 up to date as of 9/17/2026.)

### 4.41(a) — VERBATIM
> "(a) No commodity pool operator, commodity trading advisor, or any principal thereof, may advertise in a manner which:
> **(1)** Employs any device, scheme or artifice to defraud any participant or client or prospective participant or client;
> **(2)** Involves any transaction, practice or course of business which operates as a fraud or deceit upon any participant or client or any prospective participant or client; or
> **(3)** Refers to any testimonial, unless the advertisement or sales literature providing the testimonial prominently discloses:
>   **(i)** That the testimonial may not be representative of the experience of other clients;
>   **(ii)** That the testimonial is no guarantee of future performance or success; and
>   **(iii)** If, more than a nominal sum is paid, the fact that it is a paid testimonial."

### 4.41(b) — THE MANDATORY CAUTIONARY STATEMENT (VERBATIM) ★ most important disclaimer
> "(b)(1) No person may present the performance of any simulated or hypothetical commodity interest account, transaction in a commodity interest or series of transactions in a commodity interest of a commodity pool operator, commodity trading advisor, or any principal thereof, unless such performance is accompanied by one of the following:
> **(i)** The following statement: **'These results are based on simulated or hypothetical performance results that have certain inherent limitations. Unlike the results shown in an actual performance record, these results do not represent actual trading. Also, because these trades have not actually been executed, these results may have under-or over-compensated for the impact, if any, of certain market factors, such as lack of liquidity. Simulated or hypothetical trading programs in general are also subject to the fact that they are designed with the benefit of hindsight. No representation is being made that any account will or is likely to achieve profits or losses similar to these being shown.'** ; or
> **(ii)** A statement prescribed pursuant to rules promulgated by a registered futures association pursuant to section 17(j) of the Act.
>
> **(2)** If the presentation of such simulated or hypothetical performance is other than oral, the prescribed statement **must be prominently disclosed and in immediate proximity to the simulated or hypothetical performance being presented.**"

**Note on 4.41(b)(1)(ii):** this is the gateway that lets the **NFA Rule 2-29(c)(1) disclaimer** substitute for the CFTC statement. A CTA/NFA Member may use either; a **non-NFA-member vendor has no access to (b)(1)(ii)** and must use the CFTC statement in (b)(1)(i) verbatim.

### 4.41(c) — SCOPE (VERBATIM)
> "(c) The provisions of this section shall apply:
> **(1)** To any publication, distribution or broadcast of any report, letter, circular, memorandum, publication, writing, advertisement or other literature or advice, **whether by electronic media or otherwise, including information provided via internet or e-mail**, the texts of standardized oral presentations and of radio, television, seminar or similar mass media presentations; and
> **(2)** **Regardless of whether the commodity pool operator or commodity trading advisor is exempt from registration under the Act.**"
> "(Approved by the Office of Management and Budget under control number 3038-0005)"

⚠️ **4.41(c)(2) is the critical trap for unregistered vendors:** the advertising rule applies even to persons **exempt from CTA registration** (e.g., under 4.14(a)(9)). Exemption from *registration* is not exemption from *4.41*.

---

## 6. CFTC REGISTRATION RULES FOR CTAs

### 6.1 CEA § 1a(12) — "Commodity trading advisor" (VERBATIM)

**Sources:** https://www.law.cornell.edu/uscode/text/7/1a (HTTP 200) · https://www.govinfo.gov/content/pkg/USCODE-2023-title7/html/USCODE-2023-title7-chap1-sec1a.htm (HTTP 200)
⚠️ uscode.house.gov timed out repeatedly on 2026-09-20 — could not verify there.

> "**(12) Commodity trading advisor**
> **(A) In general** — Except as otherwise provided in this paragraph, the term 'commodity trading advisor' means any person who—
> **(i)** for compensation or profit, engages in the business of advising others, either directly or through publications, writings, or electronic media, as to the value of or the advisability of trading in—
>   (I) any contract of sale of a commodity for future delivery, security futures product, or swap;
>   (II) any agreement, contract, or transaction described in section 2(c)(2)(C)(i) of this title or section 2(c)(2)(D)(i) of this title;
>   (III) any commodity option authorized under section 6c of this title; or
>   (IV) any leverage transaction authorized under section 23 of this title;
> **(ii)** for compensation or profit, and as part of a regular business, issues or promulgates analyses or reports concerning any of the activities referred to in clause (i);
> **(iii)** is registered with the Commission as a commodity trading advisor; or
> **(iv)** the Commission, by rule or regulation, may include if the Commission determines that the rule or regulation will effectuate the purposes of this chapter.
> **(B) Exclusions** — Subject to subparagraph (C), the term 'commodity trading advisor' does not include—
> **(i)** any bank or trust company or any person acting as an employee thereof;
> **(ii)** any news reporter, news columnist, or news editor of the print or electronic media, or any lawyer, accountant, or teacher;
> **(iii)** any floor broker or futures commission merchant;
> **(iv)** **the publisher or producer of any print or electronic data of general and regular dissemination, including its employees;**
> **(v)** the fiduciary of any defined benefit plan that is subject to the Employee Retirement Income Security Act of 1974 (29 U.S.C. 1001 et seq.);
> **(vi)** any contract market or derivatives transaction execution facility; and
> **(vii)** such other persons not within the intent of this paragraph as the Commission may specify by rule, regulation, or order.
> **(C) Incidental services** — Subparagraph (B) shall apply only if the furnishing of such services by persons referred to in subparagraph (B) is **solely incidental to the conduct of their business or profession.**
> **(D) Advisors** — The Commission, by rule or regulation, may include within the term 'commodity trading advisor', any person advising as to the value of commodities or issuing reports or analyses concerning commodities if the Commission determines that the rule or regulation will effectuate the purposes of this paragraph."

### 6.2 ⚠️ On the "statutory publisher exclusion" as quoted in the brief

**The brief's quoted language — "the publisher of any newspaper, news column, newsletter, news magazine, or business or financial publication or service… that does not consist of the rendering of advice on the basis of the specific investment situation of each client" — is NOT in CEA § 1a(12).**

That language is from the **Investment Advisers Act of 1940 § 202(a)(11)(D)** (the *Lowe v. SEC* publisher exclusion), not the CEA. The CEA analogue is the much narrower **§ 1a(12)(B)(iv)** quoted above: "the publisher or producer of any print or electronic data of general and regular dissemination, including its employees," and it applies **only if** the activity is "**solely incidental**" to the person's business or profession under **(C)**.

**The brief's quoted text is therefore UNVERIFIED as CEA § 1a(12) and should not be used.** *(I did not independently re-verify the Advisers Act text in this session — treat the attribution as an inference from the CEA text, which demonstrably lacks it.)*

### 6.3 CFTC Rule 4.14(a)(9) — VERBATIM (current, eCFR)
**Source:** https://www.ecfr.gov/current/title-17/chapter-I/part-4/subpart-B/section-4.14 (HTTP 200)

> "**(9)** It does not engage in any of the following activities:
> **(i)** Directing client accounts; or
> **(ii)** Providing commodity trading advice based on, or tailored to, the commodity interest or cash market positions or other circumstances or characteristics of particular clients; or"

⚠️ **Confirmed, with a caveat:** as currently codified, (a)(9) is a **two-prong** test. The brief's framing of "4.14(a)(9)" as an exemption for standardized advice is correct in substance (per IN 9055 and CFTC Letter 03-26, which describe it as "exempting from mandatory registration under the Act CTAs whose business is limited to distributing standardized commodity trading advice").

### 6.4 CFTC Rule 4.14(a)(10) — VERBATIM (current, eCFR)
> "**(10)** If, as provided for in section 4m(1) of the Act, during the course of the preceding 12 months, it has not furnished commodity trading advice to **more than 15 persons** and it **does not hold itself out generally to the public as a commodity trading advisor.**"

**(a)(10)(i) — counting rules (who is "a single person"):**
> "**(A)** A natural person, and: (1) Any minor child of the natural person; (2) Any relative, spouse, or relative of the spouse of the natural person who has the same principal residence; (3) All accounts of which the natural person and/or the persons referred to in paragraph (a)(10)(i)(A) of this section are the only primary beneficiaries; and (4) All trusts of which the natural person and/or the persons referred to in paragraph (a)(10)(i)(A) of this section are the only primary beneficiaries;
> **(B)** (1) A corporation, general partnership, limited partnership, limited liability company, trust (other than a trust referred to in paragraph (a)(10)(i)(A)(4) of this section), or other legal organization … that receives commodity interest trading advice **based on its investment objectives rather than the individual investment objectives** of its shareholders, partners, limited partners, members, or beneficiaries …; and (2) Two or more legal organizations referred to in paragraph (a)(10)(i)(B)(1) of this section that have identical owners."

**(a)(10)(ii) Special Rules** include: "An owner must be counted in its own capacity as a person if the commodity trading advisor provides advisory services to the owner **separate and apart** from the advisory services provided to the legal organization"; and "A general partner of a limited partnership, or other person acting as a commodity trading advisor to the partnership, **may count the limited partnership as one person**."

⚠️ **The (a)(10) exemption requires BOTH prongs** — ≤15 persons **and** no general public holding-out. A vendor marketing EAs/signals to the retail public **fails the second prong outright**.

### 6.5 ⚠️ 4.14(a)(8) — the exemption actually relevant to many CTA-adjacent firms
The current § 4.14 has a substantial **(a)(8)** regime (investment-adviser-registered persons; qualifying entities; offshore pools) with **notice filing, annual affirmation, 15-business-day amendment, and 5-year recordkeeping** obligations:
> "(iv) Each person who has filed a notice of registration exemption under this § 4.14(a)(8) must: (A)(1) **Make and keep all books and records** prepared in connection with its activities as a trading advisor, including all books and records demonstrating eligibility for and compliance with the applicable criteria for exemption under this section, **for a period of five years from the date of preparation**; and (2) Keep such books and records **readily accessible during the first two years** of the five-year period…; and (B) **Submit to such special calls as the Commission may make** to demonstrate eligibility for and compliance with the applicable criteria for exemption under this section."
⚠️ Note this is **§ 4.14(a)(8)(iv)** — a **5-year recordkeeping** obligation. This may be the source of the brief's "5-year record" recollection, but it applies to **actual books and records of the advisory business**, **not** to a "hypothetical performance record."

---

## 7. DOES SELLING TRADING SOFTWARE/SYSTEMS TRIGGER CTA REGISTRATION?

### 7.1 CFTC Staff Letter 03-26 (May 30, 2003) — the leading primary guidance
**URL:** https://www.cftc.gov/sites/default/files/idc/groups/public/@lrlettergeneral/documents/letter/03-26.pdf (HTTP 200)
Title: "**Re: Section 4m — Interpretation with regard to Commodity Trading Advisor Registration**"; Division of Clearing and Intermediary Oversight; signed Jane Kang Thorpe, Director.

Facts: an AP of an IB created a trading program generating signals; clients executed a "letter of direction" that the IB "follow [the trading program] signals as close as reasonably possible."

Holding (VERBATIM):
> "In March 2000, the Commission adopted Rule 4.14(a)(9), exempting from mandatory registration under the Act **CTAs whose business is limited to distributing standardized commodity trading advice.**"
> "In adopting Rule 4.14(a)(9), the Commission noted it intended '**that a CTA who manages a client's trading under some type of informal arrangement be required to register even if the CTA is not authorized to effect transactions without the client's specific authorization.**' The Commission further stated that the language of Rule 4.14(a)(9)(ii) '**cover[s] CTAs that informally manage their customer's trading**' and, therefore, such arrangements would require the CTA to register with the Commission."
> "It is the Division's opinion that, as the clients' contact with the CTA includes not only the trading program, but also **the opening of a trading account that is traded pursuant to a 'letter of direction,'** the facts as represented by you … would indicate the presence of the type of '**informal arrangement**' for which the exemption provided under Rule 4.14(a)(9) was not intended. Moreover, the fact that the whole of your activities as an AP of .X. consists of **the solicitation of clients for the trading program** would urge registration as a CTA. Accordingly, **registration as a CTA is required of either .X. or yourself.**"

**Practical rule of thumb:** pure software sale with **no** account-opening/letter-of-direction/auto-execution arrangement and **no** tailoring → 4.14(a)(9) available. Software bundled with account opening, auto-trading authorization, or a "follow the signals" mandate → **registration required**.

### 7.2 CFTC Staff Letter 26-25 — "Passive Software" no-action (September 17, 2026) ★ THREE DAYS OLD
**URLs:** https://www.cftc.gov/PressRoom/PressReleases/9300-26 · https://www.cftc.gov/csl/26-25/download (both HTTP 200)
Press release title: "**CFTC Staff Issues No-Action Position to Providers of Passive Software**," Release Number 9300-26, **September 17, 2026**.

> "The Commodity Futures Trading Commission's Market Participants Division today announced it has issued a no-action position for the benefit of providers of passive software. **The position is similar to that provided in Staff Letter 26-09 and now is broadly available to such providers.**"
> "The letter states that, subject to certain specified conditions, MPD will not recommend the Commission take enforcement action against any such provider or their relevant personnel for **failure to register as an introducing broker or associated person of an introducing broker**. This applies solely in relation to their provision and marketing of software to facilitate trading by the provider's users with registered futures commission merchants, introducing brokers, and designated contract markets."

**Letter 26-25 details:**
- Predecessor: **Letter 26-09** (March 17, 2026), issued to **Phantom Technologies, Inc.**, under **17 CFR 140.99**. "Pursuant to 17 CFR 140.99(a)(2), **only the Beneficiary of a no-action letter may rely on it** and, thus, no PSP other than Phantom may rely on Letter 26-09." **26-25 makes the position generally available to all PSPs.**
- "For the avoidance of doubt, **PSPs are not limited to providers of crypto asset related software.**"
- **Reliance conditions (10):** no statutory disqualification (Reg 3.1); conflict-of-interest disclosures; **Reg 1.55(b)-equivalent risk disclosure statement**; Users onboarded as direct DCM members / FCM-IB customers with independent access; **"The PSP adopts and enforces policies and procedures reasonably designed to ensure compliance with applicable Commission and National Futures Association ('NFA') rules regarding communications with the public and marketing as if the PSP were registered as an IB"** (citing **7 U.S.C. §6b; 17 CFR 180.1; and NFA Compliance Rule 2-29**); **"The PSP does not engage in advertising or promotions that, if the PSP were registered as an IB, would require pre-approval by NFA under NFA Compliance Rule 2-29"**; **joint and several liability undertaking** with each Registrant, filed with the Division; Reg 1.31-conforming records; insolvency notice; and a filed notice consenting to CFTC jurisdiction.
- **"Covered Activities" limits — critical carve-outs:** the software "will serve only to **passively enable** Users to transact…" and "**At no point would the PSP hold, control, or take into custody User assets, generate express 'buy' or 'sell' signals, or exercise discretion with respect to the routing or execution of User orders.**"
- Covered Activities **exclude** non-custodial models: they "are limited to circumstances where a User is transacting on a DCM either directly as a member of the DCM or indirectly as a customer of an FCM or IB… the User would also maintain the funds or other property securing its derivatives positions in custody with the DCM's DCO and/or an FCM…"

⚠️ **MATERIAL LIMITATION FOR THE VENDOR:** Letter 26-25 is an **IB-registration** no-action position. It **expressly requires that the PSP not "generate express 'buy' or 'sell' signals."** An **MT5 EA or signals service that generates buy/sell signals falls outside Covered Activities** and cannot rely on it. It also does **not** address CTA registration at all.

### 7.3 TSV Letters (predecessors) — the six conditions
Letter 26-25 describes the earlier DCIO "TSV Letters": **CFTC Staff Letter 06-29**, **08-07**, and **08-12** (URLs cited in 26-25, all verified HTTP 200):
- 06-29: https://www.cftc.gov/sites/default/files/idc/groups/public/@lrlettergeneral/documents/letter/06-29.pdf
- 08-07: https://www.cftc.gov/sites/default/files/idc/groups/public/@lrlettergeneral/documents/letter/08-07.pdf
- 08-12: https://www.cftc.gov/sites/default/files/idc/groups/public/@lrlettergeneral/documents/letter/08-12.pdf

The six **"TSV Letter Requirements"** (quoted from 26-25):
> "(1) each customer would have established a **pre-existing relationship with a futures commission merchant ('FCM') or IB independent of its relationship with the TSV**; (2) the TSV would **not recommend, propose, or encourage that customers use any particular FCM or IB**, even upon request; (3) the TSV's platform **would not produce express 'buy' or 'sell' signals**; (4) the TSV would **not solicit or accept orders** for any commodity futures or commodity option transaction; (5) **fees charged by the TSV would not be related to any fees charged by the FCM or IB** for the execution of any futures orders; and (6) the TSV would **not have a membership with trading privileges on any designated contract market ('DCM')** or derivatives transaction execution facility."

Letter 06-29 language confirmed in the primary PDF: "'A' will not recommend, propose, or encourage customers to use any particular FCM, even in response to a customer inquiry, nor will it solicit customers for an FCM in any other [manner]"; and the platform does not produce "'buy' or 'sell' signals."

### 7.4 CFTC CTA registration guidance page
**URL:** https://www.cftc.gov/IndustryOversight/Intermediaries/CTAs/index.htm (HTTP 200)
⚠️ This page is **general registration mechanics** (who must register, how to register, NFA as the registration agent). I did **not** find on it a dedicated "trading software" FAQ. **UNVERIFIED** that the CFTC publishes a software-specific CTA FAQ.

### 7.5 2024 Part 4 rulemaking — CORRECTED CITATION
**Correct citation: 89 FR 78793** (Vol. 89, No. 187, Thursday, September 26, 2024, pages **78793–78815**), RIN 3038-AF25.
**Sources:** https://www.cftc.gov/sites/default/files/2024/09/2024-21682a.pdf · https://www.cftc.gov/PressRoom/PressReleases/8965-24 (both HTTP 200)
**Title:** "**Commodity Pool Operators, Commodity Trading Advisors, and Commodity Pools Operated: Updating the 'Qualified Eligible Person' Definition; Adding Minimum Disclosure Requirements for Pools and Trading Programs; Permitting Monthly Account Statements for Funds of Funds; Technical Amendments**"
**Amends:** 17 CFR Parts 1, 3, 4, 30, 43, and 75.

Per CFTC Press Release 8965-24 (Sept. 12, 2024), the final rule:
> "(1) **Increases the monetary thresholds** outlined in the 'Portfolio Requirement' definition that certain persons may use to qualify as Qualified Eligible Persons;
> (2) **Codifies exemptive letters** allowing CPOs of Funds of Funds operated under Regulation 4.7 to choose to distribute monthly account statements within 45 days of the month-end;
> (3) Includes **technical amendments** designed to improve its efficiency and usefulness…; and,
> (4) **Updates citations** within 17 CFR Part 4, and throughout the CFTC's rulebook, to reflect the new structure of Regulation 4.7."

**DATES (from the FR document):** "**Effective date: This rule is effective November 25, 2024.** Compliance date: Commodity pool operators (CPOs) and commodity trading advisors (CTAs) must comply with the increased Portfolio Requirement thresholds in Commission regulation §4.7(a) by **March 26, 2025**."

**Effect on § 4.14:** the rule made a **technical revision only** — "In §4.14, revise paragraph **(a)(8)(i)(C)(2)**" (an offshore-pool non-US-person beneficial-interest provision). **It did NOT change 4.14(a)(9) or (a)(10), and did NOT change the CTA registration triggers.**

⚠️ **The 2024 rulemaking is essentially irrelevant to a software/signals vendor's registration question.** It is a QEP/disclosure/technical rulemaking, not a CTA-registration rulemaking.

### 7.6 NFA guidance on trading-system vendors / referral arrangements
**IN 9055** (see §4) is the operative notice. Additionally **IN 9037** covers referral/link liability, and **NFA Bylaw 1101** imposes strict liability on Members transacting customer business with non-Members required to be registered (see **IN 9007**, "Compliance with NFA Bylaw 1101").

---

## 8. ENFORCEMENT REALITY — CONCRETE ACTIONS

### 8.1 CFTC v. Fintech Investment Group, Inc., Alan Friedland, and Compcoin LLC ★ the "forex robot" case
**Case No. 6:20-cv-00652-WWB-EJK (M.D. Fla.)**
**Primary sources:**
- Complaint (filed 2020-04-16): https://www.cftc.gov/media/3756/enffintechalancomplaint041620/download
- **Consent Order for Permanent Injunction, Civil Monetary Penalty, and Other Equitable Relief (filed 2022-03-07):** https://www.cftc.gov/media/7126/enfintechconsentorder030722/download
(both HTTP 200; text extracted from the primary PDFs)

**Product:** "**ART**" — an "**algorithmic trading platform**" / "**ART forex trading system**" marketed with the **Compcoin** token.

**Charges sustained (verbatim from the Consent Order):**
- **7 U.S.C. §6b(a)(2)(A)–(C) and 17 C.F.R. §5.2(b)(1)–(3)** — fraud in connection with retail forex.
- **7 U.S.C. §6o(1)(A) and (B)** — **Fraud by a Commodity Trading Advisor** (¶43: "Defendants Fintech and Friedland violated 7 U.S.C. §6o(1)(A) and (B)"). Count heading: "**Fraud by a Commodity Trading Advisor**."
- **7 U.S.C. §9(1) and 17 C.F.R. §180.1** — fraud.
- **17 C.F.R. §4.41(a)** — "**False Advertising by a CTA**" (¶49).
- **17 C.F.R. §4.41(b)** — "**Failure to Include Disclaimer Concerning Hypothetical Results**" (¶51).
- Compcoin LLC liable as **aider and abettor** under **7 U.S.C. §13c(a)**.

**The 4.41(b) holding (VERBATIM, ¶50):**
> "By the conduct described in paragraphs 1 through 37 above, Defendants presented the performance of the ART program in solicitation material, including but not limited to the Compcoin LLC website and social media sites, **without the disclaimer required by 17 C.F.R. §4.41(b) that the performance was based upon simulated or hypothetical trading results.**"

**The core misrepresentation (VERBATIM):** Defendants "**fail[ed] to include the required disclosure that Fintech and ART's forex trading performance results were largely or entirely based on simulated or hypothetical performance and not actual trading results as required by the relevant Regulation.**"

**Marketing claims alleged:** ART "is likely to deliver a return on [investment]"; "ART's high success rate at predicting USD/EUR"; "10%* quarterly return on investment (ROI)- much higher than the ROI of [others]".

**NFA disclosure-document failure:** "before Fintech could lawfully offer ART to purchasers of Compcoin, Fintech was required to seek and obtain the [NFA's]… **NFA never approved Fintech's risk disclosure documents for ART**" — citing **CFTC Regulation 4.36, 17 C.F.R. §4.36** ("a CTA 'must'…").

**Sanctions (VERBATIM):**
- **Restitution: $1,200,000** jointly and severally (¶56), with **NFA appointed as Monitor** (¶57) and payments into the "Fintech Restitution Fund."
- **Civil monetary penalty: $600,000** jointly and severally (¶65).
- **Permanent injunction** including trading ban and registration ban; and under ¶(f) "Applying for registration or claiming exemption from registration with the Commission" prohibited except as provided.

### 8.2 CFTC v. Valdas Dapkus, Tradewale LLC, and Tradewale Managed Fund ★ unregistered CTA + "trading system"
**Case filed Sept. 2021 (D.N.J.); default judgments 2023.**
**Primary sources:**
- Press Release 8845-23 (Dec. 28, 2023): https://www.cftc.gov/PressRoom/PressReleases/8845-23
- Press Release 8438-21 (original action): https://www.cftc.gov/PressRoom/PressReleases/8438-21
- Order (Dapkus, Nov. 28, 2023): https://www.cftc.gov/media/10066/enfvaldasdapkus112823/download
- Order (Tradewale, May 4, 2023): https://www.cftc.gov/media/10071/enftradewaleorder050423/download

**Violations:** fraudulent solicitation for a purported retail forex fund; misappropriation; **failure to register as commodity trading advisors**.
> "The Tradewale entities were also found liable for **failure to register as commodity trading advisors (CTA)**."
> "The court also found that, according to the allegations in the complaint, **the Tradewale entities acted as CTAs because they solicited funds for an investment vehicle by way of the mail or other means of interstate commerce and did so without being registered with the CFTC.**"

**The trading-system claims:**
> "in soliciting members of the public to trade, Tradewale made various material misrepresentations and omissions, including that it had a '**unique trading system**' using '**artificial intelligence**' to trade forex. Tradewale also claimed it generated **average monthly returns of 4%-11% and average yearly returns of over 55% with 'minimal risk.'**"

**Sanctions:** "$713,520 in restitution and a **$2,140,560 penalty**," jointly and severally; permanent injunctions including a trading ban.

### 8.3 CFTC v. SimTradePro Inc. and Robert L. Adams ★ failure to disclose simulated/hypothetical results
**Filed 2024-09-30 (D. Or.).**
**Primary sources:**
- Press Release 8993-24 (Oct. 2, 2024): https://www.cftc.gov/PressRoom/PressReleases/8993-24
- Complaint: https://www.cftc.gov/media/11416/enfrobertladamscomplaint093024/download

**Allegations (VERBATIM from the release):**
> "the defendants defrauded more than 100 U.S. customers out of at least $2.3 million; **acted as an unregistered commodity pool operator and commodity trading advisor**; **failed to make the required disclosure regarding simulated or hypothetical trading results**; and **Adams acted as an unregistered associated person of an introducing broker.**"
> "the complaint alleges the defendants **did not provide the requisite disclosure regarding simulated or hypothetical trading results**, and that Adams acted as an associated person of an introducing broker but failed to register with the CFTC as required."

**Relief sought:** "disgorgement of ill-gotten gains, civil monetary penalties, restitution, trading and registration bans, and a permanent injunction." *(No final judgment located as of 2026-09-20 — outcome UNVERIFIED.)*

### 8.4 NFA — In the Matter of Attain Capital Management LLC, Walter J. Gallwas, and Jeffrey D. Malec
**NFA Case No. 07-BCC-020** (Hearing Panel, filed 2008-05-02)
**Primary source:** https://www.nfa.futures.org/BasicNet/regulatory-actions-detail-doc.aspx?docid=1576 (HTTP 200; PDF: `Decision_AttainCapitalManagement&WalterGallwas&JeffreyMalec_20080502.pdf`)

**Charges and findings (VERBATIM):**
> "The Complaint charged Attain with using **misleading and unbalanced promotional material which failed to 1) include the disclaimer concerning past performance, 2) clearly identify performance as hypothetical, 3) include the required hypothetical disclaimer, or 4) disclose the material assumptions made in arriving at hypothetical performance, in violation of NFA Compliance Rules 2-29(b)(1), (2), (3) and (4) and 2-29(c).** The Complaint also charged Attain with failing to submit promotional material to NFA after its first use, in violation of NFA Compliance Rule 2-29(g)."
> "the Panel finds that Attain failed to maintain required books and records and support for advertised performance results and failed to implement AML requirements, in violation of NFA Compliance Rules **2-10, 2-29(f)** and 2-9(c). Lastly, the Panel finds that Attain failed to supervise Attain's operations, in violation of NFA Compliance Rule **2-9**."

**Sanction:** "**Attain shall pay a fine of $25,000** (for which Gallwas and Malec shall be jointly and severally liable in the event that Attain does not pay the fine)."
⚠️ Attain was an **IB** member — note the case shows Rule 2-29 reaching a firm that was not itself a CTA/CPO.

### 8.5 ⚠️ Enforcement-research limitations
- **NFA BASIC** (https://www.nfa.futures.org/basicnet/) and its disciplinary-detail pages are **JavaScript-rendered**; the case-detail HTML returns an empty shell to non-browser clients. `docid`-based PDF endpoints **do** work (used for Attain above), but **there is no public bulk index of NFA disciplinary actions keyed by rule violated**. Systematic enumeration of NFA hypothetical-performance cases is **UNVERIFIED / not achievable** with the tools available in this session.
- I did **not** locate a CFTC or NFA action specifically against a **MetaTrader EA vendor** by name. The Fintech/ART, Tradewale, and SimTradePro matters are the closest analogues (algorithmic/forex trading system vendors).
- No action was found premised on **NFA Rule 2-36** against a pure software vendor.

---

## 9. CONSOLIDATED COMPLIANCE CHECKLIST FOR THE VENDOR

| # | Requirement | Cite | Note for EA/signals vendor |
|---|---|---|---|
| 1 | No misleading promo; no material misstatement; no misleading omission | NFA 2-29(b)(1)–(2); CFTC 4.41(a)(1)–(2) | Applies to website, social, Discord/Telegram, webinars |
| 2 | Profit mention → equally prominent risk-of-loss discussion | NFA 2-29(b)(3) | "not downplayed or hidden" (IN 9003) |
| 3 | Past trading profits → must state past results not indicative of future results | NFA 2-29(b)(4) | |
| 4 | Actual performance figures must be representative, net of all fees, Part 4-consistent | NFA 2-29(b)(5) | "model account" advertising barred unless representative |
| 5 | Testimonials: not-representative + not-indicative + paid disclosures | NFA 2-29(b)(6); CFTC 4.41(a)(3)(i)–(iii) | |
| 6 | **Hypothetical/backtest → mandatory disclaimer** | **NFA 2-29(c)(1)** (or **CFTC 4.41(b)(1)(i)** if not an NFA member) | Backtests, demo accounts, "live data-feed" sims all count |
| 7 | Disclaimer prominence: type size ≥ results; immediate proximity; precede if <12 mo actual | IN 9025 | Repeat on multi-page decks |
| 8 | Disclose ALL material assumptions (initial investment, reinvestment, commissions, mgmt/incentive fees, calc method) | IN 9025 | |
| 9 | **Cannot use hypothetical if ≥3 months actual results for that system** | NFA 2-29(c)(4); Promo Guide | **Kills backtest marketing once live track record exists** |
| 10 | Must include 5-yr actual customer-account performance alongside hypotheticals | NFA 2-29(c)(3) | QEP-only carve-out at (c)(6) |
| 11 | Actual results ≥ same prominence as hypothetical; separate; balanced; same ROR method | IN 9025 | |
| 12 | Do not call hypothetical "live," "real-time," or "pro forma" | IN 9025; Promo Guide | |
| 13 | Extracted performance: only if pre-designated % of assets; label + disclose overall results | IN 9025; NFA 2-29(c)(7) | |
| 14 | Written supervisory procedures + written pre-use approval by someone other than author | NFA 2-29(e) | |
| 15 | Recordkeeping: 5 years from last use; 2 years readily accessible | NFA 2-29(f) + CFTC 1.31 | |
| 16 | Demonstrate basis for reported results to NFA on request | NFA 2-29(f) | Burden rises with dramatic claims |
| 17 | Audio/video with recommendations or profit claims → NFA pre-approval ≥10 days | NFA 2-29(h) | |
| 18 | Statements of opinion identifiable + reasonable basis in fact | NFA 2-29(d) | |
| 19 | No "limited risk" implying limited *likelihood* of loss | Promo Guide | |
| 20 | No guarantees against losses / limited losses; no "no-slippage" claims | Promo Guide (forex) | |
| 21 | Website/social content is promotional material; supervise & take down violative posts | IN 9037 | Includes closed communities w/ customers |
| 22 | **CTA registration** unless 4.14(a)(9) or (a)(10) satisfied | CEA 1a(12); 17 CFR 4.14 | Signals/auto-execution likely defeat (a)(9) |
| 23 | **4.41 applies even if exempt from registration** | CFTC 4.41(c)(2) | |
| 24 | IB registration exposure for order-routing/solicitation | CEA 4d(g); Staff Ltr 26-25 | 26-25 excludes "buy/sell signals" |

---

## 10. EXPLICIT UNVERIFIED / NOT-FOUND LIST

1. **"Hypothetical performance record" (5 years, monthly trades, examined)** — **NOT FOUND** in NFA Rule 2-29, Rule 2-36, any NFA Interpretive Notice, the Promo Guide, or the 2019 CFTC submission. **Appears to be a conflation of 2-29(c)(3) (5-yr *actual* performance) and 2-29(f)/4.14(a)(8)(iv) (5-yr recordkeeping).**
2. **NFA Rule 2-36(d) as the hypothetical-results paragraph** — **INCORRECT.** (d) is "Doing Business with Non-Members." Forex hypothetical results = **2-36(h)** (redlined 2019, now printed "Reserved") → **2-29(c)**.
3. **NFA Rule 2-36(c) as the forex promotional-material/risk-warning paragraph** — **INCORRECT.** (c) is "Just and Equitable Principles of Trade." Promo material = **2-36(g)**; risk disclosure = **2-36(l)(4)** → Reg 5.5 / Reg 4.34.
4. **"Substantial risk of loss"** as an exact phrase in Rule 2-36 or CFTC Reg 5.5 — **NOT FOUND.**
5. **Enumerated banned words ("guaranteed," "insured," "safe," "secure," "risk-free," "no-risk," "hedge," "safe harbor") in NFA Rule 2-29** — **NOT FOUND.** Regulated instead via 2-29(b)(1)–(3), Rule 2-4, and Promo Guide forex/options guidance.
6. **Brief's quoted "publisher exclusion" as CEA §1a(12)** — **NOT IN §1a(12).** That language is Advisers Act §202(a)(11)(D). CEA analogue is §1a(12)(B)(iv) + (C) "solely incidental."
7. **"89 FR 78813" as a 2024 CTA-registration rulemaking** — **INCORRECT.** Correct cite **89 FR 78793** (Sept. 26, 2024); it is a QEP/disclosure/technical rulemaking and did not change 4.14(a)(9)/(a)(10).
8. **A separate 2019 interpretive notice titled "Fictitious or hypothetical performance" or "Trading Systems"** — **NOT FOUND.** Content consolidated in IN 9025 and IN 9055.
9. **A joint CFTC/NFA "Use of Promotional Material" interpretive notice dated 29 Aug 2019** — **NOT FOUND.** The 29 Aug 2019 document is NFA's §17(j) submission letter with redlines.
10. **CFTC software-specific CTA registration FAQ** — **NOT FOUND** on the CFTC CTA page.
11. **uscode.house.gov** — timed out repeatedly on 2026-09-20; CEA §1a(12) verified via **law.cornell.edu** and **govinfo.gov** instead.
12. **NFA BASIC systematic disciplinary search** — **not achievable** (JS-rendered). Individual `docid` PDFs are retrievable.
13. **SimTradePro final judgment** — **not located**; matter pending/outcome unknown as of 2026-09-20.

---

## 11. VERIFIED PRIMARY-SOURCE URL INDEX (all HTTP 200 on 2026-09-20)

**eCFR**
- 17 CFR 4.41 — https://www.ecfr.gov/current/title-17/chapter-I/part-4/subpart-A/section-4.41
- 17 CFR 4.14 — https://www.ecfr.gov/current/title-17/chapter-I/part-4/subpart-B/section-4.14
- 17 CFR 1.31 — https://www.ecfr.gov/current/title-17/chapter-I/part-1/section-1.31
- 17 CFR 5.5 — https://www.ecfr.gov/current/title-17/chapter-I/part-5/section-5.5
- 17 CFR 4.34 — https://www.ecfr.gov/current/title-17/chapter-I/part-4/subpart-B/section-4.34

**NFA**
- Compliance Rules (Section 4) — https://www.nfa.futures.org/rulebooksql/rules.aspx?Section=4
- Compliance Rules PDF — https://www.nfa.futures.org/rulebooksql/rulespdf.aspx?Section=4
- Interpretive Notices (Section 9) — https://www.nfa.futures.org/rulebooksql/rules.aspx?Section=9
- 2019 §17(j) submission letter (redlines) — https://www.nfa.futures.org/news/PDF/CFTC/08292019-CR-2-29-CR-2-36-Interp-Notices-Use-of-Promotional-Material.pdf
- Promotional Material Guide (Dec. 2025) — https://www.nfa.futures.org/members/member-resources/files/promo-material-guide.pdf
- Attain Capital decision (07-BCC-020) — https://www.nfa.futures.org/BasicNet/regulatory-actions-detail-doc.aspx?docid=1576
- Rule 2-29 direct anchor — https://www.nfa.futures.org/rulebooksql/rules.aspx?Section=4&RuleID=RULE%202-29
- IN 9003 direct anchor — https://www.nfa.futures.org/rulebooksql/rules.aspx?Section=9&RuleID=9003

**CFTC**
- Staff Letter 26-25 (Passive Software) — https://www.cftc.gov/csl/26-25/download
- Press Release 9300-26 — https://www.cftc.gov/PressRoom/PressReleases/9300-26
- Staff Letter 26-09 — https://www.cftc.gov/csl/26-09/download
- Staff Letter 03-26 — https://www.cftc.gov/sites/default/files/idc/groups/public/@lrlettergeneral/documents/letter/03-26.pdf
- Staff Letter 06-29 — https://www.cftc.gov/sites/default/files/idc/groups/public/@lrlettergeneral/documents/letter/06-29.pdf
- Staff Letter 08-07 — https://www.cftc.gov/sites/default/files/idc/groups/public/@lrlettergeneral/documents/letter/08-07.pdf
- Staff Letter 08-12 — https://www.cftc.gov/sites/default/files/idc/groups/public/@lrlettergeneral/documents/letter/08-12.pdf
- Fintech/Compcoin complaint — https://www.cftc.gov/media/3756/enffintechalancomplaint041620/download
- Fintech/Compcoin consent order — https://www.cftc.gov/media/7126/enfintechconsentorder030722/download
- PR 8845-23 (Tradewale) — https://www.cftc.gov/PressRoom/PressReleases/8845-23
- PR 8438-21 (Tradewale original) — https://www.cftc.gov/PressRoom/PressReleases/8438-21
- Tradewale order (Dapkus) — https://www.cftc.gov/media/10066/enfvaldasdapkus112823/download
- Tradewale order (entities) — https://www.cftc.gov/media/10071/enftradewaleorder050423/download
- PR 8993-24 (SimTradePro) — https://www.cftc.gov/PressRoom/PressReleases/8993-24
- SimTradePro complaint — https://www.cftc.gov/media/11416/enfrobertladamscomplaint093024/download
- PR 8965-24 (2024 Part 4 final rule) — https://www.cftc.gov/PressRoom/PressReleases/8965-24
- 89 FR 78793 PDF — https://www.cftc.gov/sites/default/files/2024/09/2024-21682a.pdf
- CTA registration page — https://www.cftc.gov/IndustryOversight/Intermediaries/CTAs/index.htm

**Statute**
- CEA §1a(12) (Cornell LII) — https://www.law.cornell.edu/uscode/text/7/1a
- CEA §1a(12) (govinfo, 2023 ed.) — https://www.govinfo.gov/content/pkg/USCODE-2023-title7/html/USCODE-2023-title7-chap1-sec1a.htm

**Federal Register**
- 89 FR 78793 (FR site) — https://www.federalregister.gov/documents/2024/09/26/2024-21682/commodity-pool-operators-commodity-trading-advisors-and-commodity-pools-operated-updating-the
- 2004 NFA IN 9055 approval (SEC, SR-NFA-2004-02) — https://www.federalregister.gov/documents/full_text/xml/2004/10/15/E4-2654.xml
