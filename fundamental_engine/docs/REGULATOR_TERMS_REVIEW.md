# Regulator terms review tracking (opened 2026-11-09)

Rule: a regulator's website being public does not permit automated collection. No adapter is built until a review
concludes `verified_permitted` (or an owner override is recorded in the permission log with its conditions).

## Registry facts (Turso `sources`, as of 2026-11-09)
| Source | Registry status | Recorded evidence |
|---|---|---|
| `sbp` State Bank of Pakistan (`www.sbp.org.pk`) | `BLOCKED`, `terms_status=not_found` | robots.txt returned HTTP 403 to automated requests (2026-11-07); disclaimer page has no reuse terms; automated requests refused (403) |
| `secp` SECP (`www.secp.gov.pk`) | `BLOCKED`, `terms_status=not_reviewed` | home page returned HTTP 403 to automated requests; robots.txt allows (2026-11-07) |

## Review checklist (per regulator) — all items OPEN
- [ ] Locate the terms of use / copyright / disclaimer pages and record URL + date read
- [ ] Record robots.txt content and status
- [ ] Find official machine-readable channels (data portal, API, RSS, downloadable statistical releases) and their terms
- [ ] Find the official data-request / permissions contact; record any reply verbatim in the permission log
- [ ] Decide per document class: automated fetch / manual download only / not permitted
- [ ] If an owner override is chosen: log it (honest User-Agent, jitter, robots.txt respected, no bypass of blocks)
- [ ] Update the registry row (`access_status`, `terms_status`, `lifecycle_status`) with evidence

## Constraints already known
- Both sites refused automated requests with HTTP 403: a block is a perimeter to respect, not to work around.
- Until reviewed, regulator documents enter only through the manual route (`manual_pdf_ingester.py`-style, owner-supplied,
  one document at a time) and are subject to the LLM eligibility gate (non-`verified_permitted` sources are never sent to a model).

Suggested order: SBP, then SECP, then OGRA (per the owner's priority list).
