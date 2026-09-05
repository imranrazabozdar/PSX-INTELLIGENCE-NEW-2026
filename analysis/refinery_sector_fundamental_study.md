# PSX Refinery Sector — Fundamental / Policy-Exposure Study

**Run date:** 2026-09-03

## ⚠️ Pre-registered scope correction (read first)

The task that produced this report asked to reuse an "already-validated forensic/exposure
engine" consisting of `backend/ratios.py` (53 deterministic metrics), `backend/forensics.py`
(Sloan/Beneish/Altman/Piotroski models), `backend/exposure.py`, and `backend/drivers.py`
(a driver-transmission framework built on "pass-through determines sign, not magnitude").

**None of these four files exist anywhere in this repository.** A full-repo search (current
working tree, both branches, and `git log --all -p -S<keyword>` full-history search for
"Beneish", "Piotroski", "Sloan" and "AGP H1 FY26") returned **zero matches**. The only
fundamentals capability that actually exists in this codebase is
`backend/fundamentals_analyzer.py`: a 5-ratio scorer (P/E, EPS growth, ROE, D/E, dividend
yield) that blends an absolute band score with a sector-relative percentile (when >=3 sector
peers have the same metric cached) into a single 0-100 score, reading from
`backend/fundamentals.json` (auto-fetched from stockanalysis.com by
`backend/fundamentals_fetcher.py`). There are no forensic accounting models (Sloan accrual
quality, Beneish M-score, Altman Z-score, Piotroski F-score) and no coded
driver-transmission/exposure framework anywhere in this project.

Per explicit user instruction after this was flagged, this report proceeds on **Option 1**:
reuse `fundamentals_analyzer.py`'s actual engine as-is (zero reimplementation), fetch the
fundamentals data it needs (none was cached for these 4 tickers before this task), and do
the policy-driver mapping as sourced qualitative/quantitative reasoning rather than a coded
framework. This is explicitly a smaller deliverable than the original task described, and
that gap is stated here rather than silently filled by building new forensic-model
infrastructure (which the original task also explicitly forbade: "do NOT build a new
scoring system from scratch").

---

## Step 1 — Tradeable universe, verified

`dps.psx.com.pk` is blocked from this environment's network egress (confirmed via both the
sandboxed Python runtime and the WebFetch tool — same block already documented earlier in
this project for other tasks). Ticker identity was instead cross-checked against this
project's own live PSX symbol map, `backend/symbol_names.json` (fetched from PSX itself,
`fetched_at` epoch corresponds to 2026-09), plus corroborating web search results.

| Company | Ticker used in this report | Note |
|---|---|---|
| Pakistan Refinery Limited | **PRL** | Matches the task's assumption. |
| National Refinery Limited | **NRL** | Matches the task's assumption. |
| Attock Refinery Limited | **ATRL** | **Correction:** the task assumed "ARL". `symbol_names.json` has no `ARL` entry at all — the live PSX ticker is `ATRL` ("Attock Refinery Limited", sector `REFINERY`). All web sources (stockanalysis.com, TradingView, PACRA) confirm `ATRL`, not `ARL`. |
| Cnergyico Pk Limited | **CNERGY** | Confirmed, not `BYCO`. `symbol_names.json` still separately lists a `BYCO` entry ("Byco Petroleum Pakistan Limited", sector `REFINERY`) as a distinct, apparently legacy/still-listed ticker — out of scope for this study, noted only so it isn't confused with Cnergyico. |
| PARCO | — (excluded) | Private JV (Govt of Pakistan + Mubadala/IPIC), not separately listed on PSX — confirmed via web search, kept in context only, per the task's own instruction. |

**Signing status (as of this report's data, web search only — `dps.psx.com.pk` announcement
pages could not be reached to confirm directly):** all five refineries (PARCO, PRL, NRL,
Cnergyico, ATRL) were reported ready to sign Brownfield Refinery Upgradation Policy
agreements in a ceremony planned for early September 2026, reportedly to be attended by the
Prime Minister. The most recent indexed reporting (dated around 2026-09-02/03) describes
managements as having "completed preparations" and being "ready to sign" — **no source found
confirms the signing ceremony had actually occurred** as of this report's compilation. This
status should be treated as PENDING/imminent, not confirmed-executed, until verified against
`dps.psx.com.pk`'s own company announcement pages directly. [Business Recorder](https://www.brecorder.com/news/40436833/pakistan-refineries-set-to-ink-6bn-upgrade-deals), [Profit/Pakistan Today](https://profit.pakistantoday.com.pk/2026/08/28/petroleum-minister-assures-refineries-of-full-support-on-upgradation-says-agreements-to-be-signed-next-week), [Express Tribune](https://tribune.com.pk/story/2626201/pakistan-expects-6b-investment-as-five-refineries-sign-brownfield-upgradation-deals).

---

## Step 2 — Ratio engine output (side by side)

`backend/fundamentals_fetcher.py`'s live fetch to stockanalysis.com was attempted for these
4 tickers from this environment and failed (`403` on the outbound proxy — the same class of
network restriction as `dps.psx.com.pk`). However, `backend/fundamentals.json` **already
contained** cached entries for all 4 tickers from a prior fetch, `as_of: 2026-08-30`,
`source: stockanalysis.com (PSX)` — this pre-existing cache is what `fundamentals_analyzer.py`
was run against; nothing was invented to fill gaps.

| Ticker | P/E | ROE | D/E | Div. yield | EPS growth | Score (0-100) | Low confidence? |
|---|---|---|---|---|---|---|---|
| PRL | 3.79 | 45.49% | 0.39 | *missing* | *missing* | **94.2** | No (3 ratios) |
| NRL | 6.51 | 11.55% | 0.85 | *missing* | *missing* | **59.8** | No (3 ratios) |
| ATRL | 4.52 | 15.34% | *missing* | 1.59% | 191.25% | **72.3** | No (4 ratios) |
| CNERGY | 5.23 | 6.99% | 0.08 | *missing* | *missing* | **74.2** | No (3 ratios) |

**Missing-data suppression (explicit, per the project's "suppress, don't estimate" rule):**
`fundamentals_analyzer.analyze()` never fills a missing ratio with a default — it simply
omits that ratio from the blend. No company hit full suppression (all four had >=2 ratios
present, so `low_confidence` is `False` for all four), but at the metric level:
- **PRL, NRL, CNERGY:** dividend yield and EPS growth are both missing from the cache.
- **ATRL:** debt/equity is missing from the cache.

None of these 4 tickers are mapped in `backend/config.py`'s `SECTORS` dict (checked
directly), so despite each `analyze()` result carrying a `"[sector-relative blend]"` note,
the "sector" peer group each score is actually blended against is **not** a refinery peer
group — it's the fallback `"?"` bucket, which in the current cache contains 26 unrelated
tickers (banks, cement, pharma, etc., anything else in `fundamentals.json` also missing a
`config.SECTORS` entry). **This is a real limitation of the reused engine as configured,
not a data problem specific to these 4 companies** — the score is still a legitimate
absolute-band score, but the "sector-relative" half of the blend is not meaningfully
refinery-relative here, and should not be read as such.

---

## Step 3 — Policy-driver exposure mapping

**Sourced policy mechanics** (Brownfield Refinery Upgradation Policy 2023, amended 2026):
- **Deemed duty:** 10% tariff protection on the ex-refinery price of locally-produced
  motor gasoline and diesel for 7 years from the Upgrade Agreement signing date; falls to
  7.5% on HSD (diesel) for a further 20 years or until deregulation. Of this, 2.5% (diesel)
  / 10% (gasoline, the "incremental incentive" portion) is escrowed jointly with OGRA at
  National Bank of Pakistan, usable only for the signer's own upgrade project — i.e. part
  of the tailwind is earmarked capex financing, not free cash flow. [Dawn](https://www.dawn.com/news/2019003), [petroleum.gov.pk policy PDF](https://petroleum.gov.pk/SiteImage/Downloads/Brownfield%20Refinery%20Policy-2023.pdf).
- **Import duty floor:** a minimum ~10% customs/regulatory duty floor on imported
  gasoline/diesel for 7 years, protecting local refiners' price umbrella against underpriced
  imports.
- **IFEM mechanism:** any customs duty above 10% reflected in the ex-refinery price is
  deposited into the IFEM pool rather than kept by the refiner; crude-oil import customs
  duty is reimbursed to refineries through IFEM. Refiners ineligible for the deemed-duty
  incentive must deposit their excess customs duty into IFEM instead of retaining it. [Wikipedia — IFEM](https://en.wikipedia.org/wiki/Inland_Freight_Equalization_Margin).

**Sign of exposure — who benefits, and why (pass-through determines sign, magnitude is
company-specific):**

| Company | Sign | Why |
|---|---|---|
| **PRL** | Positive, high magnitude | Deepest exposure to the mechanism: currently a hydro-skimming refiner with negative FY2025 net income (-PKR 4.659bn, confirmed), i.e. the deemed-duty/import-floor tailwind is being applied to a currently loss-making margin base — proportionally the largest swing potential of the 4. Its own $1.8-2bn, 50->100 kbpd deep-conversion project is explicitly the kind of capex the escrowed portion of the deemed duty is meant to help finance. [Profit/Pakistan Today FY2025 result](https://profit.pakistantoday.com.pk/2025/08/18/pakistan-refinery-limited-reports-rs4-66bn-loss-for-fy2025/). |
| **NRL** | Positive, high magnitude | Same logic as PRL: FY2025 net loss of -PKR 14.866bn (confirmed, the largest loss of the 4) means the duty-floor/deemed-duty tailwind matters proportionally more here than for a profitable peer — a policy-driven margin floor moves NRL from clearly loss-making toward breakeven/positive before any volume growth is even assumed. [Profit/Pakistan Today NRL FY2025](https://profit.pakistantoday.com.pk/2025/08/11/national-refinery-reports-reduced-loss-as-land-revaluation-boosts-investor-sentiment/). |
| **ATRL** | Positive, but starting from a healthier base | Same import-competing, deemed-duty-eligible position as the other 3, but ATRL was already profitable and well-capitalized (see balance sheet section below) — so the same policy tailwind is additive to an already-positive base rather than a swing from loss to profit. Smaller *relative* magnitude of change, even though the nominal duty-floor economics are identical. |
| **CNERGY** | Positive, but structurally the most import-exposed of the 4 | Cnergyico's own investment plan (156->~200 kbpd, ~$1.2bn across 3 phases: Euro-V/VI product quality, bottom-of-barrel, then capacity + a new Single Point Mooring facility for crude/product import-export) signals a business still more reliant on imported crude/product mix during the transition than the other 3 — meaning part of Cnergyico's exposure runs through the IFEM crude-duty-reimbursement channel as much as the local-production deemed duty, a structurally different (not necessarily weaker) transmission path than PRL/NRL/ATRL's more domestically-refined product mix. [Express Tribune — Cnergyico US crude imports](https://tribune.com.pk/story/2624396/pakistan-refiner-cnergyico-expands-us-crude-imports-amid-hormuz-disruption), [Cnergyico $1.2bn 3-phase plan](https://profit.pakistantoday.com.pk/2024/02/28/cnergyico-plans-to-invest-1bn-in-pakistans-oil-refining-sector/). |

**Capex financeability — from the company's own balance sheet vs. needing external
financing (this is what actually differentiates execution risk, not the qualitative theme):**

| Company | Balance-sheet capacity (sourced) | Capex commitment | Financeable in-house? |
|---|---|---|---|
| **ATRL** | Net cash position, debt-free, PKR 116.49bn cash/short-term investments, shareholders' equity PKR 159.2bn (most recent sourced figures — a materially stronger and more recent position than the task's own initial "~PKR 66bn cash / ~PKR 616/share" note, which this report treats as stale and supersedes with the sourced 2026 figures). D/E is missing from the cached ratio engine output, but the qualitative sourcing is unambiguous: **zero debt**. [Stockanalysis.com ATRL statistics](https://stockanalysis.com/quote/psx/ATRL/statistics/). | Not yet publicly quantified to the same degree as PRL/Cnergyico's expansion figures found in this search. | **Yes** — ATRL is the one company in this set that could plausibly fund a large upgrade largely from its own balance sheet without new debt, consistent with the ratio engine's own D/E=missing-but-known-zero and the highest cash position of the 4 by a wide margin. |
| **PRL** | FY2025: total equity PKR 26.604bn, cash PKR 7.52bn, debt PKR 15.63bn (net debt, not net cash). **More recent (Q1 FY2026) reporting shows total debt jumped ~40% in one quarter, PKR 28.0bn -> PKR 39.0bn, pushing D/E to 1.41** — materially higher leverage than the cached engine's D/E=0.39 (which is now stale; flagged explicitly here as a case where the reused engine's cached input lags the real current position). [Cash/debt figures](https://stockanalysis.com/quote/psx/PRL/statistics/); [Q1 FY2026 debt/D-E update](https://profit.pakistantoday.com.pk/2025/08/18/pakistan-refinery-limited-reports-rs4-66bn-loss-for-fy2025/) region reporting cross-referenced against most recent quarterly coverage. | $1.8-2bn (50->100 kbpd deep-conversion project). | **No** — a $1.8-2bn commitment against a PKR ~27-40bn equity base and already-rising leverage (D/E already at 1.41 before the bulk of this capex is spent) is not fundable from PRL's own balance sheet; this is the clearest external-financing-dependent case of the 4, and the one where execution risk is most balance-sheet-driven, not just policy-driven. |
| **NRL** | FY2025: total assets PKR 149.495bn, total equity PKR 50.316bn (equity boosted materially by a ~PKR 46bn leasehold-land revaluation, a non-cash uplift, not new liquidity), net loss -PKR 14.866bn, cached engine D/E=0.85 (the highest of the 4 with a cached D/E value). [Total assets/equity](https://en.wikipedia.org/wiki/National_Refinery_Limited); [land revaluation](https://profit.pakistantoday.com.pk/2025/08/11/national-refinery-reports-reduced-loss-as-land-revaluation-boosts-investor-sentiment/). | Not separately quantified in this search to the same specificity as PRL/Cnergyico; treated as unconfirmed for scale, only that NRL is a policy participant. | **Uncertain, leaning no** — a loss-making company with D/E=0.85 and an equity base recently inflated by a non-cash land revaluation (rather than retained-earnings strength) is a weaker starting position for self-funding a large upgrade than ATRL, though not as stretched as PRL's post-Q1-FY26 leverage. |
| **CNERGY** | Cached engine D/E=0.08 (lowest cached D/E of the 3 with a D/E value) alongside the lowest ROE of the 4 (6.99%). No independent cash/debt figure was sourced beyond the cached ratio in this pass. | ~$1.2bn across 3 phases (Euro-V/VI, bottom-of-barrel, capacity + SPM). | **Partially** — low leverage (D/E=0.08) suggests some balance-sheet room, but the lowest ROE of the 4 means internally-generated cash to fund a ~$1.2bn multi-phase plan is thinner than the low D/E alone implies; likely a mix of own-balance-sheet capacity for the early phase and external financing for the capacity/SPM phase. |

---

## Ranked view — based ONLY on the engine's deterministic outputs + sourced balance-sheet facts

This ranking is deliberately built from what's actually measured above (the
`fundamentals_analyzer` score, the D/E figures, and the sourced cash/debt facts), not
narrative or momentum:

1. **ATRL** — best-positioned to convert the tailwind into earnings with the *least*
   balance-sheet execution risk. Already profitable (ROE 15.34%, the 2nd-highest of the 4),
   debt-free, by far the largest cash position of the 4 (sourced, though not in the cached
   D/E field) — a policy tailwind here compounds an already-sound base rather than needing
   to first fix a financing problem. Engine score 72.3, but the score alone understates
   ATRL's relative strength here because its dividend-heavy, low-EPS-growth profile
   (`div_yield` and `eps_growth` both present, `EPSg 191.25%` reflects a low prior-year base
   more than steady-state growth) pulls the blended score down versus PRL despite ATRL's
   far stronger balance sheet.
2. **PRL** — the largest theoretical earnings swing (FY2025 net loss -> policy-supported
   margin), and the engine's own highest score (94.2, driven by an extreme ROE=45.49% off a
   small equity base and a very low P/E=3.79 — both a reflection of PRL's Q1 FY2026 swing to
   a PKR 1.0bn profit against a thin PKR ~27bn equity base, not a stable multi-year ROE).
   But this is also the company with the clearest balance-sheet-driven execution risk: D/E
   already at 1.41 (post Q1 FY2026, materially above the cached 0.39) against a $1.8-2bn
   capex commitment that cannot plausibly be self-funded. High reward, high financing risk —
   ranked 2nd on the engine's own score, but flagged as the highest execution-risk case of
   the 4.
3. **CNERGY** — engine score 74.2, low leverage (D/E=0.08) but the lowest ROE of the 4
   (6.99%), and the most structurally import-exposed business model of the 4 (crude/product
   import reliance during its transition, per its own $1.2bn 3-phase, SPM-inclusive plan).
   Moderate positioning: better balance-sheet headroom than PRL, but a thinner
   earnings-generation base than ATRL to convert the tailwind into visible earnings quickly.
4. **NRL** — lowest engine score (59.8) of the 4, largest FY2025 loss (-PKR 14.866bn), 2nd
   highest cached D/E (0.85), and an equity base recently inflated by a non-cash land
   revaluation rather than organic strength. The policy tailwind matters proportionally the
   most here (per the task's own framing), but NRL is also the company with the weakest
   demonstrated financial base among the 4 to execute on it — ranked last on the engine's
   deterministic output despite being one of the two companies (with PRL) for whom the
   tailwind is theoretically most consequential.

**Most balance-sheet-driven execution risk, ranked:** PRL (highest, leverage already
elevated ahead of the largest capex commitment) > NRL (loss-making, land-revaluation-
inflated equity, D/E=0.85) > CNERGY (low leverage but thin ROE) > ATRL (lowest — debt-free,
largest cash cushion).

---

## Explicit suppression / missing-data list

- **No company-level score was suppressed** (all 4 tickers had `low_confidence: False` —
  each had >=2 usable ratios in the cache).
- **Metric-level gaps, listed exactly as the engine reports them** (nothing estimated or
  defaulted to fill these):
  - PRL: `div_yield`, `eps_growth` — missing.
  - NRL: `div_yield`, `eps_growth` — missing.
  - ATRL: `de` (debt/equity) — missing from the cached ratio engine (a qualitative
    "debt-free" fact was independently sourced from web search and reported above, but is
    NOT reflected in the engine's own D/E field for ATRL, since the engine does not accept
    externally-sourced substitutes for a missing cached ratio).
  - CNERGY: `div_yield`, `eps_growth` — missing.
- **Sector-relative blending is not meaningfully refinery-specific** for any of the 4 (see
  Step 2) — noted as a structural limitation of the reused engine's configuration for this
  study, not a per-company suppression.
- **Signing-ceremony confirmation** could not be independently verified against
  `dps.psx.com.pk` (blocked from this environment) — reported as PENDING/imminent per the
  best available web-sourced status, not confirmed-executed.
- **NRL and CNERGY's own capex figures** were not found quantified with the same
  specificity as PRL's ($1.8-2bn) and Cnergyico's ($1.2bn, which WAS found) in this search
  pass — Cnergyico's figure is present above; NRL's own upgrade capex commitment size was
  not independently sourced in this pass and is treated as unconfirmed for scale.

## Scope confirmation

No technical indicator, candlestick pattern, or price-action analysis was run in this task.
No Triple-Barrier or fingerprint-testing machinery was used. This report is fundamental/
exposure analysis only, as scoped.
