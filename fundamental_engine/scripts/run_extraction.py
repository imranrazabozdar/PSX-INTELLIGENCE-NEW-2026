"""Phase 1 runner (Groq first). DRY RUN by default: lists what would be sent, spends nothing.
  python fundamental_engine/scripts/run_extraction.py --task news_event_extraction --limit 10
  python fundamental_engine/scripts/run_extraction.py --task news_event_extraction --limit 5 --live   # needs an enabled+reviewed provider + key
Relevance prefilter is ON by default (--no-prefilter to disable; --scan N = pending window scanned, default 300).
Reads/writes the production Turso DB via LIBSQL_URL/LIBSQL_AUTH_TOKEN."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.db import TursoClient
from extract.pipeline import run_news_batch
from extract.relevance import Relevance
from llm.router import Router

if __name__ == "__main__":
    a = sys.argv[1:]
    task = a[a.index("--task") + 1] if "--task" in a else "news_event_extraction"
    limit = int(a[a.index("--limit") + 1]) if "--limit" in a else 10
    live = "--live" in a
    db = TursoClient()
    router = Router.from_config(db, task)
    if live and not router.providers:
        sys.exit("no usable provider: enable it, verify the model, record the terms review, and set its key (see docs/LLM_PROVIDERS.md)")
    scan = int(a[a.index("--scan") + 1]) if "--scan" in a else 300
    pre = None if "--no-prefilter" in a else Relevance.from_db(db)
    res = run_news_batch(router, db, limit, dry_run=not live, prefilter=pre, scan_limit=scan)
    print(json.dumps({k: v for k, v in res.items() if k != "plan"}))
    for p in res["plan"][:20]:
        print("  ", p)
