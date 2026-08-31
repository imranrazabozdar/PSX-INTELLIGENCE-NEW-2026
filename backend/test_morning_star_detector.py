"""Unit tests for MorningStarDetector (backend/morning_star_detector.py).

Uses the stdlib unittest module (no pytest dependency). Run with:
    python -m unittest test_morning_star_detector -v
"""

import unittest

import pandas as pd

from morning_star_detector import MorningStarDetector, MorningStarConfig


def _baseline_rows(n_quiet: int = 20, start_price: float = 100.0, volume: float = 50000):
    """n_quiet flat/noisy days a real pattern can sit on top of -- keeps
    avg_body_10/sma10/avg_volume_20 baselines small and stable."""
    rows = []
    p = start_price
    for i in range(n_quiet):
        o = p
        c = p + (0.1 if i % 2 == 0 else -0.1)
        rows.append({"trade_date": f"2025-11-{i + 1:02d}", "open": o, "high": max(o, c) + 0.3,
                     "low": min(o, c) - 0.3, "close": c, "volume": volume})
        p = c
    return rows


def _decline_rows(closes, start_date_prefix="2025-12"):
    rows = []
    for i, c in enumerate(closes):
        o = c + 1.5
        rows.append({"trade_date": f"{start_date_prefix}-{i + 1:02d}", "open": o, "high": o + 0.5,
                     "low": c - 0.5, "close": c, "volume": 50000})
    return rows


def _rising_rows(closes, start_date_prefix="2025-12"):
    """Mirror of _decline_rows for Evening Star fixtures -- each day's
    open sits BELOW its own close (bullish days), strictly ascending
    closes, so higher_close_count_6 registers a "higher close" on every
    one of these days relative to the previous."""
    rows = []
    for i, c in enumerate(closes):
        o = c - 1.5
        rows.append({"trade_date": f"{start_date_prefix}-{i + 1:02d}", "open": o, "high": c + 0.5,
                     "low": o - 0.5, "close": c, "volume": 50000})
    return rows


class TestMorningStarDetector(unittest.TestCase):

    def test_strong_signal_full_confluence(self):
        rows = _baseline_rows() + _decline_rows([98, 95, 92, 89, 86])
        rows.append({"trade_date": "2026-01-06", "open": 85, "high": 86, "low": 77, "close": 78, "volume": 48000})
        rows.append({"trade_date": "2026-01-07", "open": 76.25, "high": 77, "low": 75, "close": 76.30, "volume": 30000})
        rows.append({"trade_date": "2026-01-08", "open": 77, "high": 85, "low": 76.5, "close": 84, "volume": 95000})
        df = pd.DataFrame(rows)

        result = MorningStarDetector().detect_patterns(df, date_col="trade_date")

        self.assertEqual(len(result), 1)
        row = result.iloc[0]
        self.assertEqual(row["pattern_type"], "Morning Star")
        self.assertEqual(row["strength_rating"], "STRONG")
        self.assertEqual(str(row["date"].date()), "2026-01-08")
        self.assertGreater(row["day3_penetration_pct"], 75.0)
        self.assertGreaterEqual(row["volume_ratio_day3"], 1.5)
        self.assertEqual(row["entry_price"], 84.0)
        # Risk parameters must be internally consistent, not just present.
        self.assertLess(row["stop_loss"], 76.5)  # below Day 2's low
        self.assertGreater(row["target_1"], row["entry_price"])
        self.assertGreater(row["target_2"], row["target_1"])

    def test_moderate_signal_meets_minimum_bar_only(self):
        # Same geometry/trend as the STRONG case, but Day 3 volume is only
        # just over the 1.3x MINIMUM (not the 1.5x STRONG threshold) and
        # Day 2 is not a doji (real body far above 5% of its range) --
        # fails 2 of the 4 STRONG extras, still passes every base rule.
        # (20-day avg volume here is ~48,900, not a round 50,000 -- Day 1
        # and Day 2 both trade below the 50,000 baseline and sit inside
        # that window, so Day 3's volume is chosen against the true average.)
        rows = _baseline_rows() + _decline_rows([98, 95, 92, 89, 86])
        rows.append({"trade_date": "2026-01-06", "open": 85, "high": 86, "low": 77, "close": 78, "volume": 48000})
        rows.append({"trade_date": "2026-01-07", "open": 76.2, "high": 79, "low": 75.5, "close": 77.5, "volume": 30000})
        rows.append({"trade_date": "2026-01-08", "open": 77.6, "high": 83, "low": 77.4, "close": 82.0, "volume": 65000})
        df = pd.DataFrame(rows)

        result = MorningStarDetector().detect_patterns(df, date_col="trade_date")

        self.assertEqual(len(result), 1)
        row = result.iloc[0]
        self.assertEqual(row["strength_rating"], "MODERATE")
        self.assertGreaterEqual(row["volume_ratio_day3"], 1.3)
        self.assertLess(row["volume_ratio_day3"], 1.5)

    def test_day3_below_midpoint_rejected(self):
        # Day 3 closes back above Day 1's open (bullish) but NOT above the
        # 50% midpoint of Day 1's body -- the single non-negotiable rule.
        rows = _baseline_rows() + _decline_rows([98, 95, 92, 89, 86])
        rows.append({"trade_date": "2026-01-06", "open": 85, "high": 86, "low": 77, "close": 78, "volume": 48000})
        rows.append({"trade_date": "2026-01-07", "open": 76.25, "high": 77, "low": 75, "close": 76.30, "volume": 30000})
        rows.append({"trade_date": "2026-01-08", "open": 76.5, "high": 79, "low": 76.4, "close": 78.5, "volume": 95000})
        df = pd.DataFrame(rows)  # midpoint of Day1 body (78 + 3.5 = 81.5); Day3 close 78.5 is below it

        result = MorningStarDetector().detect_patterns(df, date_col="trade_date")
        self.assertTrue(result.empty)

    def test_day2_body_too_large_rejected(self):
        # Day 2's real body exceeds 30% of Day 1's -- not a "star" at all.
        rows = _baseline_rows() + _decline_rows([98, 95, 92, 89, 86])
        rows.append({"trade_date": "2026-01-06", "open": 85, "high": 86, "low": 77, "close": 78, "volume": 48000})
        rows.append({"trade_date": "2026-01-07", "open": 76, "high": 80, "low": 75, "close": 79.5, "volume": 30000})
        rows.append({"trade_date": "2026-01-08", "open": 80, "high": 85, "low": 79.5, "close": 84, "volume": 95000})
        df = pd.DataFrame(rows)

        result = MorningStarDetector().detect_patterns(df, date_col="trade_date")
        self.assertTrue(result.empty)

    def test_no_prior_downtrend_rejected(self):
        # Day 1 is bearish (close < open, big body) but sits on top of a
        # STEADY UPTREND, not a decline: its close (113) stays above the
        # trailing SMA10 (~111.2, itself pulled up by the uptrend) and the
        # preceding 6 days have zero lower-lows (monotonically rising) --
        # both halves of Filter A fail, geometry alone must not be enough.
        # (Note: a single sharp Day-1 drop usually DOES pull an inclusive
        # SMA10 below Day 1's own close -- by construction, Close(Day1) <
        # SMA10(incl. Day1) reduces to Close(Day1) < avg(previous 9 closes).
        # This fixture keeps Day 1's close above that recent average, which
        # is what a genuine "no established downtrend" case requires.)
        rows = []
        p = 90.0
        for i in range(25):
            o = p
            c = p + 1.0
            rows.append({"trade_date": f"2025-11-{i + 1:02d}", "open": o, "high": c + 0.3,
                         "low": o - 0.3, "close": c, "volume": 50000})
            p = c
        rows.append({"trade_date": "2026-01-06", "open": 117, "high": 118, "low": 111, "close": 113, "volume": 48000})
        rows.append({"trade_date": "2026-01-07", "open": 111.5, "high": 112, "low": 110, "close": 111.6, "volume": 30000})
        rows.append({"trade_date": "2026-01-08", "open": 111.8, "high": 117, "low": 111.5, "close": 116, "volume": 95000})
        df = pd.DataFrame(rows)

        result = MorningStarDetector().detect_patterns(df, date_col="trade_date")
        self.assertTrue(result.empty)

    def test_low_day3_volume_rejected(self):
        # Same as the STRONG case but Day 3 volume is only at the 20-day
        # average (no accumulation signature) -- Filter B fails.
        rows = _baseline_rows() + _decline_rows([98, 95, 92, 89, 86])
        rows.append({"trade_date": "2026-01-06", "open": 85, "high": 86, "low": 77, "close": 78, "volume": 48000})
        rows.append({"trade_date": "2026-01-07", "open": 76.25, "high": 77, "low": 75, "close": 76.30, "volume": 30000})
        rows.append({"trade_date": "2026-01-08", "open": 77, "high": 85, "low": 76.5, "close": 84, "volume": 50000})
        df = pd.DataFrame(rows)

        result = MorningStarDetector().detect_patterns(df, date_col="trade_date")
        self.assertTrue(result.empty)

    def test_low_day1_volume_does_not_block_detection(self):
        # PSX circuit-breaker exception: Day 1 volume is a fraction of
        # normal (a lower-circuit-lock signature) -- must NOT be filtered.
        rows = _baseline_rows() + _decline_rows([98, 95, 92, 89, 86])
        rows.append({"trade_date": "2026-01-06", "open": 85, "high": 86, "low": 77, "close": 78, "volume": 500})
        rows.append({"trade_date": "2026-01-07", "open": 76.25, "high": 77, "low": 75, "close": 76.30, "volume": 30000})
        rows.append({"trade_date": "2026-01-08", "open": 77, "high": 85, "low": 76.5, "close": 84, "volume": 95000})
        df = pd.DataFrame(rows)

        result = MorningStarDetector().detect_patterns(df, date_col="trade_date")
        self.assertEqual(len(result), 1)  # still detected despite a near-zero-volume Day 1

    def test_insufficient_history_returns_empty_not_error(self):
        rows = _decline_rows([98, 95, 92, 89, 86])
        rows.append({"trade_date": "2026-01-06", "open": 85, "high": 86, "low": 77, "close": 78, "volume": 48000})
        rows.append({"trade_date": "2026-01-07", "open": 76.25, "high": 77, "low": 75, "close": 76.30, "volume": 30000})
        rows.append({"trade_date": "2026-01-08", "open": 77, "high": 85, "low": 76.5, "close": 84, "volume": 95000})
        df = pd.DataFrame(rows)  # far fewer than 25+3 rows

        result = MorningStarDetector().detect_patterns(df, date_col="trade_date")
        self.assertTrue(result.empty)
        self.assertListEqual(list(result.columns),
                              ["date", "pattern_type", "strength_rating", "day3_penetration_pct",
                               "volume_ratio_day3", "entry_price", "stop_loss", "target_1", "target_2"])

    def test_empty_and_malformed_input_safe(self):
        det = MorningStarDetector()
        self.assertTrue(det.detect_patterns(pd.DataFrame()).empty)
        self.assertTrue(det.detect_patterns(None).empty)
        # Missing required columns entirely.
        self.assertTrue(det.detect_patterns(pd.DataFrame({"trade_date": ["2026-01-01"]})).empty)

    def test_missing_ohlc_values_do_not_crash(self):
        rows = _baseline_rows() + _decline_rows([98, 95, 92, 89, 86])
        rows.append({"trade_date": "2026-01-06", "open": 85, "high": 86, "low": None, "close": 78, "volume": 48000})
        rows.append({"trade_date": "2026-01-07", "open": 76.25, "high": 77, "low": 75, "close": 76.30, "volume": 30000})
        rows.append({"trade_date": "2026-01-08", "open": 77, "high": 85, "low": 76.5, "close": 84, "volume": 95000})
        df = pd.DataFrame(rows)
        try:
            result = MorningStarDetector().detect_patterns(df, date_col="trade_date")
        except Exception as e:  # pragma: no cover - must never happen
            self.fail(f"detect_patterns raised on missing OHLC data: {e!r}")
        self.assertIsInstance(result, pd.DataFrame)

    def test_custom_config_thresholds_are_honored(self):
        # Loosen the volume-ratio bar and confirm behavior actually changes.
        rows = _baseline_rows() + _decline_rows([98, 95, 92, 89, 86])
        rows.append({"trade_date": "2026-01-06", "open": 85, "high": 86, "low": 77, "close": 78, "volume": 48000})
        rows.append({"trade_date": "2026-01-07", "open": 76.25, "high": 77, "low": 75, "close": 76.30, "volume": 30000})
        rows.append({"trade_date": "2026-01-08", "open": 77, "high": 85, "low": 76.5, "close": 84, "volume": 55000})
        df = pd.DataFrame(rows)  # ~1.1x avg volume -- fails the default 1.3x floor

        default_result = MorningStarDetector().detect_patterns(df, date_col="trade_date")
        self.assertTrue(default_result.empty)

        loose_cfg = MorningStarConfig(volume_min_ratio_day3=1.0)
        loose_result = MorningStarDetector(loose_cfg).detect_patterns(df, date_col="trade_date")
        self.assertEqual(len(loose_result), 1)

    # --- Coverage for the code-review audit fixes ---

    def test_zero_avg_volume_does_not_produce_infinite_ratio(self):
        # A long-dead/suspended counter: every session up to and including
        # Day 2 trades zero volume, so the trailing 20-day average at Day 3
        # is exactly 0. Pre-fix this divided out to `inf`, which trivially
        # cleared both the >=1.3x and >1.5x volume bars.
        rows = _baseline_rows(volume=0) + _decline_rows([98, 95, 92, 89, 86])
        for r in rows:
            r["volume"] = 0
        rows.append({"trade_date": "2026-01-06", "open": 85, "high": 86, "low": 77, "close": 78, "volume": 0})
        rows.append({"trade_date": "2026-01-07", "open": 76.25, "high": 77, "low": 75, "close": 76.30, "volume": 0})
        rows.append({"trade_date": "2026-01-08", "open": 77, "high": 85, "low": 76.5, "close": 84, "volume": 12000})
        df = pd.DataFrame(rows)

        result = MorningStarDetector().detect_patterns(df, date_col="trade_date")
        self.assertTrue(result.empty)  # NOT detected via a spurious infinite ratio

    def test_nonadjacent_sessions_rejected(self):
        # Otherwise-valid STRONG geometry, but Day 3 is dated 10 calendar
        # days after Day 2 -- simulating a data-provider gap that silently
        # dropped several real sessions in between (_prepare's dropna keeps
        # Day 2 and this later row as consecutive SURVIVING rows, but they
        # aren't consecutive trading sessions).
        rows = _baseline_rows() + _decline_rows([98, 95, 92, 89, 86])
        rows.append({"trade_date": "2026-01-06", "open": 85, "high": 86, "low": 77, "close": 78, "volume": 48000})
        rows.append({"trade_date": "2026-01-07", "open": 76.25, "high": 77, "low": 75, "close": 76.30, "volume": 30000})
        rows.append({"trade_date": "2026-01-17", "open": 77, "high": 85, "low": 76.5, "close": 84, "volume": 95000})
        df = pd.DataFrame(rows)

        result = MorningStarDetector().detect_patterns(df, date_col="trade_date")
        self.assertTrue(result.empty)

    def test_flat_zero_range_day2_rejected(self):
        # Day 2 prints Open=High=Low=Close (a lower-circuit-lock signature,
        # not a genuine traded star) -- otherwise identical to the STRONG
        # fixture.
        rows = _baseline_rows() + _decline_rows([98, 95, 92, 89, 86])
        rows.append({"trade_date": "2026-01-06", "open": 85, "high": 86, "low": 77, "close": 78, "volume": 48000})
        rows.append({"trade_date": "2026-01-07", "open": 76.5, "high": 76.5, "low": 76.5, "close": 76.5, "volume": 30000})
        rows.append({"trade_date": "2026-01-08", "open": 77, "high": 85, "low": 76.5, "close": 84, "volume": 95000})
        df = pd.DataFrame(rows)

        result = MorningStarDetector().detect_patterns(df, date_col="trade_date")
        self.assertTrue(result.empty)

    def test_stop_loss_has_minimum_atr_floor(self):
        # Zero out the ATR term entirely (multiplier=0) so only the floor
        # can produce a nonzero buffer -- isolates the floor from ATR math.
        rows = _baseline_rows() + _decline_rows([98, 95, 92, 89, 86])
        rows.append({"trade_date": "2026-01-06", "open": 85, "high": 86, "low": 77, "close": 78, "volume": 48000})
        rows.append({"trade_date": "2026-01-07", "open": 76.25, "high": 77, "low": 75, "close": 76.30, "volume": 30000})
        rows.append({"trade_date": "2026-01-08", "open": 77, "high": 85, "low": 76.5, "close": 84, "volume": 95000})
        df = pd.DataFrame(rows)

        cfg = MorningStarConfig(stop_loss_atr_multiplier=0.0, stop_loss_min_buffer_pct=0.01)
        result = MorningStarDetector(cfg).detect_patterns(df, date_col="trade_date")

        self.assertEqual(len(result), 1)
        row = result.iloc[0]
        expected_stop = 75.0 - 0.01 * row["entry_price"]  # Day2 low (75.0) - 1% of entry
        self.assertAlmostEqual(row["stop_loss"], round(expected_stop, 2), places=2)

    def test_sma10_inclusive_vs_exclusive_are_provably_equivalent(self):
        # A proposed audit patch suggested comparing Close(Day1) against an
        # SMA10 that EXCLUDES Day 1's own close, reasoning that including it
        # lets Day 1's own drop help itself pass. That's a no-op by algebra:
        # "Close < (sum_prev9 + Close)/10" reduces exactly to
        # "Close < avg(prev9)". This test proves the two give an IDENTICAL
        # boolean result on a real "sharp Day 1, no real prior decline"
        # fixture, so nobody re-introduces the exclusive-SMA10 change
        # expecting it to filter anything the inclusive version doesn't.
        rows = _baseline_rows(n_quiet=25)
        rows.append({"trade_date": "2026-01-06", "open": 101.5, "high": 102, "low": 93.5, "close": 94.5, "volume": 48000})
        rows.append({"trade_date": "2026-01-07", "open": 92.75, "high": 93.5, "low": 91.5, "close": 92.80, "volume": 30000})
        rows.append({"trade_date": "2026-01-08", "open": 93.5, "high": 101.5, "low": 93, "close": 100.5, "volume": 95000})
        df = pd.DataFrame(rows)

        det = MorningStarDetector()
        clean = det._prepare(df, "trade_date")
        ind = det._compute_indicators(clean)
        day1_close = clean["close"].iloc[25]
        sma10_inclusive = ind["sma10"].iloc[25]
        sma10_exclusive = ind["sma10"].shift(1).iloc[25]
        self.assertEqual(day1_close < sma10_inclusive, day1_close < sma10_exclusive)
        # And: this single sharp Day 1 crash genuinely does clear both --
        # Filter A is satisfied here with no real preceding multi-day
        # decline, a known, documented, unfixed limitation of the spec's
        # own rule (not a coding bug).
        self.assertTrue(day1_close < sma10_inclusive)


    # --- Evening Star (bearish mirror) ---

    def test_evening_star_textbook_detected(self):
        # Flat baseline, then a 6-day strictly-ascending rising tail
        # (higher_close_count_6 = 6 >= trend_min_higher_closes=5) feeding
        # into Day 1 (large bullish), Day 2 (tiny body, any color), Day 3
        # (large bearish, closing well below Day 1's 50% midpoint of
        # 105 + (112-105)/2 = 108.5).
        rows = _baseline_rows(n_quiet=20) + _rising_rows([100, 101, 102, 103, 104, 105])
        rows.append({"trade_date": "2026-01-07", "open": 105, "high": 112.5, "low": 104.8, "close": 112, "volume": 50000})
        rows.append({"trade_date": "2026-01-08", "open": 112.3, "high": 112.8, "low": 112.0, "close": 112.6, "volume": 30000})
        # Day 3 closes at 107 -- below the 108.5 midpoint (valid penetration)
        # but still ABOVE Day 1's open (105). This matters for target_1:
        # per the exact spec, target_1 = Day 1 Open (a flat level, not
        # "entry +/- a measured distance" the way the bullish target_1
        # is constructed) -- it is only guaranteed to sit on the correct
        # side of entry_price if Day 3 has NOT already fallen below Day
        # 1's open by signal time. A steeper Day 3 (closing below 105)
        # would make target_1 > entry_price, an already-passed target at
        # the moment of signal -- a genuine property of the literal spec
        # formula, not a fixture bug, but one this "textbook" case avoids
        # by construction to keep the risk parameters sane.
        rows.append({"trade_date": "2026-01-09", "open": 112.5, "high": 113, "low": 106.5, "close": 107, "volume": 80000})
        df = pd.DataFrame(rows)

        result = MorningStarDetector().detect_evening_star(df, date_col="trade_date")

        self.assertEqual(len(result), 1, msg=f"result={result}")
        row = result.iloc[0]
        self.assertEqual(row["pattern"], "Evening Star")
        self.assertEqual(str(row["date"].date()), "2026-01-09")
        self.assertGreater(row["day3_penetration_pct"], 0)
        self.assertGreaterEqual(row["volume_ratio_day3"], 1.3)
        self.assertEqual(row["entry_price"], 107.0)
        # Risk parameters internally consistent for a SHORT trade: stop
        # ABOVE entry (plus sign), targets BELOW entry.
        self.assertGreater(row["stop_loss"], row["entry_price"])
        self.assertLess(row["target_1"], row["entry_price"])
        self.assertLess(row["target_2"], row["target_1"])

    def test_evening_star_day3_above_midpoint_rejected(self):
        # Same setup, but Day 3 only pulls back to 110 -- still bearish
        # (112.5 -> 110) but ABOVE Day 1's 108.5 midpoint, so the single
        # non-negotiable 50% rule fails.
        rows = _baseline_rows(n_quiet=20) + _rising_rows([100, 101, 102, 103, 104, 105])
        rows.append({"trade_date": "2026-01-07", "open": 105, "high": 112.5, "low": 104.8, "close": 112, "volume": 50000})
        rows.append({"trade_date": "2026-01-08", "open": 112.3, "high": 112.8, "low": 112.0, "close": 112.6, "volume": 30000})
        rows.append({"trade_date": "2026-01-09", "open": 112.5, "high": 113, "low": 109.5, "close": 110, "volume": 80000})
        df = pd.DataFrame(rows)  # midpoint = 105 + (112-105)/2 = 108.5; Day3 close 110 is ABOVE it

        result = MorningStarDetector().detect_evening_star(df, date_col="trade_date")
        self.assertTrue(result.empty)

    def test_evening_star_no_prior_uptrend_rejected(self):
        # Identical Day 1/2/3 geometry, but the 6 days immediately before
        # Day 1 are FLAT/declining, not rising -- higher_close_count_6
        # stays well under the trend_min_higher_closes=5 floor.
        rows = _baseline_rows(n_quiet=20) + _decline_rows([105, 104, 103, 102, 101, 100], start_date_prefix="2025-12")
        rows.append({"trade_date": "2026-01-07", "open": 105, "high": 112.5, "low": 104.8, "close": 112, "volume": 50000})
        rows.append({"trade_date": "2026-01-08", "open": 112.3, "high": 112.8, "low": 112.0, "close": 112.6, "volume": 30000})
        rows.append({"trade_date": "2026-01-09", "open": 112.5, "high": 113, "low": 99.5, "close": 100, "volume": 80000})
        df = pd.DataFrame(rows)

        result = MorningStarDetector().detect_evening_star(df, date_col="trade_date")
        self.assertTrue(result.empty)


if __name__ == "__main__":
    unittest.main()
