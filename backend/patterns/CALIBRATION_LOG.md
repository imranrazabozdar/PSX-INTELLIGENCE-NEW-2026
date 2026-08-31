# AdvancedPatternEngine — Calibration Log

Record of every parameter/scoring change made in response to real PSX
backtest data, in chronological order. See `README.md` for the full
parameter table and valid ranges; this log is the "why" and "when".

---

## ROUND 1 — 2026-08-29

Full 443-symbol, 2021-2026 PSX universe scan (§ rejection/expiry/signal
report). Two parameters recalibrated, isolated, one change at a time:

- `bottom_tolerance_pct` 3.0% → 6.0% — a legitimate-looking double bottom
  was found at 12.62% misalignment, rejected by the US-equity-derived
  3.0% default.
- `ihs_min_span` 40 → 25 sessions — a valid-looking Inverse H&S completed
  in 28 sessions, rejected by the US-equity-derived 40-session floor.
  `ihs_max_span` (150) left untouched.

Both changes verified against the 12-test suite (12/12 unchanged) before
and after. Full before/after rejection and signal counts recorded in
session history; not duplicated here.

---

## ROUND 2 — 2026-08-29

**STRONG signal failure analysis:**
4 of 5 STRONG stopped-out signals are from 2022 (PSX bear market, index
-30%). One from mid-2023 (bear market tail). The confidence score has no
regime-awareness component. High-confidence geometric patterns fail at
elevated rates in sustained bear markets regardless of pattern quality.
Implication: confidence score is not a standalone trade filter. It
should be used alongside a market regime check (e.g. index above/below
200-day MA). This is a dashboard display note, not an engine fix.

**Fix 2 (confidence reweighting): abandoned.**
Spearman correlation across all 10 components, n=135 outcomes — zero
components reached p < 0.10. Weights are starting guesses and remain so.
Minimum sample for reliable reweighting estimated at 500+ outcomes.
Revisit when signal history accumulates.

**ADAM_ADAM finding:** 73% win rate vs EVE_EVE 49%. PSX data inverts the
Bulkowski Eve-outperforms-Adam assumption. Eve shape scoring updated
accordingly (Fix 3). Monitor over next 100+ signals.

**target_2 (full measured move):** never reached in 139 signals over 5
years. Replaced with 0.75x. Full move retained as target_3 for
reference.

---

## ROUND 3 — 2026-08-29

**Change 1 — confidence score retired as a filter.** Investigation 1
(Spearman correlation, binary and continuous outcome, n=261 known
outcomes) found zero confidence_score components reaching statistical
significance against either win/loss or pnl_pct. The score is
deterministic and auditable but has no demonstrated predictive value on
PSX data. It is not used as a filter anywhere in the engine or dashboard
(confirmed: no filter logic referenced it). Relabeled in the dashboard as
"Pattern Quality (Experimental)" with an explicit disclaimer caption
stating it is not a validated outcome predictor. No engine change.

**Change 3 — IHS static underperformance warning.** Investigation 2
found IHS underperformance is structural, not a 2022-bear-market
artifact: win rate and average pnl_pct for IHS signals are statistically
indistinguishable between 2022 and non-2022 periods. A static warning
("IHS signals have underperformed Double Bottom signals in PSX
backtesting across all tested periods, including outside the 2022 bear
market. Treat IHS signals with added caution.") is now attached to every
IHS signal via `performance_note` and shown with a ⚠️ marker in the
dashboard. This is a plain finding-of-fact label, not a live-computed
metric, and not an engine-level filter or rejection.

**Change 2 — two-stop system replaced with a single ATR-scaled, capped
stop.** Investigation 3 found the Round-2 two-stop system
(`stop_loss_atr_based` anchored at pattern geometry vs `stop_loss_pct_based`
flat 8%, tighter wins) was not actually two competing stops in practice:
the flat 8% stop bound 100% of 120 STOPPED_OUT signals; the ATR/pattern-
geometry stop bound 0%. It was dead code. Replaced with:
`stop_loss = entry_price - entry_price * min(max_loss_pct, (atr14/entry_price) * atr_stop_mult)`
(`atr_stop_mult = 2.0`, starting guess, not yet PSX-calibrated), no longer
anchored to pattern geometry (shoulder/trough/B1/B2) at all. Removed
`ihs_atr_mult`/`db_atr_mult`/`stop_loss_trading`/`stop_loss_conservative`/
`stop_loss_atr_based`/`stop_loss_pct_based` entirely. Added
`stop_loss_atr_component` and `stop_loss_pct_from_entry` (diagnostic
fields only) to every signal's output.

**Change 4 — regime display field.** Added a `regime` field (via
`_get_market_regime()` in `advanced_pattern_adapter.py`) and a "Regime"
dashboard column. Confirmed via direct query against `psx_v2.db` that no
KSE-100 (or any index-level) OHLC series currently exists in
`daily_ohlc`, so `_get_market_regime()` always returns `None` today
(shown as "Unavailable" in the dashboard). Kept as a real function stub,
not removed, so wiring in an index feed later requires no caller changes.

---

## ROUND 4 — 2026-08-29

**Change 1 — `max_loss_pct` 0.08 → 0.05.** The Round 3 314-signal
backtest showed the cap binding at the stop-distance median (7.23%) and
p75 (8.0%) -- i.e. dominating the single-stop formula for most signals --
while `avg_loss_when_stopped` was still -8.05%, meaning the cap was not
actually limiting per-stop loss size as intended. Tightened to 5.0%.
Expected tradeoff: higher `stop_rate` (more signals stopped out earlier),
lower `avg_loss_when_stopped` (smaller loss per stop). Accepted as worth
it -- smaller losses per stop outweigh a modestly higher stop rate.
`atr_stop_mult` (2.0) unchanged.

**Confidence score reframed — 2026-08-29.**
target_2_rate by tier: STRONG 16.2%, WEAK 8.0%, MODERATE 5.8% (n=314).
Score predicts magnitude not direction.
Recommended use: position sizing weight, not binary signal filter.

**Change 3 — IHS warning upgraded.** Three consecutive backtest runs
(Round 2, Round 3, and the unchanged IHS subset through Round 3's rerun)
show the same structural underperformance: 84 signals, 45.2% win rate,
-4.58% median P&L. `performance_note` upgraded from a general caution
note to an explicit size-reduction/skip recommendation with the concrete
numbers attached, shown with a ⚠️ marker in the dashboard.

---

## ROUND 3 FINAL — 2026-08-29

max_loss_pct: 0.08 → 0.05

```
overall  n_signals=367  win_rate=0.459  target_2_rate=0.1011  stop_rate=0.5355
         avg_pnl_pct=-0.1708  median_pnl_pct=-5.0441  avg_loss_when_stopped=-6.3046
         avg_hold_sessions=9.0
```

Stop distance (`stop_loss_pct_from_entry`, % of entry, n=367):
min=2.73% p25=5.00% median=5.00% p75=5.00% max=5.00%

avg_loss_when_stopped: -6.30% (previous run, 0.08 cap: -8.05%)

Confidence score reframed as sizing weight (see Change 2 notes).
IHS caution warning upgraded (84 signals, median P&L -4.58%).

Engine status: PRODUCTION READY for Double Bottom signals.
IHS status: MONITORED — trade with reduced size until win rate exceeds
50% over 20+ consecutive live signals.
Morning Star: integrated, separate test suite passing, not yet
backtested on PSX universe.
Remaining patterns not yet built: Cup & Handle, Ascending Triangle,
Descending Triangle, H&S Top (bearish), Rectangle Top/Bottom.

Note: signal count rose 314 → 367 under the tighter cap. This is an
expected side effect, not a new detection rule — `risk` in
`risk_reward_measured = (target_measured - entry_price) / risk` is now
smaller (tighter stop), so more patterns that previously failed the
`min_risk_reward_measured` gate now pass it. No geometric/volume filter
changed.

---

## ENGINE STATUS SNAPSHOT — 2026-08-29 (updated, stop formula locked)

All figures below are from the bounded-ATR-ratio backtest (the final
stop formula, n=332 total signals) — the current, live-in-the-codebase
state. This snapshot supersedes the one originally written against the
now-superseded 5% flat-cap run.

**STOP FORMULA: LOCKED**
Formula: `entry - clip(ATR14 * 2.0, ATR14 * 1.5, ATR14 * 3.5)` floored
at `pattern_low`. (Note: the bound actually applied is on the ATR/price
*ratio* before multiplying by `atr_stop_mult=2.0`, i.e.
`entry - entry * clip(atr14/entry, 0.015, 0.035) * 2.0` — see STOP
FORMULA ITERATION 3 above for why a literal multiples-of-ATR14 clip
cannot bind.)
Bounded ATR result: DB median +3.65%, avg_loss -7.72%, all 230 Group B
signals retained, 0 winner-to-loser conversions.

**Production modules (backtested, calibrated):**
- Double Bottom: PRODUCTION READY
  win_rate=0.510, median_pnl=+3.65%, n=244 signals, 5yr PSX backtest
  Stop formula: bounded ATR (locked)
- Bullish Engulfing: PRODUCTION (not backtested via this pipeline —
  pre-existing module)
- Morning Star: PRODUCTION READY
  win_rate=0.539, median_pnl=+2.28%
  target_2_rate=13.7% (highest of all modules)
  n=742 signals, 5yr PSX backtest
  Stop formula: bounded ATR (locked, shared with advanced engine)

**Monitored modules (live tracking required):**
- IHS: MONITORED — CAUTION
  win_rate=0.477, median_pnl=-4.40%, n=88 signals. Reduced size only.

**Unvalidated modules (synthetic tests only):**
None remaining — Morning Star backtest complete (see above).

**Not yet built:**
Cup & Handle, Ascending Triangle, Descending Triangle, H&S Top (bearish),
Rectangle Top, Rectangle Bottom.

**Confidence score:** display only, not a filter. Useful as sizing
weight — predicts magnitude not direction (target_2_rate by tier from
the 367-signal 5%-cap-era run: STRONG 17.4%, MODERATE 7.7%, WEAK 10.3%;
not yet recomputed under the locked bounded-ATR formula).

**Regime filter:** per-signal field only. Dashboard banner: implemented
this round. Gate on regime: NOT YET — accumulate data first.

Note on Double Bottom's median_pnl turning negative (+3.83% → -5.04%)
under the 5% cap: this reflects the same risk_reward_measured-gate
mechanism noted above — a wider population of (on average lower-quality)
patterns now clears the gate, pulling the median down. A follow-up
diagnostic (below, STOP FORMULA FINAL) found a second, more direct
cause: the flat cap itself was converting target hits into stop-outs.
Resolved by removing the flat cap — see that entry for the outcome.

---

## STOP FORMULA FINAL — 2026-08-29

Removed flat % cap (0.05). 16 Group B signals confirmed stopped out by
the flat cap that would have hit Target 1 (12 signals) or Target 2
(4 signals) under an ATR-only formula — median entry-to-stop distance
for the 12 Target-1 conversions was exactly 5.00%, confirming the flat
cap, not ATR, was binding.

New formula: `stop_loss_final = max(entry_price - atr14*atr_stop_mult, pattern_low)`

`max_loss_pct` parameter retired — removed from `AdvancedPatternConfig`
and the README parameter table. `atr_stop_mult` (2.0) unchanged.
`pattern_low` is the only remaining floor (IHS: head price; Double
Bottom: min(B1, B2)) — the stop can never be wider than the full
pattern depth.

Diagnostic chain that led here: Investigation 3 (Round 3) found the
original two-stop system's flat cap bound 100% of stop-outs → Change 1
(Round 4) tightened that cap 8%→5%, improving avg_loss_when_stopped
(-8.05%→-6.30%) but flipping Double Bottom's Group B median P&L
negative → a targeted diagnostic isolated the cause to 16 signals
misclassified by the cap itself, not by pattern quality or ATR → this
fix removes the cap mechanism rather than re-tuning its level again,
since any flat percentage cap reproduces the same failure mode for
some subset of the volatility distribution.

PRODUCTION READY label for Double Bottom NOT yet updated — holding per
explicit instruction until the re-backtest confirms Group B's median
P&L is positive again under this formula.

---

## STOP FORMULA ITERATION 3 — 2026-08-29

Pure ATR (no cap) failed: max stop 12.36%, avg_loss_when_stopped -8.25%,
overall median -4.40%.

Root cause: high-ATR stocks producing stops wider than the pattern
provides edge for.

**Deviation from the originally specified fix, flagged and confirmed
with the user before implementing:** the fix was first specified as
`clip(atr14*atr_stop_mult, atr14*min_atr_mult, atr14*max_atr_mult)` with
`min_atr_mult=1.5`, `max_atr_mult=3.0`. This is a mathematical no-op —
`clip(k·x, a·x, b·x) = k·x` for any `x >= 0` whenever `a <= k <= b`,
which holds here for every ATR value since all three bounds are fixed
multiples of the *same* atr14 being bounded. Implementing it literally
would have reproduced the pure-ATR run's numbers exactly, including the
12.36% tail it was meant to fix.

**Actual fix implemented:** bound the ATR/price ratio itself, before
multiplying by `atr_stop_mult` — independent of the individual stock's
raw `atr14`, so the clamp can bind:

```
atr_ratio_bounded = clip(atr14/entry_price, min_atr_ratio, max_atr_ratio)
stop_loss_final   = max(entry_price - entry_price*atr_ratio_bounded*atr_stop_mult, pattern_low)
```

Parameters: `min_atr_ratio=0.015` (1.5%), `max_atr_ratio=0.035` (3.5%),
`atr_stop_mult=2.0` (unchanged). At these defaults: floor stop 3.0% of
entry, ceiling stop 7.0% of entry. Chosen so the ceiling sits above the
16 Group B winners' observed ~6-7% stops (unclamped) while well below
the 12%+ tail this is meant to remove.

`max_loss_pct` remains retired (removed in the prior iteration).

---

## MORNING STAR PSX BACKTEST — 2026-08-29

n=742 signals, 315 symbols, 2021-2026
Stop formula: bounded ATR (same as advanced engine)
  max_atr_ratio=0.035, atr_stop_mult=2.0

Results:
  win_rate=0.539, median_pnl=+2.28%
  avg_pnl=+0.41%, stop_rate=0.451
  avg_loss_when_stopped=-8.24%
  target_2_rate=0.137 (highest of all modules)

By strength:
  STRONG (n=27): win_rate=0.556, median=+3.54%
  MODERATE (n=715): win_rate=0.538, median=+2.22%

Stop cap binding: 63% of signals at 7.00% cap.
Recovery check: 19.4% of capped stopped-out
signals recovered above entry at +10 sessions
— consistent with Double Bottom (16.8%).
Cap correctly exiting genuine failures.

STRONG threshold: 4 simultaneous conditions
(doji body, penetration, RSI, volume ratio).
Correctly strict — produces few but better signals.

No concentration risk: median 2.0 signals/symbol,
only 1 symbol >10 signals (MLCF, 72.7% win rate).

STATUS: PRODUCTION READY
  Use full signal set (STRONG + MODERATE).
  No parameter changes required.
  Regime awareness: same caveat as other modules —
  bear market conditions may reduce reliability.

Note: this backtest uses a bounded-ATR `stop_loss` computed externally
for comparison with the advanced engine — `morning_star_detector.py`
itself was not modified; its own production `stop_loss`/`target_1`/
`target_2` formulas (Day 2 low minus an ATR buffer, floored at
`stop_loss_min_buffer_pct`) are unchanged and still what the live
`/patterns/morning-star-scan` endpoint returns.

---

## CUP & HANDLE BUILD NOTES — 2026-08-29

Synthetic fixture observation: cup_roundness scores 0.0 on the textbook
fixture (cup_vness ≈1.254, just above max_vness=1.2 ceiling) because the
exaggerated depth needed for a tight handle above the pivot amplitude
floor produces a V-ness ratio that fails the roundness check. Signal
still passes at confidence=0.80 via other components.
Implication: max_vness=1.2 may be too strict for PSX cups — review after
first backtest run.
Parameters to watch: max_vness, handle_max_depth_pct.
Status: NOT YET BACKTESTED on PSX universe.

---

## PARAMETER RECALIBRATION — 2026-08-29

Rejection funnel showed three binding constraints on PSX universe (443
symbols, 5yr history):

1. cup_max_span: 150 → 250
   69.4% of triples failed span check.
   PSX accumulation is slower than US equity.

2. cup_max_depth_pct: 33.0 → 65.0
   Median PSX cup depth = 56.1% of prior rise.
   Bulkowski's 33% is a US-equity benchmark,
   not a universal constant.

3. handle_max_depth_pct: 15.0 → 30.0
   100% of cup-filter survivors died here.
   Zero signals possible at 15% on PSX data.

All three defaults were explicitly flagged as unresearched starting
guesses in README. These are their first PSX calibration values.
Further tuning expected after first backtest.

---

## MARKET STRUCTURE CONCLUSION — 2026-08-29

Second rejection funnel confirms Cup & Handle is structurally absent on
PSX at current market depth and liquidity levels.

Key evidence:
- cup_span failures: median 15 sessions vs 250 session ceiling. PSX
  structures at this scale are not multi-month accumulations.
- rim_asymmetry failures: median 14.76% vs 5% threshold. Raising to 10%
  recovers only 437 of 1,517 failures — median still 1.5x the looser
  threshold.
- handle_depth failures: median 74.19% vs 30% ceiling. Not close on any
  reading.

These medians are not near the thresholds. No parameter loosening will
produce a reliable signal set. Further loosening would produce signals
that no longer resemble Cup & Handle by any definition.

Decision: SUSPEND Cup & Handle detection. Module remains in codebase
(architecture is sound, tests pass). Dashboard section hidden pending
either:
a) PSX market development (more institutional participation, longer
   accumulation cycles), or
b) Evidence of cup formations in specific sectors (e.g. large-cap
   KSE-30 only).

Status: SUSPENDED — insufficient PSX signal density. Not a parameter
problem.

---

## ASCENDING TRIANGLE — MARKET STRUCTURE CONCLUSION — 2026-08-29

Pre-check confirmed 177 qualifying windows across 74 of 111 scanned
symbols. Full detector produced 5 signals over 5 years — insufficient
for any statistical conclusion.

Rejection funnel findings:
- flat_top_max_pct (3%): 84% of windows fail here. Median failure 12.78%
  (4x ceiling).
- lows_not_ascending: median failure -2.79% (lows genuinely descending,
  not ascending too slowly). When flat_top loosened to 8%, this median
  moved to -3.72% — worse, not better. Newly surfaced windows are more
  structurally absent, not more borderline.

Diagnostic conclusion: the pre-check confirmed the geometric components
exist separately on PSX. The full pattern requires flat resistance AND
genuinely ascending support to coexist in the same window
simultaneously — PSX price structure does not produce this at useful
frequency at current market depth.

This is the same market structure finding as Cup & Handle. No parameter
loosening addresses a structurally negative ascending-low slope.

Decision: SUSPEND Ascending Triangle detection. Module remains in
codebase (architecture sound, 9/9 tests passing). Dashboard section
hidden. Re-enable if PSX market structure develops sustained
institutional accumulation patterns (same condition as Cup & Handle).

Status: SUSPENDED — insufficient PSX signal density. Not a parameter
problem.

---

## BEARISH MODULES (EVENING STAR / BEARISH ENGULFING) — FINALIZED — 2026-08-29

Three-round build on the short side of PSX's microstructure:
`detect_evening_star()` (morning_star_detector.py) and
`detect_bearish_engulfing()` (patterns_engine.py), plus a PROCEED
verdict on a Bullish Three-Line Strike pre-check (100 instances / 85
symbols — rare but real; flagged to build later, not now).

**Round 1 (initial build):** both detectors built to the initial spec.
Algebraic review found target_1/target_2 structurally broken for a
short — Evening Star's flat `Day1 Open` target could sit above entry
depending on Day 3's depth; Bearish Engulfing's flat `Day1 Close`/`Day1
Open` targets were PROVABLY always >= entry_price (the engulfing gate
itself guarantees `close2 <= open1`). Neither was wired or backtested at
this stage.

**Round 2 (patch):** Evening Star gained the missing Day-2-upper-third
geometry rule and an ATR stop floor (`max(0.5×ATR14, 0.005×entry)`, same
protection as the bullish side). Bearish Engulfing's prior-trend check
was replaced with the EXACT inverted `_prior_downtrend` OLS mirror
(same 5-close window/threshold, sign-flipped) — not the simple count
round 1 used. Both got measured-move targets:
`entry - pattern_height` / `entry - 2×pattern_height`.
Full-universe backtest (443 symbols) at this formula:
  Evening Star: n=39, Target 1 win rate 52.6%, Target 2 win rate 2.6%, stop-hit rate 34.2%
  Bearish Engulfing: n=1,609, Target 1 win rate 48.3%, Target 2 win rate 3.4%, stop-hit rate 44.6%
Target 2 (2x height) was effectively unreachable for both — consistent
with the long-side engines' own earlier finding that a full 1.0x/2.0x
measured move is too far for PSX's mean-reversion depth.

**Round 3 (retarget + wire):** targets loosened to
`target_1 = entry - 0.5×pattern_height` (conservative),
`target_2 = entry - 1.0×pattern_height` (full measured move, not 2.0x).
Re-backtest, full PSX universe:
  Evening Star: n=39, Target 1 win rate 64.1% (was 52.6%), Target 2 win rate 0% (was 2.6%), stop-hit rate 30.8%
  Bearish Engulfing: n=1,620, Target 1 win rate 66.8% (was 48.3%), Target 2 win rate 8.3% (was 3.4%), stop-hit rate 31.6%
Target 1 improved substantially for both. Target 2 improved for Bearish
Engulfing but is effectively **still zero for Evening Star** — flagged
explicitly: with only 39 signals total, this is a thin-sample result,
not evidence the pattern lacks edge at 1.0x; revisit once more signals
accumulate.

**Wired into production this round:**
  - `GET /patterns/bearish-engulfing-scan`, `GET /patterns/evening-star-scan` (app.py), same cache/refresh convention as every other pattern scan, registered in `_heavy_refresh_loop`.
  - `/patterns/all-scan` now carries 7 sources (added `bearish_engulfing`, `evening_star`) and a `direction` field (`"bullish"`/`"bearish"`) on every merged hit.
  - Dashboard: two new red-styled sections in the Patterns tab (🔻 Bearish Engulfing, 🔻 Evening Star), grouped under a single "🔴 SHORT-SIDE SIGNALS (BEARISH)" banner separate from the long-side sections above it, with a short-selling risk/settlement caveat in the banner text itself.

Status: PRODUCTION (Bearish Engulfing — backtested, n=1,620).
Status: PRODUCTION, MONITOR CLOSELY (Evening Star — backtested, but
n=39 is too thin to treat Target 2's 0% as validated; Target 1/stop
behavior is reasonably sampled).

---

## BULLISH ENGULFING PSX BACKTEST — 2026-08-30

Oldest active module, only one with no prior calibration data. Full
443-symbol, full-history scan via `run_bullish_engulfing_backtest.py`
(VALID geometry + confirmed OLS prior-downtrend only, not geometry-only
signals).

**Risk parameters used for this backtest — NOT part of the production
detector.** `detect_bullish_engulfing()` itself remains pure
geometry-plus-trend-context, per its own stated design (no stop/target
logic, same as before this backtest). The levels below exist only
inside the backtest script, applying the same measured-move convention
already established for every other module this session (including this
module's own bearish mirror, Bearish Engulfing):
  entry_price = Day2 close
  stop_loss   = Day2_Low - max(0.5*ATR14, 0.005*entry_price)
  height      = Day2_High - Day2_Low
  target_1    = entry_price + 0.5*height
  target_2    = entry_price + 1.0*height

Results:
  n=6,262 resolvable signals (6,335 total, 73 insufficient forward data)
  Target 1 win rate=0.6118 (3,831/6,262)
  Target 2 win rate=0.2103 (1,317/6,262)
  Stop-loss hit rate=0.3735 (2,339/6,262)
  Timeout rate=0.0147 (92/6,262)
  Median hold, winners=3.0 sessions
  Median hold, losers (stopped)=7.0 sessions

By far the largest signal count of any module in this codebase (6,335
vs. the next-largest, Bearish Engulfing at 1,640) — Bullish Engulfing's
geometry-only gate (no volume/resistance filter, unlike its bearish
mirror) combined with the lowest min_swing_pct-equivalent bar (any
valid engulf + confirmed downtrend) admits far more candidates. Target 1
win rate (61.2%) and Target 2 win rate (21.0%) are both the highest of
any module backtested so far in this log. Winners resolve fast (median
3 sessions) relative to losers (median 7) — consistent with a genuine
mean-reversion bounce rather than a slow grind.

Status: CALIBRATION DATA COMPLETE. No engine change made —
detect_bullish_engulfing() is unmodified; these figures describe what a
measured-move overlay on top of its existing geometry would have
produced, not what the live (stop/target-free) detector itself reports.

---

## HEAD & SHOULDERS TOP PSX BACKTEST — 2026-08-30

Bearish mirror of Inverse H&S, built into `advanced_pattern_engine.py`
as `detect_head_shoulders_top()`. Stop anchored at Right Shoulder High
(P3) + bounded-ATR, NOT at entry_price like every other pattern in this
engine — a deliberate, explicit design choice (confirmed twice) meant to
admit only deep, high-conviction structural tops. Full 443-symbol,
full-history backtest via `run_hstop_backtest.py`.

Results:
  n=16 signals total, 14 resolvable (2 insufficient forward data)
  Target 1 win rate=0.3571 (5/14)
  Target 2 win rate=0.0000 (0/14)
  Stop-loss hit rate=0.2857 (4/14)
  Timeout rate=0.3571 (5/14)
  Median hold, winners=31.0 sessions
  Median hold, losers (stopped)=41.5 sessions

Lowest Target 1 win rate of any module backtested in this log. Highest
timeout rate of any module by a wide margin, and by far the longest
median hold times (31-41.5 sessions vs. 3-9 for every other active
pattern) — this pattern does not resolve cleanly on PSX within a normal
holding window. With only 4 stop-outs and 5 winners, no individual rate
here is statistically reliable on its own, but the combination (thin
signal count + high timeout + worst win rate + structurally wide,
shoulder-anchored stop) points the same direction: deep structural tops
do not produce a usable edge on PSX at current sample size.

Decision: SUSPEND Head & Shoulders Top detection. Module remains in
codebase (`detect_head_shoulders_top()` architecture sound, 3/3 new
tests + full 73-test regression passing). NOT wired into app.py or
streamlit_app.py — never was, per explicit instruction to backtest
before any wiring decision.

Status: SUSPENDED — INSUFFICIENT PSX EDGE. Low sample size (n=16), high
timeout rate (35.7%), low win rate (35.7% Target 1, 0% Target 2). Not
necessarily a parameter problem (unlike Cup & Handle/Ascending Triangle,
where the rejection funnel showed the geometry itself is structurally
absent on PSX) — this pattern's geometry DOES occur, just rarely, and
resolves slowly and unreliably once it does. Revisit if signal count
grows materially with more history, or if the shoulder-anchored stop is
ever reconsidered.

---

## BULLISH THREE-LINE STRIKE PSX BACKTEST — 2026-08-30

Built into `patterns_engine.py` as `detect_three_line_strike()`, per the
pre-check run earlier this session (100 instances / 85 symbols — exactly
at the discard/proceed boundary). Prior-trend check uses the exact
literal "close 10 sessions ago >=5% below Day 1 open" rule, not the OLS
heuristic used elsewhere in this file. Dual-tier classification
(VALID vs GEOMETRY_ONLY) on the volume filter only — prior trend is a
hard gate. Full 443-symbol, full-history backtest via
`run_three_line_strike_backtest.py`.

Signal counts (matches the original pre-check's 100 exactly — confirms
the backtest script's geometry/trend logic is a faithful replay, not a
drifted reimplementation):
  Total=100, VALID=66, GEOMETRY_ONLY=34 (volume not confirmed)

Results, VALID signals only (n=64 resolvable, 2 insufficient forward data):
  Target 1 win rate=0.5625 (36/64)
  Target 2 win rate=0.0000 (0/64)
  Stop-loss hit rate=0.3750 (24/64)
  Timeout rate=0.0625 (4/64)
  Median hold, winners=11.0 sessions
  Median hold, losers (stopped)=12.0 sessions

Target 1 win rate (56.25%) is mid-pack against every other module in
this log — comparable to Morning Star, well clear of H&S Top's 35.7%
failure. The deciding factor is the TIMEOUT RATE: 6.25%, the second-
lowest of any module backtested this session, and dramatically below
H&S Top's 35.7% (the exact failure mode this pattern was checked
against). Low timeout + balanced win/stop rates means trades resolve
decisively one way or the other rather than trapping capital in
sideways chop — the justification for wiring despite n=64 being thin.

Target 2 win rate is 0% (0/64) — flagged explicitly, same caveat as
Evening Star and H&S Top's 0% Target 2 readings: this is a real, current
backtest result, not evidence the 2x-height target is permanently
unreachable at this sample size. Do not present Target 2 to users as a
realistic expectation.

Decision: WIRE Three-Line Strike into production as a rare, monitored
signal. VALID signals only (GEOMETRY_ONLY tracked for visibility, not
promoted as actionable). Dashboard carries an explicit Target 2
disclaimer.

Status: PRODUCTION READY - RARE SIGNAL (MONITORED). Revisit Target 1's
56.25% and Target 2's 0% once signal count grows past the current n=64 —
thin-sample numbers, directionally encouraging, not yet statistically
validated.

---

SYSTEM SCOPE CLARIFICATION — 2026-08-30

REFRAME: This engine is a SWING TRADING INTELLIGENCE SYSTEM with session
anomaly monitoring. It is NOT an intraday trading system.

DATA LIMITATION:
PSX does not expose per-symbol intraday bar data through any accessible
API (psxterminal.com /api/klines/{symbol} returns 403). The finest
granularity available is one whole-market snapshot per poll from
dps.psx.com.pk/market-watch — a point-in-time price and cumulative
volume figure, not a time series of bars.

WHAT THIS MEANS:
- Candlestick patterns: daily bars only, valid end-of-day signals
- Chart patterns: daily bars only, valid swing trading signals (5-20 days)
- Session anomaly alerts: polling-derived approximations, useful as
  WATCHLIST FILTERS, not as trade entry signals
- Volume surge detection: compared against 20-day daily average scaled
  by session progress — an approximation, not true intraday bar data

VOLUME SURGE THRESHOLD VALIDATION:
Backtested on 5yr PSX daily OHLCV data (467,621 symbol-day observations):
  EXTREME (3x+ daily vol): 8.5% of days, next-day positive rate 41.2%
  SURGE (2-3x daily vol): 5.0% of days, next-day positive rate 43.2%
  NORMAL (<1.5x): 81.6% of days, next-day positive rate 33.8%

Key finding: High volume days on PSX are followed by positive next-day
returns less than 50% of the time. Volume surges flag activity, they do
not predict direction. Thresholds adjusted accordingly:
  _INTRADAY_EXTREME_SURGE_X: 3.0 -> 5.0
  _INTRADAY_VOLUME_SURGE_X:  2.0 -> 3.0
  _INTRADAY_WATCH_RVOL_X:    1.5 -> 2.5

Alert types renamed to remove directional bias (BREAKOUT_WATCH ->
RANGE_HIGH_VOLUME etc).

PSX SESSION HOURS CORRECTED:
Fixed inconsistency between three sources in the codebase. Canonical
hours now:
  Mon-Thu: 09:30-15:30 PKT
  Friday:  09:15-12:00 + 14:15-16:05 PKT
  (Jumu'ah break: 12:00-14:15 PKT)
Updated: WATCHLIST_HOURS_PKT, session_progress(), loose comment at
app.py:3239.

FUTURE PATH TO REAL INTRADAY CAPABILITY:
Option 1: Collect 1-minute market_watch snapshots as pseudo-bars (start
now, usable after 90 days of accumulation)
Option 2: Obtain paid PSX tick data from a licensed vendor

PENDING: Backend server restart required to activate scan_run_log,
intraday_alert tables in the live database. New schema tables are in
the code but not yet in the live psx_v2.db process.

---

H&S TOP SUSPENSION REVIEW — 2026-08-30

Decision confirmed: remains suspended.

Reason: n=14 resolvable signals is insufficient to distinguish genuine
underperformance (35.7% win rate) from variance. A fair coin gives 50%;
getting 5/14 has p-value ~0.21 under binomial test — not statistically
significant.

More concerning than win rate: 35.7% timeout rate (highest of any
module). Neckline breaks on PSX H&S Top frequently recover rather than
continuing down. This suggests the pattern's core thesis (breakdown
confirmation = trend reversal) may not hold on PSX's volatile,
mean-reverting market structure.

REVIEW TRIGGER:
Revisit when EITHER of these conditions is met:
1. Signal count reaches n=50 from live scanning — enough for a
   meaningful win rate estimate
2. Three consecutive live signals hit Target 1 — would suggest recent
   market conditions are more favourable

To accumulate signals faster: wire H&S Top into the scan pipeline
WITHOUT displaying it on the dashboard. Log signals to intraday_alert
or a separate hst_signals table. Review accumulated signals in 3-6
months. This is the recommended path.

STATUS: SUSPENDED — ACCUMULATING SIGNALS RECOMMENDED BEFORE NEXT
REVIEW.

---

INDICATOR BACKTEST RESULTS — 2026-08-30

Backtested 23 indicator signals on 564,178 bars, 501 PSX symbols,
2021-2026. 623,519 total signal firings.

Baseline win_rate_10d: 44.55%

KEY FINDING: PSX is a mean-reverting market. Every bearish/oversold
signal beats baseline. Every bullish crossover signal is at or below
baseline.

SIGNALS REMOVED FROM SCORING (below baseline):
- VOLUME_SPIKE: 36.63% (-7.9% vs baseline)
  n=109,509 — worst signal, largest sample
- GOLDEN_CROSS: 42.18% (-2.4% vs baseline)
- EMA50_CROSS_UP: 42.99% (-1.6%)
- EMA20_CROSS_UP: 44.33% (-0.2%)
- MACD_CROSS_UP: 44.42% (-0.1%)
- MACD_HIST_POS: 44.42% (-0.1%, identical firings to MACD_CROSS_UP)

SIGNALS BOOSTED (top performers):
- BB_OVERSOLD: 55.11% (+10.6% vs baseline)
- RSI_OVERSOLD: 51.20% (+6.7% vs baseline)

SIGNALS RETAINED UNCHANGED:
- DEATH_CROSS, EMA crossovers (bearish)
- MACD_CROSS_DOWN
- MOM_CROSS_NEG

PENDING (20% of DSS score):
- historical_stats, quant_validation components still inactive

IMPLEMENTATION NOTE: only VOLUME_SPIKE (removed) and BB_OVERSOLD/
RSI_OVERSOLD (boosted) were actually changed in technical_analyzer.py's
scoring. GOLDEN_CROSS, EMA20/50_CROSS_UP, MACD_CROSS_UP, and
MACD_HIST_POS were NOT removed, despite being listed above and below
baseline: analyze() has no discrete crossing-event check for these —
only a single current-state read per indicator (price > EMA20 right
now; MACD histogram/line currently positive/above), with no comparison
to the prior bar. That single check structurally matches what was
meant to be KEPT (a sustained-position read), not the narrower
crossing-event population this backtest actually measured (a bar's
first day past the threshold only, e.g. 19,883 MACD_CROSS_UP firings
out of 525,024 eligible bars — a different, smaller set of bars than
every day analyze()'s current bonus applies to). Building genuine
crossing-event detection into analyze() (comparing to the prior bar's
value) was explicitly deferred, not implemented.

---

INDICATOR BACKTEST — SUSTAINED POSITION FOLLOW-UP — 2026-08-30

Backtested 4 sustained-position signals on 1,002,470 observations.
Baseline win_rate_10d: 44.55%

Results:
  MACD_BULL:      44.86% (+0.31%) → KEPT
  MACD_HIST_BULL: 44.86% (+0.31%) → KEPT
  EMA50_ABOVE:    43.60% (-0.95%) → REMOVED
  EMA20_ABOVE:    43.26% (-1.29%) → REMOVED

Change 2 implemented: EMA20 and EMA50 sustained-position bonuses
removed from technical_analyzer.analyze() scoring. EMA200 not tested —
left unchanged. MACD sustained bonuses confirmed above baseline — left
unchanged.

Change 2 status: COMPLETE.

---

INTRADAY BARS COLLECTION — 2026-08-30

1-minute market_watch snapshot collector activated. Stores price,
cumulative volume, day high/low per symbol per minute during trading
hours.

Retention: 2 trading days in Turso (~320k rows max vs 800k at 5-day
retention)
Historical export: weekly CSV to backend/intraday_history/ before
deletion

Turso write estimate:
  ~160k rows/day during trading hours
  ~3.5M rows/month = ~35% of free tier

Purpose: accumulate 90 days of pseudo-bars for future Opening Range
Breakout and VWAP signal backtesting. Data will be usable from
~November 2026.

---

EMA200 SUSTAINED POSITION TEST — 2026-08-31

n_signals: 245920
win_rate_10d: 45.87% vs baseline 44.55%
Decision: KEEP
