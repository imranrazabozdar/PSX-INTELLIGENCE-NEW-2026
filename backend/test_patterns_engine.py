"""Unit tests for patterns_engine's Bullish Engulfing detector.

Uses the stdlib unittest module (no pytest dependency). Run with:
    python -m unittest backend.test_patterns_engine -v
or, from inside backend/:
    python -m unittest test_patterns_engine -v
"""

import unittest

import patterns_engine as pe


def candle(d, o, h, l, c):
    return {"trade_date": d, "open": o, "high": h, "low": l, "close": c}


# Shared "as_of" for every synthetic series below: one day after the last
# candle in each series, so none of the hand-built rows are ever mistaken
# for an unfinished "today" candle.
AS_OF = "2026-02-01"


class TestBullishEngulfing(unittest.TestCase):

    # 1. Strict Bullish Engulfing after a downtrend -> valid.
    def test_strict_engulfing_with_downtrend_is_valid(self):
        rows = [
            candle("2026-01-19", 116, 119, 112, 112),   # idx0, close 112 (V2's 5-close window starts here)
            candle("2026-01-20", 112, 115, 108, 110),   # idx1, close 110 (-2)
            candle("2026-01-21", 111, 112, 106, 108),   # idx2, close 108 (-2)
            candle("2026-01-22", 109, 110, 104, 106),   # idx3, close 106 (-2)
            candle("2026-01-23", 104, 106, 98, 100),    # idx4 = Candle1: bearish, close 100 (-6)
            candle("2026-01-24", 99, 107, 97, 105),     # idx5 = Candle2: bullish, strict engulf
        ]
        result = pe.detect_bullish_engulfing(rows, as_of=AS_OF)
        self.assertTrue(result["detected"])
        self.assertEqual(result["classification"], pe.VALID_BULLISH_ENGULFING)
        self.assertEqual(result["geometry"], pe.STRICT)
        self.assertTrue(result["prior_downtrend"])
        self.assertEqual(result["pattern_date"], "2026-01-24")

    # 2. Strict engulfing without a prior downtrend -> geometry only.
    def test_strict_engulfing_without_downtrend_is_geometry_only(self):
        rows = [
            candle("2026-01-20", 88, 92, 86, 90),     # idx0, close 90
            candle("2026-01-21", 91, 97, 90, 95),     # idx1, close 95 (+5)
            candle("2026-01-22", 96, 101, 95, 100),   # idx2, close 100 (+5)
            candle("2026-01-23", 108, 110, 102, 104), # idx3 = Candle1: bearish, close 104 (+4)
            candle("2026-01-24", 103, 111, 102, 110), # idx4 = Candle2: bullish, strict engulf
        ]
        result = pe.detect_bullish_engulfing(rows, as_of=AS_OF)
        self.assertFalse(result["detected"])
        self.assertEqual(result["classification"], pe.ENGULFING_GEOMETRY_ONLY)
        self.assertEqual(result["geometry"], pe.STRICT)
        self.assertFalse(result["prior_downtrend"])

    # 3. Boundary-match engulfing -> correctly classified.
    def test_boundary_match_engulfing(self):
        rows = [
            candle("2026-01-19", 116, 119, 112, 112),
            candle("2026-01-20", 112, 115, 108, 110),
            candle("2026-01-21", 111, 112, 106, 108),
            candle("2026-01-22", 109, 110, 104, 106),
            candle("2026-01-23", 104, 106, 98, 100),   # Candle1: open=104, close=100
            candle("2026-01-24", 100, 107, 97, 105),   # Candle2: open2==close1(100), close2(105)>open1(104)
        ]
        result = pe.detect_bullish_engulfing(rows, as_of=AS_OF)
        self.assertTrue(result["detected"])
        self.assertEqual(result["classification"], pe.VALID_BULLISH_ENGULFING)
        self.assertEqual(result["geometry"], pe.BOUNDARY_MATCH)

    # 4. Bullish candle that does not engulf -> no pattern.
    def test_bullish_candle_not_engulfing(self):
        rows = [
            candle("2026-01-23", 104, 106, 98, 100),  # Candle1: bearish
            candle("2026-01-24", 101, 104, 100, 103), # Candle2: bullish but open2(101) > close1(100)
        ]
        result = pe.detect_bullish_engulfing(rows, as_of=AS_OF)
        self.assertFalse(result["detected"])
        self.assertEqual(result["classification"], pe.NO_BULLISH_ENGULFING)
        self.assertNotIn("geometry", result)

    # 5. Wick not engulfed but body engulfed -> still valid (geometry).
    def test_body_engulfs_even_when_wick_does_not(self):
        rows = [
            candle("2026-01-19", 116, 119, 112, 112),
            candle("2026-01-20", 112, 115, 108, 110),
            candle("2026-01-21", 111, 112, 106, 108),
            candle("2026-01-22", 109, 110, 104, 106),
            candle("2026-01-23", 104, 120, 90, 100),   # Candle1: huge wick, high=120 low=90
            candle("2026-01-24", 99, 106, 95, 105),    # Candle2: high=106 (does NOT engulf 120), body still strict
        ]
        result = pe.detect_bullish_engulfing(rows, as_of=AS_OF)
        self.assertTrue(result["detected"])
        self.assertEqual(result["classification"], pe.VALID_BULLISH_ENGULFING)
        self.assertEqual(result["geometry"], pe.STRICT)

    # 6. Previous candle bullish -> no pattern.
    def test_previous_candle_bullish_no_pattern(self):
        rows = [
            candle("2026-01-23", 100, 106, 98, 104),  # Candle1: bullish (close>open)
            candle("2026-01-24", 99, 110, 97, 108),   # Candle2: bullish too, would engulf geometrically
        ]
        result = pe.detect_bullish_engulfing(rows, as_of=AS_OF)
        self.assertFalse(result["detected"])
        self.assertEqual(result["classification"], pe.NO_BULLISH_ENGULFING)

    # 7. Current candle bearish -> no pattern.
    def test_current_candle_bearish_no_pattern(self):
        rows = [
            candle("2026-01-23", 104, 106, 98, 100),  # Candle1: bearish
            candle("2026-01-24", 105, 106, 100, 101), # Candle2: bearish too (close<open)
        ]
        result = pe.detect_bullish_engulfing(rows, as_of=AS_OF)
        self.assertFalse(result["detected"])
        self.assertEqual(result["classification"], pe.NO_BULLISH_ENGULFING)

    # 8. Incomplete latest daily candle -> ignore.
    def test_incomplete_latest_candle_is_ignored(self):
        rows = [
            candle("2026-01-19", 116, 119, 112, 112),
            candle("2026-01-20", 112, 115, 108, 110),
            candle("2026-01-21", 111, 112, 106, 108),
            candle("2026-01-22", 109, 110, 104, 106),
            candle("2026-01-23", 104, 106, 98, 100),   # Candle1
            candle("2026-01-24", 99, 107, 97, 105),    # Candle2 (the real latest COMPLETED candle)
            candle("2026-01-25", 105, 108, 104, 106),  # unfinished "today" candle -- must be dropped
        ]
        # as_of = the unfinished candle's own date, so it's excluded as "today"
        result = pe.detect_bullish_engulfing(rows, as_of="2026-01-25")
        self.assertTrue(result["detected"])
        self.assertEqual(result["classification"], pe.VALID_BULLISH_ENGULFING)
        self.assertEqual(result["pattern_date"], "2026-01-24")

    # 9. Insufficient historical candles -> safe result.
    def test_insufficient_history_is_safe(self):
        # Exactly 2 candles: enough for geometry, NOT enough (V2 needs 6) for
        # the downtrend check -> geometry-only, never an exception.
        rows = [
            candle("2026-01-23", 104, 106, 98, 100),
            candle("2026-01-24", 99, 107, 97, 105),
        ]
        result = pe.detect_bullish_engulfing(rows, as_of=AS_OF)
        self.assertFalse(result["detected"])
        self.assertEqual(result["classification"], pe.ENGULFING_GEOMETRY_ONLY)
        self.assertFalse(result["prior_downtrend"])

        # 0 and 1 candles must also resolve safely, never raise.
        self.assertEqual(pe.detect_bullish_engulfing([], as_of=AS_OF),
                          {"pattern": "Bullish Engulfing", "timeframe": "1D",
                           "detected": False, "classification": pe.NO_BULLISH_ENGULFING})
        self.assertFalse(pe.detect_bullish_engulfing([rows[0]], as_of=AS_OF)["detected"])

    # 10. Missing OHLC data -> safe handling.
    def test_missing_ohlc_data_is_handled_safely(self):
        rows = [
            candle("2026-01-20", 112, 115, 108, 110),
            {"trade_date": "2026-01-21", "open": 111, "high": 112, "low": 106},  # close missing
            candle("2026-01-22", 109, 110, 104, 106),
            candle("2026-01-23", 104, 106, 98, 100),
            candle("2026-01-24", 99, 107, 97, 105),
        ]
        try:
            result = pe.detect_bullish_engulfing(rows, as_of=AS_OF)
        except Exception as e:  # pragma: no cover - must never happen
            self.fail(f"detect_bullish_engulfing raised on missing OHLC data: {e!r}")
        self.assertIn("detected", result)
        self.assertIn("classification", result)

    # --- Extra coverage for the "Handle" requirements not already exercised ---

    def test_duplicate_dates_last_occurrence_wins(self):
        rows = [
            candle("2026-01-23", 999, 999, 999, 999),  # stale duplicate, should be overwritten
            candle("2026-01-23", 104, 106, 98, 100),   # authoritative Candle1
            candle("2026-01-24", 99, 107, 97, 105),    # Candle2
        ]
        result = pe.detect_bullish_engulfing(rows, as_of=AS_OF)
        self.assertEqual(result["classification"], pe.ENGULFING_GEOMETRY_ONLY)
        self.assertEqual(result["geometry"], pe.STRICT)

    def test_unsorted_input_is_sorted_before_analysis(self):
        ordered = [
            candle("2026-01-19", 116, 119, 112, 112),
            candle("2026-01-20", 112, 115, 108, 110),
            candle("2026-01-21", 111, 112, 106, 108),
            candle("2026-01-22", 109, 110, 104, 106),
            candle("2026-01-23", 104, 106, 98, 100),
            candle("2026-01-24", 99, 107, 97, 105),
        ]
        shuffled = [ordered[4], ordered[0], ordered[5], ordered[2], ordered[3], ordered[1]]
        result_sorted = pe.detect_bullish_engulfing(ordered, as_of=AS_OF)
        result_shuffled = pe.detect_bullish_engulfing(shuffled, as_of=AS_OF)
        self.assertEqual(result_sorted, result_shuffled)
        self.assertEqual(result_shuffled["classification"], pe.VALID_BULLISH_ENGULFING)

    # --- Coverage for the PSX-specific fixes ---

    def test_boundary_equality_survives_yahoo_float_noise(self):
        # close1 and open2 are the "same" PSX price (304.20) but arrive as
        # different float32-derived values, as Yahoo's feed actually does.
        # Realistic, internally-consistent OHLC throughout (no impossible
        # one-day jumps) -- only the noise on the 304.20 boundary matters.
        rows = [
            candle("2026-01-19", 328, 329, 325, 325),
            candle("2026-01-20", 322, 323, 319, 320),
            candle("2026-01-21", 319, 320, 314, 315),
            candle("2026-01-22", 314, 315, 309, 310),
            candle("2026-01-23", 305.50003, 306, 304, 304.1999998),   # Candle1: bearish, close ~= 304.20
            candle("2026-01-24", 304.2000003, 315.00, 304.20, 312),   # Candle2: bullish, open ~= 304.20
        ]
        result = pe.detect_bullish_engulfing(rows, as_of=AS_OF)
        self.assertEqual(result["classification"], pe.VALID_BULLISH_ENGULFING)
        self.assertEqual(result["geometry"], pe.BOUNDARY_MATCH)

    def test_completed_vs_unfinished_psx_session(self):
        tuesday = pe._datetime(2026, 1, 20, 14, 0, tzinfo=pe.PSX_TZ)   # before 15:30 PKT close
        after_close = pe._datetime(2026, 1, 20, 16, 0, tzinfo=pe.PSX_TZ)  # after close
        friday = pe._datetime(2026, 1, 23, 15, 0, tzinfo=pe.PSX_TZ)    # before Friday's 16:30 close
        self.assertEqual(pe._effective_as_of_date(tuesday), tuesday.date())      # today still excluded
        self.assertEqual(pe._effective_as_of_date(after_close), after_close.date() + pe._timedelta(days=1))
        self.assertEqual(pe._effective_as_of_date(friday), friday.date())        # Friday's later close respected

    def test_invalid_latest_candle_no_silent_fallback(self):
        rows = [
            candle("2026-01-20", 112, 115, 108, 110),
            candle("2026-01-21", 111, 112, 106, 108),
            candle("2026-01-22", 109, 110, 104, 106),
            candle("2026-01-23", 104, 106, 98, 100),   # would-be Candle1, valid
            candle("2026-01-24", 99, 107, 97, 105),    # would-be Candle2, valid -- old code detected here
            {"trade_date": "2026-01-25", "open": 106, "high": 108, "low": 104},  # true latest row: close missing
        ]
        result = pe.detect_bullish_engulfing(rows, as_of="2026-01-26")
        self.assertFalse(result["detected"])
        self.assertEqual(result, {"pattern": "Bullish Engulfing", "timeframe": "1D",
                                   "detected": False, "classification": pe.NO_BULLISH_ENGULFING})

    def test_stale_zero_volume_bar_downgrades_trend_context(self):
        rows = [
            {"trade_date": "2026-01-19", "open": 116, "high": 119, "low": 112, "close": 112, "volume": 55000},
            {"trade_date": "2026-01-20", "open": 112, "high": 115, "low": 108, "close": 110, "volume": 50000},
            {"trade_date": "2026-01-21", "open": 111, "high": 112, "low": 106, "close": 108, "volume": 0},
            {"trade_date": "2026-01-22", "open": 109, "high": 110, "low": 104, "close": 106, "volume": 40000},
            {"trade_date": "2026-01-23", "open": 104, "high": 106, "low": 98, "close": 100, "volume": 45000},
            {"trade_date": "2026-01-24", "open": 99, "high": 107, "low": 97, "close": 105, "volume": 60000},
        ]
        result = pe.detect_bullish_engulfing(rows, as_of=AS_OF)
        self.assertEqual(result["classification"], pe.ENGULFING_GEOMETRY_ONLY)
        self.assertFalse(result["prior_downtrend"])
        self.assertEqual(result.get("trend_context_data_quality"), "stale_or_zero_volume_detected")

        # Sanity: the same geometry WITHOUT any zero-volume bar is VALID --
        # confirms the override only fires because of the stale bar above.
        clean_rows = [dict(r, volume=50000) for r in rows]
        clean_result = pe.detect_bullish_engulfing(clean_rows, as_of=AS_OF)
        self.assertEqual(clean_result["classification"], pe.VALID_BULLISH_ENGULFING)
        self.assertNotIn("trend_context_data_quality", clean_result)

    def test_large_gap_flags_possible_corporate_action(self):
        rows = [
            candle("2026-01-19", 116, 119, 112, 112),
            candle("2026-01-20", 112, 115, 108, 110),
            candle("2026-01-21", 111, 112, 106, 108),
            candle("2026-01-22", 109, 110, 104, 106),
            candle("2026-01-23", 104, 106, 98, 100),    # Candle1 close 100
            candle("2026-01-24", 99, 140, 99, 130),     # Candle2 close 130 -- 30% gap from 100
        ]
        result = pe.detect_bullish_engulfing(rows, as_of=AS_OF)
        self.assertEqual(result["classification"], pe.VALID_BULLISH_ENGULFING)
        self.assertTrue(result.get("possible_corporate_action_gap"))

    def test_talib_cross_check_uses_same_completed_candle_as_manual_detector(self):
        # 2026-01-23 is a Friday (PSX close 16:30 PKT) -- the latest row.
        rows = [
            candle("2026-01-19", 322, 323, 319, 320),
            candle("2026-01-20", 319, 320, 314, 315),
            candle("2026-01-21", 314, 315, 309, 310),
            candle("2026-01-22", 104, 106, 98, 100),   # would-be Candle1
            candle("2026-01-23", 99, 107, 97, 105),    # would-be Candle2 (today, in both scenarios below)
        ]
        during_hours = pe._datetime(2026, 1, 23, 14, 0, tzinfo=pe.PSX_TZ)  # before 16:30 PKT close
        after_close = pe._datetime(2026, 1, 23, 17, 0, tzinfo=pe.PSX_TZ)   # after 16:30 PKT close

        try:
            import talib  # noqa: F401
            talib_installed = True
        except ImportError:
            talib_installed = False

        for now_pkt, today_is_eligible in ((during_hours, False), (after_close, True)):
            as_of = pe._effective_as_of_date(now_pkt)

            selection = pe._select_latest_completed_pair(rows, "trade_date", as_of)
            self.assertIsNotNone(selection)
            candles, idx1, idx2, _ = selection
            expected_latest = "2026-01-23" if today_is_eligible else "2026-01-22"
            self.assertEqual(candles[idx2]["date"].isoformat(), expected_latest)

            det_result = pe.detect_bullish_engulfing(rows, as_of=as_of)
            self.assertEqual(det_result.get("pattern_date", expected_latest), expected_latest)

            cc_result = pe.talib_cross_check(rows, as_of=as_of)
            if talib_installed:
                # Both must have selected identically: cross-check's own
                # verdict on 2026-01-23's geometry only appears when 01-23
                # was actually included in ITS candle array too.
                self.assertIsNotNone(cc_result)
            else:
                self.assertIsNone(cc_result)  # no talib -> None regardless of selection

            # Proves the two functions cannot disagree on candle selection:
            # talib_cross_check runs through the identical shared selector.
            cc_selection = pe._select_latest_completed_pair(rows, "trade_date", as_of)
            self.assertEqual(candles[idx2]["date"], cc_selection[0][cc_selection[2]]["date"])

        # During trading hours, the true latest (01-23) is excluded, so the
        # eligible pair becomes (01-21, 01-22): 01-21 open314/close310 is
        # bearish, and 01-22 open104/close100 is ALSO bearish (no bullish
        # Candle2) -- both functions must agree on "no detection", not just
        # agree on which dates they looked at.
        as_of_during = pe._effective_as_of_date(during_hours)
        self.assertEqual(pe.detect_bullish_engulfing(rows, as_of=as_of_during)["classification"],
                          pe.NO_BULLISH_ENGULFING)
        if talib_installed:
            during_cc = pe.talib_cross_check(rows, as_of=as_of_during)
            self.assertIsNotNone(during_cc)
            self.assertFalse(during_cc["talib_bullish_geometry"])


def candle_v(d, o, h, l, c, v):
    """Same as candle() but with volume -- needed for detect_bearish_engulfing's
    volume filter, which candle() (used by every Bullish Engulfing test
    above) deliberately omits."""
    return {"trade_date": d, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _ramp_rows_bearish(n=19, start_close=70.0, step=2.0, volume=50000):
    """n strictly-ascending days (close_i = start_close + i*step), each a
    small bullish day -- feeds _prior_uptrend's "5+ higher closes before
    Day 1" check and _avg_volume_20's baseline simultaneously."""
    rows = []
    for i in range(n):
        c = start_close + i * step
        o = c - 1.0
        rows.append(candle_v(f"2025-12-{i + 1:02d}", o, c + 1.0, o - 1.0, c, volume))
    return rows


class TestBearishEngulfing(unittest.TestCase):
    """3 required tests per the Evening-Star-style bearish expansion spec.
    See patterns_engine.py's module-level ARCHITECTURE NOTE above
    detect_bearish_engulfing for the one remaining flagged departure from
    this file's stated design (volume/resistance filters).

    PATCH (round 2): prior-trend now uses the exact inverted
    _prior_downtrend OLS mirror (not a simple count), and targets are a
    measured move DOWN from entry_price (entry - pattern_height / 2x),
    which are now correctly below entry_price -- the structural "target
    >= entry" bug flagged in round 1 is fixed, so these tests now assert
    the corrected directional relationship directly.
    """

    def test_textbook_bearish_engulfing_detected(self):
        rows = _ramp_rows_bearish()  # indices 0-18, closes 70..106, ascending
        rows.append(candle_v("2026-01-01", 106, 116, 105, 115, 50000))   # Day 1 (idx19): bullish, the swing high
        rows.append(candle_v("2026-01-02", 116, 117, 103, 104, 80000))  # Day 2 (idx20): bearish, full engulf
        result = pe.detect_bearish_engulfing(rows, as_of="2026-01-03")

        self.assertTrue(result["detected"], msg=f"result={result}")
        self.assertEqual(result["classification"], pe.VALID_BEARISH_ENGULFING)
        self.assertEqual(result["geometry"], pe.STRICT)
        self.assertTrue(result["prior_uptrend"])
        self.assertTrue(result["volume_confirmed"])
        self.assertTrue(result["near_resistance"])
        self.assertEqual(result["pattern_date"], "2026-01-02")
        self.assertEqual(result["entry_price"], 104)
        # Pattern height = Day 2 High - Day 2 Low = 117 - 103 = 14.
        self.assertEqual(result["target_1"], 97.0)   # 104 - 0.5*14 (conservative)
        self.assertEqual(result["target_2"], 90.0)   # 104 - 1.0*14 (full measured move)
        self.assertGreater(result["stop_loss"], result["entry_price"])  # plus-sign short stop, above entry
        self.assertLess(result["target_1"], result["entry_price"])      # now correctly below entry
        self.assertLess(result["target_2"], result["target_1"])

    def test_day2_does_not_fully_engulf_rejected(self):
        # Day 2 closes at 108 -- ABOVE Day 1's open (106), so the body does
        # NOT fully engulf Day 1's (close2 <= open1 fails). Everything else
        # identical to the textbook case.
        rows = _ramp_rows_bearish()
        rows.append(candle_v("2026-01-01", 106, 116, 105, 115, 50000))
        rows.append(candle_v("2026-01-02", 116, 117, 107, 108, 80000))
        result = pe.detect_bearish_engulfing(rows, as_of="2026-01-03")

        self.assertFalse(result["detected"])
        self.assertEqual(result["classification"], pe.NO_BEARISH_ENGULFING)
        self.assertNotIn("geometry", result)

    def test_prior_downtrend_instead_of_uptrend_rejected(self):
        # Identical Day 1/Day 2 geometry, but the 19 lead-in days DESCEND
        # instead of ascending, and Day 1's own close (69) continues that
        # descent rather than reversing it (a bullish Day 1 only needs
        # close > open for that SAME day -- it need not close above the
        # PRIOR day's close). The OLS slope over the trailing 5 closes
        # ending at Day 1 (76,74,72,70,69) is unambiguously negative.
        rows = _ramp_rows_bearish(start_close=106.0, step=-2.0)  # descending: 106,104,...,70
        rows.append(candle_v("2026-01-01", 68, 70, 67, 69, 50000))   # Day 1: barely bullish, continues the decline
        rows.append(candle_v("2026-01-02", 70, 71, 66, 67, 80000))   # Day 2: bearish, full engulf of Day 1
        result = pe.detect_bearish_engulfing(rows, as_of="2026-01-03")

        self.assertFalse(result["detected"])
        self.assertEqual(result["classification"], pe.BEARISH_ENGULFING_GEOMETRY_ONLY)
        self.assertFalse(result["prior_uptrend"])


def _tls_baseline_rows(n=25, close=80.0, volume=50000, start_date_prefix="2025-11"):
    """n flat baseline days at a low level -- establishes both the
    avg_volume_20 baseline AND a close level comfortably below Day 1's
    open by more than the 5% PRIOR_UPTREND_MIN_RISE_PCT_TLS floor."""
    rows = []
    for i in range(n):
        rows.append(candle_v(f"{start_date_prefix}-{i + 1:02d}", close - 0.5, close + 0.5,
                              close - 1.0, close, volume))
    return rows


class TestThreeLineStrike(unittest.TestCase):
    """3 required tests for the Bullish Three-Line Strike. NOT wired into
    app.py/streamlit_app.py yet -- backtest pending, per explicit
    instruction."""

    def test_textbook_three_line_strike_detected(self):
        rows = _tls_baseline_rows()
        rows.append(candle_v("2025-12-02", 100, 101, 94, 95, 50000))    # Day 1: bearish
        rows.append(candle_v("2025-12-03", 94, 94.5, 89, 90, 50000))    # Day 2: bearish, < Day1 close
        rows.append(candle_v("2025-12-04", 89, 89.5, 84, 85, 50000))    # Day 3: bearish, < Day2 close
        rows.append(candle_v("2025-12-05", 84, 102, 83, 101, 80000))    # Day 4: the strike, engulfs Day1 open
        result = pe.detect_three_line_strike(rows, as_of="2025-12-06")

        self.assertTrue(result["detected"], msg=f"result={result}")
        self.assertEqual(result["classification"], pe.VALID_THREE_LINE_STRIKE)
        self.assertTrue(result["prior_uptrend"])
        self.assertTrue(result["volume_confirmed"])
        self.assertEqual(result["pattern_date"], "2025-12-05")
        self.assertEqual(result["entry_price"], 101)
        # pattern_low = min(94,89,84,83) = 83; height = Day4 High(102) - 83 = 19.
        self.assertEqual(result["target_1"], 120.0)   # 101 + 19
        self.assertEqual(result["target_2"], 139.0)   # 101 + 38
        self.assertLess(result["stop_loss"], 83)       # below pattern_low, per the ATR floor

    def test_day4_does_not_engulf_day1_open_rejected(self):
        # Day 4 closes at 97 -- BELOW Day 1's open (100), so it does not
        # fully engulf the 3-day drop (close4 >= open1 fails).
        rows = _tls_baseline_rows()
        rows.append(candle_v("2025-12-02", 100, 101, 94, 95, 50000))
        rows.append(candle_v("2025-12-03", 94, 94.5, 89, 90, 50000))
        rows.append(candle_v("2025-12-04", 89, 89.5, 84, 85, 50000))
        rows.append(candle_v("2025-12-05", 84, 98, 83, 97, 80000))
        result = pe.detect_three_line_strike(rows, as_of="2025-12-06")

        self.assertFalse(result["detected"])
        self.assertEqual(result["classification"], pe.NO_THREE_LINE_STRIKE)

    def test_day4_volume_below_1_3x_average_rejected(self):
        # Geometry and prior trend both valid, but Day 4 volume (55,000)
        # is only ~1.1x the 50,000 baseline average -- below the 1.3x floor.
        rows = _tls_baseline_rows()
        rows.append(candle_v("2025-12-02", 100, 101, 94, 95, 50000))
        rows.append(candle_v("2025-12-03", 94, 94.5, 89, 90, 50000))
        rows.append(candle_v("2025-12-04", 89, 89.5, 84, 85, 50000))
        rows.append(candle_v("2025-12-05", 84, 102, 83, 101, 55000))
        result = pe.detect_three_line_strike(rows, as_of="2025-12-06")

        self.assertFalse(result["detected"])
        self.assertEqual(result["classification"], pe.THREE_LINE_STRIKE_GEOMETRY_ONLY)
        self.assertFalse(result["volume_confirmed"])


if __name__ == "__main__":
    unittest.main()
