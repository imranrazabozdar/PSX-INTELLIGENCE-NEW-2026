# Engine Fixes + Catalyst-Exposure Extension

**Run date:** 2026-09-03

---

## Fix 1 — Missing-engine discrepancy: one more targeted check, then closed

The earlier refinery study (`analysis/refinery_sector_fundamental_study.md`) confirmed via
full-tree, full-history search across both branches of this repo
(`imranrazabozdar/PSX-INTELLIGENCE-NEW-2026`) that `backend/ratios.py`, `forensics.py`,
`exposure.py`, and `drivers.py` — the described 53-metric ratio engine, Sloan/Beneish/
Altman/Piotroski forensic models, 90x37 exposure matrix, and driver-transmission framework —
do not exist anywhere in that repository.

This task's one more targeted check was to look for the same code under a different name in
other repositories this GitHub account can reach, and to rule out a `.gitignore`-excluded
local-only subdirectory.

**`.gitignore` check:** no pattern in this repo's `.gitignore` excludes a whole subdirectory
(only `__pycache__/`, `*.db`, logs, backups, and similar generated/binary artifacts are
excluded) — nothing consistent with a `psxwatch/` or `engine/` source tree being silently
hidden from git.

**Other repositories found on this account** (via `list_repos`): this session could list
them, but a direct access attempt (`get_file_contents` on
`imranrazabozdar/Engine-Fundamentals`) was refused — this session's GitHub access is scoped
to `PSX-INTELLIGENCE-NEW-2026` only, and no `add_repo` tool was available in this session to
widen that scope. Rather than guess at their contents, this is reported as an **open lead,
not a closed negative** — the four candidate repository names, in order of how likely each
is to be the actual home of the described engine:

1. **`imranrazabozdar/Engine-Fundamentals`** — flagged as the most likely match: the name
   matches what this project's own notes describe, and it's a separate, purpose-named repo
   (not a fork of this one), consistent with a ratio/forensic engine having been built and
   pushed there independently of this intelligence-app repo.
2. `imranrazabozdar/PSX-ENGINE-NEW`
3. `imranrazabozdar/PSX-ENGINE-2.0`
4. `imranrazabozdar/PSX-INTELLIGENCE-2026` (private — the predecessor project to this one;
   plausible the engine was built there before this repo was created)

**Working assumption going forward, per explicit user instruction:** this repo
(`PSX-INTELLIGENCE-NEW-2026`) does not contain the described engine, and Fix 2 / the
Extension below proceed on that basis, reusing only what actually exists here
(`fundamentals_analyzer.py`). If the code is later found in one of the four repos above, that
would change what "reuse, don't rebuild" means for future tasks — but confirming or ruling
that out is explicitly **not** done in this task, and no forensic-model or exposure-matrix
code was written here to compensate. This is stated once, plainly, as instructed, and Fix 1
is closed.

---

## Fix 2 — Stale-data detection added to `fundamentals_analyzer.py`

### Where the input data actually comes from

`fundamentals_analyzer.analyze(symbol)` merges two sources, config wins over cache:
1. **`backend/fundamentals.json`** — a flat cache written by `fundamentals_fetcher.py`,
   which scrapes `stockanalysis.com/quote/psx/<symbol>/` (both its `statistics/` sub-page for
   `pe`, `roe`, `de`, `div_yield`, and its main quote page for `eps_growth`). The cache
   stores a single **global** `as_of` date (currently `2026-08-30`) — the date the values
   were last *scraped*, not a per-company filing date. stockanalysis.com's own pages don't
   expose which fiscal period each ratio is computed from (they present a rolling
   trailing-twelve-month/most-recent-annual figure without a labeled "as of" period), so the
   existing pipeline had **no way to know, per company, how old the underlying financials
   actually were** — that was the root cause of the PRL D/E=0.39-vs-1.41 gap the refinery
   study caught.
2. **`config.FUNDAMENTALS`** — a manually-maintained override dict (empty for all 4 refinery
   tickers currently).

### What was added

- `STALENESS_THRESHOLD_DAYS = 120` (~one quarterly filing cycle).
- `FUNDAMENTALS_FILING_DATE_OVERRIDE` — a small, manually-maintained, **sourced-only** dict
  (same honest pattern as `config.FUNDAMENTALS` itself) for symbols where separate research
  has independently confirmed the cached ratios' true underlying filing date is materially
  older than the cache's own fetch timestamp. Populated with exactly the two cases this
  project has actually verified:
  - `"PRL": "2025-06-30"` — FY2025 annual result (net loss -PKR 4.659bn), reported
    2025-08-18 (Profit/Pakistan Today); the cached D/E=0.39 was shown in the refinery study
    to already be stale versus a later Q1 FY2026 debt increase to D/E=1.41.
  - `"NRL": "2025-06-30"` — FY2025 annual result (net loss -PKR 14.866bn), reported
    2025-08-11 (Profit/Pakistan Today).
- `_data_as_of(symbol, cache_as_of)` — returns the override date if one exists, otherwise
  the cache's own recorded fetch date. **Never today's date, never a guess** — every value
  this function can return is a real, sourced date already present either in
  `fundamentals.json` or in the override dict's citation comment.
- `_staleness(data_as_of)` — `age_days = today - data_as_of`; `stale = age_days > 120`.
- `analyze()`'s return dict now always carries `data_as_of`, `age_days`, `stale`, and (when
  `stale` is true) an added note: `"STALE — verify against latest filing (data_as_of=...,
  N days old, threshold=120)."`
- `raw_ratios(symbol)` — a small new accessor exposing the merged raw ratio dict (`pe`,
  `roe`, `de`, ...) that `analyze()` already computed internally but didn't expose; added
  because `catalyst_exposure.py` (the Extension, below) needs a specific raw value rather
  than `analyze()`'s human-formatted `"have"` strings. This is exposing existing internal
  data, not new computation.

### Test results

| Ticker | `data_as_of` | `age_days` | `stale` |
|---|---|---|---|
| **PRL** | 2025-06-30 (sourced override) | 430 | **True** — matches the known-bad case |
| NRL | 2025-06-30 (sourced override) | 430 | True |
| **ATRL** | 2026-08-30 (cache fetch date, no override) | 4 | **False** — proves the flag isn't always-on |
| CNERGY | 2026-08-30 (cache fetch date, no override) | 4 | False |
| MARI (unrelated sanity check) | 2026-08-30 | 4 | False |
| HUBC (unrelated sanity check) | 2026-08-30 | 4 | False |

PRL correctly flags STALE; ATRL is the confirmed fresh/not-stale counter-example (CNERGY
also fresh) — the two-symbol requirement from the task is satisfied, and two unrelated
symbols (MARI, HUBC) were spot-checked to confirm the change didn't break anything for the
rest of the universe.

---

## Extension — `catalyst_exposure.py`

### Design

`backend/catalyst_exposure.py` generalizes the refinery study's manual method:
`fundamentals_analyzer.py`'s 5-ratio scorer (now staleness-flagged) + sourced, dated
qualitative reasoning about a catalyst's differential impact. It does **not** invent
domain classifications — which companies are net beneficiaries vs. exposed to a given
catalyst is business/sector knowledge the caller must supply, sourced and dated, exactly
like "PRL is a hydro-skimming, import-competing local producer" was sourced research in the
refinery study, not something derivable from 5 generic ratios.

`analyze_catalyst(tickers, catalyst, classifications, extra_facts=None)`:
- `classifications[ticker]` is **required** for a ticker to appear at all — `sign`
  (`"beneficiary"`/`"exposed"`), `reason`, `source`, `date`, and optionally `loss_making`
  (+ its own source/date). A ticker with no entry is **suppressed**, not defaulted.
- **Theoretical magnitude** axis: `"high"` if the caller sourced `loss_making=True`
  (biggest swing potential); `"lower"` if sourced `loss_making=False`; `None` (unavailable,
  never guessed) if `loss_making` wasn't supplied at all.
- **Execution capacity** axis: derived from the ratio engine's D/E — but **the module
  refuses to trust a `stale`-flagged D/E at face value**, reporting
  `"UNVERIFIED — cached D/E is stale"` instead, unless the caller supplies a sourced
  `execution_override` (a corrected D/E + citation) explicitly *because* the cached value
  is known to be wrong or missing. This is Fix 2's staleness flag doing real work one layer
  up, not just sitting in a report.
- A ticker with **zero** fundamentals data at all in the engine is suppressed from the
  ranking entirely (sign classification alone is not a score).
- `format_report()` renders a plain two-axis comparison table, mirroring the refinery
  study's own presentation rather than collapsing both axes into one artificial blended
  rank.

### Re-run: the refinery case through `catalyst_exposure.py`

Same catalyst (deemed duty + import duty floor), same 4 tickers, same sign classifications
as the manual study (all 4 are beneficiaries — none scoped as "exposed" in this run) — with
`loss_making` sourced exactly as the manual study cited it (PRL/NRL: True, per their FY2025
losses; ATRL/CNERGY: False, per positive cached ROE).

**Pass A — no sourced execution override (the module's default, staleness-aware behavior):**

| Ticker | Magnitude | Execution capacity |
|---|---|---|
| PRL | high | **UNVERIFIED — cached D/E is stale** |
| NRL | high | **UNVERIFIED — cached D/E is stale** |
| ATRL | lower | ? (D/E missing from cache, no override supplied) |
| CNERGY | lower | strong (low leverage) — D/E=0.08 cached, not stale |

**Pass B — with the same sourced corrections the manual study used** (PRL's Q1 FY2026
D/E=1.41; ATRL's debt-free position expressed as D/E=0.0, both cited):

| Ticker | Magnitude | Execution capacity |
|---|---|---|
| PRL | high | **weak (high leverage)** — D/E=1.41, sourced override |
| NRL | high | **UNVERIFIED — cached D/E is stale** (no correction was ever independently sourced for NRL, so it stays honestly unresolved) |
| ATRL | lower | **strong (low leverage)** — D/E=0.0, sourced override |
| CNERGY | lower | strong (low leverage) |

### Comparison to the original manual study

**Pass B reproduces the manual study's ranking exactly:** ATRL = lowest theoretical
upside / lowest execution risk (safest); PRL = highest theoretical upside / highest
execution risk; CNERGY = lower upside / strong execution (moderate); NRL = high upside,
same theme as PRL. No ranking reversal occurred — the refreshed, staleness-checked run
confirms the manual study's conclusion rather than overturning it.

**One material, worth-reporting difference: NRL.** The manual study used NRL's cached
D/E=0.85 directly to describe NRL's execution capacity as "weaker... though not as
stretched as PRL." `catalyst_exposure.py`, applying Fix 2's staleness rule strictly, refuses
to do that — NRL's D/E is flagged `stale` (same `FUNDAMENTALS_FILING_DATE_OVERRIDE` entry as
PRL, since both share the same FY2025-06-30 filing anchor) and **no sourced correction for
NRL's current D/E was ever independently found** in this project's research. So the module
correctly reports NRL's execution capacity as **unresolved**, not "weak" — a more honest
position than the manual study's, which had implicitly trusted a cached ratio without
flagging it as unverified. This is exactly the kind of gap Fix 2 was built to catch: **the
manual study's NRL execution read was partly an artifact of not having a staleness check at
the time**, not a wrong conclusion necessarily, but an unjustifiably confident one. Closing
this gap for real would require the same kind of targeted web research already done for PRL
and ATRL — not done in this task, per its own scope boundary against building a live
scraper/backfill.

---

## Files changed

- `backend/fundamentals_analyzer.py` — added `STALENESS_THRESHOLD_DAYS`,
  `FUNDAMENTALS_FILING_DATE_OVERRIDE`, `_data_as_of()`, `_staleness()`, `raw_ratios()`;
  `analyze()`'s return dict now carries `data_as_of`/`age_days`/`stale` and a STALE note
  when applicable. No existing behavior (score computation, sector-relative blending,
  `low_confidence` logic) was changed.
- `backend/catalyst_exposure.py` — new module, `analyze_catalyst()` + `format_report()`.
- `analysis/engine_fixes_and_extension_report.md` — this report.

No technical indicator, candlestick, or price-pattern analysis was run in this task. No new
forensic-model or exposure-matrix engine was built to fill Fix 1's gap.
