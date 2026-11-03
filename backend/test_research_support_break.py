"""Indicator validation for research_support_break.py: independent loop
references and no-look-ahead checks."""
import math

import numpy as np
import pandas as pd
import pytest

import research_support_break as rsb


def _d(n=400, seed=3):
    r = np.random.default_rng(seed).normal(0, 0.02, n)
    c = 100 * np.exp(np.cumsum(r))
    o = c * (1 + np.random.default_rng(seed + 1).normal(0, 0.004, n))
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.01, "low": np.minimum(o, c) * 0.99, "close": c,
                         "volume": np.random.default_rng(seed + 2).lognormal(13, 0.4, n)},
                        index=pd.bdate_range("2022-01-03", periods=n))


def _mkt(idx):
    return pd.Series(np.cumprod(1 + np.random.default_rng(9).normal(0, 0.01, len(idx))) * 100, index=idx)


def test_rsi14_matches_wilder_loop():
    d = _d()
    X = rsb.indicators(d, _mkt(d.index))
    c = d["close"].to_numpy()
    ag = al = None
    for i in range(1, len(c)):
        g, l = max(c[i] - c[i - 1], 0), max(c[i - 1] - c[i], 0)
        if ag is None:
            ag, al = g, l
        else:
            ag, al = ag + (g - ag) / 14, al + (l - al) / 14
    assert X["rsi14"].iloc[-1] == pytest.approx(100 - 100 / (1 + ag / al), rel=1e-9)


def test_atr_mfi_cmf_and_prior_low_reference():
    d = _d()
    X = rsb.indicators(d, _mkt(d.index))
    h, l, c, v = (d[k].to_numpy() for k in ("high", "low", "close", "volume"))
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    a = tr[0]
    for x in tr[1:]:
        a += (x - a) / 14
    assert X["atr14"].iloc[-1] == pytest.approx(a, rel=1e-9)
    t = len(c) - 1
    tp = (h + l + c) / 3
    pos = sum(tp[i] * v[i] for i in range(t - 13, t + 1) if tp[i] > tp[i - 1])
    neg = sum(tp[i] * v[i] for i in range(t - 13, t + 1) if tp[i] < tp[i - 1])
    assert X["mfi"].iloc[-1] == pytest.approx(100 - 100 / (1 + pos / neg), rel=1e-9)
    mfm = ((c - l) - (h - c)) / (h - l)
    assert X["cmf"].iloc[-1] == pytest.approx((mfm[-20:] * v[-20:]).sum() / v[-20:].sum(), rel=1e-9)
    assert X["p20low"].iloc[-1] == l[-21:-1].min()                    # current bar excluded


def test_no_lookahead_in_any_indicator_or_condition():
    d = _d()
    mk = _mkt(d.index)
    X1 = rsb.indicators(d.iloc[:300], mk.iloc[:300])
    d2 = d.copy()
    d2.iloc[300:, :4] *= 3
    d2.iloc[300:, 4] *= 10
    X2 = rsb.indicators(d2, mk)
    pd.testing.assert_frame_equal(X1, X2.iloc[:300], check_dtype=False)
    c1 = rsb.conditions(X1, d["close"].iloc[:300], d["low"].iloc[:300])
    c2 = rsb.conditions(X2, d2["close"], d2["low"])
    for k in c1:
        assert (c1[k].fillna(False).to_numpy() == c2[k].iloc[:300].fillna(False).to_numpy()).all(), k


def test_bh_and_cluster_effect():
    assert list(rsb.bh([0.001, 0.02, 0.5, 0.04], 0.10)) == [True, True, False, True]
    y = np.r_[np.full(50, -5.0), np.full(50, 1.0)] + np.random.default_rng(1).normal(0, 1, 100)
    x = np.r_[np.ones(50, bool), np.zeros(50, bool)]
    eff, se, t, p = rsb.ols_effect(y, x, np.arange(100))
    assert eff == pytest.approx(y[:50].mean() - y[50:].mean()) and p < 1e-6
