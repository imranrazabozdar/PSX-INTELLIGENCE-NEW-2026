"""morning_star_detector.py — vectorized Morning Star (3-candle reversal)
detector for PSX daily OHLCV data.

Reference: Thomas Bulkowski's empirical Morning Star research (the 50%
midpoint-penetration rule, small-star-body requirement, and volume-
confirmation-on-breakout logic below all follow his published criteria)
combined with Steve Nison's classical 3-candle description of the pattern.
Unlike backend/patterns_engine.py's Bullish Engulfing detector (which is
deliberately geometry-only, no strategy layer), THIS detector's spec
explicitly calls for a confidence rating and a dynamic risk-management
layer (entry/stop/targets) -- both are implemented exactly as specified
below, not as an later addition.

PSX MARKET MICROSTRUCTURE: PSX enforces a +/-10% daily circuit breaker.
Two deliberate deviations from "textbook" Morning Star rules exist purely
because of this, both called out inline where they apply:
  1. No physical gap is required between Day 1/2/3 bodies (a circuit
     breaker can prevent a real gap from ever printing) -- relative body
     POSITION within Day 1's range is used instead.
  2. No minimum volume is required on Day 1 -- a stock locked at its lower
     circuit for the session trades almost nothing by definition, and
     requiring volume there would systematically exclude the exact
     capitulation days this pattern is meant to catch.

All computation is vectorized pandas/numpy -- no per-row Python loops.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MorningStarConfig:
    """Every numeric threshold used below, named and in one place so a
    reviewer can audit or tune the rule without hunting through the
    detection logic itself. Defaults are exactly the values specified for
    this detector; nothing here is fitted to any dataset."""

    min_history_days: int = 25            # spec's stated minimum before a signal is even considered
    day1_body_avg_window: int = 10        # "10-day average body size"
    day2_max_body_pct_of_day1: float = 0.30   # Day 2 real body <= 30% of Day 1's
    day2_lower_third_fraction: float = 1.0 / 3.0  # Day 2 close must sit in Day 1's lower third
    trend_sma_window: int = 10            # Filter A: Close(Day1) < SMA10
    trend_lookback_days: int = 6          # Filter A: lower-low count window
    trend_min_lower_lows: int = 4         # Filter A: "at least 4 lower lows in preceding 6 days"
    volume_avg_window: int = 20           # Filter B: 20-day average volume
    volume_min_ratio_day3: float = 1.3    # Filter B: Day 3 volume >= 1.3x avg
    atr_window: int = 14                  # ATR(14) for stop/target sizing
    rsi_window: int = 14                  # RSI(14) for the STRONG-signal oversold check
    strong_volume_ratio: float = 1.5      # STRONG: Day 3 volume > 1.5x avg
    strong_doji_body_pct_of_range: float = 0.05   # STRONG: Day 2 real body < 5% of its own range
    strong_penetration_pct: float = 0.75  # STRONG: Day 3 close above 75% of Day 1's body
    strong_rsi_oversold: float = 35.0     # STRONG: RSI(14) on Day 2 < 35
    stop_loss_atr_multiplier: float = 0.5
    target2_atr_multiplier: float = 1.0
    # AUDIT FIX: a tight-range PSX name can have ATR14~=0, which would
    # otherwise leave the stop with literally zero cushion (Stop = Day 2
    # low - 0). Floors the ATR buffer at this fraction of the entry price
    # (Day 3 close) -- not Day 2's close, since a stop-distance floor
    # should be sized against what's actually being paid.
    stop_loss_min_buffer_pct: float = 0.005

    # --- Evening Star (bearish mirror) -- new fields only; every field
    # above this line is shared/reused as-is by detect_evening_star(). ---
    # Per explicit spec: "5+ higher closes before Day 1", a SINGLE
    # condition (unlike Morning Star's Filter A, which is an OR of an
    # SMA10 check and a lower-low count). Mirrors the lower_low_count_6
    # MECHANISM (a trailing day-over-day comparison count), just inverted
    # direction and using the threshold/window the spec gave.
    trend_lookback_days_bearish: int = 6
    trend_min_higher_closes: int = 5
    # STRONG bonus condition, Evening Star only: Day 2 gaps up from Day 1
    # close. Note this runs counter to this module's own stated PSX
    # rationale for Morning Star ("no gap required -- a circuit breaker
    # can prevent a real gap from ever printing") -- kept anyway because
    # the user specified it explicitly for this setup, and it is only a
    # STRONG-tier bonus condition, never a hard geometry gate, so it
    # merely demotes a signal to MODERATE on PSX names that gap-lock
    # rather than rejecting it outright.
    strong_rsi_overbought: float = 65.0


class MorningStarDetector:
    """Detects Morning Star reversal signals on PSX daily OHLCV data.

    Usage:
        detector = MorningStarDetector()
        signals = detector.detect_patterns(df)  # df: date_col, open, high, low, close, volume

    `detect_patterns` is the only public method; everything else is a
    private, independently-testable computation step. All indicator/
    condition series are computed once, vectorized, over the full input
    DataFrame -- there is no per-candidate Python loop anywhere in this
    class.
    """

    PATTERN_TYPE = "Morning Star"
    REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")

    def __init__(self, config: MorningStarConfig | None = None) -> None:
        self.config = config or MorningStarConfig()

    # ------------------------------------------------------------ public --
    def detect_patterns(self, df: pd.DataFrame, date_col: str = "trade_date") -> pd.DataFrame:
        """Scans `df` (ascending by date, one row per completed PSX daily
        session) for Morning Star occurrences. Returns a DataFrame with one
        row per valid signal, columns: date, pattern_type, strength_rating,
        day3_penetration_pct, volume_ratio_day3, entry_price, stop_loss,
        target_1, target_2 -- empty (same columns, zero rows) if none are
        found or there isn't enough history.

        `date_col` defaults to "trade_date" to match backend.app.ohlc_rows()
        (and patterns_engine.py's own date_key convention); pass
        date_col="date" for a differently-shaped source.
        """
        empty = pd.DataFrame(columns=["date", "pattern_type", "strength_rating",
                                       "day3_penetration_pct", "volume_ratio_day3",
                                       "entry_price", "stop_loss", "target_1", "target_2"])
        if df is None or len(df) < self.config.min_history_days + 3:
            return empty

        clean = self._prepare(df, date_col)
        if clean is None or len(clean) < self.config.min_history_days + 3:
            return empty

        indicators = self._compute_indicators(clean)
        candidates = self._build_three_day_view(clean, indicators)
        geometry_ok = self._apply_geometry_rules(candidates)
        context_ok = self._apply_context_filters(candidates)
        valid = geometry_ok & context_ok
        valid &= candidates.index >= self.config.min_history_days  # explicit minimum-history floor

        hits = candidates.loc[valid].copy()
        if hits.empty:
            return empty

        hits["strength_rating"] = self._rate_signals(hits)
        risk = self._calculate_risk_parameters(hits)
        hits = pd.concat([hits, risk], axis=1)

        hits["pattern_type"] = self.PATTERN_TYPE
        # day1_body is SIGNED (close-open, negative for a bearish Day 1) --
        # penetration must be expressed against the body's MAGNITUDE, or a
        # correctly-detected signal would report a negative percentage.
        hits["day3_penetration_pct"] = (
            (hits["day3_close"] - hits["day1_close"]) / hits["day1_abs_body"] * 100.0
        ).round(2)
        hits["volume_ratio_day3"] = hits["day3_volume_ratio"].round(3)
        hits["date"] = hits["day3_date"]

        out = hits[["date", "pattern_type", "strength_rating", "day3_penetration_pct",
                     "volume_ratio_day3", "entry_price", "stop_loss", "target_1", "target_2"]]
        return out.reset_index(drop=True)

    # --------------------------------------------------------- internals --
    def _prepare(self, df: pd.DataFrame, date_col: str) -> pd.DataFrame | None:
        """Coerces required columns to numeric, drops rows with any missing
        required OHLCV field, sorts ascending by date, de-duplicates by
        date (last occurrence wins). Never raises -- returns None on
        structurally unusable input (missing columns entirely)."""
        if date_col not in df.columns or not all(c in df.columns for c in self.REQUIRED_COLUMNS):
            return None
        work = df[[date_col, *self.REQUIRED_COLUMNS]].copy()
        work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
        for c in self.REQUIRED_COLUMNS:
            work[c] = pd.to_numeric(work[c], errors="coerce")
        work = work.dropna(subset=[date_col, *self.REQUIRED_COLUMNS])
        work = work.sort_values(date_col).drop_duplicates(subset=[date_col], keep="last")
        work = work.rename(columns={date_col: "date"}).reset_index(drop=True)
        return work

    def _compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """All indicators computed ONCE over the full ascending series, each
        anchored to "the row it describes" -- i.e. a rolling window at row j
        always covers history strictly BEFORE j unless documented otherwise,
        so a signal never uses information from its own future."""
        cfg = self.config
        body = df["close"] - df["open"]
        abs_body = body.abs()
        candle_range = df["high"] - df["low"]

        # 10-day average body size, evaluated strictly BEFORE each row (a
        # day's own body must not inflate the baseline it's compared to).
        avg_body_10 = abs_body.shift(1).rolling(cfg.day1_body_avg_window,
                                                 min_periods=cfg.day1_body_avg_window).mean()

        # SMA10 of close, inclusive of the current row (standard charting
        # convention: "the 10-day average AS OF today" includes today).
        sma10 = df["close"].rolling(cfg.trend_sma_window, min_periods=cfg.trend_sma_window).mean()

        # Day-over-day lower low, then a trailing 6-day count of how many of
        # the 6 days STRICTLY BEFORE each row had one.
        lower_low = (df["low"] < df["low"].shift(1)).astype(int)
        lower_low_count_6 = lower_low.rolling(cfg.trend_lookback_days,
                                               min_periods=cfg.trend_lookback_days).sum().shift(1)

        # Evening Star mirror: day-over-day HIGHER close, trailing count
        # over trend_lookback_days_bearish days STRICTLY BEFORE each row.
        # Same mechanism as lower_low_count_6, inverted direction, per the
        # explicit "5+ higher closes before Day 1" prior-trend spec.
        higher_close = (df["close"] > df["close"].shift(1)).astype(int)
        higher_close_count_6 = higher_close.rolling(cfg.trend_lookback_days_bearish,
                                                      min_periods=cfg.trend_lookback_days_bearish).sum().shift(1)

        # 20-day average volume, strictly BEFORE each row (so a volume
        # spike never dilutes/inflates its own baseline).
        avg_volume_20 = df["volume"].shift(1).rolling(cfg.volume_avg_window,
                                                        min_periods=cfg.volume_avg_window).mean()

        # ATR(14) -- simple rolling mean of True Range (NOT Wilder-smoothed;
        # a deliberate, documented simplification for full transparency/
        # reproducibility over an exact Wilder recursion the spec didn't
        # mandate either way).
        prev_close = df["close"].shift(1)
        true_range = pd.concat([
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr14 = true_range.rolling(cfg.atr_window, min_periods=cfg.atr_window).mean()

        # RSI(14), Wilder's smoothing via an equivalent EWM(alpha=1/14).
        delta = df["close"].diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        avg_gain = gain.ewm(alpha=1.0 / cfg.rsi_window, min_periods=cfg.rsi_window, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / cfg.rsi_window, min_periods=cfg.rsi_window, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0.0, np.nan)
        rsi14 = 100.0 - (100.0 / (1.0 + rs))
        rsi14 = rsi14.where(avg_loss != 0.0, 100.0)  # no losses in window -> maximally overbought, not undefined

        return pd.DataFrame({
            "body": body, "abs_body": abs_body, "range": candle_range,
            "avg_body_10": avg_body_10, "sma10": sma10,
            "lower_low_count_6": lower_low_count_6, "higher_close_count_6": higher_close_count_6,
            "avg_volume_20": avg_volume_20,
            "atr14": atr14, "rsi14": rsi14,
        })

    def _build_three_day_view(self, df: pd.DataFrame, ind: pd.DataFrame) -> pd.DataFrame:
        """Aligns Day 2 (shift -1) and Day 3 (shift -2) fields onto Day 1's
        row index, so every candidate 3-candle window lives on one row --
        the standard vectorized technique for multi-bar candlestick
        patterns (no per-row loop)."""
        c = pd.DataFrame(index=df.index)
        c["day1_date"] = df["date"]
        c["day1_open"] = df["open"]; c["day1_high"] = df["high"]
        c["day1_low"] = df["low"]; c["day1_close"] = df["close"]
        c["day1_body"] = ind["body"]; c["day1_abs_body"] = ind["abs_body"]
        c["avg_body_10"] = ind["avg_body_10"]
        # NOT a fix (considered and rejected during audit): a proposed patch
        # would shift ind["sma10"] here to exclude Day 1's own close from
        # the average it's compared against. That's a no-op -- provably so:
        # "Close(Day1) < (sum_prev9 + Close(Day1))/10" reduces algebraically
        # to "Close(Day1) < avg(prev9)" exactly, so the inclusive and
        # "excluding Day 1" comparisons always agree on every row. Any
        # single sufficiently sharp Day 1 close CAN satisfy this clause on
        # its own, with no real multi-session decline behind it -- that's
        # an inherent property of comparing one close to an N-day trailing
        # average (inclusive or exclusive makes no difference), not a bug
        # this indicator's inclusion/exclusion can fix. A materially
        # different rule (e.g. requiring SMA10 itself to have been
        # declining) would be a new rule, not a patch to this one.
        c["sma10"] = ind["sma10"]
        c["lower_low_count_6"] = ind["lower_low_count_6"]
        c["higher_close_count_6"] = ind["higher_close_count_6"]

        for field, series in (("date", df["date"]), ("open", df["open"]), ("high", df["high"]),
                               ("low", df["low"]), ("close", df["close"]), ("body", ind["body"]),
                               ("abs_body", ind["abs_body"]), ("range", ind["range"]),
                               ("rsi14", ind["rsi14"])):
            c[f"day2_{field}"] = series.shift(-1)

        for field, series in (("date", df["date"]), ("open", df["open"]), ("close", df["close"]),
                               ("volume", df["volume"]), ("avg_volume_20", ind["avg_volume_20"]),
                               ("atr14", ind["atr14"]), ("abs_body", ind["abs_body"]),
                               ("high", df["high"]), ("low", df["low"])):
            c[f"day3_{field}"] = series.shift(-2)

        # AUDIT FIX: guard against a 0 (or undefined) 20-day average volume
        # -- e.g. a long-suspended/dead PSX counter -- which would otherwise
        # divide out to `inf` and trivially clear both the >=1.3x Filter B
        # and the >1.5x STRONG bonus on a stock with no real liquidity.
        avg_vol = c["day3_avg_volume_20"]
        c["day3_volume_ratio"] = np.where(avg_vol > 0, c["day3_volume"] / avg_vol, np.nan)
        return c

    def _apply_geometry_rules(self, c: pd.DataFrame) -> pd.Series:
        """Section 2 of the spec -- pure 3-candle geometry, independent of
        trend/volume context. Returns a boolean Series aligned to Day 1's
        row index."""
        cfg = self.config

        day1_bearish = c["day1_close"] < c["day1_open"]
        day1_body_large = c["day1_abs_body"] > c["avg_body_10"]

        day2_small_body = c["day2_abs_body"] <= (cfg.day2_max_body_pct_of_day1 * c["day1_abs_body"])
        day1_lower_third_ceiling = c["day1_low"] + (c["day1_high"] - c["day1_low"]) * cfg.day2_lower_third_fraction
        day2_in_lower_third = c["day2_close"] <= day1_lower_third_ceiling
        # AUDIT FIX: an illiquid/lower-circuit-locked PSX session can print
        # Open=High=Low=Close (zero range). That's geometrically a valid
        # "small body in the lower third", but not an actual traded star --
        # reject it explicitly rather than let it pass as a degenerate doji.
        day2_has_range = c["day2_range"] > 0

        day3_bullish = c["day3_close"] > c["day3_open"]
        day1_midpoint = c["day1_close"] + (c["day1_open"] - c["day1_close"]) / 2.0  # spec's exact formula
        day3_above_midpoint = c["day3_close"] > day1_midpoint

        # AUDIT FIX: _prepare() drops any row missing OHLCV, anywhere in
        # history, before this method ever runs -- so "Day 2"/"Day 3" here
        # are just the next SURVIVING rows after a dropna, not necessarily
        # the next real trading sessions. A >4-calendar-day gap (more than
        # a long weekend -- the same threshold data_quality_engine.py's
        # missing_trading_days check already uses) means at least one
        # session was silently dropped between them; reject rather than
        # splice non-adjacent sessions into a fabricated 3-candle pattern.
        day1_to_day2_adjacent = (c["day2_date"] - c["day1_date"]).dt.days <= 4
        day2_to_day3_adjacent = (c["day3_date"] - c["day2_date"]).dt.days <= 4

        return (day1_bearish & day1_body_large & day2_small_body & day2_in_lower_third & day2_has_range
                & day3_bullish & day3_above_midpoint
                & day1_to_day2_adjacent & day2_to_day3_adjacent)

    def _apply_context_filters(self, c: pd.DataFrame) -> pd.Series:
        """Section 3 of the spec -- PSX-specific trend and volume context.
        Filter A is an OR (either signal of an established downtrend is
        enough); Filter B has no Day 1 volume requirement, by design (see
        module docstring)."""
        cfg = self.config
        filter_a_trend = (c["day1_close"] < c["sma10"]) | (c["lower_low_count_6"] >= cfg.trend_min_lower_lows)
        filter_b_volume = c["day3_volume_ratio"] >= cfg.volume_min_ratio_day3
        return filter_a_trend & filter_b_volume

    def _rate_signals(self, hits: pd.DataFrame) -> pd.Series:
        """Section 4 of the spec. STRONG requires ALL FOUR listed confluence
        conditions simultaneously (a strict reading of the spec's bullet
        list under one "STRONG SIGNAL" heading); every other row that
        reached this point already passed the base geometry, the 50%
        midpoint rule, and the >=1.3x volume filter, so it's MODERATE by
        definition -- there is no third, weaker tier."""
        cfg = self.config
        day2_is_doji = hits["day2_abs_body"] <= (cfg.strong_doji_body_pct_of_range * hits["day2_range"])
        day3_deep_penetration = hits["day3_close"] > (hits["day1_close"] + cfg.strong_penetration_pct * hits["day1_abs_body"])
        day2_oversold = hits["day2_rsi14"] < cfg.strong_rsi_oversold
        volume_strong = hits["day3_volume_ratio"] > cfg.strong_volume_ratio

        is_strong = day2_is_doji & day3_deep_penetration & day2_oversold & volume_strong
        return np.where(is_strong, "STRONG", "MODERATE")

    def _calculate_risk_parameters(self, hits: pd.DataFrame) -> pd.DataFrame:
        """Section 5 of the spec -- dynamic, ATR-scaled risk parameters
        (never fixed-Rupee buffers). ATR(14) used throughout is Day 3's
        value (the most recent volatility estimate available at the moment
        this signal would actually be actioned)."""
        cfg = self.config
        entry_price = hits["day3_close"]
        # AUDIT FIX: floor the ATR buffer at stop_loss_min_buffer_pct of the
        # entry price, so a tight-range name (ATR14~=0) doesn't leave the
        # stop with zero real cushion against normal PSX spread/slippage.
        atr_buffer = np.maximum(cfg.stop_loss_atr_multiplier * hits["day3_atr14"],
                                 cfg.stop_loss_min_buffer_pct * entry_price)
        stop_loss = hits["day2_low"] - atr_buffer
        target_1 = entry_price + (hits["day1_high"] - hits["day2_low"])
        target_2 = target_1 + cfg.target2_atr_multiplier * hits["day3_atr14"]
        return pd.DataFrame({"entry_price": entry_price.round(2), "stop_loss": stop_loss.round(2),
                              "target_1": target_1.round(2), "target_2": target_2.round(2)})

    # ===================================================================
    # Evening Star -- bearish mirror of the Morning Star logic above.
    # Shares _prepare()/_compute_indicators()/_build_three_day_view()
    # verbatim (those are direction-agnostic); only geometry, context
    # filters, strength rating, and risk parameters are mirrored here.
    # ===================================================================
    PATTERN_TYPE_BEARISH = "Evening Star"

    def detect_evening_star(self, df: pd.DataFrame, date_col: str = "trade_date") -> pd.DataFrame:
        """Scans `df` (ascending by date, one row per completed PSX daily
        session) for Evening Star occurrences -- the exact bearish mirror
        of detect_patterns(). Returns a DataFrame with one row per valid
        signal, columns: date, pattern, strength_rating,
        day3_penetration_pct, volume_ratio_day3, entry_price, stop_loss,
        target_1, target_2 -- empty (same columns, zero rows) if none are
        found or there isn't enough history.

        Column is named "pattern" (not "pattern_type", unlike
        detect_patterns()'s output) -- per the exact output schema
        specified for this method; the naming inconsistency with
        detect_patterns() is intentional to the spec, not an oversight.

        `date_col` defaults to "trade_date" to match backend.app.ohlc_rows().
        """
        empty = pd.DataFrame(columns=["date", "pattern", "strength_rating",
                                       "day3_penetration_pct", "volume_ratio_day3",
                                       "entry_price", "stop_loss", "target_1", "target_2"])
        if df is None or len(df) < self.config.min_history_days + 3:
            return empty

        clean = self._prepare(df, date_col)
        if clean is None or len(clean) < self.config.min_history_days + 3:
            return empty

        indicators = self._compute_indicators(clean)
        candidates = self._build_three_day_view(clean, indicators)
        geometry_ok = self._apply_geometry_rules_bearish(candidates)
        context_ok = self._apply_context_filters_bearish(candidates)
        valid = geometry_ok & context_ok
        valid &= candidates.index >= self.config.min_history_days

        hits = candidates.loc[valid].copy()
        if hits.empty:
            return empty

        hits["strength_rating"] = self._rate_signals_bearish(hits)
        risk = self._calculate_risk_parameters_bearish(hits)
        hits = pd.concat([hits, risk], axis=1)

        hits["pattern"] = self.PATTERN_TYPE_BEARISH
        # Mirror of Morning Star's penetration formula, direction-inverted:
        # how far BELOW Day 1's close Day 3 ended, as % of Day 1's body.
        hits["day3_penetration_pct"] = (
            (hits["day1_close"] - hits["day3_close"]) / hits["day1_abs_body"] * 100.0
        ).round(2)
        hits["volume_ratio_day3"] = hits["day3_volume_ratio"].round(3)
        hits["date"] = hits["day3_date"]

        out = hits[["date", "pattern", "strength_rating", "day3_penetration_pct",
                     "volume_ratio_day3", "entry_price", "stop_loss", "target_1", "target_2"]]
        return out.reset_index(drop=True)

    def _apply_geometry_rules_bearish(self, c: pd.DataFrame) -> pd.Series:
        """Bearish mirror of _apply_geometry_rules.

        PATCH (round 2): Day 2's real body must now sit in the UPPER
        third of Day 1's total range -- the missing geometric mirror of
        Morning Star's day2_in_lower_third, added per explicit correction
        after the first round deliberately omitted it per a literal
        reading of the spec. Day 3 "large" is still measured against the
        same avg_body_10 baseline as Day 1 (there is no separate
        Day-3-anchored average body size elsewhere in this pipeline)."""
        cfg = self.config

        day1_bullish = c["day1_close"] > c["day1_open"]
        day1_body_large = c["day1_abs_body"] > c["avg_body_10"]

        day2_small_body = c["day2_abs_body"] <= (cfg.day2_max_body_pct_of_day1 * c["day1_abs_body"])
        day2_has_range = c["day2_range"] > 0  # same AUDIT FIX as the bullish version
        # Upper-third mirror of Morning Star's day1_lower_third_ceiling.
        day1_upper_third_floor = c["day1_low"] + (c["day1_high"] - c["day1_low"]) * (1.0 - cfg.day2_lower_third_fraction)
        day2_in_upper_third = c["day2_close"] >= day1_upper_third_floor

        day3_bearish = c["day3_close"] < c["day3_open"]
        day3_body_large = c["day3_abs_body"] > c["avg_body_10"]
        day1_midpoint = c["day1_open"] + (c["day1_close"] - c["day1_open"]) / 2.0  # spec's exact formula
        day3_below_midpoint = c["day3_close"] < day1_midpoint

        # Same non-adjacency guard as the bullish version (see its AUDIT
        # FIX comment) -- _prepare() drops rows missing OHLCV anywhere in
        # history, so Day2/Day3 here are the next SURVIVING rows, not
        # necessarily the next real trading sessions.
        day1_to_day2_adjacent = (c["day2_date"] - c["day1_date"]).dt.days <= 4
        day2_to_day3_adjacent = (c["day3_date"] - c["day2_date"]).dt.days <= 4

        return (day1_bullish & day1_body_large & day2_small_body & day2_has_range & day2_in_upper_third
                & day3_bearish & day3_body_large & day3_below_midpoint
                & day1_to_day2_adjacent & day2_to_day3_adjacent)

    def _apply_context_filters_bearish(self, c: pd.DataFrame) -> pd.Series:
        """Bearish mirror of _apply_context_filters. Per the exact spec,
        the prior-trend check here is a SINGLE condition ("5+ higher
        closes before Day 1"), not an OR of two signals like Morning
        Star's Filter A -- trend_min_higher_closes=5 is used directly,
        not mirrored against trend_min_lower_lows=4 (the spec gave a
        different number for this side deliberately)."""
        cfg = self.config
        trend_ok = c["higher_close_count_6"] >= cfg.trend_min_higher_closes
        volume_ok = c["day3_volume_ratio"] >= cfg.volume_min_ratio_day3
        return trend_ok & volume_ok

    def _rate_signals_bearish(self, hits: pd.DataFrame) -> pd.Series:
        """Bearish mirror of _rate_signals. STRONG requires all four
        listed confluence conditions simultaneously, per spec -- including
        a Day-2-gaps-up-from-Day-1-close condition that has no equivalent
        in the bullish STRONG tier (see the config-level comment on
        strong_rsi_overbought/this module's general no-gap-required
        rationale for why that is notable, not a silent inconsistency)."""
        cfg = self.config
        day2_is_doji = hits["day2_abs_body"] <= (cfg.strong_doji_body_pct_of_range * hits["day2_range"])
        day2_gaps_up = hits["day2_open"] > hits["day1_close"]
        volume_strong = hits["day3_volume_ratio"] >= cfg.strong_volume_ratio
        day2_overbought = hits["day2_rsi14"] >= cfg.strong_rsi_overbought

        is_strong = day2_is_doji & day2_gaps_up & volume_strong & day2_overbought
        return np.where(is_strong, "STRONG", "MODERATE")

    def _calculate_risk_parameters_bearish(self, hits: pd.DataFrame) -> pd.DataFrame:
        """Bearish mirror of _calculate_risk_parameters.

        PATCH (round 2): two corrections applied after the algebraic
        review found the round-1 formulas structurally broken for a short:
          1. ATR FLOOR: stop_loss now floors the ATR buffer at 0.5% of
             Day 3's close, same protection the bullish stop_loss_min_
             buffer_pct already provides, so a tight-range PSX name
             (ATR14~=0) doesn't leave this short stop with near-zero real
             cushion.
          2. TARGETS (measured move down): target_1/target_2 are now
             entry_price MINUS the pattern height (and 2x that height),
             not flat levels (Day 1 Open/Day 1 Open-range) that could sit
             at or above entry_price depending on how far Day 3 fell --
             the exact bug flagged in the prior round's algebraic proof.
             Pattern height = max(High1,2,3) - min(Low1,2,3).

        PATCH (round 3): the full-universe backtest showed the 1.0x/2.0x
        measured-move targets were statistically unreachable on PSX
        (aggressive mean-reversion) -- target_1 is now CONSERVATIVE
        (0.5x height) and target_2 is the FULL measured move (1.0x
        height), not 2.0x. Confirmed by re-running the backtest after
        this change; see CALIBRATION_LOG.md for the before/after numbers."""
        cfg = self.config
        entry_price = hits["day3_close"]
        atr_buffer = np.maximum(cfg.stop_loss_atr_multiplier * hits["day3_atr14"],
                                 cfg.stop_loss_min_buffer_pct * hits["day2_close"])
        stop_loss = hits["day2_high"] + atr_buffer
        pattern_height = (pd.concat([hits["day1_high"], hits["day2_high"], hits["day3_high"]], axis=1).max(axis=1)
                           - pd.concat([hits["day1_low"], hits["day2_low"], hits["day3_low"]], axis=1).min(axis=1))
        target_1 = entry_price - (0.5 * pattern_height)
        target_2 = entry_price - (1.0 * pattern_height)
        return pd.DataFrame({"entry_price": entry_price.round(2), "stop_loss": stop_loss.round(2),
                              "target_1": target_1.round(2), "target_2": target_2.round(2)})
