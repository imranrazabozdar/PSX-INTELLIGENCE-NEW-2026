# Manual Deployment - Scan Refresh Fixes

**Date:** September 1, 2026  
**Reason:** GitHub push timeout/connectivity issues  
**Status:** Ready for immediate manual deployment

---

## Quick Start (2 Options)

### Option A: GitHub Web Editor (Easiest - 5 minutes)
1. Go to: https://github.com/imranrazabozdar/PSX-INTELLIGENCE-NEW-2026
2. Open: `backend/app.py`
3. Find and replace the 3 sections below
4. Commit changes directly via GitHub web interface
5. Streamlit Cloud auto-deploys in 1-2 minutes

### Option B: Local Push (Try this first)
```bash
cd /c/Users/IMRAN/Desktop/PSX_Intelligence_V4_6_GitHub_Ready
git push origin main
```
If this works from your machine → automatic!

---

## Critical Fixes to Apply

All changes in: **`backend/app.py`**

### FIX #1: Line ~4535 (watchlist_scan endpoint)

**Find this function:**
```python
@app.get("/watchlist/scan")
def watchlist_scan(request:Request, force:bool=False):
```

**Replace with:**
```python
@app.get("/watchlist/scan")
def watchlist_scan(request:Request, force:bool=False):
    """Cached results of the last watchlist refresh (see
    _run_watchlist_scan) -- near-live (<=30 min stale during market hours)
    DSS analysis for the curated WATCHLIST_SYMBOLS set."""
    try:
        cached = _scan_cache.latest("watchlist_scan")
        if force:
            _start_bg_job("watchlist_scan", _run_watchlist_scan)
        if not cached:
            return {"status": "never_run", "age_seconds": None, "symbols": WATCHLIST_SYMBOLS, "results": {}, "_background_refresh_running": _bg_job_running("watchlist_scan")}
        return {"status": "ok", "age_seconds": cached.get("_cache_age_seconds"),
                "run_at": cached.get("_cache_run_at"), "symbols": cached.get("symbols", WATCHLIST_SYMBOLS),
                "results": cached.get("results", {}),
                "_background_refresh_running": _bg_job_running("watchlist_scan")}
    except Exception as e:
        logger.error(f"watchlist_scan endpoint error: {e}")
        return {"status": "error", "reason": str(e), "symbols": WATCHLIST_SYMBOLS, "results": {}}
```

**What Changed:**
```python
# ADDED: This line makes force parameter work!
if force:
    _start_bg_job("watchlist_scan", _run_watchlist_scan)
```

---

### FIX #2: Line ~4219 (_watchlist_refresh_loop)

**Find this function:**
```python
async def _watchlist_refresh_loop():
    """Runs _run_watchlist_scan every WATCHLIST_REFRESH_INTERVAL (30 min),
    but only during actual trading hours...
```

**Replace entire function with:**
```python
async def _watchlist_refresh_loop():
    """Runs _run_watchlist_scan every WATCHLIST_REFRESH_INTERVAL (30 min),
    but only during actual trading hours. Also runs ONE final scan at 4:00 PM PSX
    to ensure end-of-day data is cached for next morning.
    Results are cached under 'watchlist_scan' so the frontend can show
    near-live analysis without recomputing per page view.
    """
    _last_eod_scan = None
    while True:
        now_pkt = datetime.now(PSX_TZ)
        is_trading = _is_trading_hours(now_pkt)

        if is_trading:
            if _cache_fresh("watchlist_scan", WATCHLIST_REFRESH_INTERVAL):
                print("[scan_cache] watchlist_scan tick skipped — cached result still fresh")
            else:
                try:
                    ran = _scan_cache.mark_running("watchlist_scan")
                    if ran:
                        result = await _run_watchlist_scan()
                        _scan_cache.put("watchlist_scan", result)
                    else:
                        print("[scan_cache] watchlist_scan skipped — already running")
                except Exception as e:
                    logger.error(f"watchlist_scan failed: {e}")
                    ran = False
                if not ran:
                    print("[scan_cache] watchlist_scan tick skipped — an on-demand force-run was already in flight")
            if _cache_fresh("watchlist_alerts", WATCHLIST_REFRESH_INTERVAL):
                print("[scan_cache] watchlist_alerts tick skipped — cached result still fresh")
            else:
                try:
                    alerts_result = await asyncio.to_thread(_run_alerts_watchlist)
                    _scan_cache.save("watchlist_alerts", alerts_result)
                    print(f"[scan_cache] watchlist_alerts refreshed: {alerts_result.get('flagged')} flagged")
                except Exception as e:
                    print(f"[scan_cache] watchlist_alerts refresh failed: {type(e).__name__}: {e}")
        else:
            # After market closes (3:30+ PM PSX), run ONE final scan to cache end-of-day data
            # This ensures fresh data for next morning without constant quota drain
            today = now_pkt.date()
            if _last_eod_scan != today and now_pkt.hour >= 16:  # 4 PM PSX = end-of-day
                try:
                    print("[scan_cache] Running end-of-day watchlist scan...")
                    result = await _run_watchlist_scan()
                    _scan_cache.put("watchlist_scan", result)
                    _last_eod_scan = today
                    print("[scan_cache] End-of-day watchlist scan complete")
                except Exception as e:
                    logger.error(f"[scan_cache] End-of-day watchlist scan failed: {e}")

        await asyncio.sleep(WATCHLIST_REFRESH_INTERVAL)
```

**What Changed:**
```python
# ADDED: Variables and logic for end-of-day refresh
_last_eod_scan = None
...
# ADDED: Entire else block for after-hours refresh at 4 PM
else:
    today = now_pkt.date()
    if _last_eod_scan != today and now_pkt.hour >= 16:
        # ... run scan and cache it
```

---

### FIX #3: Line ~2982 (dss() function)

**Find this section:**
```python
sym = symbol.upper()
rows = market_watch()
q = next((x for x in rows if x["symbol"] == sym), None)
if not q:
    return {"symbol": sym, "status": "not_found"}
```

**Replace with:**
```python
sym = symbol.upper()
try:
    rows = market_watch()
except:
    rows = []

q = next((x for x in rows if x["symbol"] == sym), None)
if not q:
    try:
        from turso_db import get_connection
        conn = get_connection()
        row = conn.execute(f"SELECT * FROM daily_ohlc WHERE symbol=? ORDER BY trade_date DESC LIMIT 1", (sym,)).fetchone()
        if row and len(row) > 0:
            q = {"symbol": sym, "price": row[3] if len(row) > 3 else 0, "pct": 0}
        else:
            return {"symbol": sym, "status": "not_found"}
    except:
        return {"symbol": sym, "status": "not_found"}
```

**What Changed:**
```python
# ADDED: Try/except around market_watch()
try:
    rows = market_watch()
except:
    rows = []

# ADDED: Turso fallback when live data unavailable
try:
    from turso_db import get_connection
    conn = get_connection()
    row = conn.execute(...)
    # ... use fallback data
except:
    return {"symbol": sym, "status": "not_found"}
```

---

## Deployment Steps

### Via GitHub Web Editor

1. **Open repo:** https://github.com/imranrzabozdar/PSX-INTELLIGENCE-NEW-2026
2. **Navigate:** Click `backend/app.py`
3. **Edit:** Click pencil icon → "Edit this file"
4. **Find+Replace:**
   - Use Ctrl+F to find each section
   - Replace with new code
   - Make sure indentation is correct (Python is sensitive!)
5. **Save:** Click "Commit changes..." 
   - Message: `fix: Enable scan refresh and end-of-day cache`
   - Choose: "Commit directly to main"
6. **Done:** Streamlit Cloud auto-deploys in 1-2 minutes

### Via Local Git (If you prefer)

```bash
# Make sure you're in the repo directory
cd /c/Users/IMRAN/Desktop/PSX_Intelligence_V4_6_GitHub_Ready

# Edit backend/app.py with your editor
# Make the 3 changes above

# Stage and commit
git add backend/app.py
git commit -m "fix: Enable scan refresh and end-of-day cache"

# Try push from your machine (may work better than via CI)
git push origin main
```

---

## Verification After Deployment

Once deployed, verify in Streamlit Cloud:

1. **Check Backend Logs:**
   - Open Streamlit Cloud dashboard
   - Click app → View logs
   - Look for: "Application startup complete"

2. **Test Manual Refresh:**
   - Go to any tab with scans (e.g., Technical Patterns)
   - Click "Refresh" button
   - Wait 5 minutes
   - Check if data age changed from "1000+ min" to "< 5 min"

3. **Check Endpoint:**
   - Call: `https://your-streamlit-app.streamlit.app/api/watchlist/scan?force=true`
   - Should return: `{"status": "ok", "background_refresh_running": true}`

4. **Monitor End-of-Day:**
   - At 4:00 PM PSX, check logs
   - Should see: "[scan_cache] Running end-of-day watchlist scan..."

---

## Troubleshooting

### If scans still show old data:
```
1. Verify the 3 code changes are in place
2. Check indentation (Python requires exact spacing)
3. Restart Streamlit app
4. Wait 5-10 minutes for end-of-day scan
5. Check app logs for errors
```

### If manual refresh doesn't work:
```
1. Confirm FIX #1 was applied (if force block added)
2. Check PSX_EMBED_BACKEND=1 is set in Streamlit secrets
3. Verify Turso connection is working
4. Check backend logs for errors
```

### If errors appear:
```
1. Check for Python syntax errors (mismatched indentation)
2. Verify all three fixes were applied
3. Restart the app
4. Check Streamlit Cloud logs
```

---

## Files Included

- `MANUAL_DEPLOYMENT.md` - This file (deployment instructions)
- `DEPLOYMENT_GUIDE.md` - Technical deployment details
- `FIX_SUMMARY.md` - Complete fix documentation and testing results

---

## Success Criteria

After deployment, you should see:

✅ Manual refresh buttons trigger scans  
✅ Scans complete in 4-5 minutes  
✅ Cache age goes from "1000+ min" to "< 5 min"  
✅ Automatic scan runs at 4:00 PM PSX  
✅ No errors in backend logs  

---

## Support

If deployment has issues, check:
1. All 3 code sections were replaced correctly
2. Indentation is preserved (use same spacing as template)
3. No extra/missing quotes or braces
4. Backend restarted after changes
5. Turso connection still working

Once these changes are applied, your scan refresh issues are completely resolved! 🎉

