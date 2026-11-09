# Extraction quality: de-duplication, entity resolution, source-content acquisition, evaluation

Constraints honoured: no migrations; no review decisions or reviewer stamps; append-only review controls untouched; no production batch run;
provider credentials, source permissions and spending limits unchanged; nothing in the database is written by any new code path.

## 1. Inspection (2026-11-09, read-only)
- **Registry:** 11 `verified_permitted` sources, all `retention_mode='metadata_only'`; registry notes: "approved for automated collection, metadata only (headline, link, publisher, timestamp)". No source permits article-body or disclosure-text storage.
- **Acquisition architecture:** the RSS collectors live outside this repo; `fundamental_engine/sources/` was empty. `source_items` stores titles/links; `permitted_excerpt` is empty for every item.
- **Master:** 67 companies, 67 ticker identifiers, 152 aliases (legal_name, short_name; no brand/former-name/abbreviation), 51 classifications (16 stubs unclassified), **no** `company_relationships` or `company_segments` rows. `story_clusters` / `story_cluster_members` exist (empty) and fit de-duplication without a migration.

## 2. Cross-source story de-duplication (`extract/dedup.py`, `dedup@v1`)
- `normalize_title`: NFKC, case-fold, quote/dash unification, publisher suffix/prefix and wire prefix removal ("- Business Recorder", "| Dawn.com", "UPDATE 2 -"), punctuation removal, `Rs 6.59`=`Rs6.59`, `12.31 percent`=`12.31%`=`12.31pc`, `1,500`=`1500`, leading articles dropped. **Numbers are kept**: different figures are different facts.
- Same normalised-token fingerprint = **exact duplicate** -> the pipeline skips the model call (`duplicates_skipped`, `model_calls_avoided`), against both already-extracted items and earlier items in the same batch. **Near-duplicates** (token Jaccard >= 0.8, identical numbers, >= 4 tokens) are only **reported**, never skipped.
- Originals are never modified; no duplicate marker is written anywhere. `cluster_plan()` shows how exact groups could be persisted in the existing `story_clusters` tables if the owner approves (not executed).
- Not detected by design: reworded versions of the same story (measured below).

## 3. Source-content acquisition (`sources/acquire.py`, `acquire@v1`) - framework only; zero sources eligible today
Gates, all default-refuse: registry (`verified_permitted` + enabled + `terms_status=approved` + `retention_mode` in `excerpt`/`full_text_permitted`), robots.txt (disallow, 401/403 or unreachable = no fetch), paywall/CAPTCHA/WAF detection (HTTP 401/402/403/429/503, body markers, teaser-length text), honest UA only, 4.5-9.5 s jitter before every request, per-run request budget, a block stops that source for the run. Output: text + manifest (url, SHA-256, status, robots result, UA, timestamps, retention mode, `text_basis='full_text'`) in the document vault; refusals are remembered in the manifest; the database is not touched. `load_acquired()` returns text only if its hash still matches.
**Current outcome:** `scripts/acquire_content.py` reports all 11 sources ineligible (metadata only) and refuses; no request is ever made. Enabling any source for article text is a source-permission change that only the owner can make.
**Text basis honesty:** every candidate now records `text_basis` (`headline` | `excerpt` | `full_text`) and `evidence_scope`; headline-only candidates carry the review reason "headline_only: findings describe the headline, not the full article"; legacy candidates are reported as headline. Full text is used only when acquired through this module, hash-verified, and the registry permits it; it is never inferred from a headline.

## 4. PSX entity resolution (`extract/entities.py`, `entities@v1`, rules `extract/exposure_rules.json`)
- **direct** (the text names the company): tickers (uppercase whole words; ambiguous ones such as `PPP` need corroboration), legal/short names, brand/former/abbreviation aliases, subsidiaries that are themselves in the master; each with `matched_by` and `confidence`.
- **indirect** (kept separate, rule-based, low confidence, direction always unknown, rationale attached): sector/commodity rules map terms (fuel prices, gas/LNG, power tariff, interest rates, cement, fertilizer, IT exports) to master sectors and, via `company_classifications`, to companies not already named; parents of a named subsidiary.
- **unresolved**: unknown parenthesised tickers, shared names, ambiguous tickers without corroboration, subsidiaries not in the master. Nothing in `unresolved` is ever promoted to a ticker. The stored candidate also flags model-proposed tickers that deterministic resolution does not support.
- Data limits: brand/subsidiary/segment matching is implemented but the master has no such rows yet, so today only ticker and name matching fire. Sector rules are the owner's to tune (low confidence by design).

## 5. Evaluation (`extract/evaluate.py`, `scripts/eval_extraction.py`, `eval@v1`) - deterministic, no model calls, no writes
Controlled synthetic sample (hand-labelled; `tests/fixtures/eval_sample.json`) and read-only production metrics.

| Metric | Controlled sample | Production (live Turso, 2026-11-09) |
|---|---|---|
| Dedup precision / recall | 1.00 / 0.83 (misses the reworded pair) | - |
| Stored headlines / exact duplicates | - | 407 / 19 (4.7%); 2 near-duplicate pairs reported |
| Duplicates among relevance-passing items (would otherwise cost model calls) | - | 5 of 52 = 9.6% (5 model calls avoidable if all were extracted) |
| Candidates / headline-only | - | 15 / 15 |
| Grounded-quote rate (re-verified against the stored headline) | validator agreement 8/8, 0 false accepts | 5/5 = 1.00; candidates with a quote 5/15 = 0.33 |
| Inferences containing digits | rejected by validator | 0 of 1 |
| Direct company match rate | precision 1.00 / recall 1.00 (11 cases) | 0/15 (no company is named in these headlines) |
| Sector/commodity (indirect) match rate | precision 1.00 / recall 1.00 | 3/15 = 0.20 |
| Useful event rate (grounded quote AND direct or indirect hit) | - | 2/15 = 0.13 |
| Model calls avoidable (duplicate candidates in past runs) | - | 2 of 15 |
| Invented tickers | 0 | 0 |

The controlled sample was written by the same author as the code: it checks behaviour and regressions, it is not independent validation. Production rates are on 15 headline-only candidates from non-market-biased test runs; treat them as a baseline, not a quality claim.

## Known limitations
- Headline-only input caps extraction yield (all permitted sources are metadata-only); no article text can be acquired until the owner changes a source's retention mode.
- Dedup does not catch reworded duplicates; near-duplicate reporting has no persisted record (no migration); exact-duplicate skips are not stored as clusters.
- Entity resolution covers 67 companies; 16 stubs have no sector; no brands/subsidiaries/segments exist in the master; sector rules are heuristic.
- The acquisition manifest lives in the vault, not the database (no schema change allowed); text acquired this way has no DB pointer until the owner approves one.
