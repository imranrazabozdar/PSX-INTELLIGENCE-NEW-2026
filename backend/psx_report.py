#!/usr/bin/env python3
"""
psx_report.py — one-command technical snapshot for PSX tickers.

Produces a compact, paste-ready text block containing every indicator value
needed for a full multi-timeframe technical review. Replaces ~15 screenshots.

USAGE
    python psx_report.py SSGC
    python psx_report.py SSGC PACE ENGRO          # several at once
    python psx_report.py SSGC --years 3           # more history
    python psx_report.py SSGC --csv               # also dump raw OHLCV
    python psx_report.py --file mydata.csv        # offline: your own CSV
                                                  # (needs date,open,high,low,close,volume)

INSTALL
    pip install psxdata pandas numpy
    (fallback: pip install psx-data-reader)

NOTE: PSX end-of-day data is scraped from the public PSX site. It is EOD only —
no intraday. For 1h charts you still need your broker/TradingView.
"""

import argparse
import os
import sys
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------
# DATA LOADING
# ----------------------------------------------------------------------------

CACHE_DIR = os.environ.get("PSX_CACHE", os.path.join(
    os.path.expanduser("~"), ".psx_cache"))


def _cache_path(symbol):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{symbol.upper()}.csv")


def _read_cache(symbol):
    fp = _cache_path(symbol)
    if not os.path.exists(fp):
        return None
    try:
        df = pd.read_csv(fp, index_col=0, parse_dates=True)
        return df if len(df) > 30 else None
    except Exception:
        return None


def _write_cache(symbol, df):
    try:
        df.to_csv(_cache_path(symbol))
    except Exception:
        pass


def load_from_psx(symbol: str, years: int, refresh_days: int = 30) -> pd.DataFrame:
    """
    Incremental loader.

    First call for a symbol downloads the full history and caches it to disk.
    Every later call fetches only the last `refresh_days` and merges — so a
    daily refresh costs ~30 bars instead of ~750. Typically 20-40x faster.

    Set refresh_days=0 to force a full re-download.
    """
    cached = _read_cache(symbol) if refresh_days else None

    if cached is not None:
        last = cached.index[-1].date()
        need_from = last - timedelta(days=refresh_days)
        try:
            fresh = _fetch_psx(symbol, need_from, date.today())
            if fresh is not None and len(fresh):
                merged = pd.concat([cached[~cached.index.isin(fresh.index)], fresh])
                merged = merged[~merged.index.duplicated(keep="last")].sort_index()
                _write_cache(symbol, merged)
                return merged
        except Exception:
            pass                      # network hiccup -> serve the cache
        return cached

    df = _fetch_psx(symbol, date.today() - timedelta(days=365 * years + 30),
                    date.today())
    if df is not None and len(df):
        _write_cache(symbol, df)
    return df


def _fetch_psx(symbol: str, start, end) -> pd.DataFrame:
    try:
        import psxdata
        df = psxdata.stocks(symbol, start=str(start), end=str(end))
    except ImportError:
        try:
            from psx import stocks
            df = stocks(symbol, start=start, end=end)
        except ImportError:
            raise RuntimeError(
                "No PSX data source installed. Run: pip install psxdata")

    return normalise(df)


def load_from_csv(path: str) -> pd.DataFrame:
    return normalise(pd.read_csv(path))


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Accept whatever column casing / index the source gives us."""
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        datecol = next((c for c in df.columns if str(c).lower() in
                        ("date", "time", "datetime", "timestamp")), None)
        if datecol is None:
            sys.exit("No date column found.")
        df[datecol] = pd.to_datetime(df[datecol])
        df = df.set_index(datecol)

    df.columns = [str(c).strip().lower() for c in df.columns]
    need = ["open", "high", "low", "close", "volume"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        sys.exit(f"Missing columns: {missing}")

    df = df[need].apply(pd.to_numeric, errors="coerce").dropna()
    return df.sort_index()


def session_fraction():
    """How much of today's PSX session has elapsed (0..1). 0 if closed/pre-open."""
    from datetime import timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=5)))
    if now.weekday() > 4:
        return 1.0
    mins = now.hour * 60 + now.minute
    start, end = 9 * 60 + 15, 15 * 60 + 30
    if mins < start:
        return 0.0
    if mins >= end:
        return 1.0
    return (mins - start) / (end - start)


def handle_partial_bar(df, mode="drop"):
    """
    Today's bar is INCOMPLETE while the market is open. Comparing a
    3-hour bar against 20 full days makes volume look collapsed and can
    flip signals that reverse by the close.

      mode="drop"   -> remove today's bar entirely (safest, default)
      mode="prorate"-> scale today's volume up to a full-session estimate
      mode="raw"    -> leave it (what a naive scan does)

    Returns (dataframe, note).
    """
    if df is None or df.empty or mode == "raw":
        return df, None
    from datetime import timezone, timedelta
    today = datetime.now(timezone(timedelta(hours=5))).date()
    last_date = df.index[-1].date()
    frac = session_fraction()

    if last_date != today or frac >= 1.0:
        return df, None                      # bar is complete

    if mode == "prorate":
        d = df.copy()
        scale = 1.0 / max(frac, 0.08)
        d.iloc[-1, d.columns.get_loc("volume")] *= scale
        return d, (f"today's bar is partial ({frac*100:.0f}% of session) — "
                   f"volume scaled x{scale:.1f} for comparability")
    return df.iloc[:-1], (f"today's incomplete bar ({frac*100:.0f}% of session) "
                          f"excluded — ranking uses the last completed day")


def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    return df.resample("W-FRI").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()


def to_monthly(df: pd.DataFrame) -> pd.DataFrame:
    return df.resample("ME").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()


def resample_tf(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample intraday bars to any timeframe, e.g. '1h', '4h', '15min'."""
    return df.resample(rule).agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()


def load_intraday(path: str) -> pd.DataFrame:
    """
    Load an intraday CSV exported from TradingView / KTrade / your broker.
    Needs columns: date(or time/datetime), open, high, low, close, volume.
    Any bar size works — 1min, 5min, 15min, 1h.
    """
    return normalise(pd.read_csv(path))


def find_intraday(symbol: str, folder: str = ".") -> str | None:
    """
    Auto-discover an intraday file for a symbol. Drop a file named
    e.g.  GAL_1h.csv  (or GAL_intraday.csv) next to the script and it is
    picked up automatically — no flags needed.
    """
    import glob
    import os
    for pat in (f"{symbol}_1h.csv", f"{symbol}_1H.csv",
                f"{symbol}_intraday.csv", f"{symbol}_60.csv"):
        hits = glob.glob(os.path.join(folder, pat))
        if hits:
            return hits[0]
    return None


# ----------------------------------------------------------------------------
# INDICATORS  (pure pandas — no TA-Lib compile needed)
# ----------------------------------------------------------------------------

def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def macd(close, fast=12, slow=26, sig=9):
    line = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    signal = line.ewm(span=sig, adjust=False).mean()
    return line, signal, line - signal


def true_range(df):
    pc = df.close.shift()
    return pd.concat([df.high - df.low,
                      (df.high - pc).abs(),
                      (df.low - pc).abs()], axis=1).max(axis=1)


def atr(df, n=14):
    return true_range(df).ewm(alpha=1 / n, adjust=False).mean()


def adx_dmi(df, n=14):
    up, dn = df.high.diff(), -df.low.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = true_range(df).ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(plus, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / tr
    mdi = 100 * pd.Series(minus, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean(), pdi, mdi


def bollinger(close, n=20, k=2):
    ma = close.rolling(n).mean()
    sd = close.rolling(n).std(ddof=0)
    return ma + k * sd, ma, ma - k * sd


def ichimoku(df, t=9, k=26, b=52):
    mid = lambda s: (df.high.rolling(s).max() + df.low.rolling(s).min()) / 2
    tenkan, kijun = mid(t), mid(k)
    return tenkan, kijun, ((tenkan + kijun) / 2).shift(k), mid(b).shift(k)


def money_flow(df):
    rng = (df.high - df.low).replace(0, np.nan)
    mfm = ((df.close - df.low) - (df.high - df.close)) / rng
    mfv = (mfm * df.volume).fillna(0)
    ad = mfv.cumsum()
    cmf = mfv.rolling(20).sum() / df.volume.rolling(20).sum()
    chaikin = ad.ewm(span=3, adjust=False).mean() - ad.ewm(span=10, adjust=False).mean()
    return ad, cmf, chaikin


def moving_avgs(close):
    return {
        "SMA20": close.rolling(20).mean(),
        "SMA50": close.rolling(50).mean(),
        "SMA200": close.rolling(200).mean(),
        "EMA20": close.ewm(span=20, adjust=False).mean(),
        "EMA50": close.ewm(span=50, adjust=False).mean(),
    }


def rolling_vwap(df, n=20):
    """Rolling VWAP over n bars. NOT session VWAP (that needs intraday data)."""
    tp = (df.high + df.low + df.close) / 3
    return (tp * df.volume).rolling(n).sum() / df.volume.rolling(n).sum()


def supertrend(df, period=10, mult=3.0):
    """Returns (supertrend line, direction) where direction 1=up, -1=down."""
    hl2 = (df.high + df.low) / 2
    at = atr(df, period)
    upper = hl2 + mult * at
    lower = hl2 - mult * at
    st = pd.Series(index=df.index, dtype=float)
    dir_ = pd.Series(index=df.index, dtype=int)
    st.iloc[0] = upper.iloc[0]
    dir_.iloc[0] = -1
    for i in range(1, len(df)):
        if df.close.iloc[i] > st.iloc[i - 1]:
            dir_.iloc[i] = 1
        elif df.close.iloc[i] < st.iloc[i - 1]:
            dir_.iloc[i] = -1
        else:
            dir_.iloc[i] = dir_.iloc[i - 1]
        if dir_.iloc[i] == 1:
            st.iloc[i] = max(lower.iloc[i], st.iloc[i - 1]) if dir_.iloc[i - 1] == 1 else lower.iloc[i]
        else:
            st.iloc[i] = min(upper.iloc[i], st.iloc[i - 1]) if dir_.iloc[i - 1] == -1 else upper.iloc[i]
    return st, dir_


def donchian(df, n=20):
    return df.high.rolling(n).max(), df.low.rolling(n).min(), \
        (df.high.rolling(n).max() + df.low.rolling(n).min()) / 2


def keltner(df, n=20, mult=2.0):
    mid = df.close.ewm(span=n, adjust=False).mean()
    rng = atr(df, n)
    return mid + mult * rng, mid, mid - mult * rng


def mfi(df, n=14):
    """Money Flow Index — volume-weighted RSI."""
    tp = (df.high + df.low + df.close) / 3
    rmf = tp * df.volume
    pos = rmf.where(tp > tp.shift(), 0.0).rolling(n).sum()
    neg = rmf.where(tp < tp.shift(), 0.0).rolling(n).sum()
    return 100 - 100 / (1 + pos / neg.replace(0, np.nan))


# ----------------------------------------------------------------------------
# STRUCTURE, STATISTICS AND MARKET-RELATIVE MEASURES
# ----------------------------------------------------------------------------

def pivot_points(df, method="classic"):
    """Pivots from the LAST completed bar — real S/R levels, not band-derived."""
    h, l, c = df.high.iloc[-1], df.low.iloc[-1], df.close.iloc[-1]
    p = (h + l + c) / 3
    if method == "fibonacci":
        r = h - l
        return {"P": p, "R1": p + .382*r, "R2": p + .618*r, "R3": p + r,
                "S1": p - .382*r, "S2": p - .618*r, "S3": p - r}
    if method == "camarilla":
        r = h - l
        return {"P": p, "R1": c + r*1.1/12, "R2": c + r*1.1/6,
                "R3": c + r*1.1/4, "S1": c - r*1.1/12,
                "S2": c - r*1.1/6, "S3": c - r*1.1/4}
    return {"P": p, "R1": 2*p - l, "R2": p + (h - l), "R3": h + 2*(p - l),
            "S1": 2*p - h, "S2": p - (h - l), "S3": l - 2*(h - p)}


def fib_levels(df, lookback=120):
    """Fibonacci retracement across the dominant recent swing."""
    seg = df.tail(lookback)
    hi, lo = seg.high.max(), seg.low.min()
    hi_i, lo_i = seg.high.idxmax(), seg.low.idxmin()
    up = hi_i > lo_i                      # was the last leg up or down?
    rng = hi - lo
    if rng <= 0:
        return None
    if up:      # retracements measured down from the high
        lv = {f"{p:.3f}": hi - rng * p for p in (0.236, 0.382, 0.5, 0.618, 0.786)}
    else:       # retracements measured up from the low
        lv = {f"{p:.3f}": lo + rng * p for p in (0.236, 0.382, 0.5, 0.618, 0.786)}
    lv["swing_high"], lv["swing_low"] = hi, lo
    lv["_direction"] = "up-leg" if up else "down-leg"
    return lv


def regression_quality(close, n=60):
    """
    Trend slope and R-squared. R2 says how ORDERLY the trend is —
    high R2 = clean directional move, low R2 = choppy noise.
    """
    y = close.tail(n).values
    if len(y) < n // 2:
        return None
    x = np.arange(len(y))
    slope_, intercept = np.polyfit(x, y, 1)
    fit = slope_ * x + intercept
    ss_res = ((y - fit) ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum()
    r2 = 1 - ss_res / ss_tot if ss_tot else 0
    ann = slope_ / y.mean() * 252 * 100          # annualised % drift
    return {"slope_pct_ann": ann, "r2": r2}


def zscore(close, n=50):
    """How stretched is price vs its own mean, in standard deviations."""
    m = close.rolling(n).mean().iloc[-1]
    s = close.rolling(n).std(ddof=0).iloc[-1]
    return (close.iloc[-1] - m) / s if s else 0.0


def relative_strength(df, bench, n=63):
    """
    Stock vs benchmark. RS ratio rising = outperforming.
    Returns dict with relative return and the RS-line trend.
    """
    a = df.close.reindex(bench.index.union(df.index)).ffill()
    b = bench.reindex(a.index).ffill()
    rs = (a / b).dropna()
    if len(rs) < n + 5:
        return None
    stock_ret = (df.close.iloc[-1] / df.close.iloc[-n] - 1) * 100
    bench_ret = (b.iloc[-1] / b.iloc[-n] - 1) * 100
    rs_slope = "rising" if rs.iloc[-1] > rs.iloc[-n] else "falling"
    # beta and correlation on daily returns
    ra, rb = a.pct_change().dropna(), b.pct_change().dropna()
    j = ra.index.intersection(rb.index)[-252:]
    beta = corr = float("nan")
    if len(j) > 30:
        ra, rb = ra.loc[j], rb.loc[j]
        var = rb.var()
        beta = ra.cov(rb) / var if var else float("nan")
        corr = ra.corr(rb)
    return {"stock_ret": stock_ret, "bench_ret": bench_ret,
            "excess": stock_ret - bench_ret, "rs_trend": rs_slope,
            "beta": beta, "corr": corr}


def structure_block(df, label, bench=None):
    """Levels + statistics: pivots, fibs, regression quality, z-score, RS."""
    last = df.close.iloc[-1]
    L = [f"--- {label} STRUCTURE & STATS ---"]

    pv = pivot_points(df)
    L.append(f"Pivots  R2 {pv['R2']:.2f}  R1 {pv['R1']:.2f}  P {pv['P']:.2f}  "
             f"S1 {pv['S1']:.2f}  S2 {pv['S2']:.2f}")

    fb = fib_levels(df)
    if fb:
        L.append(f"Fib ({fb['_direction']}, swing {fb['swing_low']:.2f}"
                 f"-{fb['swing_high']:.2f}): "
                 + "  ".join(f"{k} {v:.2f}" for k, v in fb.items()
                             if not k.startswith(("swing", "_"))))
        # which fib is price sitting on?
        near = min(((k, v) for k, v in fb.items()
                    if not k.startswith(("swing", "_"))),
                   key=lambda kv: abs(kv[1] - last))
        if abs(near[1] - last) / last < 0.02:
            L.append(f"  -> price is AT the {near[0]} retracement ({near[1]:.2f})")

    rq = regression_quality(df.close)
    if rq:
        qual = ("clean trend" if rq["r2"] > 0.7 else
                "moderate" if rq["r2"] > 0.4 else "choppy/no trend")
        L.append(f"Regression(60): slope {rq['slope_pct_ann']:+.0f}%/yr  "
                 f"R2 {rq['r2']:.2f} -> {qual}")

    z = zscore(df.close)
    zt = ("stretched high" if z > 2 else "stretched low" if z < -2
          else "normal range")
    L.append(f"Z-score(50) {z:+.2f} -> {zt}")

    if bench is not None:
        rs = relative_strength(df, bench)
        if rs:
            verdict = ("OUTPERFORMING" if rs["excess"] > 3 else
                       "UNDERPERFORMING" if rs["excess"] < -3 else "in line with")
            L.append(f"Vs KSE-100 (3m): stock {rs['stock_ret']:+.1f}%  "
                     f"index {rs['bench_ret']:+.1f}%  excess {rs['excess']:+.1f}% "
                     f"-> {verdict}")
            L.append(f"  RS line {rs['rs_trend']}   beta {rs['beta']:.2f}   "
                     f"corr {rs['corr']:.2f}")
    return "\n".join(L)


def market_breadth(rows):
    """
    Breadth from a completed market scan (list of dicts from psx_scan.evaluate).
    Tells you whether the tide is with you — the context every single-stock
    read is missing.
    """
    if not rows:
        return "No scan data — run a market scan first."
    n = len(rows)
    adv = sum(1 for r in rows if r.get("1m%", 0) > 0)
    dec = n - adv
    above = sum(1 for r in rows if r.get("cloud") == "above")
    up_tr = sum(1 for r in rows if r.get("dTrend") == "UP")
    accum = sum(1 for r in rows if r.get("wVol", 0) >= 3)
    distr = sum(1 for r in rows if r.get("wVol", 0) <= -3)

    ad_ratio = adv / dec if dec else float("inf")
    pct_above = above / n * 100
    pct_up = up_tr / n * 100

    if pct_above > 60 and ad_ratio > 1.2:
        regime = "RISK-ON — broad participation, buy setups favoured"
    elif pct_above < 35 or ad_ratio < 0.6:
        regime = "RISK-OFF — weak breadth, be selective and size down"
    else:
        regime = "MIXED — stock-picking market, no broad tailwind"

    return "\n".join([
        "--- MARKET BREADTH (KSE) ---",
        f"Universe scanned: {n}",
        f"Advancing (1m) {adv} vs declining {dec}   A/D ratio {ad_ratio:.2f}",
        f"Above daily cloud: {above}/{n} ({pct_above:.0f}%)",
        f"Daily trend UP:    {up_tr}/{n} ({pct_up:.0f}%)",
        f"Weekly accumulation {accum} vs distribution {distr}",
        f">> REGIME: {regime}",
        "   A great setup in a risk-off tape still fails more often. "
        "Breadth sets your size, not your selection.",
    ])


def slope(series, n=5):
    """Direction over the last n bars: rising / falling / flat."""
    s = series.dropna()
    if len(s) < n + 1:
        return "n/a"
    chg = s.iloc[-1] - s.iloc[-n - 1]
    ref = abs(s.iloc[-n - 1]) if s.iloc[-n - 1] else 1
    pct = chg / ref
    return "rising" if pct > 0.02 else "falling" if pct < -0.02 else "flat"


# ----------------------------------------------------------------------------
# CANDLESTICK PATTERNS  (context-aware: pattern + location + volume)
# ----------------------------------------------------------------------------

def _candle_parts(df):
    o, h, l, c = df.open, df.high, df.low, df.close
    body = (c - o).abs()
    rng = (h - l).replace(0, np.nan)
    upper = h - np.maximum(c, o)
    lower = np.minimum(c, o) - l
    return o, h, l, c, body, rng, upper, lower


def detect_patterns(df, lookback=10):
    """
    Scan the last `lookback` bars for classic candlestick patterns.
    Returns list of dicts: {bars_ago, name, bias, strength}
    Noise controls: a Doji only counts on a bar with real range, and
    repeating multi-bar patterns report only their most recent instance.
    """
    o, h, l, c, body, rng, upper, lower = _candle_parts(df)
    avg_body = body.rolling(14).mean()
    avg_rng = rng.rolling(14).mean()
    found = []

    n = len(df)
    start = max(3, n - lookback)

    for i in range(start, n):
        ago = n - 1 - i
        O, H, L, C = o.iloc[i], h.iloc[i], l.iloc[i], c.iloc[i]
        B, R = body.iloc[i], rng.iloc[i]
        U, Lo = upper.iloc[i], lower.iloc[i]
        pO, pC, pB = o.iloc[i-1], c.iloc[i-1], body.iloc[i-1]
        ab, ar = avg_body.iloc[i], avg_rng.iloc[i]
        if not R or pd.isna(R) or pd.isna(ab) or ab == 0 or pd.isna(ar):
            continue

        bull = C > O
        small_body = B < 0.3 * R
        big_body = B > 1.3 * ab
        real_range = R > 0.7 * ar          # ignore dead, rangeless bars

        # --- single-bar ---
        if real_range and small_body and Lo > 2 * B and U < 0.3 * B + 1e-9:
            found.append(dict(bars_ago=ago, name="Hammer" if bull else "Hanging Man",
                              bias="bull" if bull else "bear", strength=2))
        elif real_range and small_body and U > 2 * B and Lo < 0.3 * B + 1e-9:
            found.append(dict(bars_ago=ago,
                              name="Shooting Star" if not bull else "Inverted Hammer",
                              bias="bear" if not bull else "bull", strength=2))
        elif real_range and B < 0.08 * R:
            if Lo > 0.6 * R:
                found.append(dict(bars_ago=ago, name="Dragonfly Doji", bias="bull", strength=2))
            elif U > 0.6 * R:
                found.append(dict(bars_ago=ago, name="Gravestone Doji", bias="bear", strength=2))
            elif R > 1.2 * ar:
                found.append(dict(bars_ago=ago, name="Long-legged Doji",
                                  bias="neutral", strength=1))
        elif big_body and B > 0.9 * R:
            found.append(dict(bars_ago=ago, name="Marubozu",
                              bias="bull" if bull else "bear", strength=2))

        # --- two-bar ---
        if bull and pC < pO and C >= pO and O <= pC and B > pB:
            found.append(dict(bars_ago=ago, name="Bullish Engulfing", bias="bull", strength=3))
        if not bull and pC > pO and C <= pO and O >= pC and B > pB:
            found.append(dict(bars_ago=ago, name="Bearish Engulfing", bias="bear", strength=3))
        if bull and pC < pO and O < pC and C > (pO + pC) / 2 and C < pO:
            found.append(dict(bars_ago=ago, name="Piercing Line", bias="bull", strength=2))
        if not bull and pC > pO and O > pC and C < (pO + pC) / 2 and C > pO:
            found.append(dict(bars_ago=ago, name="Dark Cloud Cover", bias="bear", strength=2))
        if pB > 1.3 * ab and B < 0.5 * pB and max(O, C) < max(pO, pC) and min(O, C) > min(pO, pC):
            found.append(dict(bars_ago=ago,
                              name="Bullish Harami" if pC < pO else "Bearish Harami",
                              bias="bull" if pC < pO else "bear", strength=2))

        # --- three-bar ---
        if i >= 2:
            p2O, p2C = o.iloc[i-2], c.iloc[i-2]
            p2B = body.iloc[i-2]
            if p2C < p2O and pB < 0.4 * p2B and bull and C > (p2O + p2C) / 2:
                found.append(dict(bars_ago=ago, name="Morning Star", bias="bull", strength=3))
            if p2C > p2O and pB < 0.4 * p2B and not bull and C < (p2O + p2C) / 2:
                found.append(dict(bars_ago=ago, name="Evening Star", bias="bear", strength=3))
            three_up = all(c.iloc[i-k] > o.iloc[i-k] for k in range(3))
            three_dn = all(c.iloc[i-k] < o.iloc[i-k] for k in range(3))
            rising = c.iloc[i] > c.iloc[i-1] > c.iloc[i-2]
            falling = c.iloc[i] < c.iloc[i-1] < c.iloc[i-2]
            strong = body.iloc[i-2:i+1].mean() > 0.8 * ab
            if three_up and rising and strong:
                found.append(dict(bars_ago=ago, name="Three White Soldiers",
                                  bias="bull", strength=3))
            if three_dn and falling and strong:
                found.append(dict(bars_ago=ago, name="Three Black Crows",
                                  bias="bear", strength=3))

    # --- dedupe: a repeating multi-bar pattern reports only its latest bar ---
    seen, cleaned = set(), []
    for p in sorted(found, key=lambda x: x["bars_ago"]):
        if p["name"] in ("Three White Soldiers", "Three Black Crows",
                         "Long-legged Doji"):
            if p["name"] in seen:
                continue
            seen.add(p["name"])
        cleaned.append(p)
    return cleaned


def pattern_report(df, label, lookback=10):
    """Patterns PLUS context — location vs structure, and volume confirmation."""
    pats = detect_patterns(df, lookback)
    if not pats:
        return f"--- {label} PATTERNS ---\nNo significant patterns in last {lookback} bars."

    v = df.volume
    v20 = v.rolling(20).mean()
    hi20 = df.high.rolling(20).max()
    lo20 = df.low.rolling(20).min()
    _, bm, _ = bollinger(df.close)
    n = len(df)

    lines = [f"--- {label} PATTERNS (last {lookback} bars) ---"]
    net = 0
    for p in sorted(pats, key=lambda x: x["bars_ago"]):
        i = n - 1 - p["bars_ago"]
        close_i = df.close.iloc[i]

        # location context
        near_lo = (close_i - lo20.iloc[i]) / (hi20.iloc[i] - lo20.iloc[i] + 1e-9) < 0.25
        near_hi = (close_i - lo20.iloc[i]) / (hi20.iloc[i] - lo20.iloc[i] + 1e-9) > 0.75
        loc = ("at RANGE LOW" if near_lo else "at RANGE HIGH" if near_hi
               else "mid-range")

        # volume context
        vr = v.iloc[i] / v20.iloc[i] if v20.iloc[i] and not pd.isna(v20.iloc[i]) else float("nan")
        if pd.isna(vr):
            vol_tag = "vol n/a"
            vr = 1.0
        else:
            vol_tag = (f"{vr:.1f}x vol" + (" CONFIRMED" if vr > 1.5 else
                                           " (weak vol)" if vr < 0.8 else ""))

        # a pattern only counts fully when location agrees with its bias
        weight = p["strength"]
        if (p["bias"] == "bull" and near_lo) or (p["bias"] == "bear" and near_hi):
            weight += 2
            quality = "HIGH"
        elif loc == "mid-range":
            weight -= 1
            quality = "low (no level)"
        else:
            quality = "counter-location"
        if vr > 1.5:
            weight += 1
        elif vr < 0.8:
            weight -= 1

        net += weight if p["bias"] == "bull" else -weight if p["bias"] == "bear" else 0
        when = "LATEST BAR" if p["bars_ago"] == 0 else f"{p['bars_ago']} bars ago"
        lines.append(f"  {when}: {p['name']} [{p['bias']}] · {loc} · {vol_tag} "
                     f"· quality {quality}")

    lines.append(f">> PATTERN BIAS: "
                 f"{'BULLISH' if net >= 3 else 'BEARISH' if net <= -3 else 'MIXED/WEAK'} "
                 f"(net {net:+d})")
    lines.append("   (patterns only matter at levels with volume — mid-range "
                 "signals are discounted)")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# VOLUME / ACCUMULATION INDICATORS
# ----------------------------------------------------------------------------

def obv(df):
    """On-Balance Volume — running tally: +vol on up closes, -vol on down."""
    sign = np.sign(df.close.diff().fillna(0))
    return (sign * df.volume).cumsum()


def vpt(df):
    """Volume-Price Trend — OBV weighted by the size of each move."""
    return (df.close.pct_change().fillna(0) * df.volume).cumsum()


def force_index(df, n=13):
    """Elder Force Index — direction * distance * volume, smoothed."""
    raw = df.close.diff().fillna(0) * df.volume
    return raw.ewm(span=n, adjust=False).mean()


def volume_diagnostics(df, label):
    """Turn the flow numbers into an accumulation / distribution verdict."""
    v = df.volume
    c = df.close
    n = min(20, len(df) - 1)

    # --- averages: is participation rising? ---
    v5 = v.rolling(5).mean().iloc[-1]
    v20 = v.rolling(20).mean().iloc[-1]
    v50 = v.rolling(min(50, len(df))).mean().iloc[-1]
    part = "rising" if v5 > v20 > v50 else "falling" if v5 < v20 < v50 else "mixed"

    # --- up-day vs down-day volume over last n bars ---
    recent = df.tail(n)
    up_vol = recent.loc[recent.close >= recent.close.shift(), "volume"].sum()
    dn_vol = recent.loc[recent.close < recent.close.shift(), "volume"].sum()
    total = up_vol + dn_vol
    up_share = up_vol / total * 100 if total else 50

    # --- running-tally indicators and their direction ---
    ob, vp, fi = obv(df), vpt(df), force_index(df)
    _, cmf, _ = money_flow(df)

    # --- spike detection: >2x avg, and did price close up or down? ---
    spike_mask = v.tail(n) > 2 * v20
    spikes = df.tail(n)[spike_mask.values]
    green = int((spikes.close >= spikes.open).sum())
    red = int((spikes.close < spikes.open).sum())

    # --- scorecard -> verdict ---
    score = 0
    score += 1 if slope(ob, 10) == "rising" else -1 if slope(ob, 10) == "falling" else 0
    score += 1 if slope(vp, 10) == "rising" else -1 if slope(vp, 10) == "falling" else 0
    score += 1 if fi.iloc[-1] > 0 else -1
    score += 1 if cmf.iloc[-1] > 0.05 else -1 if cmf.iloc[-1] < -0.05 else 0
    score += 1 if up_share > 55 else -1 if up_share < 45 else 0
    score += 1 if green > red else -1 if red > green else 0

    verdict = ("ACCUMULATION" if score >= 3 else
               "DISTRIBUTION" if score <= -3 else
               "NEUTRAL / no clear footprint")

    L = [f"--- {label} VOLUME ---",
         f"Participation: 5d {v5/1e6:.2f}M vs 20d {v20/1e6:.2f}M vs 50d "
         f"{v50/1e6:.2f}M -> {part}",
         f"Up-day vs down-day vol (last {n}): {up_share:.0f}% up / "
         f"{100-up_share:.0f}% down",
         f"OBV {ob.iloc[-1]/1e6:+.1f}M ({slope(ob, 10)})   "
         f"VPT {vp.iloc[-1]/1e6:+.2f}M ({slope(vp, 10)})",
         f"ForceIndex13 {fi.iloc[-1]/1e6:+.2f}M ({slope(fi)})   "
         f"CMF20 {cmf.iloc[-1]:+.3f}",
         f"Volume spikes (>2x, last {n}): {green} closed UP, {red} closed DOWN",
         f">> VOLUME VERDICT: {verdict}  (score {score:+d}/6)",
         ]
    return "\n".join(L)


# ----------------------------------------------------------------------------
# REPORT
# ----------------------------------------------------------------------------

def block(df: pd.DataFrame, label: str) -> str:
    c = df.close
    last = c.iloc[-1]
    a, p, m = adx_dmi(df)
    ml, ms, mh = macd(c)
    bu, bm, bl = bollinger(c)
    tk, kj, sa, sb = ichimoku(df)
    ad, cmf, chk = money_flow(df)
    r, at = rsi(c), atr(df)
    mas = moving_avgs(c)
    vw = rolling_vwap(df)
    st, stdir = supertrend(df)
    du, dl, dm = donchian(df)
    ku, km, kl = keltner(df)
    mf = mfi(df)

    v = df.volume
    vol_ratio = v.iloc[-1] / v.rolling(20).mean().iloc[-1]

    cloud_lo, cloud_hi = sorted([sa.iloc[-1], sb.iloc[-1]])
    pos = ("ABOVE cloud" if last > cloud_hi
           else "BELOW cloud" if last < cloud_lo else "IN cloud")

    # MA stack: is price above/below and are MAs stacked bull/bear?
    ma_pos = "above" if last > mas["SMA50"].iloc[-1] else "below"
    stacked = ("bull-stacked" if mas["SMA20"].iloc[-1] > mas["SMA50"].iloc[-1] > mas["SMA200"].iloc[-1]
               else "bear-stacked" if mas["SMA20"].iloc[-1] < mas["SMA50"].iloc[-1] < mas["SMA200"].iloc[-1]
               else "mixed")
    st_word = "UP" if stdir.iloc[-1] == 1 else "DOWN"
    # BB inside KC = squeeze
    squeeze = "SQUEEZE ON" if (bu.iloc[-1] < ku.iloc[-1] and bl.iloc[-1] > kl.iloc[-1]) else "no squeeze"

    L = [f"--- {label} ---",
         f"Close {last:.2f}   ATR14 {at.iloc[-1]:.2f} ({at.iloc[-1]/last*100:.1f}%)",
         f"MA: SMA20 {mas['SMA20'].iloc[-1]:.2f}  SMA50 {mas['SMA50'].iloc[-1]:.2f}  "
         f"SMA200 {mas['SMA200'].iloc[-1]:.2f}  EMA20 {mas['EMA20'].iloc[-1]:.2f}  "
         f"-> price {ma_pos} SMA50, {stacked}",
         f"RSI14 {r.iloc[-1]:.1f} ({slope(r)})   MFI14 {mf.iloc[-1]:.1f} ({slope(mf)})",
         f"MACD {ml.iloc[-1]:+.3f} / sig {ms.iloc[-1]:+.3f} / hist {mh.iloc[-1]:+.3f} ({slope(mh)})",
         f"ADX14 {a.iloc[-1]:.1f} ({slope(a)})  +DI {p.iloc[-1]:.1f}  -DI {m.iloc[-1]:.1f}",
         f"Supertrend(10,3) {st.iloc[-1]:.2f}  -> trend {st_word}",
         f"BB20,2 {bu.iloc[-1]:.2f} / {bm.iloc[-1]:.2f} / {bl.iloc[-1]:.2f}"
         f"  width {(bu.iloc[-1]-bl.iloc[-1])/bm.iloc[-1]*100:.1f}%"
         f"  %B {(last-bl.iloc[-1])/(bu.iloc[-1]-bl.iloc[-1])*100:.0f}",
         f"Keltner {ku.iloc[-1]:.2f} / {km.iloc[-1]:.2f} / {kl.iloc[-1]:.2f}  -> {squeeze}",
         f"Donchian(20) {du.iloc[-1]:.2f} / {dm.iloc[-1]:.2f} / {dl.iloc[-1]:.2f}",
         f"Ichimoku T {tk.iloc[-1]:.2f}  K {kj.iloc[-1]:.2f}"
         f"  cloud {cloud_lo:.2f}-{cloud_hi:.2f}  -> price {pos}",
         f"VWAP(20,rolling) {vw.iloc[-1]:.2f}  -> price {'above' if last > vw.iloc[-1] else 'below'}",
         f"A/D {ad.iloc[-1]/1e6:+.1f}M ({slope(ad, 10)})   CMF20 {cmf.iloc[-1]:+.3f} ({slope(cmf)})",
         f"ChaikinOsc {chk.iloc[-1]/1e6:+.2f}M ({slope(chk)})",
         f"Volume {v.iloc[-1]/1e6:.2f}M  = {vol_ratio:.2f}x 20-avg",
         f"Swing hi/lo (20) {df.high.rolling(20).max().iloc[-1]:.2f} / "
         f"{df.low.rolling(20).min().iloc[-1]:.2f}",
         ]
    return "\n".join(L)


def report(symbol: str, daily: pd.DataFrame, volume: bool = False,
           candles: bool = False, intraday: pd.DataFrame = None,
           monthly: bool = False, bench: pd.Series = None,
           structure: bool = False) -> str:
    wk = to_weekly(daily)
    hi52, lo52 = daily.high.tail(252).max(), daily.low.tail(252).min()
    last = daily.close.iloc[-1]

    head = (f"===== {symbol}  |  {daily.index[-1].date()}  |  {last:.2f} =====\n"
            f"52W {lo52:.2f} - {hi52:.2f}   "
            f"({(last/hi52-1)*100:+.0f}% from high, {(last/lo52-1)*100:+.0f}% from low)\n"
            f"Ret: 1w {pct(daily,5)}  1m {pct(daily,21)}  3m {pct(daily,63)}  "
            f"6m {pct(daily,126)}  1y {pct(daily,252)}")

    parts = [head]
    if monthly:
        mo = to_monthly(daily)
        if len(mo) >= 30:
            parts.append(block(mo, "MONTHLY"))
    parts += [block(wk, "WEEKLY"), block(daily, "DAILY")]

    if intraday is not None and len(intraday) > 60:
        h1 = resample_tf(intraday, "1h")
        if len(h1) > 60:
            parts.append(block(h1, "1-HOUR"))

    if structure:
        parts += [structure_block(daily, "DAILY", bench),
                  structure_block(wk, "WEEKLY")]

    if volume:
        parts += [volume_diagnostics(daily, "DAILY"),
                  volume_diagnostics(wk, "WEEKLY")]

    if candles:
        if monthly:
            mo = to_monthly(daily)
            if len(mo) >= 20:
                parts.append(pattern_report(mo, "MONTHLY", 4))
        parts += [pattern_report(wk, "WEEKLY", 6),
                  pattern_report(daily, "DAILY", 10)]
        if intraday is not None and len(intraday) > 60:
            h1 = resample_tf(intraday, "1h")
            if len(h1) > 40:
                parts.append(pattern_report(h1, "1-HOUR", 12))
            h4 = resample_tf(intraday, "4h")
            if len(h4) > 40:
                parts.append(pattern_report(h4, "4-HOUR", 8))
        parts.append(multi_tf_pattern_summary(daily, wk, intraday))

    return "\n\n".join(parts)


def multi_tf_pattern_summary(daily, weekly, intraday=None):
    """Do the timeframes agree on candle bias? Alignment is the real signal."""
    def bias(df, lb):
        txt = pattern_report(df, "x", lb)
        if "BULLISH" in txt:
            return 1, "bullish"
        if "BEARISH" in txt:
            return -1, "bearish"
        return 0, "mixed/none"

    rows, total = [], 0
    wv, wl = bias(weekly, 6); rows.append(("WEEKLY", wl)); total += wv * 3
    dv, dl = bias(daily, 10); rows.append(("DAILY", dl)); total += dv * 2
    if intraday is not None and len(intraday) > 60:
        h1 = resample_tf(intraday, "1h")
        if len(h1) > 40:
            hv, hl = bias(h1, 12); rows.append(("1-HOUR", hl)); total += hv * 1

    verdict = ("ALIGNED BULLISH" if total >= 4 else
               "ALIGNED BEARISH" if total <= -4 else
               "CONFLICTED — timeframes disagree" if abs(total) <= 2
               else ("leaning bullish" if total > 0 else "leaning bearish"))

    lines = ["--- MULTI-TIMEFRAME CANDLE ALIGNMENT ---"]
    lines += [f"  {tf:<8} {lab}" for tf, lab in rows]
    lines.append(f">> {verdict}  (weighted {total:+d})")
    lines.append("   Weekly counts most, 1-hour least. Alignment across "
                 "timeframes is the signal; a lone 1-hour pattern is noise.")
    return "\n".join(lines)


def pct(df, n):
    if len(df) <= n:
        return "n/a"
    return f"{(df.close.iloc[-1]/df.close.iloc[-1-n]-1)*100:+.1f}%"


# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*", help="PSX tickers, e.g. SSGC PACE")
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--csv", action="store_true", help="also save raw OHLCV")
    ap.add_argument("--volume", action="store_true",
                    help="add volume / accumulation diagnostics")
    ap.add_argument("--candles", action="store_true",
                    help="add candlestick pattern detection")
    ap.add_argument("--monthly", action="store_true",
                    help="also analyse the monthly timeframe")
    ap.add_argument("--structure", action="store_true",
                    help="add pivots, fibonacci, regression quality, z-score, RS")
    ap.add_argument("--all", action="store_true",
                    help="everything: volume + candles + structure + monthly")
    ap.add_argument("--intraday", default=None,
                    help="path to an intraday CSV (1h/15min) for 1H+4H analysis")
    ap.add_argument("--file", help="analyse a local CSV instead of downloading")
    args = ap.parse_args()

    jobs = []
    if args.file:
        jobs.append(("CSV", load_from_csv(args.file)))
    for s in args.symbols:
        jobs.append((s.upper(), load_from_psx(s.upper(), args.years)))

    if not jobs:
        sys.exit("Give a symbol, e.g.:  python psx_report.py SSGC")

    for sym, df in jobs:
        intra = None
        ipath = args.intraday or find_intraday(sym)
        if ipath:
            try:
                intra = load_intraday(ipath)
                print(f"[intraday: {ipath}]")
            except Exception as e:
                print(f"[intraday load failed: {e}]")
        bench = None
        if args.structure or args.all:
            try:
                import psxdata
                kb = psxdata.indices("KSE100")
                if hasattr(kb, "close"):
                    bench = kb.close
            except Exception:
                bench = None
        print(report(sym, df,
                     volume=args.volume or args.all,
                     candles=args.candles or args.all,
                     intraday=intra,
                     monthly=args.monthly or args.all,
                     bench=bench,
                     structure=args.structure or args.all))
        print()
        if args.csv:
            out = f"{sym}_ohlcv.csv"
            df.to_csv(out)
            print(f"[saved {out}]\n")


if __name__ == "__main__":
    main()
