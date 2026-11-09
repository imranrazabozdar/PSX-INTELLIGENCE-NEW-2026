# Source Permission Log

Record of explicit owner approvals for fetching data from external sources.

## PILOT-2026-11-09-02 — PSX Data Portal OHLCV re-fetch (second pilot)

- **Approved by:** repository owner (imranrazabozdar), in-session, 2026-11-09
- **Source:** https://dps.psx.com.pk/historical (public PSX Data Portal page)
- **Purpose:** fill missing daily OHLCV rows in `daily_ohlc`
- **Symbols:** APL, BAHL, PACE, DFML
- **Request cap:** 10 requests maximum (retries count against the cap)
- **Jitter:** 3.5–8.5 s random delay between requests
- **User-Agent:** `PSX-NEWS-INTELLIGENCE research bot, contact owner`
- **Delay rule:** 15-minute exchange delay respected; the current session's bar is never ingested
- **Note:** the earlier pilot (-01) has no record in this repository's history; this is the first entry in this log.
- **Code:** `backend/ohlcv_pilot.py`, tests in `backend/test_ohlcv_pilot.py`

### Run record

| Step | Status |
|------|--------|
| Approval recorded | done |
| Offline tests | 6/6 passed |
| Dry run | done (0 requests, no DB) |
| Live run | ATTEMPT 1 FAILED 2026-11-09: 1 POST to /historical (symbol APL) returned HTTP 404 with the research User-Agent; run aborted, 0 rows fetched. Run stopped pending owner decision. |
| Ingest into `daily_ohlc` | NOT DONE: 0 rows. Turso handshake with a placeholder token returned HTTP 400 (local fallback blocked by guard). |

Requests that reached dps.psx.com.pk this pilot: 2 (one robots.txt GET -> 404, one POST -> 404) of the 10 cap.
Write path targets existing `daily_ohlc` (INSERT OR IGNORE, source `psx_dps`).
