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

Ingest into existing `market_bars` (`timeframe='1d'`, `bar_start_utc` = `YYYY-MM-DDT00:00:00Z`, `INSERT OR IGNORE`), reuse an existing `psx_dps` source row or create one (disabled), and one `collector_runs` row linked to every inserted bar. CORRECTION (2026-11-09 audit): this was wrong. A `psx_dps` source row DOES exist (RESTRICTED, `prohibits_automation`, `access_method=not_permitted`, disabled; PSX Terms of Use prohibit automated retrieval; announcements sit behind reCAPTCHA). My check had errored on a bad column name and I misread it. The -02 requests (5 to dps.psx.com.pk, none produced data) were made under owner approval but against that registered restriction. No `psx_dps` row was created or modified by this pilot.

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

## PILOT-2026-11-09-03 — SCS Trade chart feed micro-batch (supersedes -02 route)

- **Approved by:** repository owner, in-session, 2026-11-09 (after -02's dps.psx.com.pk route was abandoned: the portal now requires a JS-generated `X-Req-Id` header, which is not to be imitated)
- **Source:** `https://chart.scstrade.com/history` (existing `scs_chart` source row, TradingView UDF, resolution `D`)
- **Symbols:** APL, BAHL, PACE, DFML
- **Scope:** last 30 trading days per symbol only; fields Symbol/Date/O/H/L/C/Volume
- **Write budget:** up to 500 rows into `market_bars` (`INSERT OR IGNORE`, `timeframe='1d'`, one `collector_runs` row, source `scs_chart`); overrides the per-run budget block for this pilot only
- **Constraints:** UA `Mozilla/5.0 (compatible; PSX-NEWS-INTELLIGENCE research bot, contact owner)`; jitter 3.5-8.5 s; no Referer or other spoofed headers; rows younger than 15 min (and the current PKT session) excluded; request cap 10
- **Network:** `chart.scstrade.com` added to the Default environment allowlist
- **Code:** `backend/ohlcv_pilot.py`, tests `backend/test_ohlcv_pilot.py` (8/8)

### Run record — PILOT-2026-11-09-03 (2026-11-09, ~11:47 UTC)

| Step | Result |
|------|--------|
| Approval recorded | done |
| Offline tests (real-schema copy) | 8/8 passed |
| Dry run | done (0 requests, no DB) |
| Live run | 4 GET requests to chart.scstrade.com/history (cap 10), all HTTP 200, jitter 3.5-8.5 s |
| Fetched | 120 bars (30 per symbol, 2026-09-28 .. 2026-11-06); none dated 2026-11-09 (market holiday) |
| Ingest | **120 rows inserted** into `market_bars` (limit 500); 0 rejected, 0 duplicates |
| Provenance | `collector_runs.run_id=38`, job `PILOT-2026-11-09-03`, status `succeeded`, linked to all 120 bars; source `scs_chart` (existing row, unchanged) |
| Independent verification | Turso query: APL/BAHL/DFML/PACE = 30 `1d` bars each; `market_bars` total 13,228 -> 13,348 |

No `psx_dps` source row was created or modified (it pre-exists, restricted). No Referer or spoofed headers were sent.

## PILOT-2026-11-09-04 — Investify public-page read test (OWNER OVERRIDE)

- **Decision:** OWNER OVERRIDE, 2026-11-09, in-session. The `investify` source row is `RESTRICTED` / `prohibits_automation` / `permission_required` (terms reviewed 2026-11-07, `docs/INVESTIFY_SCS_TRADE_ASSESSMENT.md`, PR #6): automated access needs Investify's prior written permission. **No such permission exists.** The owner explicitly accepts the legal/terms risk, under the same risk-acceptance protocol as the SCS pilot, to test Investify's public pages for text-based announcement metadata.
- **Scope:** read-only, public pages only; console output only; **no database writes** (Turso untouched); no `sources` row change (it stays RESTRICTED).
- **Conditions:** honest User-Agent only — `Mozilla/5.0 (compatible; PSX-NEWS-INTELLIGENCE research bot, contact owner)`; no spoofed browser headers (no Sec-Fetch-*, no Referer); a browser-mimicking header set was proposed and **declined**; 4.5-9.5 s jitter before every request; robots.txt checked first and respected; no auth, no CAPTCHA/WAF bypass — on a block (403/429/503, CAPTCHA or challenge page) the script exits and reports it; hard cap of 3 requests per run.
- **Code:** `backend/investify_pilot.py`, tests `backend/test_investify_pilot.py` (offline). Run locally by the owner; not run by the assistant (no network access to the host from the sandbox).
- **Not an approval for collection:** stored data, scheduled collection or enabling the source would each need a separate decision.

### Run record

| Step | Status |
|------|--------|
| Override recorded | done |
| Offline tests | 11/11 passed |
| Live run | Run by the assistant in the sandbox at owner's request, 2026-11-09. `python backend/investify_pilot.py https://investify.pk/` -> robots.txt (404/allowed path) + 1 page GET, 2/3 requests, HTTP 200, 837,406 bytes, exit 0. No block, no CAPTCHA. Page lists homepage news plus a "Company Announcements" block (e.g. SSGC Annual Report 2026, OGDC corporate briefing recording link, EFU Life right-issue allotment, AGM notices). Console only: nothing stored, no DB writes. |
| Network | `investify.pk` and `www.investify.pk` (redirect target) added to Default environment allowlist. A first attempt (exit 4) failed only at the sandbox proxy for the www host; it never reached Investify. |

### Extension E1 to PILOT-2026-11-09-04 — structure probe (owner override, 2026-11-09)

Owner authorised a read-only probe for the dedicated announcements page and its HTML structure. Same conditions (honest UA, 4.5-9.5 s jitter, robots.txt first, no bypass, console only, no DB writes). `backend/investify_pilot.py --probe`, 14 offline tests.

- Homepage link finder initially picked an unrelated "See all" (`/tools#tax`); the homepage nav exposed `/announcements` ("Company filings"), which the owner had listed as a candidate path.
- `https://www.investify.pk/announcements`: HTTP 200, server-rendered (~485 KB), title "Company Announcements | Investify", 30 results, no CAPTCHA/WAF block.
- Requests to investify.pk / www.investify.pk this session: about 11 across 5 runs (each run: robots.txt + 1-2 pages; every request jittered). Nothing stored.
- Findings for a future parser (cards = `div[data-announcement-row="true"]`): ticker in `a[href^="/company/<TICKER>/quote"]`; company name in the span `title` attribute; category chip span; timestamp in `<time datetime="2026-11-06T12:45:00.000Z">` (ISO, visible text is PKT); title in `h3 > a[href="/announcements/<TICKER>/dps-pdf-<id>"]`; summary in `p` (Investify-generated); "Original PDF" link to `https://dps.psx.com.pk/download/document|attachment/<id>.pdf`.
- **Compliance flags (no action taken):** (1) the PDF links point at `dps.psx.com.pk`, a RESTRICTED / prohibits_automation source: they must not be fetched automatically; (2) Investify's summaries/highlights are its own derived content and its terms prohibit reuse; (3) the `investify` source row remains RESTRICTED and this override does not authorise storage or scheduled collection.

### Ingestion approval I1 to PILOT-2026-11-09-04 — OWNER OVERRIDE for factual metadata (2026-11-09)

- **Decision (owner, in-session):** authorises storing facts-only rows extracted from Investify's public announcements page into Turso `source_items`, overriding the `investify` source's `prohibits_automation` flag **for this specific script only**. The owner's stated basis is that only public facts are stored (ticker, timestamp, category, title, PSX filing id) and Investify's summaries/sentiment are dropped; this is the owner's risk acceptance, **not a legal determination by the assistant**.
- **Mapping approved as designed** (`docs/INVESTIFY_ANNOUNCEMENT_MAPPING.md`): `source_id='investify'`, `access_status='restricted'`, `retrieval_method='html'`, `external_id='psx_filing:<psx_id>'`, `document_type='announcement'`, `permitted_excerpt` and `content_location` NULL; `INSERT OR IGNORE`; append-only `source_item_versions` (v1 on insert, next version on a changed hash).
- **Company links:** none forced. Tickers outside the 51-company master (e.g. TPLP, CTM) are stored unlinked; master expansion is a separate, planned step.
- **Unchanged limits:** the source row stays RESTRICTED/disabled and is not modified; PDFs and linked pages are never fetched (manual ingester only); honest UA, 4.5-9.5 s jitter, robots.txt, hard exit on CAPTCHA/WAF; <=2 requests per run; <=60 rows per run (Turso free-tier guard); no scheduled collection authorised.
- **Code:** `backend/investify_ingester.py` (`--dry-run`, `--live`, `--html-file`), tests `backend/test_investify_ingester.py`.
- **Verification so far (no writes to Turso):** 40/40 offline tests incl. duplicate rejection and changed-title versioning; read-only dry-run against live Turso with the offline fixture: 2 would-insert, 0 duplicates; 0 `investify` rows exist in Turso. No Investify requests made for this step.
- **Live ingest:** NOT yet run.
