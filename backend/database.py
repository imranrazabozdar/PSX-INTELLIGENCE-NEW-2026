"""database.py — Compatibility shim for the ported V1 modules.

The V1 engine was built around a learning loop that stored every run, graded
outcomes days later, and fed per-indicator accuracy back into confidence. That
loop is NOT running in the V2/V4 FastAPI deployment, so the tables it depended
on are empty or absent.

This shim provides the exact call surface the V1 modules import, backed by the
same SQLite file app.py already uses. Where the V1 loop's history genuinely does
not exist yet, the functions return EMPTY results rather than invented ones —
which the V1 code already handles correctly and explicitly:

  * scoring_engine.historical_confidence_adjust() -> "No strictly-graded history
    yet - base confidence." (adjustment 0.0)
  * scoring_engine._indicator_accuracy_boost()    -> 0.0, no note
  * signal_generator's db.last_run()              -> None -> "Avoid" not "Exit"

So the ported modules degrade honestly instead of scoring against fake history.
As the tables fill (see save_run/save_sentiment below), the learning loop
reactivates automatically with no further code changes.
"""

import os
import sqlite3
import logging

log = logging.getLogger("database")

DB = os.getenv("PSX_DB", "psx_v2.db")


def _conn():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def ensure_schema():
    """Create the learning-loop tables if they don't exist. Safe to call often."""
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS runs(
          id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, symbol TEXT,
          signal TEXT, score REAL, confidence REAL, price REAL,
          stop REAL, target REAL, outcome TEXT);
        CREATE INDEX IF NOT EXISTS ix_runs ON runs(symbol, ts);
        CREATE TABLE IF NOT EXISTS sentiment(
          id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, symbol TEXT,
          score REAL, bullish INT, bearish INT, neutral INT,
          mentions INT, flags TEXT);
        CREATE INDEX IF NOT EXISTS ix_sent ON sentiment(symbol, ts);
        CREATE TABLE IF NOT EXISTS indicator_accuracy(
          symbol TEXT, indicator TEXT, hits INT DEFAULT 0, misses INT DEFAULT 0,
          PRIMARY KEY(symbol, indicator));
        """)
        c.commit()


ensure_schema()


# ---------------------------------------------------------------- reads
def recent_news(hours=48, symbol=None):
    """Rows from app.py's existing `news` table. Returns [] when unpopulated."""
    try:
        with _conn() as c:
            if symbol:
                q = ("SELECT * FROM news WHERE symbols LIKE ? "
                     "ORDER BY fetched_at DESC LIMIT 200")
                rows = c.execute(q, (f"%{symbol.upper()}%",)).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM news ORDER BY fetched_at DESC LIMIT 200"
                ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


def signal_accuracy(symbol=None):
    """Graded signal outcomes. Empty until the outcome tracker runs."""
    try:
        with _conn() as c:
            q = ("SELECT signal, outcome, COUNT(*) AS n FROM runs "
                 "WHERE outcome IS NOT NULL AND outcome != ''")
            args = []
            if symbol:
                q += " AND symbol=?"
                args.append(symbol.upper())
            q += " GROUP BY signal, outcome"
            return [dict(r) for r in c.execute(q, args)]
    except sqlite3.Error:
        return []


def indicator_stats(symbol):
    """Per-indicator hit/miss record for one symbol. Empty until graded."""
    try:
        with _conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT indicator, hits, misses FROM indicator_accuracy "
                "WHERE symbol=?", (symbol.upper(),))]
    except sqlite3.Error:
        return []


def last_run(symbol):
    """Most recent stored run for this symbol, or None."""
    try:
        with _conn() as c:
            r = c.execute("SELECT * FROM runs WHERE symbol=? "
                          "ORDER BY ts DESC LIMIT 1",
                          (symbol.upper(),)).fetchone()
        return dict(r) if r else None
    except sqlite3.Error:
        return None


def previous_sentiment(symbol):
    """Previous run's sentiment score for trend comparison, or None."""
    try:
        with _conn() as c:
            r = c.execute("SELECT score FROM sentiment WHERE symbol=? "
                          "ORDER BY ts DESC LIMIT 1",
                          (symbol.upper(),)).fetchone()
        return float(r["score"]) if r else None
    except sqlite3.Error:
        return None


# ---------------------------------------------------------------- writes
def save_sentiment(ts, symbol, score, bullish, bearish, neutral, mentions, flags):
    try:
        with _conn() as c:
            c.execute("INSERT INTO sentiment(ts,symbol,score,bullish,bearish,"
                      "neutral,mentions,flags) VALUES(?,?,?,?,?,?,?,?)",
                      (ts, symbol.upper(), score, bullish, bearish, neutral,
                       mentions, ";".join(flags or [])))
            c.commit()
    except sqlite3.Error as e:
        log.warning("save_sentiment failed: %s", e)


def save_run(ts, symbol, signal, score, confidence, price,
             stop=None, target=None):
    """Store a run so the outcome tracker can grade it later. Calling this is
    what re-activates the V1 learning loop over time."""
    try:
        with _conn() as c:
            c.execute("INSERT INTO runs(ts,symbol,signal,score,confidence,"
                      "price,stop,target) VALUES(?,?,?,?,?,?,?,?)",
                      (ts, symbol.upper(), signal, score, confidence,
                       price, stop, target))
            c.commit()
    except sqlite3.Error as e:
        log.warning("save_run failed: %s", e)


def save_run_daily(ts, symbol, signal, score, confidence, price,
                   stop=None, target=None):
    """Store AT MOST ONE row per symbol per calendar day.

    The V1 loop ran every 15 minutes and stored every cycle; the backtester then
    day-deduped before computing win rates, because many polls of one session are
    not independent confirmations. Here /decision can be hit arbitrarily often by
    the app, so dedupe at write time instead: the first call each day inserts,
    later calls update that row only if the SIGNAL changed (keeping the latest
    view of the day without inflating the sample).

    Returns "inserted" | "updated" | "unchanged" | None on failure.
    """
    try:
        day = (ts or "")[:10]
        sym = symbol.upper()
        with _conn() as c:
            row = c.execute("SELECT id, signal FROM runs WHERE symbol=? "
                            "AND substr(ts,1,10)=? ORDER BY ts DESC LIMIT 1",
                            (sym, day)).fetchone()
            if row is None:
                c.execute("INSERT INTO runs(ts,symbol,signal,score,confidence,"
                          "price,stop,target) VALUES(?,?,?,?,?,?,?,?)",
                          (ts, sym, signal, score, confidence, price, stop, target))
                c.commit(); return "inserted"
            if row["signal"] != signal:
                c.execute("UPDATE runs SET ts=?,signal=?,score=?,confidence=?,"
                          "price=?,stop=?,target=? WHERE id=?",
                          (ts, signal, score, confidence, price, stop, target,
                           row["id"]))
                c.commit(); return "updated"
        return "unchanged"
    except sqlite3.Error as e:
        log.warning("save_run_daily failed: %s", e)
        return None


def ungraded_runs(min_age_days=7, limit=500):
    """Runs with no outcome yet that are old enough for the grading horizon."""
    try:
        with _conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM runs WHERE (outcome IS NULL OR outcome='') "
                "AND julianday('now') - julianday(ts) >= ? "
                "ORDER BY ts ASC LIMIT ?", (min_age_days, limit))]
    except sqlite3.Error:
        return []


def set_outcome(run_id, outcome):
    try:
        with _conn() as c:
            c.execute("UPDATE runs SET outcome=? WHERE id=?", (outcome, run_id))
            c.commit()
            return True
    except sqlite3.Error as e:
        log.warning("set_outcome failed: %s", e)
        return False


def record_indicator_result(symbol, indicator, hit):
    """Accumulate per-indicator hit/miss so scoring_engine's
    _indicator_accuracy_boost can eventually modulate confidence."""
    try:
        col = "hits" if hit else "misses"
        with _conn() as c:
            c.execute("INSERT OR IGNORE INTO indicator_accuracy(symbol,indicator)"
                      " VALUES(?,?)", (symbol.upper(), indicator))
            c.execute(f"UPDATE indicator_accuracy SET {col}={col}+1 "
                      "WHERE symbol=? AND indicator=?", (symbol.upper(), indicator))
            c.commit()
    except sqlite3.Error as e:
        log.warning("record_indicator_result failed: %s", e)

