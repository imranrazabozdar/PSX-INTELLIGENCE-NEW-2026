"""scheduler.py — Phase 17: the daily batch. Runs after PSX market close
(scheduled trigger is external -- see run_daily_batch.py and this
project's own GitHub Actions cron convention, e.g.
.github/workflows/refresh_chart_patterns.yml -- APScheduler is not used
here since every other scheduled job in this repo is already a GitHub
Actions cron, not a long-lived in-process scheduler).

Per-symbol, per-day:
  1. Fetch (scraper.fetch_daily_ohlcv) — real 1-minute OHLCV from SCS.
  2. Validate (validators.validate_trading_session) — never fabricates
     missing candles; logs the quality status either way.
  3. Store (database.DatabaseManager.insert_candles + upsert_session).
  4. Recompute this symbol's time-of-day volume baseline
     (volume_engine.calculate_time_of_day_baseline).
  5. Walk the session bar-by-bar computing MFI/relative-volume/
     compression/absorption/support-resistance/PRE-FIRE/FIRE/score, and
     log every PRE_FIRE/FIRE/ABSORPTION/near-close event
     (events.log_fire_event).
  6. Check session_transition.check_session_transitions() against
     yesterday's near-close setups.

Results land in fire_events (and daily_reports, kept for historical
detail) in the SAME database the caller passes in -- when that's the
shared Turso connection backend/app.py already uses, the Patterns tab's
/patterns/fire-scan endpoint sees this run's results immediately, no
separate report file to distribute.
"""
from datetime import datetime, timedelta

from fire_engine.scraper import fetch_daily_ohlcv
from fire_engine.validators import validate_trading_session
from fire_engine.mfi_engine import calculate_mfi, calculate_mfi_derivatives
from fire_engine.volume_engine import calculate_time_of_day_baseline, calculate_relative_volume
from fire_engine.compression import is_compression_active
from fire_engine.absorption import detect_bullish_absorption, detect_bearish_absorption
from fire_engine.pre_fire import detect_pre_fire
from fire_engine.fire_detector import detect_fire
from fire_engine.scoring import calculate_fire_score
from fire_engine.support_resistance import calculate_support_resistance
from fire_engine.events import log_fire_event
from fire_engine.session_transition import detect_near_close_events, check_session_transitions
from fire_engine.exclusions import filter_excluded_stocks, load_exclusions_from_config


def run_symbol_for_date(db, symbol: str, date: str, cfg: dict) -> dict:
    """Full pipeline for one symbol on one trading date. Returns a small
    summary dict; all detail is in the fire_events this writes."""
    candles = fetch_daily_ohlcv(symbol, date,
                                 max_retries=cfg["data_source"]["retry_attempts"],
                                 retry_delay=cfg["data_source"]["retry_delay_seconds"])
    if not candles:
        db.upsert_session(f"{symbol}:{date}", date, 0, cfg["session"]["expected_candles_per_day"], "NO_DATA")
        return {"symbol": symbol, "date": date, "status": "NO_DATA", "events_logged": 0}

    validation = validate_trading_session(symbol, candles, cfg["session"]["expected_candles_per_day"])
    # trading_sessions row must exist BEFORE inserting candles that reference
    # it via market_candles.session_id's FOREIGN KEY -- inserting candles
    # first (the original order here) violated that constraint on every
    # symbol with real data in the first production run.
    db.upsert_session(f"{symbol}:{date}", date, validation["total_candles"],
                       validation["expected_candles"], validation["quality_status"])
    db.insert_candles(symbol, candles, session_id=f"{symbol}:{date}",
                       data_quality_status=validation["quality_status"])
    if not validation["is_valid"]:
        return {"symbol": symbol, "date": date, "status": validation["quality_status"],
                "events_logged": 0, "issues": validation["issues"][:10]}

    calculate_time_of_day_baseline(db, symbol, cfg["volume"]["lookback_sessions"])

    mfi_series = calculate_mfi(candles, length=cfg["mfi"]["length"])
    sr_cfg = cfg["support_resistance"]

    events_logged = 0
    prefire_results = []
    fire_history = []
    for i in range(len(candles)):
        window = candles[: i + 1]
        mfi_window = mfi_series[: i + 1]
        deriv = calculate_mfi_derivatives(mfi_window)

        rv_result = calculate_relative_volume(db, symbol, candles[i]["time_of_day"], candles[i]["volume"], cfg["volume"])
        rv = rv_result["relative_volume"]

        pf = detect_pre_fire(window, mfi_window, deriv, rv, cfg)
        prefire_results.append(pf)
        if pf["prefire_detected"]:
            log_fire_event(db, symbol, "PRE_FIRE", str(candles[i]["datetime"]),
                            mfi_value=mfi_window[-1], mfi_acceleration_5m=deriv["delta_5"],
                            mfi_acceleration_15m=deriv["delta_15"], volume_condition=pf["volume_condition"],
                            relative_volume=rv, fire_score=pf["prefire_score"])
            events_logged += 1

        fr = detect_fire(window, mfi_window, rv, prefire_results, cfg)
        if fr["fire_detected"]:
            fire_history.append(fr)
            sr = calculate_support_resistance(window, sr_cfg)
            score = calculate_fire_score(
                mfi_acceleration=deriv["delta_15"] or 0, mfi_persistence=deriv["persistence"],
                price_compression_active=is_compression_active(window, cfg["compression"]),
                absorption_score=0, support_strength=sr["level_strength"],
                volume_expansion=fr["volume_expansion"], breakout_confirmed=fr["breakout_confirmed"],
                cfg=cfg,
            )
            log_fire_event(db, symbol, "FIRE", str(candles[i]["datetime"]),
                            mfi_value=mfi_window[-1], mfi_acceleration_15m=deriv["delta_15"],
                            volume_condition="ABNORMAL_OR_ABOVE", relative_volume=rv,
                            fire_score=score["total_score"],
                            notes=f"rating={score['rating']} confidence={score['confidence']}")
            events_logged += 1

        if rv is not None and len(window) >= cfg["absorption"]["lookback_minutes"]:
            bull = detect_bullish_absorption(window, rv, mfi_window, cfg["absorption"], sr_cfg)
            bear = detect_bearish_absorption(window, rv, mfi_window, cfg["absorption"], sr_cfg)
            if bull["absorption_detected"]:
                log_fire_event(db, symbol, "ABSORPTION_BULLISH", str(candles[i]["datetime"]),
                                mfi_value=mfi_window[-1], volume_condition=bull["volume_condition"],
                                relative_volume=rv, price_compression_pct=bull["price_compression_pct"],
                                fire_score=int(bull["absorption_score"]))
                events_logged += 1
            if bear["absorption_detected"]:
                log_fire_event(db, symbol, "ABSORPTION_BEARISH", str(candles[i]["datetime"]),
                                mfi_value=mfi_window[-1], volume_condition=bear["volume_condition"],
                                relative_volume=rv, price_compression_pct=bear["price_compression_pct"],
                                fire_score=int(bear["absorption_score"]))
                events_logged += 1

    near_close = detect_near_close_events(candles, prefire_results, cfg)
    for nc in near_close:
        log_fire_event(db, symbol, "PRE_FIRE_NEAR_CLOSE", str(nc["event_time"]),
                        volume_condition=nc["volume_condition"], near_close=True,
                        notes=f"signal_strength={nc['signal_strength']}")
        events_logged += 1

    transition = check_session_transitions(db, symbol, date, cfg)

    return {
        "symbol": symbol, "date": date, "status": validation["quality_status"],
        "events_logged": events_logged, "fire_count": len(fire_history),
        "prefire_count": sum(1 for p in prefire_results if p["prefire_detected"]),
        "session_transition": transition,
    }


def _default_progress(msg):
    print(msg, flush=True)  # flush explicitly -- stdout piped to a GitHub
                             # Actions log (not a tty) is block-buffered by
                             # default, which would otherwise silently
                             # defeat the entire point of per-symbol
                             # progress: nothing would show up until the
                             # buffer filled or the process exited.


def run_daily_batch(db, cfg: dict, date: str = None, progress=_default_progress) -> dict:
    """Entry point: run every non-excluded configured symbol for `date`
    (defaults to yesterday, since this always runs after that day's
    close). Returns {date, results: [per-symbol summaries]}.

    `progress` is called once per symbol as it finishes (default: print),
    so an unattended run (GitHub Actions) shows live per-symbol progress
    in its log instead of only a summary at the very end -- the
    difference between "the log went quiet for 20 minutes, is it stuck?"
    and being able to see exactly which symbol it's on."""
    if date is None:
        date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    universe = cfg["stocks"]["universe"]
    if cfg["exclusion"]["enabled"]:
        excluded = load_exclusions_from_config()
        universe = filter_excluded_stocks(universe, excluded)

    results = []
    for i, symbol in enumerate(universe, 1):
        try:
            r = run_symbol_for_date(db, symbol, date, cfg)
        except Exception as exc:
            r = {"symbol": symbol, "date": date, "status": "ERROR", "error": str(exc)}
        results.append(r)
        progress(f"[{i}/{len(universe)}] {symbol}: status={r['status']} "
                 f"events={r.get('events_logged', 0)} fire={r.get('fire_count', 0)} "
                 f"prefire={r.get('prefire_count', 0)}"
                 + (f" ERROR={r.get('error')}" if r["status"] == "ERROR" else ""))

    return {"date": date, "results": results}
