"""Tiny migration runner. Files: migrations/NNNN_name.sql (NNNN = integer version).

- 0010_baseline_snapshot.sql stands in for the production migrations 1-10 on FRESH databases only.
- On the live database (schema_migrations already at version >= 10) it is never re-applied.
- Later files (0011+) are applied in order, each recorded with its SHA-256; an already-applied file whose
  checksum changed aborts the run (migrations are immutable once applied).
"""
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

MIG_DIR = Path(__file__).resolve().parent.parent / "migrations"
BASELINE_VERSION = 10


def _files():
    out = []
    for p in sorted(MIG_DIR.glob("*.sql")):
        m = re.match(r"^(\d{4})_([a-z0-9_]+)\.sql$", p.name)
        if m:
            out.append((int(m.group(1)), m.group(2), p))
    return out


def _applied(db):
    try:
        return {r["version"]: r for r in db.execute("SELECT version,name,checksum FROM schema_migrations").rows}
    except Exception:
        return {}


def plan(db):
    applied = _applied(db)
    pending = []
    for ver, name, path in _files():
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if ver == BASELINE_VERSION and applied and max(applied) >= BASELINE_VERSION:
            continue  # database is already at/after the baseline (e.g. the live Turso DB)
        if ver in applied:
            if ver > BASELINE_VERSION and applied[ver]["checksum"] != sha:
                raise RuntimeError(f"migration {ver} {name} changed after being applied")
            continue
        if ver < BASELINE_VERSION:
            continue
        pending.append((ver, name, path, sha))
    return pending


def apply(db, dry_run=False):
    pend = plan(db)
    if dry_run:
        return [(v, n) for v, n, _, _ in pend]
    done = []
    for ver, name, path, sha in pend:
        sql = path.read_text()
        if hasattr(db, "script"):
            db.script(sql)
        elif ver == BASELINE_VERSION:  # the baseline contains hundreds of triggers: apply it to a fresh Turso DB with the libsql shell
            raise RuntimeError("apply the baseline to a fresh Turso DB with the libsql CLI/shell, then re-run")
        else:  # later migrations are split on the explicit marker line, one statement per request
            parts = [x.strip() for x in re.split(r"^-- statement-break\s*$", sql, flags=re.M) if x.strip()]
            db.batch([(x, ()) for x in parts])
        db.execute("INSERT OR IGNORE INTO schema_migrations(version,name,checksum,applied_at_utc,result) VALUES(?,?,?,?,?)",
                   (ver, name, sha, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "applied"))
        db.commit()
        done.append((ver, name))
    return done
