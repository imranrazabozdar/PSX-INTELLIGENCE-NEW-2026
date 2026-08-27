"""relative_strength_engine.py — STEP 32: true multi-period relative strength
(1-week / 1-month / 3-month / 6-month / 12-month), not the single-session
proxy dss_engine.py originally shipped with. That proxy's own docstring said
"multi-session RS requires historical benchmark series" — this is that
series, using psx_live.index_history() (KSE-100, confirmed public with
limit>1) as the market benchmark and same-sector backfilled peers (from
daily_ohlc) as the sector benchmark where enough of them exist.

Date alignment: the stock's own OHLC calendar and the index's calendar don't
always share exactly the same trading days (holidays, feed gaps), so every
lookup finds the latest index/peer close ON OR BEFORE the stock's date for
that horizon, rather than assuming identical row positions line up.
"""

import bisect

PERIODS = {"1W": 5, "1M": 21, "3M": 63, "6M": 126, "12M": 252}


def _date_close_map(rows, date_key="trade_date"):
    m = {}
    for r in rows:
        d = r.get(date_key)
        if d:
            m[d] = r["close"]
    dates = sorted(m.keys())
    return dates, m


def _ts_to_date(ts_ms):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date().isoformat()


def _index_date_close_map(index_rows):
    m = {}
    for r in index_rows:
        ts = r.get("timestamp")
        c = r.get("close")
        if ts is not None and c is not None:
            m[_ts_to_date(ts)] = c
    dates = sorted(m.keys())
    return dates, m


def _closest_close_on_or_before(dates_sorted, date_to_close, target_date):
    idx = bisect.bisect_right(dates_sorted, target_date) - 1
    if idx < 0:
        return None
    return date_to_close[dates_sorted[idx]]


def _period_return(rows, n):
    """Stock's own % return over its own trailing n bars — its own calendar,
    no alignment needed."""
    if len(rows) <= n:
        return None
    then, now = rows[-1 - n]["close"], rows[-1]["close"]
    if not then:
        return None
    return round((now - then) / then * 100, 2), rows[-1 - n]["trade_date"]


def compute(stock_rows, index_rows, sector_peers=None):
    """stock_rows: this symbol's ascending true-OHLC. index_rows: KSE-100
    history from psx_live.index_history(). sector_peers: {symbol: rows} for
    other backfilled symbols in the same sector (excluding this one) — may be
    empty if too few peers have stored OHLC, in which case sector RS is
    reported as unavailable rather than guessed from one or two peers."""
    if not stock_rows or len(stock_rows) < 10:
        return {"status": "insufficient_history"}

    idx_dates, idx_map = (_index_date_close_map(index_rows) if index_rows else ([], {}))
    peer_series = []
    if sector_peers:
        for sym, prows in sector_peers.items():
            if prows and len(prows) >= 10:
                peer_series.append((sym, *_date_close_map(prows)))

    out = {}
    for label, n in PERIODS.items():
        stock_r = _period_return(stock_rows, n)
        if stock_r is None:
            out[label] = {"stock_pct": None, "index_pct": None, "sector_pct": None, "vs_index": None, "vs_sector": None}
            continue
        stock_pct, then_date = stock_r
        today_date = stock_rows[-1]["trade_date"]

        index_pct = None
        if idx_dates:
            then_c = _closest_close_on_or_before(idx_dates, idx_map, then_date)
            now_c = _closest_close_on_or_before(idx_dates, idx_map, today_date)
            if then_c and now_c:
                index_pct = round((now_c - then_c) / then_c * 100, 2)

        sector_pct = None
        if peer_series:
            peer_rets = []
            for sym, pdates, pmap in peer_series:
                then_c = _closest_close_on_or_before(pdates, pmap, then_date)
                now_c = _closest_close_on_or_before(pdates, pmap, today_date)
                if then_c and now_c:
                    peer_rets.append((now_c - then_c) / then_c * 100)
            if peer_rets:
                sector_pct = round(sum(peer_rets) / len(peer_rets), 2)

        out[label] = {
            "stock_pct": stock_pct, "index_pct": index_pct, "sector_pct": sector_pct,
            "vs_index": round(stock_pct - index_pct, 2) if index_pct is not None else None,
            "vs_sector": round(stock_pct - sector_pct, 2) if sector_pct is not None else None,
        }

    # Overall classification (STEP 32): weight longer horizons more, since a
    # single strong week is noise but six strong months is a real regime.
    weights = {"1W": 0.5, "1M": 1, "3M": 2, "6M": 3, "12M": 4}
    weighted, total_w = 0.0, 0.0
    for label, w in weights.items():
        v = out.get(label, {}).get("vs_index")
        if v is not None:
            weighted += v * w
            total_w += w
    avg_vs_index = round(weighted / total_w, 2) if total_w else None
    if avg_vs_index is None:
        classification = "Unavailable"
    elif avg_vs_index >= 15:
        classification = "Exceptional RS"
    elif avg_vs_index >= 7:
        classification = "Strong RS"
    elif avg_vs_index >= 2:
        classification = "Moderate RS"
    elif avg_vs_index >= -2:
        classification = "Neutral"
    elif avg_vs_index >= -7:
        classification = "Weak RS"
    else:
        classification = "Very Weak RS"

    return {"status": "ok", "periods": out, "weighted_avg_vs_index": avg_vs_index,
            "classification": classification, "sector_peers_used": len(peer_series),
            "note": "vs_index uses KSE-100 (confirmed-public index history). vs_sector uses the average "
                    f"of {len(peer_series)} same-sector symbol(s) with stored true-OHLC — sparse when few "
                    "peers are backfilled, reported as null per period rather than guessed from 1-2 names."}


def daily_series(stock_rows, index_rows, sector_peers=None, lookback=252):
    """STEP 60 Dashboard Page 8: rebased-to-100 daily series for stock vs
    KSE-100 vs sector-peer average, over the stock's own trailing `lookback`
    true-OHLC sessions — the actual plottable line chart, not just period
    return numbers. Sector peers are averaged only on dates where at least
    one peer has a close (sparse peers = a shorter honest sector line, never
    interpolated)."""
    if not stock_rows or len(stock_rows) < 10:
        return {"status": "insufficient_history"}
    window = stock_rows[-lookback:] if len(stock_rows) > lookback else stock_rows
    base_stock = window[0]["close"]
    if not base_stock:
        return {"status": "insufficient_history"}
    dates = [r["trade_date"] for r in window]
    stock_line = [round(r["close"] / base_stock * 100, 2) for r in window]

    idx_dates, idx_map = (_index_date_close_map(index_rows) if index_rows else ([], {}))
    index_line = [None] * len(dates)
    if idx_dates:
        base_idx = _closest_close_on_or_before(idx_dates, idx_map, dates[0])
        if base_idx:
            for i, d in enumerate(dates):
                c = _closest_close_on_or_before(idx_dates, idx_map, d)
                index_line[i] = round(c / base_idx * 100, 2) if c else None

    sector_line = [None] * len(dates)
    if sector_peers:
        peer_series = []
        for sym, prows in sector_peers.items():
            if prows and len(prows) >= 10:
                peer_series.append(_date_close_map(prows))
        if peer_series:
            for i, d in enumerate(dates):
                vals = []
                for pdates, pmap in peer_series:
                    base_p = _closest_close_on_or_before(pdates, pmap, dates[0])
                    c = _closest_close_on_or_before(pdates, pmap, d)
                    if base_p and c:
                        vals.append(c / base_p * 100)
                if vals:
                    sector_line[i] = round(sum(vals) / len(vals), 2)

    return {"status": "ok", "dates": dates, "stock": stock_line, "index": index_line, "sector": sector_line,
            "note": "Rebased to 100 at the start of the window — reads as % cumulative return from there, "
                    "not absolute price."}
