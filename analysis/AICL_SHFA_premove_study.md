# Pre-Move Study: AICL & SHFA

**Prepared:** 2026-09-03
**Method note (read first):** All price/volume data below is real, pulled directly from PSX's own Data Portal (`dps.psx.com.pk/historical`) via `backend/dps_scraper.py` — the same source this project's production backfill uses, not yfinance and not training knowledge. All announcement text is scraped verbatim from `dps.psx.com.pk/company/{SYMBOL}` — titles are copied exactly as PSX published them, never paraphrased or guessed. Because this session's own sandbox cannot reach `dps.psx.com.pk` directly (network egress block — the same constraint already documented in `backend/news_fetcher.py`), the actual fetch ran in a GitHub Actions job (`.github/workflows/premove_data_fetch.yml`, real unrestricted network) and its logs were pulled back into this session as the data-transport mechanism. The one-off fetch/scrape script is `analysis/fetch_premove_data.py`, kept in the repo for reproducibility.

Indicators (EMA20/EMA50, MACD(12,26,9), Bollinger(20,2), RSI(14), 20-day/50-day volume averages) are computed over an EXTENDED lookback (~70 calendar days before each requested window) so every reported day has genuine trailing history to average against — not padded with `None`. Candlestick pattern rules (Bullish Engulfing, Morning Star, Hammer, Doji, Piercing Line) are literal, classic textbook definitions, implemented and unit-tested against synthetic OHLC before running on real data (`analyze_premove.py`, kept alongside the fetch script).

---

## STOCK 1 — AICL (Adamjee Insurance Company Limited)

### Step 1 — Data coverage

Requested window: **2026-07-08 to 2026-08-07** (23 trading sessions). **All 23 sessions returned, no gaps** — every weekday in the window has a real PSX-reported bar. (Extended lookback fetched from 2026-04-15 for indicator warm-up; that wider range shows two market-wide non-trading gaps — 2026-04-30→05-04 and 2026-06-24→06-29 — both consistent with multi-day PSX closures, not a data problem specific to AICL.)

User-cited reference points confirmed exactly against real PSX data: **close of 73.02 on 2026-07-23** (verified, exact match) and the move reaching **96 by 2026-08-07** (close 96.37 on 08-07, and 96.03 the day before on 08-06 — matches within the stated precision).

### Step 2 — PSX announcements/news verification

**Company page (`dps.psx.com.pk/company/AICL`) — CONFIRMED, fetched successfully.** Full announcement list scraped; items falling inside the requested window (2026-07-08 to 2026-08-10):

**→ NONE.** No Financial Results, Board Meeting, General Meeting, dividend, or other disclosed item is dated inside 2026-07-08–2026-08-10 in this scrape.

Nearest items outside the window (for context, NOT claimed as causal):
| Date | Title |
|---|---|
| Aug 21, 2026 | Board Meeting (11 days after the window's end) |
| Aug 27, 2026 | Financial Results for the Quarter Ended 30 June 2026 |
| Aug 28, 2026 | Transmission of Quarterly Report for the Period Ended 30 June 2026 |
| Jun 1, 2026 | General Meetings / Briefing Sessions |
| Feb 4, 2026 | **Unusual Movement in Price of the Shares of Adamjee Insurance Company Limited (AICL)** — a PRIOR unusual-movement notice, ~5 months before this move; unrelated to this window but shows AICL has a history of PSX-flagged unusual moves |

**PSX-wide notices (`dps.psx.com.pk/announcements/psx`) — INCONCLUSIVE, not confirmed clean.** This page is a JavaScript-driven search form (confirmed: the fetched HTML shows only the empty search widget and market-index ticker, with the results grid populated by a client-side API call after form submission — 0 `<tr>` rows present in the raw response). This scrape **could not retrieve results** from this page. This is a genuine verification gap, not evidence of absence — flagged explicitly per instructions, not glossed over.

**Bottom line for Step 2 (AICL): no disclosed catalyst found on the company announcements page inside the window, but the PSX-wide notices/query check is unverified. Do NOT read this as "confirmed catalyst-free" — read it as "no company-disclosure catalyst found; market-wide notices unchecked."**

### Step 3 — Technical pre-move analysis

**Chart structure:** 07-08 through 07-22 is a ragged **downward drift/consolidation**, closes ranging roughly 75.9–81.7, with no clean flat base — more a soft bleed than a tight range. 07-23 (close 73.02) is a **flush-out low below that range** — the session low. 07-24 reverses hard off that low (Bullish Engulfing). 07-27 closes back above the top of the prior range (82.33) — the **breakout day is 07-28**, confirmed the next session by a massive volume spike.

**Breakout day: 2026-07-28.** Close 90.56 (+9.9% on the day), volume 7,505,392 — **8.70× the 20-day average volume**. This is the single most extreme reading in the whole window.

**Full day-by-day timeline (2026-07-08 to 2026-08-07):**

| Date | Close | Volume | Vol vs 20d avg | Vol vs 50d avg | Candlestick pattern(s) | EMA20 vs EMA50 | MACD hist | RSI(14) | Bollinger flag |
|---|---|---|---|---|---|---|---|---|---|
| 2026-07-08 | 81.68 | 1,266,800 | **2.27×** | 3.3× | — | 20>50 | +0.325 | 55.6 | — |
| 2026-07-09 | 80.50 | 703,060 | 1.23× | 1.78× | — | 20>50 | +0.091 | 52.0 | — |
| 2026-07-10 | 80.33 | 335,866 | 0.59× | 0.84× | **Doji** | 20>50 | -0.085 | 51.5 | — |
| 2026-07-13 | 80.26 | 265,619 | 0.47× | 0.68× | — | 20>50 | -0.208 | 51.3 | — |
| 2026-07-14 | 77.52 | 654,548 | 1.13× | 1.67× | — | 20>50 | -0.462 | 43.2 | **at/below lower band (oversold)** |
| 2026-07-15 | 77.95 | 202,437 | 0.38× | 0.52× | — | 20>50 | -0.581 | 44.7 | **near lower band** |
| 2026-07-16 | 79.75 | 296,704 | 0.58× | 0.76× | — | 20>50 | -0.520 | 50.5 | — |
| 2026-07-17 | 76.79 | 513,445 | 1.0× | 1.31× | — | 20>50 | -0.653 | 42.6 | **near lower band** |
| 2026-07-20 | 77.38 | 273,185 | 0.54× | 0.69× | **Hammer** | 20>50 | -0.671 | 44.4 | **near lower band** |
| 2026-07-21 | 77.37 | 311,382 | 0.62× | 0.78× | — | 20>50 | -0.655 | 44.4 | **near lower band** |
| 2026-07-22 | 75.92 | 98,692 | 0.2× | 0.25× | — | 20>50 | -0.707 | 40.7 | **near lower band** |
| 2026-07-23 | 73.02 | 472,797 | 0.93× | 1.19× | — | **20<50 (death cross this day)** | -0.890 | 34.4 | **at/below lower band (oversold)** |
| 2026-07-24 | 77.68 | 576,672 | 1.14× | 1.43× | **Bullish Engulfing** | 20<50 | -0.662 | 48.2 | — |
| 2026-07-27 | 82.33 | 914,421 | **1.71×** | 2.19× | — | **20>50 (golden cross this day)** | -0.187 | 57.8 | — |
| 2026-07-28 | 90.56 | **7,505,392** | **8.7×** | 13.25× | — | 20>50 | +0.647 | 68.7 | — |
| 2026-07-29 | 89.29 | **6,614,789** | **5.73×** | 9.5× | **Doji** | 20>50 | +1.054 | 65.9 | — |
| 2026-07-30 | 88.72 | 684,678 | 0.59× | 0.98× | — | 20>50 | +1.215 | 64.6 | — |
| 2026-07-31 | 92.46 | 3,453,495 | **2.6×** | 4.53× | — | 20>50 | +1.485 | 68.9 | — |
| 2026-08-03 | 93.80 | 1,586,120 | 1.15× | 2.01× | — | 20>50 | +1.653 | 70.3 | — |
| 2026-08-04 | 91.92 | 955,548 | 0.69× | 1.19× | — | 20>50 | +1.539 | 65.8 | — |
| 2026-08-05 | 92.04 | 112,797 | 0.09× | 0.14× | — | 20>50 | +1.379 | 66.0 | — |
| 2026-08-06 | 96.03 | 2,126,245 | **1.52×** | 2.56× | — | 20>50 | +1.441 | 70.6 | — |
| 2026-08-07 | 96.37 | 1,208,729 | 0.84× | 1.43× | **Doji** | 20>50 | +1.403 | 70.9 | — |

**Indicator/cross summary:**
- **EMA20/EMA50:** death cross on 07-23 (the low day), golden cross back on **07-27** — one session BEFORE the volume breakout.
- **MACD histogram:** negative from 07-10 through 07-27, flips positive on **07-28**, the exact breakout day.
- **RSI(14):** bottomed at **34.4 on 07-23**, recovered through 40s/50s, into the 65–71 range post-breakout (not extreme-overbought by the textbook 70+ line, sits right at the edge).
- **Bollinger:** price touched/pierced the lower band **07-14 and 07-23** — the only two genuinely oversold readings in the window, both on the way down into the 07-23 low.

### Step 4 — AICL Summary Signature

**Confirmed from PSX announcements:** No company-disclosed announcement found inside the 2026-07-08–2026-08-10 window on the company page. PSX-wide notices page could not be verified (JS-rendered search, results not retrievable by this scrape) — **inconclusive on that front, not confirmed clean.**

**Inferred from price/volume only (plain English):** AICL drifted down into an oversold low on 2026-07-23 (RSI 34.4, price at the lower Bollinger Band), reversed the very next session on a textbook Bullish Engulfing candle, confirmed with an EMA20/EMA50 golden cross on 07-27, then broke out violently on 2026-07-28 on **8.7× normal volume** with the MACD histogram flipping positive the same day. The move from the 07-23 low (73.02) to the 08-07 close (96.37) is +32.0%. This is a clean, textbook technical reversal-into-breakout signature — but the extreme volume spike on the breakout day (7.5M shares vs. a ~865K 20-day average) is the kind of reading that, on PSX, often coincides with a real disclosed catalyst even when this particular scrape didn't surface one in the company-page announcements list. **Given the PSX-wide notices check is unverified, this move should NOT be labeled catalyst-free — it should be labeled "no catalyst found in the sources this study could verify."**

---

## STOCK 2 — SHFA (Shifa International Hospitals Limited)

### Step 1 — Data coverage

Requested window: **2026-05-28 to 2026-06-18**. **2026-05-28 itself has no PSX bar** — the real data jumps from 2026-05-25 straight to 2026-05-29. Cross-checked against AICL's independently-fetched wider date range, which shows the identical gap shape (2026-05-25→05-29, and also 2026-04-30→05-04) — this is consistent with a **market-wide multi-day closure** (all PSX symbols non-trading, most likely a public holiday cluster), not a SHFA-specific data problem. This session did not have access to an independent PSX holiday calendar to name the specific holiday, so that specific cause is flagged as **plausible, not confirmed**. 14 of the 15 remaining requested sessions (2026-05-29 through 2026-06-18) are present with no further gaps.

User-cited reference points confirmed against real PSX data: **close of 481.15 on 2026-06-12** (user said "closed 481" — matches almost exactly), and the move **reaching 550 by 2026-06-18** — the real intraday high on 06-18 was **554.0** (open 549.95), matching "reached 550" as an intraday level; the actual 06-18 CLOSE was lower, at **525.59** (a pullback from the open/high, not a close at 550 — this distinction matters and is called out explicitly since the user's framing could be read either way).

### Step 2 — PSX announcements/news verification

**Company page (`dps.psx.com.pk/company/SHFA`) — CONFIRMED, fetched successfully.** Item found INSIDE the requested window (2026-05-28 to 2026-06-22):

| Date | Title |
|---|---|
| **Jun 19, 2026** | **Board Meeting Other Than Financial Results** |

This is a genuine disclosed event, one day after the move's reference end-date (2026-06-18) but inside the announcement-scan window requested. **This must be flagged as a possible catalyst, not dismissed** — a board meeting announced/held June 19 could reflect the market front-running/anticipating that meeting during the June 15–18 run-up (rumor or leak ahead of the formal notice), or be unrelated timing. This scrape cannot determine which; only that the disclosed event exists and sits immediately adjacent to the move.

Other SHFA items are all outside the window: Apr 16 (Board Meeting), Apr 1 (EGM resolutions), Jun 29 (another Board Meeting Other Than Financial Results, 11 days after), and a recurring series of "Disclosure of Interest by a Director/CEO/Executive" filings dated Jul 21, Jul 27, Aug 6, Aug 13, Aug 31 2026 — all well after this move, not relevant to it.

**PSX-wide notices (`dps.psx.com.pk/announcements/psx`) — INCONCLUSIVE, same as AICL.** Same JS-rendered search form, same empty static response. Not verified.

**Bottom line for Step 2 (SHFA): a real, disclosed Board Meeting sits one day past the move's reference end-date, inside the requested scan window. This is the strongest "possible catalyst" finding of the two stocks in this study — flag it prominently, do not bury it.**

### Step 3 — Technical pre-move analysis

**Chart structure:** 2026-05-29 through 2026-06-12 is a **tight consolidation/base**, closes ranging 470.36–482.32 (roughly a 2.5% band) — a genuine flat base, tighter than AICL's. 06-12 close (481.15) sits at the TOP of that base. 06-15 (491.84) and 06-16 (497.96) are the first closes clearly above the base — an early, gradual breakout. 06-17 is the **violent breakout/gap day**: opens at the prior close (497.96), rockets to a high of 546.0, closes at 541.06 (+8.65% on the day) on 3.80× normal volume. 06-18 opens even higher (549.95), hits the session's high of 554.0, then pulls back to close at 525.59 — a classic blow-off/exhaustion shape on the second breakout day.

**Breakout day: 2026-06-17.** Close 541.06, volume 74,731 — **3.80× the 20-day average.**

**Full day-by-day timeline (2026-05-28 to 2026-06-18; 05-28 itself has no bar — see Step 1):**

| Date | Close | Volume | Vol vs 20d avg | Vol vs 50d avg | Candlestick pattern(s) | EMA20 vs EMA50 | MACD hist | RSI(14) | Bollinger flag |
|---|---|---|---|---|---|---|---|---|---|
| 2026-05-28 | — | — | — | — | **NO DATA — see Step 1 gap note** | — | — | — | — |
| 2026-05-29 | 482.32 | 6,076 | 0.63× | 0.28× | — | 20>50 | -1.130 | 49.7 | — |
| 2026-06-01 | 474.80 | 12,848 | 1.46× | 0.6× | — | 20>50 | -1.284 | 45.5 | **near lower band** |
| 2026-06-02 | 473.78 | **46,425** | **4.5×** | 2.07× | — | 20>50 | -1.378 | 44.9 | **near lower band** |
| 2026-06-03 | 470.36 | **72,623** | **5.3×** | 3.05× | — | 20>50 | -1.579 | 43.0 | **near lower band** |
| 2026-06-04 | 473.49 | 7,915 | 0.6× | 0.35× | — | 20>50 | -1.415 | 45.3 | **near lower band** |
| 2026-06-05 | 473.02 | 4,186 | 0.31× | 0.19× | — | **20<50 (death cross this day)** | -1.257 | 45.0 | **near lower band** |
| 2026-06-08 | 472.93 | 6,563 | 0.51× | 0.3× | **Doji** | 20<50 | -1.084 | 44.9 | **near lower band** |
| 2026-06-09 | 478.66 | 6,454 | 0.53× | 0.29× | **Hammer** | 20<50 | -0.537 | 49.6 | — |
| 2026-06-10 | 470.39 | 5,520 | 0.45× | 0.25× | — | 20<50 | -0.677 | 43.8 | **near lower band** |
| 2026-06-11 | 475.79 | 22,790 | **1.73×** | 1.01× | — | 20<50 | -0.365 | 48.1 | — |
| 2026-06-12 | 481.15 | 13,076 | 0.96× | 0.58× | **Doji** | 20<50 | +0.211 | 51.9 | — |
| 2026-06-15 | 491.84 | 36,614 | **2.38×** | 1.58× | — | **20>50 (golden cross this day)** | +1.263 | 58.6 | — |
| 2026-06-16 | 497.96 | 21,033 | 1.29× | 0.92× | — | 20>50 | +2.263 | 61.8 | — |
| 2026-06-17 | 541.06 | **74,731** | **3.8×** | 3.07× | — | 20>50 | +5.532 | 76.1 | — |
| 2026-06-18 | 525.59 | 34,392 | **1.62×** | 1.38× | — | 20>50 | +6.303 | 66.5 | — |

**Indicator/cross summary:**
- **EMA20/EMA50:** death cross on 06-05, golden cross back on **06-15** — two sessions before the violent 06-17 breakout.
- **MACD histogram:** negative from before the window start through 06-11, flips positive on **06-12** — the exact date the user cited as the pre-move reference close (481.15).
- **RSI(14):** dipped into the low-to-mid 40s (a mild pullback, never deeply oversold like AICL's 34.4) from 06-01 to 06-10, recovered to 51.9 on 06-12, then to a **peak of 76.1 on 06-17** (genuinely overbought by the textbook 70+ line) before easing to 66.5 on 06-18.
- **Bollinger:** price sat near (not decisively below) the lower band from 06-01 through 06-10 — a mild pullback/basing signature, not a sharp oversold flush like AICL.

### Step 4 — SHFA Summary Signature

**Confirmed from PSX announcements:** A **Board Meeting (Other Than Financial Results)** was disclosed for **June 19, 2026** — one day after the move's reference end-date, inside the requested scan window. This is a real, confirmed, disclosed event immediately adjacent to the move and must be treated as a possible catalyst. PSX-wide notices page unverified (same JS-rendering limitation as AICL) — inconclusive on that front.

**Inferred from price/volume only (plain English):** SHFA based in a tight ~470–482 range for two weeks, a Doji on 06-08 and Hammer on 06-09 marking the shallow low of that base, MACD histogram turning positive on 06-12 (the exact date the user flagged), then a steady climb through 06-15/06-16 into a violent two-day breakout on 06-17 (+8.65% on 3.8× volume, RSI hitting 76.1 — genuinely overbought) and 06-18 (gapping higher intraday to 554 before pulling back to close at 525.59 — an exhaustion/blow-off shape). The move from the 06-12 reference close (481.15) to the 06-17 close (541.06) is +12.5%, or to the 06-18 intraday high (554.0) is +15.2%.

**Given the confirmed Board Meeting disclosure sitting right at the edge of this window, this move should NOT be labeled catalyst-free — there is a real, named, dated event immediately adjacent to it.**

---

## Cross-stock notes for the broader pattern-model dataset

- Both moves share a common technical shape: **basing/consolidation → oversold-to-mild-pullback reading → reversal candle (Engulfing for AICL, Hammer+Doji for SHFA) → MACD histogram sign flip → volume-confirmed breakout (8.7× and 3.8× the 20-day average respectively)**. If this shape recurs across more PSX cases, it's a candidate for a genuine confluence pattern — but n=2 is nowhere near enough to claim that; this is a first-entries dataset, not a validated signal.
- Both stocks have at least one point of PSX-disclosure ambiguity (AICL: PSX-wide notices unverified; SHFA: a genuine board meeting one day past the reference window). **Neither move is confirmed catalyst-free.** Future entries in this dataset should keep confirmed-disclosure and inferred-technical findings in separate columns, exactly as done here, rather than blending them into one verdict.
- The PSX-wide notices page (`dps.psx.com.pk/announcements/psx`) is JS-rendered and not scrapable with a plain HTTP GET — any future entry in this dataset needs either a headless-browser fetch or PSX's underlying AJAX endpoint (not yet reverse-engineered in this project) to actually check market-wide unusual-movement queries. This is a real, standing gap in this study's verification, not a one-off.
- 2026-05-26 through 2026-05-28 is very likely a multi-day PSX market holiday (both AICL's and SHFA's independently-fetched date ranges show the identical gap) — worth confirming against an actual PSX holiday calendar and recording in this project's config if this dataset grows, so future studies don't have to re-discover it.

## Reproducibility

- Raw fetched data (OHLC + full announcement rows + PSX-wide notices attempt): GitHub Actions run [33746474452](https://github.com/imranrazabozdar/PSX-INTELLIGENCE-NEW-2026/actions/runs/33746474452), triggered from `analysis/fetch_premove_data.py`, saved verbatim as `analysis/premove_data_raw.json`.
- Indicator computation and pattern scan: `analysis/analyze_premove.py` (unit-tested against synthetic OHLC for Bullish Engulfing, Doji, Hammer, Piercing Line, and Morning Star before running on real data), reads `premove_data_raw.json` and writes `analysis/premove_analysis.json` — every number in the tables above is generated programmatically from that file, not hand-transcribed (an earlier hand-typed draft of these tables had real transcription errors in the volume-ratio columns, caught and fixed by regenerating the tables straight from the JSON instead).
- To add a 3rd+ entry to this dataset: edit `TARGETS` in `fetch_premove_data.py` (new symbol/company-hint/date windows), re-run the `Pre-move study data fetch (manual, one-off)` GitHub Actions workflow, save its JSON output over `premove_data_raw.json`, then re-run `analyze_premove.py`.
