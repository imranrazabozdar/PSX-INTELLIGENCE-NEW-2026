"""database.py — SQLite schema, initialization, and a thin DatabaseManager
for the PSX FIRE Engine. Schema matches the spec's SQL exactly (table and
column names, types, constraints), with the indexes it specifies.

Turso-ready in the same sense the rest of this repo already is (see
backend/turso_db.py): this module talks to a local sqlite3 file directly.
Wiring it to Turso instead is a drop-in swap of the connection object,
not a schema change -- deliberately not done here, since nothing in this
task asked FIRE Engine data to live in the same Turso database as the
existing daily_ohlc/backtest tables, and mixing them would need an
explicit decision this task doesn't make for you.
"""
import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stocks (
    symbol TEXT PRIMARY KEY,
    name TEXT,
    enabled BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trading_sessions (
    session_id TEXT PRIMARY KEY,
    session_date DATE NOT NULL,
    total_candles INTEGER,
    expected_candles INTEGER DEFAULT 480,
    data_quality_status TEXT,
    collection_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    collection_duration_seconds INTEGER
);

CREATE TABLE IF NOT EXISTS market_candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    datetime DATETIME NOT NULL,
    date DATE NOT NULL,
    time_of_day TEXT NOT NULL,
    open DECIMAL(10,4) NOT NULL,
    high DECIMAL(10,4) NOT NULL,
    low DECIMAL(10,4) NOT NULL,
    close DECIMAL(10,4) NOT NULL,
    volume BIGINT NOT NULL,
    data_source TEXT DEFAULT 'SCS',
    collection_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    data_quality_status TEXT DEFAULT 'VALID',
    session_id TEXT,
    UNIQUE(symbol, datetime),
    FOREIGN KEY (symbol) REFERENCES stocks(symbol),
    FOREIGN KEY (session_id) REFERENCES trading_sessions(session_id)
);

CREATE TABLE IF NOT EXISTS volume_baseline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    time_of_day TEXT NOT NULL,
    median_volume BIGINT,
    mean_volume BIGINT,
    lookback_sessions INTEGER DEFAULT 30,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, time_of_day),
    FOREIGN KEY (symbol) REFERENCES stocks(symbol)
);

CREATE TABLE IF NOT EXISTS fire_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    event_date DATE NOT NULL,
    event_time TIME NOT NULL,
    event_datetime DATETIME NOT NULL,
    event_type TEXT NOT NULL,
    mfi_value DECIMAL(5,2),
    mfi_acceleration_5m DECIMAL(5,2),
    mfi_acceleration_15m DECIMAL(5,2),
    volume_condition TEXT,
    relative_volume DECIMAL(5,2),
    price_compression_pct DECIMAL(5,4),
    fire_score INTEGER,
    session_transition BOOLEAN DEFAULT 0,
    near_close BOOLEAN DEFAULT 0,
    notes TEXT,
    FOREIGN KEY (symbol) REFERENCES stocks(symbol),
    UNIQUE(symbol, event_datetime, event_type)
);

CREATE TABLE IF NOT EXISTS daily_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date DATE NOT NULL,
    symbol TEXT NOT NULL,
    data_quality_status TEXT,
    highest_mfi_acceleration DECIMAL(5,2),
    highest_fire_score INTEGER,
    pre_fire_count INTEGER DEFAULT 0,
    fire_count INTEGER DEFAULT 0,
    absorption_count INTEGER DEFAULT 0,
    failed_setup_count INTEGER DEFAULT 0,
    near_close_events_count INTEGER DEFAULT 0,
    report_html TEXT,
    generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (symbol) REFERENCES stocks(symbol),
    UNIQUE(report_date, symbol)
);

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT,
    description TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_candles_symbol_datetime ON market_candles(symbol, datetime);
CREATE INDEX IF NOT EXISTS idx_candles_symbol_date ON market_candles(symbol, date);
CREATE INDEX IF NOT EXISTS idx_candles_symbol_time ON market_candles(symbol, time_of_day);
CREATE INDEX IF NOT EXISTS idx_candles_session ON market_candles(session_id);
CREATE INDEX IF NOT EXISTS idx_fire_events_symbol_date ON fire_events(symbol, event_date);
CREATE INDEX IF NOT EXISTS idx_fire_events_type ON fire_events(event_type);
CREATE INDEX IF NOT EXISTS idx_fire_events_score ON fire_events(fire_score DESC);
"""
# NOTE: the spec's idx_candles_date_range used a `date('now', '-90 days')`
# partial-index predicate. SQLite partial indexes are static at creation
# time (the predicate is evaluated once, not re-evaluated as "now" moves),
# so a rolling 90-day window can't actually be expressed as a partial
# index in SQLite -- it would silently freeze to whatever "now" was when
# the index was created, then quietly stop covering new rows. Omitted
# rather than built as something that looks live but isn't; the plain
# idx_candles_symbol_date index above covers the same range-query pattern.


def initialize_database(db_path: str) -> None:
    """Create all tables and indexes. Safe to call repeatedly (IF NOT EXISTS)."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def _row_to_candle(row) -> dict:
    return {
        "symbol": row["symbol"], "datetime": row["datetime"], "date": row["date"],
        "time_of_day": row["time_of_day"], "open": row["open"], "high": row["high"],
        "low": row["low"], "close": row["close"], "volume": row["volume"],
        "data_source": row["data_source"], "data_quality_status": row["data_quality_status"],
        "session_id": row["session_id"],
    }


class DatabaseManager:
    """Thin wrapper around a database connection. Every write that can
    collide with existing data uses INSERT ... ON CONFLICT DO UPDATE
    (UPSERT) against the table's own UNIQUE constraint, so re-running the
    same ingestion twice is a no-op, not a duplicate or an error -- the
    idempotency the spec's testing section explicitly requires.

    Two ways to construct it:
      - DatabaseManager(db_path="psx_fire.db") -- standalone local sqlite
        file, own connection, closed by this instance. Used for local
        development/testing (e.g. by run_daily_batch.py when invoked
        without --shared-db).
      - DatabaseManager(conn=<existing connection>) -- an already-open
        connection this instance does NOT own/close, e.g.
        backend/turso_db.get_connection() -- so the FIRE Engine's tables
        live in the SAME database backend/app.py's Patterns tab already
        reads from, not a second, invisible-to-the-app sqlite file. Both
        sqlite3 connections and turso_db's wrapper support execute/
        executemany/executescript with dict-like rows, so this class
        works unmodified against either.
    """

    def __init__(self, db_path: str = None, conn=None):
        if conn is not None and db_path is not None:
            raise ValueError("pass either db_path or conn, not both")
        if conn is not None:
            self.conn = conn
            self.db_path = None
            self._owns_conn = False
        else:
            self.db_path = db_path
            self.conn = sqlite3.connect(db_path)
            self.conn.row_factory = sqlite3.Row
            self._owns_conn = True
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def close(self):
        if self._owns_conn:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def ensure_stock(self, symbol: str, name: str = None):
        self.conn.execute(
            "INSERT INTO stocks (symbol, name) VALUES (?, ?) "
            "ON CONFLICT(symbol) DO UPDATE SET name = COALESCE(excluded.name, stocks.name)",
            (symbol, name),
        )
        self.conn.commit()

    def upsert_session(self, session_id: str, session_date: str, total_candles: int,
                        expected_candles: int, data_quality_status: str,
                        collection_duration_seconds: int = None):
        self.conn.execute(
            """INSERT INTO trading_sessions
               (session_id, session_date, total_candles, expected_candles,
                data_quality_status, collection_duration_seconds)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                 total_candles=excluded.total_candles,
                 expected_candles=excluded.expected_candles,
                 data_quality_status=excluded.data_quality_status,
                 collection_duration_seconds=excluded.collection_duration_seconds""",
            (session_id, session_date, total_candles, expected_candles,
             data_quality_status, collection_duration_seconds),
        )
        self.conn.commit()

    def insert_candles(self, symbol: str, candles: list, session_id: str = None,
                        data_source: str = "SCS", data_quality_status: str = "VALID") -> int:
        """UPSERT candles keyed on (symbol, datetime). Returns count inserted/updated.
        Each candle is a dict with datetime/date/time_of_day/open/high/low/close/volume."""
        self.ensure_stock(symbol)
        rows = [
            (symbol, c["datetime"], c["date"], c["time_of_day"], c["open"], c["high"],
             c["low"], c["close"], c["volume"], data_source, data_quality_status, session_id)
            for c in candles
        ]
        self.conn.executemany(
            """INSERT INTO market_candles
               (symbol, datetime, date, time_of_day, open, high, low, close, volume,
                data_source, data_quality_status, session_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(symbol, datetime) DO UPDATE SET
                 open=excluded.open, high=excluded.high, low=excluded.low,
                 close=excluded.close, volume=excluded.volume,
                 data_source=excluded.data_source,
                 data_quality_status=excluded.data_quality_status,
                 session_id=excluded.session_id""",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def query_candles(self, symbol: str, start_date: str, end_date: str) -> list:
        cur = self.conn.execute(
            "SELECT * FROM market_candles WHERE symbol = ? AND date BETWEEN ? AND ? "
            "ORDER BY datetime ASC",
            (symbol, start_date, end_date),
        )
        return [_row_to_candle(r) for r in cur.fetchall()]

    def query_candles_for_session(self, symbol: str, session_date: str) -> list:
        return self.query_candles(symbol, session_date, session_date)
