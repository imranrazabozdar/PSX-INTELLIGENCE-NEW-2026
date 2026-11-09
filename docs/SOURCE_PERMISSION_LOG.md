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

### Amendment A1 — User-Agent (owner-approved in-session, 2026-11-09)

Original UA drew HTTP 404 from the portal. Owner approved:
`Mozilla/5.0 (compatible; PSX-NEWS-INTELLIGENCE research bot, contact owner)` (still identifies the bot).
All other parameters unchanged (4 symbols, cap 10, jitter 3.5-8.5 s). Turso token was renewed by the owner; `SELECT 1` handshake returned HTTP 200. Amendment is defined but NOT yet exercised: no request sent with it.

Finding: production Turso has no `daily_ohlc`; the real table is `market_bars` (13,228 rows, strict schema). Ingest target pending owner confirmation.

### Decision D1 (owner, 2026-11-09): ingest target

Ingest into existing `market_bars` (`timeframe='1d'`, `bar_start_utc` = `YYYY-MM-DDT00:00:00Z`, `INSERT OR IGNORE`), reuse an existing `psx_dps` source row or create one (disabled), and one `collector_runs` row linked to every inserted bar. No `psx_dps`/DPS source existed at 2026-11-09 (only `scs_chart`).

### Run record

| Step | Status |
|------|--------|
| Approval recorded | done |
| Offline tests (real-schema copy, `backend/fixtures/market_bars_schema.sql`) | 7/7 passed |
| Dry run | done (0 requests, no DB) |
| Live run | NOT COMPLETED. Attempt 1 and 2 (original and amended UA): `POST /historical` `{symbol,date}` -> HTTP 404. Diagnosis: the portal page now posts `{month,year,symbol}` and adds an `X-Req-Id` header produced by the page's JavaScript. Not replicated (would imitate the site's bot-detection; outside approval). |
| Ingest into `market_bars` | NOT DONE: 0 rows inserted, no `sources` or `collector_runs` rows created. |

Requests that reached dps.psx.com.pk: 5 of 10 (robots.txt GET 404, POST 404 x2, GET /historical 200, GET /static/script.js 200).
Turso: token renewed, `SELECT 1` HTTP 200; no writes made by this pilot.
