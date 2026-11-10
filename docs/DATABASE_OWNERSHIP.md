# Database ownership (technical engine)

Status: enforced in code on branch `feature/refuse-shared-news-database` (2026-11-10).

## Rule
The PSX-NEWS-INTELLIGENCE production database (`psx-news-intelligence-imranrazabozdar`) belongs to the news
project only. This engine must never connect to it, never write to it and never read it.

## What is enforced
* `fundamental_engine/core/db_guard.py` refuses the news host in every spelling (case, trailing dot, port,
  lookalike names containing `psx-news-intelligence`) and any URL carrying credentials, a query or a fragment.
* `fundamental_engine/core/db.py` (`TursoClient`) runs the guard before any network call.
* `backend/turso_db.py` runs the same check at import, so the module refuses to load instead of falling back.
* Tests: `fundamental_engine/tests/test_db_guard.py`.

## Owner action required (not performed by code)
1. Create a separate Turso database for this engine, with a token scoped to it only.
2. Replace `LIBSQL_URL` and `LIBSQL_AUTH_TOKEN` in this repository's secrets with the new values.
3. Remove the old values. The old token was invalidated on 2026-11-09 and the news database must not receive any
   write from this repository.
4. Record in the news repository's `docs/STATUS.md` that the technical database is separate.

## Historical note
Before separation, migration 0011 and production extraction runs from this engine wrote to the news database
(see the news repository's architecture-correction document). Those records are quarantined there and never
modified.
