"""session_transition.py — Phase 14: carry PRE-FIRE setups from one
session's final minutes into the next session's open, and check whether
they transitioned to FIRE.
"""
from datetime import datetime, timedelta

from fire_engine.events import log_fire_event, query_fire_events


def detect_near_close_events(candles: list, prefire_results: list, cfg: dict) -> list:
    """candles/prefire_results: aligned (one detect_pre_fire() result per
    candle) for a single session, oldest first. cfg: whole loaded
    fire_config dict (needs session.near_close_minutes, market_close).

    Returns the subset of prefire_results whose timestamp falls within
    the final `near_close_minutes` of the session AND was itself detected
    (prefire_detected True) -- these are what gets logged as
    PRE_FIRE_NEAR_CLOSE and carried into check_session_transitions()."""
    near_close_minutes = cfg["session"]["near_close_minutes"]
    close_h, close_m = (int(x) for x in cfg["session"]["market_close"].split(":"))

    near_close = []
    for candle, result in zip(candles, prefire_results):
        dt = candle["datetime"] if isinstance(candle["datetime"], datetime) else datetime.fromisoformat(str(candle["datetime"]))
        close_dt = dt.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
        minutes_to_close = (close_dt - dt).total_seconds() / 60
        if 0 <= minutes_to_close <= near_close_minutes and result.get("prefire_detected"):
            near_close.append({
                "event_type": "PRE_FIRE_NEAR_CLOSE",
                "symbol": None,  # filled by caller
                "event_time": candle["datetime"],
                "mfi_value": None,  # filled by caller if available
                "price_level": candle["close"],
                "volume_condition": result.get("volume_condition"),
                "support_level": None,  # filled by caller if available
                "signal_strength": "STRONG" if result.get("prefire_score", 0) >= 60 else "MODERATE",
            })
    return near_close


def check_session_transitions(db, symbol: str, current_date: str, cfg: dict) -> dict:
    """Look up yesterday's PRE_FIRE_NEAR_CLOSE event(s) for `symbol` (most
    recent prior trading date with such an event, not necessarily
    calendar-yesterday) and check whether today's data shows FIRE
    confirmed and/or support held overnight.

    Returns:
    {had_near_close_setup, setup_type, support_held, mfi_continued,
     fire_confirmation: 'CONFIRMED'|'REJECTED'|'PENDING'}
    Caller (the daily batch) is responsible for having already logged
    today's FIRE events before calling this, so the FIRE lookup below can
    see them.
    """
    prior_events = query_fire_events(
        db, symbol=symbol, event_type="PRE_FIRE_NEAR_CLOSE", date_to=current_date,
    )
    prior_events = [e for e in prior_events if e["event_date"] < current_date]
    if not prior_events:
        return {
            "had_near_close_setup": False, "setup_type": None, "support_held": None,
            "mfi_continued": None, "fire_confirmation": "PENDING",
        }

    last_setup = prior_events[-1]
    prior_close = db.conn.execute(
        "SELECT close FROM market_candles WHERE symbol=? AND datetime=?",
        (symbol, last_setup["event_datetime"]),
    ).fetchone()

    today_open_row = db.conn.execute(
        "SELECT low, close FROM market_candles WHERE symbol=? AND date=? "
        "ORDER BY datetime ASC LIMIT 1",
        (symbol, current_date),
    ).fetchone()

    support_held = None
    if prior_close and today_open_row:
        support_held = today_open_row["low"] >= prior_close["close"] * 0.98  # within 2% -- a real
                                                                              # gap-down through the
                                                                              # setup level counts as
                                                                              # not held

    today_fire_events = query_fire_events(db, symbol=symbol, event_type="FIRE",
                                           date_from=current_date, date_to=current_date)
    if today_fire_events:
        fire_confirmation = "CONFIRMED"
    elif support_held is False:
        fire_confirmation = "REJECTED"
    else:
        fire_confirmation = "PENDING"

    return {
        "had_near_close_setup": True, "setup_type": "PRE_FIRE",
        "support_held": support_held, "mfi_continued": None,  # requires today's MFI series,
                                                                # left to the caller to fill in
                                                                # if it wants a stronger check
        "fire_confirmation": fire_confirmation,
    }
