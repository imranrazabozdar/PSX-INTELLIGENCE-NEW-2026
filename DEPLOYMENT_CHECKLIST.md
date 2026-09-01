# Deployment Checklist - Scan Refresh Fixes

## Pre-Deployment ✅

- [x] Code fixed and tested locally
- [x] 6 commits ready (staged and committed)
- [x] 3 critical code sections identified
- [x] Documentation complete
- [x] Fallback guides prepared
- [x] No breaking changes to other features

---

## Deployment (Choose ONE)

### ✅ Option A: Push from Your Machine

```bash
cd /c/Users/IMRAN/Desktop/PSX_Intelligence_V4_6_GitHub_Ready
git push origin main
```

- [ ] Navigate to project directory
- [ ] Run push command
- [ ] If successful → Skip to "Post-Deployment"
- [ ] If fails → Try Option B

**Time:** 2 minutes

---

### ✅ Option B: GitHub Web Editor

1. [ ] Open: https://github.com/imranrazabozdar/PSX-INTELLIGENCE-NEW-2026
2. [ ] Click: `backend/app.py`
3. [ ] Click: Pencil icon (Edit)
4. [ ] Apply Fix #1: Replace watchlist_scan function (line ~4535)
   - [ ] Find: `def watchlist_scan(request:Request, force:bool=False):`
   - [ ] Replace with code from MANUAL_DEPLOYMENT.md
5. [ ] Apply Fix #2: Replace _watchlist_refresh_loop (line ~4219)
   - [ ] Find: `async def _watchlist_refresh_loop():`
   - [ ] Replace entire function
6. [ ] Apply Fix #3: Update dss() function (line ~2982)
   - [ ] Find: `sym = symbol.upper()`
   - [ ] Replace the error handling section
7. [ ] Click: "Commit changes..."
8. [ ] Message: `fix: Enable scan refresh and end-of-day cache`
9. [ ] Choose: "Commit directly to main"
10. [ ] Click: "Commit changes"

**Time:** 5-10 minutes

---

### ✅ Option C: Wait for GitHub

- [ ] Wait for GitHub connectivity to improve
- [ ] Try Option A again
- [ ] If it works, proceed to "Post-Deployment"

**Time:** Unpredictable (hours to days)

---

## Post-Deployment (After Push/Commit Succeeds)

### Step 1: Verify Deployment ⏱️ (Wait 1-2 minutes)

- [ ] Streamlit Cloud pulls new code (automatic)
- [ ] Embedded backend restarts
- [ ] Check status at: https://dashboard.streamlit.io/ (your app)

### Step 2: Check Backend Status

- [ ] Open Streamlit app
- [ ] Wait for "App is running"
- [ ] Check logs (if available)
- [ ] Look for: "Application startup complete"

### Step 3: Test Manual Refresh

- [ ] Go to: Technical Patterns tab (or any scan tab)
- [ ] Click: "Refresh" button
- [ ] Watch: "Background refresh running..." message
- [ ] Wait: 4-5 minutes for scan to complete
- [ ] Verify: Data age changed from "1000+ min" to "< 5 min"

### Step 4: Verify Fix #1 ✅

- [ ] Open browser console (F12 → Console tab)
- [ ] Call API: `/api/watchlist/scan?force=true`
- [ ] Expected response:
  ```json
  {
    "status": "ok",
    "_background_refresh_running": true
  }
  ```
- [ ] If you see this → Fix #1 working! ✅

### Step 5: Verify Fix #2 (End-of-Day)

- [ ] Wait until after 4:00 PM PSX (if before that time)
- [ ] Check backend logs for:
  - `[scan_cache] Running end-of-day watchlist scan...`
  - `[scan_cache] End-of-day watchlist scan complete`
- [ ] If you see these → Fix #2 working! ✅

### Step 6: Verify Fix #3 (Turso Fallback)

- [ ] After market hours (after 3:30 PM PSX)
- [ ] Click refresh button again
- [ ] Scans should still complete (using Turso)
- [ ] No "data unavailable" errors → Fix #3 working! ✅

---

## Success Criteria

After deployment, you should see:

- [ ] Manual refresh button triggers scans immediately
- [ ] Scans complete within 4-5 minutes
- [ ] Cache age shows "< 5 minutes" (not "1000+ minutes")
- [ ] No errors in backend logs
- [ ] Automatic scan runs at 4:00 PM PSX
- [ ] Data available 24/7 after hours
- [ ] Refresh works multiple times (not just once)

---

## Troubleshooting

### If deployment doesn't complete:
- [ ] Check Streamlit Cloud dashboard for errors
- [ ] View app logs for error messages
- [ ] Look for Python syntax errors
- [ ] Check indentation (Python is spacing-sensitive)
- [ ] Verify all 3 fixes were applied

### If refresh button still doesn't work:
- [ ] Confirm FIX #1 was applied correctly
- [ ] Check for Python syntax errors
- [ ] Verify indentation in watchlist_scan function
- [ ] Restart the app
- [ ] Clear browser cache (Ctrl+Shift+Del)

### If after-hours data fails:
- [ ] Check Turso credentials in Streamlit secrets
- [ ] Verify FIX #3 was applied (dss() fallback)
- [ ] Check backend logs for Turso errors
- [ ] Ensure LIBSQL_URL and LIBSQL_AUTH_TOKEN are set

### If end-of-day scan doesn't run:
- [ ] Check PSX timezone is correct (PSX_TZ)
- [ ] Verify FIX #2 was applied (_watchlist_refresh_loop)
- [ ] Look at backend logs around 4:00 PM
- [ ] Check for errors in end-of-day scan code

---

## Rollback (If Needed)

If something breaks:

```bash
git revert <commit-hash>
git push origin main
```

Streamlit will auto-deploy the revert. The changes are isolated and won't break other features.

---

## Reference Documents

- **MANUAL_DEPLOYMENT.md** → Exact code for all 3 fixes
- **DEPLOYMENT_GUIDE.md** → Detailed technical info
- **FIX_SUMMARY.md** → Complete documentation
- **STATUS.md** → Current deployment status

---

## Timeline

| Phase | Status | Time |
|-------|--------|------|
| Deploy | Choose option above | 2-10 min |
| Streamlit redeploy | Automatic | 1-2 min |
| First test | Manual refresh | 5-10 min |
| Verification | All checks | 2-5 min |
| **Total** | **~15-30 min** | ✅ |

---

## Done! 🎉

Once you complete all steps above:

✅ Manual refreshes work  
✅ End-of-day cache populates automatically  
✅ After-hours data available via Turso  
✅ Scans show fresh data (< 5 minutes old)  
✅ No more "1000+ minutes old" messages  

Your scan refresh issues are **completely resolved**!

---

**Need Help?** Check the relevant document:
- Code won't push → STATUS.md (deployment methods)
- Don't know what to change → MANUAL_DEPLOYMENT.md (exact code)
- Want technical details → FIX_SUMMARY.md (full documentation)
- Step-by-step guide → DEPLOYMENT_GUIDE.md (detailed instructions)

