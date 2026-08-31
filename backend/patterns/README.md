# AdvancedPatternEngine — Inverse H&S / Eve & Eve Double Bottom

`backend/advanced_pattern_engine.py` (+ `backend/pivots.py`) detects Inverse
Head & Shoulders and Eve & Eve Double Bottom patterns on PSX daily OHLCV
data. This README documents every tunable parameter and how to read its
output. **Every default below is a starting guess requiring PSX
calibration — none are researched constants.** Nothing in the engine's
code, comments, or output claims a win rate; see part (b) before trusting
any percentage this engine reports.

## (a) Constructor parameters

All parameters live on `AdvancedPatternConfig` (`backend/advanced_pattern_engine.py`),
passed to `AdvancedPatternEngine(config=...)`.

**Target changed in Calibration Round 2 (see `CALIBRATION_LOG.md`):** the full
1.0× measured move (`neckline + pattern_height`) was never reached once across
139 signals in a 5-year PSX backtest — `target_2_rate` was 0.0 in every
grouping. `target_measured` (what the dashboard/adapter shows as "Target 2")
now means **0.75×** pattern_height instead, and `risk_reward_measured` (the
gate `min_risk_reward_measured` checks) is computed against that reachable
0.75× target. The old 1.0× value is still computed and returned as
`target_full_measured` ("target_3"), for reference only — it is never used
in any gate or scoring component. `target_partial` ("target_1", 0.5×) is
unchanged.

| Parameter | Default | Valid range | When to tune |
|---|---|---|---|
| `k` | 5 | 2–15 (int) | Fractal pivot window (bars either side). Raise for smoother, less noisy pivots on liquid large-caps; lower to catch faster swings on volatile names — but lower values increase noise-matching risk. |
| `min_swing_pct` | 3.0 | 0.5–10.0 (%) | Minimum amplitude a pivot must move from the preceding opposite pivot. Raise if the engine is matching noise on thin small-caps; lower if it's missing real swings on very high-priced, low-volatility names (where 3% is a large move). |
| `atr_multiplier` | 1.5 | 0.5–4.0 | Multiplies ATR14/close to form the amplitude floor alongside `min_swing_pct` (the engine uses whichever is larger). Raise on volatile counters so pivot detection scales with the stock's own volatility, not a flat %. |
| `min_history_sessions` | 200 | 100–500 (int) | Minimum trading sessions before a symbol is scanned at all. Lower only if you accept patterns forming on a shorter history than one full year; not recommended below ~150. |
| `min_traded_sessions_ratio` | 0.90 | 0.5–1.0 | Fraction of sessions that must have `volume > 0`. Lower to include more PSX small-caps that trade less frequently; raise to restrict to genuinely liquid names only. |
| `min_turnover_pkr` | 5,000,000 | 500,000–50,000,000 (PKR) | Median 20-day turnover floor. This is the single most PSX-specific number in the engine — PSX's liquidity profile is nothing like US equities Bulkowski's research was based on. Recalibrate against your actual tradeable universe first. |
| `unadjusted_gap_pct` | 15.0 | 8.0–30.0 (%) | Single-bar gap, with no matching volume spike, flagged as a likely unadjusted corporate action. Lower to catch more suspected bad data (at the cost of false positives on genuine large PSX daily moves, which are common given circuit breakers can cap moves at exactly 10% for days in a row). |
| `prior_decline_pct` | 10.0 | 5.0–25.0 (%) | Minimum decline from the pre-pattern high required before either pattern is considered. **Recalibrate first** — see PSX calibration checklist below. |
| `prior_decline_min_sessions` | 20 | 10–30 (int) | Lower bound of the lookback window used to find the pre-pattern high. |
| `prior_decline_max_sessions` | 40 | 30–80 (int) | Upper bound of that same lookback window. |
| `ihs_head_discount_pct` | 2.0 | 1.0–8.0 (%) | Hard filter: head must be at least this far below both shoulders. Raise to demand a more pronounced head (fewer, higher-conviction signals). |
| `ihs_shoulder_symmetry_max_pct` | 5.0 | 2.0–15.0 (%) | Hard filter: max allowed price difference between the two shoulders. Raise to allow lopsided real-world patterns through; lower to demand textbook symmetry. |
| `ihs_min_span` / `ihs_max_span` | 25 / 150 | 20–250 (int, sessions) | Total T1→T3 span bounds. Widen `ihs_max_span` for patterns that form over many months; narrow `ihs_min_span` to catch faster reversals. **Recalibrated on PSX 2021-2026 data on 2026-08-29: `ihs_min_span` 40→25** — a full-universe scan showed a valid-looking IHS completing in 28 sessions, rejected by the US-equity-derived default of 40; PSX patterns appear to form faster (smaller float, more concentrated ownership, faster institutional decision cycles). `ihs_max_span` left untouched. |
| `neckline_mode` | `"horizontal_max"` | `"horizontal_max"` \| `"sloped"` | Both are always computed and stored regardless of this setting; it only selects which one gates the breakout. Switch to `"sloped"` if horizontal necklines are triggering breakouts too late on trending necklines. |
| `breakout_vol_mult` | 1.5 | 1.1–3.0 | Minimum breakout-bar volume, as a multiple of the 20-session average (locked bars excluded). Lower cautiously — this is a primary signal-quality gate; the same value gates both patterns per spec. |
| `confirmation_window` | 30 | 10–90 (int, sessions) | Sessions allowed for a qualifying breakout after the last pivot confirms, before the pattern is logged `expired`. Widen if you're seeing a high expiry rate for patterns that look otherwise sound. |
| `bottom_tolerance_pct` | 6.0 | 1.0–8.0 (%) | Max allowed price difference between B1 and B2. Note this directly controls how achievable `risk_reward_measured` is for double bottoms — see `atr_stop_mult` below and part (c). **Recalibrated on PSX 2021-2026 data on 2026-08-29: 3.0→6.0** — a full-universe scan showed a legitimate-looking double bottom at 12.62% misalignment, rejected by the US-equity-derived default of 3.0%; PSX stocks appear to have wider spreads, thinner liquidity, and more volatile retest behaviour. Will tighten again if signal quality degrades. |
| `min_peak_rise_pct` | 8.0 | 4.0–20.0 (%) | Minimum rise from the higher of B1/B2 to the intermediate peak PK, required to call it a genuine peak rather than a flat base. |
| `db_min_spacing` / `db_max_spacing` | 15 / 60 | 5–120 (int, sessions) | B1→B2 spacing bounds, in trading sessions (never calendar days). |
| `flat_band_pct` | 3.0 | 1.0–8.0 (%) | Eve/Adam shape test: band around a trough's price, within which nearby lows count toward "flatness". |
| `min_flat_bars` | 3 | 2–8 (int) | Minimum bars inside `flat_band_pct` required for the flatness component of the Eve test. |
| `min_trough_width` | 7 | 4–20 (int, sessions) | Minimum sessions between the swing highs bracketing a trough, for the width component of the Eve test. |
| `max_vness` | 1.2 | 0.3–3.0 | Depth-%/width ratio ceiling for the Eve test — lower is rounder/wider. **Explicitly called out in the original spec as an unresearched starting guess** — tune this one first among the Eve/Adam parameters once you have real PSX base-rate data (§5.3). |
| `min_risk_reward_measured` | 1.0 | 0.5–2.0 | Reject gate on `risk_reward_measured`, which as of Round 2 is computed against `target_measured` = neckline + **0.75×** pattern_height (not the full 1.0× measured move — see `target_measured`/`target_full_measured` below). |
| `atr_stop_mult` | 2.0 | 1.5–3.0 | **Replaced `ihs_atr_mult`/`db_atr_mult` in Round 3 (Change 2); flat percentage cap retired in Round 4.** Stop distance = `entry_price * atr_ratio_bounded * atr_stop_mult`, floored at `pattern_low`, where `atr_ratio_bounded` is `atr14/entry_price` clamped to `[min_atr_ratio, max_atr_ratio]` (see those two rows below). Default 2.0. When to tune: raise toward 3.0 for a looser stop across the board; lower toward 1.5 for a tighter one. |
| `min_atr_ratio` | 0.015 (1.5%) | 0.005–0.03 | **Added in Round 4, STOP FORMULA ITERATION 3.** Floor on `atr14/entry_price` before multiplying by `atr_stop_mult` — prevents an unusually low-ATR stock from producing a stop tighter than the pattern's real volatility supports. At the default `atr_stop_mult=2.0`, this floors the stop distance at 3.0% of entry. When to tune: raise if low-ATR names are getting stopped out on ordinary noise; lower if stops feel systematically too wide on quiet stocks. |
| `max_atr_ratio` | 0.035 (3.5%) | 0.02–0.06 | **Added in Round 4, STOP FORMULA ITERATION 3, to fix a real problem found in the pure-ATR run (no bound at all): stop distances up to 12.36% of entry and a worse `avg_loss_when_stopped` (-8.25%) on high-ATR names.** Ceiling on `atr14/entry_price` before multiplying by `atr_stop_mult` — caps the stop distance at 7.0% of entry by default. Chosen to sit above the ~6-7% stop distance observed on the 16 signals that the earlier flat-cap iterations had been cutting short (so they stay unclamped) while still well below the 12%+ tail this is meant to cut off. **Important:** an earlier version of this bound was specified as `clip(atr14*atr_stop_mult, atr14*min_atr_mult, atr14*max_atr_mult)` — i.e. bounding the already-ATR-scaled stop distance by further multiples of the *same* atr14. That is a mathematical no-op (`clip(k·x, a·x, b·x) = k·x` whenever `a ≤ k ≤ b`, for any `x`) and would have reproduced the pure-ATR run exactly. `min_atr_ratio`/`max_atr_ratio` bound the ATR/price *ratio itself*, independent of the individual stock's raw ATR value, so the clamp can actually bind. When to tune: raise if genuinely high-volatility PSX names are being clamped below their real risk; lower if the 12%+ tail isn't fully gone after backtesting. |
| `throwback_risk_pct` | 5.0 | 2.0–15.0 (%) | Entry-above-neckline threshold for flagging `throwback_risk`. Informational only — never gates a signal. |

## (b) What Bulkowski's percentages actually mean

Verbatim from the engine's own docstring — repeated here because dashboard
readers won't necessarily open the source file:

> Bulkowski reports an ~83% breakout-direction rate for inverse
> head-and-shoulders and ~88% for Eve & Eve double bottoms. These are
> **not win rates**. They measure how often price continued in the
> breakout direction to an ultimate extreme, in US equities, in bull
> markets, with no stop loss, commission, or slippage. The proportion of
> trades reaching a measured-move target before stopping out is
> substantially lower. None of these figures have been validated on PSX.
> Treat them as a prior to be tested, not as this engine's expected
> performance.

Nothing in this codebase computes or displays "83%" or "88%" as a
performance figure. If you ever see either number presented as a win rate
anywhere downstream of this engine (a dashboard tile, a report, a Slack
message), that is a misrepresentation introduced elsewhere, not something
this engine emits.

## (c) PSX calibration checklist

In priority order — these are the parameters most likely to need
adjustment once you have real PSX outcome data, and why:

1. **`prior_decline_pct`** (default 10.0%) — Bulkowski's underlying
   research is US equities in bull markets; PSX's volatility regime,
   circuit-breaker-capped daily moves, and macro-driven multi-week swings
   are structurally different. This threshold decides whether a pattern
   is even considered at all, so a miscalibration here silently
   suppresses or floods every downstream signal.
2. **`min_turnover_pkr`** (default 5,000,000 PKR) — PSX's liquidity
   distribution is nothing like the US large/mid-cap universe this
   pattern research assumes. Too low admits untradeable names; too high
   silently excludes a large share of the real PSX-listed universe.
3. **`atr_stop_mult`** (default 2.0) — directly controls how often
   `risk_reward_measured >= 1.0` is achievable, and how far price can move
   against a position before stopping out. Shared by both pattern types
   since Round 3 (Change 2) — verify with real breakout data rather than
   synthetic fixtures once available.
4. **Pivot `k`** (default 5) **and `min_swing_pct`** (default 3.0%) —
   these decide what counts as a "real" swing at all, upstream of every
   other rule. Get these wrong and every downstream percentage is
   computed on the wrong pivots, regardless of how well-tuned everything
   else is.

## (d) Reading the rejection log

`ScanResult.rejected` and `ScanResult.expired` are the primary tool for
tuning thresholds — every discarded pattern is logged with a machine-
readable reason, never silently dropped. Symbol-level pre-flight
rejections (`pattern_type: None`) mean the symbol was never scanned at
all; pattern-level rejections mean pivots were found but a specific rule
failed.

**Symbol-level (§1 pre-flight):**

| Reason | Meaning | If you see too many |
|---|---|---|
| `insufficient_history` | Fewer than `min_history_sessions` daily bars. | Expected for recent IPOs/listings — not a threshold problem unless it's hitting established names, which would suggest a data-pipeline gap. |
| `unsorted_dates` / `duplicate_dates` | Defensive checks (input is already sorted/deduped before this runs) — should never fire in practice. | Investigate your upstream OHLCV feed immediately; this indicates a real data-integrity bug, not a threshold to tune. |
| `too_illiquid` | Fewer than `min_traded_sessions_ratio` of sessions had any volume. | Common on PSX small-caps by nature. Lower the ratio if you deliberately want to include thinly-traded names; otherwise this is working as intended. |
| `untradeable_turnover` | Median 20-day turnover below `min_turnover_pkr`. | If this is excluding names you actually consider tradeable, lower `min_turnover_pkr` — this is the #1 calibration target (see part (c)). |
| `unadjusted_corporate_action_suspected` | A large single-bar gap with no matching volume spike — looks like an un-adjusted split/bonus, not a real move. | If firing on names you know ARE properly adjusted, raise `unadjusted_gap_pct` — PSX's circuit breakers make large gaps on high volume both common and legitimate. |

**Pattern-level (both types unless noted):**

| Reason | Meaning | If you see too many |
|---|---|---|
| `span_out_of_range` (IHS) / `spacing_out_of_range` (DB) | T1→T3 (or B1→B2) took too few or too many sessions. | Widen the max bound if genuine slower-forming patterns are being cut off; check for a k/amplitude problem if the min bound is firing often (may mean pivots are too close together, i.e. noise). |
| `head_not_below_shoulders` (IHS) | Head isn't at least `ihs_head_discount_pct` below both shoulders. | Firing constantly suggests either your pivot detection is too loose (matching near-flat "heads") or the threshold itself is too strict for PSX's typical pattern shapes. |
| `shoulders_not_symmetric` (IHS) | Shoulders differ by more than `ihs_shoulder_symmetry_max_pct`. | Raise the threshold if PSX patterns are structurally more lopsided than textbook examples — plausible given lower liquidity. |
| `bottoms_not_aligned` (DB) | B1/B2 differ by more than `bottom_tolerance_pct`. | Raise cautiously — this also controls how achievable `risk_reward_measured` is downstream (part (c), item 3). |
| `peak_not_prominent` (DB) | Intermediate peak's rise is below `min_peak_rise_pct`. | Lower if PSX double bottoms tend to have shallower intervening rallies than the textbook 8% assumption. |
| `no_prior_downtrend` (both) | Failed the §3 prior-trend prerequisite. | See part (c), item 1 — this is the highest-leverage threshold to recalibrate if you're seeing very few signals overall. |
| `risk_reward_measured_below_minimum` (both) | The pattern is geometrically valid but the breakout entry left too little reward relative to the stop. | If this fires on most otherwise-valid patterns, check `atr_stop_mult` before touching `min_risk_reward_measured` itself (part (c), item 3) — a bad multiplier can make this gate nearly unreachable regardless of pattern quality. |

**Not a rejection, but related:** a pattern in `ScanResult.expired` passed
every geometric and trend filter but never got a qualifying breakout
(price above the neckline, on `breakout_vol_mult`× volume) within
`confirmation_window` sessions. A high expiry rate suggests either
`breakout_vol_mult` is too strict for PSX's typical breakout volume
profile, or `confirmation_window` is too short for how long PSX patterns
actually take to resolve.

## (e) Cup & Handle parameters (recalibrated)

`CupHandleEngine` (`backend/cup_handle_engine.py`) is a separate module
built on the same architecture as this one (shared pivot detection,
pre-flight, breakout scan, bounded-ATR stop). Full documentation lives in
that module's docstring; this table covers only the three parameters
recalibrated from their original US-equity-derived defaults after a
full 443-symbol PSX rejection-funnel diagnostic — see
`CALIBRATION_LOG.md`'s "CUP & HANDLE BUILD NOTES" / "PARAMETER
RECALIBRATION" entries for the full evidence behind each change.

| Parameter | Default | Valid range | Notes |
|---|---|---|---|
| `cup_max_span` | 250 | 150–400 (int, sessions) | **Recalibrated from US-equity default to PSX on 2026-08-29 — see CALIBRATION_LOG.md.** Was 150. A rejection-funnel diagnostic found 69.4% of assembled P1/T1/P2 triples (4,489 of 6,467) died at this single gate — by far the largest rejection stage. `cup_min_span=25` had zero rejections, so only the ceiling was binding. PSX cups form over longer periods than US equities (thinner liquidity, slower institutional accumulation); 250 sessions ≈ 1 calendar year. |
| `cup_max_depth_pct` | 65.0 | 40.0–80.0 (%) | **Recalibrated from US-equity default to PSX on 2026-08-29 — see CALIBRATION_LOG.md.** Was 33.0 (the Bulkowski/O'Neil US-equity benchmark). Median `cup_depth_pct_of_rise` for triples reaching this check was 56.1% — almost twice the old cutoff. PSX stocks have structurally deeper corrections (thinner liquidity, higher volatility); 65% admits the typical PSX cup while still excluding >65% collapses that look like pattern failure rather than accumulation. |
| `handle_max_depth_pct` | 30.0 | 15.0–40.0 (%) | **Recalibrated from US-equity default to PSX on 2026-08-29 — see CALIBRATION_LOG.md.** Was 15.0. 100% of the 35 triples that cleared every cup-stage filter (under the already-loosened `cup_max_span`/`cup_max_depth_pct`) died at this single gate — zero signals were possible at 15% on PSX data. Same underlying cause as the cup recalibrations; 30% of cup height still excludes a handle that retraces the full cup. |

All three defaults above were explicitly flagged as unresearched
starting guesses when `CupHandleEngine` was first built. These are their
first PSX calibration values, derived from a rejection-funnel diagnostic
rather than a backtest (the engine has not yet produced a single signal
to backtest) — expect further tuning once real signals exist to
evaluate.
