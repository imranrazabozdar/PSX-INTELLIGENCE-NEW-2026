"""dss_engine.py — Decision Support System: assembles the evidence-hierarchy
this backend already computes (market regime, sector regime, Wyckoff phase,
effort/result, structure, candlesticks, technical indicators, relative
strength, psx_brain's trade plan, the integrated /decision signal) into one
confluence matrix, an evidence score, a confidence grade and a final action
label — per the PSX Master Quantitative Technical Intelligence framework
(market regime -> sector regime -> stock structure -> Wyckoff -> supply/demand
-> price-volume -> candlestick -> price action -> relative strength ->
statistical/quant validation -> risk/reward -> final decision).

Historical pattern statistics (Bulkowski-style) and quantitative baseline
validation (Grimes-style) are now real, computed by backtest_engine.py's
walk-forward scan over stored true-OHLC across the whole backfilled universe
— not fabricated, not guessed. When no backtest has been run yet, or the
stock's current pattern has zero recorded historical occurrences, those two
components report PENDING / INSUFFICIENT SAMPLE honestly rather than
inventing a number.

The component weights below are explicitly what the source framework calls
them: "modern model-design choices", not historical rules attributed to
Wyckoff, Nison, Brooks, Bulkowski or Grimes. They are meant to be tuned later
against real PSX backtests (STEP 39 / STEP 66 of the source spec).
"""

import backtest_engine as _bt
import candlestick_engine as _cse
import scan_cache_engine as _scan_cache

WEIGHTS = {
    "wyckoff": 20,
    "supply_demand": 15,
    "market_structure": 10,
    "candlesticks": 8,
    "price_action": 10,
    "historical_stats": 10,   # PENDING — needs backtest engine
    "quant_validation": 10,   # PENDING — needs baseline comparison engine
    "relative_strength": 7,
    "momentum_indicators": 5,
    "macd": 5,               # STEP 30
    "obv_divergence": 5,     # STEP 31
    "risk_reward": 5,
    "weekly_structure": 5,   # STEP 56: strategic-timeframe agreement/disagreement with the daily read
}
STATS_HORIZON = 20  # STEP 24: report the 20-day forward window as the headline stat


def _current_patterns(wy, candles):
    """Patterns genuinely present right now, in backtest_engine's exact naming,
    so the lookup matches real recorded occurrences instead of guessing."""
    pats = list((candles or {}).get("candles") or [])
    spring = ((wy or {}).get("spring") or {}).get("status")
    if spring in ("CONFIRMED", "TESTED", "CANDIDATE"):
        pats.append("Spring")
    upthrust = ((wy or {}).get("upthrust") or {}).get("status")
    if upthrust in ("CONFIRMED", "CANDIDATE"):
        pats.append("Upthrust")
    return pats


def _component(name, key, stance, strength, detail):
    """stance: 'bullish' | 'bearish' | 'neutral' | 'pending'
    strength: 0.0-1.0, how much of the component's weight to award."""
    weight = WEIGHTS[key]
    signed = 0.0
    if stance == "bullish":
        signed = weight * strength
    elif stance == "bearish":
        signed = -weight * strength
    return {"component": name, "key": key, "weight": weight, "stance": stance,
            "strength": round(strength, 2), "signed_points": round(signed, 1),
            "detail": detail}


def _market_regime_component(regime):
    if not regime or "label" not in regime:
        return _component("KSE-100 Market Regime", "market_structure", "neutral", 0,
                           "Market regime unavailable.")
    label = regime["label"]
    stance = ("bullish" if label in ("RISK-ON", "CONSTRUCTIVE")
              else "bearish" if label == "RISK-OFF" else "neutral")
    strength = 1.0 if label in ("RISK-ON", "RISK-OFF") else 0.5
    return _component(f"KSE-100 Regime ({label})", "market_structure", stance, strength,
                       f"Breadth {regime.get('breadth_pct')}%, avg chg {regime.get('avg_change_pct')}%")


def _sector_component(sector_row, sector_name):
    if not sector_row:
        return _component(f"Sector ({sector_name or '—'})", "market_structure", "neutral", 0,
                           "Sector rotation data unavailable for this sector.")
    breadth = sector_row.get("breadth_pct", 50)
    avg = sector_row.get("avg_change_pct", 0)
    stance = "bullish" if (breadth > 55 and avg > 0) else "bearish" if (breadth < 45 and avg < 0) else "neutral"
    strength = min(1.0, abs(breadth - 50) / 30)
    return _component(f"Sector Rotation ({sector_row.get('sector')})", "market_structure", stance, strength,
                       f"Breadth {breadth}%, avg chg {avg}%, strength {sector_row.get('strength')}")


def _wyckoff_component(wy):
    if not wy or wy.get("status") == "awaiting_true_ohlcv" or "phase" not in wy:
        return _component("Wyckoff Phase", "wyckoff", "pending", 0,
                           "Needs >=50 true-OHLC sessions (backfill from More tab).")
    phase = wy.get("phase", "UNRESOLVED")
    spring = (wy.get("spring") or {}).get("status")
    upthrust = (wy.get("upthrust") or {}).get("status")
    if "ACCUMULATION" in phase or spring == "CONFIRMED":
        stance, strength = "bullish", 1.0 if spring == "CONFIRMED" else 0.6
    elif "DISTRIBUTION" in phase or upthrust == "CONFIRMED":
        stance, strength = "bearish", 1.0 if upthrust == "CONFIRMED" else 0.6
    elif "MARKUP" in phase:
        stance, strength = "bullish", 0.5
    elif "MARKDOWN" in phase:
        stance, strength = "bearish", 0.5
    else:
        stance, strength = "neutral", 0
    return _component(f"Wyckoff ({phase})", "wyckoff", stance, strength,
                       f"Spring: {spring or '—'} · Upthrust: {upthrust or '—'}")


def _supply_demand_component(wy):
    er = (wy or {}).get("effort_vs_result") if wy else None
    if not er or er.get("status") == "insufficient_history":
        return _component("Effort vs Result", "supply_demand", "pending", 0,
                           "Needs more true-OHLC history.")
    state = er.get("state", "")
    if "HARMONY" in state:
        stance, strength = ("bullish" if er.get("progress_ratio", 0) >= 0 else "bearish"), 0.7
    elif "ABSORPTION" in state or "HIGH EFFORT" in state:
        stance, strength = "bullish", 0.5  # possible absorption — read as tentatively constructive, needs confirmation
    elif "LOW EFFORT / LARGE RESULT" in state:
        stance, strength = "bullish" if er.get("progress_ratio", 0) > 0 else "bearish", 0.6
    else:
        stance, strength = "neutral", 0
    return _component("Effort vs Result", "supply_demand", stance, strength,
                       f"{state} (vol ratio {er.get('volume_ratio')}, progress {er.get('progress_ratio')})")


def _candlestick_component(candles, ohlc_rows=None, wy=None, technical=None):
    """STEP 17-18: real 0-100 context score (pattern+location+trend+volume)
    and a real confirmation state, not a fixed placeholder strength — uses
    the exact same candlestick_engine.detect_at() output app.py's live
    /intelligence endpoint already returns, so the pattern name always matches."""
    names = (candles or {}).get("candles") or []
    if not names:
        return _component("Candlestick Pattern", "candlesticks", "neutral", 0,
                           "No pattern on the most recent bar — normal, not an error.")

    biases = [_cse.bias(n) for n in names]
    n_bull = sum(1 for b in biases if b == "bullish")
    n_bear = sum(1 for b in biases if b == "bearish")
    stance = "bullish" if n_bull > n_bear else "bearish" if n_bear > n_bull else "neutral"

    if not ohlc_rows or len(ohlc_rows) < 5:
        return _component(f"Candlestick ({', '.join(names)})", "candlesticks", stance, 0.5,
                           "Unconfirmed — no stored true-OHLC to score location/volume/follow-through against.")

    i = len(ohlc_rows) - 1
    tr = (wy or {}).get("trading_range") or {}
    support, resistance = tr.get("support"), tr.get("resistance")
    avg_vol = (technical or {}).get("avg_volume")
    directional = [n for n, b in zip(names, biases) if b == stance] or names
    best_name = directional[0]
    ctx = _cse.context_score(ohlc_rows, i, best_name, support=support, resistance=resistance, avg_volume=avg_vol)
    conf = _cse.confirmation_status(ohlc_rows, i, best_name)
    strength = min(1.0, ctx["score"] / 100)
    return _component(f"Candlestick ({', '.join(names)}) — score {ctx['score']}/100, {conf['status']}",
                       "candlesticks", stance, strength,
                       f"pattern {ctx['breakdown']['pattern_quality']} + location {ctx['breakdown']['location_quality']} "
                       f"+ trend {ctx['breakdown']['trend_context']} + volume {ctx['breakdown']['volume_support']} "
                       f"= {ctx['score']}/100. Confirmation: {conf['status']} ({conf.get('reason', conf.get('checks_passed',''))})")


def _price_action_component(wy, technical):
    st = (wy or {}).get("structure") or {}
    trend, bos = st.get("trend"), st.get("bos")
    if bos == "BULLISH BOS":
        return _component("Price Action (structure BOS)", "price_action", "bullish", 0.7, "Bullish break of structure")
    if bos == "BEARISH BOS":
        return _component("Price Action (structure BOS)", "price_action", "bearish", 0.7, "Bearish break of structure")
    if trend and "UPTREND" in trend:
        return _component("Price Action (HH/HL structure)", "price_action", "bullish", 0.5, trend)
    if trend and "DOWNTREND" in trend:
        return _component("Price Action (LH/LL structure)", "price_action", "bearish", 0.5, trend)
    return _component("Price Action", "price_action", "neutral", 0, trend or "Range / transition")


def _relative_strength_component(rs, rs_multi=None):
    """STEP 32: prefer the real multi-period (1W-12M, weighted toward longer
    horizons) read over the single-session proxy whenever enough true-OHLC
    history exists for it — falls back to the session proxy honestly rather
    than pretending multi-period data exists when it doesn't."""
    if rs_multi and rs_multi.get("status") == "ok" and rs_multi.get("weighted_avg_vs_index") is not None:
        avg = rs_multi["weighted_avg_vs_index"]
        cls = rs_multi["classification"]
        stance = "bullish" if avg > 2 else "bearish" if avg < -2 else "neutral"
        strength = min(1.0, abs(avg) / 15)
        p = rs_multi.get("periods", {})
        detail = " · ".join(f"{k} {v['vs_index']:+.1f}%" for k, v in p.items() if v.get("vs_index") is not None)
        return _component(f"Relative Strength ({cls}, multi-period)", "relative_strength", stance, strength,
                           f"Weighted avg vs KSE-100 {avg:+.2f}% ({rs_multi.get('sector_peers_used', 0)} sector "
                           f"peers) — {detail}")
    if not rs or rs.get("status") == "not_found":
        return _component("Relative Strength", "relative_strength", "neutral", 0, "Unavailable")
    vs_sector = rs.get("vs_sector_pct", 0)
    vs_kse = rs.get("vs_kse100_constituents_pct", 0)
    avg = (vs_sector + vs_kse) / 2
    stance = "bullish" if avg > 0.3 else "bearish" if avg < -0.3 else "neutral"
    strength = min(1.0, abs(avg) / 3)
    return _component("Relative Strength (session proxy — no true-OHLC yet for multi-period)",
                       "relative_strength", stance, strength,
                       f"vs sector {vs_sector:+.2f}% · vs KSE-100 {vs_kse:+.2f}%")


def _weekly_structure_component(weekly):
    """STEP 56: does the strategic (weekly) trend agree with the daily read?
    A daily bullish setup inside a weekly downtrend is real, common, and
    weaker than one inside a weekly uptrend — never scored as if timeframes
    don't interact."""
    if not weekly or weekly.get("status") != "ok":
        return _component("Weekly Structure", "weekly_structure", "pending", 0,
                           "Needs enough true-OHLC history to resample to weekly bars.")
    trend = (weekly.get("structure") or {}).get("trend", "")
    if "UPTREND" in trend:
        return _component(f"Weekly Structure ({trend})", "weekly_structure", "bullish", 0.6, trend)
    if "DOWNTREND" in trend:
        return _component(f"Weekly Structure ({trend})", "weekly_structure", "bearish", 0.6, trend)
    return _component(f"Weekly Structure ({trend or 'unresolved'})", "weekly_structure", "neutral", 0, trend or "—")


def _macd_component(technical):
    """STEP 30: MACD line/signal/histogram/zero-line, already computed by the
    v1 technical stack (technical_analyzer.py's macd_hist field) — not
    recomputed here, just scored. A crossover below zero during active
    markdown reads weaker than one during accumulation, which the contradiction
    penalty against the Wyckoff component already handles, not this row alone."""
    if not technical or technical.get("macd_hist") is None:
        return _component("MACD", "macd", "neutral", 0, "MACD unavailable")
    hist = technical["macd_hist"]
    stance = "bullish" if hist > 0 else "bearish" if hist < 0 else "neutral"
    strength = min(1.0, abs(hist) / max(0.01, abs(technical.get("price") or 1) * 0.01))
    return _component(f"MACD (hist {hist:+.3f})", "macd", stance, strength,
                       "Histogram above zero = bullish momentum, below = bearish — read with trend "
                       "context, not as a standalone crossover signal.")


def _obv_component(technical):
    """STEP 31: OBV trend + the real bullish OBV/price divergence check
    (technical_analyzer.py's obv_price_divergence — price flat/lower while
    OBV rises = possible quiet accumulation, never proof by itself)."""
    if not technical:
        return _component("OBV", "obv_divergence", "neutral", 0, "OBV unavailable")
    obv_up = technical.get("obv_up")
    divergence = technical.get("obv_divergence_bullish")
    if divergence:
        return _component("OBV (bullish price/OBV divergence)", "obv_divergence", "bullish", 0.7,
                           "Price's recent swing low is flat/lower while OBV's low is higher — "
                           "consistent with possible absorption, not confirmed accumulation by itself.")
    if obv_up is None:
        return _component("OBV", "obv_divergence", "neutral", 0, "OBV trend unavailable")
    stance = "bullish" if obv_up else "bearish"
    return _component(f"OBV ({'rising' if obv_up else 'falling'})", "obv_divergence", stance, 0.3,
                       "OBV trend alone cannot prove professional accumulation — supporting evidence only.")


def _event_risk_penalty(event_risk):
    """STEP 37: a real HIGH-materiality announcement doesn't get its own
    confluence row (it isn't bullish or bearish by itself) — it caps how much
    the score can claim, since a volume spike it explains shouldn't be read
    as Wyckoff accumulation/distribution confidence."""
    if not event_risk:
        return None
    level = event_risk.get("level")
    if level == "HIGH":
        return {"level": "HIGH", "score_cap": 70,
                "reason": event_risk.get("reason"), "items": event_risk.get("items", [])}
    return {"level": level or "UNKNOWN", "score_cap": None, "reason": event_risk.get("reason"), "items": []}


def _momentum_component(technical):
    if not technical:
        return _component("Momentum (RSI/ADX)", "momentum_indicators", "neutral", 0, "Technical engine unavailable")
    rsi = technical.get("rsi")
    adx = technical.get("adx_proxy")
    if rsi is None:
        return _component("Momentum (RSI/ADX)", "momentum_indicators", "neutral", 0, "RSI unavailable")
    stance = "bullish" if rsi > 55 else "bearish" if rsi < 45 else "neutral"
    strength = min(1.0, abs(rsi - 50) / 30)
    return _component("Momentum", "momentum_indicators", stance, strength,
                       f"RSI {round(rsi,1)}, ADX proxy {round(adx,1) if adx else '—'} — "
                       "read as trend context, never RSI<30=BUY in isolation")


def _risk_reward_component(verdict):
    if not verdict or verdict.get("status") != "ok":
        return _component("Risk/Reward", "risk_reward", "pending", 0, "Verdict/trade plan unavailable")
    rr = (verdict.get("levels") or {}).get("rr")
    if rr is None:
        return _component("Risk/Reward", "risk_reward", "neutral", 0, "R:R not computed")
    stance = "bullish" if rr >= 1.5 else "neutral" if rr >= 1.0 else "bearish"
    strength = min(1.0, rr / 3)
    return _component(f"Risk/Reward ({rr})", "risk_reward", stance, strength,
                       "STEP 47: <1 poor, 1-1.5 weak, 1.5-2 acceptable, 2-3 good, 3+ attractive")


def _historical_stats_component(current_patterns):
    """STEP 23-25: real forward-return statistics for whatever pattern(s) are
    genuinely present right now, from backtest_engine's stored walk-forward
    scan. Never uses published textbook probabilities — only what this
    backend itself measured on the backfilled PSX universe."""
    run = _bt.latest_run()
    if not run:
        return _component("Historical Pattern Statistics", "historical_stats", "pending", 0,
                           "PENDING — no backtest has been run yet. Run one from the More tab.")
    if not current_patterns:
        return _component("Historical Pattern Statistics", "historical_stats", "neutral", 0,
                           "No pattern currently active on this stock to look up.")
    stats_by_pattern = _bt.pattern_stats_multi(current_patterns, STATS_HORIZON, run_id=run["id"])
    best = None
    for pat in current_patterns:
        st = stats_by_pattern.get(pat)
        if st and st["n"] > 0 and (best is None or st["n"] > best[1]["n"]):
            best = (pat, st)
    if not best:
        return _component("Historical Pattern Statistics", "historical_stats", "pending", 0,
                           f"'{', '.join(current_patterns)}' has zero recorded occurrences in the "
                           f"backtested universe ({run['universe_symbols']} symbols) — no stat to report.")
    pat, st = best
    if st["low_sample"]:
        return _component(f"Historical Stats ({pat}, n={st['n']} — low sample)", "historical_stats",
                           "neutral", 0.2,
                           f"Win rate {st['win_rate']}%, avg {STATS_HORIZON}d return {st['avg_return']:+.2f}% "
                           f"— sample under {_bt.MIN_SAMPLE}, treat as suggestive only.")
    stance = "bullish" if st["expectancy"] > 0.3 else "bearish" if st["expectancy"] < -0.3 else "neutral"
    strength = min(1.0, abs(st["expectancy"]) / 3)
    return _component(f"Historical Stats ({pat}, n={st['n']})", "historical_stats", stance, strength,
                       f"Win rate {st['win_rate']}%, avg {STATS_HORIZON}d return {st['avg_return']:+.2f}% "
                       f"(median {st['median_return']:+.2f}%), expectancy {st['expectancy']:+.2f}%, "
                       f"MFE {st.get('mfe')}% / MAE {st.get('mae')}%")


def _quant_validation_component(current_patterns):
    """STEP 26: does the pattern's real recorded performance actually beat a
    random-entry baseline over the same universe and horizon, or is it
    statistically indistinguishable from noise?"""
    run = _bt.latest_run()
    if not run:
        return _component("Quantitative Baseline Validation", "quant_validation", "pending", 0,
                           "PENDING — no backtest has been run yet.")
    if not current_patterns:
        return _component("Quantitative Baseline Validation", "quant_validation", "pending", 0,
                           "No active pattern to validate.")
    baseline = _bt.baseline_stats("random_entry", STATS_HORIZON, run_id=run["id"])
    stats_by_pattern = _bt.pattern_stats_multi(current_patterns, STATS_HORIZON, run_id=run["id"])
    best = None
    for pat in current_patterns:
        st = stats_by_pattern.get(pat)
        if st and st["n"] > 0 and not st["low_sample"] and (best is None or st["n"] > best[1]["n"]):
            best = (pat, st)
    if not best or not baseline:
        return _component("Quantitative Baseline Validation", "quant_validation", "pending", 0,
                           "Insufficient sample to compare against the random-entry baseline.")
    pat, st = best
    edge = st["expectancy"] - baseline["expectancy"]
    stance = "bullish" if edge > 0.3 else "bearish" if edge < -0.3 else "neutral"
    strength = min(1.0, abs(edge) / 2)
    verdict_word = "YES" if edge > 0.3 else "NO" if edge < -0.3 else "UNCERTAIN"
    return _component(f"Quant Validation ({pat} vs random entry: {verdict_word})", "quant_validation",
                       stance, strength,
                       f"{pat} expectancy {st['expectancy']:+.2f}% vs random-entry baseline "
                       f"{baseline['expectancy']:+.2f}% (n={baseline['n']}) — edge {edge:+.2f}%")


def grade_from_score(score, n_bullish, n_bearish):
    """STEP 41 confidence grades. A/A+ reserved for genuinely unusual alignment
    (score alone is not enough — needs broad component agreement)."""
    dominant = max(n_bullish, n_bearish)
    if score >= 88 and dominant >= 7:
        return "A+"
    if score >= 78 and dominant >= 6:
        return "A"
    if score >= 65 and dominant >= 4:
        return "B"
    if score >= 50:
        return "C"
    if score >= 35:
        return "D"
    return "F"


_BULLISH_RANK = {"STRONG BUY": 0, "BUY": 1, "ACCUMULATE": 2, "WATCH FOR BUY": 3}


def action_from_evidence(score, n_bullish, n_bearish, rr, liquidity_ok, wyckoff_phase,
                          structural_veto=False, liquidity_tier=None, oos_negative=False):
    """STEP 42 final action states, now GATED not just additive (fixes the
    PRL-style failure: a confirmed/candidate Upthrust or Sign-of-Weakness
    inside a distribution-reading phase must cap the ceiling to WATCH FOR BUY
    regardless of how bullish other components look — an additive score
    alone let contradictory-but-outnumbered evidence produce BUY, which is
    exactly backwards for a gated hierarchy). Gates only ever RESTRICT a
    bullish claim, never loosen a bearish one.
    """
    net_bullish = n_bullish > n_bearish
    net_bearish = n_bearish > n_bullish
    accumulation = wyckoff_phase and "ACCUMULATION" in wyckoff_phase
    distribution = wyckoff_phase and any(k in wyckoff_phase for k in ("DISTRIBUTION", "MARKDOWN", "RE-DISTRIBUTION"))

    if net_bullish and score >= 78 and rr and rr >= 2 and liquidity_ok:
        action = "STRONG BUY"
    elif net_bullish and score >= 65:
        action = "BUY"
    elif net_bullish and accumulation and score >= 55:
        action = "ACCUMULATE"
    elif net_bullish and score >= 50:
        action = "WATCH FOR BUY"
    elif net_bearish and score <= 22 and distribution:
        action = "STRONG SELL / AVOID"
    elif net_bearish and score <= 35:
        action = "SELL / REDUCE"
    elif net_bearish and score <= 45:
        action = "WATCH FOR SELL"
    elif not liquidity_ok:
        action = "AVOID"
    else:
        action = "NEUTRAL"

    if action not in _BULLISH_RANK:
        return action  # gates below only restrict bullish claims, never bearish/neutral ones

    if liquidity_tier == "Very Illiquid":
        return "AVOID"
    if structural_veto:
        action = max(action, "WATCH FOR BUY", key=lambda a: _BULLISH_RANK[a])
    if rr is not None and rr < 1.5:
        action = max(action, "WATCH FOR BUY", key=lambda a: _BULLISH_RANK[a])
    if liquidity_tier == "Illiquid":
        action = max(action, "WATCH FOR BUY", key=lambda a: _BULLISH_RANK[a])
    if oos_negative:
        action = max(action, "WATCH FOR BUY", key=lambda a: _BULLISH_RANK[a])
    return action


def three_scenarios(quote, wy, verdict):
    tr = (wy or {}).get("trading_range") or {}
    support, resistance = tr.get("support"), tr.get("resistance")
    levels = (verdict.get("levels") or {}) if verdict and verdict.get("status") == "ok" else {}
    trigger, stop = levels.get("trigger"), levels.get("stop")
    price = quote.get("price") if quote else None
    return {
        "bullish": {
            "what_must_happen": (f"Break and hold above trigger {trigger}" if trigger else
                                  f"Break and hold above resistance {resistance}" if resistance else
                                  "Sustained demand above current structure"),
            "then": "Bullish continuation becomes more probable — not guaranteed.",
        },
        "base": {
            "what_must_happen": (f"Price remains between {support}–{resistance}" if support and resistance
                                  else "Price remains range-bound, no resolution"),
            "then": "No new trade until the range resolves.",
        },
        "bearish": {
            "what_must_happen": (f"Support {stop or support} breaks on expanding volume" if (stop or support)
                                  else "Structure breaks down"),
            "then": "The bullish thesis is weakened or invalidated.",
        },
        "current_price": price,
    }


def entry_engine(quote, wy, verdict):
    price = quote.get("price") if quote else None
    levels = (verdict.get("levels") or {}) if verdict and verdict.get("status") == "ok" else {}
    trigger = levels.get("trigger")
    tr = (wy or {}).get("trading_range") or {}
    resistance = tr.get("resistance")
    aggressive = price
    standard = trigger or resistance
    conservative = round(standard * 1.01, 2) if standard else None
    return {
        "aggressive": {"price": aggressive, "reason": "Current price — earlier entry, greater uncertainty."},
        "standard": {"price": standard, "reason": "At the trigger/resistance level — after reasonable confirmation."},
        "conservative": {"price": conservative, "reason": "After breakout + ~1% retest confirmation."},
    }


def stop_loss_sanity(verdict, technical):
    """STEP 45: structural stop (from psx_brain's verdict) checked against an
    ATR-based sanity band — never silently tightened to manufacture an
    attractive R:R. A stop under ~1x ATR is likely to be hit by normal noise;
    over ~5x ATR means the position size/thesis, not the stop, needs work."""
    if not verdict or verdict.get("status") != "ok" or not technical:
        return {"status": "unavailable"}
    levels = verdict.get("levels") or {}
    stop, price = levels.get("stop"), (technical.get("price") or 0)
    atr = technical.get("atr")
    if not stop or not price or not atr:
        return {"status": "unavailable"}
    stop_distance_pct = abs(price - stop) / price * 100
    atr_pct = atr / price * 100 if price else None
    atr_multiple = round(stop_distance_pct / atr_pct, 2) if atr_pct else None
    if atr_multiple is None:
        verdict_text = "Cannot assess — ATR unavailable."
    elif atr_multiple < 0.8:
        verdict_text = "Stop is TIGHTER than ~1x ATR — likely to be hit by normal noise, not a real invalidation."
    elif atr_multiple > 5:
        verdict_text = "Stop is WIDER than ~5x ATR — trade structure may be valid but risk is currently unattractive; the size, not the stop, should absorb this."
    else:
        verdict_text = "Stop distance is within a reasonable ATR-based sanity band."
    return {"status": "ok", "stop_distance_pct": round(stop_distance_pct, 2),
            "atr_pct_of_price": round(atr_pct, 2) if atr_pct else None, "atr_multiple": atr_multiple,
            "verdict": verdict_text}


def position_quality_score(n_bullish, n_bearish, rr, liquidity, stop_sanity, weekly_agrees):
    """STEP 48: a SEPARATE downstream score from the evidence score — setup
    quality (confluence direction strength), entry/stop quality, liquidity,
    reward/risk, and market alignment (weekly agreement), each 0-100,
    combined. Distinguishes "good evidence, bad trade structure" from
    "good evidence, good trade structure", which the evidence score alone
    doesn't separate."""
    total_components = n_bullish + n_bearish
    setup_quality = round(100 * abs(n_bullish - n_bearish) / total_components, 1) if total_components else 0

    stop_quality = 50
    if stop_sanity and stop_sanity.get("status") == "ok":
        m = stop_sanity.get("atr_multiple")
        stop_quality = 90 if (m and 1 <= m <= 3) else 60 if (m and 0.8 <= m <= 5) else 25

    liq_quality = round((liquidity or {}).get("confidence_multiplier", 0.5) * 100, 1)

    rr_quality = 0 if not rr else min(100, rr / 3 * 100)

    market_alignment = 70 if weekly_agrees else 40 if weekly_agrees is None else 20

    weights = {"setup": 0.30, "stop": 0.20, "liquidity": 0.20, "reward_risk": 0.20, "market_alignment": 0.10}
    total = (setup_quality * weights["setup"] + stop_quality * weights["stop"] +
             liq_quality * weights["liquidity"] + rr_quality * weights["reward_risk"] +
             market_alignment * weights["market_alignment"])
    return {"score": round(total, 1),
            "breakdown": {"setup_quality": setup_quality, "stop_quality": stop_quality,
                          "liquidity_quality": liq_quality, "reward_risk_quality": round(rr_quality, 1),
                          "market_alignment_quality": market_alignment},
            "note": "A separate downstream score from the Evidence Score (STEP 39) — this grades trade "
                    "STRUCTURE (entry/stop/liquidity/RR/alignment), not the underlying analytical case."}


def _matrix_lookup(d, key):
    return next((c for c in d.get("confluence_matrix", []) if c["key"] == key), None)


def format_formal_report(d):
    """STEP 61: the 16-part formal stock report, assembled entirely from an
    already-computed /dss/{symbol} result — pure formatting, no re-analysis,
    so the report can never say something the confluence matrix didn't."""
    sym = d.get("symbol", "?")
    q = d.get("quote") or {}
    wy = d.get("wyckoff") or {}
    v = d.get("verdict") or {}
    levels = v.get("levels") or {} if v.get("status") == "ok" else {}
    risk = d.get("risk") or {}
    ts = d.get("three_scenarios") or {}
    ee = d.get("entry_engine") or {}
    rs_multi = d.get("relative_strength_multi") or {}
    sstate = d.get("signal_state") or {}
    bt = _matrix_lookup(d, "wyckoff")
    hist = _matrix_lookup(d, "historical_stats")
    quant = _matrix_lookup(d, "quant_validation")
    cs = _matrix_lookup(d, "candlesticks")
    pa = _matrix_lookup(d, "price_action")
    macd_c = _matrix_lookup(d, "macd")
    obv_c = _matrix_lookup(d, "obv_divergence")
    mom_c = _matrix_lookup(d, "momentum_indicators")
    contradicting = [c for c in d.get("confluence_matrix", [])
                     if c["stance"] not in ("pending",) and
                     ((c["signed_points"] < 0) if (d.get("bullish_components", 0) >= d.get("bearish_components", 0))
                      else (c["signed_points"] > 0))]

    L = []
    L.append(f"# {sym}\n")
    L.append("## 1. FINAL VERDICT")
    L.append(f"**{d.get('final_action')}** — Confidence {d.get('evidence_score')}/100 — "
             f"Grade {d.get('confidence_grade')}\n")
    L.append("## 2. CURRENT MARKET STRUCTURE")
    L.append(f"- Trend: {(wy.get('structure') or {}).get('trend', '—')}")
    L.append(f"- Phase: {wy.get('phase', '—')}")
    L.append(f"- Wyckoff Event: {sstate.get('stage', '—')}\n")
    L.append("## 3. MARKET ALIGNMENT")
    mr = d.get("market_regime") or {}
    sr = d.get("sector_regime") or {}
    L.append(f"- KSE-100: {mr.get('label', '—')} (breadth {mr.get('breadth_pct', '—')}%)")
    L.append(f"- Sector: {sr.get('sector', '—')} (avg chg {sr.get('avg_change_pct', '—')}%)")
    L.append(f"- Stock: {q.get('pct', '—')}% today\n")
    L.append("## 4. WYCKOFF ANALYSIS")
    L.append(f"- Cycle/Phase: {wy.get('phase', '—')}")
    L.append(f"- Supply/Demand: {bt.get('detail') if bt else '—'}")
    sd = _matrix_lookup(d, "supply_demand")
    L.append(f"- Effort/Result: {sd.get('detail') if sd else '—'}")
    wev = d.get("wyckoff_events") or {}
    accum_seq = (wev.get("accumulation") or {}).get("sequence_found", [])
    distrib_seq = (wev.get("distribution") or {}).get("sequence_found", [])
    L.append(f"- Accumulation events detected: {', '.join(accum_seq) or 'none'}")
    L.append(f"- Distribution events detected: {', '.join(distrib_seq) or 'none'}")
    L.append("- Buying/Selling Tests: see /wyckoff-events/{symbol} for the full 9-test breakdown")
    L.append("")
    L.append("## 5. NISON CANDLESTICKS")
    L.append(f"- {cs.get('component') if cs else '—'}: {cs.get('detail') if cs else '—'}\n")
    L.append("## 6. BROOKS PRICE ACTION")
    L.append(f"- {pa.get('component') if pa else '—'}: {pa.get('detail') if pa else '—'}\n")
    L.append("## 7. BULKOWSKI-STYLE HISTORICAL STATISTICS")
    L.append(f"- {hist.get('detail') if hist else 'PENDING'}\n")
    L.append("## 8. GRIMES QUANTITATIVE VALIDATION")
    L.append(f"- {quant.get('detail') if quant else 'PENDING'}\n")
    L.append("## 9. MODERN INDICATORS")
    L.append(f"- {mom_c.get('detail') if mom_c else '—'}")
    L.append(f"- {macd_c.get('detail') if macd_c else '—'}")
    L.append(f"- {obv_c.get('detail') if obv_c else '—'}")
    vr = d.get("volatility_regime") or {}
    L.append(f"- ATR: {vr.get('atr', '—')} ({vr.get('regime', '—')} volatility regime)\n")
    L.append("## 10. RELATIVE STRENGTH")
    if rs_multi.get("status") == "ok":
        L.append(f"- Classification: {rs_multi.get('classification')}")
        L.append(f"- Weighted avg vs KSE-100: {rs_multi.get('weighted_avg_vs_index')}%")
    else:
        L.append("- Not enough true-OHLC history for multi-period relative strength.")
    L.append("")
    L.append("## 11. TRADE PLAN")
    L.append(f"- Aggressive Entry: {(ee.get('aggressive') or {}).get('price', '—')}")
    L.append(f"- Standard Entry: {(ee.get('standard') or {}).get('price', '—')}")
    L.append(f"- Conservative Entry: {(ee.get('conservative') or {}).get('price', '—')}")
    L.append(f"- Invalidation/Stop: {risk.get('invalidation', '—')}")
    L.append(f"- Target 1 / 2 / 3: {risk.get('target_1', '—')} / {risk.get('target_2', '—')} / "
             f"{risk.get('target_3', '—')}")
    L.append(f"- Reward/Risk: {risk.get('reward_risk', '—')}\n")
    L.append("## 12. THREE SCENARIOS")
    L.append(f"- Bullish: {(ts.get('bullish') or {}).get('what_must_happen', '—')}")
    L.append(f"- Base: {(ts.get('base') or {}).get('what_must_happen', '—')}")
    L.append(f"- Bearish: {(ts.get('bearish') or {}).get('what_must_happen', '—')}\n")
    L.append("## 13. WHAT WOULD CONFIRM THIS")
    L.append(f"- {(ts.get('bullish') or {}).get('then', '—')}\n")
    L.append("## 14. WHAT WOULD INVALIDATE THIS")
    L.append(f"- {(ts.get('bearish') or {}).get('then', '—')}\n")
    L.append("## 15. CONTRADICTORY EVIDENCE")
    if contradicting:
        for c in contradicting:
            L.append(f"- {c['component']} ({c['signed_points']:+.1f}): {c['detail']}")
    else:
        L.append("- None recorded against the dominant direction.")
    L.append("")
    L.append("## 16. FINAL SCORECARD")
    for c in d.get("confluence_matrix", []):
        sub = round((c["signed_points"] / c["weight"] * 5 + 5), 1) if c["weight"] and c["stance"] != "pending" else "—"
        L.append(f"- {c['component']}: {sub}/10")
    L.append(f"\n**FINAL EVIDENCE SCORE: {d.get('evidence_score')}/100**")
    L.append(f"**FINAL ACTION: {d.get('final_action')}**\n")
    L.append("---")
    L.append(d.get("note", ""))
    return "\n".join(L)


def compute(symbol, quote, regime, sector_row, rs, wy, technical, candles, verdict, decision_,
            weekly=None, event_risk=None, rs_multi=None, liquidity=None, data_quality=None, ohlc_rows=None):
    components = [
        _market_regime_component(regime),
        _sector_component(sector_row, quote.get("sector") if quote else None),
        _wyckoff_component(wy),
        _supply_demand_component(wy),
        _price_action_component(wy, technical),
        _candlestick_component(candles, ohlc_rows, wy, technical),
        _relative_strength_component(rs, rs_multi),
        _momentum_component(technical),
        _macd_component(technical),
        _obv_component(technical),
        _risk_reward_component(verdict),
        _weekly_structure_component(weekly),
    ]
    current_patterns = _current_patterns(wy, candles)
    components.append(_historical_stats_component(current_patterns))
    components.append(_quant_validation_component(current_patterns))

    scored = [c for c in components if c["stance"] != "pending"]
    pending = [c for c in components if c["stance"] == "pending"]
    n_bullish = sum(1 for c in scored if c["stance"] == "bullish")
    n_bearish = sum(1 for c in scored if c["stance"] == "bearish")
    raw = sum(c["signed_points"] for c in scored)
    score = round(max(0, min(100, 50 + raw)), 1)
    max_available = sum(c["weight"] for c in scored)

    # STEP 2-3: poor data quality or thin liquidity reduce confidence in
    # every downstream result — a cap and a multiplier, same pattern as the
    # event-risk cap, never silently hidden.
    if data_quality and data_quality.get("status") not in (None, "missing") and data_quality.get("score") is not None:
        dq_score = data_quality["score"]
        if dq_score < 70:
            score = min(score, 55.0)
        elif dq_score < 90:
            score = min(score, 80.0)
    liquidity_multiplier = (liquidity or {}).get("confidence_multiplier", 1.0)
    if liquidity_multiplier < 1.0:
        score = round(50 + (score - 50) * liquidity_multiplier, 1)

    risk_flag = _event_risk_penalty(event_risk)
    if risk_flag and risk_flag.get("score_cap") is not None and score > risk_flag["score_cap"]:
        score = float(risk_flag["score_cap"])

    rr = None
    if verdict and verdict.get("status") == "ok":
        rr = (verdict.get("levels") or {}).get("rr")
    liquidity_ok = bool(quote and quote.get("eligible"))
    wyckoff_phase = (wy or {}).get("phase")

    # STEP: hard structural gate — a confirmed/candidate Upthrust, or a phase
    # reading that's already distribution/markdown-leaning, must cap the
    # bullish ceiling regardless of how the additive score looks (the PRL
    # failure mode: Upthrust detected but other components still won BUY).
    upthrust_status = ((wy or {}).get("upthrust") or {}).get("status")
    structural_veto = bool(upthrust_status in ("CONFIRMED", "CANDIDATE") or
                           (wyckoff_phase and any(k in wyckoff_phase for k in
                                                  ("DISTRIBUTION", "MARKDOWN", "RE-DISTRIBUTION"))))
    liquidity_tier = (liquidity or {}).get("tier")

    # STEP 26/52: if the walk-forward cache says the active pattern's edge
    # reversed sign out-of-sample, don't let the score alone claim BUY.
    oos_negative = False
    wf_cached = _scan_cache.latest("walkforward")
    if wf_cached and current_patterns:
        for entry in wf_cached.get("out_of_sample_check", []):
            if entry.get("pattern") in current_patterns and not entry.get("test_low_sample") \
                    and entry.get("test_expectancy") is not None and entry["test_expectancy"] < 0:
                oos_negative = True
                break

    stop_sanity = stop_loss_sanity(verdict, technical)
    weekly_trend = (weekly or {}).get("structure", {}).get("trend", "") if weekly else ""
    weekly_agrees = (None if "UPTREND" not in weekly_trend and "DOWNTREND" not in weekly_trend
                     else (n_bullish >= n_bearish) == ("UPTREND" in weekly_trend))
    pos_quality = position_quality_score(n_bullish, n_bearish, rr, liquidity, stop_sanity, weekly_agrees)

    grade = grade_from_score(score, n_bullish, n_bearish)
    action = action_from_evidence(score, n_bullish, n_bearish, rr, liquidity_ok, wyckoff_phase,
                                   structural_veto=structural_veto, liquidity_tier=liquidity_tier,
                                   oos_negative=oos_negative)

    # Three genuinely different numbers (per the source framework and per
    # feedback that "confidence" was being used for three unrelated concepts):
    #   1. Evidence Score       — do the analytical engines agree right now?
    #   2. Historical OOS Edge  — what happened in comparable setups, held out?
    #   3. Calibrated Win Freq  — empirical win rate of the train-win-rate
    #                             bucket this pattern falls in, checked in TEST.
    historical_edge, calibrated_win_frequency = None, None
    if wf_cached and current_patterns:
        for entry in wf_cached.get("out_of_sample_check", []):
            if entry.get("pattern") in current_patterns and not entry.get("test_low_sample"):
                historical_edge = {"pattern": entry["pattern"], "oos_expectancy_pct": entry.get("test_expectancy"),
                                   "oos_win_rate_pct": entry.get("test_win_rate"), "n": entry.get("test_n"),
                                   "note": "Test-partition result — genuinely unseen data relative to the "
                                           "pattern's own training window."}
                break
        for calib_bin in wf_cached.get("calibration", []):
            if historical_edge and historical_edge["pattern"] in calib_bin.get("patterns", []):
                calibrated_win_frequency = {"predicted_from_train_pct": calib_bin.get("predicted_win_rate_from_train"),
                                            "actual_in_test_pct": calib_bin.get("actual_win_rate_in_test"),
                                            "n": calib_bin.get("test_n"),
                                            "note": "Empirical win rate of comparable-confidence setups in "
                                                    "held-out data — a frequency, not a guaranteed probability."}
                break

    gates = {"structural_veto": structural_veto, "rr_below_1_5": bool(rr is not None and rr < 1.5),
            "liquidity_tier": liquidity_tier, "oos_negative": oos_negative,
            "note": "Gates only ever CAP a bullish action (to WATCH FOR BUY or AVOID) — they never "
                    "upgrade one. A capped action means the additive evidence score alone would have "
                    "claimed more than the structure, risk, liquidity, or out-of-sample record supports."}

    return {
        "symbol": symbol,
        "quote": quote,
        "evidence_score": score,
        "evidence_score_label": "Evidence Score — how strongly current analytical engines agree, NOT a "
                                "probability of profit.",
        "historical_edge": historical_edge,
        "calibrated_win_frequency": calibrated_win_frequency,
        "gates": gates,
        "max_available_score": 100,
        "score_basis": f"{max_available}/100 weight available "
                        f"({len(pending)} layer(s) pending — see components marked 'pending')",
        "confidence_grade": grade,
        "final_action": action,
        "bullish_components": n_bullish,
        "bearish_components": n_bearish,
        "confluence_matrix": components,
        "three_scenarios": three_scenarios(quote, wy, verdict),
        "entry_engine": entry_engine(quote, wy, verdict),
        "risk": {
            "invalidation": (verdict.get("levels") or {}).get("stop") if verdict and verdict.get("status") == "ok" else None,
            "target_1": (verdict.get("levels") or {}).get("t1") if verdict and verdict.get("status") == "ok" else None,
            "target_2": (verdict.get("levels") or {}).get("t2") if verdict and verdict.get("status") == "ok" else None,
            "target_3": (verdict.get("levels") or {}).get("t3") if verdict and verdict.get("status") == "ok" else None,
            "reward_risk": rr,
            "liquidity_ok": liquidity_ok,
        },
        "market_regime": regime,
        "sector_regime": sector_row,
        "weekly_structure": weekly,
        "event_risk": risk_flag,
        "data_quality": data_quality,
        "liquidity": liquidity,
        "stop_loss_sanity": stop_sanity,
        "position_quality": pos_quality,
        "wyckoff": wy,
        "verdict": verdict,
        "decision": decision_,
        "note": "Hierarchy of evidence per the PSX Master Quantitative Technical Intelligence "
                "framework: market regime -> sector regime -> stock structure -> Wyckoff -> "
                "supply/demand -> candlesticks -> price action -> relative strength -> "
                "risk/reward -> final decision. Historical-statistics and quant-baseline-validation "
                "layers are explicitly PENDING, not fabricated. Never treat this score as a "
                "probability of profit.",
    }
