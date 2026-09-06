# PSX FIRE Engine + Wyckoff Detector — Production Readiness Report
Generated: 2026-09-06, verified against `origin/main` @ `bd333d9`

## A note on this report's source

This was requested against a spec (`CLAUDE_CODE_VERIFY_FIRE_ENGINE_PRODUCTION.md`) whose
file/table/column names don't match this repository — `fire_engine/config.yaml` (real:
`fire_engine/config/fire_config.yaml`), `fire_engine/data_fetcher.py` (real: `scraper.py`),
`fire_engine/fire_engine.py` / `fire_engine/main.py` (don't exist — real: `scheduler.py`),
`FIRE_SYMBOLS`/`PSX_EXCLUSION_SECTORS` yaml keys (real: `stocks.universe` + a separate
`excluded_sectors_config.py` module), `fire_scans`/`fire_signals` tables (real: `fire_events`),
and "244 excluded stocks" / "15 tests" (real, current counts: 243 and 29 — see below, both
with a documented reason). Every check below was re-run against the **real** structure rather
than the spec's guessed one; no code was changed (pure verification, as instructed).

## Summary

| Phase | Status |
|---|---|
| 1. Universe & exclusion | ✅ |
| 2. Data source (real SCS, no mocks) | ✅ |
| 3. Scheduler (cron + market-hours guard) | ✅ |
| 4. Patterns tab integration | ✅ |
| 5. Unit tests | ✅ 29/29 |
| 6. Logging | ✅ |
| 7. Fixes applied | ✅ |
| 8. End-to-end (real production run, not a synthetic local test) | ✅ |
| 9. Production readiness | ✅ ready |

## Details

### Phase 1 — Universe & Exclusion
- Universe: **89 symbols** (`fire_engine/config/fire_config.yaml`'s `stocks.universe`,
  reused from `backend/app.py`'s own `WATCHLIST_SYMBOLS`, not a hand-picked subset).
- YOUW: present in the universe, confirmed **absent** from the exclusion list (per explicit
  prior instruction to track it rather than filter it out).
- Exclusion list: **243 symbols**, not 244 — the source material supplied to this project
  claimed "519 stocks total" but the actual per-sector lists summed to 244; after removing
  YOUW per instruction, 243 remains. This gap is documented in
  `fire_engine/excluded_sectors_config.py`'s own module docstring and was never silently
  "fixed" to match a claimed total that the underlying data doesn't support.
- Universe ∩ exclusion: **empty set** (no overlap) — verified programmatically.

### Phase 2 — Data Source
- Real SCS endpoint confirmed: `CHART_BASE = "https://chart.scstrade.com"` in
  `fire_engine/scraper.py`, using the UDF protocol's `resolution=1` (1-minute) for FIRE
  Engine and `resolution=240` (4-hour) for the Wyckoff detector.
- No mock/dummy/fake data anywhere in `fire_engine/*.py` production code (grep-verified).
- `SCSDataError` is raised on any malformed response rather than ever returning fabricated
  candles — a genuinely empty session returns an empty list, not an error.

### Phase 3 — Scheduler
- Cron: `40 10 * * 1-4` (Mon-Thu 10:40 UTC = 15:40 PKT) and `40 11 * * 5` (Fri 11:40 UTC =
  16:40 PKT), in `.github/workflows/fire_engine_daily_batch.yml`. Both post-close, both
  weekdays only.
- Market-hours guard: `fire_engine/market_hours.py`'s `is_trading_day()` gates both
  `run_daily_batch.py` and `run_wyckoff_batch.py` — exits with status 0 (not an error) on a
  weekend, verified live on an actual Sunday during this session (prints status, never opens
  the DB connection). Deliberately checks weekday only, not an intraday hour window — the
  batch is a post-close job, and the naive "is the market open right now" check the original
  spec for this guard proposed would have silently killed the Friday run every week (verified
  during that session: at Friday's real 16:40 PKT dispatch time, that check returns False).

### Phase 4 — Patterns Tab Integration
- `/patterns/fire-scan` and `/patterns/wyckoff-scan` both defined in `backend/app.py`
  (FastAPI, not Flask), both called from `streamlit_app.py`'s Patterns tab, both using the
  same `_scan_cache`/`_serve_cached_and_refresh` convention as every other scan on that tab.
- Both sections render live in the deployed Streamlit app (confirmed via a real screenshot
  from `psx-intelligence-new-2026.streamlit.app` during this session, showing LOTCHEM/
  AIRLINK/CPHL results and correct signal badges).

### Phase 5 — Unit Tests
**29/29 passing** (not 15 — the original FIRE Engine suite was 15; adding the Wyckoff
detector's own 14-test suite brought the total to 29; both suites verified together):
```
fire_engine/tests/test_fire_engine.py ....................... 15 passed
fire_engine/tests/test_wyckoff_detector.py .................. 14 passed
============================== 29 passed in 5.03s ==============================
```
(Unrelated pre-existing test files under `backend/` — `test_find_patterns.py`,
`test_cup_handle.py`, etc. — belong to other detectors in this project, not FIRE Engine/
Wyckoff, and are out of scope for this report.)

### Phase 6 — Logging
- Every batch (`scheduler.py`, `wyckoff_scheduler.py`) calls its progress callback with
  `print(msg, flush=True)` — explicit flush because GitHub Actions' log capture isn't a tty
  (block-buffered by default, which would otherwise defeat live per-symbol progress).
  `PYTHONUNBUFFERED: "1"` is also set on all four workflow steps as a second line of defense.
- No persistent log FILE exists (by design — this runs in a fresh GitHub Actions container
  each time, not a long-lived host with a log directory); the audit trail is the GitHub
  Actions run log itself, which is what was actually inspected throughout this session's
  real production verifications.

### Phase 7 — Fixes Applied
- YOUW: present in both the universe and (as an explicit exclusion) absent from the
  exclusion list — confirmed above.
- Imports: `from fire_engine import scheduler, wyckoff_scheduler, market_hours` — clean,
  no circular-import errors.
- Schema semicolon-in-comment fix: confirmed still in place in `fire_engine/database.py`
  (the comment that previously read "...fetched again; see..." now reads "...fetched
  again -- see...", no literal `;` inside any SQL comment anywhere in `SCHEMA_SQL`).
- Wyckoff INSERT placeholder mismatch fix: confirmed — `wyckoff_accumulation`'s INSERT has
  **23 columns and 23 `?` placeholders** (verified programmatically; the earlier 22-vs-23
  bug that failed every symbol on the first real production run is gone).

### Phase 8 — End-to-End
Rather than a synthetic local single-symbol test (SCS/Turso aren't reachable from this
sandboxed environment), this was verified with **real GitHub Actions production runs**
during this session, against date `2026-09-04`:
- FIRE Engine: **87/89 symbols processed OK**, 1,714 PRE_FIRE events logged, 0 FIRE
  confirmations, runtime ~21 minutes (previously hung indefinitely past its 30-minute
  timeout before this session's Turso round-trip fixes).
- Wyckoff scan: **85/89 symbols scanned**, 3 signals — **LOTCHEM (100, EXTREME)**,
  AIRLINK (70, READY), CPHL (70, READY).
- 4-hour cache backfill: 89/89 symbols, 3,502 candles stored.
- 2 symbols (ECPL, STLR) returned NO_DATA on both scans that day (real data-coverage gap,
  not a code error); 4 symbols (KOHC, ECPL, STL, STLR) were skipped by the Wyckoff scan for
  insufficient daily history — also a genuine data-coverage limit, not a bug.

## Open items (not blockers, flagged for awareness)

- **Excluded-stock list is 243, not the originally-claimed 519** — the missing ~275 symbols
  were never supplied to this project; the list is usable but incomplete relative to that
  original claim.
- **FIRE Engine's PRE_FIRE threshold looks loose and FIRE looks too strict** — 1,714
  PRE_FIRE events but 0 FIRE confirmations across the entire universe on a real trading day
  (one symbol, BAFL, alone logged 93 PRE_FIRE events out of ~480 bars). Worth a tuning pass
  if the goal is a genuinely rare, high-conviction signal.
- **The Wyckoff detector has never been backtested for hit rate** — unlike this project's
  VCP/Flat Base detectors (backtested, came back "needs rework"), nothing here establishes
  how often a WATCH/READY/EXTREME signal is actually followed by a real breakout. The
  Streamlit UI now states this explicitly to avoid it being read as a buy signal.
- **`ohlcv_4h` cache has a 35-day prune step but no historical ceiling on `daily_ohlc`** —
  intentional (daily bars need unbounded history for the rolling windows), just noting it's
  a deliberate asymmetry, not an oversight.

## Status

✅ **PRODUCTION VERIFIED** — all 8 verification phases pass against the real repository
structure and real production runs. No code changes were made as part of this report (pure
verification, per the task's own instructions).

Next scheduled run: Monday, 15:40 PKT (10:40 UTC) — first automated run to use everything
merged in this session (Wyckoff detector, all four production bug fixes, market-hours guard,
cache pruning).
Last verified run: 2026-09-04 (FIRE + Wyckoff), both green.
Total symbols in universe: 89.
Total signals detected (most recent Wyckoff scan): 3 (1 EXTREME, 2 READY).
