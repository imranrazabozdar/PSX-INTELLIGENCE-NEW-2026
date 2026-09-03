"""engulfing_star_detector.py — "Engulfing + Star" combined candlestick
reversal, translated from a reference systematic-trading notebook
(EURUSD daily, 2003-2021, CandleSticksPatterns_..._CombinedCandles.ipynb).

RULE (translated 1:1 from isEngulfing()/isStar()/Revsignal1()): the SAME
candle must simultaneously be BOTH a full engulfing bar over the PRIOR
candle AND show a dominant wick on the same side as the engulfment --
stricter than a plain engulfing pattern (this project's existing
patterns_engine.detect_bullish_engulfing/detect_bearish_engulfing), which
requires only the engulfment.

  BEARISH (signal=1 in the source): prior candle bullish (open1<close1),
    current candle bearish (open2>close2) and fully engulfs it
    (close2 < open1, open2 >= close1) -- the notebook's own engulfing
    test -- AND that same current candle has a dominant UPPER wick
    (upper_wick > body, lower_wick < 20% of upper_wick) -- the notebook's
    own "star" test. Both conditions on the SAME bar, not two separate
    bars.
  BULLISH: exact mirror (prior bearish, current bullish and fully
    engulfing, current candle's LOWER wick dominant).

THRESHOLD ADAPTATION (stated plainly): the notebook's bodydiffmin=0.002
is an ABSOLUTE EUR/USD price difference (~0.18% of a ~1.10 price) --
meaningless reused literally on PSX stocks from single digits to
thousands of rupees. Re-expressed as BODY_MIN_PCT = 0.18% of the
candle's own close. The wick-dominance ratios (ratio1/ratio2 > 1, the
smaller wick < 20% of the dominant one) are already dimensionless
ratios of the candle's own range, so those are reused literally,
unchanged.

TRADE RULE: the source notebook has no backtestable trade rule for this
pattern at all -- mytarget()/np.select() in the notebook only LABEL
forward trend direction to measure the pattern's own hit rate, they
never define an entry/stop/target. Rather than inventing an unrelated
rule, this reuses this project's OWN existing bullish/bearish engulfing
trade-rule convention (patterns_engine.py) verbatim, since this pattern
is an engulfing variant: stop_loss = signal candle's own high/low +
max(0.5x ATR14, 0.5% of price) buffer; target_1/target_2 = entry minus/
plus 0.5x/1.0x the signal candle's own high-low range (a measured move
off the pattern's own geometry, not a fixed percentage).
"""

from patterns_engine import (
    normalize_daily_ohlc, _resolve_as_of_date, _atr14,
    STOP_LOSS_ATR_MULTIPLIER, STOP_LOSS_MIN_BUFFER_PCT, PSX_PRICE_DECIMALS, TIMEFRAME,
)

BODY_MIN_PCT = 0.18          # % of price -- see module docstring
WICK_DOMINANCE_RATIO = 1.0   # dimensionless, reused literally from the source (ratio1/ratio2 > 1)
WICK_OPPOSITE_MAX_RATIO = 0.2  # dimensionless, reused literally from the source

PATTERN_NAME_ENGULFING_STAR = "Engulfing + Star Confirmed Reversal"
BULLISH_ENGULFING_STAR = "BULLISH_ENGULFING_STAR"
BEARISH_ENGULFING_STAR = "BEARISH_ENGULFING_STAR"
NO_ENGULFING_STAR_SIGNAL = "NO_ENGULFING_STAR_SIGNAL"

MIN_BARS_REQUIRED = 3  # need the prior candle + the signal candle + 1 for ATR context


def _empty_result():
    return {
        "pattern": PATTERN_NAME_ENGULFING_STAR, "timeframe": TIMEFRAME,
        "detected": False, "classification": NO_ENGULFING_STAR_SIGNAL, "direction": None,
        "pattern_date": None, "entry_price": None, "stop_loss": None,
        "target_1": None, "target_2": None,
    }


def _is_engulfing(c1, c2):
    """c1: prior candle dict, c2: current candle dict. Returns 'BEAR',
    'BULL', or None. Body-size floor uses BODY_MIN_PCT of the CURRENT
    candle's own close (the source floors both bodies against one shared
    absolute constant; on PSX that constant must scale with price, so
    each bar's body is checked against a % of its own close)."""
    body1 = abs(c1["open"] - c1["close"])
    body2 = abs(c2["open"] - c2["close"])
    min_body = BODY_MIN_PCT / 100.0 * c2["close"]
    if body1 <= min_body or body2 <= min_body:
        return None

    if (c1["open"] < c1["close"] and c2["open"] > c2["close"]
            and c2["open"] >= c1["close"] and c2["close"] < c1["open"]):
        return "BEAR"
    if (c1["open"] > c1["close"] and c2["open"] < c2["close"]
            and c2["open"] <= c1["close"] and c2["close"] > c1["open"]):
        return "BULL"
    return None


def _is_star(c):
    """Returns 'BEAR' (dominant upper wick), 'BULL' (dominant lower
    wick), or None -- ratio1/ratio2 in the source, renamed for clarity."""
    body = abs(c["open"] - c["close"])
    min_body = BODY_MIN_PCT / 100.0 * c["close"]
    if body <= min_body:
        return None
    upper_wick = c["high"] - max(c["open"], c["close"])
    lower_wick = min(c["open"], c["close"]) - c["low"]
    body_floor = max(body, 1e-9)
    ratio_upper = upper_wick / body_floor
    ratio_lower = lower_wick / body_floor

    if ratio_upper > WICK_DOMINANCE_RATIO and lower_wick < WICK_OPPOSITE_MAX_RATIO * upper_wick:
        return "BEAR"
    if ratio_lower > WICK_DOMINANCE_RATIO and upper_wick < WICK_OPPOSITE_MAX_RATIO * lower_wick:
        return "BULL"
    return None


def _evaluate_at(candles, i):
    """Shared logic between the live detector and the backtest -- i is
    the SIGNAL bar's index into `candles` (needs i-1 for the engulfing
    check, so i must be >= 1)."""
    if i < 1:
        return None
    c1, c2 = candles[i - 1], candles[i]
    eng = _is_engulfing(c1, c2)
    if eng is None:
        return None
    star = _is_star(c2)
    if star != eng:
        return None
    return eng


def compute_trade_levels(candles, i, direction):
    """Shared between the live detector and the backtest -- entry/stop/
    target math off the signal candle's own geometry (see module
    docstring's TRADE RULE section). candles: normalize_daily_ohlc()
    shape; i: signal bar index; direction: 'BULL' or 'BEAR'."""
    c2 = candles[i]
    entry_price = c2["close"]
    atr14 = _atr14(candles, i)
    pattern_height = c2["high"] - c2["low"]
    stop_loss = None

    if direction == "BEAR":
        if atr14 is not None:
            atr_buffer = max(STOP_LOSS_ATR_MULTIPLIER * atr14, STOP_LOSS_MIN_BUFFER_PCT * entry_price)
            stop_loss = round(c2["high"] + atr_buffer, PSX_PRICE_DECIMALS)
        target_1 = round(entry_price - (0.5 * pattern_height), PSX_PRICE_DECIMALS)
        target_2 = round(entry_price - (1.0 * pattern_height), PSX_PRICE_DECIMALS)
    else:
        if atr14 is not None:
            atr_buffer = max(STOP_LOSS_ATR_MULTIPLIER * atr14, STOP_LOSS_MIN_BUFFER_PCT * entry_price)
            stop_loss = round(c2["low"] - atr_buffer, PSX_PRICE_DECIMALS)
        target_1 = round(entry_price + (0.5 * pattern_height), PSX_PRICE_DECIMALS)
        target_2 = round(entry_price + (1.0 * pattern_height), PSX_PRICE_DECIMALS)

    return entry_price, stop_loss, target_1, target_2


def detect_engulfing_star_reversal(rows, date_key="trade_date", as_of=None):
    """Detects the Engulfing+Star combined reversal on the latest
    completed daily candle. `rows`/`date_key`/`as_of` match every other
    detector in this project (see patterns_engine.detect_bullish_engulfing).
    Never raises -- malformed input or insufficient history returns the
    empty/no-detection result."""
    try:
        as_of_date = _resolve_as_of_date(as_of)
        candles = normalize_daily_ohlc(rows, date_key=date_key, as_of=as_of_date)
    except Exception:
        return _empty_result()

    if len(candles) < MIN_BARS_REQUIRED:
        return _empty_result()

    i = len(candles) - 1
    direction = _evaluate_at(candles, i)
    if direction is None:
        return _empty_result()

    c2 = candles[i]
    entry_price, stop_loss, target_1, target_2 = compute_trade_levels(candles, i, direction)
    classification = BEARISH_ENGULFING_STAR if direction == "BEAR" else BULLISH_ENGULFING_STAR

    return {
        "pattern": PATTERN_NAME_ENGULFING_STAR, "timeframe": TIMEFRAME,
        "detected": True, "classification": classification, "direction": direction,
        "pattern_date": c2["date"].isoformat(), "entry_price": entry_price,
        "stop_loss": stop_loss, "target_1": target_1, "target_2": target_2,
    }
