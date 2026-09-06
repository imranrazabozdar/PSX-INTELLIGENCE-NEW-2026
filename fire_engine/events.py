"""events.py — Phase 13: fire_events persistence and querying."""


def log_fire_event(db, symbol: str, event_type: str, event_datetime: str,
                    mfi_value: float = None, mfi_acceleration_5m: float = None,
                    mfi_acceleration_15m: float = None, volume_condition: str = None,
                    relative_volume: float = None, price_compression_pct: float = None,
                    fire_score: int = None, session_transition: bool = False,
                    near_close: bool = False, notes: str = None) -> int:
    """Insert into fire_events (UPSERT on the symbol/event_datetime/event_type
    UNIQUE constraint -- re-logging the same event is a no-op update, not a
    duplicate row). Returns the row id."""
    event_date, event_time = event_datetime.split(" ") if " " in event_datetime else (event_datetime, "00:00:00")
    db.ensure_stock(symbol)
    cur = db.conn.execute(
        """INSERT INTO fire_events
           (symbol, event_date, event_time, event_datetime, event_type, mfi_value,
            mfi_acceleration_5m, mfi_acceleration_15m, volume_condition, relative_volume,
            price_compression_pct, fire_score, session_transition, near_close, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(symbol, event_datetime, event_type) DO UPDATE SET
             mfi_value=excluded.mfi_value,
             mfi_acceleration_5m=excluded.mfi_acceleration_5m,
             mfi_acceleration_15m=excluded.mfi_acceleration_15m,
             volume_condition=excluded.volume_condition,
             relative_volume=excluded.relative_volume,
             price_compression_pct=excluded.price_compression_pct,
             fire_score=excluded.fire_score,
             session_transition=excluded.session_transition,
             near_close=excluded.near_close,
             notes=excluded.notes""",
        (symbol, event_date, event_time, event_datetime, event_type, mfi_value,
         mfi_acceleration_5m, mfi_acceleration_15m, volume_condition, relative_volume,
         price_compression_pct, fire_score, int(session_transition), int(near_close), notes),
    )
    db.conn.commit()
    row = db.conn.execute(
        "SELECT id FROM fire_events WHERE symbol=? AND event_datetime=? AND event_type=?",
        (symbol, event_datetime, event_type),
    ).fetchone()
    return row["id"] if row else cur.lastrowid


def query_fire_events(db, symbol: str = None, event_type: str = None,
                       date_from: str = None, date_to: str = None,
                       min_fire_score: int = None) -> list:
    """Flexible filter query against fire_events."""
    clauses, params = [], []
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol)
    if event_type:
        clauses.append("event_type = ?")
        params.append(event_type)
    if date_from:
        clauses.append("event_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("event_date <= ?")
        params.append(date_to)
    if min_fire_score is not None:
        clauses.append("fire_score >= ?")
        params.append(min_fire_score)

    sql = "SELECT * FROM fire_events"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY event_datetime ASC"

    cur = db.conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]
