"""Applies ONE reviewer decision. Safe by construction:
  * nothing is written unless confirm=True (otherwise the plan is returned)
  * the candidate must still be in the pending queue (no double decisions)
  * the extraction_reviews table (migration 0011) must exist
  * all statements run atomically via review.accept.apply_plan
The reviewer name is the person who made the decision; default is the project's named reviewer."""
from review import accept, queue

DEFAULT_REVIEWER = "Imran Raza"


class RunnerError(Exception):
    pass


def decide(db, extraction_id, decision, notes, reviewer=DEFAULT_REVIEWER, confirm=False, status_stage="not_applicable",
           claim_indices=None, company_rationales=None, now=None):
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='extraction_reviews' AND type='table'").one() is None:
        raise RunnerError("extraction_reviews does not exist: apply migration 0011 first")
    pending = {r["extraction_id"] for r in queue.pending(db, 10_000)}
    if extraction_id not in pending:
        raise RunnerError(f"extraction #{extraction_id} is not awaiting review (unknown, or already decided)")
    row = queue.show(db, extraction_id)
    plan = accept.build_plan(row, decision, reviewer, notes, status_stage, claim_indices, company_rationales, now)
    if not confirm:
        return {"applied": False, "summary": plan["summary"], "statements": len(plan["statements"]),
                "message": "plan only: re-run with --confirm to apply"}
    accept.apply_plan(db, plan)
    return {"applied": True, "summary": plan["summary"], "statements": len(plan["statements"])}
