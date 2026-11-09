# Relevance prefilter (`extract/relevance.py`, rules `extract/relevance_rules.json`, version `relevance@v2`)

Runs BEFORE any model call. Deterministic, no model, every decision carries its reasons.

**Score** = entity points + the highest-weight matched term of each keyword group; **pass** when score >= threshold (2).
- Entities (from the DB): PSX tickers (UPPERCASE whole words only; +4, +1 more if on the watchlist), company names/aliases (whole phrase, >=2 words and >=8 chars after stripping legal suffixes; +4).
- Keyword groups (weights in the rules file): `corporate`, `regulatory`, `markets`, `commodities` (positive), `geo` (+1), `foreign_noise` (negative).
- **Ambiguous tickers** (rules: `ambiguous_tickers`, currently `PPP`) count only when another substantive signal corroborates them.
- **Context-only signals never pass alone**: `geo` and small source bonuses need a substantive signal (entity or keyword group); a source bonus >= 3 (PBS, official statistics) counts as substantive by design.
- **Source bonus**: `pbs` +3, `brecorder_markets` +1, `brecorder` +1.
- With a prefilter the pipeline scans a window of pending items (`--scan`, default 300), then sends the first `--limit` relevant ones, so irrelevant newer items cannot starve relevant older ones. Skipped items are not marked anywhere (they are re-scored next run; cheap, no model call).

**Tuning evidence (407 stored headlines from verified_permitted sources, 2026-11-09):**
| Version | Threshold | Pass | Notes |
|---|---|---|---|
| v1 | 3 | 19 (4%) | missed NEPRA tariff, forex reserves, inflation; "PPP" matched a political party in 3 headlines |
| v2 | 2 | 57 (14%) | ambiguous-ticker rule, geo/source context rules, foreign-noise penalties; 5 earlier irrelevant headlines all skipped |

Known remaining noise (accepted, recall favoured because the model quota is far larger than the pass rate): foreign
inflation/IPO stories, vendor PR mentioning SBP, PBS items that are not market-relevant (e.g. a WaterAid MoU).
Recall check is manual: review skipped headlines periodically and adjust weights, bumping the rules `version`.

Run: `python fundamental_engine/scripts/run_extraction.py --task news_event_extraction --limit 10` (dry run, prefilter on; `--no-prefilter` to disable).
