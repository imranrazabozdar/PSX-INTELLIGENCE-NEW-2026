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

## Decisions needed
1. Provide the full file (push, upload or paste) so real counts replace the estimates.
2. Provenance: approve the `owner_psx_profiles` seed source, and state the file's true origin.
3. ISINs: drop invalid ones (default) or investigate the source.
4. Sector conflicts: master's labels win (default), or list the differing ones for manual review.
5. Companies with sectors not in the master's 14: leave unclassified (default) or approve new sector rows.
