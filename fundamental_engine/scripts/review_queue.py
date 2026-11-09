"""Candidate review queue. READ-ONLY / PLAN-ONLY: nothing here writes to the database.
  python fundamental_engine/scripts/review_queue.py list [--limit N]
  python fundamental_engine/scripts/review_queue.py show ID
  python fundamental_engine/scripts/review_queue.py plan ID --decision accept|reject|needs_more_evidence --reviewer NAME --notes "..." [--stage STAGE] [--claims 0,1]
`plan` prints the exact statements an approved apply step would run. Applying decisions needs the owner to approve migration 0011
(extraction_reviews) and the workflow (docs/REVIEW_WORKFLOW.md)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.db import TursoClient
from review import accept, queue


def arg(a, name, default=None):
    return a[a.index(name) + 1] if name in a else default


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else "list"
    db = TursoClient()
    if cmd == "list":
        rows = queue.pending(db, int(arg(a, "--limit", 20)))
        print(f"{len(rows)} candidate(s) awaiting review")
        for r in rows:
            s = queue.summarise(r)
            print(f"#{s['extraction_id']} [{s['source']}] {s['headline']}\n     type={s['event_type']} band={s['band']} tickers={s['tickers']} "
                  f"quotes={len(s['quotes'])} inferences={len(s['inferences'])} reviewable={s['reviewable']} model={s['model']}")
    elif cmd == "show":
        row = queue.show(db, int(a[1]))
        print(json.dumps(queue.summarise(row), indent=1, ensure_ascii=False))
        print("provenance:", row["provenance_json"], "\nreview reasons:", row["review_reasons_json"])
    elif cmd == "plan":
        row = queue.show(db, int(a[1]))
        claims = {int(x) for x in arg(a, "--claims").split(",")} if arg(a, "--claims") else None
        plan = accept.build_plan(row, arg(a, "--decision"), arg(a, "--reviewer"), arg(a, "--notes"), arg(a, "--stage", "not_applicable"), claims)
        print("PLAN ONLY (nothing executed):", json.dumps(plan["summary"]))
        for sql, params in plan["statements"]:
            print(" ", sql[:110].replace("\n", " "), "...", params)
    else:
        sys.exit(__doc__)
