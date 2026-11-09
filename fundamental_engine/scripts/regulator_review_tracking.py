"""Open terms-review tracking for SBP and SECP in the source registry (appends a dated note; no status changes).
python fundamental_engine/scripts/regulator_review_tracking.py [--apply]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.db import TursoClient

MARK = "[terms-review tracking opened 2026-11-09"
NOTE = (" | [terms-review tracking opened 2026-11-09: see fundamental_engine/docs/REGULATOR_TERMS_REVIEW.md. "
        "Status remains BLOCKED until the review concludes; no automated collection.]")


def track(db, apply=False):
    out = {}
    for sid in ("sbp", "secp"):
        row = db.execute("SELECT review_notes FROM sources WHERE source_id=?", (sid,)).one()
        if row is None:
            out[sid] = "missing"
        elif MARK in (row["review_notes"] or ""):
            out[sid] = "already tracked"
        else:
            if apply:
                db.execute("UPDATE sources SET review_notes=COALESCE(review_notes,'')||?, updated_at_utc=strftime('%Y-%m-%dT%H:%M:%SZ','now') "
                           "WHERE source_id=?", (NOTE, sid))
            out[sid] = "updated" if apply else "would update"
    return out


if __name__ == "__main__":
    print(track(TursoClient(), "--apply" in sys.argv))
