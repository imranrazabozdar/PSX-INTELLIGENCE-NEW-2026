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

import json
import os
import sqlite3
import threading
import time

LIBSQL_URL = os.getenv("LIBSQL_URL")
LIBSQL_AUTH_TOKEN = os.getenv("LIBSQL_AUTH_TOKEN")
LOCAL_REPLICA_PATH = os.getenv("PSX_DB", "psx_v2.db")

USING_TURSO = bool(LIBSQL_URL and LIBSQL_AUTH_TOKEN)

_lock = threading.Lock()
_shared_conn = None  # Turso (HTTP) path only — see get_connection()
_init_error = None
_on_local_fallback = False  # True only when USING_TURSO but currently serving
                             # the local-sqlite fallback after a connect failure
_last_fallback_retry = 0.0
_FALLBACK_RETRY_INTERVAL = 30  # seconds between attempts to reconnect to Turso
                                # while stuck on the fallback
_local = threading.local()  # plain-sqlite3 path: one connection per thread


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


# ------------------------------------------------------ usage accounting --
# Turso bills rows READ (rows scanned, not rows returned) and rows WRITTEN,
# and its HTTP pipeline reports both per statement. Aggregated here by SQL
# shape so a batch job or the dashboard can say exactly which queries cost
# what, instead of guessing -- the previous account hit its 500M/month read
# cap without anyone being able to see where the reads went.
import re as _re

_usage_lock = threading.Lock()
_usage = {}          # sql shape -> [calls, rows_read, rows_written]
_usage_has_fields = False


def _sql_shape(sql):
    return _re.sub(r"\s+", " ", sql).strip()[:160]


def _account(sql, result):
    global _usage_has_fields
    rr, rw = result.get("rows_read"), result.get("rows_written")
    if rr is not None or rw is not None:
        _usage_has_fields = True
    with _usage_lock:
        u = _usage.setdefault(_sql_shape(sql), [0, 0, 0])
        u[0] += 1
        u[1] += int(rr or 0)
        u[2] += int(rw or 0)


def usage_report(top=15):
    with _usage_lock:
        items = sorted(_usage.items(), key=lambda kv: -kv[1][1])
    return {
        "reported_by_turso": _usage_has_fields,
        "calls": sum(v[0] for _, v in items),
        "rows_read": sum(v[1] for _, v in items),
        "rows_written": sum(v[2] for _, v in items),
        "top_by_rows_read": [{"sql": k, "calls": v[0], "rows_read": v[1], "rows_written": v[2]}
                             for k, v in items[:top]],
    }


def print_usage_report(label=None, top=15):
    r = usage_report(top)
    if not r["calls"]:
        return
    tag = label or os.path.basename(__import__("sys").argv[0] or "process")
    print(f"\n[turso usage] {tag}: {r['calls']} statements, "
          f"{r['rows_read']:,} rows read, {r['rows_written']:,} rows written"
          + ("" if r["reported_by_turso"] else " (Turso did not report row counts)"))
    for q in r["top_by_rows_read"]:
        print(f"  {q['rows_read']:>12,} read  {q['rows_written']:>10,} written  "
              f"{q['calls']:>6}x  {q['sql']}")


if os.getenv("PSX_TURSO_USAGE_REPORT"):
    import atexit as _atexit
    _atexit.register(print_usage_report)


# ------------------------------------------------- daily_ohlc snapshot --
# The GitHub Actions refresh job runs ~9 Python steps that each re-read all
# of daily_ohlc from Turso (SELECT DISTINCT symbol + every symbol's full
# history, or a whole-table window query) -- measured 2026-09-27 at ~3.2M
# rows read per run. When PSX_DAILY_OHLC_SNAPSHOT names an existing local
# SQLite file (written once per job by snapshot_daily_ohlc.py, right after
# the OHLC refresh step), read-only statements that touch ONLY daily_ohlc
# are answered from that file instead. Any write to daily_ohlc in the same
# process turns routing off, so a process never reads its own stale copy.
_SNAPSHOT_PATH = os.getenv("PSX_DAILY_OHLC_SNAPSHOT")
_snapshot = {"conn": None, "disabled": False}
_snapshot_lock = threading.Lock()
_TABLE_REF = _re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_]\w*)", _re.I)
_CTE_NAME = _re.compile(r"(?:\bWITH|,)\s*([A-Za-z_]\w*)\s+AS\s*\(", _re.I)


def _snapshot_eligible(sql):
    head = sql.lstrip()[:4].upper()
    if head not in ("SELE", "WITH"):
        if "DAILY_OHLC" in sql.upper():
            _snapshot["disabled"] = True
        return False
    ctes = {n.lower() for n in _CTE_NAME.findall(sql)}
    tables = {t.lower() for t in _TABLE_REF.findall(sql)} - ctes
    return tables == {"daily_ohlc"}


def _snapshot_result(sql, params):
    """Hrana-shaped result from the local snapshot, or None to go to Turso."""
    if not _SNAPSHOT_PATH or _snapshot["disabled"] or not _snapshot_eligible(sql):
        return None
    with _snapshot_lock:
        if _snapshot["conn"] is None:
            if not os.path.exists(_SNAPSHOT_PATH):
                return None
            _snapshot["conn"] = sqlite3.connect(f"file:{_SNAPSHOT_PATH}?mode=ro", uri=True,
                                                check_same_thread=False)
            print(f"[turso_db] daily_ohlc reads served from local snapshot {_SNAPSHOT_PATH}")
        cur = _snapshot["conn"].execute(sql, tuple(params or ()))
        rows = cur.fetchall()
    cols = [d[0] for d in (cur.description or [])]
    return {"cols": [{"name": c} for c in cols],
            "rows": [[_encode_arg(v) for v in r] for r in rows],
            "affected_row_count": 0, "last_insert_rowid": None}


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
        self._query_cache = {}  # (sql, params) -> (timestamp, result)

    _debug_call_count = 0

    def _post(self, reqs, max_retries=4):
        _TursoConnection._debug_call_count += 1
        if os.getenv("PSX_DEBUG_TURSO_CALLS"):
            import traceback
            stack = traceback.extract_stack()
            for frame in reversed(stack[:-1]):
                if "turso_db.py" not in frame.filename:
                    print(f"[turso_db DEBUG] call #{_TursoConnection._debug_call_count} from "
                          f"{frame.filename.split(chr(92))[-1]}:{frame.lineno} ({frame.name})")
                    break
        # Encode the body ourselves as ASCII-safe bytes (json.dumps defaults
        # to ensure_ascii=True, escaping every non-ASCII character as \uXXXX)
        # and send via data= instead of requests' json= convenience param.
        # This app's data legitimately contains non-ASCII text (company/
        # sector names, news headlines) — passing that through json= hit a
        # 'latin-1' codec UnicodeEncodeError somewhere in requests/urllib3's
        # header/body handling on Streamlit Cloud's runtime; encoding to
        # plain ASCII ourselves up front sidesteps it entirely.
        payload = json.dumps({"requests": reqs}, ensure_ascii=True).encode("ascii")
        last_exc = None
        for attempt in range(1, max_retries + 1):
            try:
                r = self._session.post(self._http_url, data=payload,
                                        headers=self._headers, timeout=60)
                r.raise_for_status()
                return r.json()
            except self._requests.exceptions.RequestException as e:
                last_exc = e
                if attempt == max_retries:
                    break
                time.sleep(min(2 ** attempt, 10))
        raise sqlite3.OperationalError(f"Turso HTTP request failed: {last_exc}")

    _QUERY_CACHE_TTL = 8  # seconds

    def _run_one(self, sql, params=()):
        # Many call sites across this codebase independently re-fetch the
        # exact same (sql, params) within one request -- e.g. a scoring pass
        # and an audit pass both asking for the same symbol's indicator
        # stats a few lines apart. Free with local sqlite3; a real Turso
        # round trip once db() started talking over HTTP. A short cache on
        # this one shared low-level path catches that pattern generically,
        # without hand-auditing every caller across a dozen files. Only
        # SELECTs are eligible -- a write must never be served from cache or
        # silently deduped.
        local = _snapshot_result(sql, params)
        if local is not None:
            return local
        is_select = sql.lstrip()[:6].upper() == "SELECT"
        cache_key = (sql, tuple(params)) if is_select else None
        if cache_key is not None:
            cached = self._query_cache.get(cache_key)
            if cached and (time.time() - cached[0]) < self._QUERY_CACHE_TTL:
                return cached[1]
        stmt = {"sql": sql}
        if params:
            stmt["args"] = [_encode_arg(p) for p in params]
        data = self._post([{"type": "execute", "stmt": stmt}])
        res = data["results"][0]
        if res.get("type") == "error":
            raise sqlite3.OperationalError(res["error"].get("message", "Turso error"))
        result = res["response"]["result"]
        _account(sql, result)
        if cache_key is not None:
            if len(self._query_cache) > 5000:  # crude cap against unbounded
                self._query_cache.clear()       # growth over a long-lived process
            self._query_cache[cache_key] = (time.time(), result)
        return result

    def execute(self, sql, params=()):
        return _TursoCursor(self).execute(sql, params)

    def executemany(self, sql, seq_of_params):
        return _TursoCursor(self).executemany(sql, seq_of_params)

    def batch_query(self, queries):
        """queries: list of (sql, params) tuples. Sends them all as ONE HTTP
        request (Hrana lets one pipeline call carry many "execute" ops) and
        returns a list of row-lists in the same order -- for hot paths that
        run several independent, unrelated SELECTs (e.g. /health checking N
        cache keys, or a peer-comparison loop fetching N symbols' history)
        where the bottleneck is round-trip count, not any single query."""
        local = [_snapshot_result(sql, params) for sql, params in queries]
        remote = [q for q, r in zip(queries, local) if r is None]
        reqs = []
        for sql, params in remote:
            stmt = {"sql": sql}
            if params:
                stmt["args"] = [_encode_arg(p) for p in params]
            reqs.append({"type": "execute", "stmt": stmt})
        remote_results = iter(self._post(reqs)["results"] if reqs else [])
        out = []
        for (sql, _), result in zip(queries, local):
            if result is None:
                res = next(remote_results)
                if res.get("type") == "error":
                    raise sqlite3.OperationalError(res["error"].get("message", "Turso error"))
                result = res["response"]["result"]
                _account(sql, result)
            cols = [c["name"] for c in result.get("cols", [])]
            rows = [_Row(zip(cols, [_decode_cell(v) for v in r])) for r in result.get("rows", [])]
            out.append(rows)
        return out

    def executescript(self, script):
        # This codebase's executescript() calls are simple CREATE TABLE/INDEX
        # blocks with no semicolons inside string literals, so a naive split
        # is safe here (Turso's HTTP API takes one statement per "execute").
        stmts = [s.strip() for s in script.split(";") if s.strip()]
        if not stmts:
            return
        data = self._post([{"type": "execute", "stmt": {"sql": s}} for s in stmts])
        for s, res in zip(stmts, data["results"]):
            if res.get("type") == "error":
                raise sqlite3.OperationalError(res["error"].get("message", "Turso error"))
            _account(s, res["response"]["result"])

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
        # Retry the initial handshake a few times before giving up -- a
        # transient Turso hiccup (e.g. heavy concurrent write load from a
        # backfill job) must not permanently strand this process on an
        # empty local SQLite fallback for the rest of its life (see
        # get_connection()'s retry-on-cooldown logic, which depends on this
        # actually succeeding once conditions clear).
        last_exc = None
        for attempt in range(1, 4):
            try:
                conn.execute("SELECT 1")  # fail fast here if the URL/token are wrong
                return conn
            except Exception as e:
                last_exc = e
                if attempt < 3:
                    time.sleep(2 * attempt)
        raise last_exc
    conn = _make_local_sqlite_connection()
    return conn


class _LocalSqliteConnection(sqlite3.Connection):
    """sqlite3.Connection subclass adding batch_query() for API parity with
    _TursoConnection. Needed because USING_TURSO callers across app.py,
    backtest_engine.py, scan_cache_engine.py etc. call conn.batch_query(...)
    unconditionally whenever Turso creds are configured -- but get_connection()
    can still hand back this local-fallback connection instead (Turso
    unreachable, e.g. a free-tier quota block), and a plain sqlite3.Connection
    has no such method. Without this, every one of those call sites raised
    AttributeError on every request while stuck on the fallback, turning a
    read-quota block into a total outage instead of a degraded one."""

    def batch_query(self, queries):
        return [self.execute(sql, params).fetchall() for sql, params in queries]


def _make_local_sqlite_connection():
    # A single sqlite3.Connection object is NOT safe to call concurrently
    # from multiple threads -- check_same_thread=False only disables
    # Python's thread-identity guard, it does not serialize access to the
    # connection handle itself. FastAPI runs sync endpoints in a thread
    # pool, and this dashboard fires many concurrent requests, so sharing
    # one connection across threads produced real, intermittent
    # "sqlite3.InterfaceError: bad parameter or other API misuse" failures
    # (seen mid-scan in advanced_pattern_scan, discover_edges, watchlist_scan).
    # WAL mode is what actually makes concurrent access safe -- but only
    # across SEPARATE connections to the same file, one per thread, which
    # is what get_connection() now hands out.
    conn = sqlite3.connect(LOCAL_REPLICA_PATH, timeout=30, check_same_thread=False,
                            factory=_LocalSqliteConnection)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = _row_factory
    return conn


class QueryMetrics:
    """Track query performance and patterns for optimization."""
    def __init__(self):
        self.total_queries = 0
        self.total_rows_read = 0
        self.total_rows_written = 0
        self.batch_queries = 0
        self.query_times = []
        self.queries_by_type = {}

    def record_query(self, query_type: str, rows_affected: int, exec_time: float):
        """Record metrics for a single query."""
        self.total_queries += 1
        self.total_rows_read += rows_affected
        self.queries_by_type[query_type] = self.queries_by_type.get(query_type, 0) + 1
        self.query_times.append(exec_time)

    def record_batch(self, count: int):
        """Record a batch query."""
        self.batch_queries += 1
        self.total_queries += count


_query_metrics = QueryMetrics()


def get_connection():
    """Return this thread's database connection, creating it on first use.
    Turso (HTTP) path: one shared connection is fine -- each call is a
    stateless HTTPS round trip, not a handle to serialize access to.
    Plain-sqlite3 path: one connection PER THREAD (see
    _make_local_sqlite_connection) -- WAL mode makes that safe for
    concurrent access; a single shared handle is not.
    Callers still manage their own transactions/commits exactly as before
    (this only replaces how the connection itself is obtained)."""
    global _shared_conn, _init_error, _on_local_fallback, _last_fallback_retry
    if USING_TURSO:
        if _shared_conn is None:
            with _lock:
                if _shared_conn is None:
                    try:
                        _shared_conn = _make_connection()
                        _on_local_fallback = False
                    except Exception as e:
                        _init_error = f"{type(e).__name__}: {e}"
                        print(f"[turso_db] Turso connection failed ({_init_error}) — "
                              f"falling back to a plain local SQLite file. Data will "
                              f"NOT persist across restarts on a host with no disk "
                              f"(e.g. Streamlit Community Cloud) until this is fixed.")
                        _shared_conn = _make_local_sqlite_connection()
                        _on_local_fallback = True
                        _last_fallback_retry = time.time()
        elif _on_local_fallback and (time.time() - _last_fallback_retry) > _FALLBACK_RETRY_INTERVAL:
            # Stuck on the local fallback -- periodically try to reconnect
            # to Turso instead of staying pinned to an empty local DB for
            # the rest of this process's life once conditions clear.
            with _lock:
                if _on_local_fallback and (time.time() - _last_fallback_retry) > _FALLBACK_RETRY_INTERVAL:
                    _last_fallback_retry = time.time()
                    try:
                        _shared_conn = _make_connection()
                        _on_local_fallback = False
                        _init_error = None
                        print("[turso_db] Turso connection recovered — switched off the local fallback.")
                    except Exception as e:
                        _init_error = f"{type(e).__name__}: {e}"
        return _shared_conn

    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _make_local_sqlite_connection()
        _local.conn = conn
    return conn


def status():
    """For /health — never crashes, always reports what's actually true.
    `backend` reflects what's ACTUALLY being served right now, not just
    whether Turso env vars are configured -- `on_local_fallback` is the
    critical flag: True means Turso creds are set and USING_TURSO is True,
    but this process is currently serving an empty, non-persistent local
    SQLite file because the last Turso connection attempt failed."""
    if USING_TURSO and _on_local_fallback:
        backend_label = "local sqlite3 (TURSO FALLBACK — configured but unreachable)"
    elif USING_TURSO:
        backend_label = "turso (HTTP pipeline)"
    else:
        backend_label = "local sqlite3"
    return {"backend": backend_label,
            "connected": _shared_conn is not None,
            "using_turso_configured": USING_TURSO,
            "on_local_fallback": bool(USING_TURSO and _on_local_fallback),
            "init_error": _init_error}


# ============================================================================
# TURSO OPTIMIZATION HELPERS
# ============================================================================

def batch_select_by_id(table: str, id_column: str, ids: list, limit=None):
    """Optimized batch SELECT for a list of IDs - single HTTP round trip.

    Example: batch_select_by_id("daily_ohlc", "symbol", ["ABC", "XYZ"])
    Returns: {"ABC": [...rows...], "XYZ": [...rows...]}
    """
    if not ids:
        return {}

    conn = get_connection()
    id_list = list(dict.fromkeys(ids))  # de-dupe, keep order

    queries = []
    for id_val in id_list:
        sql = f"SELECT * FROM {table} WHERE {id_column} = ?"
        if limit:
            sql += f" LIMIT {limit}"
        queries.append((sql, (id_val,)))

    results = conn.batch_query(queries) if USING_TURSO else [c.execute(sql, params).fetchall() for sql, params in queries]

    out = {}
    for id_val, rows in zip(id_list, results):
        out[id_val] = [dict(r) for r in rows]

    _query_metrics.record_batch(len(queries))
    return out


def batch_select_with_filter(table: str, filters: list):
    """Batch SELECT with different WHERE conditions - single HTTP round trip.

    Example: batch_select_with_filter("daily_ohlc", [
        ("symbol=? ORDER BY trade_date DESC LIMIT 260", ("ABC",)),
        ("symbol=? ORDER BY trade_date DESC LIMIT 260", ("XYZ",))
    ])
    """
    if not filters:
        return []

    conn = get_connection()

    queries = [(f"SELECT * FROM {table} WHERE {cond}", params) for cond, params in filters]
    results = conn.batch_query(queries) if USING_TURSO else [c.execute(sql, params).fetchall() for sql, params in queries]

    out = []
    for rows in results:
        out.append([dict(r) for r in rows])

    _query_metrics.record_batch(len(queries))
    return out


def get_query_metrics():
    """Return current query metrics and reset counters."""
    global _query_metrics

    metrics = {
        "total_queries": _query_metrics.total_queries,
        "batch_queries": _query_metrics.batch_queries,
        "total_rows_read": _query_metrics.total_rows_read,
        "queries_by_type": dict(_query_metrics.queries_by_type),
        "avg_query_time_ms": round(sum(_query_metrics.query_times) / len(_query_metrics.query_times), 2) if _query_metrics.query_times else 0
    }

    # Reset for next cycle
    _query_metrics = QueryMetrics()

    return metrics
