# PSX Fundamental & News Intelligence Engine

Independent research/decision-support engine. **Isolated from the technical engine**: nothing here imports from
`backend/` or `fire_engine/`, and it is written so the folder can be lifted into its own repository
(`git subtree split -P fundamental_engine`) without changes. It uses the existing Turso database (migrations 1-10).

Principle: detect event impact -> understand economic transmission -> estimate company-level financials -> assess
whether the market has priced it in. Event-centered schema, provenance on every claim.

## Layout
| Folder | Role | Status |
|---|---|---|
| `migrations/` | `0010_baseline_snapshot.sql` (regenerated from live Turso; replaces unversioned migrations 1-10 for fresh DBs) + `baseline_manifest.json` | Phase 0 done |
| `core/` | `db.py` (Turso HTTP + SQLite, same interface), `config.py`, `migrate.py`, `watchlist.py` | Phase 0 done |
| `llm/` | `router.py`, `providers.py`, `budget.py`, `validate.py` | Phase 1 done (no live provider wired) |
| `extract/` | prompt + JSON-schema registry (`prompts/`, `schemas/`), `claims.py` | Phase 1 done |
| `extract/` also: `dedup.py`, `entities.py`, `evaluate.py` | de-duplication, entity resolution, evaluation | see `docs/EXTRACTION_QUALITY.md` |
| `sources/acquire.py` | permission-gated content acquisition (zero eligible sources today) | framework only |
| `review/` | candidate review queue + confirmed apply | see `docs/REVIEW_WORKFLOW.md` |
| `events/` `exposure/` `calc/` `market/` `app/` | module boundaries reserved | later phases |
| `scripts/` | `init_watchlist.py`, `regulator_review_tracking.py` (dry-run by default) | |
| `docs/` | `REGULATOR_TERMS_REVIEW.md`, `LLM_PROVIDERS.md` | |

## Hard rules enforced in code (and tested)
1. **Models never write to the database and never produce numbers.** They return text; `llm/validate.py` accepts only
   schema-exact JSON, verbatim quotes, and number-free inferences (digits, %, currency, number words are rejected).
2. **Claim types are assigned by Python, not the model**: grounded quote from an official source -> `official_statement`,
   from another permitted source -> `news_report`, model-authored -> `model_inference`. `verified_fact` is reserved for
   human-reviewed evidence. Model confidence is a band mapped to a fixed value in Python.
3. **Candidates only**: results land in `event_extractions` with `needs_human_review=1`; nothing reaches `events`,
   `event_evidence` or exposures without review.
4. **Content-hash cache**: `(source_item, schema_version, prompt_version)` hit -> no call, logged as `cached`.
5. **Budget gates + kill switch**: per-provider calls/tokens per UTC day counted from `llm_calls`; `LLM_KILL_SWITCH=1` stops all calls.
6. **Eligibility gate**: only `verified_permitted` sources may be sent to a third-party model; restricted/blocked/unreviewed
   content never leaves the project.
7. Fallback only on error/budget refusal, never retrying a rate-limited provider; one account/key per provider.

## Run the tests
`python -m pytest fundamental_engine/tests -q`
