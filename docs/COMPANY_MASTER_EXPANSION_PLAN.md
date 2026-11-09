# Company master expansion — design (PLAN ONLY, nothing written to Turso)

Input: `data/psx_profiles.json` (owner says 540 profiles; file not yet visible in the repo — design is based on the owner's
pasted sample: `symbol, company_name, sector, listing_status, isin, fiscal_year_end`). Script: `backend/company_master_loader.py`
(plan/dry-run only; no write path exists in it). Tests: `backend/test_company_master_loader.py`.

## Existing master (Turso, 2026-11-09)
51 companies (50 listed, 1 delisted FFBL), 51 `psx_ticker` identifiers, **0 ISINs**, 152 aliases (ticker / legal_name / short_name),
14 PSX sectors, classifications per company, all provenance pointing at `psx_dps` company-page `source_items` (items 2..52).
Loaded 2026-11-07 via `dataset_loads('reference_data', record_count=51)`.

## Field mapping
| Profile field | Target | Rule |
|---|---|---|
| `symbol` | `companies.company_id = cmp-<lowercase ticker>`; `company_identifiers(id_type='psx_ticker', value=<UPPER>)` | must match `^[A-Z0-9]{1,16}$`; else rejected |
| `company_name` | `companies.legal_name`; alias `legal_name` | required |
| `listing_status` | `companies.listing_status` | `Active`->`listed`, `Delisted`->`delisted`, `Suspended`->`suspended`; anything else rejected (no guessing) |
| `fiscal_year_end` ("June 30") | `companies.fiscal_year_end_month` | month name -> 1..12; unparseable -> rejected |
| `isin` | `company_identifiers(id_type='isin')` | **only if the ISO 6166 check digit passes**; otherwise ISIN dropped and flagged, company kept |
| `sector` | `company_classifications` -> `sectors.sector_id` | matched on normalised name (case, `&`/`and`, punctuation); **no new sectors are created implicitly** |
| (derived) | aliases: `ticker` and `legal_name`, `confidence='derived'`, evidence = dataset provenance | not `verified`: we did not read these from a PSX page |

## Overlap strategy (the 51 existing companies)
Matched by ticker. **Existing rows are never updated, replaced or deleted.** Each overlap is classified `identical` or
`CONFLICT` (name / listing status / fiscal-year month / sector) and listed for owner review. A new ISIN for an existing
company is reported separately and only added if approved. UNIQUE keys containing NULL `valid_from` do not dedupe in
SQLite, so the real loader must use explicit existence checks, not `INSERT OR IGNORE`, for `company_identifiers` and
`company_classifications`.

## Provenance (needs owner answers)
- `companies.profile_source_item_id` and the child `source_item_id` columns are nullable, but the 51 existing rows all
  cite a source item. Proposal: one `source_items` seed row (`retrieval_method='seed'`, `document_type='dataset'`,
  `content_sha256` = SHA-256 of the JSON file, `external_id='dataset:psx_profiles_v1'`) under a **new** source
  `owner_psx_profiles` (`source_type='other'`, disabled, `access_status='unverified'`), referenced by every new profile,
  plus `dataset_loads('psx_profiles_v1', sha256, record_count)`. Creating that source row needs approval.
- **Origin of the file:** described as "public structural mappings". The 51 existing profiles were read from `psx_dps`
  pages, a RESTRICTED / `prohibits_automation` source. If any of the 540 trace back to automated reads of those pages, the
  restriction applies. The seed source's `notes` must record the true origin; no claim of ToS compliance is made by the loader.

## Write budget (Turso free tier)
Estimated for N new companies: ~`6N` rows (company, ticker identifier, ISIN if valid, 2 aliases, classification) plus 3-4
bookkeeping rows. Worst case ~489 new -> ~2,950 rows, on top of index writes. The scheduled collector hit its per-run limit
at ~4,950 rows written, so apply in **chunks of <=100 companies per run**, each with its own `collector_runs` row, resumable
(plan re-computed each run, already-loaded tickers skipped), with `rows_written` reported from `turso_db.usage_report()`.

## Findings from the owner's sample (not the full file)
1. **SSGC sector conflict:** sample says "Gas, Water and Multiutilities"; master has `OIL & GAS MARKETING COMPANIES`.
   Different taxonomies/labels: the master's PSX sector scheme must stay the source of truth (CHECK `scheme='PSX'`).
2. **ISINs fail validation:** `PK0035010103` (SSGC) and `PK0037010100` (OGDC) both fail the ISIN check digit. If the full
   file's ISINs behave the same, none can be loaded as verified identifiers.
3. OGDC is identical to the master apart from case/`&` (sector matches after normalisation).

## Owner decisions (2026-11-09) and current status
1. **Seed source approved:** new source `owner_psx_profiles` (disabled, `lifecycle_status=RESTRICTED`, `access_status=unverified` — a source cannot be both `restricted` and `unverified` in `access_status`, so "restricted" is carried by `lifecycle_status`) plus a `dataset_loads('psx_profiles_v1')` record, written only when the whole file has been loaded. Origin note recorded as the owner's statement: profiles aggregated from publicly available structural listings of the PSX corporate directory (not restricted individual pages); not independently verified by the assistant.
2. **Defaults approved:** invalid ISINs dropped (company kept); master's sector labels win; unknown sectors leave the company unclassified; no sectors created.
3. **Full file:** NOT yet received (the message announcing it contained no attachment or JSON; `data/psx_profiles.json` is not in the repo). No real counts exist yet and nothing has been written to Turso.
4. **Apply path built and tested offline** (`--apply`, <=100 new companies per run, resumable, idempotent, never touches existing companies); 7 tests against the production DDL. Not run against Turso.

## Stub mode (owner decision 2026-11-09: iterative, verified-only; no fabricated profiles)
`python backend/company_master_loader.py --stubs [--names names.json] [--apply --chunk N]`
- **Candidates:** tickers present in `source_items.source_metadata_json.ticker` (source `investify`) but missing from `company_identifiers`.
- **Stub = ticker + legal name only:** `companies(listing_status='unknown', fiscal_year_end_month NULL, profile_source_item_id=<first announcement item>)`, a `psx_ticker` identifier, `ticker` and `legal_name` aliases marked `candidate`. No ISIN, no classification.
- **A name is mandatory** (`companies.legal_name NOT NULL`) and must be verified: either `source_metadata_json.company_name` on the item, or an owner-supplied `--names` entry that carries an `evidence` note. Otherwise the ticker is reported as `needs_name`. Names are never derived from filing titles.
- **Resolution of announcements:** no update to `source_items` (append-only). Announcements link by ticker through `company_identifiers`; once a stub exists the existing join resolves automatically (`resolution_coverage()` reports linked-now vs linked-after).
- **Idempotent and chunked**, one `collector_runs` row (`company_master_stub_load`) per apply; existing companies never touched.

### Dry run against Turso (2026-11-09, read-only)
16 unlinked tickers, **0 creatable**, 16 `needs_name`; announcement coverage 4/21 linked now, 4/21 after stubs. Reason: the 21 ingested items store only ticker/category/title, no company name.

### Ways to obtain verified names (decision needed)
1. Extend the Investify parser/mapping to capture the card's company-name attribute (a public fact shown in the approved DOM map but outside the five approved fields) into `source_metadata_json`; backfill the 21 existing items requires one more fetch (2 requests) and an UPDATE of that JSON column (not blocked by the immutability triggers).
2. Owner supplies a `names.json` (`symbol`, `company_name`, `evidence`).
3. SCS chart `/symbols` (existing approved source for OHLCV; a name read would need a new approval entry).
