#!/usr/bin/env python3
"""One-off Phase 1 discovery probe, round 5: chart.scstrade.com is the
real, self-hosted UDF datafeed backing TA_RealTimeCharting.aspx (round 4
confirmed /config, /symbols, /history, /marks all resolve to
scstrade.com's own subdomain, not tradingview.com). This round hits it
directly with plain requests (no browser needed -- it's a public JSON
API) to confirm: (1) what resolutions /config declares as supported
(does it offer real intraday/1-minute, not just 1D?), (2) the correct
symbol format for a real stock via /symbols, (3) whether /history
actually returns genuine 1-minute OHLCV bars for a real trading day."""
import json
from datetime import datetime, timedelta, timezone

import requests

BASE = "https://chart.scstrade.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.scstrade.com/TechnicalAnalysis/TA_RealTimeCharting.aspx",
    "Accept": "application/json",
}


def get(path, **params):
    r = requests.get(f"{BASE}{path}", params=params, headers=HEADERS, timeout=20)
    print(f"GET {r.url}")
    print(f"  status={r.status_code} content-type={r.headers.get('content-type')}")
    try:
        data = r.json()
        text = json.dumps(data)
        print(f"  body[:1500]: {text[:1500]}")
        return data
    except Exception as e:
        print(f"  (not JSON) body[:500]: {r.text[:500]!r}  error={e!r}")
        return None


print("=== /config ===")
cfg = get("/config")

print()
print("=== /symbols for AICL ===")
sym = get("/symbols", symbol="AICL")

print()
print("=== /symbols for KSE 100 (known-good from round 4) ===")
get("/symbols", symbol="KSE 100")

# Find a recent PSX trading day (skip weekend) and ask for 1-minute bars
now = datetime.now(timezone.utc)
day = now
for _ in range(10):
    day = day - timedelta(days=1)
    if day.weekday() < 5:  # Mon-Fri
        break
day_start = day.replace(hour=3, minute=30, second=0, microsecond=0)   # ~09:30 PKT in UTC (PKT = UTC+5)
day_end = day.replace(hour=11, minute=0, second=0, microsecond=0)     # ~16:00 PKT in UTC
from_ts, to_ts = int(day_start.timestamp()), int(day_end.timestamp())

print()
print(f"=== /history for AICL, resolution=1 (1-minute), {day.date()} ===")
get("/history", symbol="AICL", resolution="1", **{"from": from_ts, "to": to_ts})

print()
print(f"=== /history for AICL, resolution=1D (sanity check, should work like round 4) ===")
get("/history", symbol="AICL", resolution="1D", **{"from": int((now - timedelta(days=30)).timestamp()), "to": int(now.timestamp())})
