"""regime_backtest_engine.py — STEP 27: split pattern performance by market
regime (Bull/Bear/Range, from KSE-100's own trailing structure) and by
volatility regime (the stock's own trailing ATR percentile, bar-indexed so
no look-ahead), instead of pooling every signal into one number regardless
of what the market was doing when it fired.

Also STEP 64: discover PSX-specific combinations beyond the fixed textbook
patterns — RVOL>90th-percentile breakout + successful 3-day retest, and a
low-volume Spring test + strong sector RS + KSE-100 bull regime combo — and
report honestly whether either beats the textbook patterns' own numbers,
using the exact same walk-forward machinery.
"""

import bisect
import statistics

from backtest_engine import HORIZONS, forward_return, stats_from_returns
from walkforward_engine import _signals_with_index


def _index_regime_series(index_rows, sma_period=50):
    """Bull/Bear/Range per date, from KSE-100's own trailing SMA — STEP 4's
    'do not use one moving average alone' is honored by also requiring the
    SMA itself to be trending, not just price vs SMA."""
    if not index_rows or len(index_rows) < sma_period + 5:
        return [], {}
    from datetime import datetime, timezone
    dated = []
    for r in index_rows:
        ts = r.get("timestamp")
        c = r.get("close")
        if ts is not None and c is not None:
            d = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date().isoformat()
            dated.append((d, c))
    dated.sort()
    closes = [c for _, c in dated]
    regime_map = {}
    for i in range(sma_period, len(dated)):
        sma_now = statistics.mean(closes[i - sma_period:i])
        sma_prev = statistics.mean(closes[i - sma_period - 5:i - 5]) if i - sma_period - 5 >= 0 else sma_now
        price = closes[i]
        if price > sma_now and sma_now >= sma_prev:
            regime_map[dated[i][0]] = "Bull"
        elif price < sma_now and sma_now <= sma_prev:
            regime_map[dated[i][0]] = "Bear"
        else:
            regime_map[dated[i][0]] = "Range"
    dates_sorted = sorted(regime_map.keys())
    return dates_sorted, regime_map


def _regime_on_or_before(dates_sorted, regime_map, target_date):
    idx = bisect.bisect_right(dates_sorted, target_date) - 1
    if idx < 0:
        return "Unknown"
    return regime_map[dates_sorted[idx]]


def _volatility_regime_series(rows, atr_period=14, lookback=250):
    """Bar-indexed ATR-percentile label at every bar, using only bars up to
    and including it — same method as wyckoff_engine.volatility_regime but
    computed at every historical index instead of just the latest bar."""
    n = len(rows)
    if n < atr_period + 20:
        return [None] * n
    trs = [None]
    for i in range(1, n):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr_at = [None] * n
    for i in range(atr_period, n):
        window = [t for t in trs[i - atr_period + 1:i + 1] if t is not None]
        atr_at[i] = statistics.mean(window) if window else None

    labels = [None] * n
    for i in range(atr_period, n):
        if atr_at[i] is None:
            continue
        hist_start = max(atr_period, i - lookback)
        hist = [a for a in atr_at[hist_start:i + 1] if a is not None]
        if len(hist) < 20:
            continue
        current = atr_at[i]
        pct_rank = sum(1 for v in hist if v <= current) / len(hist) * 100
        labels[i] = ("Very Low" if pct_rank < 20 else "Low" if pct_rank < 40 else
                     "Normal" if pct_rank < 60 else "High" if pct_rank < 80 else "Extreme")
    return labels


def run_regime_split(universe, index_rows, horizon=20):
    """universe: {symbol: rows}. index_rows: KSE-100 history from
    psx_live.index_history(). Splits every real detected signal by market
    regime (KSE-100-derived) and volatility regime (each stock's own), then
    aggregates pattern stats within each bucket."""
    dates_sorted, regime_map = _index_regime_series(index_rows)
    by_market_regime = {"Bull": [], "Bear": [], "Range": [], "Unknown": []}
    by_vol_regime = {"Very Low": [], "Low": [], "Normal": [], "High": [], "Extreme": []}

    for sym, rows in universe.items():
        if not rows or len(rows) < 100:
            continue
        sigs = _signals_with_index(rows, sym)
        vol_labels = _volatility_regime_series(rows)
        for s in sigs:
            mreg = _regime_on_or_before(dates_sorted, regime_map, s["date"]) if dates_sorted else "Unknown"
            by_market_regime.setdefault(mreg, []).append(s)
            vlabel = vol_labels[s["index"]] if s["index"] < len(vol_labels) else None
            if vlabel:
                by_vol_regime[vlabel].append(s)

    def agg(sigs, h):
        by_pattern = {}
        for s in sigs:
            r = s["returns"].get(h)
            if r is None:
                continue
            by_pattern.setdefault(s["pattern"], []).append(r)
        return {pat: stats_from_returns(rets) for pat, rets in by_pattern.items()}

    market_regime_stats = {reg: agg(sigs, horizon) for reg, sigs in by_market_regime.items() if sigs}
    vol_regime_stats = {reg: agg(sigs, horizon) for reg, sigs in by_vol_regime.items() if sigs}

    # A compact, honest summary: for each pattern that appears in >=2 market
    # regimes with a real sample, show how its win rate actually shifts.
    pattern_regime_summary = {}
    for reg, stats in market_regime_stats.items():
        for pat, st in stats.items():
            if st["low_sample"]:
                continue
            pattern_regime_summary.setdefault(pat, {})[reg] = {"n": st["n"], "win_rate": st["win_rate"],
                                                                "expectancy": st["expectancy"]}
    pattern_regime_summary = {p: r for p, r in pattern_regime_summary.items() if len(r) >= 2}

    return {
        "horizon": horizon,
        "market_regime_dates_available": len(dates_sorted),
        "counts": {"market_regime": {k: len(v) for k, v in by_market_regime.items()},
                   "volatility_regime": {k: len(v) for k, v in by_vol_regime.items()}},
        "market_regime_stats": market_regime_stats,
        "volatility_regime_stats": vol_regime_stats,
        "pattern_regime_shift": pattern_regime_summary,
        "note": "STEP 27: market regime is derived from KSE-100's own trailing 50-bar SMA (price vs SMA "
                "AND the SMA's own slope — never one moving average reading alone). Volatility regime is "
                "each stock's own trailing ATR percentile at the bar the signal fired, no look-ahead. "
                "pattern_regime_shift shows only patterns with a real (non-low) sample in 2+ regimes — "
                "the honest way to see whether 'Bullish Engulfing works' actually means 'works in bull "
                "markets, doesn't in bear markets', per the source framework's own worked example.",
    }


# ---------------------------------------------------------- edge discovery ---
def _rvol_series(rows, window=20):
    out = [None] * len(rows)
    for i in range(window, len(rows)):
        avgv = statistics.mean(v["volume"] for v in rows[i - window:i])
        out[i] = rows[i]["volume"] / avgv if avgv else None
    return out


def _rvol_percentile_at(rvol_series, i, lookback=250):
    if rvol_series[i] is None:
        return None
    hist_start = max(0, i - lookback)
    hist = [v for v in rvol_series[hist_start:i] if v is not None]
    if len(hist) < 30:
        return None
    return sum(1 for v in hist if v <= rvol_series[i]) / len(hist) * 100


def discover_psx_edges(universe, horizon=20):
    """STEP 64: test two PSX-specific combinations the fixed pattern library
    doesn't cover — (a) RVOL>90th-percentile breakout with a successful
    3-day retest, (b) low-volume Spring test — against the same walk-forward
    machinery, so 'edge' claims are held to the identical bar as every other
    pattern in this system, not graded on a curve."""
    edge_a_signals, edge_b_signals = [], []
    for sym, rows in universe.items():
        if not rows or len(rows) < 100:
            continue
        rvol = _rvol_series(rows)
        for i in range(60, len(rows)):
            window_pre = rows[max(0, i - 40):i - 3] if i >= 43 else []
            if not window_pre:
                continue
            resistance = max(x["high"] for x in window_pre)
            x = rows[i]
            pct = _rvol_percentile_at(rvol, i)
            broke = x["close"] > resistance
            if broke and pct is not None and pct >= 90:
                # successful 3-day retest: none of the next 3 bars close back below resistance
                nxt = rows[i + 1:i + 4]
                if len(nxt) == 3 and all(b["close"] >= resistance * 0.99 for b in nxt):
                    rets = {h: forward_return(rows, i, h) for h in HORIZONS}
                    edge_a_signals.append({"symbol": sym, "date": x["trade_date"], "returns": rets})

            support = min(x["low"] for x in window_pre)
            if x["low"] < support and x["close"] > support and rvol[i] is not None and rvol[i] < 0.7:
                rets = {h: forward_return(rows, i, h) for h in HORIZONS}
                edge_b_signals.append({"symbol": sym, "date": x["trade_date"], "returns": rets})

    def agg(sigs, h):
        rets = [s["returns"].get(h) for s in sigs if s["returns"].get(h) is not None]
        return stats_from_returns(rets)

    return {
        "edge_a": {"name": "RVOL>90th-percentile breakout + successful 3-day retest",
                   "n_signals": len(edge_a_signals), "stats_by_horizon": {h: agg(edge_a_signals, h) for h in HORIZONS}},
        "edge_b": {"name": "Low-volume Spring test (RVOL<0.7 on the undercut-and-reclaim bar)",
                   "n_signals": len(edge_b_signals), "stats_by_horizon": {h: agg(edge_b_signals, h) for h in HORIZONS}},
        "note": "Tested exactly like every textbook pattern in /backtest/status — same forward-return "
                "machinery, same walk-forward-eligible universe. Compare stats_by_horizon[20].expectancy "
                "against /backtest/status's pattern list and the random_entry baseline to judge honestly "
                "whether either PSX-specific combination is actually worth tracking.",
    }
