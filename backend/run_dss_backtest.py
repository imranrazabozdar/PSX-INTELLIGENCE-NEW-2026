"""run_dss_backtest.py — TEMPORARY walk-forward backtest of psx_brain's
composite confidence score against true PSX DPS daily OHLCV. Read-only:
never writes to psx_v2.db, no backend files modified.

WHY psx_brain, NOT dss_engine.compute() DIRECTLY: dss_engine.compute()
is not a standalone function of historical price bars — its ~10
components (Wyckoff phase, sector regime, the live event-risk feed, the
blended psx_brain-verdict/DSS-decision cross-check) are individually
orchestrated LIVE in app.py from several other engines that themselves
need live market context (today's sector breadth, the news feed at that
moment) that cannot be faithfully reconstructed for an arbitrary past
date without a large new historical-replay pipeline this codebase
doesn't have. psx_brain.analyse() IS exactly the self-contained kind of
analyst that CAN be walk-forward-backtested honestly — a pure function
of (symbol, daily OHLCV, optional benchmark), "no API, no cost, runs
offline" per its own module docstring. Its 0-100 `confidence` field is
the same composite "second opinion" score already surfaced in the
Screener's Whole-Book Scan, so it's the one number in this codebase that
is both (a) genuinely DSS-consensus-equivalent in spirit and (b) honest
to backtest without fabricating history for engines that need live data.

METHOD (no lookahead, ever):
  For each symbol, for each sampled historical date T (SAMPLE_STRIDE_DAYS
  apart — psx_brain.analyse() does real indicator work, ~250-350ms per
  call, so scanning every single day across the full symbol list would
  take hours; striding is a documented, standard compute-tractability
  tradeoff, not a shortcut on correctness):
    - Slice the symbol's OHLCV to rows with date <= T only — nothing
      after T is ever visible to the score at signal time.
    - Call psx_brain.analyse() on that slice -> confidence score.
    - If confidence >= BUY_THRESHOLD, a signal fires:
        entry = NEXT trading session's OPEN (T+1) — the earliest a real
                order could actually have been filled, not T's own close.
        exit  = close of the session HORIZON_DAYS trading sessions after
                entry.
        max drawdown = worst (low - entry)/entry seen at any point during
                the hold, using each day's real intraday LOW.
    - A signal is skipped (not counted, not padded with fake data) if
      HORIZON_DAYS of forward data don't exist yet — i.e. the most
      recent ~HORIZON_DAYS of history can never produce a countable
      trade, exactly as a live trader couldn't know that outcome yet
      either.
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

import psx_brain

DB_PATH = Path(__file__).parent / "psx_v2.db"

# 12 liquid, sector-diversified names with full multi-year DPS/legacy
# history in daily_ohlc (confirmed >=1280 rows each before this run) —
# the same "quick pick" universe streamlit_app.py's Stock Research tab
# already treats as representative liquid names, plus PSO/BAFL/HUBC for
# broader sector coverage (oil, banking, power).
SYMBOLS = ["OGDC", "PPL", "HBL", "UBL", "LUCK", "FFC", "PSO", "MCB", "SYS", "MARI", "BAFL", "HUBC"]

YEARS_BACK = 2               # walk-forward window per symbol
BUY_THRESHOLD = 70            # psx_brain confidence >= this counts as a BUY-equivalent signal
HORIZON_DAYS = 20             # trading sessions held per signal
SAMPLE_STRIDE_DAYS = 4        # signal-check cadence — see module docstring
TRADING_DAYS_PER_YEAR = 252


def load_symbol_df(conn, symbol):
    rows = conn.execute(
        "SELECT trade_date, open, high, low, close, volume FROM daily_ohlc "
        "WHERE symbol=? ORDER BY trade_date ASC", (symbol,)).fetchall()
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def backtest_symbol(symbol, df):
    """Returns a list of trade dicts. No lookahead: analyse() only ever
    sees df.iloc[:i+1] (through and including the signal date)."""
    n = len(df)
    lookback_bars = TRADING_DAYS_PER_YEAR * YEARS_BACK
    start_i = max(220, n - lookback_bars)  # 220: enough bars for SMA200/weekly resample to be meaningful
    trades = []
    for i in range(start_i, n - HORIZON_DAYS, SAMPLE_STRIDE_DAYS):
        window = df.iloc[: i + 1]
        try:
            r = psx_brain.analyse(symbol, window, bench=None, partial="raw")
        except Exception:
            continue  # a data gap/short window for this date -- skip, don't crash the run
        if r["confidence"] < BUY_THRESHOLD:
            continue

        entry_i = i + 1
        exit_i = entry_i + HORIZON_DAYS - 1
        if exit_i >= n:
            continue  # not enough forward data yet -- never fabricate an exit

        entry_price = float(df["open"].iloc[entry_i])
        exit_price = float(df["close"].iloc[exit_i])
        hold = df.iloc[entry_i: exit_i + 1]
        worst_low = float(hold["low"].min())
        mdd_pct = (worst_low - entry_price) / entry_price * 100
        ret_pct = (exit_price - entry_price) / entry_price * 100

        risk_pct = r["levels"]["risk_pct"]  # psx_brain's own stop-distance at signal time
        r_multiple = (ret_pct / risk_pct) if risk_pct and risk_pct > 0 else None

        trades.append({
            "symbol": symbol,
            "signal_date": df.index[i].strftime("%Y-%m-%d"),
            "entry_date": df.index[entry_i].strftime("%Y-%m-%d"),
            "entry_price": entry_price,
            "exit_date": df.index[exit_i].strftime("%Y-%m-%d"),
            "exit_price": exit_price,
            "confidence": r["confidence"],
            "verdict": r["verdict"],
            "return_pct": ret_pct,
            "max_drawdown_pct": mdd_pct,
            "r_multiple": r_multiple,
        })
    return trades


def summarize(trades):
    if not trades:
        return None
    rets = np.array([t["return_pct"] for t in trades])
    mdds = np.array([t["max_drawdown_pct"] for t in trades])
    r_mults = np.array([t["r_multiple"] for t in trades if t["r_multiple"] is not None])

    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    win_rate = len(wins) / len(rets) * 100

    return {
        "total_signals": len(trades),
        "win_rate_pct": win_rate,
        "avg_return_pct": rets.mean(),
        "median_return_pct": np.median(rets),
        "avg_win_pct": wins.mean() if len(wins) else 0.0,
        "avg_loss_pct": losses.mean() if len(losses) else 0.0,
        "avg_max_drawdown_pct": mdds.mean(),
        "worst_single_trade_drawdown_pct": mdds.min(),
        "expectancy_R": r_mults.mean() if len(r_mults) else None,
    }


def main():
    conn = sqlite3.connect(DB_PATH)
    all_trades = []
    per_symbol_rows = []

    print(f"Walk-forward backtesting psx_brain confidence >= {BUY_THRESHOLD} "
          f"over {YEARS_BACK}y, {HORIZON_DAYS}-session horizon, "
          f"sampled every {SAMPLE_STRIDE_DAYS} sessions.\n")

    for sym in SYMBOLS:
        df = load_symbol_df(conn, sym)
        if df is None or len(df) < 260:
            print(f"  {sym}: insufficient history — skipped")
            continue
        trades = backtest_symbol(sym, df)
        all_trades.extend(trades)
        s = summarize(trades)
        per_symbol_rows.append((sym, len(trades),
                                 f"{s['win_rate_pct']:.1f}%" if s else "—",
                                 f"{s['avg_return_pct']:+.2f}%" if s else "—"))
        print(f"  {sym}: {len(trades)} signal(s) — done")

    print("\n" + "=" * 78)
    print("PER-SYMBOL SIGNAL COUNT")
    print("=" * 78)
    print(f"{'Symbol':<8}{'Signals':<10}{'Win Rate':<12}{'Avg Return':<12}")
    for row in per_symbol_rows:
        print(f"{row[0]:<8}{row[1]:<10}{row[2]:<12}{row[3]:<12}")

    overall = summarize(all_trades)
    print("\n" + "=" * 78)
    print(f"OVERALL BACKTEST SUMMARY — psx_brain confidence >= {BUY_THRESHOLD}, "
          f"{HORIZON_DAYS}-session horizon")
    print("=" * 78)
    if overall is None:
        print("No signals fired across the tested universe/window — nothing to report.")
        return

    print(f"{'Total signals:':<32}{overall['total_signals']}")
    print(f"{'Win rate:':<32}{overall['win_rate_pct']:.1f}%")
    print(f"{'Average return:':<32}{overall['avg_return_pct']:+.2f}%")
    print(f"{'Median return:':<32}{overall['median_return_pct']:+.2f}%")
    print(f"{'Average winning trade:':<32}{overall['avg_win_pct']:+.2f}%")
    print(f"{'Average losing trade:':<32}{overall['avg_loss_pct']:+.2f}%")
    print(f"{'Average max drawdown/trade:':<32}{overall['avg_max_drawdown_pct']:.2f}%")
    print(f"{'Worst single-trade drawdown:':<32}{overall['worst_single_trade_drawdown_pct']:.2f}%")
    if overall["expectancy_R"] is not None:
        print(f"{'Expectancy (R-multiple):':<32}{overall['expectancy_R']:+.2f}R")
    print("\nNote: 'Expectancy (R-multiple)' expresses average return as a multiple of "
          "psx_brain's own stop-distance (risk_pct) at signal time — e.g. +0.50R means "
          "the average trade returned half of what was risked to the stop. Data is a mix "
          "of PSX Data Portal (recent ~3 months, refreshed this session) and the prior "
          "Yahoo-sourced history for dates before that — see daily_ohlc.source per row.")


if __name__ == "__main__":
    main()
