# Investify announcement -> `source_items` mapping (DESIGN ONLY, nothing executed)

Status: design drafted 2026-11-09 for PILOT-2026-11-09-04. **No Turso writes are authorised.** The investify source
row is RESTRICTED and the owner override covers read-only console tests only; ingesting needs a separate decision.
Parser: `backend/investify_parser.py` (offline, pure). Mapping function: `to_source_item()` in the same file (builds
a dict, executes nothing). Validated only against an in-memory copy of the production DDL.

## Facts extracted (and nothing else)
`ticker`, `timestamp_utc`, `category`, `title`, `psx_id` (+ `deep_link`, needed as the canonical URL).
Never extracted: Investify summaries, "Highlights", sentiment chips, logos. PDF links are never read or followed;
PDFs go through `backend/manual_pdf_ingester.py` by hand.

## Column mapping
| `source_items` column | Value | Why |
|---|---|---|
| `source_id` | `investify` | Honest provenance (read from Investify). Row stays RESTRICTED/disabled; the FK allows it. Not `psx_dps` (not read from there). |
| `retrieval_method` | **`html`** | Server-rendered HTML page. `api` would be false: no API is used. |
| `external_id` | **`psx_filing:<psx_id>`** e.g. `psx_filing:288842-1` | PSX's own filing id (from `dps-pdf-<id>`), stable across sources; `UNIQUE(source_id, external_id)` gives idempotent re-runs. |
| `canonical_url` / `original_url` | `https://www.investify.pk/announcements/<TICKER>/dps-pdf-<id>` | Investify deep link; also satisfies "url or external_id required". |
| `title` | announcement title | public fact |
| `published_at_utc` / `published_at_raw` | `<time datetime>` normalised to `YYYY-MM-DDTHH:MM:SSZ` | `publication_time_status='known'` |
| `event_date` | UTC date of the timestamp | caveat: a late-evening PKT filing (after 19:00 UTC offset) could differ from the PKT date; compute PKT date downstream |
| `document_type` | `announcement` | |
| `access_status` | `restricted` | conservative while the source is RESTRICTED (allowed values: public/permitted/restricted/unavailable) |
| `content_sha256` | SHA-256 of JSON `[ticker, timestamp, category, title, psx_id]` | hash of public facts only, never of Investify's text |
| `permitted_excerpt` | `NULL` | never store Investify's summary |
| `content_location` | `NULL` | PDF not fetched; manual ingester can later create a separate `pdf` item with the same hash-based vault path |
| `source_metadata_json` | `{"ticker","category","psx_filing_id","via"}` | keeps ticker queryable (`json_extract`) without a schema change |
| `collection_run_id` | one `collector_runs` row per ingest (`job='investify_announcements'`) | as for market_bars |

Changes to an existing announcement (e.g. a corrected title) must append a `source_item_versions` row (new hash);
`source_items` is immutable/append-only by trigger.

## Linking to the company master
`source_items` has **no company column** by design. Path:
1. `ticker` -> `company_identifiers` (`id_type='psx_ticker'`, `value=<ticker>`, `valid_to IS NULL`) -> `company_id` (`cmp-*`) -> `companies`.
2. Today this resolves only for the **51 companies in the master**; e.g. SSGC, OGDC, APL, BAHL resolve, but **TPLP and CTM do not**. Unresolved tickers stay as items with the ticker in `source_metadata_json` and are queued for master expansion; never guess a link.
3. A formal company link exists only through `events` -> `event_evidence(source_item_id)` + `event_companies(company_id)`. `events` is empty today and needs classification fields (`event_type`, `status_stage`, `verification_state`, ...). Recommendation: **Phase A** ingest items only; **Phase B** a reviewed extraction step creates events (category -> `event_type`, `verification_state='single_source'`, evidence `claim_type='official_statement'` only if checked against the PSX filing) with human review (`reviewer_status='pending'`).

## Open decisions for the owner
1. Written permission from Investify or an owner-approved ingest of facts-only rows? (Currently: no ingest.)
2. Confirm `source_id='investify'` + `access_status='restricted'` (vs `permitted` if permission is obtained).
3. Master expansion for tickers outside the 51 companies.
