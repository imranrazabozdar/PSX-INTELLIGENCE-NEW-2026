"""Minimal, dependency-light DB access for the fundamental engine (independent of the technical engine).

Two interchangeable backends with the same interface:
    TursoClient(url, token)  - Turso over HTTPS (/v2/pipeline); token normally injected by a proxy or env
    sqlite_connect(path)     - local/in-memory SQLite (tests, offline work)
Both return rows as dicts and expose .execute(sql, params) -> Result(rows, lastrowid, rowcount)
and .batch(statements) (atomic).
"""
import os
import sqlite3
from dataclasses import dataclass, field

import requests


@dataclass
class Result:
    rows: list = field(default_factory=list)
    lastrowid: int | None = None
    rowcount: int = -1

    def one(self):
        return self.rows[0] if self.rows else None


def _enc(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def _dec(cell):
    t, v = cell.get("type"), cell.get("value")
    if t == "null":
        return None
    if t == "integer":
        return int(v)
    if t == "float":
        return float(v)
    return v


class TursoClient:
    def __init__(self, url=None, token=None, timeout=30):
        url = url or os.getenv("LIBSQL_URL", "")
        if not url:
            raise RuntimeError("LIBSQL_URL is not set")
        self.endpoint = url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
        self.token = token or os.getenv("LIBSQL_AUTH_TOKEN", "")
        self.timeout = timeout

    def _post(self, stmts):
        reqs = [{"type": "execute", "stmt": {"sql": s, "args": [_enc(a) for a in p]}} for s, p in stmts]
        reqs.append({"type": "close"})
        r = requests.post(self.endpoint, json={"requests": reqs}, timeout=self.timeout,
                          headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        r.raise_for_status()
        out = []
        for item in r.json()["results"][:len(stmts)]:
            if item["type"] == "error":
                raise sqlite3.OperationalError(item["error"].get("message", "Turso error"))
            res = item["response"]["result"]
            cols = [c["name"] for c in res.get("cols", [])]
            rid = res.get("last_insert_rowid")
            out.append(Result([dict(zip(cols, (_dec(c) for c in row))) for row in res.get("rows", [])],
                              int(rid) if rid is not None else None, res.get("affected_row_count", -1)))
        return out

    def execute(self, sql, params=()):
        return self._post([(sql, tuple(params))])[0]

    def batch(self, statements):
        """Atomic: BEGIN ... COMMIT on one stream; any error aborts (Turso rolls the stream back on close)."""
        stmts = [("BEGIN", ())] + [(s, tuple(p)) for s, p in statements] + [("COMMIT", ())]
        return self._post(stmts)[1:-1]

    def commit(self):  # interface parity with sqlite wrapper (every execute is auto-committed)
        pass


class SqliteClient:
    def __init__(self, path=":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = lambda cur, row: {d[0]: v for d, v in zip(cur.description, row)}
        self.conn.execute("PRAGMA foreign_keys=ON")

    def execute(self, sql, params=()):
        cur = self.conn.execute(sql, tuple(params))
        return Result(cur.fetchall() if cur.description else [], cur.lastrowid, cur.rowcount)

    def batch(self, statements):
        out = []
        try:
            for s, p in statements:
                out.append(self.execute(s, p))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return out

    def script(self, sql):
        self.conn.executescript(sql)

    def commit(self):
        self.conn.commit()


def sqlite_connect(path=":memory:"):
    return SqliteClient(path)
