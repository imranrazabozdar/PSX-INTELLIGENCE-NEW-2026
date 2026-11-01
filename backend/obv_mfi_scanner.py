"""obv_mfi_scanner.py — "OBV+MFI Setup with ATR Contraction": an
institutional-accumulation footprint on daily bars.

Day 0 (the impulse), 3-45 trading days before today:
  - close > highest close of the 20 sessions before it
  - volume > 3x the 20-session volume SMA before it
  - OBV > highest OBV of the 20 sessions before it (new 20-day high)
  - MFI(14) > 80
Today (the retracement), against that Day 0:
  - close 4-30% below the Day 0 close, and still above today's SMA20
  - average volume of the sessions after Day 0 through today < 40% of Day 0 volume
  - MFI(14) < 55
  - OBV >= Day 0 OBV - 10% of |Day 0 OBV| ("sticky" OBV; works when OBV < 0)
  - ATR(14, Wilder) < ATR on Day 0

"Before it" means the bar is compared with the prior 20 sessions, never with
itself. The volume average excludes the impulse bar, which would otherwise make
the 40% test nearly impossible to pass. When several Day 0 candidates exist, the
most recent one that passes every check is reported.

A pattern signal, not a probability of profit: it has not been backtested on
PSX data.
"""
import numpy as np
import pandas as pd

LOOKBACK_MIN, LOOKBACK_MAX = 3, 45
MIN_BARS_REQUIRED = 20 + 14 + LOOKBACK_MAX + 1

_COLS = {"date": "Date", "trade_date": "Date", "open": "Open", "high": "High",
         "low": "Low", "close": "Close", "volume": "Volume"}


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Accepts Date/Open/... or this repo's trade_date/open/... columns."""
    df = df.rename(columns={c: _COLS.get(str(c).lower(), c) for c in df.columns})
    df = df[["Date", "Open", "High", "Low", "Close", "Volume"]].copy()
    df["Date"] = pd.to_datetime(df["Date"])
    for c in ("Open", "High", "Low", "Close", "Volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return (df.dropna().drop_duplicates("Date").sort_values("Date")
              .reset_index(drop=True))


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    out = df.copy()
    out["OBV"] = (np.sign(c.diff()).fillna(0) * v).cumsum()

    tp = (h + l + c) / 3
    raw = tp * v
    tp_diff = tp.diff()
    pos = raw.where(tp_diff > 0, 0.0).rolling(14).sum()
    neg = raw.where(tp_diff < 0, 0.0).rolling(14).sum()
    mfi = 100 - 100 / (1 + pos / neg.replace(0, np.nan))
    out["MFI"] = mfi.where(neg != 0, 100.0).where(pos.notna())

    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    out["ATR"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    out["SMA20"] = c.rolling(20).mean()
    out["PrevHighClose20"] = c.shift(1).rolling(20).max()
    out["PrevVolSMA20"] = v.shift(1).rolling(20).mean()
    out["PrevOBVHigh20"] = out["OBV"].shift(1).rolling(20).max()
    return out


def _is_day0(d: pd.DataFrame, i0: int) -> bool:
    r = d.iloc[i0]
    return bool(r["Close"] > r["PrevHighClose20"]
                and r["Volume"] > 3.0 * r["PrevVolSMA20"]
                and r["OBV"] > r["PrevOBVHigh20"]
                and r["MFI"] > 80)


def _retracement(d: pd.DataFrame, i0: int):
    t, z = d.iloc[-1], d.iloc[i0]
    drop = (z["Close"] - t["Close"]) / z["Close"]
    avg_vol_after = d["Volume"].iloc[i0 + 1:].mean()
    ok = bool(0.04 <= drop <= 0.30
              and t["Close"] > t["SMA20"]
              and avg_vol_after < 0.40 * z["Volume"]
              and t["MFI"] < 55
              and t["OBV"] >= z["OBV"] - 0.10 * abs(z["OBV"])
              and t["ATR"] < z["ATR"])
    if not ok:
        return None
    return {
        "day0_date": z["Date"].strftime("%Y-%m-%d"),
        "pattern_date": t["Date"].strftime("%Y-%m-%d"),
        "days_since_day0": int(len(d) - 1 - i0),
        "day0_close": round(float(z["Close"]), 2),
        "close": round(float(t["Close"]), 2),
        "sma20": round(float(t["SMA20"]), 2),
        "pullback_pct": round(float(drop) * 100, 1),
        "vol_drought_pct": round(float(avg_vol_after / z["Volume"]) * 100, 1),
        "mfi_day0": round(float(z["MFI"]), 1),
        "mfi_now": round(float(t["MFI"]), 1),
        "obv_retention_pct": (round(float(t["OBV"] / z["OBV"]) * 100, 1) if z["OBV"] else None),
        "atr_ratio": round(float(t["ATR"] / z["ATR"]), 2),
    }


def scan_obv_mfi_setup(df: pd.DataFrame, return_details: bool = False):
    """True when today completes the sequence against any Day 0 in the last
    3-45 sessions (newest first). return_details=True gives (bool, dict|None)."""
    d = _normalise(df)
    if len(d) < MIN_BARS_REQUIRED:
        return (False, None) if return_details else False
    d = add_indicators(d)
    last = len(d) - 1
    for k in range(LOOKBACK_MIN, LOOKBACK_MAX + 1):
        i0 = last - k
        if _is_day0(d, i0):
            details = _retracement(d, i0)
            if details:
                return (True, details) if return_details else True
    return (False, None) if return_details else False
