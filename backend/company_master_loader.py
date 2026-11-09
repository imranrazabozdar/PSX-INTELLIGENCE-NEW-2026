"""Company master expansion: PLAN-ONLY loader (design draft, owner approval pending).

Reads data/psx_profiles.json, validates every record, compares it with what is already in Turso (read-only),
and prints the dry-run plan: counts of new / overlapping / conflicting / rejected records and the exact rows
that WOULD be written. There is deliberately NO write path in this file: applying the plan is added only after
the owner approves the design (see docs/COMPANY_MASTER_EXPANSION_PLAN.md).

    python backend/company_master_loader.py data/psx_profiles.json [--no-db]
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


def main(argv):
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
    report(plan(records, existing), hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    main(sys.argv[1:])
