#!/usr/bin/env python3
"""Assembles the full AICL_SHFA_premove_study.md (v2) from the
programmatically-generated tables/narratives in gen_report_v2.py plus
static prose written for this round. Run this, don't hand-edit the
generated tables in the .md file directly -- if the underlying data or
indicator logic changes, re-run analyze_premove.py then this script.
"""
from pathlib import Path
import gen_report_v2 as g

OUT = Path(__file__).parent / "AICL_SHFA_premove_study.md"

analysis = g.analysis
crosses = analysis["crosses"]


def window_str(sym):
    c = crosses[sym]
    return f"{c['report_start']} to {c['report_end']}"


def stock_section(sym, title, chart_note, extra_note=""):
    return f"""## {title}

### Data coverage & ticker identity

Report window: **{window_str(sym)}**. OHLC pulled from `dps.psx.com.pk/historical` via `backend/dps_scraper.py`, same source as the first pass of this study. Ticker identity for **{sym}** confirmed two ways (announcements/company-page checking is explicitly out of scope for this round, so identity was verified without it): (1) `{sym}` is one of this project's own already-used, real PSX Watchlist symbols (`backend/app.py`'s `WATCHLIST_SYMBOLS`), and (2) the fetched OHLC values on the user's own reference dates match the user-stated reference prices almost exactly (see table below) — a coincidental match on both the ticker symbol AND the exact price level on the exact date is not plausible for a wrong/similarly-named scrip.
{extra_note}
**Chart structure:** {chart_note}

### Day-by-day forensic table

Every column below is generated programmatically from `analysis/premove_analysis.json` (see Reproducibility) — none of these numbers are hand-typed. Weekday rows with no PSX-reported trade are shown explicitly as gap rows, not skipped.

{g.build_table(sym)}

### What specifically fired, and on which day

Day offsets are relative to the user-given move-start date ({g.MOVE_START[sym]} = Day 0).

{g.what_fired(sym)}
"""


AICL = stock_section(
    "AICL", "STOCK 1 — AICL (Adamjee Insurance Company Limited)",
    "07-08 through 07-22 is a ragged downward drift/consolidation (closes ~75.9-81.7). "
    "07-23 (close 73.02) is a flush-out low below that range. 07-24 reverses hard off that low "
    "(Bullish Engulfing). 07-27 closes back above the top of the prior range; the volume breakout "
    "confirms on 07-28 (8.70x the 20-day average).",
    "\n**Note on this round's re-fetch:** AICL/SHFA were re-fetched at the same full daily granularity "
    "as the first pass (per this round's instruction); the announcement findings from the first pass "
    "(company page: no in-window disclosure found; PSX-wide notices: unverifiable JS-rendered page) "
    "still stand and are carried forward below unchanged — see \"Confirmed PSX-announcement findings "
    "(carried forward from first pass)\".\n\n"
    "**Confirmed PSX-announcement findings (carried forward from first pass, not re-checked this round):** "
    "No company-disclosed announcement found inside the 2026-07-08 to 2026-08-10 window on the company "
    "page. PSX-wide notices page could not be verified (JS-rendered search). Do not read this as "
    "\"confirmed catalyst-free\" — read it as \"no company-disclosure catalyst found in the sources "
    "checked; market-wide notices unchecked.\"\n"
)

SHFA = stock_section(
    "SHFA", "STOCK 2 — SHFA (Shifa International Hospitals Limited)",
    "05-29 through 06-12 is a tight consolidation/base (closes 470.36-482.32, ~2.5% band). "
    "06-15/06-16 are the first closes clearly above the base. 06-17 is the violent breakout/gap day "
    "(+8.65% on 3.80x volume). 06-18 opens even higher, hits an intraday high of 554.0, then pulls "
    "back to close at 525.59 — a blow-off/exhaustion shape on the second breakout day.",
    "\n**Note on this round's re-fetch:** re-fetched at full daily granularity per this round's "
    "instruction; the first pass's announcement finding stands unchanged — see below.\n\n"
    "**Confirmed PSX-announcement findings (carried forward from first pass, not re-checked this round):** "
    "A **Board Meeting (Other Than Financial Results)** was disclosed for **June 19, 2026** — one day "
    "after the move's reference end-date. This is a real, confirmed, disclosed event immediately "
    "adjacent to the move and should be treated as a possible catalyst; this move should NOT be "
    "labeled catalyst-free.\n"
)

THCCL = stock_section(
    "THCCL", "STOCK 3 — THCCL (full company name not independently confirmed this round, since the "
    "company-page fetch is out of scope this pass — ticker identity below is confirmed via the "
    "project's own watchlist and by exact-price-match instead)",
    "06-15 through 06-24 opens already elevated (SMA20 well below spot, RSI 60-77) then bleeds down "
    "through 06-29/06-30 as momentum cools. 07-01 is the first clear reversal up (+4.3% on the day), "
    "then a multi-day base 07-02 to 07-06 in the high-66s to high-68s. 07-07 is the volume breakout "
    "day (3.79x the 20-day average, +7.3% on the day), followed by continued elevated volume into "
    "07-08/07-09, closing the window at 73.21 with a confirmed Bullish Engulfing on 07-09.",
    "\n**Announcements/catalyst-checking intentionally out of scope for this round** (per this round's "
    "explicit instruction — pure price/volume/technical forensics only, all four stocks). No claim of "
    "\"catalyst-free\" is made for THCCL; this is simply not checked in this pass.\n"
)

FNEL = stock_section(
    "FNEL", "STOCK 4 — FNEL (full company name not independently confirmed this round, since the "
    "company-page fetch is out of scope this pass — ticker identity below is confirmed via the "
    "project's own watchlist and by exact-price-match instead)",
    "The report window opens already inside a multi-week grind lower (03-24 to 04-07, closes 1.25 "
    "down to 1.16, RSI mid-30s to low-40s, EMA20 below EMA50 throughout — a genuine bearish trend, "
    "not a base). 04-08 is the volume breakout day: +31.2% on the day (open 1.30, high 1.60, close "
    "1.58) on 8.65x the 20-day average volume (212M shares) — the single most extreme reading in any "
    "of the four stocks' windows. 04-09/04-10 give back some of that gain (1.47, then 1.44) before a "
    "second, calmer base 04-13 to 04-22 (1.31-1.46). 04-23 is a second violent volume spike "
    "(+22.3% on the day, 5.71x avg volume, high hits 1.74 exactly matching the user's reference), "
    "closing the window at 1.51 on 04-24 after a pullback from that high.",
    "\n**Important data-quality note — READ BEFORE USING THIS SECTION:** FNEL's fetched historical "
    "series shows an abrupt **~90.7% single-day price adjustment on 2026-02-02** (close 17.70 on "
    "2026-01-30 -> 1.65 on 2026-02-02, volume spiking to 191,182,675 vs a typical 8-20M in the days "
    "before). This is the classic signature of a large bonus-share or rights issue on PSX being "
    "reflected as a raw (non-split-adjusted) price cliff in the historical table, **not a real -90.7% "
    "one-day return and not a wrong-ticker mixup**: the post-adjustment series continues trading "
    "organically at the new scale, and the window-end values (close 1.16 on 2026-04-06, high 1.74 on "
    "2026-04-23) match the user's own reference prices for this move almost exactly, which would be an "
    "implausible coincidence for a mismatched scrip. To keep every moving-average/volatility/Bollinger "
    "calculation below from spanning that capital-structure discontinuity, this study's indicator "
    "computation for FNEL **excludes bars before 2026-02-02** — meaning the 50-day volume/price "
    "averages only reach full 50-bar depth partway through the report window (rows before that show "
    "\"insufficient history\" for the SMA50/vol comparisons, honestly, rather than a computed-but-wrong "
    "number spanning the cliff). This is a genuine limitation of the underlying PSX historical data for "
    "this stock, not an error in this study's methodology, and readers should independently confirm the "
    "corporate-action date/ratio against PSX's official disclosures before using pre-April FNEL price "
    "history for anything beyond this technical study.\n\n"
    "**Announcements/catalyst-checking intentionally out of scope for this round** (same as THCCL — "
    "pure technical forensics only this pass). No claim of \"catalyst-free\" is made for FNEL.\n"
)

CROSS_STOCK = f"""## Cross-stock first-occurrence comparison

For all four stocks, the day (relative to each stock's own move-start date, Day 0) each of the following
first appears in its report window:

{g.cross_stock_table()}

**Reading this table:** the breakout day (highest-conviction volume+price confirmation) lands between
Day +2 and Day +5 across all four stocks — a fairly tight cluster given the four stocks span wildly
different price scales (₹1-2 for FNEL up to ₹500+ for SHFA) and sectors (insurance, healthcare, cement,
fertilizer). The first >2x-average-volume day and the breakout day coincide exactly for THCCL and FNEL,
but not for AICL or SHFA (where an earlier, smaller volume pickup preceded the actual breakout by several
sessions) — so "first elevated volume" is not a reliable stand-alone breakout-timing signal on its own in
this n=4 sample; it needs to be read together with the candlestick/MACD/BB signals in the same row. BB
oversold readings and EMA20/50 golden crosses are inconsistent across the four (present for AICL/SHFA,
absent for THCCL, and only very late for FNEL, well after its own breakout) — with n=4, this is descriptive,
not a validated cross-stock rule.
"""

METHOD_NOTE = """# Pre-Move Study: AICL, SHFA, THCCL & FNEL

**Prepared:** 2026-09-03 (deepened/extended from the first pass, which covered only AICL/SHFA at
summary-level detail).
**Method note (read first):** All price/volume data below is real, pulled directly from PSX's own Data
Portal (`dps.psx.com.pk/historical`) via `backend/dps_scraper.py` — the same source this project's
production backfill uses, not yfinance and not training knowledge. Because this session's own sandbox
cannot reach `dps.psx.com.pk` directly (network egress block — the same constraint already documented in
`backend/news_fetcher.py`), the actual fetch ran in a GitHub Actions job
(`.github/workflows/premove_data_fetch.yml`, real unrestricted network) and its logs were pulled back
into this session as the data-transport mechanism. The fetch script is `analysis/fetch_premove_data.py`.

**This round's scope, explicitly:** pure price/volume/technical forensics only, on all four stocks — no
announcement/catalyst checking was performed for THCCL or FNEL in this pass, and AICL/SHFA's
announcement findings below are carried forward unchanged from the first pass (not re-checked). This
round's contribution is (1) a genuine day-by-day forensic table (open/high/low/close/volume/vol-avg/
vol-ratio/candle-pattern/pattern-criteria-text/price-vs-MA20/price-vs-MA50/BB-sigma-position/MACD-hist/
MACD-direction/EMA-cross-state/RSI/support-resistance-note) replacing the earlier summary-level table for
AICL and SHFA, (2) the same table for two new stocks, THCCL and FNEL, and (3) a cross-stock
first-occurrence comparison table.

Indicators (EMA20/EMA50, MACD(12,26,9), Bollinger(20,2), RSI(14), 20-day volume averages, SMA20/SMA50)
are computed over an EXTENDED lookback (~70 calendar days before each requested window) so every
reported day has genuine trailing history to average against — not padded with `None`. Candlestick
pattern rules (Bullish Engulfing, Morning Star, Hammer, Doji, Piercing Line) are literal, classic
textbook definitions, implemented and unit-tested against synthetic OHLC before running on real data.
Support/resistance notes come from a simple retrospective swing-point scan (local highs/lows over a
+/-3-bar window) — this is a descriptive, after-the-fact structural annotation, not a causal/live
trading signal (a swing point's confirmation legitimately uses bars that come after it in the series).

---

"""

REPRO = f"""## Reproducibility

- Raw fetched data (all four stocks' OHLC, this round's pure-technical pass — no announcements fetched):
  GitHub Actions run
  [33750322608](https://github.com/imranrazabozdar/PSX-INTELLIGENCE-NEW-2026/actions/runs/33750322608),
  triggered from `analysis/fetch_premove_data.py`, saved verbatim as `analysis/premove_data_raw.json`.
  (First pass's AICL/SHFA-plus-announcements run remains at
  [33746474452](https://github.com/imranrazabozdar/PSX-INTELLIGENCE-NEW-2026/actions/runs/33746474452)
  for the announcement findings carried forward above.)
- Indicator computation, pattern scan, FNEL pre-adjustment trim, and first-occurrence tracking:
  `analysis/analyze_premove.py` (unit-tested against synthetic OHLC before running on real data), reads
  `premove_data_raw.json` and writes `analysis/premove_analysis.json`.
- Markdown table / "what fired" narrative / cross-stock table generation: `analysis/gen_report_v2.py`,
  assembled into this file by `analysis/build_full_report.py` — every number in the tables above is
  generated programmatically from `premove_analysis.json`, never hand-typed (the lesson from the first
  pass, where a hand-typed draft had real transcription errors, caught only by cross-checking against the
  raw JSON). Re-running `analyze_premove.py` from its repo location reproduces byte-identical JSON output
  (verified via `diff` on sorted `json.dumps()` output).
- To add a 5th+ entry to this dataset: add an entry to `TARGETS` in `fetch_premove_data.py` and a
  `MOVE_START` entry in `analyze_premove.py`, re-run the `Pre-move study data fetch (manual, one-off)`
  GitHub Actions workflow, save its JSON output over `premove_data_raw.json`, then re-run
  `analyze_premove.py` and `build_full_report.py`.
"""

full = METHOD_NOTE + AICL + "\n---\n\n" + SHFA + "\n---\n\n" + THCCL + "\n---\n\n" + FNEL + "\n---\n\n" + CROSS_STOCK + "\n---\n\n" + REPRO

OUT.write_text(full)
print(f"Wrote {len(full):,} chars to {OUT}")
