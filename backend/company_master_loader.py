"""Company master expansion loader (design approved by owner 2026-11-09; see docs/COMPANY_MASTER_EXPANSION_PLAN.md).

Default = DRY RUN: validate every profile, compare with Turso (read-only SELECTs), print counts and the rows that
WOULD be written. `--apply` writes at most `--chunk` (default 100) NEW companies per run, resumable (the plan is
recomputed each run, so loaded tickers are skipped). Existing companies are never updated or deleted. Invalid ISINs
are dropped (company kept); the master's sector labels win; unknown sectors leave the company unclassified; no
sectors are ever created.

    python backend/company_master_loader.py data/psx_profiles.json [--no-db]          # dry run
    python backend/company_master_loader.py data/psx_profiles.json --apply [--chunk N] # write one chunk

STUB MODE (iterative, minimal; owner decision 2026-11-09: no fabricated profiles):
    python backend/company_master_loader.py --stubs [--names names.json] [--apply --chunk N]
Registers ONLY tickers that already appear in verified `source_items` (e.g. Investify announcements) and are missing
from the master, and only when a verified company name exists (source_metadata_json.company_name, or an owner-supplied
--names file with an `evidence` note). Stub = ticker + legal name + listing_status 'unknown'; ISIN, sector, fiscal-year
month stay NULL/absent. Tickers without a verified name are listed as `needs_name`, never guessed.
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timezone

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], 1)}
STATUS_MAP = {"active": "listed", "listed": "listed", "delisted": "delisted", "suspended": "suspended"}
TICKER_RE = re.compile(r"^[A-Z0-9]{1,16}$")
DATASET_NAME = "psx_profiles_v1"
SEED_SOURCE_ID = "owner_psx_profiles"   # proposed NEW source row (disabled, unverified); needs owner approval


def isin_valid(isin):
    """ISO 6166: 12 chars, 2-letter country, Luhn check digit over the letters-as-numbers expansion."""
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin or ""):
        return False
    digits = "".join(str(int(ch, 36)) for ch in isin)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return total % 10 == 0


def norm_sector(name):
    s = (name or "").casefold().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def fy_month(text):
    m = re.match(r"\s*([A-Za-z]+)", text or "")
    return MONTHS.get(m.group(1).lower()) if m else None


def validate(rec):
    """Return (clean_dict, [problems]). Nothing is guessed: unknowns stay None and are reported."""
    probs = []
    t = (rec.get("symbol") or "").strip().upper()
    if not TICKER_RE.match(t):
        probs.append("bad_symbol")
    name = re.sub(r"\s+", " ", rec.get("company_name") or "").strip()
    if not name:
        probs.append("missing_company_name")
    status = STATUS_MAP.get((rec.get("listing_status") or "").strip().lower())
    if status is None:
        probs.append("unknown_listing_status")
    isin = (rec.get("isin") or "").strip().upper() or None
    if isin and not isin_valid(isin):
        probs.append("invalid_isin_checksum")
    fym = fy_month(rec.get("fiscal_year_end"))
    if rec.get("fiscal_year_end") and fym is None:
        probs.append("unparseable_fiscal_year_end")
    clean = {"ticker": t, "company_id": f"cmp-{t.lower()}", "legal_name": name, "listing_status": status,
             "sector_raw": (rec.get("sector") or "").strip() or None, "isin": isin if isin and isin_valid(isin) else None,
             "fiscal_year_end_month": fym}
    return clean, probs


def plan(records, existing=None):
    """existing = {'companies': {ticker: {...}}, 'sectors': {norm_name: sector_id}, 'isins': set()} (read-only snapshot)."""
    existing = existing or {"companies": {}, "sectors": {}, "isins": set()}
    out = {"records": len(records), "new": [], "overlap_same": [], "overlap_conflict": [], "rejected": [],
           "duplicate_in_file": [], "sector_unmapped": {}, "isin_new_for_existing": []}
    seen = set()
    for rec in records:
        c, probs = validate(rec)
        hard = [p for p in probs if p != "invalid_isin_checksum"]
        if hard:
            out["rejected"].append((rec.get("symbol"), probs))
            continue
        if c["ticker"] in seen:
            out["duplicate_in_file"].append(c["ticker"])
            continue
        seen.add(c["ticker"])
        if "invalid_isin_checksum" in probs:
            out["rejected"].append((c["ticker"], ["invalid_isin_checksum (ISIN dropped, company kept)"]))
        sid = existing["sectors"].get(norm_sector(c["sector_raw"])) if c["sector_raw"] else None
        c["sector_id"] = sid
        if c["sector_raw"] and sid is None:
            out["sector_unmapped"].setdefault(c["sector_raw"], []).append(c["ticker"])
        ex = existing["companies"].get(c["ticker"])
        if ex is None:
            out["new"].append(c)
            continue
        diffs = {k: (ex.get(k), c[k]) for k in ("legal_name", "listing_status", "fiscal_year_end_month")
                 if c[k] is not None and ex.get(k) != c[k]}
        if c["sector_raw"] and norm_sector(ex.get("sector_name")) != norm_sector(c["sector_raw"]):
            diffs["sector"] = (ex.get("sector_name"), c["sector_raw"])
        (out["overlap_conflict"] if diffs else out["overlap_same"]).append((c["ticker"], diffs))
        if c["isin"] and c["isin"] not in existing["isins"]:
            out["isin_new_for_existing"].append(c["ticker"])
    return out


def row_estimate(p):
    """Rows that WOULD be written for the NEW companies (overlaps are never overwritten)."""
    n = len(p["new"])
    per = {"companies": n, "company_identifiers(psx_ticker)": n,
           "company_identifiers(isin)": sum(1 for c in p["new"] if c["isin"]),
           "company_aliases(ticker+legal_name)": 2 * n,
           "company_classifications": sum(1 for c in p["new"] if c["sector_id"])}
    per["TOTAL (+1 dataset_loads, +1 source, +1 seed item, +runs)"] = sum(per.values()) + 3
    return per


def snapshot(conn):
    q = lambda s: conn.execute(s).fetchall()
    comp = {}
    for r in q("select ci.value t, c.legal_name, c.listing_status, c.fiscal_year_end_month, s.name sector_name "
               "from company_identifiers ci join companies c using(company_id) "
               "left join company_classifications k on k.company_id=c.company_id and k.valid_to is null "
               "left join sectors s on s.sector_id=k.sector_id where ci.id_type='psx_ticker'"):
        comp[r["t"]] = {k: r[k] for k in ("legal_name", "listing_status", "fiscal_year_end_month", "sector_name")}
    return {"companies": comp,
            "sectors": {norm_sector(r["name"]): r["sector_id"] for r in q("select sector_id,name from sectors")},
            "isins": {r["value"] for r in q("select value from company_identifiers where id_type='isin'")}}


def report(p, sha, out=print):
    out(f"file sha256 {sha}")
    out(f"records: {p['records']} | NEW: {len(p['new'])} | overlap identical: {len(p['overlap_same'])} | "
        f"overlap CONFLICTS: {len(p['overlap_conflict'])} | rejected/flagged: {len(p['rejected'])} | "
        f"duplicates in file: {len(p['duplicate_in_file'])}")
    for t, d in p["overlap_conflict"][:15]:
        out(f"  conflict {t}: {d}")
    for raw, tks in sorted(p["sector_unmapped"].items(), key=lambda x: -len(x[1]))[:25]:
        out(f"  sector not in master: {raw!r} -> {len(tks)} companies (e.g. {tks[:3]})")
    for t, pr in p["rejected"][:15]:
        out(f"  rejected/flagged {t}: {pr}")
    out("rows that WOULD be written: " + json.dumps(row_estimate(p)))


# ------------------------------------------------------------------ apply (owner-approved design)
JOB = "company_master_load"
SEED_NOTES = ("Owner-stated origin (2026-11-09): profiles aggregated from publicly available structural listings of the "
              "PSX corporate directory (structural mappings, not restricted individual pages). Not independently verified "
              "by the assistant. Seed/reference dataset only: never fetched by this project; source disabled.")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _v(row, key):
    try:
        return row[key]
    except (TypeError, IndexError, KeyError):
        return row[0]


def ensure_seed(conn, sha, count, now):
    """Create (if missing) the disabled seed source and its dataset seed item. Returns seed source_item_id."""
    if not conn.execute("SELECT 1 FROM sources WHERE source_id=?", (SEED_SOURCE_ID,)).fetchone():
        conn.execute(
            "INSERT INTO sources(source_id,name,source_type,access_method,access_status,enabled,lifecycle_status,"
            "terms_status,verification_status,content_format,retention_mode,notes,created_at_utc,updated_at_utc) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (SEED_SOURCE_ID, "Owner-supplied PSX company profiles (seed dataset)", "other", "manual", "unverified", 0,
             "RESTRICTED", "not_reviewed", "unverified", "unknown", "metadata_only", SEED_NOTES, now, now))
    ext = f"dataset:{DATASET_NAME}:{sha[:16]}"
    row = conn.execute("SELECT source_item_id FROM source_items WHERE source_id=? AND external_id=?",
                       (SEED_SOURCE_ID, ext)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO source_items(source_id,external_id,title,collected_at_utc,content_sha256,access_status,"
            "retrieval_method,document_type,publication_time_status,source_metadata_json) "
            "VALUES(?,?,?,?,?,'restricted','seed','dataset','unavailable',?)",
            (SEED_SOURCE_ID, ext, f"{DATASET_NAME} ({count} records)", now, sha,
             json.dumps({"records": count, "file": "data/psx_profiles.json"})))
        row = conn.execute("SELECT source_item_id FROM source_items WHERE source_id=? AND external_id=?",
                           (SEED_SOURCE_ID, ext)).fetchone()
    return _v(row, "source_item_id")


def apply_chunk(conn, records, sha, chunk=100, now=None):
    """Write up to `chunk` NEW companies. Returns a summary dict. Safe to re-run."""
    now = now or _now()
    existing = snapshot(conn)
    p = plan(records, existing)
    batch = p["new"][:chunk]
    seed = ensure_seed(conn, sha, len(records), now)
    run_id = conn.execute("INSERT INTO collector_runs(job,source_id,started_at_utc,status,log_reference) "
                          "VALUES(?,?,?,'running',?)", (JOB, SEED_SOURCE_ID, now, DATASET_NAME)).lastrowid
    stats = dict(companies=0, isins=0, classifications=0, aliases=0)
    for c in batch:
        conn.execute("INSERT OR IGNORE INTO companies(company_id,legal_name,listing_status,fiscal_year_end_month,"
                     "profile_source_item_id,created_at_utc,updated_at_utc) VALUES(?,?,?,?,?,?,?)",
                     (c["company_id"], c["legal_name"], c["listing_status"], c["fiscal_year_end_month"], seed, now, now))
        stats["companies"] += 1

        def add_ident(id_type, value):  # explicit existence check: UNIQUE(.., valid_from NULL) does not dedupe
            if conn.execute("SELECT 1 FROM company_identifiers WHERE id_type=? AND value=? AND valid_to IS NULL",
                            (id_type, value)).fetchone():
                return 0
            conn.execute("INSERT INTO company_identifiers(company_id,id_type,value,verified_at_utc,source_item_id) "
                         "VALUES(?,?,?,?,?)", (c["company_id"], id_type, value, now, seed))
            return 1
        add_ident("psx_ticker", c["ticker"])
        if c["isin"]:
            stats["isins"] += add_ident("isin", c["isin"])
        for alias, atype in ((c["ticker"], "ticker"), (c["legal_name"], "legal_name")):
            conn.execute("INSERT OR IGNORE INTO company_aliases(company_id,alias,alias_normalized,alias_type,confidence,"
                         "source_item_id,evidence) VALUES(?,?,?,?,'derived',?,?)",
                         (c["company_id"], alias, alias.casefold(), atype, seed, f"seed dataset {DATASET_NAME}"))
            stats["aliases"] += 1
        if c["sector_id"] and not conn.execute(
                "SELECT 1 FROM company_classifications WHERE company_id=? AND sector_id=? AND valid_from IS NULL",
                (c["company_id"], c["sector_id"])).fetchone():
            conn.execute("INSERT INTO company_classifications(company_id,sector_id,verified_at_utc,source_item_id) "
                         "VALUES(?,?,?,?)", (c["company_id"], c["sector_id"], now, seed))
            stats["classifications"] += 1
    remaining = len(p["new"]) - len(batch)
    if remaining == 0 and not conn.execute("SELECT 1 FROM dataset_loads WHERE dataset=?", (DATASET_NAME,)).fetchone():
        conn.execute("INSERT INTO dataset_loads(dataset,sha256,loaded_at_utc,record_count) VALUES(?,?,?,?)",
                     (DATASET_NAME, sha, now, len(records)))
    conn.execute("UPDATE collector_runs SET finished_at_utc=?,status=?,items_fetched=?,items_accepted=? WHERE run_id=?",
                 (_now(), "succeeded" if remaining == 0 else "partial", len(records), len(batch), run_id))
    conn.commit()
    return {**stats, "chunk": len(batch), "remaining_new": remaining, "run_id": run_id,
            "overlap_conflicts_untouched": len(p["overlap_conflict"])}


# ------------------------------------------------------------------ STUB MODE (iterative, verified-only)
STUB_SOURCES = ("investify",)  # sources whose items may seed stubs (owner-approved facts-only ingestion)


def stub_candidates(conn, sources=STUB_SOURCES):
    """Read-only: tickers present in source_items metadata but missing from company_identifiers.
    Returns {ticker: {"items": n, "first_item_id": id, "name": str|None, "sample_title": str}}."""
    ph = ",".join("?" * len(sources))
    rows = conn.execute(
        f"SELECT json_extract(source_metadata_json,'$.ticker') t, json_extract(source_metadata_json,'$.company_name') nm, "
        f"source_item_id, title FROM source_items WHERE source_id IN ({ph}) AND json_extract(source_metadata_json,'$.ticker') IS NOT NULL "
        f"AND json_extract(source_metadata_json,'$.ticker') NOT IN (SELECT value FROM company_identifiers WHERE id_type='psx_ticker') "
        f"ORDER BY source_item_id", tuple(sources)).fetchall()
    out = {}
    for r in rows:
        t = (r["t"] or "").strip().upper()
        if not TICKER_RE.match(t):
            continue
        d = out.setdefault(t, {"items": 0, "first_item_id": r["source_item_id"], "name": None, "sample_title": r["title"]})
        d["items"] += 1
        if r["nm"] and not d["name"]:
            d["name"] = re.sub(r"\s+", " ", r["nm"]).strip() or None
    return out


def plan_stubs(cands, names=None):
    """names = {TICKER: {"company_name":..., "evidence":...}} (owner-verified, optional). Nothing is guessed."""
    names = {k.upper(): v for k, v in (names or {}).items()}
    out = {"creatable": [], "needs_name": []}
    for t, d in sorted(cands.items()):
        nm, ev = d["name"], "source_item metadata"
        if not nm and t in names and (names[t].get("company_name") or "").strip() and (names[t].get("evidence") or "").strip():
            nm, ev = re.sub(r"\s+", " ", names[t]["company_name"]).strip(), names[t]["evidence"].strip()
        if nm:
            out["creatable"].append({"ticker": t, "company_id": f"cmp-{t.lower()}", "legal_name": nm, "evidence": ev,
                                     "source_item_id": d["first_item_id"], "items": d["items"]})
        else:
            out["needs_name"].append({"ticker": t, "items": d["items"], "sample_title": d["sample_title"]})
    return out


def resolution_coverage(conn, add_tickers=()):
    """How many ingested announcements resolve to a company now, and after the planned stubs."""
    total = conn.execute("SELECT COUNT(*) n FROM source_items WHERE source_id='investify'").fetchone()["n"]
    linked = conn.execute(
        "SELECT COUNT(*) n FROM source_items s JOIN company_identifiers ci ON ci.id_type='psx_ticker' "
        "AND ci.value=json_extract(s.source_metadata_json,'$.ticker') WHERE s.source_id='investify'").fetchone()["n"]
    extra = 0
    if add_tickers:
        ph = ",".join("?" * len(add_tickers))
        extra = conn.execute(f"SELECT COUNT(*) n FROM source_items WHERE source_id='investify' AND "
                             f"json_extract(source_metadata_json,'$.ticker') IN ({ph})", tuple(add_tickers)).fetchone()["n"]
    return {"announcements": total, "linked_now": linked, "linked_after_stubs": linked + extra}


def apply_stubs(conn, sp, chunk=100, now=None):
    """Write up to `chunk` creatable stubs. Idempotent; existing companies never touched."""
    now = now or _now()
    batch = sp["creatable"][:chunk]
    run_id = conn.execute("INSERT INTO collector_runs(job,source_id,started_at_utc,status,log_reference) VALUES(?,?,?,'running',?)",
                          ("company_master_stub_load", "investify", now, "stubs")).lastrowid
    done = 0
    for c in batch:
        if conn.execute("SELECT 1 FROM company_identifiers WHERE id_type='psx_ticker' AND value=? AND valid_to IS NULL",
                        (c["ticker"],)).fetchone():
            continue
        conn.execute("INSERT OR IGNORE INTO companies(company_id,legal_name,listing_status,profile_source_item_id,"
                     "created_at_utc,updated_at_utc) VALUES(?,?,'unknown',?,?,?)",
                     (c["company_id"], c["legal_name"], c["source_item_id"], now, now))
        conn.execute("INSERT INTO company_identifiers(company_id,id_type,value,verified_at_utc,source_item_id) "
                     "VALUES(?,'psx_ticker',?,?,?)", (c["company_id"], c["ticker"], now, c["source_item_id"]))
        for alias, atype in ((c["ticker"], "ticker"), (c["legal_name"], "legal_name")):
            conn.execute("INSERT OR IGNORE INTO company_aliases(company_id,alias,alias_normalized,alias_type,confidence,"
                         "source_item_id,evidence) VALUES(?,?,?,?,'candidate',?,?)",
                         (c["company_id"], alias, alias.casefold(), atype, c["source_item_id"], f"stub: {c['evidence']}"))
        done += 1
    remaining = len(sp["creatable"]) - len(batch)
    conn.execute("UPDATE collector_runs SET finished_at_utc=?,status=?,items_fetched=?,items_accepted=? WHERE run_id=?",
                 (_now(), "succeeded" if remaining == 0 else "partial", len(sp["creatable"]), done, run_id))
    conn.commit()
    return {"stubs_created": done, "remaining_creatable": remaining, "needs_name": len(sp["needs_name"]), "run_id": run_id}


def stub_main(argv):
    try:
        from backend import turso_db
    except ImportError:
        import turso_db
    import sqlite3
    conn = turso_db.get_connection()
    names = json.load(open(argv[argv.index("--names") + 1])) if "--names" in argv else None
    if isinstance(names, list):
        names = {r["symbol"].upper(): r for r in names}
    cands = stub_candidates(conn)
    sp = plan_stubs(cands, names)
    cov = resolution_coverage(conn, [c["ticker"] for c in sp["creatable"]])
    print(f"unlinked tickers in verified source_items: {len(cands)} | creatable stubs: {len(sp['creatable'])} | needs_name: {len(sp['needs_name'])}")
    print("announcement resolution coverage:", json.dumps(cov))
    for c in sp["creatable"][:20]:
        print(f"  WOULD CREATE {c['ticker']}: {c['legal_name']!r} (listing_status unknown; no ISIN/sector) <- item {c['source_item_id']}, {c['evidence'][:60]}")
    for c in sp["needs_name"][:30]:
        print(f"  needs verified name: {c['ticker']} ({c['items']} announcement(s)); e.g. {c['sample_title'][:70]!r}")
    if "--apply" in argv:
        if isinstance(conn, sqlite3.Connection):
            sys.exit("refusing --apply: Turso connection failed (local SQLite fallback)")
        chunk = int(argv[argv.index("--chunk") + 1]) if "--chunk" in argv else 100
        print("APPLIED:", apply_stubs(conn, sp, chunk))


def main(argv):
    if "--stubs" in argv:
        return stub_main(argv)
    path = next((a for a in argv if not a.startswith("--")), "data/psx_profiles.json")
    raw = open(path, "rb").read()
    records = json.loads(raw)
    if not isinstance(records, list):
        sys.exit("expected a JSON list of profile objects")
    existing = None
    if "--no-db" not in argv:
        try:
            from backend import turso_db
        except ImportError:
            import turso_db
        conn = turso_db.get_connection()
        existing = snapshot(conn)  # read-only SELECTs
    sha = hashlib.sha256(raw).hexdigest()
    report(plan(records, existing), sha)
    if "--apply" in argv:
        if existing is None:
            sys.exit("--apply needs the database (do not pass --no-db)")
        import sqlite3
        if isinstance(conn, sqlite3.Connection):
            sys.exit("refusing --apply: Turso connection failed (local SQLite fallback)")
        chunk = int(argv[argv.index("--chunk") + 1]) if "--chunk" in argv else 100
        print("APPLIED:", apply_chunk(conn, records, sha, chunk))


if __name__ == "__main__":
    main(sys.argv[1:])
