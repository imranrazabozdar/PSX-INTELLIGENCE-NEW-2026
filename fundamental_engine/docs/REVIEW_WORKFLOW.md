# Candidate review workflow (DESIGN + plan-only tooling; nothing applied to production)

Model output is only ever a **candidate** (`event_extractions`, `needs_human_review=1`). A human decision turns it into
records or closes it. Nothing a model wrote becomes a fact without a named reviewer.

## Why a new table
`event_extractions` is append-only (UPDATE/DELETE blocked by trigger), so a decision cannot be stored on the candidate.
Proposed additive migration **`migrations/0011_extraction_reviews.sql`** (NOT applied to Turso yet):
`extraction_reviews` (decision accept/reject/needs_more_evidence, reviewer >= 2 chars, non-blank notes, event_id required iff accept,
append-only triggers) + view `v_review_queue` (candidates with no decision, or whose latest decision is needs_more_evidence).
Tested in memory on top of the production baseline, including the Turso-style statement-by-statement path.

## Decisions and what each writes
| Decision | Writes |
|---|---|
| reject | one `extraction_reviews` row |
| needs_more_evidence | one `extraction_reviews` row (candidate stays in the queue) |
| accept | `events` + `event_revisions` (rev 1) + `event_evidence` per selected **grounded quote** + `extraction_reviews`, atomically; `event_companies` only if the reviewer supplies a rationale, always `reviewer_status='pending'` |

Accept mapping (all enforced in `review/accept.py` and by the schema's triggers):
- headline = the source item's own title (public fact); **no model-written summary**; `verification_state='single_source'`; confidence left NULL (the reviewer, not the model, assesses)
- `status_stage` chosen by the reviewer (default `not_applicable`); event date left unknown unless the source provides one
- evidence: `relation='supports'`, `verification_state='unverified'`, claim type = the Python-assigned one (`official_statement` / `news_report`)
- **model inferences never become evidence or part of the event**; a candidate without a grounded quote cannot be accepted
- company links cannot be `accepted` from here (the schema requires a confirmed exposure candidate): that is a later workflow

## Tooling
`python fundamental_engine/scripts/review_queue.py list | show ID | plan ID --decision ... --reviewer ... --notes ...`
`plan` prints the exact statements. `apply ID --decision ... --notes "..." [--rationale TICKER=text] --confirm` runs ONE decision atomically (`review/runner.py`): nothing is written without `--confirm`; the candidate must still be pending (no double decisions; needs_more_evidence can be decided again); migration 0011 must exist. Default reviewer: **Imran Raza** (owner-named). The tool never decides anything by itself: every decision is a person's call, passed in by that person.

## State today (live Turso, read-only)
5 candidates: #1, #2, #5 have no claims (not reviewable: would be rejected/closed), #3 and #4 have one grounded `news_report` quote each (#4 also one inference).
All 5 are non-market headlines from the first test run.

## Approvals (owner, 2026-11-09)
Approved: apply migration 0011; the accept mapping above; reviewer name `Imran Raza`; `apply` with mandatory `--confirm`.
Decisions on the 5 stored candidates are NOT made by the assistant; they await the reviewer's calls.
