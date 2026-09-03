#!/usr/bin/env python3
"""Assembles the full AICL_SHFA_premove_study.md from the
programmatically-generated tables/narratives in gen_report_v2.py plus
static prose written for this round. Run this, don't hand-edit the
generated tables in the .md file directly -- if the underlying data or
indicator logic changes, re-run analyze_premove.py then this script.

This version (indicator-expansion + 8-new-stock round) covers all 12
stocks now in the dataset: AICL, SHFA, THCCL, FNEL (re-run through the
expanded indicator set, replacing their prior tables) plus MDTL, FPJM,
BNL, DSIL, SYM, PREMA, JSBL, ILP (new this round). BNL's section is a
data-quality disclosure, not a forensic narrative -- see its section
below for why.
"""
from pathlib import Path
import gen_report_v2 as g

OUT = Path(__file__).parent / "AICL_SHFA_premove_study.md"

analysis = g.analysis
crosses = analysis["crosses"]


def window_str(sym):
    c = crosses[sym]
    return f"{c['report_start']} to {c['report_end']}"


def identity_note(sym, extra=""):
    return (
        f"Report window: **{window_str(sym)}**. OHLC pulled from `dps.psx.com.pk/historical` via "
        f"`backend/dps_scraper.py`. Ticker identity for **{sym}** confirmed two ways (announcements/"
        f"company-page checking remains out of scope this round): (1) `{sym}` is one of this project's "
        f"own already-used, real PSX Watchlist symbols (`backend/app.py`'s `WATCHLIST_SYMBOLS`), and "
        f"(2) the fetched OHLC on the user's exact reference dates matches the user-stated reference "
        f"prices (see table below).{extra}"
    )


def flow_divergence_summary(sym):
    days = g.flow_divergence_days(sym)
    if not days:
        return "No OBV/A-D Line divergence-from-price days detected anywhere in this window."
    lines = [f"{len(days)} day(s) with an OBV/A-D Line divergence-from-price flag:"]
    for date, note in days:
        lines.append(f"  - {date}: {note}")
    return "\n".join(lines)


def stock_section(sym, title, chart_note, extra_identity="", extra_note=""):
    return f"""## {title}

### Data coverage & ticker identity

{identity_note(sym, extra_identity)}
{extra_note}
**Chart structure:** {chart_note}

### Core day-by-day table (OHLC, candles, trend)

{g.build_core_table(sym)}

### Volume & flow table (same dates as the core table above)

MFI(14) is volume-weighted RSI; OBV and A/D Line are both cumulative volume-direction
indicators (OBV uses simple close-to-close direction, A/D Line weights by where the close
sits within its own high-low range -- the two can diverge, which is itself informative,
see "Flow divergence" below); ATR(14) is Wilder-smoothed true range, in price units; VWAP
here is a **window-anchored approximation** (cumulative volume-weighted typical price
`(H+L+C)/3`, restarting at this window's own first day) since only daily OHLCV is
available -- **not** a real intraday VWAP; Tenkan-sen/Kijun-sen and the Ichimoku cloud use
standard periods (9/26/52, cloud displaced 26 periods forward) -- the cloud reading for the
last ~26 days of any window is provisional, since Senkou Span A/B for those days are drawn
from Tenkan/Kijun computed inside the window itself, the same caveat real charting
platforms show for an unclosed forward cloud.

{g.build_flow_table(sym)}

### What specifically fired, and on which day

Day offsets are relative to the user-given move-start date ({g.MOVE_START[sym]} = Day 0).

{g.what_fired(sym)}

### Flow divergence check

{flow_divergence_summary(sym)}
"""


AICL = stock_section(
    "AICL", "STOCK 1 — AICL (Adamjee Insurance Company Limited)",
    "07-08 through 07-22 is a ragged downward drift/consolidation (closes ~75.9-81.7). "
    "07-23 (close 73.02) is a flush-out low below that range. 07-24 reverses hard off that low "
    "(Bullish Engulfing). 07-27 closes back above the top of the prior range; the volume breakout "
    "confirms on 07-28 (8.70x the 20-day average).",
    extra_note="\n**Confirmed PSX-announcement findings (carried forward from the first pass, not "
    "re-checked this or last round):** No company-disclosed announcement found inside the "
    "2026-07-08 to 2026-08-10 window on the company page. PSX-wide notices page could not be "
    "verified (JS-rendered search). Do not read this as \"confirmed catalyst-free.\"\n"
)

SHFA = stock_section(
    "SHFA", "STOCK 2 — SHFA (Shifa International Hospitals Limited)",
    "05-29 through 06-12 is a tight consolidation/base (closes 470.36-482.32, ~2.5% band). "
    "06-15/06-16 are the first closes clearly above the base. 06-17 is the violent breakout/gap day "
    "(+8.65% on 3.80x volume). 06-18 opens even higher, hits an intraday high of 554.0, then pulls "
    "back to close at 525.59 -- a blow-off/exhaustion shape on the second breakout day.",
    extra_note="\n**Confirmed PSX-announcement findings (carried forward, not re-checked):** A "
    "**Board Meeting (Other Than Financial Results)** was disclosed for **June 19, 2026** -- one "
    "day after the move's reference end-date. Treat as a possible catalyst; not catalyst-free.\n"
)

THCCL = stock_section(
    "THCCL", "STOCK 3 — THCCL (full company name not independently confirmed, company-page "
    "fetch out of scope this round)",
    "06-15 through 06-24 opens already elevated (RSI 60-77) then bleeds down through 06-29/06-30. "
    "07-01 is the first clear reversal up, then a base 07-02 to 07-06. 07-07 is the volume breakout "
    "(3.79x the 20-day average, +7.3% on the day), continued elevated volume into 07-08/07-09, "
    "closing the window at 73.21 with a confirmed Bullish Engulfing on 07-09.",
    extra_note="\n**Announcements/catalyst-checking remains out of scope.** No claim of "
    "\"catalyst-free\" is made for THCCL.\n"
)

FNEL = stock_section(
    "FNEL", "STOCK 4 — FNEL (full company name not independently confirmed, company-page fetch "
    "out of scope this round)",
    "The window opens inside a multi-week grind lower (03-24 to 04-07). 04-08 is the volume "
    "breakout day: +31.2% on 8.65x the 20-day average (212M shares) -- the single most extreme "
    "single-day reading in the whole dataset. 04-09/04-10 give back some gain before a calmer base "
    "04-13 to 04-22, then a second violent volume spike on 04-23 (+22.3%, high 1.74 matching the "
    "user's reference) closing the window at 1.51 on 04-24.",
    extra_note="\n**Data-quality note (carried forward from the deepening round):** FNEL's series "
    "shows an abrupt ~90.7% single-day price adjustment on 2026-02-02 (17.70->1.65, volume "
    "191M vs a typical 8-20M) -- a bonus/rights-issue signature, not a real return and not a "
    "wrong-ticker mixup (post-adjustment trajectory matches the user's reference prices exactly). "
    "This round's general `detect_price_cliffs()` was verified to still find exactly this same "
    "cliff (asserted in `analyze_premove.py`'s `main()`) and NOT the real 04-08 breakout day "
    "(the detector only flags price DROPS, since a bonus/rights issue mechanically dilutes price "
    "down, never up -- see the function's docstring). Indicator computation excludes bars before "
    "2026-02-02.\n**Announcements/catalyst-checking remains out of scope.**\n"
)

MDTL = stock_section(
    "MDTL", "STOCK 5 — MDTL",
    "07-08 through 07-13 drifts down into a shallow low, price pushing to a Bollinger extreme "
    "(-2.3 sigma on 07-14), a Doji on 07-15 marking the low. The real move happens fast: 07-24 is "
    "both the first >2x-volume day (6.52x) AND the MACD histogram's sign flip AND the breakout day "
    "simultaneously -- a same-day confirmation rather than a staged sequence like AICL/SHFA showed. "
    "Window closes 6.15 on 07-27, near the open (6.85) after an intraday pullback."
)

FPJM = stock_section(
    "FPJM", "STOCK 6 — FPJM",
    "This is the largest percentage move in the whole dataset (10.02 -> 27.80, +177%, over five "
    "weeks). 07-29 through 08-17 is a slow grind higher on ordinary volume; 08-18 is the first "
    "vol>2x day and the breakout day together (2.76x). From there the climb continues through late "
    "August into a final push, closing the window at 23.15 on 09-03 -- below the day's own open "
    "(27.99) and well off the window's peak, a pullback from an extended run rather than a single "
    "clean breakout day the way MDTL or THCCL showed."
)

DSIL = stock_section(
    "DSIL", "STOCK 7 — DSIL",
    "07-16 through 07-22 is a mild base; 07-17 (day -10) already shows a >2x volume day and a "
    "positive MACD histogram flip, well ahead of the reference move-start (07-31). A Piercing Line "
    "on 07-23 and an EMA20/50 golden cross on 07-24 both land inside this early window too -- meaning "
    "by the time the reference move-start date itself arrives, several bullish signals had already "
    "fired. The actual highest-conviction breakout day is 08-03 (4.35x volume), well into the second "
    "half of the window; the close at window-end (08-12) is 15.07, a pullback from the day's own "
    "high of 17.75 (matching the user's reference) after a huge 67.5M-share volume day."
)

SYM = stock_section(
    "SYM", "STOCK 8 — SYM",
    "This window captures BOTH legs the user asked for: an early dip (low 9.85 on 04-30, the "
    "user-given Day 0) inside a broader decline that started well before the window, then a slow "
    "multi-month climb through May/June to the final breakout reference (high 12.69 on 07-03). "
    "Note the breakout_day computed here (04-27, 6.43x volume) actually falls just BEFORE the "
    "04-30 dip reference -- a large volume day on the way down, not on the way up -- while the "
    "real MACD sign flip into bullish territory only comes on 05-13 (day +8), after the dip. This "
    "is a materially different, slower shape than the other stocks in this dataset: no single clean "
    "breakout day, more of a multi-week grind."
)

PREMA = stock_section(
    "PREMA", "STOCK 9 — PREMA",
    "03-16 through 03-29 drifts down into a Doji-marked low on 03-18, reaching a genuine "
    "Bollinger extreme (-2.2 sigma) exactly on the reference move-start date, 03-30. Volume and "
    "price both build over the following two weeks; the highest-conviction breakout day is 04-14 "
    "(3.24x volume), roughly three weeks into the window, with an EMA20/50 golden cross following "
    "on 04-24, close to the window's end. No MACD histogram sign flip was detected in-window (it "
    "may have flipped before 03-16, outside this report's start)."
)

JSBL = stock_section(
    "JSBL", "STOCK 10 — JSBL",
    "05-04 opens the window already at 13.66; 05-06 (day -9) is an extreme single-day volume spike "
    "(10.7x the 20-day average) alongside a Bollinger extreme, both well before the reference "
    "move-start (05-19). A Bullish Engulfing on 05-25 and the MACD sign flip/breakout day on 05-29 "
    "(2.6x volume) follow. Window closes 13.78 on 06-02, close to its open (14.50) that day after "
    "an intraday pullback from a high of 15.20 (matching the user's reference)."
)

ILP = stock_section(
    "ILP", "STOCK 11 — ILP",
    "05-18 through 06-03 is a shallow, choppy base (78-84 range), touching a Bollinger extreme "
    "(-1.8 sigma) on 05-18 itself. 06-04 (day +2) is a sharp single-day volume spike (9.5x average) "
    "that doubles as the breakout day, though price only firms up gradually after it; the real "
    "acceleration comes 06-12 through 06-30, with RSI climbing into the high 70s/low 80s and the "
    "window closing at 107.54 on 06-30, essentially matching the user's reference (107.00)."
)

BNL_MISMATCH = """## STOCK 12 — BNL — TICKER/PRICE MISMATCH, NOT A FORENSIC SECTION

**This section is a data-quality disclosure, not a pre-move forensic narrative, per the explicit
instruction to report any mismatch rather than silently proceed.**

The user's reference for BNL was **2.10 on 2025-05-09 -> 17.10 on 2025-09-17** (a >700% move
flagged in advance as needing a price-cliff/corporate-action check, the same way FNEL's real
2026-02-02 bonus-share adjustment was caught).

The real, fetched PSX data for ticker `BNL` over an extended window (2025-02-09 to 2025-09-17,
149 trading days) shows:

- **2025-05-09 close: 23.20** (not 2.10 -- off by roughly 11x)
- **2025-09-17 close: 160.09** (not 17.10 -- off by roughly 9.4x)
- The full 149-bar series is **smooth and continuous** -- `detect_price_cliffs()` (the same
  function that correctly found FNEL's real 2026-02-02 bonus-share cliff) found **zero**
  qualifying discontinuities anywhere in this window. There is no single-day price cliff that
  would reconcile the ~10x gap between the user's reference numbers and the real fetched prices.
- The real move IS large and real -- close 13.99 on 2025-02-10 to close 160.09 on 2025-09-17, a
  genuine +1044% run over the period -- just not at the price levels the user cited.

**What this means:** unlike FNEL (where a real, dated corporate action fully explained an
apparent price-scale mismatch, confirmed by the post-adjustment prices matching the user's
reference exactly), BNL's real PSX price history does not match the user-given reference prices
at either endpoint, by a consistent ~10x factor, with no dated event to explain it. Plausible
explanations that this study cannot resolve without further input: the reference prices may be
quoting a different par-value/share class, a different exchange, an already-split-adjusted
series from another source, or `BNL` on `dps.psx.com.pk` may not be the intended scrip at all
(a similarly-named ticker issue, exactly as the user's own instructions warned against for
THCCL/FNEL in the prior round -- worth the same scrutiny here).

**No day-by-day forensic table, "what fired" narrative, or chart-structure summary is produced
for BNL in this round.** Producing one would imply this data represents the move the user asked
about, which it does not, at least not without further confirmation of the reference prices'
source/scale or of `BNL`'s exact intended identity. The real fetched OHLC (2025-02-09 to
2025-09-17) is nonetheless saved in `analysis/premove_data_raw.json` and its indicators in
`analysis/premove_analysis.json` under the `BNL` key, available once/if the mismatch is resolved.
"""

CROSS_STOCK = f"""## Cross-stock first-occurrence comparison (all 12 stocks)

For all twelve stocks currently in the dataset, the day (relative to each stock's own move-start
date, Day 0) each of the following first appears in its report window. **BNL is included in this
table only because it produces real numbers from real (if reference-mismatched) PSX data for the
fetched `BNL` ticker -- its row(s) should be read with the identity caveat above in mind, not as
confirmation of the user's originally-described move.**

{g.cross_stock_table()}

**Reading this table:** across the now-11 reliably-identified stocks (excluding BNL), the breakout
day continues to cluster in a fairly narrow band relative to each stock's own move-start date, but
the spread widened noticeably with this round's additions -- SYM's breakout_day computation (day -3)
actually precedes its own move-start reference, and DSIL's/JSBL's/PREMA's earliest signals (first
volume spike, first MACD flip) also land well before their move-start dates, sometimes 6-10 days
early. This is a genuinely more mixed picture than the tight day+2-to+5 cluster the first four
stocks showed -- at n=11, "first elevated volume" and "breakout day" are clearly NOT a single
universal lag from a stock's own reference move-start; the relationship between a user-cited
reference date and this study's own mechanically-detected signal days varies stock to stock,
and should be read per-stock, not assumed to generalize.
"""

METHOD_NOTE = """# Pre-Move Study: AICL, SHFA, THCCL, FNEL, MDTL, FPJM, BNL, DSIL, SYM, PREMA, JSBL, ILP

**Prepared:** 2026-09-03 (indicator-expansion + 8-new-stock round, extending the prior
AICL/SHFA/THCCL/FNEL day-by-day-forensics round).
**Method note (read first):** All price/volume data below is real, pulled directly from PSX's own
Data Portal (`dps.psx.com.pk/historical`) via `backend/dps_scraper.py`. Because this session's
sandbox cannot reach `dps.psx.com.pk` directly, fetches run in a GitHub Actions job
(`.github/workflows/premove_data_fetch.yml`) and results are pulled back via job logs. This
round's 12-symbol combined fetch produced a single JSON-blob log line large enough that GitHub
Actions truncated the head of the log (silently dropping the parsing marker this pipeline depends
on) -- the workflow now accepts an optional `symbols` input (`PREMOVE_SYMBOLS` env var) so a run
can be split into smaller batches; this round's data was fetched across three such batched runs.

**This round's scope, explicitly:** announcement/catalyst-checking remains out of scope for every
stock except the two carried-forward AICL/SHFA findings from the very first pass (not re-checked).
This round's real additions are (1) a significantly expanded indicator layer (below), (2) the
existing AICL/SHFA/THCCL/FNEL sections re-run through it end to end, with an explicit check for
whether the richer indicator set changes any of their stories, and (3) eight new stocks --
MDTL, FPJM, DSIL, SYM, PREMA, JSBL, ILP (all ticker-identity-confirmed) and BNL (ticker-identity
**mismatch**, disclosed rather than force-fit into a forensic narrative -- see its section).

**Expanded indicator layer (added this round), and why:**

- **MFI (Money Flow Index, 14-period)** -- volume-weighted RSI; tests whether volume was actually
  flowing IN during the pre-move window, not just present. Standard convention: simple rolling
  sums of positive/negative typical-price*volume over 14 bars (a different smoothing convention
  from this module's Wilder-smoothed RSI, by design -- MFI and RSI are meant to read differently).
- **OBV (On-Balance Volume)** -- cumulative, close-to-close direction-weighted volume; the
  standard tool for spotting quiet accumulation that doesn't yet show up as a price breakout.
- **A/D Line (Accumulation/Distribution Line)** -- cumulative money-flow-volume, but weighted by
  where each bar's close sits within its own high-low range rather than just up/down close-to-
  close. Reported alongside OBV specifically because the two can diverge from each other, and a
  divergence is itself informative (see each stock's "Flow divergence check").
- **ATR (Average True Range, 14-period)**, Wilder-smoothed -- gives this study's prior qualitative
  "low-volatility base" language an actual measured number.
- **VWAP, window-anchored approximation** -- only daily OHLCV is available, so this is NOT a real
  intraday VWAP; it's a cumulative volume-weighted typical price `(H+L+C)/3`, restarting at each
  report window's own first day. Labeled as such in every table it appears in.
- **Ichimoku Cloud** (standard 9/26/52 periods, cloud displaced 26 periods forward) -- reports
  cloud position (above/below/inside), Tenkan/Kijun cross state and date if one occurred
  in-window, and cloud color (bullish green if Senkou A>B, bearish red otherwise) and thickness.
  Because Senkou Span A/B are plotted 26 periods FORWARD, the cloud reading for the last ~26 days
  of any window is provisional -- it's drawn from Tenkan/Kijun computed inside the window itself,
  not from data further back, the same caveat real charting platforms show for an unclosed
  forward cloud.
- **Morning Star and Piercing Line candlestick patterns** -- both were already implemented and
  unit-tested in the prior round's `scan_patterns()` (verified again this round, not
  re-implemented); Piercing Line fired for the first time in this dataset on DSIL (2026-07-23).

Chart-pattern (geometric) detection -- Head & Shoulders, Double Bottom, Triangle, Cup & Handle --
is explicitly OUT of scope for this round, per instruction: it's a separate, larger task
(geometric pattern recognition across a whole price series, not a single-column indicator) to be
scoped once this indicator layer is confirmed working.

**Did the richer indicator set change the story for AICL/SHFA/THCCL/FNEL?** Checked explicitly,
stock by stock:

- **AICL: confirmed, not changed.** OBV/A-D Line track the existing price narrative closely (both
  negative through the 07-08 to 07-23 drift, both flip sharply positive on the 07-28 breakout).
  One minor nuance: MFI's low (38.3-38.4, around 07-23/07-24) is noticeably less extreme than
  RSI's low (34.4 on 07-23) -- volume-weighted momentum wasn't quite as oversold as price-only
  RSI suggested, but this doesn't change the overall signature.
- **SHFA: genuinely changed.** MFI reads deeply oversold (9.6 on 05-29, 16.8-23.9 through
  06-01/06-02) right at the start of the base -- a much more extreme volume-weighted oversold
  reading, and much earlier, than RSI ever showed in the original pass (RSI only reached the
  low-to-mid 40s). This is new information: volume-weighted selling pressure peaked earlier and
  harder than the price-only view suggested.
- **THCCL: confirmed, not changed.** OBV and MFI both stay elevated throughout (MFI 46-86),
  consistent with the already-elevated momentum the original RSI-based read already showed.
- **FNEL: confirmed for the main 04-08 breakout** (OBV/MFI both flip sharply positive same-day,
  matching the existing narrative), **but with one genuinely new secondary finding**: OBV and MFI
  both show a real accumulation build from 04-14 through 04-17 (OBV climbing from -32M to +55M,
  MFI from 71.9 to 84.6) in the days immediately BEFORE the second volume spike on 04-23 -- a
  quieter, volume-led build-up ahead of that second leg that the original RSI/MACD/BB-only set
  didn't surface as a distinct phase.

No systematic OBV/A-D-Line divergence-from-price cluster was found concentrated specifically in
the days immediately before any of the four stocks' breakout days -- divergence flags occur on
scattered ordinary days across all four (see each section's "Flow divergence check"), not as a
concentrated pre-breakout "quiet accumulation" pattern this richer indicator set would have
otherwise missed with the original set.

Indicators (EMA20/EMA50, MACD(12,26,9), Bollinger(20,2), RSI(14), MFI(14), 20-day volume
averages, SMA20/SMA50, OBV, A/D Line, ATR(14), Ichimoku) are computed over an EXTENDED lookback
(~70 calendar days before each requested window, more for BNL/SYM given their wider windows) so
every reported day has genuine trailing history to average against. Candlestick pattern rules
(Bullish Engulfing, Morning Star, Hammer, Doji, Piercing Line) are literal, classic textbook
definitions, unit-tested against synthetic OHLC before running on real data. Support/resistance
notes come from a retrospective swing-point scan (local highs/lows over a +/-3-bar window) --
descriptive, not a causal/live trading signal.

**General price-cliff detector (generalized this round from a FNEL-specific hardcode):** every
stock's raw series is scanned for a day whose close DROPS more than 30% from the prior close AND
whose volume exceeds 3x the trailing 10-day average -- deliberately one-sided (drops only), since
a bonus/rights share issue mechanically dilutes price DOWN, never explains a price rising sharply
(an upward spike on high volume, like FNEL's real 04-08 breakout, is exactly the kind of genuine
signal this whole study exists to find, and must never be trimmed away as a data artifact). The
detector was verified (via an assertion in `analyze_premove.py`'s `main()`) to still find exactly
FNEL's known 2026-02-02 cliff and nothing else for that symbol. It found zero qualifying cliffs
for BNL -- BNL's mismatch with the user's reference prices is NOT explained by an unadjusted
corporate action; see its section.

---

"""

REPRO = f"""## Reproducibility

- Raw fetched data: three batched GitHub Actions runs this round (log-line truncation on the
  combined 12-symbol payload forced the split) --
  [33762455347](https://github.com/imranrazabozdar/PSX-INTELLIGENCE-NEW-2026/actions/runs/33762455347)
  (AICL,SHFA,THCCL,FNEL,MDTL,FPJM),
  [33762462806](https://github.com/imranrazabozdar/PSX-INTELLIGENCE-NEW-2026/actions/runs/33762462806)
  (DSIL,SYM,PREMA,JSBL,ILP), and
  [33762471001](https://github.com/imranrazabozdar/PSX-INTELLIGENCE-NEW-2026/actions/runs/33762471001)
  (BNL alone, given its wide window) -- all triggered from `analysis/fetch_premove_data.py`,
  merged and saved as `analysis/premove_data_raw.json`.
- Indicator computation (including the new MFI/OBV/A-D-Line/ATR/VWAP/Ichimoku layer), pattern
  scan, general price-cliff detection/trim, and first-occurrence tracking:
  `analysis/analyze_premove.py` (unit-tested against synthetic OHLC before running on real data,
  including a dedicated test that an upward volume spike is never flagged as a price cliff), reads
  `premove_data_raw.json` and writes `analysis/premove_analysis.json`.
- Markdown table / "what fired" narrative / flow-divergence / cross-stock table generation:
  `analysis/gen_report_v2.py`, assembled into this file by `analysis/build_full_report.py` --
  every number in the tables above is generated programmatically from `premove_analysis.json`,
  never hand-typed. Verified the full fetch -> analyze -> render pipeline reproduces
  byte-identical `premove_analysis.json` output on re-run (diff on sorted `json.dumps()` output).
- To add a 13th+ entry to this dataset: add an entry to `TARGETS` in `fetch_premove_data.py` and a
  `MOVE_START` entry in `analyze_premove.py`, re-run the `Pre-move study data fetch (manual,
  one-off)` GitHub Actions workflow (use the `symbols` input to batch large additions), save its
  JSON output over `premove_data_raw.json` (merging with existing symbols if fetched in batches),
  then re-run `analyze_premove.py` and `build_full_report.py`.
"""

sections = [METHOD_NOTE, AICL, SHFA, THCCL, FNEL, MDTL, FPJM, DSIL, SYM, PREMA, JSBL, ILP,
            BNL_MISMATCH, CROSS_STOCK, REPRO]
full = ("\n---\n\n".join(s.rstrip() for s in sections)) + "\n"

OUT.write_text(full)
print(f"Wrote {len(full):,} chars to {OUT}")
