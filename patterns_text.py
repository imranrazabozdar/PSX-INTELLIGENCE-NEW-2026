"""patterns_text.py — the Patterns tab's existing rule / metric / warning text.

GENERATED VERBATIM from the pre-redesign streamlit_app.py (bodies of its
"View Rules & Metrics" expanders and its st.warning / st.error calls) so no
wording is retyped. Each function issues the same Streamlit calls as before;
TITLE is the old expander label, now shown as a heading inside Details.
"""
import json

import streamlit as st



def mharris_rules(ctx=None):
    st.markdown('**📖 View Rules & Metrics for MHarris 5-Bar Reversal**')
    st.caption("Market-wide scan, on the latest completed daily candles — a contained "
               "micro-trend snap-back translated 1:1 from a reference systematic-trading "
               "notebook (5-candle window, indices -4..0 relative to the signal candle). "
               "3 straight bars of declining/rising lows or highs (a contained downtrend/"
               "uptrend, not a runaway breakout — the whole move still sits inside the "
               "range set 4 bars back), then a reversal candle closing beyond the PRIOR "
               "candle's high/low.")
    st.caption("⚠️ Backtested walk-forward on PSX at the strategy's own stated default "
               "parameters (SL 4% / TP 2% off the signal candle's close, unoptimized): "
               "55.8% win rate but **-0.83% average return per trade and a 0.35 profit "
               "factor** — losses (avg -2.9%) are ~3.5x bigger than wins (avg +0.8%), so "
               "this loses money at these defaults despite the win rate looking "
               "reasonable on its own. The bullish side is markedly worse (profit factor "
               "0.08) than the bearish side (0.55). The source notebook's positive result "
               "came from a per-instrument grid-search of SL/TP on 7 FX pairs, not these "
               "defaults — treat this as a documented, tracked signal, not a validated "
               "PSX edge.")


def engulfing_star_rules(ctx=None):
    st.markdown('**📖 View Rules & Metrics for Engulfing + Star Confirmed Reversal**')
    st.caption("Market-wide scan, on the latest completed daily candle — translated from a "
               "reference systematic-trading notebook. Stricter than a plain engulfing "
               "pattern: the SAME candle must be both a full engulfing bar over the prior "
               "candle AND show a dominant wick on the reversal side (upper wick for "
               "bearish, lower wick for bullish) — two confirmations on one bar, not one.")
    st.caption("The source notebook never defines a trade rule for this pattern (only "
               "forward-trend labeling to measure hit rate) — entry/stop/target here reuse "
               "this project's own bullish/bearish engulfing convention instead: stop beyond "
               "the signal candle's high/low + an ATR buffer, targets a measured move off "
               "the candle's own high-low range.")
    st.caption("⚠️ Backtested walk-forward on PSX (194 symbols, 168 resolved trades) at "
               "this geometry-based stop/target rule — **71.4% win rate, +0.34% average "
               "return per trade, 1.16 profit factor overall**, one of the few net-profitable "
               "signals this project has backtested. The two directions diverge sharply "
               "though: bearish signals (123 trades) carry the edge — **76.4% win rate, "
               "+0.81% avg return, 1.54 profit factor** — while bullish signals (45 trades) "
               "are a net loser — **57.8% win rate, -0.94% avg return, 0.75 profit factor**. "
               "Treat the bearish (short) side as the one with real support here; the "
               "bullish side is currently losing money at these defaults despite a win rate "
               "over 50%.")


def macdema_rules(ctx=None):
    st.markdown('**📖 View Rules & Metrics for MACD+EMA200 Trend Resumption**')
    st.caption("Market-wide scan, on the latest completed daily candle — translated from a "
               "reference systematic-trading notebook. Requires an ALREADY-established trend "
               "(every bar in a trailing 6-bar window trading fully above/below its EMA200), "
               "then a MACD line/signal-line cross back through zero while still on the "
               "trend's side — i.e. buying/selling a pullback WITHIN a confirmed trend, not "
               "catching a fresh reversal. Needs ~217+ days of daily history per symbol "
               "before it can evaluate at all (EMA200 dominates that requirement), so "
               "coverage is partial while the full-market backfill is still loading.")
    st.caption("Exit is a pure ATR(14) trailing stop (atr_mult=2.0, the strategy's own "
               "stated default, unoptimized) — there is no fixed take-profit target by "
               "design, so \"Target\" always reads Trailing.")
    st.caption("⚠️ Backtested walk-forward on PSX (180 symbols, 1,299 resolved trades) at "
               "the strategy's own stated default (ATR trailing stop, atr_mult=2.0, "
               "unoptimized): **39.3% win rate, -0.71% average return per trade, 0.78 "
               "profit factor overall** — this loses money at these defaults. Split by "
               "side: bullish signals are the weaker half (35.3% win rate, -1.31% avg "
               "return, PF 0.62); bearish signals are close to breakeven (43.6% win rate, "
               "-0.08% avg return, PF 0.97) but still net negative. Coverage is 180/~750 "
               "symbols so far (full-market backfill still loading) and will be re-run "
               "periodically as coverage grows — treat this as a documented, tracked "
               "signal, not a validated PSX edge.")


def obv_mfi_rules(ctx=None):
    st.markdown('**📖 View Rules for OBV+MFI Setup with ATR Contraction**')
    st.caption("**Day 0 (3–45 sessions ago):** close above the prior 20-day highest close, "
               "volume > 3× its prior 20-day average, OBV at a new 20-day high, MFI(14) > 80. "
               "**Today:** close 4–30% below Day 0 but above SMA20; average volume since Day 0 "
               "< 40% of Day 0's; MFI < 55; OBV within 10% of its Day 0 value; ATR(14) below "
               "Day 0's. A pattern signal, not yet backtested on PSX — not a probability of profit.")


def triangle_rules(ctx=None):
    st.markdown('**📖 View Rules & Metrics for Regression-Channel Triangle Squeeze**')
    st.caption("Market-wide scan, on the latest completed daily candle — a rolling "
               "OLS-regression converging-channel detector translated from a reference "
               "systematic-trading notebook: over a trailing 40-day window, fits a "
               "regression line through every confirmed pivot high and every confirmed "
               "pivot low separately, and requires both to be genuinely linear (R² ≥ 0.7) "
               "with a near-flat/declining resistance rail (≤0.8% total drift) and a "
               "meaningfully rising support rail (≥2.0% total rise) — a squeeze. Different "
               "from this app's separate discrete-pivot Ascending Triangle engine "
               "(currently disabled for insufficient PSX signal density): this is a "
               "continuous, looser formulation expected to fire far more often.")
    st.caption("⚠️ **SHORT-only, deliberately** — the source notebook backtested SHORTING "
               "this squeeze (betting on a breakdown), not the classical bullish-breakout "
               "assumption, on 5-minute gold futures. Entry at the signal candle's own "
               "close, stop 1% above the signal high, target at 3x that risk (the "
               "strategy's own stated default, unoptimized).")
    st.caption("⚠️ Backtested walk-forward on PSX (193 symbols, 11,741 resolved trades — by "
               "far the highest signal density of any pattern on this page, as expected "
               "from this looser, continuous formulation): **23.3% win rate, -0.58% average "
               "return per trade, 0.78 profit factor** — with a 3:1 target-to-risk ratio the "
               "breakeven win rate is ~25%, so this sits just below breakeven and loses "
               "money at these defaults, same honest verdict as every other pattern here. "
               "Coverage is 193/~750 symbols so far and will be re-run periodically as the "
               "full-market backfill grows — treat this as a documented, tracked signal, "
               "not a validated PSX edge.")


def level_breakout_rules(ctx=None):
    st.markdown('**📖 View Rules & Metrics for Level Break Out**')
    st.caption("Market-wide scan, on the latest completed daily candle — a horizontal "
               "support/resistance breakout translated from a reference systematic-trading "
               "notebook. Finds the last 3 confirmed pivot lows (or highs) within a trailing "
               "40-day window that all sit within 1% of each other (a flat horizontal "
               "level), then signals when the close moves decisively (>2% ) beyond that "
               "level — classical breakout logic: buy strength on a resistance breakout, "
               "sell weakness on a support breakdown. This is the OPPOSITE convention from "
               "the Regression-Channel Triangle Squeeze above, which deliberately shorts its "
               "geometry instead.")
    st.caption("Fixed 3% stop, 2:1 reward:risk (the strategy's own stated defaults, "
               "unoptimized), entered at the next bar's open. The notebook's backtest ALSO "
               "closes an open position early if RSI(14) crosses above 80 (long) or below "
               "20 (short) — reflected in the walk-forward backtest below, not in this "
               "table's static target (a live scan has no open position to manage).")
    st.caption("⚠️ On EURUSD daily (2003-2023, 16 years) this fired only 7 times — an "
               "extremely rare setup even on its native instrument. PSX's larger, more "
               "volatile universe fires far more often: backtested walk-forward on PSX "
               "(193 symbols, 190 resolved trades) at the strategy's own default, "
               "unoptimized rule (3% stop, 2:1 reward:risk, RSI 80/20 early exit) — "
               "**43.2% win rate, +0.37% average return per trade, 1.22 profit factor "
               "overall**. The two directions diverge sharply: resistance breakouts "
               "(109 trades) are profitable at **50.5% win rate, +1.05% avg return, 1.65 "
               "profit factor**, while support breakdowns (81 trades) are not — **33.3% "
               "win rate, -0.54% avg return, 0.71 profit factor**. Treat the bullish "
               "(resistance-breakout) side as the one with real edge here; the bearish "
               "(support-breakdown) side is currently a net loser at these defaults.")


def gp_rules(ctx=None):
    _gp_evolved_ranking = (ctx or {}).get('gp_ranking')
    st.markdown('**📖 View Rules & Metrics for GP-Evolved Formula**')
    st.caption("NOT a fixed rule like this project's other detectors — translated from a "
               "reference genetic-programming (GP) repo (ZiadFrancis/Genetics_Trading_Part_1) "
               "that EVOLVES a symbolic formula per instrument (via DEAP) mapping OHLC inputs "
               "to a continuous TARGET position exposure from -100% (max short-bias) to "
               "+100% (max long-bias), instead of following a fixed textbook pattern.")
    st.caption("PSX adaptation: each watchlist symbol's own daily OHLC is paired with the "
               "KSE-100 index's own daily OHLC as the formula's 8 inputs (the source used 4 "
               "correlated FX pairs; PSX has no such basket, so each stock is paired with its "
               "own benchmark index instead, per explicit direction). All 8 inputs are "
               "z-scored on a trailing 20-day window before the formula ever sees them — "
               "raw stock price (Rs) and the KSE-100 index level (tens of thousands) differ "
               "by orders of magnitude, which made an early, un-normalized version collapse "
               "onto a constant signal (caught in testing, not shipped).")
    st.caption("Each symbol's formula is evolved on its own trailing 60% of history, the best "
               "Hall-of-Fame formula is picked on the next 20% (validation), and the exposure "
               "shown above is that SAME formula's TODAY reading — the 'Out-of-Sample' columns "
               "are that formula's own performance on the FINAL, never-trained-on 20% of "
               "history, not a promise about tomorrow. Training runs offline (a long, "
               "resumable GitHub Actions job, not the daily refresh) — see "
               "backend/run_gp_evolution_training.py and gp_evolved_detector.py's module "
               "docstring for the full translation, including the no-lookahead adaptation "
               "(the source fills orders same-bar; here, a bar's signal only ever applies to "
               "the NEXT bar's return) and the rescaled commission/trade-count guard.")
    if _gp_evolved_ranking and _gp_evolved_ranking.get("ranked"):
        st.caption(f"{_gp_evolved_ranking.get('symbols_trained', 0)} of the watchlist's ~89 "
                   f"symbols currently have a viable trained model "
                   f"({_gp_evolved_ranking.get('symbols_skipped', 0)} skipped — insufficient "
                   "history/overlap, or no evolved formula cleared the minimum-trade-count "
                   "guard on validation).")


def fire_rules(ctx=None):
    st.markdown('**📖 View Rules & Metrics for the FIRE Engine**')
    st.caption("Detects MFI acceleration + time-of-day relative volume (median-based, not "
               "global) + price compression preceding a volume-confirmed breakout, on real "
               "1-minute PSX data from SCS (Standard Capital Securities). PRE-FIRE = setup "
               "forming (score 60-74); FIRE = breakout confirmed (score >=75). Runs once "
               "per day after market close, not live intraday yet -- see "
               "fire_engine/run_daily_batch.py.")


def wyckoff_rules(ctx=None):
    st.markdown('**📖 View Rules & Metrics for Wyckoff Accumulation**')
    st.caption("Detects consolidation (tight 20-day range, by % or ATR) + supply exhaustion "
               "(volume drying up) + absorption (high volume, tight spread) + OBV/price "
               "divergence on daily bars, plus Bollinger Band compression on 4-hour bars "
               "resampled into the daily score, gated by a daily MACD confirmation. "
               "WATCH = score 60-69, READY = 70-84, EXTREME = 85+. Runs once per day after "
               "market close, right after the FIRE Engine batch -- see "
               "fire_engine/run_wyckoff_batch.py.")


def wyckoff_components(ctx=None):
    _wyckoff_hits = ctx['wyckoff_hits']
    _signal_badge = ctx['signal_badge']
    st.markdown('**Component breakdown (why each symbol scored what it did)**')
    _mark = lambda ok: "✅" if ok else "❌"
    for i, h in enumerate(_wyckoff_hits):
        try:
            components = json.loads(h.get("components") or "{}")
        except (TypeError, ValueError):
            components = {}
        if i > 0:
            st.divider()
        st.markdown(f"**{h['symbol']}** — {h.get('accumulation_score')}/100, "
                    f"{_signal_badge.get(h.get('signal_type'), h.get('signal_type'))}")
        st.markdown(
            f"{_mark(components.get('bb_compression'))} BB Compression "
            f"— {h.get('bb_width_score')}/20  \n"
            f"{_mark(components.get('supply_exhaustion'))} Supply Exhaustion "
            f"— {h.get('dry_supply_score')}/20  \n"
            f"{_mark(components.get('absorption'))} Absorption "
            f"— {h.get('absorption_score')}/30  \n"
            f"{_mark(components.get('obv_divergence'))} OBV Divergence "
            f"— {h.get('obv_divergence_score')}/30"
        )
        st.caption(
            f"Required gates (both must hold): "
            f"{_mark(components.get('is_consolidating'))} Consolidating · "
            f"{_mark(components.get('macd_confirmation'))} MACD Confirmed"
        )


def bullish_engulfing_rules(ctx=None):
    st.markdown('**📖 View Rules & Metrics for Bullish Engulfing**')
    st.caption("Market-wide scan, on the latest completed daily candles — real bodies per Steve "
               "Nison's classical definition, not wicks/shadows. Detection only: no targets, stop "
               "losses, or indicator filters. 🟢 = geometry confirmed by a preceding downtrend (a "
               "full, valid reversal signal). 🔴 = engulfing geometry present but with **no "
               "confirmed prior downtrend** — flagged, not a valid classical signal on its own.")
    st.caption("**Rules used** — Candle 1 (previous) bearish, Candle 2 (latest) bullish, and "
               "Candle 2's real body engulfs Candle 1's real body (STRICT: open₂<close₁ and "
               "close₂>open₁; BOUNDARY_MATCH: one boundary equal, the other strictly beyond). "
               "Prior downtrend (automation-only rule, not from Nison): of the 3 close-to-close "
               "moves ending at Candle 1's close, at least 2 must be negative, and Candle 1's "
               "close must be below the close 3 sessions earlier. An unfinished current-day "
               "candle is always excluded. Refreshed once daily in the background (daily-bar "
               "geometry doesn't shift within a session) — use the sidebar's Force Market-Wide "
               "Refresh for an immediate re-run.")


def morning_star_rules(ctx=None):
    st.markdown('**📖 View Rules & Metrics for Morning Star**')
    st.caption("Market-wide scan, on the latest completed daily candles — Thomas Bulkowski's "
               "empirical 3-candle criteria (50% midpoint penetration, small-star geometry) plus "
               "Steve Nison's classical description. Two deliberate PSX exceptions: no physical "
               "gap is required between candles (±10% circuit breakers can prevent one from ever "
               "printing) and Day 1 volume is never filtered (a lower-circuit lock trades almost "
               "nothing by definition). 🟢 STRONG = full 4-way confluence (volume >1.5x, Day 2 is "
               "a doji, >75% penetration, Day 2 RSI(14)<35). 🔵 MODERATE = passes the base "
               "geometry, 50% midpoint rule, and ≥1.3x volume, but not the full STRONG bar.")
    st.caption("Backtested on 742 PSX signals (2021-2026). Win rate 53.9%, median P&L +2.3%. "
               "STRONG signals (4 strict conditions) show 55.6% win rate. Target 2 hit rate "
               "13.7% — highest of all pattern modules.")
    st.caption("**Rules used** — Day 1: bearish, real body larger than its trailing 10-day "
               "average. Day 2: real body ≤30% of Day 1's, closing in the lower third of Day 1's "
               "range. Day 3: bullish, closing above the 50% midpoint of Day 1's body (Bulkowski's "
               "non-negotiable rule). Context: Day 1 close below its SMA10 OR ≥4 lower-lows in "
               "the preceding 6 days; Day 3 volume ≥1.3x its trailing 20-day average. Stop loss = "
               "Day 2 low − 0.5×ATR(14); Target 1 = entry + (Day 1 high − Day 2 low); Target 2 = "
               "Target 1 + 1.0×ATR(14). Refreshed once daily in the background — use the "
               "sidebar's Force Market-Wide Refresh for an immediate re-run.")


def three_line_strike_rules(ctx=None):
    st.markdown('**📖 View Rules & Metrics for Bullish Three-Line Strike**')
    st.caption("Market-wide scan, on the latest completed 4-candle window — a rare "
               "volatility-trap reversal: three consecutive lower closes in a confirmed uptrend, "
               "fully engulfed by a single bullish strike candle on expanding volume (≥1.3x "
               "20-day average). Prior trend is the exact literal rule (close 10 sessions ago "
               "≥5% below Day 1's open), not the OLS heuristic used for the Engulfing detectors. "
               "🟢 VALID = volume confirmed. ⚪ GEOMETRY_ONLY = the 4-candle pattern and prior "
               "uptrend both confirmed, but Day 4 volume did not reach 1.3x average — tracked "
               "for visibility, not an actionable signal.")


def bearish_engulfing_rules(ctx=None):
    st.markdown('**📖 View Rules & Metrics for Bearish Engulfing**')
    st.caption("Market-wide scan, on the latest completed daily candles — mirror of Bullish "
               "Engulfing, inverted. Day 1 bullish, Day 2 bearish and fully engulfing Day 1's "
               "body, prior uptrend confirmed by the same OLS-regression-slope heuristic Bullish "
               "Engulfing uses (sign-flipped), plus a volume filter (Day 2 ≥1.3x its 20-day "
               "average) and a near-resistance filter (Day 1's high within 3% of the trailing "
               "20-day swing high) that Bullish Engulfing does not have.")
    st.caption("Backtested on the full PSX universe: Target 1 win rate 66.8%, Target 2 win rate "
               "8.3%, stop-hit rate 31.6% (n=1,620 VALID signals).")


def evening_star_rules(ctx=None):
    st.markdown('**📖 View Rules & Metrics for Evening Star**')
    st.caption("Market-wide scan, on the latest completed daily candles — bearish mirror of "
               "Morning Star. Day 1 large bullish, Day 2 small body in the UPPER third of Day "
               "1's range, Day 3 large bearish closing below Day 1's 50% midpoint, Day 3 volume "
               "≥1.3x its 20-day average.")


def structural_rules(ctx=None):
    st.markdown('**📖 View Rules & Metrics for Chart Patterns (IHS, Double Bottom & Head/Shoulders)**')
    st.caption("⚠️ \"Pattern Quality\" is a deterministic geometric/volume score, NOT a "
               "validated predictor of trade outcome — backtesting found zero statistically "
               "significant correlation between this score and win/loss. Use it to understand "
               "why a pattern matched, not to decide whether to trust it. Higher scores suggest "
               "larger moves when the pattern succeeds, not higher win probability. Consider "
               "using for position sizing only. IHS (⚠️) signals have structurally "
               "underperformed Double Bottom signals in PSX backtesting. \"Regime\" is a "
               "placeholder pending a KSE-100 index data feed.")
    st.caption("Head & Shoulders Top is the exact bearish mirror of Inverse H&S (same engine, "
               "same pivot/breakout/confidence machinery, flipped: highs instead of lows, "
               "requires a PRIOR UPTREND, SHORTS the breakdown below the neckline). It was "
               "built alongside Inverse H&S but deliberately left unwired pending its own "
               "walk-forward backtest.")
    st.caption("⚠️ Backtested walk-forward on PSX (202 symbols, only **7 signals** total — "
               "this is a strict 5-pivot structural pattern, same low signal density as "
               "Inverse H&S on this market): **42.9% win rate to Target 1, 0% reached "
               "Target 2, -4.42% average return per trade, 0.63 profit factor** — a small "
               "loser at these defaults, and n=7 is too thin to treat as a reliable "
               "estimate either way. Treat this as a documented, tracked signal, not a "
               "validated PSX edge — and re-run the backtest periodically as more history "
               "accumulates before trusting the number more than the sample size allows.")


def three_line_strike_warning(ctx=None):
    st.warning("⚠️ Ultra-rare volatility trap. Target 1 has a 56% historical win rate, but Target 2 "
               "is structurally unvalidated (0%). Trade with caution. Backtested on only 64 "
               "resolvable PSX signals (PRODUCTION READY - RARE SIGNAL (MONITORED), not a "
               "full-confidence module) — low 6.25% timeout rate is the reason this was wired "
               "despite the thin sample.")


def evening_star_warning(ctx=None):
    st.warning("⚠️ Backtested on the full PSX universe: Target 1 win rate 64.1%, stop-hit rate "
               "30.8% (n=39 — a very thin sample; Target 2 win rate is 0% at this sample size, so "
               "treat this pattern's edge as unvalidated, not just unbacktested).")


def short_side_warning(ctx=None):
    st.error("Everything in this tab expects price to FALL, not rise. PSX short-selling carries "
              "different risk/settlement parameters than a long position — confirm your broker/NCCPL "
              "margin and settlement rules before acting on any of these.", icon="🚨")


def wyckoff_warning(ctx=None):
    st.warning("⚠️ **Not a buy signal, and not a prediction.** WATCH/READY/EXTREME describe how "
               "completely a textbook Wyckoff accumulation *pattern* is present right now (tight "
               "range + volume drying up + a high-volume absorption day + OBV/price divergence) -- "
               "not the odds the price actually rises. This pattern fails often in real markets, "
               "and this scanner has never been backtested for hit rate (unlike this project's VCP/ "
               "Flat Base detectors, which were backtested and came back needing rework). Treat a "
               "hit as \"worth a closer look on the 1-hour chart for a real entry trigger (Spring, "
               "absorption spike, etc.),\" never as \"buy this.\"")
    st.caption("💡 Daily + 4-hour data only -- entry timing (Spring, absorption spikes, etc.) is a "
               "manual 1-hour-chart step; this scanner intentionally never fetches or computes on "
               "1-hour data.")
