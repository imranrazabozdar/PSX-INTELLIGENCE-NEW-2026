"""obv_mfi_scanner_experimental.py — EXPERIMENTAL, not used in production.

Identical to obv_mfi_scanner.py except for ONE rule. The production
"sticky OBV" test is

    OBV_today >= OBV_day0 - 0.10 * |OBV_day0|

which depends on OBV's absolute LEVEL. OBV is a running sum, so its level
depends on where the loaded history starts (the live scan loads 260 bars,
the backtest loaded full history), i.e. the same day can pass in one and
fail in the other. This variant replaces it with an offset-invariant
version:

    OBV_today - OBV_day0 >= -0.10 * (volume of the 20 sessions ending on Day 0)

"OBV may give back at most 10% of the volume that built the Day-0 impulse".
Every other rule is imported unchanged from the production module.
Production keeps the original rule until this is explicitly approved.
"""
import pandas as pd

import obv_mfi_scanner as _prod

LOOKBACK_MIN, LOOKBACK_MAX, MIN_BARS_REQUIRED = _prod.LOOKBACK_MIN, _prod.LOOKBACK_MAX, _prod.MIN_BARS_REQUIRED
OBV_GIVEBACK_FRAC = 0.10


def obv_retention_ok(d: pd.DataFrame, i0: int, t: int) -> bool:
    vol20 = float(d["Volume"].iloc[max(0, i0 - 19):i0 + 1].sum())
    return bool(d["OBV"].iloc[t] - d["OBV"].iloc[i0] >= -OBV_GIVEBACK_FRAC * vol20)


def _retracement(d, i0):
    t, z = d.iloc[-1], d.iloc[i0]
    drop = (z["Close"] - t["Close"]) / z["Close"]
    avg_vol_after = d["Volume"].iloc[i0 + 1:].mean()
    ok = bool(0.04 <= drop <= 0.30 and t["Close"] > t["SMA20"] and avg_vol_after < 0.40 * z["Volume"]
              and t["MFI"] < 55 and obv_retention_ok(d, i0, len(d) - 1) and t["ATR"] < z["ATR"])
    return ok


def scan_obv_mfi_setup(df: pd.DataFrame) -> bool:
    d = _prod._normalise(df)
    if len(d) < MIN_BARS_REQUIRED:
        return False
    d = _prod.add_indicators(d)
    last = len(d) - 1
    for k in range(LOOKBACK_MIN, LOOKBACK_MAX + 1):
        i0 = last - k
        if _prod._is_day0(d, i0) and _retracement(d, i0):
            return True
    return False
