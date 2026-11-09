"""PILOT-2026-11-09-04 ingestion (OWNER OVERRIDE for factual metadata; see docs/SOURCE_PERMISSION_LOG.md).

Ties together: polite honest fetch (investify_pilot) -> pure parser (investify_parser) -> source_items mapping.
Stores ONLY public facts (ticker, timestamp, category, title, PSX filing id). Never fetches PDFs or linked pages,
never stores Investify's summaries/sentiment. Unmapped tickers are stored unlinked (no guessing).

    python backend/investify_ingester.py --html-file page.html --dry-run   # offline input, read-only DB check
    python backend/investify_ingester.py --dry-run                         # live fetch (<=2 requests), read-only DB check
    python backend/investify_ingester.py --live                            # live fetch + INSERT OR IGNORE into Turso
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

try:
    import investify_parser as parser
    import investify_pilot as pilot
except ImportError:  # imported as backend.<module>
    from backend import investify_parser as parser, investify_pilot as pilot

JOB = "investify_announcements"
MAX_ROWS_PER_RUN = 60  # free-tier write guard


class IngestError(Exception):
    pass


def _v(row, key):
    """Named column from a dict/sqlite3.Row; falls back to column 0 for plain tuples."""
    try:
        return row[key]
    except (TypeError, IndexError, KeyError):
        return row[0]


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plan(conn, items):
    """Read-only: classify items as new / duplicate / changed against existing source_items."""
    out = {"new": [], "duplicate": [], "changed": []}
    for it in items:
        row = parser.to_source_item(it, "1970-01-01T00:00:00Z")
        ex = conn.execute("SELECT source_item_id, content_sha256 FROM source_items WHERE source_id=? AND external_id=?",
                          (parser.SOURCE_ID, row["external_id"])).fetchone()
        if ex is None:
            out["new"].append(it)
        elif _v(ex, "content_sha256") == row["content_sha256"]:
            out["duplicate"].append(it)
        else:
            out["changed"].append((it, _v(ex, "source_item_id")))
    return out


def _count(conn):
    return _v(conn.execute("SELECT COUNT(*) AS n FROM source_items WHERE source_id=?", (parser.SOURCE_ID,)).fetchone(), "n")


def ingest(conn, items, http_requests=0, now=None):
    if len(items) > MAX_ROWS_PER_RUN:
        raise IngestError(f"{len(items)} items exceeds per-run guard {MAX_ROWS_PER_RUN}")
    if not conn.execute("SELECT 1 FROM sources WHERE source_id=?", (parser.SOURCE_ID,)).fetchone():
        raise IngestError("source 'investify' missing")
    p = plan(conn, items)
    stamp = now or _now()
    run_id = conn.execute(
        "INSERT INTO collector_runs(job,source_id,started_at_utc,status,http_requests,log_reference) VALUES(?,?,?,?,?,?)",
        (JOB, parser.SOURCE_ID, stamp, "running", http_requests, pilot.APPROVAL_ID)).lastrowid
    before = _count(conn)
    cols = None
    batch = []
    for it in p["new"]:
        row = parser.to_source_item(it, stamp, run_id)
        cols = cols or list(row)
        batch.append([row[c] for c in cols])
    if batch:
        conn.executemany(f"INSERT OR IGNORE INTO source_items({','.join(cols)}) VALUES({','.join('?' * len(cols))})", batch)
    inserted = _count(conn) - before
    # version 1 for each newly inserted item, appended; a changed hash appends the next version
    for it in p["new"]:
        row = parser.to_source_item(it, stamp, run_id)
        sid = conn.execute("SELECT source_item_id FROM source_items WHERE source_id=? AND external_id=?",
                           (parser.SOURCE_ID, row["external_id"])).fetchone()
        if sid is not None:
            conn.execute("INSERT OR IGNORE INTO source_item_versions(source_item_id,version_no,content_sha256,"
                         "collected_at_utc,collection_run_id,title) VALUES(?,?,?,?,?,?)",
                         (_v(sid, "source_item_id"), 1, row["content_sha256"], stamp, run_id, row["title"]))
    for it, sid in p["changed"]:
        row = parser.to_source_item(it, stamp, run_id)
        mx = _v(conn.execute("SELECT COALESCE(MAX(version_no),0) AS n FROM source_item_versions WHERE source_item_id=?",
                             (sid,)).fetchone(), "n")
        conn.execute("INSERT OR IGNORE INTO source_item_versions(source_item_id,version_no,content_sha256,"
                     "collected_at_utc,collection_run_id,title) VALUES(?,?,?,?,?,?)",
                     (sid, mx + 1, row["content_sha256"], stamp, run_id, row["title"]))
    conn.execute("UPDATE collector_runs SET finished_at_utc=?,status='succeeded',items_fetched=?,items_accepted=?,"
                 "items_duplicate=?,items_new_version=? WHERE run_id=?",
                 (_now(), len(items), inserted, len(p["duplicate"]), len(p["changed"]), run_id))
    conn.commit()
    return {"parsed": len(items), "inserted": inserted, "duplicates": len(p["duplicate"]),
            "new_versions": len(p["changed"]), "run_id": run_id}


def get_html(args):
    if args.html_file:
        return open(args.html_file, encoding="utf-8").read(), 0
    budget = pilot.Budget()
    url = "https://www.investify.pk/announcements"
    try:
        if not pilot.allowed_by_robots(url, budget):
            raise IngestError("robots.txt disallows the page")
        return pilot.polite_get(url, budget).text, budget.used
    except pilot.Blocked as e:
        raise IngestError(f"BLOCKED: {e}; not retrying, no bypass")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--live", action="store_true")
    ap.add_argument("--html-file", help="parse a saved page instead of fetching (no Investify request)")
    a = ap.parse_args(argv)
    try:
        html, used = get_html(a)
        items = parser.parse_announcements(html)
        print(f"parsed {len(items)} announcements (requests to Investify: {used})")
        try:
            from backend import turso_db
        except ImportError:
            import turso_db
        if not turso_db.USING_TURSO:
            raise IngestError("Turso not configured; refusing (would use local SQLite)")
        conn = turso_db.get_connection()
        if isinstance(conn, sqlite3.Connection):
            raise IngestError("Turso connection failed (local fallback); refusing")
        if a.dry_run:
            p = plan(conn, items)
            print({"would_insert": len(p["new"]), "duplicates": len(p["duplicate"]), "changed": len(p["changed"])})
            for it in p["new"][:5]:
                print("  new:", it["ticker"], it["timestamp_utc"], it["category"], "|", it["title"][:60], "| psx_filing:" + it["psx_id"])
            return 0
        print(ingest(conn, items, used))
        return 0
    except IngestError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 3
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
