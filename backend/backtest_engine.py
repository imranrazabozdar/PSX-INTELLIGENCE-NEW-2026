"""backtest_engine.py — real, walk-forward pattern backtesting over stored
true-OHLC (daily_ohlc in psx_v2.db). This is what makes the Decision Support
System's "historical pattern statistics" (Bulkowski-style) and "quantitative
baseline validation" (Grimes-style) real instead of PENDING.

Methodology, matching the source framework's STEP 23-26 / 50-52:
  - Every pattern is detected walk-forward: at bar i, only rows[0..i] are used
    to detect it (no future data enters the detection), then forward returns
    are read from rows[i+1..i+horizon] — which is the correct way to backtest
    history, not look-ahead bias (look-ahead would be using future bars to
    decide whether a SIGNAL fired, which never happens here).
  - Every signal records its own SIGNAL DATE separately from nothing else —
    there is no separate "confirmation date" delay modeled (this engine scores
    the signal bar itself), so results describe "what happened after this bar
    printed", stated plainly rather than implying same-day fills are free.
  - Baselines (random entry = every bar, simple trend-following, simple RSI
    oversold, MA crossover) are computed the same way, over the same universe
    and the same horizons, so pattern performance can be honestly compared
    against "would a naive rule have done this anyway" (Grimes validation).
  - Samples under MIN_SAMPLE are still reported, never hidden, but flagged
    low_sample=True so nothing downstream treats 3 occurrences like 300.

This is intentionally NOT the full 75-step spec (no multi-regime splits, no
walk-forward train/validation/out-of-sample partitioning, no transaction
costs yet) — it is a real, honest, first version. Extending it is future work,
not a shortcut taken here.
"""

import candlestick_engine as _candles
import statistics
from datetime import datetime, timezone

import turso_db

HORIZONS = [1, 3, 5, 10, 20, 40, 60]
MIN_SAMPLE = 20


def _conn():
    return turso_db.get_connection()


_tables_ensured = False

def ensure_tables():
    # Used to send this CREATE TABLE IF NOT EXISTS on every call -- free when
    # _conn() meant a local sqlite3 no-op, but latest_run()/pattern_stats()/
    # baseline_stats() all call this first, and dss_engine.py calls those
    # once per detected pattern per symbol -- that's a real Turso network
    # round trip doubling the cost of every one of those lookups. Run once.
    global _tables_ensured
    if _tables_ensured:
        return
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS backtest_runs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at TEXT, universe_symbols INTEGER, universe_bars INTEGER);
        CREATE TABLE IF NOT EXISTS backtest_pattern_stats(
            run_id INTEGER, pattern TEXT, horizon INTEGER,
            n INTEGER, win_rate REAL, avg_return REAL, median_return REAL,
            stdev REAL, avg_win REAL, avg_loss REAL, mfe REAL, mae REAL,
            expectancy REAL, low_sample INTEGER,
            PRIMARY KEY(run_id, pattern, horizon));
        CREATE TABLE IF NOT EXISTS backtest_baseline_stats(
            run_id INTEGER, baseline TEXT, horizon INTEGER,
            n INTEGER, win_rate REAL, avg_return REAL, median_return REAL,
            stdev REAL, expectancy REAL, low_sample INTEGER,
            PRIMARY KEY(run_id, baseline, horizon));
        """)
        c.commit()
    _tables_ensured = True


# ---------------------------------------------------------------- helpers ---
def _avg(xs):
    return sum(xs) / len(xs) if xs else 0.0


def candle_patterns_at(a, i):
    """Full Nison set at bar i, via the shared candlestick_engine — identical
    detection logic to what app.py uses live, so backtested win-rates
    describe exactly the patterns the DSS tab shows as 'currently active'."""
    if i < 1:
        return []
    return _candles.detect_at(a, i)


def _trading_range_at(a, i, window=40):
    if i < window - 1:
        return None
    r = a[i - window + 1:i + 1]
    core = r[:-3] if len(r) > 3 else r
    if not core:
        return None
    return {"support": min(x["low"] for x in core), "resistance": max(x["high"] for x in core)}


def spring_at(a, i):
    if i < 45:
        return None
    tr = _trading_range_at(a, i)
    if not tr:
        return None
    x = a[i]
    if x["low"] < tr["support"] and x["close"] > tr["support"]:
        return "Spring"
    return None


def upthrust_at(a, i):
    if i < 45:
        return None
    tr = _trading_range_at(a, i)
    if not tr:
        return None
    x = a[i]
    if x["high"] > tr["resistance"] and x["close"] < tr["resistance"]:
        return "Upthrust"
    return None


def breakout_at(a, i, window=40):
    if i < window:
        return None
    tr = _trading_range_at(a, i - 1, window)
    if not tr:
        return None
    x = a[i]
    if x["close"] > tr["resistance"]:
        return "Resistance Breakout"
    if x["close"] < tr["support"]:
        return "Support Breakdown"
    return None


def rsi_series(a, period=14):
    closes = [x["close"] for x in a]
    out = [None] * len(a)
    gains, losses = [], []
    for i in range(1, len(a)):
        chg = closes[i] - closes[i - 1]
        gains.append(max(0.0, chg))
        losses.append(max(0.0, -chg))
        if i >= period:
            ag, al = _avg(gains[-period:]), _avg(losses[-period:])
            out[i] = 100.0 if al == 0 else 100 - (100 / (1 + ag / al))
    return out


def sma_series(a, period):
    closes = [x["close"] for x in a]
    out = [None] * len(a)
    for i in range(period - 1, len(a)):
        out[i] = _avg(closes[i - period + 1:i + 1])
    return out


def forward_return(a, i, horizon):
    if i + horizon >= len(a):
        return None
    entry = a[i]["close"]
    if not entry:
        return None
    return (a[i + horizon]["close"] - entry) / entry * 100


def mfe_mae(a, i, horizon):
    if i + horizon >= len(a):
        return None, None
    entry = a[i]["close"]
    window = a[i + 1:i + horizon + 1]
    if not window or not entry:
        return None, None
    mfe = max((x["high"] - entry) / entry * 100 for x in window)
    mae = min((x["low"] - entry) / entry * 100 for x in window)
    return mfe, mae


# ------------------------------------------------------------- detection ---
def scan_symbol_patterns(rows, symbol, combo_window=10):
    """Every occurrence of every detectable pattern in one symbol's history,
    each with its own forward returns at every horizon. Also detects a small
    set of combos (STEP 63/64 style: does Spring+Engulfing beat Engulfing
    alone?) by checking whether a Spring occurred within `combo_window` bars
    before a candlestick signal."""
    out = []
    last_spring_i = None
    for i in range(len(rows)):
        pats = []
        cps = candle_patterns_at(rows, i)
        pats.extend(cps)
        sp = spring_at(rows, i)
        if sp:
            pats.append(sp)
            last_spring_i = i
        ut = upthrust_at(rows, i)
        if ut:
            pats.append(ut)
        bo = breakout_at(rows, i)
        if bo:
            pats.append(bo)
        if last_spring_i is not None and 0 < i - last_spring_i <= combo_window:
            for cp in cps:
                pats.append(f"Spring + {cp}")
        for p in pats:
            rets = {h: forward_return(rows, i, h) for h in HORIZONS}
            # MFE/MAE must be measured over the SAME window as the horizon
            # they're reported against — this used to compute a single
            # max(HORIZONS)-window (60-bar) excursion and attach it to every
            # horizon's stats row, so a 1-day pattern's "worst adverse
            # excursion" was actually a 60-day figure, wildly overstating
            # both favorable and adverse excursion at short horizons.
            excursions = {h: mfe_mae(rows, i, h) for h in HORIZONS}
            mfe = {h: v[0] for h, v in excursions.items()}
            mae = {h: v[1] for h, v in excursions.items()}
            out.append({"symbol": symbol, "date": rows[i]["trade_date"], "pattern": p,
                        "returns": rets, "mfe": mfe, "mae": mae})
    return out


def scan_symbol_baselines(rows):
    """Naive baselines: every bar (random entry), price>SMA50 (trend
    following), RSI<30 (oversold), SMA9 crossing above SMA20 (MA crossover).
    Same forward-return machinery as patterns, so comparison is apples-to-apples."""
    rsis = rsi_series(rows, 14)
    sma9, sma20, sma50 = sma_series(rows, 9), sma_series(rows, 20), sma_series(rows, 50)
    fired = {"random_entry": [], "trend_following": [], "simple_rsi": [], "ma_crossover": []}
    for i in range(len(rows)):
        fired["random_entry"].append(i)
        if sma50[i] is not None and rows[i]["close"] > sma50[i]:
            fired["trend_following"].append(i)
        if rsis[i] is not None and rsis[i] < 30:
            fired["simple_rsi"].append(i)
        if i > 0 and None not in (sma9[i], sma20[i], sma9[i - 1], sma20[i - 1]):
            if sma9[i - 1] <= sma20[i - 1] and sma9[i] > sma20[i]:
                fired["ma_crossover"].append(i)
    out = {}
    for name, idxs in fired.items():
        out[name] = [{"returns": {h: forward_return(rows, i, h) for h in HORIZONS}} for i in idxs]
    return out


# -------------------------------------------------------------- stats ------
def _stats(rets):
    n = len(rets)
    if n == 0:
        return {"n": 0, "win_rate": None, "avg_return": None, "median_return": None,
                "stdev": None, "avg_win": None, "avg_loss": None, "expectancy": None,
                "low_sample": True}
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    win_rate = len(wins) / n * 100
    avg_win = statistics.mean(wins) if wins else 0.0
    avg_loss = statistics.mean(losses) if losses else 0.0
    expectancy = (len(wins) / n) * avg_win + (len(losses) / n) * avg_loss
    return {
        "n": n, "win_rate": round(win_rate, 1), "avg_return": round(statistics.mean(rets), 2),
        "median_return": round(statistics.median(rets), 2),
        "stdev": round(statistics.pstdev(rets), 2) if n > 1 else 0.0,
        "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2),
        "expectancy": round(expectancy, 2), "low_sample": n < MIN_SAMPLE,
    }


stats_from_returns = _stats  # public alias for reuse by walkforward_engine.py


def aggregate_patterns(all_signals, horizon):
    by_pattern = {}
    mfe_by = {}
    mae_by = {}
    for s in all_signals:
        r = s["returns"].get(horizon)
        if r is None:
            continue
        by_pattern.setdefault(s["pattern"], []).append(r)
        h_mfe = (s.get("mfe") or {}).get(horizon)
        h_mae = (s.get("mae") or {}).get(horizon)
        if h_mfe is not None:
            mfe_by.setdefault(s["pattern"], []).append(h_mfe)
        if h_mae is not None:
            mae_by.setdefault(s["pattern"], []).append(h_mae)
    out = {}
    for pat, rets in by_pattern.items():
        st = _stats(rets)
        st["mfe"] = round(statistics.mean(mfe_by[pat]), 2) if mfe_by.get(pat) else None
        st["mae"] = round(statistics.mean(mae_by[pat]), 2) if mae_by.get(pat) else None
        out[pat] = st
    return out


def aggregate_baselines(baseline_signals, horizon):
    out = {}
    for name, sigs in baseline_signals.items():
        rets = [s["returns"].get(horizon) for s in sigs if s["returns"].get(horizon) is not None]
        out[name] = _stats(rets)
    return out


# ---------------------------------------------------------------- run ------
def run_backtest(universe):
    """universe: {symbol: rows (ascending, from ohlc_rows)}. Persists results
    and returns the new run_id plus a compact summary."""
    ensure_tables()
    all_pattern_signals = []
    all_baseline_signals = {"random_entry": [], "trend_following": [], "simple_rsi": [], "ma_crossover": []}
    total_bars = 0
    for sym, rows in universe.items():
        if not rows or len(rows) < 60:
            continue
        total_bars += len(rows)
        all_pattern_signals.extend(scan_symbol_patterns(rows, sym))
        b = scan_symbol_baselines(rows)
        for name, sigs in b.items():
            all_baseline_signals[name].extend(sigs)

    with _conn() as c:
        cur = c.execute("INSERT INTO backtest_runs(run_at, universe_symbols, universe_bars) VALUES(?,?,?)",
                         (datetime.now(timezone.utc).isoformat(), len(universe), total_bars))
        run_id = cur.lastrowid
        pattern_names = set()
        for h in HORIZONS:
            pat_stats = aggregate_patterns(all_pattern_signals, h)
            for pat, st in pat_stats.items():
                pattern_names.add(pat)
                c.execute("""INSERT INTO backtest_pattern_stats
                    (run_id,pattern,horizon,n,win_rate,avg_return,median_return,stdev,avg_win,avg_loss,mfe,mae,expectancy,low_sample)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (run_id, pat, h, st["n"], st["win_rate"], st["avg_return"], st["median_return"],
                     st["stdev"], st["avg_win"], st["avg_loss"], st.get("mfe"), st.get("mae"),
                     st["expectancy"], int(st["low_sample"])))
            base_stats = aggregate_baselines(all_baseline_signals, h)
            for name, st in base_stats.items():
                c.execute("""INSERT INTO backtest_baseline_stats
                    (run_id,baseline,horizon,n,win_rate,avg_return,median_return,stdev,expectancy,low_sample)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (run_id, name, h, st["n"], st["win_rate"], st["avg_return"], st["median_return"],
                     st["stdev"], st["expectancy"], int(st["low_sample"])))
        c.commit()

    return {"run_id": run_id, "universe_symbols": len(universe), "universe_bars": total_bars,
            "patterns_found": sorted(pattern_names), "horizons": HORIZONS}


# ---------------------------------------------------------------- reads ----
def latest_run():
    ensure_tables()
    with _conn() as c:
        row = c.execute("SELECT * FROM backtest_runs ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def pattern_stats(pattern, horizon=20, run_id=None):
    ensure_tables()
    if run_id is None:
        r = latest_run()
        if not r:
            return None
        run_id = r["id"]
    with _conn() as c:
        row = c.execute("SELECT * FROM backtest_pattern_stats WHERE run_id=? AND pattern=? AND horizon=?",
                         (run_id, pattern, horizon)).fetchone()
    return dict(row) if row else None


def pattern_stats_multi(patterns, horizon=20, run_id=None):
    """Same per-pattern result as calling pattern_stats() once per pattern,
    but as ONE database round trip -- dss_engine.py's historical-stats and
    quant-validation components each loop over every currently-active
    pattern calling pattern_stats() individually, which used to be free with
    local sqlite3 and became a real Turso round trip per pattern (a stock
    with a dozen active patterns meant a dozen sequential network calls)."""
    ensure_tables()
    pats = list(dict.fromkeys(patterns))
    if not pats:
        return {}
    if run_id is None:
        r = latest_run()
        if not r:
            return {}
        run_id = r["id"]
    placeholders = ",".join("?" * len(pats))
    sql = (f"SELECT * FROM backtest_pattern_stats WHERE run_id=? AND horizon=? "
           f"AND pattern IN ({placeholders})")
    with _conn() as c:
        rows = c.execute(sql, (run_id, horizon, *pats)).fetchall()
    return {r["pattern"]: dict(r) for r in rows}


def baseline_stats(baseline, horizon=20, run_id=None):
    ensure_tables()
    if run_id is None:
        r = latest_run()
        if not r:
            return None
        run_id = r["id"]
    with _conn() as c:
        row = c.execute("SELECT * FROM backtest_baseline_stats WHERE run_id=? AND baseline=? AND horizon=?",
                         (run_id, baseline, horizon)).fetchone()
    return dict(row) if row else None


def all_pattern_stats(horizon=20, run_id=None):
    ensure_tables()
    if run_id is None:
        r = latest_run()
        if not r:
            return []
        run_id = r["id"]
    with _conn() as c:
        rows = c.execute("SELECT * FROM backtest_pattern_stats WHERE run_id=? AND horizon=? ORDER BY expectancy DESC",
                          (run_id, horizon)).fetchall()
    return [dict(x) for x in rows]


def all_baseline_stats(horizon=20, run_id=None):
    ensure_tables()
    if run_id is None:
        r = latest_run()
        if not r:
            return []
        run_id = r["id"]
    with _conn() as c:
        rows = c.execute("SELECT * FROM backtest_baseline_stats WHERE run_id=? AND horizon=?",
                          (run_id, horizon)).fetchall()
    return [dict(x) for x in rows]
