"""
Extended Indicator Backtest with Volume Indicators
Tests 40+ indicators including volume signals on PSX daily OHLCV
Ranked by 1-day win rate (intraday trading focus)
"""

import os
import sqlite3
import time
import numpy as np
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "psx_v2.db")
MIN_HISTORY_DAYS = 60
FORWARD_HORIZONS = (1, 5, 10, 20)
MIN_SIGNAL_COUNT = 200

# Signal to indicator mapping
_SIGNAL_INDICATOR = {
    # Price-based
    "RSI_OVERSOLD": "RSI", "RSI_OVERBOUGHT": "RSI", "RSI_HEALTHY": "RSI",
    "MACD_CROSS_UP": "MACD", "MACD_CROSS_DOWN": "MACD", "MACD_HIST_POS": "MACD",
    "EMA20_CROSS_UP": "EMA", "EMA50_CROSS_UP": "EMA",
    "EMA20_CROSS_DN": "EMA", "EMA50_CROSS_DN": "EMA",
    "GOLDEN_CROSS": "EMA", "DEATH_CROSS": "EMA",
    "BB_SQUEEZE_BREAK": "Bollinger", "BB_OVERSOLD": "Bollinger", "BB_OVERBOUGHT": "Bollinger",
    "MOM_CROSS_POS": "Momentum", "MOM_CROSS_NEG": "Momentum",
    "ADX_TRENDING": "ADX", "ADX_WEAK": "ADX",
    "VOLUME_SPIKE": "Volume",

    # Volume indicators - NEW
    "MFI_OVERSOLD": "MFI", "MFI_OVERBOUGHT": "MFI",
    "OBV_CROSS_UP": "OBV", "OBV_CROSS_DN": "OBV", "OBV_DIVERGE_BULL": "OBV",
    "CMF_POS": "CMF", "CMF_NEG": "CMF",
    "VROC_POSITIVE": "VROC", "VROC_NEGATIVE": "VROC",
    "AD_RISING": "AD", "AD_FALLING": "AD",
    "PVT_CROSS_UP": "PVT", "PVT_CROSS_DN": "PVT",
    "VWMA_CROSS_UP": "VWMA", "VWMA_CROSS_DN": "VWMA",
    "FORCE_INDEX_BULL": "ForceIndex", "FORCE_INDEX_BEAR": "ForceIndex",
    "KLINGER_CROSS_UP": "Klinger", "KLINGER_CROSS_DN": "Klinger",
}

def _load_all_ohlc(db_path=DB_PATH) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            "SELECT symbol, trade_date, open, high, low, close, volume "
            "FROM daily_ohlc ORDER BY symbol, trade_date",
            conn,
        )
    finally:
        conn.close()
    return df

def _cross_above(a: pd.Series, b) -> pd.Series:
    b_prev = b.shift(1) if isinstance(b, pd.Series) else b
    return (a > b) & (a.shift(1) <= b_prev)

def _cross_below(a: pd.Series, b) -> pd.Series:
    b_prev = b.shift(1) if isinstance(b, pd.Series) else b
    return (a < b) & (a.shift(1) >= b_prev)

# Existing indicators
def _rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def _macd(close, fast=12, slow=26, signal=9):
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    line = ema_f - ema_s
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig

def _bollinger(close, period=20, mult=2):
    mid = close.rolling(period).mean()
    sd = close.rolling(period).std()
    return mid + mult * sd, mid, mid - mult * sd

def _obv(close, volume):
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume).cumsum()

def _true_adx(high, low, close, period=14):
    pc = close.shift(1)
    tr = pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    up = high.diff()
    dn = -low.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    alpha = 1.0 / period
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    s_pdm = pd.Series(pdm, index=high.index).ewm(alpha=alpha, adjust=False).mean()
    s_mdm = pd.Series(mdm, index=high.index).ewm(alpha=alpha, adjust=False).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = 100 * s_pdm / atr
        mdi = 100 * s_mdm / atr
        dx = 100 * (pdi - mdi).abs() / (pdi + mdi)
    return dx.ewm(alpha=alpha, adjust=False).mean()

def _cmf(high, low, close, volume, period=20):
    rng = (high - low).replace(0, np.nan)
    mfm = (((close - low) - (high - close)) / rng).fillna(0.0)
    mfv = mfm * volume
    return mfv.rolling(period).sum() / volume.rolling(period).sum().replace(0, np.nan)

# NEW: Volume indicators
def _mfi(high, low, close, volume, period=14):
    """Money Flow Index"""
    tp = (high + low + close) / 3
    rmf = tp * volume
    pmf = rmf.where(tp > tp.shift(1), 0)
    nmf = rmf.where(tp < tp.shift(1), 0)
    pmf_sum = pmf.rolling(period).sum()
    nmf_sum = nmf.rolling(period).sum()
    mr = pmf_sum / nmf_sum.replace(0, np.nan)
    return 100 - (100 / (1 + mr))

def _ad_line(high, low, close, volume):
    """Accumulation/Distribution Line"""
    clv = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    clv = clv.fillna(0)
    return (clv * volume).cumsum()

def _vroc(volume, period=14):
    """Volume Rate of Change"""
    return volume.pct_change(period) * 100

def _pvt(close, volume):
    """Price-Volume Trend"""
    roc = close.pct_change() * 100
    return (roc * volume).cumsum()

def _vwma(close, volume, period=20):
    """Volume Weighted Moving Average"""
    return (close * volume).rolling(period).sum() / volume.rolling(period).sum()

def _force_index(close, volume, period=13):
    """Force Index"""
    fi = (close.diff() * volume).ewm(span=period, adjust=False).mean()
    return fi

def _klinger_oscillator(high, low, close, volume, fast=34, slow=55):
    """Klinger Oscillator"""
    v = np.where(
        ((close > close.shift(1)).astype(int) * 2 - 1) * volume,
        volume,
        -volume
    )
    kvo = pd.Series(v, index=close.index).ewm(span=fast, adjust=False).mean() - \
          pd.Series(v, index=close.index).ewm(span=slow, adjust=False).mean()
    return kvo

def _compute_signals(g: pd.DataFrame) -> dict:
    """Compute all indicator signals for one symbol"""
    close, high, low, volume = g["close"], g["high"], g["low"], g["volume"]

    # Price indicators
    rsi = _rsi(close)
    macd_line, macd_sig, macd_hist = _macd(close)
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    bb_up, bb_mid, bb_lo = _bollinger(close)
    obv = _obv(close, volume)
    adx = _true_adx(high, low, close)
    cmf = _cmf(high, low, close, volume)
    mom20 = close.pct_change(20) * 100
    avg_vol20 = volume.rolling(20).mean()
    bw = (bb_up - bb_lo) / bb_mid
    bw_pct10 = bw.rolling(60).quantile(0.10)

    # NEW: Volume indicators
    mfi = _mfi(high, low, close, volume)
    ad_line = _ad_line(high, low, close, volume)
    vroc = _vroc(volume)
    pvt = _pvt(close, volume)
    vwma = _vwma(close, volume)
    fi = _force_index(close, volume)
    kvo = _klinger_oscillator(high, low, close, volume)

    return {
        # Existing price signals
        "RSI_OVERSOLD": _cross_below(rsi, 30),
        "RSI_OVERBOUGHT": _cross_above(rsi, 70),
        "RSI_HEALTHY": (rsi >= 45) & (rsi <= 65) & (rsi.shift(1) < 45),

        "MACD_CROSS_UP": _cross_above(macd_line, macd_sig),
        "MACD_CROSS_DOWN": _cross_below(macd_line, macd_sig),
        "MACD_HIST_POS": (macd_hist > 0) & (macd_hist.shift(1) <= 0),

        "EMA20_CROSS_UP": _cross_above(close, ema20),
        "EMA50_CROSS_UP": _cross_above(close, ema50),
        "EMA20_CROSS_DN": _cross_below(close, ema20),
        "EMA50_CROSS_DN": _cross_below(close, ema50),
        "GOLDEN_CROSS": _cross_above(ema20, ema50),
        "DEATH_CROSS": _cross_below(ema20, ema50),

        "VOLUME_SPIKE": volume >= 1.8 * avg_vol20,
        "OBV_DIVERGE_BULL": (obv > obv.shift(30)) & (close <= close.shift(30) * 1.01),

        "BB_SQUEEZE_BREAK": (bw.shift(1) <= bw_pct10.shift(1)) & (bw > bw.shift(1)),
        "BB_OVERSOLD": _cross_below(close, bb_lo),
        "BB_OVERBOUGHT": _cross_above(close, bb_up),

        "MOM_CROSS_POS": _cross_above(mom20, 0),
        "MOM_CROSS_NEG": _cross_below(mom20, 0),

        "ADX_TRENDING": _cross_above(adx, 25),
        "ADX_WEAK": _cross_below(adx, 20),

        "CMF_POS": _cross_above(cmf, 0),
        "CMF_NEG": _cross_below(cmf, 0),

        # NEW: Volume signals
        "MFI_OVERSOLD": _cross_below(mfi, 30),
        "MFI_OVERBOUGHT": _cross_above(mfi, 70),

        "OBV_CROSS_UP": _cross_above(obv, obv.shift(5)),
        "OBV_CROSS_DN": _cross_below(obv, obv.shift(5)),

        "VROC_POSITIVE": (vroc > 0) & (vroc.shift(1) <= 0),
        "VROC_NEGATIVE": (vroc < 0) & (vroc.shift(1) >= 0),

        "AD_RISING": (ad_line > ad_line.shift(5)) & (close <= close.shift(5)),
        "AD_FALLING": (ad_line < ad_line.shift(5)) & (close >= close.shift(5)),

        "PVT_CROSS_UP": _cross_above(pvt, pvt.ewm(span=20, adjust=False).mean()),
        "PVT_CROSS_DN": _cross_below(pvt, pvt.ewm(span=20, adjust=False).mean()),

        "VWMA_CROSS_UP": _cross_above(close, vwma),
        "VWMA_CROSS_DN": _cross_below(close, vwma),

        "FORCE_INDEX_BULL": (fi > 0) & (fi.shift(1) <= 0),
        "FORCE_INDEX_BEAR": (fi < 0) & (fi.shift(1) >= 0),

        "KLINGER_CROSS_UP": _cross_above(kvo, kvo.ewm(span=13, adjust=False).mean()),
        "KLINGER_CROSS_DN": _cross_below(kvo, kvo.ewm(span=13, adjust=False).mean()),
    }

def run_backtest(db_path=DB_PATH, min_history_days=MIN_HISTORY_DAYS):
    all_df = _load_all_ohlc(db_path)
    records = []
    baseline_records = []
    max_h = max(FORWARD_HORIZONS)

    for symbol, g in all_df.groupby("symbol", sort=False):
        g = g.sort_values("trade_date").reset_index(drop=True)
        n = len(g)
        if n < min_history_days + max_h + 1:
            continue

        close = g["close"].astype(float)
        fwd = {h: (close.shift(-h) - close) / close for h in FORWARD_HORIZONS}

        signals = _compute_signals(g)

        eligible = pd.Series(False, index=g.index)
        eligible.iloc[min_history_days:] = True
        eligible &= fwd[max_h].notna()

        dates = g["trade_date"]

        base_idx = g.index[eligible]
        for i in base_idx:
            baseline_records.append((
                symbol, dates.iat[i],
                fwd[1].iat[i], fwd[5].iat[i], fwd[10].iat[i], fwd[20].iat[i],
            ))

        for sig_name, sig_bool in signals.items():
            fired = (sig_bool & eligible).fillna(False)
            idx = g.index[fired]
            indicator = _SIGNAL_INDICATOR[sig_name]
            for i in idx:
                records.append({
                    "symbol": symbol, "date": dates.iat[i],
                    "indicator": indicator, "signal_type": sig_name,
                    "forward_1d": fwd[1].iat[i], "forward_5d": fwd[5].iat[i],
                    "forward_10d": fwd[10].iat[i], "forward_20d": fwd[20].iat[i],
                })

    signal_df = pd.DataFrame(records)
    baseline_df = pd.DataFrame(
        baseline_records,
        columns=["symbol", "date", "forward_1d", "forward_5d", "forward_10d", "forward_20d"],
    )
    return signal_df, baseline_df

def summarize(signal_df: pd.DataFrame, baseline_df: pd.DataFrame) -> pd.DataFrame:
    total_eligible_bars = len(baseline_df)
    rows = []
    for (indicator, signal_type), grp in signal_df.groupby(["indicator", "signal_type"]):
        n = len(grp)
        rows.append({
            "indicator": indicator, "signal_type": signal_type, "n_signals": n,
            "win_rate_1d": (grp["forward_1d"] > 0).mean() * 100,
            "win_rate_5d": (grp["forward_5d"] > 0).mean() * 100,
            "win_rate_10d": (grp["forward_10d"] > 0).mean() * 100,
            "win_rate_20d": (grp["forward_20d"] > 0).mean() * 100,
            "avg_return_10d": grp["forward_10d"].mean() * 100,
            "median_return_10d": grp["forward_10d"].median() * 100,
            "signal_frequency_pct": n / total_eligible_bars * 100 if total_eligible_bars else 0.0,
        })
    summary = pd.DataFrame(rows)

    baseline_row = {
        "indicator": "BASELINE", "signal_type": "ANY_RANDOM_BAR",
        "n_signals": total_eligible_bars,
        "win_rate_1d": (baseline_df["forward_1d"] > 0).mean() * 100,
        "win_rate_5d": (baseline_df["forward_5d"] > 0).mean() * 100,
        "win_rate_10d": (baseline_df["forward_10d"] > 0).mean() * 100,
        "win_rate_20d": (baseline_df["forward_20d"] > 0).mean() * 100,
        "avg_return_10d": baseline_df["forward_10d"].mean() * 100,
        "median_return_10d": baseline_df["forward_10d"].median() * 100,
        "signal_frequency_pct": 100.0,
    }
    summary = pd.concat([summary, pd.DataFrame([baseline_row])], ignore_index=True)

    # Sort by win_rate_1d (intraday focus)
    summary = summary.sort_values("win_rate_1d", ascending=False).reset_index(drop=True)
    return summary

if __name__ == "__main__":
    t0 = time.time()
    print("Loading daily_ohlc and scanning all symbols/signals (VOLUME EXTENDED) ...")
    signal_df, baseline_df = run_backtest()
    print(f"Scan complete in {time.time() - t0:.1f}s -- "
          f"{len(signal_df):,} signal firings, {len(baseline_df):,} eligible baseline bars.")

    summary = summarize(signal_df, baseline_df)

    out_dir = os.path.dirname(os.path.abspath(__file__))

    # Save detailed results
    signal_df.to_csv(os.path.join(out_dir, "indicator_backtest_volume_extended_results.csv"), index=False)

    # Save summary sorted by 1-day win rate
    summary.to_csv(os.path.join(out_dir, "indicator_backtest_volume_extended_1day.csv"), index=False)

    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 220)

    print("\n" + "="*120)
    print("TOP 10 PERFORMERS (1-day win rate)")
    print("="*120)
    print(summary.head(10)[["indicator", "signal_type", "n_signals", "win_rate_1d", "win_rate_5d", "win_rate_10d", "avg_return_10d"]].round(2).to_string(index=False))

    baseline_win_1d = summary.loc[summary["indicator"] == "BASELINE", "win_rate_1d"].iloc[0]

    non_baseline = summary[summary["indicator"] != "BASELINE"]
    above_baseline_1d = non_baseline[non_baseline["win_rate_1d"] > baseline_win_1d]

    print(f"\n" + "="*120)
    print(f"ABOVE BASELINE (win_rate_1d) -- {len(above_baseline_1d)} signal(s):")
    print("="*120)
    if len(above_baseline_1d):
        print(above_baseline_1d[["indicator", "signal_type", "win_rate_1d", "win_rate_5d", "n_signals"]].round(2).to_string(index=False))
    else:
        print("(none)")

    print(f"\n" + "="*120)
    print("BOTTOM 10 PERFORMERS (1-day win rate)")
    print("="*120)
    print(summary.tail(10)[["indicator", "signal_type", "n_signals", "win_rate_1d", "win_rate_5d", "win_rate_10d", "avg_return_10d"]].round(2).to_string(index=False))

    print(f"\n" + "="*120)
    print(f"Baseline win_rate_1d: {baseline_win_1d:.2f}%")
    print(f"Files saved:")
    print(f"  - indicator_backtest_volume_extended_1day.csv (ranked by 1-day win rate)")
    print(f"  - indicator_backtest_volume_extended_results.csv (detailed results)")
    print(f"Total elapsed: {time.time() - t0:.1f}s")
    print("="*120)
