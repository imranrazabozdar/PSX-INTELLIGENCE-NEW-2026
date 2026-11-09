"""Candidate review queue. READ-ONLY / PLAN-ONLY: nothing here writes to the database.
  python fundamental_engine/scripts/review_queue.py list [--limit N]
  python fundamental_engine/scripts/review_queue.py show ID
  python fundamental_engine/scripts/review_queue.py plan ID --decision accept|reject|needs_more_evidence --notes "..." [--reviewer NAME] [--stage STAGE] [--claims 0,1]
  python fundamental_engine/scripts/review_queue.py apply ID --decision ... --notes "..." [--reviewer NAME] [--stage STAGE] [--claims 0,1] [--rationale TICKER=text] --confirm
`plan` prints the exact statements; `apply` writes ONLY with --confirm (atomic; candidate must still be pending; needs migration 0011).
Default reviewer: "Imran Raza". Decisions are the reviewer's: this tool never decides anything by itself. See docs/REVIEW_WORKFLOW.md."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.db import TursoClient
from review import accept, queue, runner


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
        plan = accept.build_plan(row, arg(a, "--decision"), arg(a, "--reviewer", runner.DEFAULT_REVIEWER), arg(a, "--notes"), arg(a, "--stage", "not_applicable"), claims)
        print("PLAN ONLY (nothing executed):", json.dumps(plan["summary"]))
        for sql, params in plan["statements"]:
            print(" ", sql[:110].replace("\n", " "), "...", params)
    elif cmd == "apply":
        claims = {int(x) for x in arg(a, "--claims").split(",")} if arg(a, "--claims") else None
        why = dict(x.split("=", 1) for x in a if "=" in x and x.split("=", 1)[0].isupper()) or None
        try:
            res = runner.decide(db, int(a[1]), arg(a, "--decision"), arg(a, "--notes"), arg(a, "--reviewer", runner.DEFAULT_REVIEWER),
                                confirm="--confirm" in a, status_stage=arg(a, "--stage", "not_applicable"), claim_indices=claims, company_rationales=why)
        except (runner.RunnerError, accept.ReviewError) as e:
            sys.exit(f"REFUSED: {e}")
        print(json.dumps(res))
    else:
        sys.exit(__doc__)
