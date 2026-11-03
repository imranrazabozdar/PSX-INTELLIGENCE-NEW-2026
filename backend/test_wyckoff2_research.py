"""Tests for Wyckoff Accumulation 2.0 (RESEARCH) and its production-safety guarantees."""
import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import wyckoff2_research as w2
import run_wyckoff2_backtest as bt


def _df(n=500, seed=0):
    r = np.random.default_rng(seed).normal(0, 0.015, n)
    c = 100 * np.exp(np.cumsum(r))
    o = c * (1 + np.random.default_rng(seed + 1).normal(0, 0.003, n))
    return pd.DataFrame({"trade_date": pd.bdate_range("2022-01-03", periods=n), "open": o,
                         "high": np.maximum(o, c) * 1.01, "low": np.minimum(o, c) * 0.99, "close": c,
                         "volume": np.random.default_rng(seed + 2).lognormal(13, 0.4, n)})


def _mkt(n=500):
    return pd.Series(np.cumprod(1 + np.random.default_rng(9).normal(0, 0.01, n)) * 100,
                     index=pd.bdate_range("2022-01-03", periods=n))


def test_point_in_time_no_future_dependence():
    df, mk = _df(), _mkt()
    full = w2.compute(df, mk)
    mod = df.copy()
    mod.loc[400:, ["open", "high", "low", "close"]] *= 2.5
    mod.loc[400:, "volume"] *= 9
    part = w2.compute(mod, mk)
    cols = ["abs_q", "obv_q", "struct_q", "rs_q", "enh_class", "orig_score", "orig_signal"]
    pd.testing.assert_frame_equal(full.iloc[:400][cols], part.iloc[:400][cols])


def test_pivot_is_only_known_after_confirmation():
    low = np.array([5, 4, 3, 1, 3, 4, 5, 6], float)
    piv = w2.confirmed_pivot_lows(low, k=3)
    assert piv == [(3, 6)]                       # pivot at 3 usable from bar 6, not earlier


def test_original_score_comes_from_unchanged_production_detector():
    from fire_engine.wyckoff_detector import WyckoffDetector, DEFAULT_CONFIG
    df = _df()
    f = w2.compute(df, _mkt())
    ref = WyckoffDetector().detect_stealth_accumulation(w2.normalise(df), None)
    assert (f["orig_score"].to_numpy() == ref["accumulation_score"].to_numpy()).all()
    assert (DEFAULT_CONFIG["watch_threshold"], DEFAULT_CONFIG["ready_threshold"], DEFAULT_CONFIG["extreme_threshold"]) == (60, 70, 85)


def test_two_sided_high_volume_is_penalised():
    df = _df(300, 4)
    base = w2.compute(df, _mkt(300))
    d2 = df.copy()
    for i in range(285, 295):                         # wide-range, mid-close, heavy-volume sessions
        mid = d2.loc[i, "close"]
        d2.loc[i, ["open", "high", "low", "close", "volume"]] = [mid, mid * 1.05, mid * 0.95, mid, 5e7]
    hv = w2.compute(d2, _mkt(300))
    assert hv["two_sided"].iloc[-1]
    assert hv["abs_q"].iloc[-1] < 60


def test_classification_rules_and_failed_accumulation():
    out = pd.DataFrame({"abs_q": [70, 70, 0], "obv_q": [70, 70, 0], "struct_q": [70, 70, 0], "rs_q": [70, 70, 0],
                        "atr_contraction": [0.8, 0.8, 1.2], "pos_in_base": [0.7, 0.7, 0.1], "dist_res_pct": [10, 2, 30],
                        "close": [10, 10, 7], "range_lo": [8, 8, 8]})
    w2.classify(out, w2.DEFAULT_THRESHOLDS)
    assert list(out["enh_class"]) == ["ADVANCED ACCUMULATION", "POTENTIAL BREAKOUT", "FAILED ACCUMULATION"]
    assert list(out["confirming"]) == [4, 4, 0]


def _raw(o, h, l, c, v=None):
    n = len(c)
    v = np.full(n, 1e6) if v is None else np.asarray(v, float)
    return {"open": np.asarray(o, float), "high": np.asarray(h, float), "low": np.asarray(l, float),
            "close": np.asarray(c, float), "volume": v, "vsma_prior": np.full(n, 1e6)}


def test_entry_into_upper_lock_is_unfilled():
    c = np.full(40, 100.0)
    c[11:] = 110.0
    r = bt.forward(_raw(c, c, c, c), 10, 105)
    assert r == {"unfilled": True}


def test_gap_through_stop_fills_at_open_and_lower_lock_cannot_exit():
    c = np.full(40, 100.0)
    o, h, l = c.copy(), c * 1.001, c * 0.999
    o[13] = h[13] = l[13] = c[13] = 90.0                       # locked lower circuit: cannot sell
    o[14], h[14], l[14], c[14] = 88.0, 89.0, 87.0, 88.5
    c[15:] = o[15:] = h[15:] = l[15:] = 88.5
    r = bt.forward(_raw(o, h, l, c), 10, 150)
    assert r["trade"] == "stop" and r["held"] == 4                # exit on the first unlocked session
    assert r["trade_ret"] == pytest.approx((88.0 * (1 - bt.SLIP) / (100 * (1 + bt.SLIP)) - 1 - bt.COST) * 100)


def test_breakout_needs_close_above_resistance_on_volume_and_failure_is_tracked():
    c = np.full(40, 100.0)
    v = np.full(40, 1e6)
    c[15], v[15] = 106.0, 2e6                                  # breakout over 105 on 2x volume
    c[16] = 104.0                                              # back below within 5 -> failed
    r = bt.forward(_raw(c, c * 1.001, c * 0.999, c, v), 10, 105)
    assert r["breakout"] and r["t_breakout"] == 5 and r["failed_breakout"]
    c2 = c.copy()
    c2[15], v2 = 106.0, np.full(40, 1e6)                       # same close, normal volume -> no breakout
    assert not bt.forward(_raw(c2, c2 * 1.001, c2 * 0.999, c2, v2), 10, 105)["breakout"]


def test_cluster_ci_requires_multiple_dates():
    assert bt.cluster_ci([1, 0, 1], ["d", "d", "d"]) == (None, None)
    lo, hi = bt.cluster_ci([1, 0] * 30, list(range(60)))
    assert lo < 50 < hi


def test_production_files_not_modified_by_research():
    import subprocess
    for f in ("fire_engine/wyckoff_detector.py", "fire_engine/wyckoff_scheduler.py", "fire_engine/run_wyckoff_batch.py",
              "fire_engine/scheduler.py", "backend/obv_mfi_scanner.py", "backend/volatility_engine.py"):
        diff = subprocess.run(["git", "diff", "--stat", "origin/main", "--", f], cwd=ROOT, capture_output=True, text=True).stdout
        assert diff.strip() == "", f"{f} changed"
