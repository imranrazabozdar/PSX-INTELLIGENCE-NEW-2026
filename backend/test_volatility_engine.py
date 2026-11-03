"""Tests for volatility_engine.py and run_volatility_backtest.py.

Reference values are computed independently here (plain loops / numpy),
not by calling the engine's own helpers.
"""
import math

import numpy as np
import pandas as pd
import pytest

import volatility_engine as ve
import run_volatility_backtest as bt


def _frame(close, vol=None, spread=0.01, start="2021-01-04", opens=None):
    close = np.asarray(close, float)
    n = len(close)
    vol = np.full(n, 1e6) if vol is None else np.asarray(vol, float)
    o = close if opens is None else np.asarray(opens, float)
    return pd.DataFrame({"trade_date": pd.bdate_range(start, periods=n), "open": o,
                         "high": np.maximum(o, close) * (1 + spread), "low": np.minimum(o, close) * (1 - spread),
                         "close": close, "volume": vol})


def _random_walk(n, seed=0, sigma=0.02):
    r = np.random.default_rng(seed).normal(0, sigma, n)
    return 100 * np.exp(np.cumsum(r))


def _squeeze_then_break(fail=False, n_pre=320, n_flat=60, rv=5.0):
    """Normal volatility, then a very tight base, then a high-volume breakout."""
    pre = _random_walk(n_pre, 3)
    base = pre[-1]
    rng = np.random.default_rng(9)
    flat = base * (1 + rng.normal(0, 0.002, n_flat))
    brk = [base * 1.07]
    post = [base * 1.08, base * 1.09, base * 1.10, base * 1.11] if not fail else [base * 0.995, base * 0.99, base * 0.99]
    close = np.concatenate([pre, flat, brk, post])
    vol = np.full(len(close), 1e6)
    vol[n_pre:n_pre + n_flat] = 4e5
    vol[n_pre + n_flat] = 1e6 * rv
    spread = np.full(len(close), 0.012)
    spread[n_pre:n_pre + n_flat] = 0.002
    df = _frame(close, vol)
    df["high"] = df["close"] * (1 + spread)
    df["low"] = df["close"] * (1 - spread)
    return df, n_pre + n_flat


# ---------------------------------------------------------------- indicators
def test_pct_rank_prior_matches_manual_and_excludes_current():
    x = np.random.default_rng(1).normal(size=300)
    p = ve.pct_rank_prior(x, 100)
    for t in (100, 150, 299):
        prior = x[t - 100:t]
        ref = ((prior < x[t]).sum() + 0.5 * (prior == x[t]).sum()) / 100 * 100
        assert p[t] == pytest.approx(ref)
    assert np.isnan(p[:100]).all()


def test_bbw_atr_hv_against_reference():
    df = _frame(_random_walk(400, 2))
    d = ve.compute_frame(df)
    c = df["close"].to_numpy()
    t = 350
    w = c[t - 19:t + 1]
    mid, sd = w.mean(), w.std(ddof=1)            # pandas rolling std is ddof=1
    assert d["BBW"].iloc[t] == pytest.approx((4 * sd) / mid, rel=1e-9)
    # Wilder ATR(20) by explicit recursion
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    a = tr[0]
    for i in range(1, t + 1):
        a = a + (tr[i] - a) / 20
    assert d["ATR20"].iloc[t] == pytest.approx(a, rel=1e-9)
    lr = np.log(c[t - 19:t + 1] / c[t - 20:t])
    assert d["HV20"].iloc[t] == pytest.approx(lr.std(ddof=1) * math.sqrt(252) * 100, rel=1e-9)
    assert d["DC20_hi"].iloc[t] == pytest.approx(h[t - 19:t + 1].max())


def test_cmf_series_matches_existing_scalar():
    import technical_analyzer as ta
    df = _frame(_random_walk(120, 4))
    d = ve.compute_frame(df)
    bars = [{"high": r.high, "low": r.low, "close": r.close, "volume": r.volume} for r in df.itertuples()]
    assert d["CMF20"].iloc[-1] == pytest.approx(ta.chaikin_money_flow(bars, 20), rel=1e-9)


def test_squeeze_detected_in_tight_base_not_in_normal_range():
    df, b = _squeeze_then_break()
    d = ve.compute_frame(df)
    assert d["SQZ"].iloc[b - 5]
    assert d["SQZ_run"].iloc[b - 5] >= 10
    assert d["BBW_p100"].iloc[b - 5] < 5
    assert not d["SQZ"].iloc[200:280].all()


def test_no_lookahead_features_and_stages_unchanged_by_future():
    df = _frame(_random_walk(500, 7))
    d1 = ve.compute_frame(df.iloc[:400])
    c1 = ve.classify_series(d1)
    mod = df.copy()
    mod.loc[400:, "close"] *= 3        # wildly different future
    mod.loc[400:, "high"] *= 3
    d2 = ve.compute_frame(mod)
    c2 = ve.classify_series(d2)
    cols = ["BBW_p100", "ATRP_p100", "HV20_p252", "SQZ", "BOX_hi", "RV20", "CMF20", "wk_trend", "wk_bbw_pct"]
    pd.testing.assert_frame_equal(d1[cols].iloc[:400], d2[cols].iloc[:400], check_dtype=False)
    assert (c1["stage"].to_numpy() == c2["stage"].to_numpy()[:400]).all()


def test_weekly_features_use_only_completed_weeks():
    df = _frame(_random_walk(300, 5))
    d = ve.compute_frame(df)
    mod = df.copy()
    last_fri = d["Date"][d["Date"].dt.day_of_week == 4].iloc[-1]
    i = int(np.flatnonzero(d["Date"] == last_fri)[0])
    mod.loc[i, "close"] *= 2      # change the bar that closes the latest week
    d2 = ve.compute_frame(mod)
    assert d["wk_trend"].iloc[i] == d2["wk_trend"].iloc[i] or (np.isnan(d["wk_trend"].iloc[i]) and np.isnan(d2["wk_trend"].iloc[i]))


# ---------------------------------------------------------------- stages
def test_breakout_attempt_then_confirmed():
    df, b = _squeeze_then_break()
    d = ve.compute_frame(df)
    cl = ve.classify_series(d)
    assert cl["stage"].iloc[b - 5] in (1, 2)
    assert cl["stage"].iloc[b] == 3 and cl["stage_dir"].iloc[b] == 1
    assert cl["stage"].iloc[b + 2] == 4
    assert cl["up_status"].iloc[b + 2] in ("confirmed", "retested")


def test_low_volume_breakout_is_not_confirmed():
    df, b = _squeeze_then_break(rv=0.5)
    cl = ve.classify_series(ve.compute_frame(df))
    assert cl["stage"].iloc[b + 3] == 3
    assert "low volume" in cl["stage_detail"].iloc[b + 3]


def test_failed_breakout_detected():
    df, b = _squeeze_then_break(fail=True)
    cl = ve.classify_series(ve.compute_frame(df))
    assert cl["stage"].iloc[b + 1] == 5
    assert cl["stage_detail"].iloc[b + 1] in ("Failed bullish breakout", "Bull trap")
    assert cl["up_status"].iloc[b + 1] == "failed"


def test_intraday_only_penetration_is_not_a_breakout():
    df, b = _squeeze_then_break()
    df = df.iloc[:b + 1].copy()
    base = df["close"].iloc[b - 1]
    df.loc[b, "close"] = base
    df.loc[b, "high"] = base * 1.05
    cl = ve.classify_series(ve.compute_frame(df))
    assert cl["stage"].iloc[b] != 3 or "attempt" not in cl["stage_detail"].iloc[b] or cl["stage_dir"].iloc[b] == 0
    assert cl["up_status"].iloc[b] == "attempt (intraday only)"


def test_corporate_action_jump_does_not_trigger_breakout():
    df, b = _squeeze_then_break()
    df.loc[b, ["close", "high", "low", "open"]] *= 1.5 / 1.07   # +50% overnight = adjustment, not breakout
    df.loc[b + 1:, ["close", "high", "low", "open"]] *= 1.5
    d = ve.compute_frame(df)
    cl = ve.classify_series(d)
    assert d["CA_flag"].iloc[b]
    assert cl["stage"].iloc[b] not in (3, 4)


# ---------------------------------------------------------------- scoring
def test_scores_bounded_and_bull_bear_independent():
    df, b = _squeeze_then_break()
    d = ve.compute_frame(df)
    cl = ve.classify_series(d)
    s = ve.scores_at(d, cl, b + 3)
    for k in ("compression_score", "bull_score", "bear_score", "bull_expansion_score", "bear_expansion_score"):
        assert 0 <= s[k] <= 100
    assert s["bull_score"] > s["bear_score"]
    assert s["bull_score"] + s["bear_score"] != pytest.approx(100)
    s0 = ve.scores_at(d, cl, b - 5)
    assert s0["compression_score"] > 60


def test_missing_data_earns_no_points():
    parts = {"bbw": 1.0, "squeeze": None, "atr": None, "hv": None, "donchian": None, "volume": None}
    score, cov = ve._weighted(parts, ve.DEFAULT_CONFIG["w_compression"])
    assert score == 25.0 and cov == 25


def test_short_history_returns_none():
    row, det = ve.analyze_symbol("X", _frame(_random_walk(40)))
    assert row is None


def test_classifications():
    assert ve.bbw_class(3) == "Extreme Compression"
    assert ve.bbw_class(15) == "Strong Compression"
    assert ve.bbw_class(None) == "Insufficient history"
    assert ve.liquidity_class(150e6) == "Highly Liquid"
    assert ve.liquidity_class(1e6) == "Illiquid"
    assert ve.mtf_alignment(70, 20, 1, 1) == "Strong Bullish Alignment"
    assert ve.mtf_alignment(70, 20, -1, -1) == "Conflicting Alignment"
    assert ve.mtf_alignment(10, 60, -1, 0) == "Strong Bearish Alignment"
    assert ve.setup_bucket(4, 1, 10, 80) == "s4_up"
    assert ve.setup_bucket(2, 0, 70, 20) == "s2_bull"


def test_alerts_only_on_change():
    r = {"symbol": "A", "stage": 2, "stage_detail": "Advanced squeeze", "stage_dir": 0, "bbw_pct100": 4,
         "compression_score": 80, "bull_score": 30, "bear_score": 30, "bull_expansion_score": 0,
         "bear_expansion_score": 0, "liquidity": "Liquid", "mtf_alignment": "Conflicting Alignment",
         "hist": {"available": False}}
    assert len(ve.build_alerts([r], None)) == 1
    assert ve.build_alerts([r], {"rows": [r]}) == []
    r2 = dict(r, stage=4, stage_detail="Confirmed breakout", stage_dir=1)
    assert ve.build_alerts([r2], {"rows": [r]})[0]["alert"] == "Confirmed breakout"


def test_insufficient_history_label():
    row = {"stage": 2, "stage_dir": 0, "bull_score": 50, "bear_score": 20}
    stats = {"buckets": {"s2_bull": {"n": 12, "p_up_10d": 80}}}
    h = ve.attach_stats(row, stats)
    assert not h["available"] and h["label"] == "INSUFFICIENT HISTORICAL EVIDENCE"
    stats["buckets"]["s2_bull"]["n"] = 45
    assert ve.attach_stats(row, stats)["available"]


def test_wilson_interval():
    lo, hi = ve.wilson(50, 100)
    assert lo == pytest.approx(40.4, abs=0.1) and hi == pytest.approx(59.6, abs=0.1)


def test_universe_scan_json_serialisable():
    import json
    data = {f"S{i}": _frame(_random_walk(400, i)).assign(trade_date=lambda x: x.trade_date.astype(str)).to_dict("records")
            for i in range(6)}
    res, det = ve.analyze_universe(data, {f"S{i}": "X" for i in range(6)})
    assert res["scanned"] == 6
    json.dumps(res)
    json.dumps(det)


# ---------------------------------------------------------------- backtest labelling
def test_forward_outcomes_and_target_before_stop():
    close = np.full(60, 100.0)
    close[31:] = 109.0
    df = _frame(close, spread=0.0)
    d = ve.compute_frame(df)
    f = bt.forward(d, 28, atrp=2.0)
    assert f["r5"] == pytest.approx(9.0)
    assert f["long_fix"][0] == "target" and f["long_fix"][1] == 3
    assert f["short_fix"][0] == "stop"


def test_forward_excludes_corporate_action_window():
    close = np.full(60, 100.0)
    close[35:] = 50.0
    d = ve.compute_frame(_frame(close, spread=0.0))
    assert bt.forward(d, 30, atrp=2.0) == {"excluded": True}


def test_stop_checked_before_target_on_same_bar():
    close = np.full(40, 100.0)
    df = _frame(close, spread=0.0)
    df.loc[11, "high"] = 120
    df.loc[11, "low"] = 90
    d = ve.compute_frame(df)
    assert bt.forward(d, 9, atrp=2.0)["long_fix"][0] == "stop"
