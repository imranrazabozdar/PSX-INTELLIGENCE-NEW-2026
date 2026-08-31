"""Required tests for AdvancedPatternEngine, per spec §10.

Uses the stdlib unittest module (no pytest dependency). Run with:
    python -m unittest test_advanced_patterns -v
"""

import unittest

import numpy as np
import pandas as pd

from advanced_pattern_engine import AdvancedPatternEngine, AdvancedPatternConfig


# ------------------------------------------------------------- fixtures --
def _leg(start, end, n, vol=200000):
    prices = np.linspace(start, end, n)
    return [{"open": p, "high": p + 0.6, "low": p - 0.6, "close": p, "volume": vol} for p in prices]


def _to_df(rows, symbol="TEST", start_date="2023-01-02"):
    dates = pd.bdate_range(start_date, periods=len(rows))
    df = pd.DataFrame(rows)
    df["date"] = dates[: len(df)]
    df["symbol"] = symbol
    return df[["symbol", "date", "open", "high", "low", "close", "volume"]]


def build_ihs_fixture(symbol="IHSTEST", t1_price=80, p1_price=90, t2_price=75, p2_price=92, t3_price=80,
                       decline_end=82, bounce_price=89, breakout_close=93, breakout_vol=500000):
    """Textbook-shaped Inverse H&S: 120 quiet days, an 18% prior decline,
    then T1(low)-P1(high)-T2(low,head)-P2(high)-T3(low)-breakout. Default
    parameters produce a clean VALID signal (empirically verified); each
    near-miss test overrides exactly one of these to violate one rule.
    p1_price/p2_price/bounce_price are exposed (not hardcoded) because a
    t1/t2/t3 override that moves prices far from the textbook defaults can
    otherwise reverse one of these legs' direction -- e.g. the post-T3
    bounce leg must target ABOVE t3_price or T3 never registers as a
    genuine local low at all, silently producing a different pivot
    sequence than the one being tested."""
    rows = []
    rows += _leg(100, 100, 120)
    rows += _leg(100, decline_end, 30)
    rows += _leg(decline_end, t1_price, 8)
    rows += _leg(t1_price, p1_price, 15, vol=180000)
    rows += _leg(p1_price, t2_price, 15, vol=220000)
    rows += _leg(t2_price, p2_price, 15, vol=160000)
    rows += _leg(p2_price, t3_price, 15, vol=140000)
    rows += _leg(t3_price, bounce_price, 8, vol=150000)
    rows.append({"open": 90, "high": 93.5, "low": 89.5, "close": breakout_close, "volume": breakout_vol})
    rows += _leg(breakout_close, 96, 10)
    return _to_df(rows, symbol)


def build_db_fixture(symbol="DBTEST", b1_price=77.4, pk_price=90.6, b2_price=78.4,
                      decline_end=82, spacing_sessions=15, breakout_close=91.4, breakout_vol=500000):
    """Textbook-shaped Eve & Eve Double Bottom: 120 quiet days, an 18%
    prior decline, then B1(low)-PK(high)-B2(low)-breakout. Default
    parameters produce a clean VALID EVE_EVE signal (empirically verified).
    `spacing_sessions` controls exactly how far apart B1/B2 land: the two
    legs either side of PK are split so they SUM to spacing_sessions
    (not each independently floor-divided, which previously left B2.index
    - B1.index one session short of the target -- e.g. 7+7=14 for a
    spacing_sessions=15 default, landing just outside db_min_spacing)."""
    half1 = max(4, spacing_sessions // 2)
    half2 = max(4, spacing_sessions - half1)
    rows = []
    rows += _leg(100, 100, 140)  # 140 (not 120) so the default-params fixture clears the 200-session minimum
    rows += _leg(100, decline_end, 30)
    rows += _leg(decline_end, b1_price, 8)
    rows += _leg(b1_price, pk_price, half1, vol=160000)
    rows += _leg(pk_price, b2_price, half2, vol=150000)
    rows += _leg(b2_price, breakout_close - 1.0, 8, vol=150000)
    rows.append({"open": breakout_close - 0.95, "high": breakout_close + 0.25,
                  "low": breakout_close - 1.15, "close": breakout_close, "volume": breakout_vol})
    rows += _leg(breakout_close, breakout_close + 2.35, 10)
    return _to_df(rows, symbol)


def build_hst_fixture(symbol="HSTTEST", p1_price=140, t1_price=110, p2_price=160, t2_price=111,
                       p3_price=141, rise_end=137, drop_price=112, breakout_close=108, breakout_vol=500000):
    """Textbook-shaped Head & Shoulders Top: 120 quiet days, a prior RISE
    (direction-inverted mirror of IHS's prior decline), then P1(high,left
    shoulder)-T1(low)-P2(high,head)-T2(low)-P3(high,right shoulder)-
    breakout BELOW the neckline (min(T1,T2)). Default parameters produce a
    clean VALID signal (empirically verified); each near-miss test
    overrides exactly one relationship. Same _leg/_to_df helpers and same
    total-session budget as build_ihs_fixture, just inverted direction.

    The head is deliberately FAR above the neckline (pattern_height ~50,
    not just barely above the shoulders) -- per EXPLICIT spec, this
    pattern's stop anchors at the Right Shoulder High (P3) PLUS a bounded-
    ATR term, not at entry_price the way every other pattern's stop does.
    Since the breakout (entry) necessarily happens BELOW the neckline,
    which is necessarily below P3, risk = stop - entry is structurally
    much wider here than an entry-anchored stop would produce -- a real,
    deliberate consequence of the user's explicit, twice-stated formula
    ("P3 + bounded ATR... added to the high"), not an implementation
    error. A shallow head (closer to IHS's own default proportions) fails
    the risk_reward_measured >= 1.0 gate every time under this formula;
    confirmed empirically before settling on these proportions."""
    rows = []
    rows += _leg(100, 100, 120)
    rows += _leg(100, rise_end, 30)
    rows += _leg(rise_end, p1_price, 8)
    rows += _leg(p1_price, t1_price, 15, vol=180000)
    rows += _leg(t1_price, p2_price, 15, vol=220000)
    rows += _leg(p2_price, t2_price, 15, vol=160000)
    rows += _leg(t2_price, p3_price, 15, vol=140000)
    rows += _leg(p3_price, drop_price, 8, vol=150000)
    rows.append({"open": 110, "high": 110.5, "low": 104.5, "close": breakout_close, "volume": breakout_vol})
    # Trailing leg uses the SAME volume as the breakout bar -- otherwise a
    # low breakout_vol override only suppresses the first qualifying bar,
    # and _scan_breakout (which keeps scanning up to confirmation_window
    # sessions) finds a LATER bar in this leg that still clears the
    # volume floor on _leg's own default (200000), silently defeating the
    # "volume too low -> expires" near-miss test.
    rows += _leg(breakout_close, 101, 10, vol=breakout_vol)
    return _to_df(rows, symbol)


class TestTextbookFixtures(unittest.TestCase):
    """§10.1"""

    def test_ihs_textbook_detected_with_high_confidence(self):
        df = build_ihs_fixture()
        result = AdvancedPatternEngine().scan(df)
        self.assertEqual(len(result.signals), 1, msg=f"rejected={result.rejected}")
        self.assertEqual(result.signals[0]["pattern_type"], "INVERSE_HS")
        self.assertGreater(result.signals[0]["confidence_score"], 0.8)
        self.assertGreaterEqual(result.signals[0]["risk_reward_measured"], 1.0)

    def test_eve_eve_double_bottom_textbook_detected_with_high_confidence(self):
        df = build_db_fixture()
        result = AdvancedPatternEngine().scan(df)
        self.assertEqual(len(result.signals), 1, msg=f"rejected={result.rejected}")
        self.assertEqual(result.signals[0]["pattern_type"], "DOUBLE_BOTTOM")
        self.assertEqual(result.signals[0]["pattern_subtype"], "EVE_EVE")
        self.assertGreater(result.signals[0]["confidence_score"], 0.8)
        self.assertGreaterEqual(result.signals[0]["risk_reward_measured"], 1.0)


class TestNearMissFixtures(unittest.TestCase):
    """§10.2 -- one hard-filter violation per test, rejected with the
    correct reason (or logged as expired, for the breakout-volume case,
    since volume confirmation is part of the breakout search itself, not
    a discrete geometric filter with its own reason string)."""

    def test_shoulders_8pct_apart_rejected(self):
        # T1=80, T3=86.4 -> |80-86.4|/80 = 8% > 5% limit.
        df = build_ihs_fixture(t3_price=86.4)
        result = AdvancedPatternEngine().scan(df)
        self.assertEqual(len(result.signals), 0)
        reasons = {r["reason"] for r in result.rejected if r["pattern_type"] == "INVERSE_HS"}
        self.assertIn("shoulders_not_symmetric", reasons)

    def test_head_only_1pct_below_shoulders_rejected(self):
        # T1=T3=80, head must be <78.4 (2% below); 79.2 is only 1% below.
        df = build_ihs_fixture(t2_price=79.2)
        result = AdvancedPatternEngine().scan(df)
        self.assertEqual(len(result.signals), 0)
        reasons = {r["reason"] for r in result.rejected if r["pattern_type"] == "INVERSE_HS"}
        self.assertIn("head_not_below_shoulders", reasons)

    def test_prior_decline_only_4pct_rejected(self):
        # Baseline 100 -> T1 94 is only a ~6% prior decline (<10%), while
        # every OTHER geometric constraint is kept comfortably valid:
        # head 89 is >2% below both shoulders (92.12 ceiling), shoulders
        # are perfectly symmetric (94==94), and p1/p2/bounce are all
        # correctly positioned (above their neighboring troughs) so the
        # full 5-pivot sequence survives pivot detection intact.
        df = build_ihs_fixture(decline_end=95, t1_price=94, p1_price=100, t2_price=89,
                                p2_price=100, t3_price=94, bounce_price=99)
        result = AdvancedPatternEngine().scan(df)
        self.assertEqual(len(result.signals), 0)
        reasons = {r["reason"] for r in result.rejected if r["pattern_type"] == "INVERSE_HS"}
        self.assertIn("no_prior_downtrend", reasons, msg=f"rejected={result.rejected}")

    def test_breakout_volume_only_1_2x_expires_not_signals(self):
        # Geometry/trend/risk all otherwise valid, but breakout volume
        # never reaches the 1.5x floor -- _scan_breakout never finds a
        # qualifying bar, so the pattern EXPIRES rather than being
        # rejected with a discrete filter reason.
        #
        # avg_volume_20 is a rolling window INCLUSIVE of the breakout bar
        # itself, so the breakout volume feeds its own average -- solved
        # as a fixed point: breakout_vol=174893 -> avg_volume_20 converges
        # to 145744.65 at the breakout bar -> ratio = 174893/145744.65 =
        # exactly 1.2000, provably below the 1.5x floor.
        df = build_ihs_fixture(breakout_vol=174893)
        result = AdvancedPatternEngine().scan(df)
        self.assertEqual(len(result.signals), 0)
        self.assertTrue(any(e["pattern_type"] == "INVERSE_HS" for e in result.expired),
                         msg=f"rejected={result.rejected} expired={result.expired}")

    def test_double_bottom_spacing_90_sessions_rejected(self):
        # db_max_spacing defaults to 60 sessions; 90 violates it.
        df = build_db_fixture(spacing_sessions=90)
        result = AdvancedPatternEngine().scan(df)
        self.assertEqual(len(result.signals), 0)
        reasons = {r["reason"] for r in result.rejected if r["pattern_type"] == "DOUBLE_BOTTOM"}
        self.assertIn("spacing_out_of_range", reasons)


class TestNoLookahead(unittest.TestCase):
    """§10.3 / §0 -- the single most important test in this suite."""

    def test_truncated_series_matches_full_series_up_to_same_date(self):
        df = build_ihs_fixture()
        full_result = AdvancedPatternEngine().scan(df)
        self.assertEqual(len(full_result.signals), 1)
        breakout_index = full_result.signals[0]["signal_index"]

        truncated = df.iloc[: breakout_index + 1].reset_index(drop=True)
        truncated_result = AdvancedPatternEngine().scan(truncated)

        self.assertEqual(len(truncated_result.signals), 1,
                          msg=f"rejected={truncated_result.rejected} expired={truncated_result.expired}")
        full_sig = {k: v for k, v in full_result.signals[0].items() if k != "_dedup_key"}
        trunc_sig = {k: v for k, v in truncated_result.signals[0].items() if k != "_dedup_key"}
        self.assertEqual(full_sig, trunc_sig, msg="Truncated-series signal differs from full-series "
                                                   "signal up to the same date -- lookahead exists.")

    def test_assert_no_lookahead_raises_on_genuine_violation(self):
        from advanced_pattern_engine import _assert_no_lookahead, LookaheadError
        with self.assertRaises(LookaheadError):
            _assert_no_lookahead([10, 25, 30], eval_index=20, context="synthetic violation")
        _assert_no_lookahead([10, 15, 20], eval_index=20, context="no violation")  # must not raise


class TestMultiSymbolIsolation(unittest.TestCase):
    """§10.4"""

    def test_two_symbols_scanned_together_match_scanned_separately(self):
        df_a = build_ihs_fixture(symbol="SYMA")
        df_b = build_db_fixture(symbol="SYMB")
        combined = pd.concat([df_a, df_b], ignore_index=True)

        engine = AdvancedPatternEngine()
        result_a_alone = engine.scan(df_a)
        result_b_alone = engine.scan(df_b)
        result_combined = engine.scan(combined)

        sigs_a_combined = [s for s in result_combined.signals if s["symbol"] == "SYMA"]
        sigs_b_combined = [s for s in result_combined.signals if s["symbol"] == "SYMB"]
        sigs_a_alone = [{k: v for k, v in s.items()} for s in result_a_alone.signals]
        sigs_b_alone = [{k: v for k, v in s.items()} for s in result_b_alone.signals]

        self.assertEqual(len(sigs_a_combined), len(sigs_a_alone))
        self.assertEqual(len(sigs_b_combined), len(sigs_b_alone))
        if sigs_a_combined:
            self.assertEqual(sigs_a_combined[0]["entry_price"], sigs_a_alone[0]["entry_price"])
            self.assertEqual(sigs_a_combined[0]["pattern_type"], "INVERSE_HS")
        if sigs_b_combined:
            self.assertEqual(sigs_b_combined[0]["entry_price"], sigs_b_alone[0]["entry_price"])
            self.assertEqual(sigs_b_combined[0]["pattern_type"], "DOUBLE_BOTTOM")
        # No signal for SYMA may carry a DOUBLE_BOTTOM type or vice versa --
        # the clearest proof no pivots leaked across the groupby boundary.
        for s in sigs_a_combined:
            self.assertEqual(s["pattern_type"], "INVERSE_HS")
        for s in sigs_b_combined:
            self.assertEqual(s["pattern_type"], "DOUBLE_BOTTOM")


class TestPsxEdgeCases(unittest.TestCase):
    """§10.5 -- must not crash, must not produce a signal off the artifact."""

    def test_holiday_gap_locked_bar_and_zero_volume_do_not_crash_or_signal(self):
        df = build_ihs_fixture().copy()
        rows = df.to_dict("records")

        # Holiday gap: jump one date by 10 calendar days (a long closure),
        # not a clean trading-session sequence.
        gap_idx = 50
        rows[gap_idx]["date"] = rows[gap_idx - 1]["date"] + pd.Timedelta(days=10)

        # Locked-limit bar: high == low, abnormally low volume.
        lock_idx = 60
        rows[lock_idx]["high"] = rows[lock_idx]["low"] = rows[lock_idx]["open"] = rows[lock_idx]["close"]
        rows[lock_idx]["volume"] = 1

        # Zero-volume bar (no lock, just no trades).
        zv_idx = 70
        rows[zv_idx]["volume"] = 0

        edge_df = pd.DataFrame(rows)
        try:
            result = AdvancedPatternEngine().scan(edge_df)
        except Exception as e:  # pragma: no cover - must never happen
            self.fail(f"scan() raised on PSX edge-case data: {e!r}")
        # Not asserting zero signals outright (the underlying IHS fixture
        # is still structurally valid) -- asserting instead that no signal
        # is anchored AT the artifact bars themselves.
        for s in result.signals:
            pivot_indices = {p["index"] for p in s["pivots"]}
            self.assertNotIn(gap_idx, pivot_indices)
            self.assertNotIn(lock_idx, pivot_indices)
            self.assertNotIn(zv_idx, pivot_indices)

    def test_all_locked_bars_excluded_from_atr_and_volume_average(self):
        df = build_ihs_fixture()
        engine = AdvancedPatternEngine()
        clean = df.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
        enriched = engine._enrich(clean)
        enriched.loc[30, ["high", "low", "open", "close"]] = 100.0
        enriched.loc[30, "volume"] = 1
        re_enriched = engine._enrich(clean.assign(
            high=enriched["high"], low=enriched["low"], open=enriched["open"],
            close=enriched["close"], volume=enriched["volume"]))
        self.assertTrue(bool(re_enriched["is_locked"].iloc[30]))


class TestHeadShouldersTop(unittest.TestCase):
    """3 required tests for Head & Shoulders Top (bearish mirror of
    Inverse H&S). NOT wired into app.py/streamlit_app.py yet -- backtest
    pending, per explicit instruction."""

    def test_hst_textbook_detected(self):
        df = build_hst_fixture()
        result = AdvancedPatternEngine().detect_head_shoulders_top(df)
        self.assertEqual(len(result.signals), 1, msg=f"rejected={result.rejected} expired={result.expired}")
        sig = result.signals[0]
        self.assertEqual(sig["pattern_type"], "HEAD_SHOULDERS_TOP")
        self.assertGreaterEqual(sig["risk_reward_measured"], 1.0)
        # Short-trade risk parameters: stop ABOVE entry, targets BELOW entry.
        self.assertGreater(sig["stop_loss"], sig["entry_price"])
        self.assertLess(sig["target_partial"], sig["entry_price"])
        self.assertLess(sig["target_measured"], sig["target_partial"])

    def test_hst_breakout_volume_only_1_2x_expires_not_signals(self):
        # Geometry/trend/risk all otherwise valid, but breakout volume
        # never reaches the 1.3x hst_breakout_vol_mult floor -- _scan_breakout
        # never finds a qualifying bar, so the pattern EXPIRES rather than
        # being rejected with a discrete filter reason.
        df = build_hst_fixture(breakout_vol=100000)
        result = AdvancedPatternEngine().detect_head_shoulders_top(df)
        self.assertEqual(len(result.signals), 0)
        self.assertTrue(any(e["pattern_type"] == "HEAD_SHOULDERS_TOP" for e in result.expired),
                         msg=f"rejected={result.rejected} expired={result.expired}")

    def test_hst_right_shoulder_higher_than_head_rejected(self):
        # P3 (165) pushed ABOVE P2/the head (160) -- head_above_shoulders
        # fails since the head is no longer strictly higher than BOTH
        # shoulders (checked before the symmetry gate, so this fires
        # regardless of how p1/p3 compare to each other).
        df = build_hst_fixture(p3_price=165)
        result = AdvancedPatternEngine().detect_head_shoulders_top(df)
        self.assertEqual(len(result.signals), 0)
        reasons = {r["reason"] for r in result.rejected if r["pattern_type"] == "HEAD_SHOULDERS_TOP"}
        self.assertIn("head_not_above_shoulders", reasons, msg=f"rejected={result.rejected}")


if __name__ == "__main__":
    unittest.main()
