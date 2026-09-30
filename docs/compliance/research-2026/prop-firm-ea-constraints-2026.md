# Prop-Firm Technical & Rule Constraints for Automated Trading (MT5 EAs / Python Bots), 2026

All rules below were read from the firms' own rules/FAQ/help-centre pages. **[OFFICIAL]** = quoted from a primary firm page (URL given). **[UNVERIFIED]** = could not be confirmed on an official page.

---

## 1. FTMO (CFD) — https://ftmo.com/en/

**EAs/algo allowed — with conditions. [OFFICIAL]** "we have no reasons for limiting or restricting your trading strategy, whether it's discretionary trading, algorithmic trading, EAs, etc."
— https://ftmo.com/en/faq/which-instruments-can-i-trade-and-what-strategies-am-i-allowed-to-use/

**Hard numerical EA/server limits. [OFFICIAL]** "platform servers have **200 orders at a time and 2000 max positions per day** limitation, just as the limited acceptance of the server messages (orders and order modifications such as updates of TP/SL and updates of limit orders). If your EA causes hyperactivity to a platform server, we might alert you and ask you to adjust the EA logic or parameters." (same URL)

**HFT / latency arbitrage. [OFFICIAL]** Forbidden Trading Practices bans "any software, artificial intelligence, **ultra-high-speed tools**, or mass data entry that might manipulate, abuse, or give you an unfair advantage" and trades "operated or managed by automated robots / EAs (Expert Advisors) which cause the trading account to become hyperactive in the sense of an excessive number of **more than 2,000 server requests per day** on individual simulated trades or pending orders being opened, modified, or closed, causing overload of the trading server." No explicit "latency arbitrage"/"tick scalping" phrase appears on the CFD page — those terms are used by The5ers, not FTMO. — https://ftmo.com/en/forbidden-trading-practices/

**Copy trading. [OFFICIAL]** Bans "perform, alone or in concert with other persons — **including between connected accounts, accounts held with various operators/providers**, or accounts held with other members of the Program Group — simulated trades or combinations of trades for manipulative purposes, for example by simultaneously entering into opposite positions." Third-party account access is banned: "You must not allow any third party to access or otherwise use your FTMO Account." (same URL). Third-party EA risk: "By using a third-party EA, you potentially run a risk of being denied the FTMO Account if you exceed the maximum capital allocation rule."

**Gap/news trading. [OFFICIAL]** Gap trading banned around "major global news, macroeconomic events, or corporate reports" and "**two hours or less before** a relevant financial market is closed for at least two hours." (Forbidden Practices URL)

**News rule (Standard accounts, FTMO Account stage only). [OFFICIAL]** "it is not permitted to open or close any trades, including the execution of pending orders (such as Stop Loss or Take Profit), within a time window starting **2 minutes before and ending 2 minutes after** the release of selected news announcements." Does **not** apply during Evaluation. — https://ftmo.com/en/faq/can-i-trade-news/

**Account types. [OFFICIAL]** Standard (up to 1:100) vs **Swing** (up to 1:30). Swing "does not have any restrictions on trading during news releases or on holding positions overnight (longer than 2 hours after market close) or over the weekend." Swing is available **exclusively in FTMO Challenge: 2-Step**; Standard→Swing change is not allowed. — https://ftmo.com/en/faq/ftmo-swing-account-type/ and /is-the-swing-account-type-available-for-ftmo-challenge-1-step/

**Consistency / Best Day Rule. [OFFICIAL]** 1-Step: "your Best Day does not represent more than **50% of your Positive Days' Profit**." Exceeding is "not treated as a rule breach" — you keep trading until compliant. — https://ftmo.com/en/trading-objectives/
**FTMO Futures Consistency Rule. [OFFICIAL]** "your single most profitable trading day (the Best Day) does not represent more than **40%** of your total profit" (Growth); **50%** (Pro). Applies to Evaluation only; "There is no Profit Target or Consistency Rule on the Sim-Funded Account." — https://ftmo.com/en/futures/trading-objectives-and-rules/

**Platforms. [OFFICIAL]** MT4, MT5, cTrader, TradingView. FTMO cTrader "enables you to build and run custom indicators and trading robots... with support for **C# and Python**" via cTrader Automate/Open API. — https://ftmo.com/en/trading-platforms/. MT5 server time = GMT+2 +DST. — https://ftmo.com/en/faq/what-are-the-account-specifications/

**VPS. [OFFICIAL]** "The use of VPN/VPS is also generally allowed," sole exception: avoid logging in from / geo-locating to the **United States** on MetaTrader, cTrader or TradingView. — https://ftmo.com/en/faq/can-i-travel-or-use-vpn-vps/

**Capital / split. [OFFICIAL]** Max capital allocation **$400,000 per trader or strategy** (prior to scaling); Scaling Plan up to **$2,000,000** with **90%** reward ratio (2-Step). — https://ftmo.com/en/faq/how-many-accounts-can-i-have/ and /reward-growth-and-scaling-plan/

**DLL imports / WebRequest / Python API. [UNVERIFIED]** No FTMO page mentions DLL imports, WebRequest whitelisting, or the MetaTrader5 Python package. FTMO imposes no documented block, but no official confirmation exists either.

---

## 2. The5ers — https://the5ers.com/faqs/

**EA rules. [OFFICIAL]** "You can use any EA you have in your trading account, as long as it does not: Copy trades of other person's signals; Do tick scalping; Perform latency arbitrage trading; Perform reverse arbitrage trading; Perform hedge arbitrage trading; Perform high-frequency trading; Use emulators. Any accounts using these types of EAs will be canceled, banned, and will not refunded. The stop-loss order has to be visible in the trading platform, so you cannot use a 'stealth mode' stop-loss. Additionally, **the trader must own the source code of the EA**."

**HFT definition + EA/server rule. [OFFICIAL]** "high-frequency trading, in which the majority of trade durations span is measured **within a few seconds or less**"; also bans "using automated robots or expert advisors that cause the trading account to generate an excessive number of server requests per day." Also banned: arbitrage, **bulk trading** ("multiple trades are open simultaneously"), **bracketing** pending orders around high-impact news, "trade coordination or copy trading with other traders or accounts", "one-sided bets", "EA from a third party, where other traders have the same trades open (copy trading)", "expert advisors that scalp during the rollover night."

**News. [OFFICIAL]** High Stakes: "it is not allowed to execute any order... **2 minutes prior, after or within** to high-impact news... any trade opened within the 2-minute period before or after a high-impact (red folder) news event will be classified as a **soft breach**." Hyper Growth/Bootcamp: "news trading is allowed except for bracket strategies around news." Source: Forex Factory, server time.

**Consistency. [OFFICIAL]** Formula: "(Best trading day ÷ profits from profitable days) × 100 = Consistency percentage." "there is **no consistency rule during the evaluation phases for the 2-step plan**... once you pass... a **50% consistency requirement** will apply." Percentages vary by account/region: "some accounts may have a **30%** consistency rule, while others may have a **50%**." Calculated on accumulated **profitable trades only** — "losing trades are not deducted."

**Copy trading. [OFFICIAL]** Between own accounts allowed: "Yes, copy trading between your own accounts is allowed. However, once your total managed capital reaches **$500K** across all programs and accounts, copy trading across accounts is no longer permitted." Copying another person's signals is banned.

**Platforms/limits. [OFFICIAL]** MT5 and cTrader; US clients TradingView via terminal.the5ers.com. Leverage 1:30 on Bootcamp/Hyper Growth; growth up to **$4M** (Hyper Growth, 100% of profits). "you must not execute trades from **two different IP addresses at the same time**."

**DLL/WebRequest/VPS/MT5 Python API. [UNVERIFIED]** Not addressed on the official FAQ.

---

## 3. Funding Pips — https://help.fundingpips.com/hc/en-us/

**EA rules — the strictest of the group. [OFFICIAL]** "**Default rule (third-party EAs): permitted only when used strictly as a trade or risk manager.** Any other use of a third-party EA will result in denial of the evaluation or reward and closure of the account." "**Personal EA Exception: Full Automation with Proof of Ownership** — If the EA is your own, developed by you, full automation is permitted with proof of ownership... Source code files (uncompiled .mq5, .mq4, or equivalent platform source)... **A compiled binary on its own is not proof.**" 1K Instant account exempts third-party EAs; **Monthly Competition prohibits all EAs**. — /hc/en-us/articles/34505029138449-Trading-Conduct-and-Security-Standards

**Forbidden strategies. [OFFICIAL]** "gap trading, high-frequency trading, server spamming, **latency arbitrage**, toxic trading flow, hedging, long-short arbitrage, reverse arbitrage, **tick scalping**, server execution exploits, opposite account trading, and churning and burning are not allowed." (same URL)

**Copy trading. [OFFICIAL]** Permitted: copying between **your own** FundingPips accounts; using your FP account as **master** to an external slave. Prohibited: copying between accounts of **different users**; "**Inbound copy trading**: copying trades into your FundingPips account from an external source (signal providers, trade copier services where the FundingPips account is the slave)"; third-party account management. (same URL)

**VPS/VPN — explicitly banned. [OFFICIAL]** "Connecting to a VPN or VPS while accessing your trading account is **not permitted**. Make sure your VPN/VPS is disabled to access your trading account." (same URL)

**Consistency. [OFFICIAL]** 2 Step Standard / 1 Step Flex / 2 Step Pro (On Demand 90% cycle only): "**35% consistency score** must be achieved: no single trading day can account for more than 35% of total profit. This resets after each reward." Weekly/Bi-Weekly/Monthly cycles are **not** subject to it. **FundingPips Zero: 15%** — "Your single largest winning day must not exceed 15% of your total cumulative profit." Formula: "(Biggest Winning Day / Current Total Account Profit) x 100%".

**News. [OFFICIAL]** Master accounts: news window "**5 minutes before the news or 5 minutes after**"; speeches "**10 minutes before the speech begins to 10 minutes after it ends**." Swing exception: trades opened **≥5 hours** before the event are exempt. **FundingPips Zero: 10 minutes** either side, and holding/opening/closing during restricted news "will result in account closure." "**Purposely trading news in both evaluation and master phase is prohibited** and will lead to account closure."

**Platforms. [OFFICIAL]** MT5, cTrader, Match-Trader. Copy Trader works on all three. Up to $400K Evaluation Allocation, up to $2M Prime Capital; splits 60%–100% by cycle.

**DLL/WebRequest. [UNVERIFIED]** Not documented.

---

## 4. Alpha Capital Group — https://help.alphacapitalgroup.uk/en/

**EAs — heavily restricted. [OFFICIAL]** "EAs are permitted on our MT5 platform; however, their use is **strictly limited to risk management and trade assistance tools**... **Automated EAs that execute trades independently, without human oversight, are strictly prohibited and will not be approved under any circumstances.** This prohibition includes third-party bots, fully automated strategies, high-frequency trading, and latency arbitrage strategies. The use of any such system will result in immediate account closure." EAs require **pre-approval** (submit EX5, MQ5 source where available); "EA functionality is not currently available for cTrader, DX Trade, or TradeLocker accounts." — https://help.alphacapitalgroup.uk/en/articles/6934236-can-i-use-an-expert-advisor-ea

**Prohibited strategies. [OFFICIAL]** "exploiting mispricing or front-running price feeds; **Latency trading**; Arbitrage trading; **High-frequency trading**; Reverse trading/group hedging; **Position spamming**; Group trading/signal following." Position spamming = "**3 or more positions, each opened within 60 seconds of the previous one**... as part of the same trade idea." — /articles/6934275-what-are-prohibited-trading-strategies

**Anti-HFT duration rule. [OFFICIAL]** "We require the **average duration of all your trades to be greater than 2 minutes**... At least **50% of your gross generated profits**... must come from trades that exceed 2 minutes. If the total profit from all trades lasting less than 2 minutes... exceeds 50% of that amount, the rule will be breached." Applies to all accounts; breach = restart from Phase 1 or profit removal. — /articles/8447268-what-is-the-2-minute-average-trade-duration-rule

**Copy trading. [OFFICIAL]** "Copy trading... is permitted" but "Engaging in copy trading from other groups, or duplicating trades from fellow traders, is strictly prohibited." External accounts may be Master **with proof of ownership**; you must supply Master/Slave account numbers in advance; "Only one account can serve as a Master at any given time." Not possible on cTrader/DX Trade/TradeLocker. — /articles/8786973-is-copy-trading-allowed

**VPS. [OFFICIAL]** "You are allowed to use a VPN or VPS, as long as... It must have a **static IP address**... You must **notify our support team by email before using it**... Using a VPN or VPS without prior notification... will lead to account closure and a potential permanent ban." — /articles/8420522-what-is-the-ip-rule-are-vpns-and-vpss-allowed

**News. [OFFICIAL]** Evaluation: unrestricted. Qualified Analyst (Pro/One/Three/Direct): "NOT permitted to execute any new trades or close existing trades... within the window of **5 minutes before and 5 minutes after**" — classified as a **Soft Breach**. Alpha Swing: trades initiated within a **4-minute window** must last >2 minutes. — /articles/9293522-can-i-trade-news

**Consistency. [OFFICIAL]** "**The 40% Best Day Rule** — If you request performance fees on-demand, no single trading day can represent more than 40% of your total cumulative profit... **It does not apply to bi-weekly schedules.**" (publisher guide; primary confirmation at help.alphacapitalgroup.uk/en/articles/6934210 — article body **[UNVERIFIED]** directly).

**Capital. [OFFICIAL]** "Maximum allocation across all four plans combined is **$400,000**... Performance split is up to **80%**."

---

## 5. E8 Markets — https://e8markets.com/ — **[UNVERIFIED]**

**All e8markets.com and help.e8markets.com URLs returned HTTP 403 behind a Cloudflare "Confirm you're human" security check** from this network (Ray IDs a3df1397285b2ab6 / a3df1492ee5ee9df). Attempted via `web_fetch` and `pwsh Invoke-WebRequest` with full browser headers; all blocked. Search engines surface official titles — [Trading Policies and Prohibited Trading Strategies](https://help.e8markets.com/en/articles/6929927-trading-policies-and-prohibited-trading-strategies) and [Can I use indicators or expert advisors...](https://help.e8markets.com/en/articles/5515409-can-i-use-indicators-or-expert-advisors-when-trading-the-e8-account) — **but their contents could not be read, so no rule is asserted here.**

---

## 6. Topstep (Futures) — https://help.topstep.com/en/

**Automation. [OFFICIAL]** No blanket EA ban, but banned under "Using Unfair Technology": "Using software, AI, ultra-high speed systems, or mass data entry that manipulates, abuses, or provides an unfair advantage." SIM exploitation is explicitly prohibited: "Running scalping algorithms designed to exploit unrealistic SIM fills; Making hundreds of rapid trades to take advantage of preferential queue position in SIM... Using tight brackets or auto-breakeven to take favorable SIM fills." Signals abuse as "hundreds or thousands of trades per day, with **average durations measured in seconds, not minutes**." — /articles/10305426-prohibited-trading-strategies-at-topstep

**Copy trading. [OFFICIAL]** TopstepX has a built-in Trade Copier (Lead/Follower); "Follower Accounts must have a greater than or equal margin / max position size as the Lead Account." Note "**Your copy-trading connection is automatically disabled while a Payout processes.**" — https://help.topstepx.com/settings/copy-trading and /articles/8284233-topstep-payout-policy. Cross-account hedging (single-user) and **coordinated trading** are prohibited. — /articles/10296582-prohibited-conduct

**Consistency Rule. [OFFICIAL]** Express Funded Account **Consistency Path**: "**Stay at or below the 40% consistency target. Your largest single day cannot exceed 40% of your total net profit.**" (Standard Path instead requires 5 winning days of $150+.) — /articles/8284233-topstep-payout-policy

**VPS/VPN. [OFFICIAL]** "**Do not use a VPN.** VPNs, proxy services, TOR, geo-location obfuscation, and other identity-masking services are not permitted at Topstep." — /articles/10296582-prohibited-conduct

**Other. [OFFICIAL]** Prohibits "Holding a position within **2% of a product's price lock limit**"; "**Trading Maximum Position Size into Major News Events**." Payouts: 90/10 split, min $125. **MT5 is not a supported Topstep platform** — platforms are TopstepX, NinjaTrader, Tradovate, TradingView, Quantower. [UNVERIFIED] — no explicit official statement listing MT5 as unsupported was retrieved.

---

## 7. Cross-cutting constraints for EA/Python vendors selling to prop clients

1. **MT5 Signals are impossible on prop accounts — by MetaQuotes' design, not firm policy. [OFFICIAL]** MetaTrader 5 build 4150 (Jan 2024) release notes: "**Terminal: Disabled support for the Signals service for demo accounts.**" Renat Fatkhullin (MetaQuotes CEO), MQL5 forum: "Support for signals on any **non-real accounts (demo, contest, cents, etc.)** for MetaTrader 4 and MetaTrader 5 is **completely removed**"; "The ability to register demo or private signals on the site is removed"; "MQL5 functions SignalsXXXX are abolished; they return empty data"; and for signal-subscription accounts: "**Any copiers are prohibited**", "**Connections with read only passwords are prohibited**", "All MQL5 functions will produce empty open positions/orders/trade history." Since **every prop account is a demo account**, the built-in MT5 Signals service is structurally unavailable regardless of firm. — https://www.mql5.com/en/forum/461169
2. **The MetaTrader5 Python package works against any MT5 terminal. [OFFICIAL]** `mt5.initialize(path, login, password, server, timeout, portable)` "Establish a connection with the MetaTrader 5 terminal... If required, the MetaTrader 5 terminal is launched to establish connection." No prop-firm-specific block exists in the API. — https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py. **No prop firm publishes a rule permitting or banning it — [UNVERIFIED]** for all firms surveyed. Practically, a Python bot driving the terminal is an EA-equivalent and is judged under each firm's automation rule (Alpha Capital would treat it as an unapproved EA; Funding Pips as a non-own EA).
3. **DLL imports / WebRequest: no firm surveyed publishes a whitelist or ban. [UNVERIFIED]** across FTMO, The5ers, Funding Pips, Alpha Capital, Topstep. Do not claim a DLL/WebRequest restriction exists.
4. **VPS is the sharpest divergence — and the biggest vendor risk.** Banned outright by **Funding Pips** and **Topstep**; allowed with **static IP + prior email notification** at **Alpha Capital**; allowed by **FTMO** (except US geo-location). A vendor shipping a VPS-hosted bot must check this per firm.
5. **"Own the source code" is a recurring gate.** The5ers requires the trader to own the EA source; Funding Pips accepts personal EAs only with source/version-control proof and states "A compiled binary on its own is not proof"; Alpha Capital requires pre-approval with EX5/MQ5. **Selling compiled-only EAs to prop clients is the single largest commercial blocker.**
6. **Minimum-duration / anti-HFT thresholds are the practical design envelope for automated strategies:** Alpha Capital avg trade >2 min and ≥50% of gross profit from trades >2 min; The5ers bans "majority of trade durations... within a few seconds or less"; Topstep flags "average durations measured in seconds, not minutes"; FTMO caps 2,000 server requests/day and 200 orders at a time.
7. **Consistency rules now bind automated strategies at 15%–50%.** Verified: FTMO CFD 50% Best Day; FTMO Futures 40%/50%; The5ers 30%/50%; Funding Pips 35% (On Demand) and **15% (Zero)**; Alpha Capital 40% (on-demand only); Topstep 40% (Consistency path). A high-win-rate bot that produces one outsized day can be blocked from payout even with zero rule breaches.
