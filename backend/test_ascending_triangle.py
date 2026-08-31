"""Required tests for AscendingTriangleEngine, same 9 categories as
test_cup_handle.py (textbook / near-miss / lookahead / multi-symbol
isolation / PSX edge case).

Run with: python -m unittest test_ascending_triangle -v
"""

import unittest

import numpy as np
import pandas as pd

from ascending_triangle_engine import AscendingTriangleEngine, AscendingTriangleConfig
from test_advanced_patterns import build_ihs_fixture, _leg, _to_df


def build_ascending_triangle_fixture(symbol="TRITEST", pre_low_price=60.0, p0_price=92.0,
                                      t1_price=88.0, p1_price=110.0, t2_price=90.0, p2_price=111.0,
                                      t3_price=92.0, p3_price=112.0, p3_pullback_price=109.0,
                                      breakout_close=115.0, breakout_vol=500000, dip_sessions=15,
                                      rise_sessions=16, pullback0_sessions=5, t1_p1_sessions=10,
                                      p1_t2_sessions=6, t2_p2_sessions=6, p2_t3_sessions=6,
                                      t3_p3_sessions=8, p3_pullback_sessions=6, bridge_sessions=6,
                                      flat_baseline=120):
    """Textbook-shaped Ascending Triangle: flat baseline, a large prior
    RISE (continuation pattern, same direction convention as Cup &
    Handle), a small pullback forming P0 (a spurious lead-in high,
    irrelevant to the gated window) then T1, then
    T1(low)-P1(high)-T2(low)-P2(high)-T3(low)-P3(high)-breakout, T1-first
    (IHS convention). Default parameters produce a clean VALID signal
    (empirically verified); each near-miss test overrides exactly one
    relationship. Session counts are generous (same lesson learned while
    building the Cup & Handle fixture) so no single bar-to-bar close move
    exceeds _preflight's unadjusted_gap_pct=15% threshold.

    IMPORTANT: P3 must fully CONFIRM as a fractal high (k=5 bars to its
    right with no higher high) BEFORE the breakout bar -- the engine's
    breakout search only starts at max(confirmed_at_index) across all six
    pivots, which for P3 (the highest index) is P3.index+k. A naive build
    that rises straight from T3 through P3's level into the breakout
    bar never lets P3 register as a pivot at all (discovered empirically:
    the first draft of this fixture produced only 7 pivots, with no P3).
    The fix is a genuine pullback after P3 -- p3_pullback_price -- giving
    P3 five bars of lower subsequent highs to confirm against, before a
    bridge leg climbs back up through the resistance level to breakout."""
    rows = []
    rows += _leg(100, 100, flat_baseline)
    rows += _leg(100, pre_low_price, dip_sessions, vol=150000)
    rows += _leg(pre_low_price, p0_price, rise_sessions, vol=180000)
    rows += _leg(p0_price, t1_price, pullback0_sessions, vol=160000)
    rows += _leg(t1_price, p1_price, t1_p1_sessions, vol=170000)
    rows += _leg(p1_price, t2_price, p1_t2_sessions, vol=160000)
    rows += _leg(t2_price, p2_price, t2_p2_sessions, vol=160000)
    rows += _leg(p2_price, t3_price, p2_t3_sessions, vol=160000)
    rows += _leg(t3_price, p3_price, t3_p3_sessions, vol=160000)
    rows += _leg(p3_price, p3_pullback_price, p3_pullback_sessions, vol=150000)
    rows += _leg(p3_pullback_price, breakout_close - 1.0, bridge_sessions, vol=150000)
    rows.append({"open": breakout_close - 0.8, "high": breakout_close + 0.3,
                  "low": breakout_close - 1.0, "close": breakout_close, "volume": breakout_vol})
    rows += _leg(breakout_close, breakout_close + 3, 10)
    return _to_df(rows, symbol)


class TestTextbookFixtures(unittest.TestCase):
    def test_textbook_ascending_triangle_detected_with_confidence_above_065(self):
        df = build_ascending_triangle_fixture()
        result = AscendingTriangleEngine().scan(df)
        self.assertEqual(len(result.signals), 1, msg=f"rejected={result.rejected} expired={result.expired}")
        sig = result.signals[0]
        self.assertEqual(sig["pattern_type"], "ASCENDING_TRIANGLE")
        self.assertGreater(sig["confidence_score"], 0.65, msg=f"components={sig['confidence_components']}")
        self.assertGreaterEqual(sig["risk_reward_measured"], 1.0)


class TestNearMissFixtures(unittest.TestCase):
    def test_prior_rise_only_4pct_rejected(self):
        # T1 pivot high ~= 88.6; pre_low pivot low ~= 84.8 -> rise ~= 4.48%,
        # below the 10% prior_rise_pct floor.
        df = build_ascending_triangle_fixture(pre_low_price=85.4)
        result = AscendingTriangleEngine().scan(df)
        self.assertEqual(len(result.signals), 0)
        reasons = {r["reason"] for r in result.rejected if r["pattern_type"] == "ASCENDING_TRIANGLE"}
        self.assertIn("no_prior_uptrend", reasons, msg=f"rejected={result.rejected}")

    def test_flat_top_too_loose_rejected(self):
        # P3 pivot pushed to 118.6 vs P1=110.6 -> flat_top_pct =
        # (118.6-110.6)/110.6*100 = 7.23%, above the 3% ceiling.
        df = build_ascending_triangle_fixture(p3_price=118.0)
        result = AscendingTriangleEngine().scan(df)
        self.assertEqual(len(result.signals), 0)
        reasons = {r["reason"] for r in result.rejected if r["pattern_type"] == "ASCENDING_TRIANGLE"}
        self.assertIn("flat_top_not_tight", reasons, msg=f"rejected={result.rejected}")

    def test_lows_not_ascending_by_min_step_rejected(self):
        # T2 pivot pulled to 87.9 vs T1=87.4 -> step = (87.9-87.4)/87.4*100
        # = 0.57%, below the 1.0% minimum step.
        df = build_ascending_triangle_fixture(t2_price=88.5)
        result = AscendingTriangleEngine().scan(df)
        self.assertEqual(len(result.signals), 0)
        reasons = {r["reason"] for r in result.rejected if r["pattern_type"] == "ASCENDING_TRIANGLE"}
        self.assertIn("lows_not_ascending", reasons, msg=f"rejected={result.rejected}")

    def test_breakout_volume_only_1_2x_expires_not_signals(self):
        df = build_ascending_triangle_fixture(breakout_vol=170000)
        result = AscendingTriangleEngine().scan(df)
        self.assertEqual(len(result.signals), 0)
        self.assertTrue(any(e["pattern_type"] == "ASCENDING_TRIANGLE" for e in result.expired),
                         msg=f"rejected={result.rejected} expired={result.expired}")

    def test_span_out_of_range_rejected(self):
        # Stretch every inter-pivot leg so T1->P3 span exceeds
        # triangle_max_span=75 (sum = 20+20+20+20+20 = 100).
        df = build_ascending_triangle_fixture(t1_p1_sessions=20, p1_t2_sessions=20,
                                                t2_p2_sessions=20, p2_t3_sessions=20, t3_p3_sessions=20)
        result = AscendingTriangleEngine().scan(df)
        self.assertEqual(len(result.signals), 0)
        reasons = {r["reason"] for r in result.rejected if r["pattern_type"] == "ASCENDING_TRIANGLE"}
        self.assertIn("span_out_of_range", reasons, msg=f"rejected={result.rejected}")


class TestNoLookahead(unittest.TestCase):
    def test_truncated_series_matches_full_series_up_to_same_date(self):
        df = build_ascending_triangle_fixture()
        full_result = AscendingTriangleEngine().scan(df)
        self.assertEqual(len(full_result.signals), 1, msg=f"rejected={full_result.rejected}")
        breakout_index = full_result.signals[0]["signal_index"]

        truncated = df.iloc[: breakout_index + 1].reset_index(drop=True)
        truncated_result = AscendingTriangleEngine().scan(truncated)

        self.assertEqual(len(truncated_result.signals), 1,
                          msg=f"rejected={truncated_result.rejected} expired={truncated_result.expired}")
        full_sig = {k: v for k, v in full_result.signals[0].items() if k != "_dedup_key"}
        trunc_sig = {k: v for k, v in truncated_result.signals[0].items() if k != "_dedup_key"}
        self.assertEqual(full_sig, trunc_sig, msg="Truncated-series signal differs from full-series "
                                                   "signal up to the same date -- lookahead exists.")


class TestMultiSymbolIsolation(unittest.TestCase):
    def test_two_symbols_interleaved_no_cross_contamination(self):
        df_a = build_ascending_triangle_fixture(symbol="SYMA")
        df_b = build_ihs_fixture(symbol="SYMB")
        combined = pd.concat([df_a, df_b], ignore_index=True)

        engine = AscendingTriangleEngine()
        result_a_alone = engine.scan(df_a)
        result_combined = engine.scan(combined)

        sigs_a_combined = [s for s in result_combined.signals if s["symbol"] == "SYMA"]
        sigs_b_combined = [s for s in result_combined.signals if s["symbol"] == "SYMB"]

        self.assertEqual(len(sigs_a_combined), len(result_a_alone.signals))
        if sigs_a_combined:
            self.assertEqual(sigs_a_combined[0]["entry_price"], result_a_alone.signals[0]["entry_price"])
            self.assertEqual(sigs_a_combined[0]["pattern_type"], "ASCENDING_TRIANGLE")
        # SYMB is an IHS fixture -- AscendingTriangleEngine has no IHS
        # detection at all, so it must never emit a signal for it.
        self.assertEqual(len(sigs_b_combined), 0, msg=f"SYMB produced spurious signals: {sigs_b_combined}")


class TestPsxEdgeCases(unittest.TestCase):
    def test_locked_bar_and_zero_volume_in_triangle_do_not_crash_or_signal(self):
        df = build_ascending_triangle_fixture().copy()
        rows = df.to_dict("records")

        # Locked-limit bar inside the T1->P1 leg: high == low, abnormally
        # low volume. Indices chosen to sit strictly between pivot indices
        # (T1=155, P1=165 in the default fixture) -- an earlier draft used
        # 150/165, and 165 turned out to coincide exactly with P1's own
        # pivot index, which the test is supposed to rule out, not collide
        # with by construction.
        lock_idx = 158
        rows[lock_idx]["high"] = rows[lock_idx]["low"] = rows[lock_idx]["open"] = rows[lock_idx]["close"]
        rows[lock_idx]["volume"] = 1

        # Zero-volume bar, also inside the T1->P1 leg (no lock, just no trades).
        zv_idx = 162
        rows[zv_idx]["volume"] = 0

        edge_df = pd.DataFrame(rows)
        try:
            result = AscendingTriangleEngine().scan(edge_df)
        except Exception as e:  # pragma: no cover - must never happen
            self.fail(f"scan() raised on PSX edge-case data: {e!r}")
        for s in result.signals:
            pivot_indices = {p["index"] for p in s["pivots"]}
            self.assertNotIn(lock_idx, pivot_indices)
            self.assertNotIn(zv_idx, pivot_indices)


if __name__ == "__main__":
    unittest.main()
