"""turso_db.py — shared database connection layer.

Every other module in this backend (app.py, database.py, scan_cache_engine.py,
audit_engine.py, backtest_engine.py) used to call sqlite3.connect(DB) directly.
That works fine on a host with a real disk, but Streamlit Community Cloud has
none: the filesystem resets on every redeploy/restart, so a plain local file
silently loses all 500K+ backfilled rows the first time the app restarts.

This module switches behavior based on environment variables:

  - LIBSQL_URL and LIBSQL_AUTH_TOKEN both set (e.g. on Streamlit Cloud):
    connects via libsql's "embedded replica" mode — a local file used for
    fast reads, transparently kept in sync with a real Turso database in the
    cloud. Reads/writes still go through the same execute()/commit() calls;
    only the connection setup differs. Call sync_if_remote() after a write
    you want durable immediately (a backfill, a cache save) rather than
    waiting for the next periodic sync tick.

  - Neither set (local development, or any host with a real persistent
    disk): behaves exactly as before, a plain local sqlite3 file. Nothing
    changes for that deployment path.

IMPORTANT — untested integration: libsql's Python package needs a native
extension that this project's development environment could not build (a
Rust-toolchain issue specific to that machine's Python version, not
something expected to recur on Streamlit Cloud's own Linux runtime, which
ships prebuilt wheels for libsql). The embedded-replica path in this file is
written against Turso's official documented API but has not been exercised
end-to-end against a real Turso database. Smoke-test it (run the backend
with LIBSQL_URL/LIBSQL_AUTH_TOKEN set and confirm /health plus a few reads
and one write-then-restart round-trip) before trusting it with real data.

Row access: every row returned from this module's connection is a plain
dict (both row["col"] and row.get("col") work), via a custom row_factory —
deliberately NOT sqlite3.Row specifically, since that class's exact
semantics aren't guaranteed to be replicated by every DB-API-compatible
driver. A plain callable row_factory is part of the standard protocol any
"drop-in sqlite3 replacement" is expected to honor.
"""

import os
import sqlite3
import threading

LIBSQL_URL = os.getenv("LIBSQL_URL")
LIBSQL_AUTH_TOKEN = os.getenv("LIBSQL_AUTH_TOKEN")
LOCAL_REPLICA_PATH = os.getenv("PSX_DB", "psx_v2.db")
# How often the embedded replica auto-syncs with the remote, in seconds.
# Independent of any explicit sync_if_remote() calls after writes you want
# durable sooner.
SYNC_INTERVAL_SECONDS = int(os.getenv("LIBSQL_SYNC_INTERVAL", "60"))

USING_TURSO = bool(LIBSQL_URL and LIBSQL_AUTH_TOKEN)

_lock = threading.Lock()
_shared_conn = None
_init_error = None


class _Row(dict):
    """dict subclass — row["col"] and row.get("col") both work, matching how
    this codebase already treats query results everywhere (many call sites
    do dict(row) or row.get(...) directly). Deliberately not sqlite3.Row."""
    __slots__ = ()


def _row_factory(cursor, row):
    return _Row(zip((d[0] for d in cursor.description), row))


def _make_connection():
    if USING_TURSO:
        import libsql  # deferred import: only required when actually using Turso
        conn = libsql.connect(LOCAL_REPLICA_PATH, sync_url=LIBSQL_URL,
                               auth_token=LIBSQL_AUTH_TOKEN,
                               sync_interval=SYNC_INTERVAL_SECONDS)
        # Force an initial pull so a freshly-provisioned container (empty
        # local disk) is hydrated from the remote before anything reads from
        # it, rather than waiting for the first periodic sync_interval tick.
        conn.sync()
    else:
        # check_same_thread=False: this connection is now a shared,
        # process-wide singleton (get_connection() below), reused across
        # FastAPI's request threadpool AND the background refresh-loop
        # threads — sqlite3's default same-thread check rejects exactly
        # that, since every prior call site used to get a brand-new
        # connection per call instead of sharing one. WAL mode + every
        # caller's existing timeout=30/retry handling is what actually
        # keeps concurrent access safe; this flag just stops sqlite3 from
        # refusing legitimate cross-thread use of that one connection.
        conn = sqlite3.connect(LOCAL_REPLICA_PATH, timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = _row_factory
    return conn


def get_connection():
    """Return the shared, process-wide database connection, creating it on
    first use. One physical connection is reused across every caller in this
    process — the embedded replica's sync machinery is not designed to be
    re-established on every single query the way a fresh sqlite3.connect()
    per call tolerates. Callers still manage their own transactions/commits
    exactly as before (this only replaces how the connection itself is
    obtained, not the surrounding with-block / commit() patterns)."""
    global _shared_conn, _init_error
    if _shared_conn is None:
        with _lock:
            if _shared_conn is None:
                try:
                    _shared_conn = _make_connection()
                except Exception as e:
                    _init_error = f"{type(e).__name__}: {e}"
                    if USING_TURSO:
                        print(f"[turso_db] Turso connection failed ({_init_error}) — "
                              f"falling back to a plain local SQLite file. Data will "
                              f"NOT persist across restarts on a host with no disk "
                              f"(e.g. Streamlit Community Cloud) until this is fixed.")
                        conn = sqlite3.connect(LOCAL_REPLICA_PATH, timeout=30, check_same_thread=False)
                        conn.execute("PRAGMA journal_mode=WAL")
                        conn.row_factory = _row_factory
                        _shared_conn = conn
                    else:
                        raise
    return _shared_conn


def sync_if_remote():
    """Push pending local writes to the remote Turso database immediately,
    rather than waiting for the next periodic sync_interval tick. Call this
    after a write you want durable right away (a backfill, a cache save).
    No-op when not using Turso (plain local SQLite has nothing to sync)."""
    if USING_TURSO and _shared_conn is not None:
        try:
            _shared_conn.sync()
        except Exception as e:
            print(f"[turso_db] sync failed: {type(e).__name__}: {e}")


def status():
    """For /health — never crashes, always reports what's actually true."""
    return {"backend": "turso (libsql embedded replica)" if USING_TURSO else "local sqlite3",
            "connected": _shared_conn is not None,
            "init_error": _init_error}
