"""Required tests for CupHandleEngine, same 9 categories as
test_advanced_patterns.py (textbook / near-miss / lookahead /
multi-symbol isolation / PSX edge case).

Run with: python -m unittest test_cup_handle -v
"""

import unittest

import numpy as np
import pandas as pd

from cup_handle_engine import CupHandleEngine, CupHandleConfig
from test_advanced_patterns import build_ihs_fixture, _leg, _to_df


def build_cup_handle_fixture(symbol="CUPTEST", pre_low_price=28.0, p1_price=101.0, t1_price=25.75,
                              p2_price=100.0, t2_price=96.7, breakout_close=103.0, breakout_vol=500000,
                              rise_sessions=25, cup_down_sessions=30, cup_up_sessions=30,
                              handle_sessions=10, dip_sessions=25, flat_baseline=120):
    """Textbook-shaped Cup & Handle: flat baseline, a large prior RISE
    (direction-inverted vs IHS/Double Bottom, per the Cup & Handle spec),
    then P1(high)-T1(low, cup bottom)-P2(high, right rim)-T2(low, handle
    bottom)-breakout. Default parameters produce a clean VALID signal
    (empirically verified); each near-miss test overrides exactly one
    relationship to violate one rule. The prior rise and cup depth are
    proportionally large (not realistic percentages) purely so that a
    TIGHT handle (<=7.5% of cup height) still clears pivots.py's
    min_swing_pct=3% amplitude floor in absolute price terms -- cup_height
    must be at least ~0.4x the rim price for a tight handle to register
    as a genuine pivot at all; this is a structural property of the
    amplitude filter, not a choice specific to this fixture. Session
    counts for the dip/cup legs are deliberately generous (not just
    enough to form the swing) so no single bar-to-bar close move exceeds
    _preflight's unadjusted_gap_pct=15% threshold -- a steep swing spread
    over too few bars is indistinguishable from an un-adjusted corporate
    action and gets the whole symbol rejected before pattern detection
    ever runs."""
    rows = []
    rows += _leg(100, 100, flat_baseline)
    rows += _leg(100, pre_low_price, dip_sessions, vol=150000)
    rows += _leg(pre_low_price, p1_price, rise_sessions, vol=180000)
    rows += _leg(p1_price, t1_price, cup_down_sessions, vol=170000)
    rows += _leg(t1_price, p2_price, cup_up_sessions, vol=160000)
    rows += _leg(p2_price, t2_price, handle_sessions, vol=150000)
    rows += _leg(t2_price, breakout_close - 1.0, 6, vol=150000)
    rows.append({"open": breakout_close - 0.8, "high": breakout_close + 0.3,
                  "low": breakout_close - 1.0, "close": breakout_close, "volume": breakout_vol})
    rows += _leg(breakout_close, breakout_close + 3, 10)
    return _to_df(rows, symbol)


class TestTextbookFixtures(unittest.TestCase):
    def test_textbook_cup_handle_detected_with_confidence_above_070(self):
        df = build_cup_handle_fixture()
        result = CupHandleEngine().scan(df)
        self.assertEqual(len(result.signals), 1, msg=f"rejected={result.rejected} expired={result.expired}")
        sig = result.signals[0]
        self.assertEqual(sig["pattern_type"], "CUP_HANDLE")
        self.assertGreater(sig["confidence_score"], 0.70, msg=f"components={sig['confidence_components']}")
        self.assertGreaterEqual(sig["risk_reward_measured"], 1.0)


class TestNearMissFixtures(unittest.TestCase):
    def test_prior_rise_only_4pct_rejected(self):
        # p1 pivot = 101.6; pre_low pivot = 97.2 -> rise = (101.6-97.2)/97.2
        # = 4.53%, below the 10% prior_rise_pct floor but still above
        # pivots.py's 3% amplitude floor so P1 still registers as a pivot.
        df = build_cup_handle_fixture(pre_low_price=97.8)
        result = CupHandleEngine().scan(df)
        self.assertEqual(len(result.signals), 0)
        reasons = {r["reason"] for r in result.rejected if r["pattern_type"] == "CUP_HANDLE"}
        self.assertIn("no_prior_uptrend", reasons, msg=f"rejected={result.rejected}")

    def test_cup_too_deep_rejected(self):
        # Moderate rise (~20%) with a very deep cup (~50% of rim) ->
        # cup_depth_pct_of_rise ~= 250%, far above the 33% cutoff.
        df = build_cup_handle_fixture(pre_low_price=85.3, t1_price=51.4)
        result = CupHandleEngine().scan(df)
        self.assertEqual(len(result.signals), 0)
        reasons = {r["reason"] for r in result.rejected if r["pattern_type"] == "CUP_HANDLE"}
        self.assertIn("cup_too_deep", reasons, msg=f"rejected={result.rejected}")

    def test_handle_too_deep_rejected(self):
        # t2 pivot pulled down to 70.4 -> handle_depth_pct = (100.6-70.4)
        # / 75.45 * 100 = 40.03%, clearly above the 30% handle_max_depth_pct
        # (recalibrated from 15.0 -> 30.0 during the PSX parameter
        # recalibration round -- the original 80.0 override here produced
        # only ~28.1%, which cleared the new 30% ceiling and silently
        # started passing. Pushed to 40%+ margin to avoid sitting close to
        # the boundary again if the threshold moves slightly in the future).
        df = build_cup_handle_fixture(t2_price=71.0)
        result = CupHandleEngine().scan(df)
        self.assertEqual(len(result.signals), 0)
        reasons = {r["reason"] for r in result.rejected if r["pattern_type"] == "CUP_HANDLE"}
        self.assertIn("handle_too_deep", reasons, msg=f"rejected={result.rejected}")

    def test_breakout_volume_only_1_2x_expires_not_signals(self):
        df = build_cup_handle_fixture(breakout_vol=170000)
        result = CupHandleEngine().scan(df)
        self.assertEqual(len(result.signals), 0)
        self.assertTrue(any(e["pattern_type"] == "CUP_HANDLE" for e in result.expired),
                         msg=f"rejected={result.rejected} expired={result.expired}")

    def test_rim_asymmetry_over_5pct_rejected(self):
        # p2 pivot pushed to 108.0 vs p1 pivot 101.6 -> symmetry =
        # |101.6-108.0|/101.6*100 = 6.3%, above the 5% ceiling.
        df = build_cup_handle_fixture(p2_price=107.4)
        result = CupHandleEngine().scan(df)
        self.assertEqual(len(result.signals), 0)
        reasons = {r["reason"] for r in result.rejected if r["pattern_type"] == "CUP_HANDLE"}
        self.assertIn("rims_not_symmetric", reasons, msg=f"rejected={result.rejected}")


class TestNoLookahead(unittest.TestCase):
    def test_truncated_series_matches_full_series_up_to_same_date(self):
        df = build_cup_handle_fixture()
        full_result = CupHandleEngine().scan(df)
        self.assertEqual(len(full_result.signals), 1, msg=f"rejected={full_result.rejected}")
        breakout_index = full_result.signals[0]["signal_index"]

        truncated = df.iloc[: breakout_index + 1].reset_index(drop=True)
        truncated_result = CupHandleEngine().scan(truncated)

        self.assertEqual(len(truncated_result.signals), 1,
                          msg=f"rejected={truncated_result.rejected} expired={truncated_result.expired}")
        full_sig = {k: v for k, v in full_result.signals[0].items() if k != "_dedup_key"}
        trunc_sig = {k: v for k, v in truncated_result.signals[0].items() if k != "_dedup_key"}
        self.assertEqual(full_sig, trunc_sig, msg="Truncated-series signal differs from full-series "
                                                   "signal up to the same date -- lookahead exists.")


class TestMultiSymbolIsolation(unittest.TestCase):
    def test_two_symbols_interleaved_no_cross_contamination(self):
        df_a = build_cup_handle_fixture(symbol="SYMA")
        df_b = build_ihs_fixture(symbol="SYMB")
        combined = pd.concat([df_a, df_b], ignore_index=True)

        engine = CupHandleEngine()
        result_a_alone = engine.scan(df_a)
        result_combined = engine.scan(combined)

        sigs_a_combined = [s for s in result_combined.signals if s["symbol"] == "SYMA"]
        sigs_b_combined = [s for s in result_combined.signals if s["symbol"] == "SYMB"]

        self.assertEqual(len(sigs_a_combined), len(result_a_alone.signals))
        if sigs_a_combined:
            self.assertEqual(sigs_a_combined[0]["entry_price"], result_a_alone.signals[0]["entry_price"])
            self.assertEqual(sigs_a_combined[0]["pattern_type"], "CUP_HANDLE")
        # SYMB is an IHS fixture -- CupHandleEngine has no IHS detection at
        # all, so it must never emit a CUP_HANDLE signal for it.
        for s in sigs_b_combined:
            self.assertEqual(s["pattern_type"], "CUP_HANDLE")  # would fail loudly if this ever fired
        self.assertEqual(len(sigs_b_combined), 0, msg=f"SYMB produced spurious signals: {sigs_b_combined}")


class TestPsxEdgeCases(unittest.TestCase):
    def test_locked_bar_and_zero_volume_in_cup_do_not_crash_or_signal(self):
        df = build_cup_handle_fixture().copy()
        rows = df.to_dict("records")

        # Locked-limit bar inside the cup-down leg: high == low, abnormally
        # low volume.
        lock_idx = 140
        rows[lock_idx]["high"] = rows[lock_idx]["low"] = rows[lock_idx]["open"] = rows[lock_idx]["close"]
        rows[lock_idx]["volume"] = 1

        # Zero-volume bar inside the cup-up leg (no lock, just no trades).
        zv_idx = 155
        rows[zv_idx]["volume"] = 0

        edge_df = pd.DataFrame(rows)
        try:
            result = CupHandleEngine().scan(edge_df)
        except Exception as e:  # pragma: no cover - must never happen
            self.fail(f"scan() raised on PSX edge-case data: {e!r}")
        for s in result.signals:
            pivot_indices = {p["index"] for p in s["pivots"]}
            self.assertNotIn(lock_idx, pivot_indices)
            self.assertNotIn(zv_idx, pivot_indices)


if __name__ == "__main__":
    unittest.main()
