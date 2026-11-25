"""Chart Patterns loader: latest 250 sessions per symbol, and the window is enough for the detector."""
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pattern_scanner.bulkowski_detector import _indicators, _prepare, scan_symbol  # noqa: E402
from pattern_scanner.recent_bars import RECENT_SESSIONS, fetch_recent_bars, recent_bars_sql  # noqa: E402


def _synthetic_series(n=1300, seed=0):
    """1,300 daily bars with a Cup-with-Handle ending near the last bars and a volume breakout."""
    rng = np.random.default_rng(seed)
    price = [100.0]
    for _ in range(n - 170):
        price.append(price[-1] * (1 + rng.normal(0.0004, 0.01)))
    base = price[-1]
    cup = [base * (1 - 0.25 * np.sin(np.pi * (i + 1) / 60 / 2)) for i in range(60)]
    cup += [base * (0.75 + 0.25 * np.sin(np.pi * (i + 1) / 60 / 2)) for i in range(60)]
    handle = [base * (1 - 0.03 * (i + 1) / 8) for i in range(8)]
    close = np.array(price + cup + handle, dtype=float)
    close = np.append(close, close[-1] * 1.06)
    m = len(close)
    high = close * (1 + np.abs(rng.normal(0, 0.005, m)))
    low = close * (1 - np.abs(rng.normal(0, 0.005, m)))
    op = np.concatenate(([close[0]], close[:-1]))
    volume = rng.uniform(900_000, 1_100_000, m) * 10
    volume[-9:-1] = 5_000_000
    volume[-1] = 40_000_000
    dates = pd.bdate_range(end="2026-11-20", periods=m).strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "open": op, "high": high, "low": low,
                         "close": close, "volume": volume})


def _db(frames):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE daily_ohlc (symbol TEXT, trade_date TEXT, open REAL, high REAL, "
                 "low REAL, close REAL, volume REAL)")
    for sym, df in frames.items():
        conn.executemany(
            "INSERT INTO daily_ohlc VALUES (?,?,?,?,?,?,?)",
            [(sym, r.date, r.open, r.high, r.low, r.close, r.volume) for r in df.itertuples()])
    return conn


def test_loader_returns_latest_250_ascending_per_symbol():
    long_df = _synthetic_series(1300, seed=0)
    short_df = _synthetic_series(100, seed=1)
    conn = _db({"AAA": long_df, "BBB": short_df})
    got = fetch_recent_bars(conn, ["AAA", "BBB"], chunk=1)   # chunk=1 exercises multiple queries
    assert len(got["AAA"]) == RECENT_SESSIONS == 250
    assert len(got["BBB"]) == len(short_df) < RECENT_SESSIONS   # short history is returned whole
    dates = [r["trade_date"] for r in got["AAA"]]
    assert dates == sorted(dates)                            # ascending
    assert dates[-1] == long_df["date"].iloc[-1]             # latest date matches
    assert dates[0] == long_df["date"].iloc[-RECENT_SESSIONS]


def test_sql_is_select_only_and_uses_window_cut():
    sql = recent_bars_sql(3).upper()
    assert sql.lstrip().startswith("SELECT")
    for verb in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "REPLACE"):
        assert verb not in sql
    assert "ROW_NUMBER() OVER (PARTITION BY SYMBOL ORDER BY TRADE_DATE DESC)" in sql
    assert "RN <= ?" in sql


def test_window_is_enough_for_sma200_and_cup_signal():
    full_df = _synthetic_series(1300, seed=0)
    conn = _db({"AAA": full_df})
    window = fetch_recent_bars(conn, ["AAA"])["AAA"]
    win_df = pd.DataFrame([dict(r) for r in window]).rename(columns={"trade_date": "date"})
    for col in ("open", "high", "low", "close", "volume"):
        win_df[col] = pd.to_numeric(win_df[col])

    # Indicators at the latest bars must be identical, not just close.
    _, A_full = _prepare(full_df)
    _, A_win = _prepare(win_df)
    I_full, I_win = _indicators(A_full), _indicators(A_win)
    for key in ("sma200", "ema20", "atr", "med20"):
        assert np.isclose(I_full[key][-1], I_win[key][-1], rtol=1e-9), key
    assert np.isclose(I_full["sma200"][-1], I_win["sma200"][-1])

    # Signals whose date lies inside the window must match the full-history scan exactly.
    first_win_date = win_df["date"].iloc[0]
    full_sig = [s for s in scan_symbol("AAA", full_df) if s["signal_date"] >= first_win_date]
    win_sig = scan_symbol("AAA", win_df)
    key = lambda s: (s["pattern"], s["state"], s["signal_date"], s["formation_high"],
                     s["pattern_floor"], s["suggested_stop"], s["clear_runway_pct"])
    assert sorted(map(key, full_sig)) == sorted(map(key, win_sig))
    assert any(s["pattern"] == "CUP_WITH_HANDLE" for s in win_sig)
