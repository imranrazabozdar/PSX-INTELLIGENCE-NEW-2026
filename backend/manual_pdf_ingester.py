"""Manual / seed PDF ingestion: copy one local PDF into the document vault and record
its provenance in source_items (append-only). No network access.

    python backend/manual_pdf_ingester.py FILE.pdf --source-id psx \
        [--published-date YYYY-MM-DD] [--title T] [--original-url U] [--category announcements] \
        [--ack-terms] [--dry-run]

Vault layout (root = DOCUMENT_VAULT_PATH, see docs/DOCUMENT_VAULT.md):
    <root>/<category>/YYYY/MM/<sha256[:12]>_<safe-name>.pdf
source_items.content_location stores the path RELATIVE to the root.
"""
import argparse
import hashlib
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

CATEGORIES = ("announcements", "financial_reports", "other")
MAX_BYTES = 50 * 1024 * 1024
APPROVED_ACCESS = ("verified_permitted",)  # other sources need --ack-terms
ACCESS_STATUS = "permitted"  # source_items CHECK allows public/permitted/restricted/unavailable only


class IngestError(Exception):
    pass


def vault_root(env=None):
    env = os.environ if env is None else env
    v = env.get("DOCUMENT_VAULT_PATH", "").strip()
    if not v:
        raise IngestError("DOCUMENT_VAULT_PATH is not set (put it in .env; see backend/.env.example)")
    root = Path(v).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_name(name):
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).stem).strip("._") or "document"
    return stem[:80] + ".pdf"


def relative_path(category, year, month, digest, filename):
    return f"{category}/{year:04d}/{month:02d}/{digest[:12]}_{safe_name(filename)}"


def _val(row, key):
    return row[key] if isinstance(row, dict) else row[0]


def ingest(conn, src, source_id, root, *, category="announcements", published_date=None,
           title=None, original_url=None, ack_terms=False, dry_run=False, now=None):
    src = Path(src)
    if not src.is_file():
        raise IngestError(f"not a file: {src}")
    if category not in CATEGORIES:
        raise IngestError(f"category must be one of {CATEGORIES}")
    size = src.stat().st_size
    if size == 0 or size > MAX_BYTES:
        raise IngestError(f"file size {size} outside 1..{MAX_BYTES} bytes")
    with open(src, "rb") as f:
        if f.read(5) != b"%PDF-":
            raise IngestError("file does not start with %PDF- (not a PDF)")
    if published_date:
        try:
            pub = datetime.strptime(published_date, "%Y-%m-%d")
        except ValueError:
            raise IngestError("--published-date must be YYYY-MM-DD")
    else:
        pub = None

    srow = conn.execute("SELECT access_status, terms_status FROM sources WHERE source_id=?", (source_id,)).fetchone()
    if not srow:
        raise IngestError(f"unknown source_id {source_id!r}; sources are not created by this script")
    access = srow["access_status"] if isinstance(srow, dict) else srow[0]
    if access not in APPROVED_ACCESS and not ack_terms:
        raise IngestError(f"source {source_id!r} access_status={access!r}: a manual, owner-supplied file is allowed "
                          "only with --ack-terms (owner confirms they obtained the file themselves, one at a time, "
                          "in line with the source's terms)")

    digest = sha256_file(src)
    external_id = f"sha256:{digest}"
    dup = conn.execute("SELECT source_item_id, content_location FROM source_items WHERE source_id=? AND external_id=?",
                       (source_id, external_id)).fetchone()
    if dup:
        return {"status": "duplicate", "source_item_id": _val(dup, "source_item_id"), "sha256": digest}

    now = now or datetime.now(timezone.utc)
    when = pub or now
    rel = relative_path(category, when.year, when.month, digest, src.name)
    dest = root / rel
    result = {"status": "dry_run" if dry_run else "inserted", "sha256": digest, "content_location": rel}
    if dry_run:
        return result

    dest.parent.mkdir(parents=True, exist_ok=True)
    existed = dest.exists()
    tmp = dest.with_suffix(".part")
    shutil.copy2(src, tmp)
    if sha256_file(tmp) != digest:
        tmp.unlink()
        raise IngestError("copy verification failed (hash mismatch)")
    os.replace(tmp, dest)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        run_id = conn.execute(
            "INSERT INTO collector_runs(job,source_id,started_at_utc,finished_at_utc,status,items_fetched,items_accepted,"
            "log_reference) VALUES('manual_pdf_ingest',?,?,?,'succeeded',1,1,?)",
            (source_id, stamp, stamp, rel)).lastrowid
        item_id = conn.execute(
            "INSERT INTO source_items(source_id,canonical_url,external_id,title,published_at_utc,published_at_raw,"
            "event_date,collected_at_utc,content_sha256,content_location,access_status,original_url,"
            "retrieval_method,collection_run_id,document_type,publication_time_status,source_metadata_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'manual',?,'pdf',?,json(?))",
            (source_id, original_url, external_id, title or src.stem,
             (published_date + "T00:00:00Z") if pub else None, published_date, published_date,
             stamp, digest, rel, ACCESS_STATUS, original_url, run_id,
             "date_only" if pub else "unknown",
             '{"ingest":"manual_pdf_ingester","original_filename":%s,"size_bytes":%d}'
             % (__import__("json").dumps(src.name), size))).lastrowid
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        if not existed:
            dest.unlink(missing_ok=True)
        raise
    result.update(source_item_id=item_id, collection_run_id=run_id)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--source-id", required=True)
    ap.add_argument("--category", default="announcements", choices=CATEGORIES)
    ap.add_argument("--published-date")
    ap.add_argument("--title")
    ap.add_argument("--original-url")
    ap.add_argument("--ack-terms", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    try:
        root = vault_root()
        try:
            from backend import turso_db
        except ImportError:
            import turso_db
        conn = turso_db.get_connection()
        if isinstance(conn, sqlite3.Connection) and os.getenv("LIBSQL_URL"):
            raise IngestError("Turso connection failed (local fallback); refusing to write")
        out = ingest(conn, a.pdf, a.source_id, root, category=a.category, published_date=a.published_date,
                     title=a.title, original_url=a.original_url, ack_terms=a.ack_terms, dry_run=a.dry_run)
    except IngestError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
