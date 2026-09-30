# UK Regulatory Findings — Automated Trading Software (MT5 EAs) & Trading Signals
**Research date: 2026-09-20. Target year: 2026.**

## 0. Sourcing method, and version caveats (READ FIRST)

`fca.org.uk` and `handbook.fca.org.uk` return **HTTP 403 (Cloudflare)** to `web_fetch`. All FCA Handbook text below was obtained from `web.archive.org` copies of the official FCA Handbook PDFs and extracted with `pdftotext -layout`. legislation.gov.uk was reachable directly (XML `/data.xml` and `/data.xht?view=snippet` endpoints; the plain HTML view truncates provisions at ~2,000 chars and must not be used for quoting).

**Verified release versions of the Handbook text quoted below:**

| Source | Handbook release of the text I quote | Confirmed by |
|---|---|---|
| COBS 4 | **Release 32, Dec 2023** | running footer in PDF (`s Release 32 q Dec 2023`) |
| COBS 22 | **Release 40, Oct 2024** | running footer (`s Release 40 q Oct 2024`) |
| PRIN 2A | **Release 33, Feb 2024** | running footer (`s Release 33 q Feb 2024`) |
| PERG 4 | Release 35, Apr 2024 | running footer |
| PERG 8 | Release 36, May 2024 | running footer |

⚠️ **CURRENCY CAVEAT — mark as UNVERIFIED:** the newest *genuine* Wayback capture of `handbook.fca.org.uk/handbook/COBS/4.pdf` is the Dec 2023 release (Wayback CDX digest `U7ZQUOY5LPLDBBH53ETMZ6IEEQD6GB3U`, also served for 2024–2025 requests). The most recent capture (2025-10-28) returns a Cloudflare interstitial, not the PDF. **I could not verify that COBS 4/22 and PRIN 2A were not amended between those releases and September 2026.** The rule *numbers* cited are long-standing and stable, but before relying on any specific wording for a 2026 filing, re-check against the live Handbook. Flagged per-item below where it matters.

The text of legislation.gov.uk sources **is** current: RAO 2001 XML is stamped "up to date with all changes known to be in force on or before **20 September 2026**"; FSMA 2000 s.21 XML stamped **2026-09-09**.

---

## 1. COBS 4 — EXACT rule numbers and text

### 1.1 ⚠️ MAJOR CORRECTION to the premise of the question

The rule numbers assumed in the brief are **wrong**. The actual structure is:

| Assumed in brief | **Actual** heading and content |
|---|---|
| "COBS 4.5 (Past performance)" | **COBS 4.5 = "Communicating with retail clients (non-MiFID provisions)"** — general retail communication rules, *not* past performance. COBS 4.5.6R is **comparative information**, not past performance. |
| "COBS 4.5.2R past performance" | Past performance is **COBS 4.6.2R**. |
| "COBS 4.5.6R required past-performance warning" | The warning is **COBS 4.6.2R(4)** (non-MiFID) / **COBS 4.5A.10UK(d)** (MiFID). |
| "COBS 4.5A — maybe performance info" | **Correct in substance.** COBS 4.5A = **"Communicating with clients (including past, simulated past and future performance) (MiFID provisions)"** — the MiFID Org Regulation mirror of COBS 4.5/4.6. |
| "COBS 4.6 (Future performance)" | **COBS 4.6 = "Past, simulated past and future performance (non-MiFID provisions)"** — it covers all three. Future performance is **COBS 4.6.7R**. |

Correct section list for COBS 4: 4.1 Application · **4.2 Fair, clear and not misleading communications** · 4.3 Financial promotions to be identifiable as such · 4.4 Compensation information · **4.5 Communicating with retail clients (non-MiFID provisions)** · **4.5A Communicating with clients (including past, simulated past and future performance) (MiFID provisions)** · **4.6 Past, simulated past and future performance (non-MiFID provisions)** · 4.7 Direct offer financial promotions · 4.8 Cold calls · 4.9 Financial promotions with an appointed representative · **4.10 Approving and confirming compliance of financial promotions** · 4.11 Record keeping · 4.12A/4.12B Restricted mass market / non-mass market investments · 4.13 UCITS.

### 1.2 COBS 4.2 — Fair, clear and not misleading

**COBS 4.2.1R — "The fair, clear and not misleading rule"** (heading at 4.2.1/4.2.2 in the PDF layout; the rule is cited in-Handbook as **COBS 4.2.1R**):
> "(1) A firm must ensure that a communication or a financial promotion is fair, clear and not misleading.
> (2) This rule applies in relation to: (a) a communication by the firm to a customer in relation to designated investment business which is not MiFID, equivalent third country or optional exemption business, other than a third party prospectus; … (ab) a communication by the firm to a customer in relation to MiFID, equivalent third country or optional exemption business…; (b) a financial promotion communicated by the firm that is not: (i) an excluded communication; (ii) a non-retail communication; (iii) a third party prospectus; and (c) a financial promotion approved by the firm.
> (3) As part of complying with (1), a firm must take into account the nature of the client."

**COBS 4.2.2G** — proportionality guidance: the rule "applies in a way that is appropriate and proportionate taking into account the means of communication, the information the communication is intended to convey and the nature of the client and of its business"; a communication to a professional client or eligible counterparty "may not need to include the same information, or be presented in the same way, as a communication addressed to a retail client."

**COBS 4.2.3G** — signposts that Part 7 of the Financial Services Act 2012 "creates criminal offences relating to certain misleading statements and practices."

**COBS 4.2.4G — "Fair, clear and not misleading financial promotions"** (this is the **prominence/balance** provision):
> "A firm should ensure that a financial promotion: (1) **for a product or service that places a client's capital at risk makes this clear**; (2) that quotes a yield figure gives a balanced impression of both the short and long term prospects for the investment; (3) that promotes an investment or service whose charging structure is complex, or in relation to which the firm will receive more than one element of remuneration, includes the information necessary to ensure that it is fair, clear and not misleading and contains sufficient information taking into account the needs of the recipients; (4) that names the FCA, PRA or both as its regulator and refers to matters not regulated by either the FCA, PRA or both makes clear that those matters are not regulated by the FCA, PRA or either; (5) that offers packaged products or stakeholder products not produced by the firm, gives a fair, clear and not misleading impression of the producer of the product or the manager of the underlying investments."

**COBS 4.2.5G — "guaranteed"/"protected"/"secure"**:
> "A communication or a financial promotion should not describe a feature of a product or service as 'guaranteed', 'protected' or 'secure', or use a similar term unless: (1) that term is capable of being a fair, clear and not misleading description of it; and (2) the firm communicates all of the information necessary, and presents that information with sufficient clarity and prominence, to make the use of that term fair, clear and not misleading."

**COBS 4.2.6R — "The reasonable steps defence to an action for damages"** (this is the "must be able to show it has taken reasonable steps" point — note it is a **s.138D private-right-of-action defence, NOT a general "must be able to show" evidential rule**):
> "If, in relation to a particular communication or financial promotion, a firm takes reasonable steps to ensure it complies with the fair, clear and not misleading rule, a contravention of that rule does not give rise to a right of action under **section 138D** of the Act."

*Correction to brief:* there is **no** COBS 4.2 rule stating a firm "must be able to show it has taken reasonable steps" in the sense of a documentary obligation. COBS 4.2.6R is a damages defence. The closest documentary obligation is **COBS 4.11** (record keeping: financial promotion) and the **COBS 4.10.2R(1B)** quarterly attestation requirement (see §4.3).

### 1.3 COBS 4.5 — Communicating with retail clients (non-MiFID provisions)

**COBS 4.5.2R — "General rule"** (the retail general rule; the user's assumed "4.5.2R past performance" is wrong):
> "A firm must ensure that information: (1) includes the name of the firm (and also, where relevant, the name of the firm that has confirmed the compliance of the financial promotion for the purposes of COBS 4.10.9AR(3)(a)); (1A) where relevant, includes the date on which the financial promotion was approved; (2) **is accurate and always gives a fair and prominent indication of any relevant risks when referencing any potential benefits** of relevant business or a relevant investment; (3) is sufficient for, and presented in a way that is likely to be understood by, the average member of the group to whom it is directed, or by whom it is likely to be received; (4) **does not disguise, diminish or obscure important items, statements or warnings**; (5) **uses a font size in the indication of relevant risks that is at least equal to the predominant font size** used throughout the information provided, as well as a layout that ensures that such indication is prominent; (6) is consistently presented in the same language…; and (7) is up-to-date and relevant to the means of communication used."

**COBS 4.5.2AR** — where a promotion is by website/mobile app/digital medium and the approver name or approval date cannot reasonably be included, that information may be on a linked webpage, and the link **must be in the format: `Approver FRN [firm reference number of the firm that approved or confirmed the compliance of the financial promotion]`**.

**COBS 4.5.3G** — the firm name may be a trading name/shortened legal name provided the retail client can identify the communicating firm and, if different, the approving firm; the name and any 4.5.2AR link "should be given sufficient prominence to enable the retail client to easily identify the firm responsible for the compliance of the financial promotion."

**COBS 4.5.4G** — target-audience factors: "the nature of the product or business, the risks involved, the client's commitment, the likely information needs of the average recipient, and the role of the information in the sales process."

**COBS 4.5.5G** — omission: "a firm should consider whether omission of any relevant fact will result in the information being insufficient, unclear, unfair or misleading."

**COBS 4.5.6R — "Comparative information"** (NOT past performance):
> "If information compares relevant business, relevant investments, or persons who carry on relevant business, a firm must ensure that the comparison is meaningful and presented in a fair and balanced way."

**COBS 4.5.7R — "Referring to tax"**; **COBS 4.5.8R — "Consistent financial promotions"** ("A firm must ensure that information contained in a financial promotion is consistent with any information the firm provides to a retail client in the course of carrying on designated investment business."); **COBS 4.5.16R** — FIIA risk warning (illiquid assets), with prescribed wording and prominence rule. (4.5.9–4.5.15 cover innovative finance ISAs, lifetime ISAs and authorised fund benchmark communications.)

### 1.4 COBS 4.5A — Communicating with clients (including past, simulated past and future performance) (MiFID provisions)

Applies to information / financial promotion relating to the firm's **MiFID, equivalent third country or optional exemption business** (COBS 4.5A.1R). Provisions marked **"UK"** apply in relation to MiFID optional exemption business as if they were rules (COBS 4.5A.2R). Text is the **onshored MiFID Org Regulation art. 44**; the PDF prints the article number alongside each rule.

- **COBS 4.5A.3UK (= art. 44(1)–(2))** — general conditions: name of the investment firm; accurate with "a fair and prominent indication of any relevant risks when referencing any potential benefits of an investment service or financial instrument"; risk-indication font size at least equal to predominant font size with prominent layout; sufficient for and likely to be understood by the average member of the group; "does not disguise, diminish or obscure important items, statements or warnings"; consistent language; up-to-date and relevant to the means of communication.
- **COBS 4.5A.7UK (= art. 44(3))** — comparative information: "(a) the comparison is meaningful and presented in a fair and balanced way; (b) the sources of the information used for the comparison are specified; (c) the key facts and assumptions used to make the comparison are included."
- **COBS 4.5A.8UK (= art. 44(7))** — tax.
- **COBS 4.5A.9UK (= art. 46(5))** — consistency of marketing communications.
- **COBS 4.5A.10UK (= art. 44(4)) — PAST PERFORMANCE.** Conditions: (a) "that indication **is not the most prominent feature** of the communication"; (b) appropriate performance information covering the preceding 5 years (or whole period offered/established/provided if less), "in every case that performance information is based on complete 12-month periods"; (c) reference period and source clearly stated; **(d) "the information contains a prominent warning that the figures refer to the past and that past performance is not a reliable indicator of future results"**; (e) currency clearly stated plus warning that return may increase or decrease as a result of currency fluctuations; (f) where based on gross performance, the effect of commissions, fees or other charges are disclosed.
- **COBS 4.5A.11G** — proportionality; a periodic statement under COBS 16/16A "may include past performance as its most prominent feature."
- **COBS 4.5A.12UK (= art. 44(5)) — SIMULATED PAST PERFORMANCE.** "Where the information includes or refers to simulated past performance, investment firms shall ensure that **the information relates to a financial instrument or a financial index**, and the following conditions are satisfied: 44(5)(a) the simulated past performance is based on the actual past performance of one or more financial instruments or financial indices which are the same as, or substantially the same as, or underlie, the financial instrument concerned; 44(5)(b) in respect of the actual past performance referred to in point (a), the conditions set out in points (a) to (c), (e) and (f) of paragraph 4 are satisfied; **44(5)(c) the information contains a prominent warning that the figures refer to simulated past performance and that past performance is not a reliable indicator of future performance.**"
- **COBS 4.5A.14UK (= art. 44(6)) — FUTURE PERFORMANCE.** (a) "the information **is not based on or refer to simulated past performance**"; (b) "based on reasonable assumptions supported by objective data"; (c) "where the information is based on gross performance, the effect of commissions, fees or other charges is disclosed"; (d) "based on performance scenarios in different market conditions (both negative and positive scenarios), and reflects the nature and risks of the specific types of instruments included in the analysis"; **(e) "the information contains a prominent warning that such forecasts are not a reliable indicator of future performance."**
- **COBS 4.5A.16UK (= art. 44(8))** — "The information shall not use the name of any competent authority in such a way that would indicate or suggest endorsement or approval by that authority of the products or services of the investment firm." **(Directly relevant to any "FCA-regulated/approved" marketing claim.)**
- **COBS 4.5A.17R** — FIIA risk warning with prescribed wording.

### 1.5 COBS 4.6 — Past, simulated past and future performance (non-MiFID provisions)

**COBS 4.6.1R — Application:** applies to (b) "the communication or approval of a financial promotion" addressed to / likely to be received by a **retail client**; does **not** apply to a firm communicating in relation to its MiFID, equivalent third country or optional exemption business (so 4.6 and 4.5A are mutually exclusive); does not apply to excluded communications, Prospectus Regulation art. 22 advertisements, image advertising, non-structured deposits, or long-term care insurance contracts.

**COBS 4.6.2R — "Past performance" (the key rule):**
> "A firm must ensure that information that contains an indication of past performance of relevant business, a relevant investment or a financial index, satisfies the following conditions:
> (1) **that indication is not the most prominent feature of the communication**;
> (2) the information includes appropriate performance information which covers **the preceding five years**, or the whole period for which the investment has been offered, the financial index has been established, or the service has been provided (where less than five years, or such longer period as the firm may decide), and in every case that performance information must be based on **complete 12-month periods**;
> (3) the reference period and the source of information are clearly stated;
> **(4) the information contains a prominent warning that the figures refer to the past and that past performance is not a reliable indicator of future results;**
> (5) if the indication relies on figures denominated in a currency other than pounds sterling, the currency is clearly stated, together with a warning that the return may increase or decrease as a result of currency fluctuations;
> (6) **if the indication is based on gross performance, the effect of commissions, fees or other charges is disclosed.**"

**COBS 4.6.3G** — proportionality; a periodic statement under COBS 16 "may include past performance as its most prominent feature."
**COBS 4.6.4G / 4.6.4AG / 4.6.4BG / 4.6.5G** — packaged products: prescribed percentage-growth table, prominence ("no less prominently than any other past performance information"), offer-to-bid / bid-to-bid pricing bases.

**COBS 4.6.6R — "Simulated past performance"** (the rule the brief was looking for):
> "A firm must ensure that information that contains an indication of simulated past performance of relevant business, a relevant investment or a financial index, satisfies the following conditions:
> **(1) it relates to an investment or a financial index;**
> (2) the simulated past performance is based on the actual past performance of one or more investments or financial indices which are the same as, substantially the same as, or underlie, the investment concerned;
> (3) in respect of the actual past performance referred to in (2), the conditions set out in paragraphs (1) to (3), (5) and (6) of the rule on past performance (COBS 4.6.2R) are complied with; and
> **(4) the information contains a prominent warning that the figures refer to simulated past performance and that past performance is not a reliable indicator of future performance.**"

*Note:* COBS 4.6.6R does **not** in terms say "must not be presented as actual". That effect arises from (1) read with (2) — simulated performance must relate to a real investment/index and be derived from real past performance — plus the mandatory warning in (4) that the figures "refer to simulated past performance". The brief's assumed "must not be presented as actual" wording is **not** the rule text.

**COBS 4.6.7R — "Future performance":**
> "(1) A firm must ensure that information that contains an indication of future performance of relevant business, a relevant investment, a structured deposit or a financial index, satisfies the following conditions:
> **(a) it is not based on and does not refer to simulated past performance;**
> (b) it is based on reasonable assumptions supported by objective data;
> **(c) where the indication is based on gross performance, the effect of commissions, fees or other charges is disclosed;**
> (ca) it is based on performance scenarios in different market conditions (both negative and positive scenarios), and reflects the nature and risks of the specified types of investments included in the analysis; and
> **(d) it contains a prominent warning that such forecasts are not a reliable indicator of future performance.**
> (2) This rule only applies in relation to financial promotions that relate to a financial instrument (or a financial index that relates exclusively to financial instruments) or a structured deposit."

**COBS 4.6.8G** — a firm "should not provide information on future performance if it is not able to obtain the objective data needed" to comply.

**COBS 4.6.9R** — projections for a packaged product that is not a financial instrument must comply with the projections rules in COBS 13.4, COBS 13.5 and COBS 13 Annex 2; "A firm must not communicate a projection for a highly volatile product to a client unless the product is a financial instrument."

**There is NO COBS 4.6.2R rule prohibiting a claim that future performance is "guaranteed" as such.** The prohibition on "guaranteed"/"protected"/"secure" language is **COBS 4.2.5G** (guidance). COBS 4.6.7R(1)(b)+(d) is the operative constraint on projections. Mark the brief's "4.6.2R must not claim future performance is guaranteed" as **INCORRECT**.

**Net position for an EA/signal vendor's marketing:** any backtest equity curve or live track record is an "indication of past performance" (live) or "simulated past performance" (backtest), and any projection is "future performance". All three regimes bite: not-most-prominent, 5-year/complete-12-month-period data, stated reference period and source, **mandatory prescribed warnings**, currency warning, gross-of-fees disclosure, no simulated-performance basis for projections, and scenario-based projections.

---

## 2. Risk warnings and the CFD product intervention

### 2.1 COBS 22.5 — Restrictions on the retail marketing, distribution and sale of contracts for differences and similar speculative investments

**Application — COBS 22.5.1R:** applies to MiFID investment firms (except collective portfolio management investment firms) and branches of third country investment firms, "in relation to the marketing, distribution or sale of **restricted speculative investments** in or from the United Kingdom to a retail client." **COBS 22.5.4G:** "'marketing' restricted speculative investments includes communicating and/or approving financial promotions, and 'distribution or sale' includes dealing in relation to restricted speculative investments." Exclusions: COBS 22.5.1AR (restricted options sold through an intermediary), COBS 22.5.5R (art. 85(3) credit-risk derivatives; cryptoasset derivatives — the latter prohibited under COBS 22.6).

**Standardised risk warning — COBS 22.5.6R(1A).** Where a firm markets, distributes or sells leveraged CFDs, leveraged spread bets or leveraged rolling spot forex contracts, it must include:
> **"CFDs are complex instruments and come with a high risk of losing money rapidly due to leverage.**
> **[insert percentage per provider]% of retail investor accounts lose money when trading CFDs with this provider.**
> **You should consider whether you understand how CFDs work and whether you can afford to take the high risk of losing your money."**

(Parallel wordings are prescribed for CFDs + restricted options, and for restricted options alone.)

**⚠️ The "70%" point — the brief's premise is wrong.** There is **no fixed 70% figure in the UK rules**. The warning uses a **firm-specific placeholder** `[insert percentage per provider]%`, and:
- **COBS 22.5.6R(2)–(7):** the warning must be modified to refer to the percentage of retail client accounts that lost money **relevant to the firm**; the disclosure must be an up-to-date percentage based on the firm's own retail client accounts; **the calculation must be performed every three months and cover the 12-month period preceding the date of the calculation**; an account is treated as having lost money if the sum of all realised and unrealised net profits on restricted speculative investments traded in that account during the 12-month period is below zero; the calculation **must include all costs, fees, commissions and any other charges**; and must exclude accounts with no open restricted speculative investment in the period, profits/losses from other investments, and deposits of funds.
- PS19/18 originally proposed the generic line *"The vast majority of retail client accounts lose money when trading in CFDs"* (PS19/18 ¶2.49ff, and see the consultation text at pp. ~118/132 of the PDF); the final rule replaced it with the firm-specific percentage. PS19/18 ¶1.15 describes the final package as "provide a standardised risk warning, telling potential customers the percentage of the firm's retail client accounts that make losses."
- Separately, the **FCA's press material uses an 80% figure**: in its September 2025 finfluencer press release the FCA states "**80% of customers lose money when investing in CFDs** because of the risks" (see §4.4). That is an FCA public statement, **not** a rule.

**Prominence — COBS 22.5.8R:** the relevant risk warning must be (1) prominent; (2) contained within its own border and with bold and unbold text as indicated; (3) if on a website or mobile app, **statically fixed and visible at the top of the screen even when the retail client scrolls**; and (4) if on a website, **included on each linked webpage**. **COBS 22.5.9G:** proportionate to content/size/orientation and published against a neutral background.

**Leverage / margin — COBS 22.5.11R.** A firm must require a retail client to post margin to open a position of at least:
| Underlying asset | Margin | Equivalent leverage |
|---|---|---|
| Major foreign exchange pair or relevant sovereign debt | **3.33%** of exposure | **30:1** |
| Major stock market index, minor FX pair, or **gold** | **5%** | **20:1** |
| Minor stock market index, or a commodity other than gold | **10%** | **10:1** |
| (4) **[deleted]** | — | — |
| A share, or an asset not otherwise listed in (1)–(4) | **20%** | **5:1** |

COBS 22.5.10R: margin posted to **open** a position must be in the form of money. COBS 22.5.14R: margin posted to **maintain** an open position must be in the form of money. COBS 22.5.12G gives worked "exposure" examples.

**⚠️ FCA limits are NOT identical to ESMA's.** Two differences confirmed from PS19/18 ¶1.9 and ¶2.30:
1. The FCA's rules **apply to a wider range of products by including CFD-like options**.
2. The FCA set leverage for CFDs referencing **certain government bonds at 30:1, compared with 5:1 under ESMA's measures**. PS19/18 ¶2.30: "Our proposed leverage limits only differed from ESMA's temporary leverage limits for CFDs referencing certain government bonds, which we have set at 30:1 compared with 5:1."
3. ESMA's temporary regime had a **2:1 (50%) tier for cryptocurrencies**; the FCA's COBS 22.5.11R(4) is **[deleted]** — cryptoasset derivatives are instead **prohibited** for retail under COBS 22.6. So the FCA ladder is **30:1 / 20:1 / 10:1 / 5:1**, not "30:1/20:1/10:1/5:1/2:1".

**50% margin close-out — COBS 22.5.13R:**
> "(1) A firm must ensure a retail client's net equity in an account used to trade restricted speculative investments **does not fall below 50% of the margin requirement** (as outlined in COBS 22.5.11R) required to maintain the retail client's open positions. (2) Where a retail client's net equity falls below 50% of the margin requirement, the firm **must close the retail client's open position(s) … as soon as market conditions allow**. (3) In this rule, 'net equity' means the sum of the retail client's net profit and loss on their open position(s) and the retail client's deposited margin."

**COBS 22.5.15R** — firm must provide a clear description in a durable medium (or on a website meeting the website conditions) of how the margin close-out level will be calculated and triggered, in good time before the client opens their first position and before any change to T&Cs takes effect. **COBS 22.5.16G** reminds firms of COBS 2.1.1R (best interests) and COBS 11.2A.2R (best execution) when making margin calls or closing positions.

**Negative balance protection — COBS 22.5.17R:**
> "The liability of a retail client for all restricted speculative investments connected to the retail client's account **is limited to the funds in that account**."
COBS 22.5.18G: a retail client cannot lose more than the funds specifically dedicated to trading restricted speculative investments. COBS 22.5.19G: "funds" = cash in the account and unrealised net profits from open positions.

**Inducements ban — COBS 22.5.20R:** a firm must not offer or provide a retail client any monetary or non-monetary incentive when marketing, distributing or selling a restricted speculative investment. COBS 22.5.21G: monetary incentives include bonuses for opening a new account and fee rebates (including volume-based rebates); lower fees offered to all retail clients are not a monetary incentive; information and research tools are not non-monetary incentives.

**COBS 22.5.22G — "Other products":** firms marketing derivatives with similar features to restricted speculative investments (particularly leveraged ones) should have particular regard to COBS 2.1.1R, **COBS 4.2.1R**, COBS 9A, COBS 10A, PRIN (principles 1, 2 and 6) and PROD 3.

### 2.2 PS19/18

**FCA PS19/18, "Restricting contract for difference products sold to retail clients", published 2019.** Confirmed content: ¶1.15 sets out the five measures (leverage 30:1–2:1; 50% close-out; negative balance protection; inducements ban; standardised risk warning). ¶1.9 confirms the government-bond divergence from ESMA and the inclusion of CFD-like options. The rules were made as **COBS 22.5** and took effect **29 July 2019** (UNVERIFIED as to exact commencement date from the copy I hold — the PS text I extracted does not print the commencement date in the sections read; the widely-cited date is 29 July 2019, but I did not confirm it from a primary source).
- Primary URL: `https://www.fca.org.uk/publication/policy/ps19-18.pdf` (403 direct; retrieved via `https://web.archive.org/web/2025id_/https://www.fca.org.uk/publication/policy/ps19-18.pdf`)
- Consultation: CP18/38.

---

## 3. Consumer Duty (PRIN 2A)

### 3.1 Application and dates
- **Principle 12** is the Consumer Duty principle; **PRIN 2A** contains the rules. PRIN 2A.1.1R/2A.1.2R cross-refer.
- **PRIN 2A.1.3G:** "Principle 12 applies in relation to a firm's **retail market business** or where the firm **communicates or approves financial promotions** which are addressed to, or disseminated in such a way that they are likely to be received by, a **retail customer**. To the extent that Principle 12 applies, **Principles 6 and 7 do not apply**."
- **PRIN 2A.1.4G:** "The definition of a **product** for the purposes of Principle 12 and PRIN 2A includes both **products and services**." **PRIN 2A.1.5G:** "retail customer" includes a **prospective customer**.
- **PRIN 2A.1.6G:** rules "are to be interpreted in accordance with the standard that could reasonably be expected of a **prudent firm carrying on the same activity in relation to the same product**" (see PRIN 2A.7.1R).
- **PRIN 2A.1.11G:** Principle 12 "does not create a fiduciary relationship where one would not otherwise exist **nor require a firm to provide advice or carry out any other regulated activity where it would not otherwise have done so**." *(Important for software/signal vendors: the Duty does not itself convert a non-regulated software sale into a regulated activity.)*
- **PRIN 2A.1.12G:** "The FCA has issued guidance on the Consumer Duty in **FG22/5**, which firms should read alongside Principle 12 and PRIN 2A."
- **Closed products:** PRIN 2A.1.10G(4) — "There are particular provisions concerning **closed products** and existing products distributed to retail customers **before 31 July 2023** in PRIN 2A.3 and PRIN 2A.4." PRIN 2A.3.3G, 2A.3.15G, 2A.3.21R, 2A.4.4G, 2A.4.29R all turn on the **31 July 2023** date; PRIN 2A.11.2R–2A.11.5R turn on purchases of product books before/after 31 July 2023.
- **Application dates:** the brief's dates (31 July 2023 open products; 31 July 2024 closed products) are consistent with the PRIN 2A text I extracted, but note that the **PRIN 2A copy I hold is Release 33 (Feb 2024)**, so I did **not** independently verify the 31 July 2024 closed-products date from a primary FCA publication. **Mark the 31 July 2024 date as UNVERIFIED-from-primary** (it is well established; confirm at `https://www.fca.org.uk/firms/consumer-duty`).

### 3.2 The four outcomes and the cross-cutting rules
**PRIN 2A.1.10G(3):** "The retail customer outcome rules and guidance at PRIN 2A.3 to PRIN 2A.6 set out firms' key obligations in relation to **product governance, price and value, consumer understanding and supporting consumers**."

| Outcome | Section | Key rules |
|---|---|---|
| Products and services | **PRIN 2A.3** | 2A.3.2R (manufacturer product governance, non-closed products), 2A.3.5R (closed products), 2A.3.9R/2A.3.10R (testing), 2A.3.12R (distribution channels), 2A.3.17R–2A.3.19R (distributor), 2A.3.21R (existing contracts pre-31 July 2023) |
| **Price and value** | **PRIN 2A.4** | 2A.4.1R, 2A.4.2R, 2A.4.3R, 2A.4.5R, 2A.4.7R, 2A.4.8R, 2A.4.21R, 2A.4.24R–2A.4.29R |
| Consumer understanding | **PRIN 2A.5** | 2A.5.3R–2A.5.14R |
| Consumer support | **PRIN 2A.6** | 2A.6.1R–2A.6.5R |

**Cross-cutting obligations — PRIN 2A.2:** 2A.2.1R (**act in good faith**), 2A.2.5R (**avoid causing foreseeable harm**), 2A.2.14R (**enable and support retail customers to pursue their financial objectives**). PRIN 2A.2.2R: "Acting in good faith is a standard of conduct characterised by honesty, fair and open dealing and acting consistently with the reasonable expectations of retail customers." PRIN 2A.2.9R: foreseeable harm may be caused by both act and omission.

### 3.3 Price and value applied to software subscription pricing
- **PRIN 2A.4.1R:** "value is the relationship between the amount paid by a retail customer for the product and the benefits they can reasonably expect to get from the product; and … **a product provides fair value where the amount paid for the product is reasonable relative to the benefits of the product**."
- **PRIN 2A.4.2R:** "A manufacturer must: (1) ensure that its products provide fair value to retail customers in the target markets for those products; and (2) **carry out a value assessment** of its products and review that assessment on a regular basis."
- **PRIN 2A.4.3R:** an initial value assessment must be carried out for a product and any significant adaptation **before it is marketed or distributed to a retail customer**.
- **PRIN 2A.4.8R:** the value assessment "must include (but is not limited to)": (1) nature of the product, benefits reasonably expected and its quality; (2) any limitations that are part of the product; (3) **the expected total price to be paid** — including (a) price paid on entering the contract, (b) **any regular charges or fees payable over the lifetime of the product, for example an annual management charge**, (c) any contingent fees or charges, and (d) any non-financial costs the retail customer is asked or required to provide; and (4) **any characteristics of vulnerability** in the target market and the impact on the likelihood of not receiving fair value.
- **PRIN 2A.4.9G:** factors that may be considered include (1) costs incurred by the firm, (2) **the market rate and charges for a comparable product**, (3) accrued costs/benefits for existing or closed products, and (4) whether products are priced significantly lower for some customers.
- **PRIN 2A.4.7R:** where a product is provided with other products, each component **and the package as a whole** must provide fair value.
- **PRIN 2A.4.24R–2A.4.27R:** regular review of the value assessment; where a manufacturer identifies the product no longer provides fair value, appropriate action includes **notifying distributors**; a distributor identifying the same must act.

**I found no FCA statement specifically addressing software subscription pricing under the price and value outcome.** The general "expected total price" language in PRIN 2A.4.8R(3)(b) (recurring charges over the product's lifetime) and the "market rate for a comparable product" factor in PRIN 2A.4.9G(2) are the applicable hooks. **Mark "FCA statements on software subscription pricing" as UNVERIFIED / none found.** FG22/5 (retrieved, 407,914 chars) should be checked for any pricing examples.

### 3.4 How the Duty applies to financial promotions
- **PRIN 2A.1.3G** (above): Principle 12 applies where a firm communicates or approves financial promotions likely to be received by a retail customer.
- **PRIN 2A.1.15AG:** "where a firm's sole activity subject to obligations under Principle 12 is communicating or approving a financial promotion, the rules and guidance in PRIN 2A.3 (products and services), **PRIN 2A.4 (price and value)**, PRIN 2A.6 (customer support) and PRIN 2A.11 (sale and purchase of product books) are **likely to have limited relevance**." — i.e. for a pure promoter, the **consumer understanding** outcome (PRIN 2A.5) does the heavy lifting.
- **FG24/1 ¶1.2:** "Under the Consumer Duty (the Duty), financial promotions must **support retail customer understanding** and communicate information to retail customers in a way that equips them to make effective decisions."
- **FG24/1 ¶1.4:** "We expect promotions to provide a **balanced view of the benefits and risks**…"

---

## 4. Financial promotions, the s.21 gateway, and finfluencers

### 4.1 FSMA 2000 s.21 — exact statutory wording
(legislation.gov.uk, current to 2026-09-09)
> **21 Restrictions on financial promotion.**
> "(1) A person ('**A**') must not, in the course of business, **communicate an invitation or inducement to engage in investment activity**, or to engage in claims management activity.
> (2) But subsection (1) does not apply if— (a) A is an authorised person; or (b) **the content of the communication is approved for the purposes of this section by an authorised person**.
> **(2A) The content of a communication may be approved for the purposes of this section by an authorised person only if the giving of the approval— (a) is permitted under section 55NA (which enables approval to be given with FCA permission), or (b) falls within an exemption conferred by regulations under section 55NB.**
> (3) In the case of a communication originating outside the United Kingdom, subsection (1) applies only if the communication is **capable of having an effect in the United Kingdom**.
> (4) The Treasury may by order specify circumstances in which a person is to be regarded for the purposes of subsection (1) as— (a) acting in the course of business; (b) not acting in the course of business.
> (5) The Treasury may by order specify circumstances (which may include compliance with financial promotion rules) in which subsection (1) does not apply. …
> (8) 'Engaging in investment activity' means— (a) entering or offering to enter into an agreement the making or performance of which by either party constitutes a controlled activity; or (b) exercising any rights conferred by a controlled investment to acquire, dispose of, underwrite or convert a controlled investment. …"
> Definitions: "'**Communicate**' includes **causing a communication to be made**." (s.21(13) area)

URL: `https://www.legislation.gov.uk/ukpga/2000/8/section/21` (use `/data.xht?view=snippet&wrap=true` for full text). s.19 (general prohibition): `https://www.legislation.gov.uk/ukpga/2000/8/section/19`. s.138D (action for damages): `https://www.legislation.gov.uk/ukpga/2000/8/section/138D`.

**Penalty (FG24/1 ¶2.4):** "A breach of s21 is a criminal offence which is punishable by **up to 2 years imprisonment, the imposition of an unlimited fine, or both**."

### 4.2 The s.21 approval gateway — CORRECT SI NUMBERS
⚠️ **The brief's "SI 2023/1217" is wrong.** `SI 2023/1217` is *The Persistent Organic Pollutants (Amendment) (No. 2) Regulations 2023*. The correct instruments are:

| Instrument | Number | URL |
|---|---|---|
| **FSMA 2000 (Financial Promotion) (Amendment) (No. 2) Order 2023** — the gateway SI | **SI 2023/1411** (made 19 Dec 2023, **in force 31 January 2024**) | `https://www.legislation.gov.uk/uksi/2023/1411/contents` |
| **FSMA 2000 (Exemptions from Financial Promotion General Requirement) Regulations 2023** — the "**Financial Promotion Gateway Exemptions Regulations**" | **SI 2023/966** | `https://www.legislation.gov.uk/uksi/2023/966/contents` |
| **FSMA 2000 (Financial Promotion) (Amendment) Order 2023** — this is the **cryptoasset** promotions SI, *not* the gateway | **SI 2023/612** | `https://www.legislation.gov.uk/uksi/2023/612/contents` |
| FSMA 2000 (Financial Promotion) (Amendment and Transitional Provision) Order 2024 | SI 2024/301 | `https://www.legislation.gov.uk/uksi/2024/301/contents` |

**Statutory basis:** **FSMA 2000 ss.55NA and 55NB**, inserted by **Financial Services and Markets Act 2023 (c. 29), s.20(3)**, brought into force **7 February 2024** ("in so far as not already in force"). Note the distinction: **SI 2023/1411 came into force 31 January 2024**, while **ss.55NA/55NB were commenced for all remaining purposes on 7 February 2024** — which is why the FCA and the trade press cite 7 February 2024 as the operative date.

> **FSMA s.55NA(1):** "An authorised person **must not approve the content of a communication for the purposes of section 21 unless the person has permission to do so given by the FCA** under this section."
> **s.55NA(2):** "An authorised person who approves the content of a communication for the purposes of section 21 otherwise than in accordance with permission granted under this section is to be taken to have **contravened a requirement imposed on the person by the FCA** under this Act."
> **s.55NA(3):** permission may be granted on the application of an authorised person, or an applicant for Part 4A permission that has yet to be determined.
> **s.55NB(1):** "The Treasury may by regulations provide for **exemptions** from the requirement imposed by section 55NA(1)…"

**COBS 4.10.1BG(1)** (FCA guidance confirming the date): "The effect of **section 55NA** of the Act is that, **with effect from 7 February 2024**, a firm is unable to approve a financial promotion unless: (a) the firm is a **permitted approver** in relation to the financial promotion; or (b) an **approver permission exemption** applies." COBS 4.10.1BG(2): "**SUP 6A** contains guidance on applying for approver permission." COBS 4.10.1BG(3): obligations continue after a firm ceases to be entitled to approve — it may withdraw approval but cannot approve amendments.

**FCA page — "Approving financial promotions"** (`https://www.fca.org.uk/firms/financial-promotions-and-adverts/approving-financial-promotions`, first published 26/11/2019, last updated 28/05/2024):
> "A firm can only approve a financial promotion if the **FCA has granted the firm permission** to do so, or the approval falls within the scope of an exemption from the requirement for permission. If you intend to begin approving the financial promotions of unauthorised persons, then you may need to apply for permission to do so. **SUP 6A** in the FCA Handbook contains guidance on applying for permission to approve financial promotions…"
> **FCA permission is NOT required** to approve financial promotions in the following circumstances: (a) approvals of promotions prepared by a firm's **Appointed Representatives (ARs)**, where the promotions relate to the regulated activities the AR is permitted to undertake under the responsibility of the firm; (b) approvals of promotions prepared by **unauthorised persons within a firm's corporate group**; (c) approvals of an **authorised person's own** financial promotions for the purpose of communication by an unauthorised person.
> "If you are granted permission to approve financial promotions, you will need to comply with the **reporting requirements** for approvers of financial promotions… This involves **ad-hoc notifications** to us about your approval activity and a **bi-annual report**."

**Related COBS 4.10 rules:**
- **COBS 4.10.2R(1):** before approving for communication by an unauthorised person, the firm "must confirm that the financial promotion complies with the financial promotion rules."
- **COBS 4.10.2R(1A):** ongoing monitoring of continuing compliance.
- **COBS 4.10.2R(1B)–(1C):** the firm must require from the unauthorised person a **written quarterly attestation** that there has been no material change to the promotion or to circumstances affecting its continuing compliance; **first attestation no less than 3 months after approval, and thereafter at least once every 3 months** for as long as the promotion is communicated.
- **COBS 4.10.2R(2):** if the firm becomes aware the promotion no longer complies, it "**must withdraw its approval and notify any person that it knows to be relying on its approval** as soon as reasonably practicable."
- **COBS 4.10.9AR:** "A firm must not communicate or approve a financial promotion unless the individual or individuals responsible for the compliance of the financial promotion with the financial promotion rules has or have **appropriate competence and expertise**." (2) competence/expertise "in the investment or financial service to which the financial promotion relates". (3) if a firm (A) determines it lacks appropriate competence and expertise it must either (a) **have another firm (B) confirm that the financial promotion complies** with the financial promotion rules before A communicates it, or (b) **decline to approve**. (4) "A **registered person is not permitted** to confirm the compliance of a financial promotion for the purpose of COBS 4.10.9AR(3)."
- **COBS 4.10.9BR:** a firm must not confirm compliance unless satisfied the promotion complies and the responsible individual has appropriate competence and expertise; and must not confirm compliance for a promotion to be made in the course of a **personal visit, telephone conversation or other interactive dialogue**.
- **COBS 4.10.10R:** reliance on another firm's confirmation of compliance, including (d) taking reasonable care to establish that B **did not breach the approver permission requirement**.
- **COBS 4.10.12R:** conflicts of interest — a firm that approves a promotion for communication by an unauthorised person, or confirms compliance, must take all appropriate steps to identify and prevent or manage conflicts of interest.

### 4.3 FG24/1 — Finalised guidance on financial promotions on social media
**Confirmed: FCA FG24/1, "Finalised guidance on financial promotions on social media", March 2024.** Wayback captures of the PDF begin **26 March 2024** (`https://web.archive.org/web/20240326101604/https://www.fca.org.uk/publication/finalised-guidance/fg24-1.pdf`). Landing page: `https://www.fca.org.uk/publications/finalised-guidance/fg24-1-finalised-guidance-financial-promotions-social-media`. Direct PDF: `https://www.fca.org.uk/publication/finalised-guidance/fg24-1.pdf` (403 direct; use Wayback).

Key exact text:
- **¶1.1:** "This Guidance clarifies our expectations of firms and others, such as influencers, communicating financial promotions on social media. Our financial promotion rules are **technology neutral** and apply across all channels used to advertise, including social media."
- **¶1.3:** "We expect financial promotions to be **standalone compliant**. This means that **each communication must comply with our rules when considered individually**."
- **¶1.4:** "We expect promotions to provide a **balanced view of the benefits and risks**…"
- **¶1.5:** "…in promotions for high-risk investments (HRIs), we expect the prescribed risk warning to be **displayed throughout the promotion and not to be obscured or truncated by a design feature of the social media platform**."
- **¶1.6:** "Firms working with affiliate marketers, such as influencers, should take **proactive responsibility** for how their affiliates communicate financial promotions… **Firms remain responsible for the compliance of every promotion they make or cause to be made.**"
- **¶1.7:** "**Unauthorised persons, such as influencers, who promote financial products or services that are subject to regulation without the approval of an FCA authorised person may be committing a criminal offence.**"
- **¶1.8:** "**Even when an influencer does not have a commercial relationship with a firm**, their communications on social media about financial products or services **may still be subject to the financial promotion restriction and require approval to communicate**."
- **¶1.9:** ASA expectation to label content as an advertisement upfront, including affiliate links, if they get any form of payment.
- **¶1.11:** FG24/1 **replaces FG15/4** (Social media and customer communications).
- **¶1.12:** "The Guidance below **does not create new obligations** for firms. Rather, it indicates how firms might approach complying with their existing regulatory obligations."
- **¶2.4:** territorial breadth + criminal penalty (up to 2 years / unlimited fine).
- **¶2.6:** "An **illegal** financial promotion is one communicated in breach of s21." **¶2.7:** "A **non-compliant** financial promotion is one that has been lawfully communicated under s21 of FSMA but breaches our financial promotion rules."
- **¶2.8:** "**Any form of communication (including through social media) is capable of being a financial promotion if it includes an invitation or inducement to engage in investment activity. This can include communications through 'private' or invitation only social media channels, like chatrooms such as Discord and Telegram.**" *(Directly on point for paid signal groups.)*
- **¶2.18:** "Firms approving financial promotions should familiarise themselves with our guidance on approving financial promotions. Firms also need to consider **whether they require FCA permission to approve financial promotions for unauthorised persons**. Guidance on the need for permission to approve financial promotions can be found in **PERG 8.9**…"
- **¶2.20:** standalone compliance restated.

### 4.4 FCA enforcement against finfluencers (2024–2026)
**Confirmed primary source — FCA press release, "First court appearance for three 'finfluencers' charged in FCA-led global crackdown on illegal promotions"**, first published **10/09/2025**, last updated **13/10/2025**:
- Charles Hunter, Kayan Kalipha and Luke Desmaris appeared before **Westminster Magistrates' Court**, each individually charged with an offence relating to their social media posts.
- "The individuals – often referred to as 'finfluencers' – are alleged to have **encouraged social media followers to invest in foreign exchange (forex or FX) trading through high-risk products known as contracts for difference, without having the authorisation to promote these investments**."
- "The individuals are each charged with **one count of communicating an invitation to engage in investment activity, contrary to section 21(1) of the Financial Services and Markets Act 2000**."
- "A person who contravenes Section 21(1) of the Financial Services and Markets Act 2000 can be punished on indictment by a **fine and/or up to 2 years' imprisonment**."
- All three **pleaded not guilty**; attended **Southwark Crown Court** on **8 October 2025** for a plea and trial preparation hearing. Final hearings set: **Charles Hunter – 6 September 2027; Kayan Kalipha – 25 October 2027; Luke Desmaris – 29 November 2027.**
- "In **June 2025**, the FCA led a coordinated international enforcement effort involving **nine regulators across six countries**. The operation resulted in **arrests, interviews, cease and desist letters, and over 650 takedown requests** across social media platforms and websites."
- "The FCA has previously said that **80% of customers lose money when investing in CFDs** because of the risks."
- URL: `https://www.fca.org.uk/news/press-releases/first-court-appearance-three-finfluencers-charged-fca-led-global-crackdown-illegal-promotions`

**UNVERIFIED:** I could not retrieve the companion FCA "news story" page on the June 2025 global action (`.../news/news-stories/fca-participates-global-action-stop-illegal-finfluencers`) — the archive connection was reset. Any additional 2024 finfluencer final notices/decision notices are **UNVERIFIED** from primary sources in this research.

### 4.5 Copy trading / signals — FCA's own position
**FCA page "Copy trading"** (`https://www.fca.org.uk/firms/copy-trading`, first published 12/05/2015, **last updated 27/07/2026**):
> "**We classify copy trading as portfolio or investment management where no manual input is clear from the account holder.** This entails standard regulatory obligations for authorised management."
> "We support the view set out in question nine of ESMA's MiFID Questions and Answers: Investor Protection & Intermediaries as to how copy and mirror trading fit within the MiFID Directive. **It considers them an automatic execution of trade signals.**"
> "A platform may allow its clients to choose one or more third parties who provide trade signals… Once the client chooses a signal provider and authorises the service provider to issue orders on their behalf, the service provider transforms each signal into a buy or sell order to be executed by the service provider itself or transmitted for execution to another firm, **without further intervention from the client**."
> "This service falls within **Article 4(1)(9) of MiFID**… 'managing portfolios in accordance with mandates given by clients on a discretionary client-by-client basis'… In copy trading and mirror trading, investment decisions are implemented with **no intervention by the client other than an agreement ('mandate')**…"
> "Where the service described above is provided through MiFID financial instruments, it **requires portfolio management authorisation from us**… Where MiFID applies, this triggers associated ongoing regulatory obligations including the **suitability assessment**, other conduct of business requirements and providing periodic reports to clients and regulators."
> "**Where the client sets trading parameters, such as the sum they wish to invest or are prepared to lose, this will not affect the characterisation of the service as portfolio management.**"
> "**Exceptions:** Where **no automatic order execution occurs because client action is required before executing each transaction**, the activity performed will **not** amount to portfolio management. However, depending on the interaction with the client, **other investment services may still be relevant (eg investment advice with personal recommendations, and reception and transmission of orders)**."
> "The client may take investment decisions rather than the service provider… The trade signals are investment advice (or a general recommendation), and the **client must confirm each recommendation before any order is executed**…"

---

## 5. Is selling trading software (not advice) a regulated activity?

### 5.1 The RAO 2001 architecture
A regulated activity requires **a specified kind of activity**, **carried on by way of business**, **in relation to an investment of a specified kind** (FSMA s.22; RAO 2001, SI 2001/544). FSMA **s.19** prohibits an unauthorised person carrying on a regulated activity in the UK; contravention is a **criminal offence**.

⚠️ **The brief's "by way of business test in article 3" is imprecise.** **RAO article 3 is the interpretation provision** ("In this Order— 'the Act' means…"). The by-way-of-business provision is a **separate instrument: the Financial Services and Markets Act 2000 (Carrying on Regulated Activities by Way of Business) Order 2001, SI 2001/1177** (`https://www.legislation.gov.uk/uksi/2001/1177/contents`). Note SI 2001/1177 deals with specific activities (deposit-taking etc.) rather than a single general test; the general "by way of business" question is a matter of fact informed by FCA guidance (PERG 2.3–2.4, UNVERIFIED in detail here).

**Exact operative wording of the key articles (legislation.gov.uk XML, current to 2026-09-20):**

**Article 14 — Dealing in investments as principal** (UNVERIFIED verbatim — I fetched the file but did not quote it in this report; it specifies dealing as principal in securities/relevant investments etc. Read at `https://www.legislation.gov.uk/uksi/2001/544/article/14/data.xml`). Key point for prop firms: the **exclusions** (notably art. 15 "Absence of holding out", art. 16 "Dealing in own shares", and the "**own account / no holding out**" route) mean dealing as principal is only regulated in defined circumstances — but **the CFD/rolling-spot-forex business model generally does hold out**.

**Article 21 — Dealing in investments as agent**: dealing as agent is specified where the agent buys/sells etc. a security or relevant investment on behalf of a client.

**Article 25 — Arranging deals in investments** (quoted exactly):
> "**25(1)** Making arrangements for another person (whether as principal or agent) to buy, sell, subscribe for or underwrite a particular investment which is— (a) a security, (b) a relevant investment, … (c) an investment of the kind specified by article 86, or article 89 so far as relevant to that article, or (d) a structured deposit, is a specified kind of activity.
> **25(2)** Making arrangements with a view to a person who participates in the arrangements buying, selling, subscribing for or underwriting investments falling within paragraph (1)(a), (b), (c) or (d) (whether as principal or agent) is also a specified kind of activity.
> **25(3)** Paragraphs (1) and (2) do not apply to a kind of activity to which article 25D, 25DA or 25DB, applies."

**Article 37 — Managing investments**: managing assets belonging to another person, in circumstances involving the exercise of discretion, is a specified kind of activity where the assets consist of or comprise investments.

**Article 40 — Safeguarding and administering investments**: safeguarding and administering investments, or arranging for another to do so, is specified where done in the course of carrying on the activity in art. 37 or with a view to doing so.

**Article 53 — Advising on investments** (quoted exactly, **as currently in force**):
> "**53(1)** Advising a person is a specified kind of activity if the advice is— (a) given to the person in his capacity as an investor or potential investor, or in his capacity as agent for an investor or a potential investor; and (b) advice on the merits of his doing any of the following (whether as principal or agent)— (i) buying, selling, subscribing for, exchanging, redeeming, holding or underwriting a particular investment which is a security, structured deposit or a relevant investment, or (ii) exercising or not exercising any right conferred by such an investment to buy, sell, subscribe for, exchange or redeem such an investment.
> **(1A) Paragraph (1) does not apply to a person who is appropriately authorised except to the extent that they are providing a personal recommendation.**
> (1B) A person is appropriately authorised when they are authorised for the purposes of the Act to carry on an activity of a kind specified by a provision of this Order which is not the activity specified by paragraph (1)…
> **(1C) … a personal recommendation is a recommendation– (a) made to a person in their capacity as an investor or potential investor…; (b) which constitutes a recommendation to them to do any of the following… buy, sell, subscribe for, exchange, redeem, hold or underwrite a particular investment…; and (c) that is– (i) presented as suitable for the person to whom it is made; or (ii) based on a consideration of the circumstances of that person.**
> **(1D) A recommendation is not a personal recommendation if it is issued exclusively to the public.**
> (2) …[advising a lender under a relevant article 36H agreement — **P2P lending**]
> (3) Paragraph (2) does not apply in so far as— (a) the advice is given in relation to a relevant article 36H agreement which has been facilitated by the person giving the advice… (b) …article 39F (debt-collecting)… (c) …article 39G (debt administration)…"

### 5.2 ⚠️ MAJOR CORRECTION: article 53(2)/(3) is NOT the journalistic exclusion
**Article 53(2) and 53(3) as currently in force concern P2P lending agreements (article 36H) and debt activities — not newspapers or publications.** The brief's premise is wrong. The exclusions the brief is looking for are:

**(a) RAO article 54 — "Advice given in newspapers etc."** — this is the operative exclusion from **article 53**:
> "**54(1)** There is excluded from articles 53, 53A, 53B, 53C, 53D, 53DA and 53E **the giving of advice in writing or other legible form if the advice is contained in a newspaper, journal, magazine, or other periodical publication, or is given by way of a service comprising regularly updated news or information, if the principal purpose of the publication or service, taken as a whole and including any advertisements or other promotional material contained in it, is neither— (a) that of giving advice of a kind mentioned in article 53, 53A, 53B, 53C, 53D, 53DA or 53E, as the case may be; nor (b) that of leading or enabling persons— (i) to buy, sell, subscribe for or underwrite securities, structured deposits, or relevant investments, or… (ii) to enter as borrower into regulated mortgage contracts… (iii) …home reversion plans… (iv) …home purchase plans… (v) …sale and rent back agreements… (va) …regulated credit agreement the purpose of which is to acquire or retain property rights in land in the United Kingdom… (vi) …pension scheme [article 53E(1)(c)].
> **54(2)** There is also excluded from articles 53, 53A, 53B, 53C, 53D, 53DA and 53E **the giving of advice in any service consisting of the broadcast or transmission of television or radio programmes**, if the principal purpose of the service, taken as a whole and including any advertisements or other promotional material contained in it, is neither of those mentioned in paragraph (1)(a) and (b).
> **(2A) Paragraphs (1) and (2) do not apply to advice which is a personal recommendation falling within article 53(1A).**
> **(3) The FCA may, on the application of the proprietor of any such publication or service as is mentioned in paragraph (1) or (2), certify that it is of the nature described in that paragraph, and may revoke any such certificate if it considers that it is no longer justified.**
> **(4) A certificate given under paragraph (3) and not revoked is conclusive evidence of the matters certified.**"

URL: `https://www.legislation.gov.uk/uksi/2001/544/article/54` · FCA certification route: **PERG 7** ("Periodical publications, news services and broadcasts: applications for certification").

**(b) FPO 2005 article 20 — "Communications by journalists"** — this is the **financial-promotion-side "publisher exclusion"**. Note FPO 2001 (SI 2001/1335) was **revoked (1.7.2005) by FPO 2005 (SI 2005/1529)** — the brief's reference to FPO 2001 art. 20 is superseded:
> "**20(1)** Subject to paragraph (2), **the financial promotion restriction does not apply to any non-real time communication if— (a) the content of the communication is devised by a person acting in the capacity of a journalist; (b) the communication is contained in a qualifying publication; and (c) in the case of a communication requiring disclosure, one of the conditions in paragraph (2) is met.**
> (2) The conditions are that— (a) the communication is accompanied by an indication explaining the nature of the author's financial interest or that of a member of his family; (b) the authors are subject to proper systems and procedures which prevent the publication of communications requiring disclosure without the explanation referred to in sub-paragraph (a); or (c) the qualifying publication falls within the remit of— (i) the Code of Practice issued by the Press Complaints Commission; (ii) the OFCOM Broadcasting Code; or (iii) the Producers' Guidelines issued by the BBC.
> (3) … a communication requires disclosure if— (a) an author of the communication or a member of his family is likely to obtain a financial benefit or avoid a financial loss if people act in accordance with the invitation or inducement…; (b) the communication relates to a controlled investment of a kind falling within paragraph (4)…; and (c) the communication identifies directly a person who issues or provides the controlled investment…
> (4) A controlled investment falls within this paragraph if it is— (a) …paragraph 14 of Schedule 1 (shares or stock in share capital); (b) …paragraph 21 (options)…; (c) …paragraph 22 (futures)…; or (d) …paragraph 23 (contracts for differences etc.)…
> **(5) … 'qualifying publication' is a publication or service of the kind mentioned in paragraph (1) or (2) of article 54 of the Regulated Activities Order and which is of the nature described in that article**, and … a certificate given under paragraph (3) of article 54 of that Order and not revoked is conclusive evidence of the matters certified…"

URL: `https://www.legislation.gov.uk/uksi/2005/1529/article/20`

**So the UK does have a "publisher exclusion", in two layers:** RAO art. 54 (excludes *advising* from being a regulated activity) and FPO 2005 art. 20 (excludes a *non-real-time communication* from the s.21 financial promotion restriction). Both are narrow: they turn on the **principal purpose** of the publication/service as a whole, require the **journalist** capacity, and **art. 54(2A) disapplies the exclusion for a personal recommendation**. **FPO art. 20 does not cover real-time communications.**

### 5.3 FCA perimeter guidance on software — the decisive passages
**PERG 8.30.5G — software generating buy/sell signals (this is the single most important passage for the client):**
> "Some software services involve the **generation of specific buy, sell or hold signals relating to particular investments**. These signals are **liable, as a general rule, to be advice for the purposes of article 53(1) (as well as financial promotions) given by the person responsible for the provision of the software**. The exception to this is where the user of the software is required to use **enough control over the setting of parameters and inputting of information** for the signals to be regarded as having been generated by him rather than by the software itself."

**PERG 8.30.3G:** "The provider of the service will be giving advice for the purpose of article 53(1) **only if the service results in something more than a generic recommendation**, as with a paper version."

**PERG 8.30.1G:** "With the exception of periodicals, broadcasts and other news or information services (see PERG 8.31.2G), **the medium used to give advice should make no difference** to whether or not it is caught by article 53(1)." **PERG 8.30.2G(6):** advice can be provided "through the provision of an interactive software system."

**PERG 8.4.24G — "Investment trading methods and training courses"** (the "merely supplying software" question):
> "Trading methods and techniques, such as traded options training courses and **software-based or manual trading tools will, in many cases, be too remote from any eventual investment dealing activities to be inducements to engage in investment activity**. Promotions of such things will be inducements (or invitations) to receive training and general trading tips and techniques. **However, such things may be sold on the basis that they are almost certain to produce profits from the trading which the recipient will undertake using the training or technique. If this is the case, the promotions are capable of being inducements to engage in those trading activities.** Such financial promotions are capable of being **generic promotions under article 17 of the Financial Promotion Order**."

**PERG 8.31.2G — the art. 54 exclusion as the FCA applies it:**
> "With regard to article 53(1), **the main exclusion relates to advice given in periodical publications, regularly updated news and information services and broadcasts (article 54: Advice given in newspapers etc)**. The exclusion applies if the **principal purpose** of any of these is not to give advice covered in article 53(1) or to lead or enable persons to acquire or dispose of securities or contractually based investments. **This exclusion does not apply when the definition of advising on investments … is based on giving a personal recommendation.**"

**PERG 4.6.28AG** (mortgage analogue, art. 53A, but states the FCA's general approach to software-generated prompts): "Some software services involve the generation of specific prompts… These prompts are liable, as a general rule, to be **advice** for the purposes of article 53A **(as well as financial promotions) given by the person responsible for the provision of the software**. The exception … is where the user of the software is required to use enough control over the setting of parameters and inputting of information for the prompts to be regarded as having been generated by the customer rather than by the software itself."

### 5.4 Answer to the question posed
**Merely supplying software that a client uses to trade on their own account** — i.e. a tool the client configures and runs, executing in the client's own account, with no discretionary mandate and no personalised recommendation — **falls outside the RAO on the FCA's own perimeter guidance**, because:
- it is not "advising on investments" under art. 53(1): PERG 8.30.5G's exception applies where the user has "enough control over the setting of parameters and inputting of information"; and art. 53(1)(b) requires advice "on the merits" of a "particular investment", while PERG 8.30.3G excludes a merely "generic recommendation";
- it is not "managing investments" under art. 37 because the vendor does not manage assets belonging to another **with discretion** — the client retains control (contrast the **copy-trading** case in §4.5, where the FCA says portfolio management authorisation **is** required because there is "no manual input … from the account holder");
- it is not "arranging" under art. 25 where the vendor does not make arrangements for another person to buy/sell and is not a participant in the chain to the transaction; and
- it is not "dealing" under arts. 14/21 where the vendor never deals in the investment.

**But the perimeter moves sharply in four situations:**
1. **The software generates specific buy/sell/hold signals for particular investments → PERG 8.30.5G says these are "liable, as a general rule, to be advice for the purposes of article 53(1) (as well as financial promotions) given by the person responsible for the provision of the software."** This squarely covers a **signals** business. The exception requires the *user* to have enough control over parameters that the signals are treated as generated by the user.
2. **Automatic execution without client intervention → portfolio management** (FCA copy-trading page; art. 37).
3. **Marketing that the software is "almost certain to produce profits"** → PERG 8.4.24G: the promotion becomes "capable of being inducements to engage in those trading activities", i.e. a **financial promotion** caught by s.21 (generic promotions under FPO art. 17).
4. **Any invitation or inducement to engage in investment activity** — including a signal group on Discord/Telegram (FG24/1 ¶2.8) — is a financial promotion requiring authorisation or approval, **regardless of whether the underlying software supply is itself a regulated activity**. This is the most common trap: the software may be unregulated while the *marketing* is a criminal offence.

**Case law:** I found **no** UK case law directly on whether software vendors are "arranging" or "advising" under the RAO. **Mark UNVERIFIED / none found.** The perimeter here is governed by FCA guidance (PERG 8), not by reported authority.

---

## 6. Prop firms / funded trader programmes

### 6.1 FCA position — NO FORMAL FCA STATEMENT FOUND
**⚠️ Mark as UNVERIFIED / NONE FOUND.** I was unable to locate **any** FCA statement, warning, webpage, speech, consultation, policy statement or final notice specifically addressing "prop firms", "funded trader programmes", "prop firm challenges", or simulated funded accounts. Searches covered the FCA site (via Wayback, since direct access is Cloudflare-blocked) and general web search.

**Corroborating negative evidence:** a UK Parliament e-petition, **"Require FCA regulation of proprietary trading firms operating in the UK"** (petition 754761, published 26 January 2026, **closed 26 July 2026 with 24 signatures**), asserts that "Proprietary trading firms offering funded accounts operate widely in the UK **without FCA regulation**" and that such firms "operate without FCA oversight or consumer protections." It closed **far below the 10,000-signature threshold required to obtain a Government response**, so **no Government or FCA response exists**. URL: `https://petition.parliament.uk/petitions/754761`
This is consistent with the absence of any FCA statement — but it is **not** an FCA source, and it is not evidence that prop firms are lawful, only that the FCA has not issued a public position.

### 6.2 Regulatory analysis against the RAO
Because there is no FCA guidance on prop firms, the analysis must be built from the RAO itself. Applying the exact article text in §5.1:

**(a) The "challenge"/evaluation phase (simulated account).** The trader trades a demo account; no client money is at risk; the firm takes no position. On the face of it this is **not** a specified activity — there is no dealing (arts. 14/21), no arrangement for another person to buy/sell a real investment (art. 25), no management of another's assets (art. 37), and no advice on the merits of a particular investment (art. 53(1)) unless the firm is also making personalised recommendations. **However**, if the firm charges a fee and its marketing presents the challenge as a route to trading real CFDs/rolling spot forex, the *marketing* is a financial promotion issue independent of the underlying activity (PERG 8.4.24G; FG24/1).

**(b) The "funded" phase — the critical distinction.** Everything turns on **whether the "funded" account is genuinely funded with the firm's own capital, or is another simulated account with a profit-split calculated on notional P&L**:
- **If genuinely funded and the firm deals as principal** with the trader (taking the other side of the trader's CFD/rolling-spot-forex positions), the firm is **dealing in investments as principal (RAO art. 14)** and is very likely within the perimeter — the art. 15 "absence of holding out" exclusion is unavailable because the firm holds itself out as a counterparty. It would also need to consider **COBS 22.5** (retail CFD restrictions: leverage caps, 50% close-out, negative balance protection, risk warning, inducements ban) if the trader is a retail client.
- **If the "funded" account is simulated** and the firm pays a profit split on notional profits, the firm is arguably **not** dealing, arranging, managing or advising — but this structure raises a **separate** risk that the arrangement is a **collective investment scheme under FSMA s.235** (UNVERIFIED — I did not fetch s.235 in this research; it should be checked) or that the trader is being paid for an activity that, if performed on real markets for another person's account, would be regulated. The **payment of a profit split for trading a simulated account is not itself a specified activity** under the RAO on the text I have reviewed.
- **If the firm transmits the trader's orders to a broker**, it may be **arranging deals in investments (art. 25)** and/or **dealing as agent (art. 21)**, or providing **reception and transmission of orders** — note the FCA's copy-trading page expressly says that where automatic execution does not occur, "other investment services may still be relevant (eg investment advice with personal recommendations, and **reception and transmission of orders**)".

**(c) "By way of business".** The prop firm is carrying on the activity as a business (charging challenge fees, paying profit splits), so the "by way of business" limb (SI 2001/1177 / PERG 2) is readily satisfied and will not assist a prop firm seeking to argue it falls outside the RAO.

**(d) The industry's "we are a software/education company" defence.** The common prop-firm position is that it supplies software/education and a simulated environment, so it is not providing a financial service. **The FCA has not, to my knowledge, publicly challenged this position** (see §6.1). **UNVERIFIED** as to whether the FCA has privately challenged it or taken supervisory action. The strongest counter-arguments available to the FCA are (i) the marketing is a financial promotion irrespective of the software characterisation, and (ii) the "funded" phase, if genuinely funded, is dealing as principal.

**(e) Other regulators.** The brief asked for ESMA/EU or other national regulator statements on prop firms. **UNVERIFIED** — I did not identify a primary ESMA or national competent authority statement on retail prop firms within this research. (Search results referenced CFTC/other-jurisdiction commentary, which is secondary and not verified.)

---

## 7. Summary of corrections to the brief's assumptions

| # | Assumption in brief | Finding |
|---|---|---|
| 1 | COBS 4.5 = past performance | ❌ **COBS 4.5 = "Communicating with retail clients (non-MiFID provisions)"**. Past performance = **COBS 4.6.2R** |
| 2 | COBS 4.5.2R/4.5.6R past-performance rules | ❌ 4.5.2R = retail general rule; **4.5.6R = comparative information** |
| 3 | COBS 4.6.2R = "must not claim future performance guaranteed" | ❌ COBS 4.6.2R = **past performance**. Future performance = **COBS 4.6.7R**. "Guaranteed" language is **COBS 4.2.5G** |
| 4 | COBS 4.5A = performance information | ✅ **Correct** — "Communicating with clients (including past, simulated past and future performance) (MiFID provisions)" |
| 5 | COBS 4.5.6R required warning wording | ❌ Warning is **COBS 4.6.2R(4)** / **COBS 4.5A.10UK(d)**: "…past performance is not a reliable indicator of future results" |
| 6 | UK CFD warning uses "70% of accounts lose money" | ❌ **No fixed 70%.** COBS 22.5.6R(1A) uses `[insert percentage per provider]%`, recalculated **every 3 months over a 12-month period** |
| 7 | FCA leverage = ESMA's 30:1/20:1/10:1/5:1/2:1 | ❌ FCA = **30:1 / 20:1 / 10:1 / 5:1**; the 2:1 crypto tier is **deleted** (cryptoasset derivatives **prohibited**, COBS 22.6). FCA set **government bonds at 30:1 vs ESMA's 5:1** and covers **CFD-like options** |
| 8 | RAO art. 53(2)/(3) = journalistic exclusion | ❌ art. 53(2)/(3) = **P2P lending (art. 36H) / debt activities**. Journalistic exclusion = **RAO art. 54**; publisher exclusion for promotions = **FPO 2005 art. 20** |
| 9 | FPO = SI 2001/544-era FPO 2001 | ❌ FPO 2001 (SI 2001/1335) was **revoked 1.7.2005** by **FPO 2005 (SI 2005/1529)** |
| 10 | s.21 gateway SI = **2023/1217** | ❌ **SI 2023/1217 = Persistent Organic Pollutants**. Gateway = **SI 2023/1411** + exemptions **SI 2023/966**; statutory basis **FSMA ss.55NA/55NB** (inserted by FSMA 2023 s.20(3), in force **7 Feb 2024**) |
| 11 | "by way of business test in article 3" | ❌ RAO art. 3 = **interpretation**. By-way-of-business = **SI 2001/1177** |
| 12 | FCA has warned about prop firms | ❌ **No FCA statement found.** Petition 754761 closed with 24 signatures → **no Government/FCA response** |

---

## 8. Source URLs (all primary unless marked)

**FCA Handbook (retrieve via `https://web.archive.org/web/<YYYY>id_/` prefix — direct access is 403):**
- COBS 4: `https://www.handbook.fca.org.uk/handbook/COBS/4.pdf` · COBS 22: `.../COBS/22.pdf` · PRIN 2A: `.../PRIN/2A.pdf` · PERG 2: `.../PERG/2.pdf` · PERG 4: `.../PERG/4.pdf` · PERG 8: `.../PERG/8.pdf`
- FCA Handbook HTML (403 direct): `https://www.handbook.fca.org.uk/handbook/COBS/4/5A.html`

**FCA publications (403 direct; use Wayback):**
- FG24/1: `https://www.fca.org.uk/publication/finalised-guidance/fg24-1.pdf` · landing: `https://www.fca.org.uk/publications/finalised-guidance/fg24-1-finalised-guidance-financial-promotions-social-media`
- PS19/18: `https://www.fca.org.uk/publication/policy/ps19-18.pdf`
- FG22/5: `https://www.fca.org.uk/publication/finalised-guidance/fg22-5.pdf`
- Approving financial promotions: `https://www.fca.org.uk/firms/financial-promotions-and-adverts/approving-financial-promotions`
- Copy trading: `https://www.fca.org.uk/firms/copy-trading`
- Finfluencer prosecutions: `https://www.fca.org.uk/news/press-releases/first-court-appearance-three-finfluencers-charged-fca-led-global-crackdown-illegal-promotions`

**legislation.gov.uk (directly accessible; use `/data.xml` or `/data.xht?view=snippet&wrap=true` for full text):**
- FSMA 2000 s.19: `https://www.legislation.gov.uk/ukpga/2000/8/section/19` · s.21: `.../section/21` · s.55NA: `.../section/55NA` · s.55NB: `.../section/55NB` · s.138D: `.../section/138D`
- RAO 2001 (SI 2001/544): contents `https://www.legislation.gov.uk/uksi/2001/544/contents`; arts. 3, 14, 21, 25, 37, 40, 53, **54**: `.../uksi/2001/544/article/<N>`
- FPO 2005 (SI 2005/1529) art. 20: `https://www.legislation.gov.uk/uksi/2005/1529/article/20`
- By Way of Business Order (SI 2001/1177): `https://www.legislation.gov.uk/uksi/2001/1177/contents`
- SI 2023/1411: `https://www.legislation.gov.uk/uksi/2023/1411/contents` · SI 2023/966: `.../uksi/2023/966/contents` · SI 2023/612: `.../uksi/2023/612/contents` · SI 2024/301: `.../uksi/2024/301/contents`
- Petition 754761: `https://petition.parliament.uk/petitions/754761`

**Local evidence files** (extracted text, in `D:\RoundTrip\sources\`): `cobs4.utf8.txt`, `cobs22.utf8.txt`, `prin2a.txt`, `perg8.txt`, `perg4.txt`, `fg24_1.txt`, `ps19_18.txt`, `fg22_5.txt`, `leg_rao_art53.clean.txt`, `leg_rao_art25.clean.txt`, `leg_fsma_s21.clean.txt`, `fsma_s55NA.txt`, `fsma_s55NB.txt`, `fpo2005_art20.clean.txt`, `rao_whole.clean.txt`.
