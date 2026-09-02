"""patterns_engine.py — manual candlestick pattern detectors, starting with
Bullish Engulfing on the 1-Day timeframe only.

Pure Python (stdlib + data_quality_engine, itself dependency-free), no
database/network dependency, so every detector here is independently
unit-testable (see test_patterns_engine.py) without a live backend.
`backend/app.py` wires the actual daily_ohlc rows into this module and
exposes it over HTTP; the Streamlit "Patterns" tab calls that endpoint.

Reference: Steve Nison's classical Bullish Engulfing description (real
bodies only -- wicks/shadows are deliberately NOT required to engulf) for
STRICT/BOUNDARY_MATCH geometry. The prior-downtrend check is a SEPARATE,
clearly-labeled AUTOMATION TREND HEURISTIC V2 -- an implementation choice,
not Nison's rule, and not a claim of equivalence to an experienced trader's
visual judgment (see `_prior_downtrend`). V2 replaced V1's discrete
2-of-3-moves rule after a dedicated validation study (11,696 real PSX
occurrences) found V1 mis-flagged trend context on single-tick noise at
either edge of its window; V2 uses an OLS regression slope over a slightly
wider window instead. Geometry classification is unaffected either way.

This module intentionally does NOT add trading strategy, targets, stop
losses, indicator filters, volume filters, or scoring -- it answers exactly
one question per pattern: is a valid instance of that pattern present on
the latest completed daily candles, yes or no. Data-quality reuse below
(zero-volume/stale-bar and large-gap flags) only ever affects the
prior-downtrend CONTEXT or adds an informational flag -- it never changes
geometry classification.

Adding a future pattern (Morning Star, Hammer, Piercing Pattern, Harami,
Three White Soldiers, ...): reuse `normalize_daily_ohlc` for preprocessing,
keep pure candle-geometry logic separate from pattern-context logic (like
`_prior_downtrend` below) the same way this module does, and return a dict
with at least {"pattern", "timeframe", "detected", "classification"} so
every detector's output shape stays predictable to callers.
"""

from datetime import date as _date, datetime as _datetime, time as _time, timedelta as _timedelta
from zoneinfo import ZoneInfo

import data_quality_engine as _dq

PATTERN_NAME = "Bullish Engulfing"
TIMEFRAME = "1D"

# Final classification labels
VALID_BULLISH_ENGULFING = "VALID_BULLISH_ENGULFING"
ENGULFING_GEOMETRY_ONLY = "ENGULFING_GEOMETRY_ONLY"
NO_BULLISH_ENGULFING = "NO_BULLISH_ENGULFING"

# Geometry labels -- STRICT is the primary classical Nison geometry;
# BOUNDARY_MATCH is a separate, weaker boundary-equality case (see
# _classify_geometry). Never conflate the two in downstream reporting.
STRICT = "STRICT"
BOUNDARY_MATCH = "BOUNDARY_MATCH"

# PSX prices settle in Rupees and Paisa (2 decimal places). Yahoo's feed
# carries float32-derived representation noise (e.g. 330.9700012207031),
# which breaks exact `==` boundary comparisons even when the true quoted
# prices are identical. Rounding to this fixed decimal count is
# deterministic normalization back to the exchange's actual quoted
# precision -- NOT an arbitrary percentage/epsilon tolerance.
PSX_PRICE_DECIMALS = 2

# Asia/Karachi, PKT, UTC+5 year-round (Pakistan does not observe DST) --
# matches PSX_TZ as already defined/used in backend/app.py. Duplicated here
# (rather than imported) because app.py imports this module, not the
# reverse; if PSX's official close times below ever change, update both
# this table and app.py's WATCHLIST_HOURS_PKT together.
PSX_TZ = ZoneInfo("Asia/Karachi")
_PSX_CLOSE_PKT = {0: (15, 30), 1: (15, 30), 2: (15, 30), 3: (15, 30), 4: (16, 30)}  # Mon=0..Fri=4; Sat/Sun: no session


def _parse_date(value):
    """Accepts a date, datetime, or a string starting with YYYY-MM-DD.
    Returns a date object, or None if it can't be parsed -- callers treat
    None as "drop this row" rather than raising."""
    if isinstance(value, _datetime):
        return value.date()
    if isinstance(value, _date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return _date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _to_float(value):
    """Parses to float and rounds to PSX_PRICE_DECIMALS -- see that
    constant's docstring for why this is deterministic normalization, not a
    tolerance."""
    if value is None:
        return None
    try:
        return round(float(value), PSX_PRICE_DECIMALS)
    except (TypeError, ValueError):
        return None


def _effective_as_of_date(now_pkt):
    """The latest PSX daily candle becomes eligible for analysis once that
    day's session has actually closed; before close (or on a non-trading
    day), today's date stays excluded as still-forming/not-yet-open."""
    close_hm = _PSX_CLOSE_PKT.get(now_pkt.weekday())
    if close_hm is not None and now_pkt.time() >= _time(*close_hm):
        return now_pkt.date() + _timedelta(days=1)
    return now_pkt.date()


def _resolve_as_of_date(as_of):
    """Shared by normalize_daily_ohlc and detect_bullish_engulfing's own
    raw-validity pre-check, so both always agree on the exact same cutoff
    date -- see detect_bullish_engulfing for why that matters."""
    if as_of is not None:
        return _parse_date(as_of)
    return _effective_as_of_date(_datetime.now(PSX_TZ))


def normalize_daily_ohlc(rows, date_key="trade_date", as_of=None):
    """Cleans a raw list of OHLC row dicts into an ascending-by-date list of
    {"date": date, "open": float, "high": float, "low": float,
    "close": float} dicts, ready for pattern detection. Never raises --
    malformed input is dropped, not crashed on.

    Handles:
      - missing/non-numeric OHLC fields -> row dropped
      - unparseable/missing date -> row dropped
      - duplicate dates -> keeps the LAST occurrence in input order for a
        given date (treated as the more authoritative/overwritten value)
      - unsorted input -> always returned sorted ascending by date
      - an unfinished "current session" candle -> excluded until the PSX
        session for that date has actually closed (Asia/Karachi, see
        _effective_as_of_date); `as_of` overrides this for testing/replay.
    """
    if not rows:
        return []
    as_of_date = _resolve_as_of_date(as_of)

    by_date = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        d = _parse_date(row.get(date_key))
        if d is None:
            continue
        o = _to_float(row.get("open"))
        h = _to_float(row.get("high"))
        l = _to_float(row.get("low"))
        c = _to_float(row.get("close"))
        if None in (o, h, l, c):
            continue
        by_date[d] = {"date": d, "open": o, "high": h, "low": l, "close": c}

    cleaned = sorted(by_date.values(), key=lambda r: r["date"])
    if as_of_date is not None:
        cleaned = [r for r in cleaned if r["date"] < as_of_date]
    return cleaned


def _raw_dedup_by_date(rows, date_key):
    """Same date parsing/dedup (last occurrence wins) as
    normalize_daily_ohlc, but WITHOUT dropping invalid OHLC -- used only to
    check whether the latest REQUIRED candles (Candle 1, Candle 2) are
    themselves valid before normalize_daily_ohlc's silent drop can ever
    substitute an older candle in their place (see detect_bullish_engulfing)."""
    by_date = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        d = _parse_date(row.get(date_key))
        if d is None:
            continue
        by_date[d] = row
    return by_date


def _row_ohlc_valid(row):
    o, h, l, c = (_to_float(row.get(k)) for k in ("open", "high", "low", "close"))
    return None not in (o, h, l, c)


def _classify_geometry(c1, c2):
    """Steve Nison's classical Bullish Engulfing, real-bodies only --
    Candle 2's high/low are NOT required to engulf Candle 1's shadows.
    Returns STRICT (the primary classical geometry), BOUNDARY_MATCH (a
    separate, weaker boundary-equality case), or None (no engulfing
    geometry). Prices are already PSX-precision-normalized by _to_float
    before this ever runs, so `==` here is a deterministic comparison, not
    raw float equality on unnormalized data."""
    bearish1 = c1["close"] < c1["open"]
    bullish2 = c2["close"] > c2["open"]
    if not (bearish1 and bullish2):
        return None

    open2, close2, open1, close1 = c2["open"], c2["close"], c1["open"], c1["close"]
    if open2 < close1 and close2 > open1:
        return STRICT
    if (open2 == close1 and close2 > open1) or (open2 < close1 and close2 == open1):
        return BOUNDARY_MATCH
    return None


PRIOR_DOWNTREND_WINDOW = 5  # AUTOMATION TREND HEURISTIC V2's lookback, in closes (idx1-4..idx1)
PRIOR_DOWNTREND_SLOPE_THRESHOLD_PCT = 0.001  # -0.1% of the window's mean close, per session


def _prior_downtrend(candles, idx1):
    """AUTOMATION TREND HEURISTIC V2 -- an implementation choice, NOT part
    of Steve Nison's original text (Nison describes the preceding-downtrend
    requirement qualitatively, with no numerical rule) and NOT a claim that
    this reproduces how an experienced trader would visually judge a prior
    decline.

    SUPERSEDES V1 (a discrete "≥2 of 3 close-to-close moves negative AND
    close[idx1] < close[idx1-3]" rule over a 4-close window). A dedicated
    validation study (11,696 real PSX Bullish Engulfing geometry
    occurrences, full local history) found V1 produced two real, opposite
    failure modes at scale, both traceable to its narrow discrete window
    being flipped by a single edge-tick: ~1,144 false negatives (rejecting
    a visually obvious, ongoing decline that merely paused for one tick
    right before Candle 1) and ~615 false positives (flagging flat/
    range-bound noise as a decline because of one stray 2-of-3 wiggle). Of
    the alternative methods compared in that study, a smooth OLS
    regression slope over a slightly wider window showed near-total data
    coverage (matching V1's) and was immune to single-tick sensitivity by
    construction -- V2 adopts that method's exact validated parameters.

    Rule: fit an ordinary-least-squares line through the PRIOR_DOWNTREND_
    WINDOW (5) closes ending at Candle 1's own close (indices idx1-4
    through idx1, closes vs. session index). Consider a prior decline
    present when the fitted slope is more negative than
    -PRIOR_DOWNTREND_SLOPE_THRESHOLD_PCT (0.1%) of the window's mean close,
    per session -- a fixed, price-scaled significance threshold (not a
    tuned/arbitrary tolerance) that keeps near-flat noise from reading as
    "declining".

    Returns True/False, or None if there isn't enough history
    (idx1 - 4 < 0) to evaluate it at all -- callers treat None as "not
    confirmed" rather than guessing.
    """
    if idx1 - (PRIOR_DOWNTREND_WINDOW - 1) < 0:
        return None
    closes = [candles[i]["close"] for i in range(idx1 - (PRIOR_DOWNTREND_WINDOW - 1), idx1 + 1)]
    n = len(closes)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(closes) / n
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, closes))
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    if variance_x == 0:
        return False
    slope = covariance / variance_x
    return slope < (-PRIOR_DOWNTREND_SLOPE_THRESHOLD_PCT * mean_y)


def _data_quality_flags(candles, idx1, idx2, raw_by_date):
    """Reuses the existing data_quality_engine.audit() (STEP 2's stale/
    zero-volume-session and large-gap detection) at this validation layer --
    NOT a new staleness rule invented here. Geometry is never touched.
    Returns (trend_context_reliable, possible_corporate_action_gap):
      - trend_context_reliable: False if the PRIOR_DOWNTREND_WINDOW-candle
        AUTOMATION TREND HEURISTIC V2 window (idx1-4..idx1) contains a
        zero-volume or internally-impossible OHLC bar per
        data_quality_engine -- None if that window isn't available
        (insufficient history) or the check itself errors, True otherwise.
        detect_bullish_engulfing treats False the same as "downtrend not
        confirmed".
      - possible_corporate_action_gap: True if data_quality_engine flags a
        >=15% close-to-close gap landing on Candle 2's own date. This is a
        GAP-SIZE flag only, not a confirmed corporate-action diagnosis --
        this codebase has no split/bonus/rights database to check against
        (see data_quality_engine.py's own docstring); that is a known,
        unresolved limitation, not something invented or guessed here.
    """
    trend_context_reliable = None
    if idx1 - (PRIOR_DOWNTREND_WINDOW - 1) >= 0:
        window = [candles[i] for i in range(idx1 - (PRIOR_DOWNTREND_WINDOW - 1), idx1 + 1)]
        volumes = [raw_by_date.get(c["date"], {}).get("volume") for c in window]
        volume_data_available = any(v is not None for v in volumes)
        try:
            audit_rows = [{"trade_date": c["date"].isoformat(), "open": c["open"], "high": c["high"],
                           "low": c["low"], "close": c["close"], "volume": v}
                          for c, v in zip(window, volumes)]
            issues = _dq.audit(audit_rows).get("issues", {})
            # zero_volume_sessions is only a meaningful signal when this
            # input actually carries volume data at all -- data_quality_
            # engine.audit() treats a MISSING volume field the same as a
            # genuine zero (x.get("volume") or 0), which would otherwise
            # wrongly flag every volume-less caller (e.g. tests, or any
            # source that doesn't provide "volume") as unreliable.
            unreliable = issues.get("impossible_ohlc", 0) > 0
            if volume_data_available:
                unreliable = unreliable or issues.get("zero_volume_sessions", 0) > 0
            trend_context_reliable = not unreliable
        except Exception:
            trend_context_reliable = None

    possible_ca_gap = False
    try:
        c1, c2 = candles[idx1], candles[idx2]
        gap_rows = [{"trade_date": c1["date"].isoformat(), "open": c1["open"], "high": c1["high"],
                     "low": c1["low"], "close": c1["close"], "volume": raw_by_date.get(c1["date"], {}).get("volume")},
                    {"trade_date": c2["date"].isoformat(), "open": c2["open"], "high": c2["high"],
                     "low": c2["low"], "close": c2["close"], "volume": raw_by_date.get(c2["date"], {}).get("volume")}]
        gap_issues = _dq.audit(gap_rows).get("issues", {})
        possible_ca_gap = c2["date"].isoformat() in {g["date"] for g in gap_issues.get("large_gaps", [])}
    except Exception:
        possible_ca_gap = False

    return trend_context_reliable, possible_ca_gap


def _empty_result():
    """The exact minimal shape for every non-detection: no engulfing
    geometry at all, invalid/missing required OHLC, or not enough valid
    data to even check."""
    return {"pattern": PATTERN_NAME, "timeframe": TIMEFRAME, "detected": False,
            "classification": NO_BULLISH_ENGULFING}


def _select_latest_completed_pair(rows, date_key, as_of):
    """Shared completed-candle SELECTION, used by BOTH
    detect_bullish_engulfing and talib_cross_check so the two always agree
    on exactly which two candles are "the latest completed pair" -- same
    PSX_TZ/effective-as-of cutoff (see _resolve_as_of_date), and the same
    refusal to silently substitute an older pair when the true latest
    required candle(s) are invalid/missing. Returns
    (candles, idx1, idx2, raw_by_date), or None if there's no valid latest
    pair to select."""
    try:
        as_of_date = _resolve_as_of_date(as_of)
        raw_by_date = _raw_dedup_by_date(rows, date_key) if rows else {}
    except Exception:
        return None

    eligible_dates = sorted(d for d in raw_by_date if as_of_date is None or d < as_of_date)
    if len(eligible_dates) < 2:
        return None

    date1, date2 = eligible_dates[-2], eligible_dates[-1]
    if not (_row_ohlc_valid(raw_by_date[date1]) and _row_ohlc_valid(raw_by_date[date2])):
        return None  # invalid latest required candle(s) -- no silent fallback to an older pair

    try:
        candles = normalize_daily_ohlc(rows, date_key=date_key, as_of=as_of_date)
    except Exception:
        return None

    if len(candles) < 2 or candles[-1]["date"] != date2 or candles[-2]["date"] != date1:
        return None  # defensive: should be unreachable given the validity check above

    idx2 = len(candles) - 1
    idx1 = idx2 - 1
    return candles, idx1, idx2, raw_by_date


def detect_bullish_engulfing(rows, date_key="trade_date", as_of=None):
    """Main entry point.

    `rows`: list of dicts shaped like {date_key: ..., "open": ..., "high":
    ..., "low": ..., "close": ..., "volume": ...} -- e.g. straight from
    backend.app.ohlc_rows() ("volume" is optional; used only for the
    data-quality reuse below, never for geometry). `date_key` defaults to
    "trade_date" to match that shape.
    `as_of`: date/datetime/ISO-string to treat as "now" for the completed-
    candle cutoff; defaults to the real current Asia/Karachi time.

    Never raises. Uses only completed daily PSX candles, and never looks
    past the latest completed candle (no future information). If the two
    most recent ELIGIBLE dates are not both valid OHLC, this returns a safe
    no-detection result rather than silently falling back to an older pair.
    """
    selected = _select_latest_completed_pair(rows, date_key, as_of)
    if selected is None:
        return _empty_result()
    candles, idx1, idx2, raw_by_date = selected
    c1, c2 = candles[idx1], candles[idx2]

    geometry = _classify_geometry(c1, c2)
    if geometry is None:
        return _empty_result()

    downtrend = _prior_downtrend(candles, idx1)
    trend_context_reliable, possible_ca_gap = _data_quality_flags(candles, idx1, idx2, raw_by_date)
    if trend_context_reliable is False:
        downtrend = False  # stale/zero-volume bar in the trend window -> don't confirm a downtrend on it
    downtrend_confirmed = bool(downtrend)  # None (insufficient history) -> not confirmed

    classification = VALID_BULLISH_ENGULFING if downtrend_confirmed else ENGULFING_GEOMETRY_ONLY
    result = {
        "pattern": PATTERN_NAME,
        "timeframe": TIMEFRAME,
        "detected": classification == VALID_BULLISH_ENGULFING,
        "classification": classification,
        "geometry": geometry,
        "prior_downtrend": downtrend_confirmed,
        "pattern_date": c2["date"].isoformat(),
    }
    if trend_context_reliable is False:
        result["trend_context_data_quality"] = "stale_or_zero_volume_detected"
    if possible_ca_gap:
        result["possible_corporate_action_gap"] = True
    return result


# ============================================================================
# Bearish Engulfing -- mirror of detect_bullish_engulfing above, for the
# short side of PSX's mean-reverting microstructure.
#
# ARCHITECTURE NOTE -- one remaining deliberate departure from this
# module's own stated design philosophy, per explicit spec, flagged
# rather than silently introduced: this module's docstring states it
# "intentionally does NOT add trading strategy, targets, stop losses,
# indicator filters, volume filters, or scoring". detect_bearish_engulfing
# below adds exactly those things (ATR-based stop/targets, a volume
# filter, a swing-high/resistance filter) because the spec for this
# function explicitly requires them. detect_bullish_engulfing is
# UNCHANGED -- it remains pure geometry-plus-trend-context, per the
# module's original design.
#
# PATCH (round 2): the prior-trend check is now the EXACT inverted mirror
# of _prior_downtrend's validated OLS-regression-slope heuristic (V2),
# not the simple trailing-count rule round 1 used -- see _prior_uptrend
# below, which reuses PRIOR_DOWNTREND_WINDOW/PRIOR_DOWNTREND_SLOPE_
# THRESHOLD_PCT directly rather than inventing separate constants, since
# "exact mirror" means the same window/threshold, sign flipped.
# ============================================================================

PATTERN_NAME_BEARISH = "Bearish Engulfing"
VALID_BEARISH_ENGULFING = "VALID_BEARISH_ENGULFING"
BEARISH_ENGULFING_GEOMETRY_ONLY = "BEARISH_ENGULFING_GEOMETRY_ONLY"
NO_BEARISH_ENGULFING = "NO_BEARISH_ENGULFING"

VOLUME_AVG_WINDOW = 20
VOLUME_MIN_RATIO_DAY2 = 1.3
SWING_HIGH_WINDOW = 20
NEAR_RESISTANCE_MAX_PCT = 3.0     # Day 1's high within this % of the swing high
STOP_LOSS_ATR_MULTIPLIER = 0.5
STOP_LOSS_MIN_BUFFER_PCT = 0.005  # ATR floor, same protection as morning_star_detector.py's
ATR_WINDOW = 14


def _classify_geometry_bearish(c1, c2):
    """Mirror of _classify_geometry, inverted direction. The spec's own
    inequalities (Opens >= Day1 Close, Closes <= Day1 Open) are already
    boundary-inclusive, so -- unlike the bullish STRICT/BOUNDARY_MATCH
    two-tier split -- a single label covers the full rule as given; no
    separate boundary-equality tier was requested or added."""
    bullish1 = c1["close"] > c1["open"]
    bearish2 = c2["close"] < c2["open"]
    if not (bullish1 and bearish2):
        return None
    open2, close2, open1, close1 = c2["open"], c2["close"], c1["open"], c1["close"]
    if open2 >= close1 and close2 <= open1:
        return STRICT
    return None


def _prior_uptrend(candles, idx1):
    """PATCH (round 2): EXACT inverted mirror of _prior_downtrend -- same
    PRIOR_DOWNTREND_WINDOW (5 closes ending at Day 1's own close), same
    OLS regression slope, same PRIOR_DOWNTREND_SLOPE_THRESHOLD_PCT
    magnitude, sign flipped: a prior uptrend is present when the fitted
    slope is MORE POSITIVE than +PRIOR_DOWNTREND_SLOPE_THRESHOLD_PCT of
    the window's mean close, per session. Reuses _prior_downtrend's exact
    validated parameters rather than inventing separate ones, since
    "exact mirror" means the same window/threshold, not a different rule.

    Returns True/False, or None if there isn't enough history
    (idx1 - 4 < 0) to evaluate it at all -- same contract as
    _prior_downtrend."""
    if idx1 - (PRIOR_DOWNTREND_WINDOW - 1) < 0:
        return None
    closes = [candles[i]["close"] for i in range(idx1 - (PRIOR_DOWNTREND_WINDOW - 1), idx1 + 1)]
    n = len(closes)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(closes) / n
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, closes))
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    if variance_x == 0:
        return False
    slope = covariance / variance_x
    return slope > (PRIOR_DOWNTREND_SLOPE_THRESHOLD_PCT * mean_y)


def _avg_volume_20(candles, raw_by_date, end_idx):
    """20-session average volume, strictly BEFORE end_idx (so Day 2's own
    volume spike never inflates the baseline it's compared against --
    same rationale as morning_star_detector.py's avg_volume_20). Returns
    None if there isn't a full 20-session window available, or any
    session in that window is missing a volume value -- never guesses."""
    if end_idx - VOLUME_AVG_WINDOW < 0:
        return None
    vols = []
    for i in range(end_idx - VOLUME_AVG_WINDOW, end_idx):
        raw = raw_by_date.get(candles[i]["date"], {})
        v = raw.get("volume") if isinstance(raw, dict) else None
        if v is None:
            return None
        try:
            vols.append(float(v))
        except (TypeError, ValueError):
            return None
    return sum(vols) / len(vols) if vols else None


def _swing_high_20(candles, end_idx):
    """Highest `high` over the SWING_HIGH_WINDOW (20) sessions ending at
    end_idx INCLUSIVE (Day 1 itself can be the swing high -- e.g. a
    blow-off top that Day 2 then reverses). Returns None if there isn't a
    full 20-session window available."""
    if end_idx - (SWING_HIGH_WINDOW - 1) < 0:
        return None
    return max(candles[i]["high"] for i in range(end_idx - (SWING_HIGH_WINDOW - 1), end_idx + 1))


def _atr14(candles, end_idx):
    """Simple (not Wilder-smoothed) mean True Range over ATR_WINDOW (14)
    sessions ending at end_idx INCLUSIVE -- same deliberate simplification
    already used in morning_star_detector.py/advanced_pattern_engine.py,
    for consistency across this codebase's several independent ATR
    implementations. Returns None if there isn't a full 14-session
    window (plus one prior close) available."""
    if end_idx - (ATR_WINDOW - 1) < 1:
        return None
    trs = []
    for i in range(end_idx - (ATR_WINDOW - 1), end_idx + 1):
        prev_close = candles[i - 1]["close"]
        tr = max(candles[i]["high"] - candles[i]["low"],
                  abs(candles[i]["high"] - prev_close),
                  abs(candles[i]["low"] - prev_close))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else None


def _empty_result_bearish():
    return {"pattern": PATTERN_NAME_BEARISH, "timeframe": TIMEFRAME, "detected": False,
            "classification": NO_BEARISH_ENGULFING}


def detect_bearish_engulfing(rows, date_key="trade_date", as_of=None):
    """Bearish mirror of detect_bullish_engulfing -- see the module-level
    ARCHITECTURE NOTE above for the two deliberate departures from this
    module's stated no-filters/no-strategy design philosophy, both
    required by the exact spec this was built against.

    `rows` must include "volume" for the volume filter to ever confirm
    (missing volume anywhere in the required window -> that filter simply
    never passes, the same fail-closed posture as every other filter
    here); geometry/trend detection still runs without it.

    Never raises. Uses the exact same completed-candle SELECTION as
    detect_bullish_engulfing (_select_latest_completed_pair, reused
    verbatim, not reimplemented).
    """
    selected = _select_latest_completed_pair(rows, date_key, as_of)
    if selected is None:
        return _empty_result_bearish()
    candles, idx1, idx2, raw_by_date = selected
    c1, c2 = candles[idx1], candles[idx2]

    geometry = _classify_geometry_bearish(c1, c2)
    if geometry is None:
        return _empty_result_bearish()

    uptrend = _prior_uptrend(candles, idx1)
    uptrend_confirmed = bool(uptrend)  # None (insufficient history) -> not confirmed

    avg_vol20 = _avg_volume_20(candles, raw_by_date, idx2)
    day2_volume = raw_by_date.get(c2["date"], {}).get("volume")
    volume_confirmed = False
    if avg_vol20 is not None and day2_volume is not None:
        try:
            volume_confirmed = float(day2_volume) >= VOLUME_MIN_RATIO_DAY2 * avg_vol20
        except (TypeError, ValueError):
            volume_confirmed = False

    swing_high = _swing_high_20(candles, idx1)
    near_resistance = False
    if swing_high:
        near_resistance = c1["high"] >= swing_high * (1 - NEAR_RESISTANCE_MAX_PCT / 100.0)

    classification = (VALID_BEARISH_ENGULFING
                       if (uptrend_confirmed and volume_confirmed and near_resistance)
                       else BEARISH_ENGULFING_GEOMETRY_ONLY)

    # PATCH (round 2): ATR floor on the stop, and measured-move-down
    # targets (entry_price minus pattern height) replacing the flat
    # Day-1-close/Day-1-open levels that the algebraic proof showed were
    # structurally always >= entry_price.
    # PATCH (round 3): the full-universe backtest showed the 1.0x/2.0x
    # measured-move targets were statistically unreachable on PSX
    # (aggressive mean-reversion) -- target_1 is now CONSERVATIVE (0.5x
    # height) and target_2 is the FULL measured move (1.0x height), not
    # 2.0x. Confirmed by re-running the backtest after this change; see
    # CALIBRATION_LOG.md for the before/after numbers.
    atr14 = _atr14(candles, idx2)
    entry_price = c2["close"]
    stop_loss = None
    if atr14 is not None:
        atr_buffer = max(STOP_LOSS_ATR_MULTIPLIER * atr14, STOP_LOSS_MIN_BUFFER_PCT * entry_price)
        stop_loss = round(c2["high"] + atr_buffer, PSX_PRICE_DECIMALS)
    pattern_height = c2["high"] - c2["low"]
    target_1 = round(entry_price - (0.5 * pattern_height), PSX_PRICE_DECIMALS)
    target_2 = round(entry_price - (1.0 * pattern_height), PSX_PRICE_DECIMALS)

    return {
        "pattern": PATTERN_NAME_BEARISH,
        "timeframe": TIMEFRAME,
        "detected": classification == VALID_BEARISH_ENGULFING,
        "classification": classification,
        "geometry": geometry,
        "prior_uptrend": uptrend_confirmed,
        "volume_confirmed": volume_confirmed,
        "near_resistance": near_resistance,
        "pattern_date": c2["date"].isoformat(),
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "target_1": target_1,
        "target_2": target_2,
    }


# ============================================================================
# Bullish Three-Line Strike -- 4-bar rolling window, confirmed present on
# PSX via a dedicated pre-check (100 instances / 85 symbols, exactly at
# the discard/proceed boundary) before this detector was built at all.
#
# Unlike Bullish/Bearish Engulfing, the prior-trend rule here is NOT the
# OLS-regression-slope heuristic -- it is the EXACT literal rule given
# ("Close 10 sessions ago was at least 5% lower than Day 1 Open"), the
# same formula the pre-check script itself used, reused verbatim rather
# than re-derived. This module's own general "no trading strategy"
# philosophy is set aside here the same way it was for Bearish
# Engulfing -- entry/stop/targets are added per explicit spec.
# ============================================================================

PATTERN_NAME_TLS = "Bullish Three-Line Strike"
VALID_THREE_LINE_STRIKE = "VALID_THREE_LINE_STRIKE"
THREE_LINE_STRIKE_GEOMETRY_ONLY = "THREE_LINE_STRIKE_GEOMETRY_ONLY"
NO_THREE_LINE_STRIKE = "NO_THREE_LINE_STRIKE"

PRIOR_UPTREND_LOOKBACK_TLS = 10
PRIOR_UPTREND_MIN_RISE_PCT_TLS = 5.0
VOLUME_MIN_RATIO_TLS = 1.3  # own constant, not VOLUME_MIN_RATIO_DAY2 -- same value, different pattern


def _select_latest_completed_quad(rows, date_key, as_of):
    """4-candle mirror of _select_latest_completed_pair -- same PSX_TZ/
    effective-as-of cutoff, same refusal to silently substitute an older
    quad when the true latest required candles are invalid/missing.
    Returns (candles, idx1, idx2, idx3, idx4, raw_by_date), or None."""
    try:
        as_of_date = _resolve_as_of_date(as_of)
        raw_by_date = _raw_dedup_by_date(rows, date_key) if rows else {}
    except Exception:
        return None

    eligible_dates = sorted(d for d in raw_by_date if as_of_date is None or d < as_of_date)
    if len(eligible_dates) < 4:
        return None

    latest_four = eligible_dates[-4:]
    if not all(_row_ohlc_valid(raw_by_date[d]) for d in latest_four):
        return None  # any invalid latest required candle -- no silent fallback to an older quad

    try:
        candles = normalize_daily_ohlc(rows, date_key=date_key, as_of=as_of_date)
    except Exception:
        return None

    if len(candles) < 4 or [c["date"] for c in candles[-4:]] != latest_four:
        return None  # defensive: should be unreachable given the validity check above

    idx4 = len(candles) - 1
    return candles, idx4 - 3, idx4 - 2, idx4 - 1, idx4, raw_by_date


def _classify_geometry_tls(c1, c2, c3, c4):
    """Pure 4-candle geometry, per exact spec -- independent of trend/
    volume context. Returns True/False."""
    day1_bearish = c1["close"] < c1["open"]
    day2_bearish = c2["close"] < c2["open"] and c2["close"] < c1["close"]
    day3_bearish = c3["close"] < c3["open"] and c3["close"] < c2["close"]
    day4_strike = (c4["close"] > c4["open"] and c4["open"] <= c3["close"] and c4["close"] >= c1["open"])
    return day1_bearish and day2_bearish and day3_bearish and day4_strike


def _prior_uptrend_tls(candles, idx1):
    """EXACT literal rule, not the OLS heuristic used elsewhere in this
    file: "Close 10 sessions ago was at least 5% lower than Day 1 Open"
    -- the same formula the Three-Line Strike pre-check script used.
    Returns None if there isn't enough history (idx1 - 10 < 0)."""
    lookback_idx = idx1 - PRIOR_UPTREND_LOOKBACK_TLS
    if lookback_idx < 0:
        return None
    close_10_ago = candles[lookback_idx]["close"]
    day1_open = candles[idx1]["open"]
    if close_10_ago <= 0:
        return False
    rise_pct = (day1_open - close_10_ago) / close_10_ago * 100.0
    return rise_pct >= PRIOR_UPTREND_MIN_RISE_PCT_TLS


def _empty_result_tls():
    return {"pattern": PATTERN_NAME_TLS, "timeframe": TIMEFRAME, "detected": False,
            "classification": NO_THREE_LINE_STRIKE}


def detect_three_line_strike(rows, date_key="trade_date", as_of=None):
    """Main entry point for the Bullish Three-Line Strike, on the latest
    4 completed daily candles. Never raises. Uses the same completed-
    candle SELECTION discipline as detect_bullish_engulfing
    (_select_latest_completed_quad) -- never silently falls back to an
    older quad when the true latest required candles are invalid/missing.
    """
    selected = _select_latest_completed_quad(rows, date_key, as_of)
    if selected is None:
        return _empty_result_tls()
    candles, idx1, idx2, idx3, idx4, raw_by_date = selected
    c1, c2, c3, c4 = candles[idx1], candles[idx2], candles[idx3], candles[idx4]

    geometry_ok = _classify_geometry_tls(c1, c2, c3, c4)
    if not geometry_ok:
        return _empty_result_tls()

    uptrend = _prior_uptrend_tls(candles, idx1)
    if not uptrend:
        return _empty_result_tls()  # prior trend is part of "Rules & Geometry", a hard gate, not a soft context flag

    avg_vol20 = _avg_volume_20(candles, raw_by_date, idx4)
    day4_volume = raw_by_date.get(c4["date"], {}).get("volume")
    volume_confirmed = False
    if avg_vol20 is not None and day4_volume is not None:
        try:
            volume_confirmed = float(day4_volume) >= VOLUME_MIN_RATIO_TLS * avg_vol20
        except (TypeError, ValueError):
            volume_confirmed = False

    classification = VALID_THREE_LINE_STRIKE if volume_confirmed else THREE_LINE_STRIKE_GEOMETRY_ONLY

    pattern_low = min(c1["low"], c2["low"], c3["low"], c4["low"])
    entry_price = c4["close"]
    atr14 = _atr14(candles, idx4)
    stop_loss = None
    if atr14 is not None:
        atr_buffer = max(STOP_LOSS_ATR_MULTIPLIER * atr14, STOP_LOSS_MIN_BUFFER_PCT * entry_price)
        stop_loss = round(pattern_low - atr_buffer, PSX_PRICE_DECIMALS)
    height = c4["high"] - pattern_low
    target_1 = round(entry_price + height, PSX_PRICE_DECIMALS)
    target_2 = round(entry_price + (height * 2.0), PSX_PRICE_DECIMALS)

    return {
        "pattern": PATTERN_NAME_TLS,
        "timeframe": TIMEFRAME,
        "detected": classification == VALID_THREE_LINE_STRIKE,
        "classification": classification,
        "prior_uptrend": bool(uptrend),
        "volume_confirmed": volume_confirmed,
        "pattern_date": c4["date"].isoformat(),
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "target_1": target_1,
        "target_2": target_2,
    }


# ============================================================================
# MHarris 5-Bar Reversal -- a contained micro-trend snap-back, translated
# 1:1 from the "01_MHarris_Systematic.ipynb" reference notebook's
# total_signal() (candles indexed -4..0 relative to the signal candle, the
# latest completed daily bar here):
#
#   BULLISH: low[-4] > high[0]  (signal candle's whole range still below
#            where price was 4 bars ago -- a contained move, not a
#            breakout) AND high[0] > low[-3] (but not below the -3 bar's
#            low either) AND low[-3] > low[-2] > low[-1] (lows declining
#            for 3 straight bars -- the downtrend leg being interrupted)
#            AND close[0] > high[-1] (the signal candle closes above the
#            PRIOR candle's high -- the reversal thrust).
#   BEARISH: the exact mirror (highs rising for 3 bars, then a reversal
#            candle closing below the prior candle's low).
#
# Trade levels use the notebook's OWN stated MyStrat defaults (SL 4% / TP
# 2% off the signal candle's close) -- this is not an invented filter,
# it's the strategy's literal rule, same as target_1/stop_loss are for
# every other detector in this module. See backend/run_mharris_backtest.py
# for the walk-forward PSX backtest of this exact rule.
# ============================================================================

PATTERN_NAME_MHARRIS = "MHarris 5-Bar Reversal"
BULLISH_MHARRIS = "BULLISH_MHARRIS_REVERSAL"
BEARISH_MHARRIS = "BEARISH_MHARRIS_REVERSAL"
NO_MHARRIS_SIGNAL = "NO_MHARRIS_SIGNAL"

MHARRIS_SL_PCT = 0.04
MHARRIS_TP_PCT = 0.02


def _empty_result_mharris():
    return {"pattern": PATTERN_NAME_MHARRIS, "timeframe": TIMEFRAME, "detected": False,
            "classification": NO_MHARRIS_SIGNAL}


def detect_mharris_reversal(rows, date_key="trade_date", as_of=None):
    """Detects the MHarris 5-bar reversal on the latest completed daily
    candle. `rows`/`date_key`/`as_of` match every other detector in this
    module (see detect_bullish_engulfing). Never raises -- malformed input
    or insufficient history (fewer than 5 completed candles) returns the
    empty/no-detection result.

    `entry_price` here is the signal candle's own close (the same
    convention detect_bearish_engulfing/detect_three_line_strike use for a
    live scanner's reference price) -- the notebook's own backtest fills
    the actual order at the FOLLOWING bar's open under backtesting.py's
    default execution model, which a live scan can't know yet. stop_loss/
    target_1 are computed off that close using the strategy's stated 4%/2%
    defaults, unoptimized (the notebook's headline numbers come from a
    per-instrument grid-search of these percentages -- see
    run_mharris_backtest.py for the walk-forward comparison)."""
    try:
        as_of_date = _resolve_as_of_date(as_of)
        candles = normalize_daily_ohlc(rows, date_key=date_key, as_of=as_of_date)
    except Exception:
        return _empty_result_mharris()

    if len(candles) < 5:
        return _empty_result_mharris()

    i = len(candles) - 1

    def lo(k):
        return candles[i + k]["low"]

    def hi(k):
        return candles[i + k]["high"]

    signal_close = candles[i]["close"]

    direction = None
    if lo(-4) > hi(0) and hi(0) > lo(-3) and lo(-3) > lo(-2) and lo(-2) > lo(-1) and signal_close > hi(-1):
        direction = "BULL"
    elif hi(-4) < lo(0) and lo(0) < hi(-3) and hi(-3) < hi(-2) and hi(-2) < hi(-1) and signal_close < lo(-1):
        direction = "BEAR"

    if direction is None:
        return _empty_result_mharris()

    if direction == "BULL":
        classification = BULLISH_MHARRIS
        stop_loss = round(signal_close * (1 - MHARRIS_SL_PCT), PSX_PRICE_DECIMALS)
        target_1 = round(signal_close * (1 + MHARRIS_TP_PCT), PSX_PRICE_DECIMALS)
    else:
        classification = BEARISH_MHARRIS
        stop_loss = round(signal_close * (1 + MHARRIS_SL_PCT), PSX_PRICE_DECIMALS)
        target_1 = round(signal_close * (1 - MHARRIS_TP_PCT), PSX_PRICE_DECIMALS)

    return {
        "pattern": PATTERN_NAME_MHARRIS,
        "timeframe": TIMEFRAME,
        "detected": True,
        "classification": classification,
        "direction": direction,
        "pattern_date": candles[i]["date"].isoformat(),
        "entry_price": signal_close,
        "stop_loss": stop_loss,
        "target_1": target_1,
    }


def talib_cross_check(rows, date_key="trade_date", as_of=None):
    """Optional secondary cross-check of candle GEOMETRY only, using
    TA-Lib's CDLENGULFING if the package is installed. TA-Lib has no notion
    of the preceding-downtrend context used above, so this never decides
    the final classification -- it's purely a second opinion on whether the
    latest two completed candles form engulfing geometry at all. Uses the
    exact same completed-candle SELECTION as detect_bullish_engulfing (see
    _select_latest_completed_pair) -- same PSX_TZ/effective-as-of cutoff,
    same refusal to silently fall back to an older pair when the true
    latest required candle(s) are invalid/missing. Returns None if talib
    isn't installed or there isn't a valid latest pair to check, so callers
    can treat this as a best-effort, non-blocking extra.
    """
    try:
        import talib
        import numpy as np
    except ImportError:
        return None
    selected = _select_latest_completed_pair(rows, date_key, as_of)
    if selected is None:
        return None
    candles, idx1, idx2, _raw_by_date = selected
    try:
        opens = np.array([c["open"] for c in candles], dtype="float64")
        highs = np.array([c["high"] for c in candles], dtype="float64")
        lows = np.array([c["low"] for c in candles], dtype="float64")
        closes = np.array([c["close"] for c in candles], dtype="float64")
        result = talib.CDLENGULFING(opens, highs, lows, closes)
        value = int(result[idx2])
        return {"talib_cdlengulfing": value, "talib_bullish_geometry": value > 0}
    except Exception:
        return None
