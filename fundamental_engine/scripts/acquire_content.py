"""Source-content acquisition. DRY RUN by default; --live additionally requires an eligible source (registry retention_mode
'excerpt'/'full_text_permitted' + terms approved), DOCUMENT_VAULT_PATH, robots.txt permission, and respects paywalls/CAPTCHAs/rate limits.
  python fundamental_engine/scripts/acquire_content.py [--source ID] [--limit N] [--live]
Does not change source permissions or write to the database."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.db import TursoClient
from sources import acquire

if __name__ == "__main__":
    a = sys.argv[1:]
    arg = lambda n, d=None: a[a.index(n) + 1] if n in a else d
    db = TursoClient()
    print("eligibility (registry):")
    for e in acquire.eligibility(db):
        print(f"  {e['source_id']:<20} eligible={e['eligible']!s:<5} {e['reason']}")
    live = "--live" in a
    root = acquire.vault_root_from_env() if live else Path("/nonexistent-dry-run")
    res = acquire.acquire_items(db, root, acquire.PoliteFetcher(), arg("--source"), int(arg("--limit", 5)), dry_run=not live)
    print(json.dumps({k: v for k, v in res.items() if k not in ("ineligible",)}, default=str))
    if res.get("refused"):
        sys.exit(f"REFUSED: {res.get('reason')}")
