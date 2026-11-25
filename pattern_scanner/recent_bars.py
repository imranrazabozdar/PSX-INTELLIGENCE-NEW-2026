"""Read-only loader for the most recent N daily bars per symbol (used by the Chart Patterns tab).

One SELECT per symbol chunk; the window function cuts each symbol to its latest `sessions`
rows in SQL, so the app never pulls the full history. Returns rows ordered by symbol then
trade_date ascending, the same shape the previous unbounded query returned.
"""

RECENT_SESSIONS = 250   # 130-bar Cup-with-Handle window + 200-bar SMA warm-up, with margin


def recent_bars_sql(n_placeholders, sessions=RECENT_SESSIONS):
    """SQL text for `n_placeholders` symbols; bind the symbols followed by `sessions`."""
    ph = ",".join("?" * n_placeholders)
    return (
        "SELECT symbol, trade_date, open, high, low, close, volume FROM ("
        "  SELECT symbol, trade_date, open, high, low, close, volume,"
        "         ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY trade_date DESC) AS rn"
        f"  FROM daily_ohlc WHERE symbol IN ({ph})"
        ") WHERE rn <= ? ORDER BY symbol, trade_date"
    )


def fetch_recent_bars(conn, symbols, sessions=RECENT_SESSIONS, chunk=50):
    """Return {SYMBOL: [row, ...]} with the latest `sessions` rows per symbol, ascending."""
    by_sym = {}
    symbols = list(symbols)
    for i in range(0, len(symbols), chunk):
        part = symbols[i:i + chunk]
        for r in conn.execute(recent_bars_sql(len(part), sessions), (*part, sessions)).fetchall():
            by_sym.setdefault(str(r["symbol"]).upper(), []).append(r)
    return by_sym
