#!/usr/bin/env python3
"""fetch_premove_data.py — ONE-OFF data-collection script for the
AICL/SHFA pre-move study (analysis/AICL_SHFA_premove_study.md).

Not part of the app's regular pipeline. Exists because the interactive
session sandbox's network egress blocks dps.psx.com.pk directly (same
constraint documented in backend/news_fetcher.py's own docstring: "the
sandbox where Claude runs can't reach Pakistani news hosts ... GitHub
Actions can"). This script is meant to run in a GitHub Actions
workflow_dispatch job (real, unrestricted network egress) and print
everything to stdout as JSON, one block per section, so the run's logs
are the data-transport mechanism back into the session.

Sources, all read-only, no invented data:
  - OHLC: backend/dps_scraper.fetch_psx_dps_ohlc() -- PSX's own Data
    Portal historical table (already used by the project's real daily
    backfill), NOT yfinance/training knowledge.
  - Company announcements: dps.psx.com.pk/company/{SYMBOL} -- same
    table-row extraction approach as backend/app.py's
    announcement_intelligence(), but keeping the FULL row text (every
    cell) rather than classifying it, since this study wants the raw
    disclosed facts, not a POS/NEG/materiality guess.
  - PSX-wide notices: dps.psx.com.pk/announcements/psx -- no existing
    scraper for this in the codebase, so this is new, straightforward
    table-row extraction, filtered client-side to rows whose text
    mentions the symbol or company name. If the page's structure turns
    out to differ from what's assumed here, this prints a diagnostic
    (row count, first row's raw HTML) instead of silently returning
    nothing, so a structure mismatch is visible, not swallowed.
"""

import json
import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent.parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import requests
from bs4 import BeautifulSoup

import dps_scraper

HEAD = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

TARGETS = [
    {"symbol": "AICL", "company_hint": "Adamjee",
     "ohlc_start": "2026-07-08", "ohlc_end": "2026-08-07",
     "ann_start": "2026-07-08", "ann_end": "2026-08-10"},
    {"symbol": "SHFA", "company_hint": "Shifa",
     "ohlc_start": "2026-05-28", "ohlc_end": "2026-06-18",
     "ann_start": "2026-05-28", "ann_end": "2026-06-22"},
]


def fetch_company_announcements(symbol):
    url = f"https://dps.psx.com.pk/company/{symbol.upper()}"
    try:
        r = requests.get(url, headers=HEAD, timeout=20)
        r.raise_for_status()
    except Exception as e:
        return {"symbol": symbol, "source": url, "error": f"{type(e).__name__}: {e}", "rows": []}

    soup = BeautifulSoup(r.text, "html.parser")
    rows = []
    for tr in soup.select("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.select("td")]
        if len(cells) >= 2 and cells[0]:
            rows.append({"cells": cells})
    return {"symbol": symbol, "source": url, "error": None, "row_count": len(rows), "rows": rows}


def fetch_psx_wide_notices(keywords):
    url = "https://dps.psx.com.pk/announcements/psx"
    try:
        r = requests.get(url, headers=HEAD, timeout=20)
        r.raise_for_status()
    except Exception as e:
        return {"source": url, "error": f"{type(e).__name__}: {e}", "matched_rows": [], "total_rows_seen": 0}

    soup = BeautifulSoup(r.text, "html.parser")
    all_rows = []
    for tr in soup.select("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.select("td")]
        if len(cells) >= 2 and cells[0]:
            all_rows.append(cells)

    matched = []
    for cells in all_rows:
        joined = " ".join(cells).lower()
        if any(k.lower() in joined for k in keywords):
            matched.append({"cells": cells})

    diag = None
    if not all_rows:
        diag = {"note": "no <tr> with >=2 <td> found -- page structure may differ from assumption",
                "first_2000_chars_of_body": soup.get_text(" ", strip=True)[:2000]}

    return {"source": url, "error": None, "total_rows_seen": len(all_rows),
            "matched_rows": matched, "diagnostic_if_zero_rows": diag}


def main():
    output = {"ohlc": {}, "company_announcements": {}, "psx_wide_notices": {}}

    for t in TARGETS:
        sym = t["symbol"]
        print(f"--- Fetching OHLC for {sym} ({t['ohlc_start']} to {t['ohlc_end']}) ---", file=sys.stderr)
        df = dps_scraper.fetch_psx_dps_ohlc(sym, start_date=t["ohlc_start"], end_date=t["ohlc_end"])
        output["ohlc"][sym] = {
            "requested_start": t["ohlc_start"], "requested_end": t["ohlc_end"],
            "rows_returned": len(df),
            "dates_present": df["date"].tolist() if len(df) else [],
            "bars": df.to_dict("records") if len(df) else [],
        }

        print(f"--- Fetching company announcements for {sym} ---", file=sys.stderr)
        output["company_announcements"][sym] = fetch_company_announcements(sym)

        print(f"--- Fetching PSX-wide notices, filtering for {sym}/{t['company_hint']} ---", file=sys.stderr)
        output["psx_wide_notices"][sym] = fetch_psx_wide_notices([sym, t["company_hint"]])

    print("===JSON_START===")
    print(json.dumps(output, indent=2, default=str))
    print("===JSON_END===")


if __name__ == "__main__":
    main()
