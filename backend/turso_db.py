"""turso_db.py — shared database connection layer.

Every other module in this backend (app.py, database.py, scan_cache_engine.py,
audit_engine.py, backtest_engine.py) used to call sqlite3.connect(DB) directly.
That works fine on a host with a real disk, but Streamlit Community Cloud has
none: the filesystem resets on every redeploy/restart, so a plain local file
silently loses all 500K+ backfilled rows the first time the app restarts.

This module switches behavior based on environment variables:

  - LIBSQL_URL and LIBSQL_AUTH_TOKEN both set (e.g. on Streamlit Cloud):
    talks to Turso directly over its HTTPS "Hrana v2 pipeline" API
    (https://<db>.turso.io/v2/pipeline) via plain `requests` calls — no
    native extension involved. This is deliberately NOT the `libsql` Python
    package's "embedded replica" mode: that mode's sync protocol was found to
    be rejected by Turso's server at deploy time ("you are using a client
    with a deprecated version of sync, that is not supported on this
    platform"), which left every query against a half-initialized local
    replica file failing with confusing sqlite3-level errors. The HTTPS API
    used here is the same one the one-off migration script
    (scripts/migrate_to_turso.py, run manually, not part of the deployed
    app) used to push 656K+ rows into Turso successfully, so it's proven
    against this exact database, not just documented.

  - Neither set (local development, or any host with a real persistent
    disk): behaves exactly as before, a plain local sqlite3 file. Nothing
    changes for that deployment path.

Every write over the Turso path is already durable the moment execute()
returns (Turso's HTTP API has no local buffering to flush) — commit() is a
no-op kept only so call sites written against sqlite3's API don't need an
if/else for which backend they're on.

Row access: every row returned from this module's connection is a plain
dict (both row["col"] and row.get("col") work) on both the sqlite3 and Turso
paths, via a custom row_factory / cursor implementation — deliberately NOT
sqlite3.Row specifically, since many call sites already do dict(row) or
row.get(...) directly.
"""

import os
import sqlite3
import threading
import time

LIBSQL_URL = os.getenv("LIBSQL_URL")
LIBSQL_AUTH_TOKEN = os.getenv("LIBSQL_AUTH_TOKEN")
LOCAL_REPLICA_PATH = os.getenv("PSX_DB", "psx_v2.db")

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


# --------------------------------------------------------- Turso HTTP path --
def _decode_cell(cell):
    t = cell.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(cell["value"])
    if t == "float":
        return float(cell["value"])
    if t == "text":
        return cell["value"]
    if t == "blob":
        import base64
        return base64.b64decode(cell["base64"])
    return cell.get("value")


def _encode_arg(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, bytes):
        import base64
        return {"type": "blob", "base64": base64.b64encode(v).decode()}
    return {"type": "text", "value": str(v)}


class _TursoCursor:
    """Minimal DB-API-shaped cursor backed by one Hrana "execute" result —
    just enough of sqlite3.Cursor's surface for how this codebase uses it:
    execute/executemany, fetchone/fetchall/fetchmany, iteration, lastrowid."""

    def __init__(self, conn):
        self._conn = conn
        self._rows = []
        self._idx = 0
        self.description = None
        self.lastrowid = None
        self.rowcount = -1

    def execute(self, sql, params=()):
        self._load(self._conn._run_one(sql, params))
        return self

    def executemany(self, sql, seq_of_params):
        result = None
        for params in seq_of_params:
            result = self._conn._run_one(sql, params)
        if result is not None:
            self._load(result)
        return self

    def _load(self, result):
        cols = [c["name"] for c in result.get("cols", [])]
        self.description = [(c, None, None, None, None, None, None) for c in cols] if cols else None
        self._rows = [_Row(zip(cols, [_decode_cell(v) for v in r])) for r in result.get("rows", [])]
        self._idx = 0
        last_id = result.get("last_insert_rowid")
        self.lastrowid = int(last_id) if last_id is not None else None
        self.rowcount = result.get("affected_row_count", -1)

    def fetchone(self):
        if self._idx < len(self._rows):
            row = self._rows[self._idx]
            self._idx += 1
            return row
        return None

    def fetchall(self):
        rows = self._rows[self._idx:]
        self._idx = len(self._rows)
        return rows

    def fetchmany(self, size=1):
        rows = self._rows[self._idx:self._idx + size]
        self._idx += len(rows)
        return rows

    def __iter__(self):
        return iter(self._rows[self._idx:])


class _TursoConnection:
    """Minimal DB-API-shaped connection that executes every statement
    directly over Turso's HTTPS pipeline API — see module docstring for why
    this replaces the `libsql` package's embedded-replica mode."""

    def __init__(self, http_url, token):
        self._http_url = http_url
        self._headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        import requests
        self._session = requests.Session()
        self._requests = requests
        self.row_factory = None  # unused; kept only for API parity with sqlite3.Connection

    def _post(self, reqs, max_retries=4):
        last_exc = None
        for attempt in range(1, max_retries + 1):
            try:
                r = self._session.post(self._http_url, json={"requests": reqs},
                                        headers=self._headers, timeout=60)
                r.raise_for_status()
                return r.json()
            except self._requests.exceptions.RequestException as e:
                last_exc = e
                if attempt == max_retries:
                    break
                time.sleep(min(2 ** attempt, 10))
        raise sqlite3.OperationalError(f"Turso HTTP request failed: {last_exc}")

    def _run_one(self, sql, params=()):
        stmt = {"sql": sql}
        if params:
            stmt["args"] = [_encode_arg(p) for p in params]
        data = self._post([{"type": "execute", "stmt": stmt}])
        res = data["results"][0]
        if res.get("type") == "error":
            raise sqlite3.OperationalError(res["error"].get("message", "Turso error"))
        return res["response"]["result"]

    def execute(self, sql, params=()):
        return _TursoCursor(self).execute(sql, params)

    def executemany(self, sql, seq_of_params):
        return _TursoCursor(self).executemany(sql, seq_of_params)

    def executescript(self, script):
        # This codebase's executescript() calls are simple CREATE TABLE/INDEX
        # blocks with no semicolons inside string literals, so a naive split
        # is safe here (Turso's HTTP API takes one statement per "execute").
        stmts = [s.strip() for s in script.split(";") if s.strip()]
        if not stmts:
            return
        data = self._post([{"type": "execute", "stmt": {"sql": s}} for s in stmts])
        for res in data["results"]:
            if res.get("type") == "error":
                raise sqlite3.OperationalError(res["error"].get("message", "Turso error"))

    def commit(self):
        pass  # every statement above is already durable the moment it returns

    def cursor(self):
        return _TursoCursor(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False  # nothing buffered to roll back; let exceptions propagate


def _make_connection():
    if USING_TURSO:
        http_url = LIBSQL_URL.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
        conn = _TursoConnection(http_url, LIBSQL_AUTH_TOKEN)
        conn.execute("SELECT 1")  # fail fast here if the URL/token are wrong
        return conn
    # check_same_thread=False: this connection is now a shared, process-wide
    # singleton (get_connection() below), reused across FastAPI's request
    # threadpool AND the background refresh-loop threads — sqlite3's default
    # same-thread check rejects exactly that, since every prior call site
    # used to get a brand-new connection per call instead of sharing one.
    # WAL mode + every caller's existing timeout=30/retry handling is what
    # actually keeps concurrent access safe; this flag just stops sqlite3
    # from refusing legitimate cross-thread use of that one connection.
    conn = sqlite3.connect(LOCAL_REPLICA_PATH, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = _row_factory
    return conn


def get_connection():
    """Return the shared, process-wide database connection, creating it on
    first use. Callers still manage their own transactions/commits exactly
    as before (this only replaces how the connection itself is obtained)."""
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


def status():
    """For /health — never crashes, always reports what's actually true."""
    return {"backend": "turso (HTTP pipeline)" if USING_TURSO else "local sqlite3",
            "connected": _shared_conn is not None,
            "init_error": _init_error}
