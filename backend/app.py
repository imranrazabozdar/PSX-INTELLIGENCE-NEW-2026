from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from datetime import datetime, timezone, time as dtime
from zoneinfo import ZoneInfo
import asyncio, io, json, math, os, statistics, requests, time
import concurrent.futures as _cf
from bs4 import BeautifulSoup
import pandas as pd
from volume_engine import volume_analysis
from fundamentals_analyzer import analyze as fundamental_analysis
from intelligence_engine import ai_evidence_packet

# ---- V4.8: ported V1 analytics. Imported defensively so that a missing config
# key or module can NEVER stop the API from booting — each capability degrades
# to None and every call site checks before use.
try:
    import technical_analyzer as _v1_tech
    from legacy_adapter import eod_frame as _eod_frame
except Exception as _e:                                  # pragma: no cover
    _v1_tech = None; _eod_frame = None
    print(f"[V4.8] technical_analyzer unavailable: {_e}")

try:
    import shariah_checker as _v1_shariah
except Exception as _e:                                  # pragma: no cover
    _v1_shariah = None
    print(f"[V4.8] shariah_checker unavailable: {_e}")

try:
    import risk_manager as _v1_risk
except Exception as _e:                                  # pragma: no cover
    _v1_risk = None
    print(f"[V4.8] risk_manager unavailable: {_e}")

try:
    import portfolio_risk as _v1_book
except Exception as _e:                                  # pragma: no cover
    _v1_book = None
    print(f"[V4.8] portfolio_risk unavailable: {_e}")

try:
    import market_regime as _v1_regime
except Exception as _e:                                  # pragma: no cover
    _v1_regime = None
    print(f"[V4.8] market_regime unavailable: {_e}")

# ---- V4.9: the INTEGRATION layer. main.py (the V1 orchestrator) did not
# survive the port, which is why these engines never talked to each other.
# orchestrator.py rebuilds that pipeline.
try:
    import scoring_engine as _v1_scoring
except Exception as _e:                                  # pragma: no cover
    _v1_scoring = None
    print(f"[V4.9] scoring_engine unavailable: {_e}")

try:
    import signal_generator as _v1_signal
except Exception as _e:                                  # pragma: no cover
    _v1_signal = None
    print(f"[V4.9] signal_generator unavailable: {_e}")

try:
    import orchestrator as _orch
except Exception as _e:                                  # pragma: no cover
    _orch = None
    print(f"[V4.9] orchestrator unavailable: {_e}")

# ---- V4.10: merged in from the standalone psx/ terminal. psx_report is a pure
# indicator engine (no psxdata import at module scope — it's lazy inside
# load_from_psx, which this deployment never calls), psx_brain turns those
# indicators into a verdict/trade-plan, and psx_live is a stdlib-only adapter
# for the psxterminal.com live snapshot/breadth/tape API. All three degrade to
# None on import failure, same as every other layer above.
try:
    import psx_report as _psx_report
    import psx_brain as _psx_brain
except Exception as _e:                                  # pragma: no cover
    _psx_report = None; _psx_brain = None
    print(f"[V4.10] psx_brain/psx_report unavailable: {_e}")

try:
    import psx_live as _psx_live
except Exception as _e:                                  # pragma: no cover
    _psx_live = None
    print(f"[V4.10] psx_live unavailable: {_e}")

# ---- V4.11: read-only bridge into the sibling Engine Fundamentals project
# (psxwatch.db) — news impact scoring, the 53-metric ratio engine, and the
# driver-exposure model. See psxwatch_bridge.py for why this stays read-only
# and separate from psx_v2.db rather than a schema merge.
try:
    import psxwatch_bridge as _pw
except Exception as _e:                                  # pragma: no cover
    _pw = None
    print(f"[V4.11] psxwatch_bridge unavailable: {_e}")

# PSX's market-watch feed carries sector as a bare numeric code (e.g. "0804"),
# never a name -- see psx_sector_codes.py's docstring for where that was verified.
import psx_sector_codes as _sector_codes

# Decision Support System: assembles market-regime/sector-regime/Wyckoff/
# candlestick/price-action/relative-strength/risk-reward evidence this backend
# already computes into one confluence matrix + evidence score. See
# dss_engine.py's module docstring for what's real vs explicitly PENDING.
import dss_engine as _dss

# Real walk-forward pattern backtesting over stored true-OHLC — feeds the DSS
# historical-statistics and quant-baseline-validation layers with genuine
# numbers instead of PENDING. See backtest_engine.py's module docstring.
import backtest_engine as _bt

# Full Nison candlestick set, shared by live reads and the backtest scan.
import candlestick_engine as _candles

# Full Wyckoff event set (PS/SC/AR/ST/Spring/SOS/LPS + PSY/BC/AR/ST/UT/UTAD/SOW/LPSY),
# 9 Buying/Selling Tests, Al Brooks bar classification, volatility regime.
import wyckoff_engine as _wyckoff2
import price_action_engine as _pae

# Daily update mode, signal state machine, audit trail, failure analysis.
import audit_engine as _audit

# Walk-forward train/validation/out-of-sample split, transaction costs,
# correlation-based feature importance, and empirical calibration.
import walkforward_engine as _wf

# STEP 32: true multi-period (1W/1M/3M/6M/12M) relative strength vs KSE-100
# and same-sector backfilled peers — upgrades the session-only proxy.
import relative_strength_engine as _rse

# STEP 2-3: real data-quality audit and liquidity classification over stored
# true-OHLC, run before any pattern/indicator result is trusted.
import data_quality_engine as _dq

# STEP 27: pattern performance split by market/volatility regime.
# STEP 64: PSX-specific edge discovery beyond the fixed pattern library.
import regime_backtest_engine as _rbt

# Caches the expensive whole-market scan so it's computed once per refresh
# window, not on every request — see module docstring for why 5-minute
# recomputation of daily-bar analysis was wasted work.
import scan_cache_engine as _scan_cache

# Shared DB connection layer — local SQLite by default, or a Turso libSQL
# embedded replica when LIBSQL_URL/LIBSQL_AUTH_TOKEN are set (needed on
# hosts with no persistent disk, e.g. Streamlit Community Cloud). See
# turso_db.py's module docstring for the full explanation and the
# not-yet-smoke-tested caveat on the Turso path.
import turso_db

# ---- V4.12: official ticker -> company name map (dps.psx.com.pk/symbols).
try:
    import names as _names
except Exception as _e:                                  # pragma: no cover
    class _NamesStub:
        def name(self, s, default=None): return default if default is not None else s
        def load(self, force=False): return {}
    _names = _NamesStub()
    print(f"[V4.12] names unavailable: {_e}")

app = FastAPI(title="PSX Intelligence V2 API", version="3.3-real-intelligence")
PSX="https://dps.psx.com.pk"
MIN_VOLUME=50_000
HEAD={"User-Agent":"PSX-Intelligence-V2/2.0 private-research"}

# ---- Admin gate for expensive/mutating endpoints.
# The backfill, refresh and grading routes each fire dozens of outbound requests
# and write to disk. Left open, anyone who reaches the URL can run them in a
# loop — trivially turning this server into a source of abusive traffic against
# PSX/Yahoo/Google News, from YOUR IP. Set PSX_ADMIN_TOKEN and pass it as
# ?token=... (or X-Admin-Token) to enable them.
# Unset = localhost-only, which is the safe default for a laptop deployment.
ADMIN_TOKEN=os.getenv("PSX_ADMIN_TOKEN","")


def _require_admin(request):
    """Return None if allowed, else an error dict the route should return."""
    if ADMIN_TOKEN:
        supplied=(request.query_params.get("token")
                  or request.headers.get("x-admin-token") or "")
        if supplied==ADMIN_TOKEN:
            return None
        return {"status":"forbidden",
                "reason":"This endpoint is expensive and requires an admin token.",
                "how":"Pass ?token=... or the X-Admin-Token header. The token is "
                      "the PSX_ADMIN_TOKEN environment variable on the server."}
    host=(request.client.host if request.client else "")
    if host in ("127.0.0.1","::1","localhost"):
        return None
    return {"status":"forbidden",
            "reason":"Expensive endpoints are localhost-only until an admin "
                     "token is configured.",
            "how":"Set the PSX_ADMIN_TOKEN environment variable on the server, "
                  "then pass ?token=... with the request."}

_db_schema_ready = False


def db():
    """Returns the shared process-wide connection (turso_db.py — a plain
    local SQLite file by default, or a Turso libSQL embedded replica when
    LIBSQL_URL/LIBSQL_AUTH_TOKEN are set, e.g. on Streamlit Community Cloud
    which has no persistent disk of its own). Schema creation used to run on
    every single call — harmless-but-wasteful when each call got a genuinely
    fresh sqlite3 connection, actually worth avoiding now that every caller
    shares one persistent connection: run it once per process instead."""
    global _db_schema_ready
    c = turso_db.get_connection()
    if not _db_schema_ready:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots(ts TEXT,symbol TEXT,sector TEXT,listed TEXT,ldcp REAL,o REAL,h REAL,l REAL,p REAL,ch REAL,pct REAL,vol REAL,score REAL,setup TEXT,shariah INTEGER);
        CREATE INDEX IF NOT EXISTS ix_snap ON snapshots(symbol,ts);
        CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY AUTOINCREMENT,fetched_at TEXT,source TEXT,title TEXT,link TEXT,published TEXT,direction TEXT,materiality TEXT,symbols TEXT);
        CREATE TABLE IF NOT EXISTS predictions(id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT,symbol TEXT,signal TEXT,score REAL,entry REAL,stop REAL,target REAL,model_version TEXT,outcome TEXT);
        """)
        _db_schema_ready = True
    return c

def num(x):
    try:return float(str(x).replace(",","").replace("%","").strip())
    except:return 0.0

def _shariah_status(symbol, listed):
    """Shariah compliance, preferring the STRONGEST available evidence.

    PSX's own `listed` field states live index membership. KMI30 and KMIALLSHR
    ARE the Shariah indices — membership means the index provider has already
    applied the screen, and it is refreshed by the exchange every session. That
    is stronger evidence than a hand-maintained constituent list, which goes
    stale between semi-annual recompositions (OGDC, 2026-08: PSX reported
    KMI30+KMIALLSHR membership while the local list was 234 days old and
    excluded it, vetoing a valid setup to Avoid).

    So: live PSX membership is primary. shariah_checker runs as corroboration
    and its notes are always surfaced. Neither source is silently assumed —
    `shariah_method` records which one decided.
    """
    idx = [i.strip().upper() for i in (listed or "").split(",") if i.strip()]
    live = "KMI30" in idx or "KMIALLSHR" in idx
    checker = None
    if _v1_shariah is not None:
        try:
            checker = _v1_shariah.check(symbol)
        except Exception:
            checker = None

    if live:
        which = "KMI30" if "KMI30" in idx else "KMIALLSHR"
        out = {"shariah": True,
               "shariah_status": f"Compliant ({which} constituent, per PSX live index membership)",
               "shariah_source": "PSX market-watch index membership (current session)",
               "shariah_verified": True,
               "shariah_method": "psx_live_index"}
    elif checker and checker.get("eligible_for_ranking"):
        out = {"shariah": True,
               "shariah_status": checker.get("status"),
               "shariah_source": checker.get("source"),
               "shariah_verified": True,
               "shariah_method": "config_verified_list"}
    else:
        out = {"shariah": False,
               "shariah_status": (checker or {}).get("status",
                                  "Not in any Shariah index this session"),
               "shariah_source": (checker or {}).get("source", "PSX index membership"),
               "shariah_verified": bool(checker),
               "shariah_method": "not_compliant"}
    if checker and checker.get("notes"):
        out["shariah_notes"] = checker["notes"]
    return out


# PSX appends corporate-action markers to the symbol cell in market-watch, e.g.
# "AKBL XD" (ex-dividend), "SGPL XR" (ex-rights), "XB" (ex-bonus), "XI" (ex-
# interest), "NC" (non-compliant / notice). Only " NC" was being stripped, so
# rows like "AKBL XD" carried a corrupt symbol into every downstream lookup —
# history fetch, OHLC backfill and per-symbol endpoints all silently failed for
# any stock that happened to go ex- that session. The marker is itself material
# information (a price drop on the ex-date is mechanical, not weakness), so it
# is preserved as `corporate_action` rather than discarded.
_CA_MARKERS = {"XD": "ex-dividend", "XR": "ex-rights", "XB": "ex-bonus",
               "XI": "ex-interest", "XBR": "ex-bonus/rights", "NC": "notice"}


def clean_symbol(raw):
    """Return (clean_symbol, [corporate_action_labels]) from a market-watch cell."""
    parts = (raw or "").strip().split()
    if not parts:
        return "", []
    sym, flags = parts[0], []
    for p in parts[1:]:
        label = _CA_MARKERS.get(p.upper().strip("*"))
        if label:
            flags.append(label)
    return sym.strip(), flags


_MW_CACHE={"rows":None,"ts":0.0,"lock":None}
MARKET_TTL=int(os.getenv("PSX_MARKET_TTL","60"))   # seconds


def market_watch(force=False):
    """Cached PSX market-watch.

    Every /decision, /news-feed, /conviction and /ranked-opportunities call needs
    the current quote table. Without a cache each of those is a fresh full HTML
    scrape of dps.psx.com.pk — a handful of users refreshing would put hundreds
    of requests an hour on PSX from one IP and get the server rate-limited or
    blocked. PSX data is ~5 minutes delayed anyway, so a short TTL costs nothing
    in freshness and removes the load. Concurrent callers share one fetch.
    """
    import threading, time as _t
    if _MW_CACHE["lock"] is None:
        _MW_CACHE["lock"]=threading.Lock()
    now=_t.time()
    if not force and _MW_CACHE["rows"] is not None and (now-_MW_CACHE["ts"])<MARKET_TTL:
        return _MW_CACHE["rows"]
    with _MW_CACHE["lock"]:
        now=_t.time()
        if not force and _MW_CACHE["rows"] is not None and (now-_MW_CACHE["ts"])<MARKET_TTL:
            return _MW_CACHE["rows"]
        # PSX's portal 502s intermittently (observed directly, not hypothetical).
        # Every endpoint in this file — /market, /opportunities, /sectors,
        # /decision, /news-feed, /refresh-news — calls market_watch(), so an
        # uncaught exception here used to turn one flaky PSX response into a
        # 500 on every one of them simultaneously, which is what "modules not
        # talking to each other" actually was: not a wiring bug, an unhandled
        # upstream failure with no retry and no fallback.
        last_err=None
        for attempt in range(3):
            try:
                rows=_market_watch_uncached()
                _MW_CACHE["rows"]=rows; _MW_CACHE["ts"]=_t.time()
                return rows
            except Exception as e:
                last_err=e
                if attempt<2:
                    _t.sleep(1.5*(attempt+1))
        print(f"[market_watch] PSX portal fetch failed after 3 attempts: {last_err}")
        if _MW_CACHE["rows"] is not None:
            # Serve the stale cache rather than crash every caller. Callers that
            # care about freshness can force=True after checking /market-status.
            return _MW_CACHE["rows"]
        return []


def _market_watch_uncached():
    r=requests.get(PSX+"/market-watch",headers=HEAD,timeout=15);r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser"); out=[]
    for tr in soup.select("tr"):
        x=[td.get_text(" ",strip=True) for td in tr.select("td")]
        if len(x)<11: continue
        s,ca=clean_symbol(x[0]); sector=_sector_codes.name_for(x[1]); listed=x[2]
        if not s: continue
        ldcp,o,h,l,p,ch,pct,vol=map(num,x[3:11]); sh=_shariah_status(s,listed)
        rng=max(.00001,h-l); loc=(p-l)/rng; liq=min(20,math.log10(max(vol,1))*3)
        mom=max(-20,min(20,pct*2.2)); strength=(loc-.5)*24
        score=max(0,min(100,50+mom+strength+liq/2))
        setup="Momentum breakout" if pct>3 and loc>.8 else "Strong close" if loc>.72 else "Pullback / watch" if pct<0 and loc>.45 else "Neutral"
        out.append(dict(symbol=s,name=_names.name(s,default=None),sector=sector,listed=listed,ldcp=ldcp,open=o,high=h,low=l,price=p,change=ch,pct=pct,volume=vol,score=round(score,1),setup=setup,eligible=vol>=MIN_VOLUME,corporate_action=ca,**sh))
    return out

def save_snapshot(rows):
    ts=datetime.now(timezone.utc).isoformat()
    with db() as c:
        c.executemany("INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(ts,x["symbol"],x["sector"],x["listed"],x["ldcp"],x["open"],x["high"],x["low"],x["price"],x["change"],x["pct"],x["volume"],x["score"],x["setup"],int(x["shariah"])) for x in rows])
        c.commit()

def eod(symbol):
    # Network call — guarded here (not just at call sites) so any future
    # caller gets fail-soft behavior by default rather than needing to
    # remember to wrap it. A prior incident: /scan's fallback path called
    # yahoo_ohlcv() unwrapped and a single 404 crashed the whole request.
    try:
        r=requests.get(f"{PSX}/timeseries/eod/{symbol}",headers=HEAD,timeout=15);r.raise_for_status()
        raw=r.json()
    except Exception as e:
        print(f"[eod] {symbol}: {type(e).__name__}: {e}")
        return []
    a=raw.get("data") or raw.get("timeseries") or []
    out=[]
    for z in a:
        if isinstance(z,list) and len(z)>=2: out.append({"time":z[0],"close":z[1],"volume":z[2] if len(z)>2 else None})
        elif isinstance(z,dict): out.append(z)
    return out


def yahoo_ohlcv(symbol, range_="2y"):
    ticker=f"{symbol.upper()}.KA"
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    try:
        r=requests.get(url,params={"range":range_,"interval":"1d","includePrePost":"false","events":"div,splits"},headers=HEAD,timeout=15)
        r.raise_for_status(); root=r.json()["chart"]; results=root.get("result") or []
    except Exception as e:
        print(f"[yahoo_ohlcv] {ticker}: {type(e).__name__}: {e}")
        return []
    if not results:return []
    q=results[0]; ts=q.get("timestamp") or []; quote=((q.get("indicators") or {}).get("quote") or [{}])[0]
    out=[]
    for i,t in enumerate(ts):
        try:
            close=quote["close"][i]
            if close is None:continue
            out.append({"time":int(t)*1000,"open":quote["open"][i],"high":quote["high"][i],
                        "low":quote["low"][i],"close":close,"volume":quote["volume"][i] or 0,
                        "source":f"Yahoo Finance {ticker}"})
        except: pass
    return out

def best_history(symbol):
    try:
        x=eod(symbol)
        if len(x)>=30:return x,"PSX EOD"
    except: pass
    try:
        x=yahoo_ohlcv(symbol)
        if len(x)>=30:return x,f"Yahoo Finance {symbol.upper()}.KA"
    except: pass
    return [],"Unavailable"

def structure(rows):
    closes=[num(x.get("close",x.get("price"))) for x in rows if num(x.get("close",x.get("price")))>0]
    if len(closes)<20:return {"state":"Insufficient history","trend":"Unknown"}
    ma20=sum(closes[-20:])/20; last=closes[-1]
    hi=max(closes[-20:]); lo=min(closes[-20:])
    trend="Bullish" if last>ma20 else "Bearish"
    return {"state":"Above 20-bar mean" if last>ma20 else "Below 20-bar mean","trend":trend,"ma20":round(ma20,2),"range20":[round(lo,2),round(hi,2)]}

def wyckoff(rows):
    closes=[num(x.get("close",x.get("price"))) for x in rows if num(x.get("close",x.get("price")))>0]
    if len(closes)<40:return {"label":"UNCONFIRMED","confidence":0,"reason":"Need >=40 historical observations"}
    recent=closes[-30:]; rng=max(recent)-min(recent); last=closes[-1]; pos=(last-min(recent))/max(.0001,rng)
    slope=(statistics.mean(closes[-5:])-statistics.mean(closes[-15:-10]))/max(.0001,statistics.mean(closes[-15:-10]))
    if pos>.78 and slope>0.02:return {"label":"SOS / possible Phase D","confidence":62,"reason":"Upper-range acceptance with improving short-term mean"}
    if pos<.22 and slope>0:return {"label":"Spring/Test hypothesis","confidence":55,"reason":"Lower-range location with improving short-term mean"}
    if pos>.75 and slope<0:return {"label":"Upthrust/Distribution watch","confidence":52,"reason":"Upper-range location with weakening mean"}
    return {"label":"Trading range / unresolved","confidence":45,"reason":"No high-confidence phase event"}

@app.get("/health")
def health():
    """Real readiness check, not just 'the process is alive'. Reports DB
    connectivity, whether the background refresh loops are running at all
    (PSX_DISABLE_SCAN_AUTOREFRESH silently disables them otherwise), the
    freshness of every cached whole-universe analysis, which optional engine
    modules failed to import, and whether any background job is currently
    mid-computation — so a monitoring probe (or a human) can tell "up but
    stale/overloaded" apart from "genuinely healthy" instead of both looking
    like a bare 200 OK.
    """
    db_ok, db_err = True, None
    try:
        with db() as c:
            c.execute("SELECT 1").fetchone()
    except Exception as e:
        db_ok, db_err = False, f"{type(e).__name__}: {e}"

    cache_keys = ("dss_scan", "alerts", "scan_brain", "backtest_run",
                  "walkforward", "regime_split", "discover_edges", "failure_analysis")
    caches_raw = _scan_cache.latest_many(cache_keys)
    caches = {}
    for k in cache_keys:
        c = caches_raw[k]
        caches[k] = {"age_seconds": c["_cache_age_seconds"] if c else None,
                     "job_running": _bg_job_running(k)}

    modules = {"technical_analyzer": _v1_tech is not None, "shariah_checker": _v1_shariah is not None,
               "risk_manager": _v1_risk is not None, "portfolio_risk": _v1_book is not None,
               "market_regime": _v1_regime is not None, "scoring_engine": _v1_scoring is not None,
               "signal_generator": _v1_signal is not None, "orchestrator": _orch is not None,
               "psx_report": _psx_report is not None, "psx_brain": _psx_brain is not None,
               "psx_live": _psx_live is not None, "psxwatch_bridge": _pw is not None}
    missing_modules = [k for k, v in modules.items() if not v]

    refresh_loops_disabled = bool(os.getenv("PSX_DISABLE_SCAN_AUTOREFRESH"))
    any_job_running = any(v["job_running"] for v in caches.values())

    ok = db_ok  # module degradation and stale caches are reported, not fatal —
                # every call site already falls back to neutral/unavailable
    return {"ok": ok, "time": datetime.now(timezone.utc).isoformat(), "min_volume": MIN_VOLUME,
            "market_data": "PSX Data Portal", "freshness": "5-minute delayed unless PSX indicates otherwise",
            "policy": "private research; do not redistribute PSX market data without appropriate rights",
            "database": {"ok": db_ok, "error": db_err, **turso_db.status()},
            "background_refresh_loops_disabled": refresh_loops_disabled,
            "background_job_running": any_job_running,
            "caches": caches,
            "modules_unavailable": missing_modules}

@app.get("/market-status")
def market_status():
    """Freshness of the cached PSX market-watch snapshot every other market
    endpoint reads from. If PSX's portal is 502ing, rows here go stale rather
    than every dependent endpoint failing — this tells you which is happening."""
    import time as _t
    ts=_MW_CACHE["ts"]
    return {"cached_rows":len(_MW_CACHE["rows"] or []),
            "age_seconds":round(_t.time()-ts,1) if ts else None,
            "ttl_seconds":MARKET_TTL,
            "stale":bool(ts and (_t.time()-ts)>MARKET_TTL)}


@app.get("/company-names")
def company_names():
    """Full ticker -> {name, sector, is_etf, is_debt} map, straight from PSX's
    own /symbols directory. Cached ~24h since listings change rarely."""
    m=_names.load()
    return {"count":len(m),"names":m}


@app.get("/market")
def market(min_volume:int=0, shariah:bool=False):
    rows=market_watch(); save_snapshot(rows)
    return [x for x in rows if x["volume"]>=min_volume and (not shariah or x["shariah"])]

@app.get("/opportunities")
def opportunities(min_volume:int=MIN_VOLUME, shariah:bool=False, limit:int=50):
    rows=market_watch()
    rows=[x for x in rows if x["volume"]>=min_volume and (not shariah or x["shariah"])]
    rows.sort(key=lambda x:x["score"],reverse=True); return rows[:limit]

@app.get("/stock/{symbol}")
def stock(symbol:str):
    rows=market_watch(); q=next((x for x in rows if x["symbol"]==symbol.upper()),None)
    hist,source=best_history(symbol.upper()); return {"quote":q,"history":hist[-180:],"history_source":source,"structure":structure(hist),"wyckoff":wyckoff(hist)}

@app.get("/breadth")
def breadth():
    rows=market_watch(); adv=sum(x["pct"]>0 for x in rows); dec=sum(x["pct"]<0 for x in rows)
    return {"advancing":adv,"declining":dec,"unchanged":len(rows)-adv-dec,"breadth_pct":round(100*adv/max(1,adv+dec),1)}

@app.get("/sectors")
def sectors():
    rows=market_watch(); d={}
    for x in rows:
        a=d.setdefault(x["sector"],{"sector":x["sector"],"n":0,"adv":0,"pct_sum":0,"volume":0})
        a["n"]+=1;a["adv"]+=x["pct"]>0;a["pct_sum"]+=x["pct"];a["volume"]+=x["volume"]
    out=[]
    for a in d.values():a["avg_pct"]=round(a.pop("pct_sum")/a["n"],2);out.append(a)
    return sorted(out,key=lambda x:x["avg_pct"],reverse=True)

@app.get("/news")
def news(symbol:str|None=None,hours:int=48):
    with db() as c:
        q="SELECT * FROM news";args=[]
        if symbol:q+=" WHERE symbols LIKE ?";args=[f"%{symbol.upper()}%"]
        q+=" ORDER BY fetched_at DESC LIMIT 200"
        return [dict(x) for x in c.execute(q,args)]

@app.get("/predictions")
def predictions(symbol:str|None=None):
    with db() as c:
        q="SELECT * FROM predictions";args=[]
        if symbol:q+=" WHERE symbol=?";args=[symbol.upper()]
        q+=" ORDER BY ts DESC LIMIT 500";return [dict(x) for x in c.execute(q,args)]

@app.get("/export.xlsx")
def export_excel():
    rows=market_watch(); eligible=[x for x in rows if x["volume"]>=MIN_VOLUME]
    bio=io.BytesIO()
    with pd.ExcelWriter(bio,engine="openpyxl") as w:
        pd.DataFrame(rows).to_excel(w,index=False,sheet_name="Full PSX")
        pd.DataFrame(eligible).sort_values("score",ascending=False).to_excel(w,index=False,sheet_name="Shortlist 50K")
        pd.DataFrame([x for x in eligible if x["shariah"]]).sort_values("score",ascending=False).to_excel(w,index=False,sheet_name="Shariah 50K")
        pd.DataFrame(breadth(),index=[0]).to_excel(w,index=False,sheet_name="Breadth")
        pd.DataFrame(sectors()).to_excel(w,index=False,sheet_name="Sectors")
    bio.seek(0);return StreamingResponse(bio,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":"attachment; filename=psx_v2.xlsx"})

@app.websocket("/ws/market")
async def ws_market(ws:WebSocket):
    import asyncio
    await ws.accept()
    try:
        while True:
            rows=market_watch()
            await ws.send_text(json.dumps({"ts":datetime.now(timezone.utc).isoformat(),"rows":rows}))
            await asyncio.sleep(300)
    except: pass

@app.get("/fundamentals/{symbol}")
def fundamentals(symbol:str):
    """Fetch the official PSX company page and return only fields actually present."""
    from bs4 import BeautifulSoup
    r=requests.get(f"{PSX}/company/{symbol.upper()}",headers=HEAD,timeout=15);r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    text=soup.get_text("\n",strip=True)
    def nearby(label):
        import re
        m=re.search(rf"{re.escape(label)}(?: \(%\))?\s*\n?\s*([^\n]{{1,80}})",text,re.I)
        return m.group(1).strip() if m else None
    return {
      "symbol":symbol.upper(),"source":f"{PSX}/company/{symbol.upper()}",
      "sales":nearby("Sales"),"profit_after_tax":nearby("Profit after Taxation"),
      "eps":nearby("EPS"),"gross_profit_margin":nearby("Gross Profit Margin"),
      "net_profit_margin":nearby("Net Profit Margin"),"eps_growth":nearby("EPS Growth"),
      "peg":nearby("PEG"),"raw_available":bool(text)
    }

def _closes(hist):
    vals=[]
    for x in hist:
        try:
            v=float(x.get("close",x.get("price")))
            if v>0: vals.append(v)
        except: pass
    return vals

def _ema(v,n):
    if len(v)<n:return None
    k=2/(n+1); e=v[-n]
    for x in v[-n+1:]:e=x*k+e*(1-k)
    return e

def _rsi(v,n=14):
    if len(v)<n+1:return None
    d=[v[i]-v[i-1] for i in range(len(v)-n,len(v))]
    up=sum(max(x,0) for x in d)/n; dn=sum(max(-x,0) for x in d)/n
    return 100 if dn==0 else 100-100/(1+up/dn)

@app.get("/technicals/{symbol}")
def technicals(symbol:str):
    hist,source=best_history(symbol.upper()); v=_closes(hist)
    if len(v)<30:return {"symbol":symbol.upper(),"status":"insufficient_history","observations":len(v)}
    ma20=sum(v[-20:])/20; ma50=sum(v[-50:])/50 if len(v)>=50 else None
    r=_rsi(v); e12=_ema(v,12); e26=_ema(v,26); macd=(e12-e26) if e12 is not None and e26 is not None else None
    sd=(sum((x-ma20)**2 for x in v[-20:])/20)**0.5
    return {"symbol":symbol.upper(),"observations":len(v),"last":v[-1],"sma20":ma20,"sma50":ma50,
            "rsi14":r,"macd_proxy":macd,"bollinger_upper":ma20+2*sd,"bollinger_lower":ma20-2*sd,
            "history_source":source,"ohlc_limitation":None if any(x.get("high") is not None for x in hist) else "True OHLC unavailable from current source."}

# ---- V2.4 true-OHLC intelligence layer ----
_ohlc_table_ensured = False

def ensure_ohlc():
    # Used to run this CREATE TABLE IF NOT EXISTS on every single ohlc_rows()
    # call — free when that meant a local sqlite3 no-op, but now that db()
    # can be a Turso HTTP round trip (see turso_db.py), that doubled every
    # ohlc_rows() call's network cost for no reason. Run it once per process.
    global _ohlc_table_ensured
    if _ohlc_table_ensured:
        return
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS daily_ohlc(
          symbol TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
          source TEXT, PRIMARY KEY(symbol,trade_date))"""); c.commit()
    _ohlc_table_ensured = True

_ohlc_cache = {}
_OHLC_CACHE_TTL = 10  # seconds
_OHLC_CACHE_MAX_LIMIT = 500  # only cache "normal" reads (verdict/decision/
                              # intelligence/relative-strength all separately
                              # re-fetch the same symbol's ~300-400 recent
                              # rows within one /dss/{symbol} request) -- not
                              # the rare full-history calls (limit=10000),
                              # which would bloat this cache for little benefit.

def ohlc_rows(symbol,limit=260):
    ensure_ohlc()
    sym = symbol.upper()
    cacheable = limit <= _OHLC_CACHE_MAX_LIMIT
    if cacheable:
        cached = _ohlc_cache.get((sym, limit))
        if cached and (time.time() - cached[0]) < _OHLC_CACHE_TTL:
            return cached[1]
    with db() as c:
        a=c.execute("SELECT * FROM daily_ohlc WHERE symbol=? ORDER BY trade_date DESC LIMIT ?",
                    (sym,limit)).fetchall()
    result = [dict(x) for x in reversed(a)]
    if cacheable:
        _ohlc_cache[(sym, limit)] = (time.time(), result)
    return result

def ohlc_rows_multi(symbols, limit=300):
    """Same per-symbol result as calling ohlc_rows() once per symbol, but as
    ONE database round trip -- built for peer-comparison loops (see
    _rs_multi_for's same-sector peers) that used to call ohlc_rows() once
    per peer stock. That was free with local sqlite3; once db() started
    talking to Turso over HTTP, a sector with 20+ peers meant 20+ sequential
    network round trips for a single /dss/ request.

    Deliberately NOT a single ROW_NUMBER()-over-PARTITION-BY query across
    all symbols at once: that shape has to read and rank a symbol's ENTIRE
    stored history before it can hand back the last `limit` rows, which
    burns through Turso's rows-read quota far faster than the round-trip
    count suggests (a first version of this function did exactly that and
    contributed to tripping a usage warning). Sending N separate per-symbol
    `WHERE symbol=? ORDER BY trade_date DESC LIMIT ?` queries in one HTTP
    batch keeps the round-trip win while each query stays index-satisfied
    (daily_ohlc's PRIMARY KEY is (symbol, trade_date)) and only reads the
    rows actually needed."""
    ensure_ohlc()
    syms = list(dict.fromkeys(s.upper() for s in symbols))  # de-dupe, keep order
    if not syms:
        return {}
    queries = [("SELECT * FROM daily_ohlc WHERE symbol=? ORDER BY trade_date DESC LIMIT ?", (s, limit))
               for s in syms]
    if turso_db.USING_TURSO:
        conn = turso_db.get_connection()
        results = conn.batch_query(queries)
    else:
        c = db()
        results = [c.execute(sql, params).fetchall() for sql, params in queries]
    out = {}
    for s, rows in zip(syms, results):
        out[s] = [dict(r) for r in rows]
    for s in out:
        out[s] = list(reversed(out[s]))  # ascending, matching ohlc_rows()
    return out

def tr_values(a):
    out=[]
    for i in range(1,len(a)):
        h,l,pc=a[i]["high"],a[i]["low"],a[i-1]["close"]
        out.append(max(h-l,abs(h-pc),abs(l-pc)))
    return out

def atr14(a):
    t=tr_values(a)
    return sum(t[-14:])/14 if len(t)>=14 else None

def pivots(a,n=2):
    hi=[];lo=[]
    for i in range(n,len(a)-n):
        if all(a[i]["high"]>=a[j]["high"] for j in range(i-n,i+n+1)):hi.append((i,a[i]["high"]))
        if all(a[i]["low"]<=a[j]["low"] for j in range(i-n,i+n+1)):lo.append((i,a[i]["low"]))
    return hi,lo

def structure_ohlc(a):
    if len(a)<20:return {"status":"insufficient_history"}
    hi,lo=pivots(a)
    trend="UNRESOLVED";bos=None
    if len(hi)>=2 and len(lo)>=2:
        hh=hi[-1][1]>hi[-2][1]; hl=lo[-1][1]>lo[-2][1]
        lh=hi[-1][1]<hi[-2][1]; ll=lo[-1][1]<lo[-2][1]
        trend="HH/HL UPTREND" if hh and hl else "LH/LL DOWNTREND" if lh and ll else "RANGE / TRANSITION"
        last=a[-1]["close"]
        if last>hi[-1][1]:bos="BULLISH BOS"
        elif last<lo[-1][1]:bos="BEARISH BOS"
    return {"trend":trend,"bos":bos,"last_swing_high":hi[-1][1] if hi else None,
            "last_swing_low":lo[-1][1] if lo else None}

def candle_patterns(a):
    """Full Nison candlestick set (STEP 16) — delegates to candlestick_engine
    so live reads and the backtest scan use identical detection logic."""
    if len(a) < 2:
        return []
    return _candles.detect_at(a, len(a) - 1)

def wyckoff_ohlc(a):
    if len(a)<50:return {"label":"UNCONFIRMED","confidence":0,"reason":"Need >=50 true OHLC sessions"}
    r=a[-40:]; hi=max(x["high"] for x in r); lo=min(x["low"] for x in r); last=r[-1]["close"]
    pos=(last-lo)/max(.0001,hi-lo)
    avgv=sum(x["volume"] for x in r[-20:])/20
    vr=r[-1]["volume"]/max(1,avgv)
    if pos>.8 and vr>1.3:return {"label":"SOS / Phase-D candidate","confidence":68,"reason":"Upper-range acceptance + volume expansion"}
    if pos<.2 and r[-1]["low"]<min(x["low"] for x in r[-10:-1]) and last>r[-1]["low"]:
        return {"label":"Spring hypothesis","confidence":58,"reason":"Range undercut with recovery; test still required"}
    return {"label":"Range / unresolved","confidence":45,"reason":"No high-confidence event"}

@app.post("/ohlc/{symbol}")
def ingest_ohlc(symbol:str, rows:list[dict], request:Request):
    """Private research ingestion endpoint for genuine daily OHLCV rows."""
    _g=_require_admin(request)
    if _g: return _g
    ensure_ohlc(); good=[]
    for x in rows:
        try:
            good.append((symbol.upper(),str(x["date"]),float(x["open"]),float(x["high"]),float(x["low"]),
                         float(x["close"]),float(x.get("volume",0)),str(x.get("source","PSX Historical Data"))))
        except: pass
    with db() as c:
        c.executemany("INSERT OR REPLACE INTO daily_ohlc VALUES(?,?,?,?,?,?,?,?)",good);c.commit()
    return {"symbol":symbol.upper(),"stored":len(good)}

@app.get("/ohlc/{symbol}")
def get_ohlc(symbol:str,limit:int=260): return ohlc_rows(symbol,limit)

@app.get("/intelligence/{symbol}")
def intelligence(symbol:str):
    a=ohlc_rows(symbol,300)
    if not a:return {"symbol":symbol.upper(),"status":"awaiting_true_ohlc_backfill",
                     "source":"PSX Historical Data","message":"No OHLC rows stored; no OHLC-dependent indicators are fabricated."}
    return {"symbol":symbol.upper(),"sessions":len(a),"atr14":atr14(a),
            "structure":structure_ohlc(a),"candles":candle_patterns(a),"wyckoff":wyckoff_ohlc(a)}

@app.get("/ohlc-coverage")
def ohlc_coverage():
    ensure_ohlc()
    with db() as c:
        rows=c.execute("""SELECT symbol,COUNT(*) sessions,MIN(trade_date) first_date,MAX(trade_date) last_date
                          FROM daily_ohlc GROUP BY symbol ORDER BY sessions DESC""").fetchall()
    return [dict(x) for x in rows]

@app.get("/data-quality/{symbol}")
def data_quality(symbol:str):
    """STEP 2: full data-quality audit (missing days, duplicates, zero-volume
    sessions, impossible OHLC, negative volume, stale-price runs, large gaps
    flagged not auto-classified) with a reproducible 0-100 score — not just
    the original OHLC-sanity-only check (kept working via the same field names)."""
    a=ohlc_rows(symbol,10000)
    result = _dq.audit(a)
    result["symbol"] = symbol.upper()
    if result.get("status") != "missing":
        result["invalid_ohlc_rows"] = result.get("issues", {}).get("impossible_ohlc", 0)  # backward-compat field
    return result


@app.get("/liquidity/{symbol}")
def liquidity(symbol:str):
    """STEP 3: liquidity classification (Highly Liquid ... Very Illiquid)
    from the stock's own trailing volume behavior, with a confidence
    multiplier the DSS applies so a pattern in an illiquid name is never
    scored as confidently as the same pattern in a liquid one."""
    a=ohlc_rows(symbol,300)
    result = _dq.classify_liquidity(a)
    result["symbol"] = symbol.upper()
    return result

def v1_technical(symbol, quote=None, rs_score=None):
    """Run the ported V1 technical_analyzer on real fetched data.

    This is the full analytics stack (true ATR/ADX from stored OHLC, CMF,
    OBV/price divergence, Bollinger squeeze, support/resistance, stop & targets,
    real headroom R:R, extension + pullback zones, accumulation confluence) —
    far beyond the lightweight /technicals endpoint, which is left untouched.

    Returns (result_dict, error_or_None). Never raises into a route.
    """
    if _v1_tech is None or _eod_frame is None:
        return None, "technical_analyzer/legacy_adapter not importable on this deployment"
    sym = symbol.upper()
    try:
        hist, source = best_history(sym)
        if not hist:
            return None, f"no historical rows available ({source})"
        df = _eod_frame(hist)
        # legacy_adapter keeps only ts/close/volume/open; technical_analyzer uses
        # high/low when present, so carry them through when the source has them.
        try:
            if len(df):
                for col in ("high", "low"):
                    vals = [x.get(col) for x in hist if isinstance(x, dict)]
                    if len(vals) == len(df) and any(v is not None for v in vals):
                        df[col] = pd.to_numeric(pd.Series(vals), errors="coerce")
        except Exception:
            pass
        if not len(df):
            return None, "history could not be normalized into a frame"
        if quote is None:
            rows = market_watch()
            quote = next((x for x in rows if x["symbol"] == sym), None)
        oh = ohlc_rows(sym, 300)
        res = _v1_tech.analyze(sym, df, quote or {}, rs_score=rs_score,
                               ohlc=oh or None)
        if isinstance(res, dict):
            res["history_source"] = source
            res["observations"] = len(df)
            res["stored_ohlc_sessions"] = len(oh or [])
        return res, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


@app.get("/technical-pro/{symbol}")
def technical_pro(symbol:str):
    """Full V1 technical stack. Falls back with an explicit reason, never fakes."""
    res, err = v1_technical(symbol)
    if res is None:
        return {"symbol":symbol.upper(),"status":"unavailable","reason":err,
                "note":"No indicator values are fabricated when the engine or "
                       "its data are unavailable. Use /technicals for the "
                       "lightweight close-only read."}
    return {"symbol":symbol.upper(),"status":"ok","technical":res}


@app.get("/risk/{symbol}")
def risk_assessment(symbol:str, capital:float=1_000_000):
    """Position sizing + veto layer from the ported V1 risk_manager."""
    if _v1_risk is None:
        return {"symbol":symbol.upper(),"status":"unavailable",
                "reason":"risk_manager not importable on this deployment"}
    res, err = v1_technical(symbol)
    if res is None:
        return {"symbol":symbol.upper(),"status":"unavailable","reason":err}
    try:
        neutral_sent = {"score":50,"flags":[]}
        neutral_macro = {"bad_news_flag":False,"bad_news":[]}
        r = _v1_risk.assess(symbol.upper(), res, neutral_sent, neutral_macro,
                            capital_pkr=capital)
        return {"symbol":symbol.upper(),"status":"ok","risk":r,
                "inputs":{"price":res.get("price"),"stop_loss":res.get("stop_loss"),
                          "headroom_rr":res.get("headroom_rr"),
                          "atr_pct":res.get("atr_pct")},
                "note":"News/sentiment inputs are neutral here — this is the "
                       "price/volume risk layer only."}
    except Exception as e:
        return {"symbol":symbol.upper(),"status":"error","reason":f"{type(e).__name__}: {e}"}


@app.get("/decision/{symbol}")
def decision(symbol:str, capital:float=1_000_000, record:bool=True):
    """INTEGRATED VIEW — every engine, combined, for one symbol.

    This is the layer the individual endpoints were always meant to feed:
    technical + fundamentals + news + macro are blended by scoring_engine,
    vetoed by risk_manager, gated by shariah_checker and market_regime, and
    resolved into a signal by signal_generator.

    Layers that cannot run are reported in `unavailable` and enter the blend as
    a neutral 50 flagged low_confidence — never as positive evidence.
    """
    if _orch is None:
        return {"symbol":symbol.upper(),"status":"unavailable",
                "reason":"orchestrator module not importable"}
    sym=symbol.upper()
    rows=market_watch(); q=next((x for x in rows if x["symbol"]==sym),None)
    if not q:return {"symbol":sym,"status":"not_found"}
    _sync_sectors_from_psx(rows)
    tech,_terr = v1_technical(sym, quote=q)
    prev=None
    try:
        import database as _db
        _last=_db.last_run(sym)
        prev=_last.get("signal") if _last else None
    except Exception:
        pass
    res=_orch.decide(sym, quote=q, capital=capital, prev_signal=prev,
                     technical=tech,
                     deps={"technical":None,"scoring":_v1_scoring,
                           "signal":_v1_signal,"risk":_v1_risk,
                           "shariah":_v1_shariah,"regime":_v1_regime,
                           "fundamentals":fundamental_analysis,
                           "news":_news_verdict,
                           "shariah_verdict":{
                               "eligible_for_ranking":bool(q.get("shariah")),
                               "status":q.get("shariah_status"),
                               "source":q.get("shariah_source"),
                               "method":q.get("shariah_method"),
                               "notes":q.get("shariah_notes",[])}})
    res["quote"]=q
    if _terr: res.setdefault("unavailable",{})["technical"]=_terr
    # Record the decision so it can be graded later. Day-deduped: repeated calls
    # in one session must not inflate the sample. `record=false` to skip.
    if record:
        try:
            import database as _db
            _t=(tech or {}) if isinstance(tech,dict) else {}
            action=_db.save_run_daily(
                res.get("as_of"), sym, res.get("decision",{}).get("signal"),
                res.get("scoring",{}).get("final_score"),
                res.get("scoring",{}).get("confidence"),
                q.get("price"), _t.get("stop_loss"), _t.get("target1"))
            res["recorded"]=action
        except Exception as e:
            res["recorded"]=f"failed: {type(e).__name__}"
    return res


def _news_verdict(sym):
    """Authentic per-symbol news verdict from news_signals.json, or None."""
    from news_feed import get as _g
    return _g(sym)


def _grade_one(run, bars):
    """Grade a stored run against the ACTUAL price path after it.

    Walks daily OHLC forward from the run date and asks which level was touched
    FIRST — this is why the stored OHLC matters: comparing only the closing price
    N days later would call a trade a winner even if it was stopped out on day 2
    and recovered. V1's rule: Buy/Strong Buy works if price moved toward target
    before stop; Avoid/Exit works if price fell. Watch/Hold are graded on the
    loose "didn't lose >3%" rule and are EXCLUDED from confidence by
    scoring_engine._STRICT_SIGNALS, so their survival rate can't masquerade as edge.
    """
    sig=(run.get("signal") or "").strip()
    entry=run.get("price") or 0
    if entry<=0 or not bars: return None
    stop=run.get("stop") or 0
    target=run.get("target") or 0
    day=(run.get("ts") or "")[:10]
    fwd=[b for b in bars if (b.get("trade_date") or "")>day]
    if len(fwd)<3: return None                      # not enough path yet

    if sig in ("Buy","Strong Buy"):
        for b in fwd:
            lo,hi=b.get("low"),b.get("high")
            if stop and lo is not None and lo<=stop:  return "failed"
            if target and hi is not None and hi>=target: return "worked"
        last=fwd[-1].get("close") or entry
        return "worked" if last>entry else "failed"
    if sig in ("Avoid","Exit"):
        last=fwd[-1].get("close") or entry
        return "worked" if last<entry else "failed"
    # Watch / Hold: loose survival rule, excluded from confidence maths.
    last=fwd[-1].get("close") or entry
    return "worked" if last >= entry*0.97 else "failed"


def _run_grade_outcomes_full(min_age_days=7, limit=500):
    try:
        import database as _db
        pend=_db.ungraded_runs(min_age_days=min_age_days, limit=limit)
        if not pend:
            return {"status":"ok","pending":0,"graded":0,
                    "note":f"No runs older than {min_age_days}d awaiting grading. "
                           "Call /decision over several sessions first."}
        cache,graded,skipped={},{"worked":0,"failed":0},0
        for r in pend:
            sym=r["symbol"]
            if sym not in cache: cache[sym]=ohlc_rows(sym,10000)
            verdict=_grade_one(r,cache[sym])
            if verdict is None:
                skipped+=1; continue
            _db.set_outcome(r["id"],verdict)
            graded[verdict]=graded.get(verdict,0)+1
        tot=graded["worked"]+graded["failed"]
        return {"status":"ok","pending":len(pend),"graded":tot,
                "worked":graded["worked"],"failed":graded["failed"],
                "insufficient_path":skipped,
                "win_rate":(round(100*graded["worked"]/tot,1) if tot else None),
                "note":"Graded against real stored OHLC paths (stop/target hit "
                       "order, not just the closing price). Watch/Hold use the "
                       "loose survival rule and are excluded from confidence by "
                       "scoring_engine. Nothing is graded without a real path."}
    except Exception as e:
        return {"status":"error","reason":f"{type(e).__name__}: {e}"}


@app.post("/grade-outcomes")
def grade_outcomes(request:Request, min_age_days:int=7, limit:int=500):
    """Grade stored runs against real subsequent prices.

    This is the learning loop: graded outcomes feed
    scoring_engine.historical_confidence_adjust() and
    _indicator_accuracy_boost(), which is why confidence currently reports
    "No strictly-graded history yet". Runs with too little forward path are left
    UNGRADED rather than guessed. Also runs automatically once a day as part
    of the background heavy-refresh cycle (see _heavy_refresh_loop) with the
    same defaults — this manual endpoint is for an immediate on-demand grade
    pass, e.g. right after backfilling a batch of history.
    """
    _g=_require_admin(request)
    if _g: return _g
    return _run_grade_outcomes_full(min_age_days, limit)


@app.get("/learning-status")
def learning_status():
    """How much graded history exists, and what it is doing to confidence."""
    try:
        import database as _db
        rows=_db.signal_accuracy()
        strict=("Buy","Strong Buy","Avoid","Exit")
        w=sum(r["n"] for r in rows if r["outcome"]=="worked" and r["signal"] in strict)
        l=sum(r["n"] for r in rows if r["outcome"]=="failed" and r["signal"] in strict)
        tot=w+l
        with _db._conn() as c:
            stored=c.execute("SELECT COUNT(*) n FROM runs").fetchone()["n"]
            ungraded=c.execute("SELECT COUNT(*) n FROM runs WHERE outcome IS NULL "
                               "OR outcome=''").fetchone()["n"]
        if tot==0: effect="No adjustment — base confidence."
        elif tot<10: effect=f"Small sample ({tot}) — capped influence, overfitting risk."
        else: effect=f"Active: {w}W/{l}L adjusts confidence up to ±15 points."
        return {"runs_stored":stored,"ungraded":ungraded,
                "strictly_graded":tot,"worked":w,"failed":l,
                "win_rate":(round(100*w/tot,1) if tot else None),
                "confidence_effect":effect,"by_signal":rows,
                "note":"Only Buy/Strong Buy/Avoid/Exit count toward confidence. "
                       "Watch/Hold survival rates are not edge."}
    except Exception as e:
        return {"status":"error","reason":f"{type(e).__name__}: {e}"}


_NEWS_LOCK={"running":False,"last":None}

# Macro themes -> sectors conventionally sensitive to them. IMPORTANT: these are
# CONVENTIONAL relationships (what analysts commonly assert), NOT correlations
# measured against PSX history. They are labelled as such everywhere they are
# surfaced, and they never move a score — they only tell the reader where to
# look. Measuring them properly against stored OHLC is a separate task.
_THEMES={
 "oil":{"kw":["oil price","crude","brent","opec","petroleum levy","fuel price"],
        "sensitive":["Oil & Gas Exploration (revenue follows crude)",
                     "Oil Marketing (inventory gains/losses)",
                     "Cement & Transport (fuel/freight cost pressure)"]},
 "rates":{"kw":["policy rate","interest rate","monetary policy","sbp","mpc","discount rate"],
          "sensitive":["Banks (margins widen with rates)",
                       "Cement / Autos / Leveraged names (financing cost)"]},
 "inflation":{"kw":["inflation","cpi","price index"],
              "sensitive":["Consumer & FMCG (demand and input costs)",
                           "Banks (rate expectations)"]},
 "fx":{"kw":["rupee","usd","exchange rate","pkr","devaluation"],
       "sensitive":["IT exporters (dollar revenue)",
                    "Importers / Autos / Pharma (input costs)"]},
 "imf":{"kw":["imf","bailout","tranche","programme review","staff level"],
        "sensitive":["Broad market (risk premium, external stability)"]},
 "policy":{"kw":["budget","tax","subsidy","tariff","psdp","circular debt",
                 "refinery","upgradation","deregulation","import duty","levy",
                 "sro","ecc","cabinet approves","policy approved","incentive"],
           "sensitive":["Sector-specific — read the headline for the named industry"]},
 "energy":{"kw":["gas price","electricity","tariff hike","load shedding","circular debt"],
           "sensitive":["Fertilizer (gas feedstock)","Power generation & distribution"]},
}


def _themes_for(text):
    low=(text or "").lower()
    out=[]
    for name,d in _THEMES.items():
        if any(k in low for k in d["kw"]):
            out.append({"theme":name,"sectors_conventionally_sensitive":d["sensitive"]})
    return out


def _news_age_minutes():
    try:
        import news_feed as _nf
        _,meta=_nf.load_signals()
        if meta.get("status")!="ok" or not meta.get("as_of"): return None
        t=datetime.fromisoformat(meta["as_of"])
        if not t.tzinfo: t=t.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc)-t).total_seconds()/60,1)
    except Exception:
        return None


def _refresh_news_bg(limit, window_hours):
    """Refresh in a background thread so the request returns immediately."""
    def _work():
        try:
            import news_pipeline as _np
            rows=market_watch()
            syms=[x["symbol"] for x in sorted(rows,key=lambda z:-z["volume"])
                  if x["volume"]>=MIN_VOLUME][:limit]
            _np.run(syms,window_hours=window_hours)
            _NEWS_LOCK["last"]=datetime.now(timezone.utc).isoformat()
        except Exception as e:
            print(f"[news] background refresh failed: {e}")
        finally:
            _NEWS_LOCK["running"]=False
    if _NEWS_LOCK["running"]: return False
    _NEWS_LOCK["running"]=True
    import threading; threading.Thread(target=_work,daemon=True).start()
    return True


@app.get("/news-feed")
def news_feed_screen(max_age_minutes:int=30, limit:int=30, window_hours:int=48,
                     auto_refresh:bool=True):
    """Headlines + the stocks they attach to, for the app's News screen.

    Serves the CACHED verdicts immediately and kicks off a background refresh
    only when the cache is older than `max_age_minutes`. Market quotes move every
    5 minutes; RSS does not, and re-fetching 30 symbols per view would be slow
    and rate-limited. So the app may poll on its 5-minute cycle while the actual
    fetch happens far less often — `age_minutes` tells you how old the read is.

    IMPACT is reported two ways, and the difference matters:
      * `observed_move_pct` — what the stock ACTUALLY did this session. Real.
      * `sectors_conventionally_sensitive` — what analysts commonly assert about
        a macro theme. NOT measured against PSX history. Directional guidance for
        where to look, never evidence, and it never moves a score.
    """
    try:
        import news_feed as _nf, json as _json
        age=_news_age_minutes()
        refreshing=False
        if auto_refresh and (age is None or age>max_age_minutes):
            refreshing=_refresh_news_bg(limit,window_hours)

        sig,meta=_nf.load_signals()

        # macro headlines come from the same payload the pipeline wrote
        macro=[]
        try:
            import news_pipeline as _np
            with open(_np._default_path(),encoding="utf-8") as f:
                payload=_json.load(f)
            for m in (payload.get("macro_headlines") or [])[:25]:
                macro.append({**m,"themes":_themes_for(m.get("title",""))})
        except Exception:
            payload={}

        # attach each verdict to its live quote so impact is OBSERVED, not asserted
        quotes={}
        try:
            for x in market_watch(): quotes[x["symbol"]]=x
        except Exception:
            pass

        items=[]
        for symv,v in (sig or {}).items():
            q=quotes.get(symv) or {}
            items.append({
                "symbol":symv,"sector":q.get("sector"),
                "price":q.get("price"),"observed_move_pct":q.get("pct"),
                "volume":q.get("volume"),
                "direction":v.get("direction"),"news_score":v.get("score"),
                "materiality":v.get("materiality"),"confidence":v.get("confidence"),
                "summary":v.get("summary"),
                "headlines":v.get("headlines",[])[:4],
                "sources":v.get("sources",[])[:4],
                "publishers":v.get("publishers",[]),
                "agreement":(None if q.get("pct") is None or not v.get("direction")
                             else "price agrees with news read"
                             if (v["direction"]=="positive" and q["pct"]>0)
                             or (v["direction"]=="negative" and q["pct"]<0)
                             else "price diverges from news read"
                             if v["direction"] in ("positive","negative") else None)})
        items.sort(key=lambda z:abs((z.get("news_score") or 50)-50),reverse=True)

        return {"status":meta.get("status"),"as_of":meta.get("as_of"),
                "age_minutes":age,"refresh_started":refreshing,
                "refreshing_now":_NEWS_LOCK["running"],
                "max_age_minutes":max_age_minutes,
                "symbols_with_news":len(items),
                "no_headlines":(payload.get("symbols_with_no_news") or [])[:40],
                "macro_headlines":macro,"stocks":items,
                "method":payload.get("method","deterministic_keyword_v1"),
                "impact_note":"`observed_move_pct` is what the stock actually did "
                              "this session. `sectors_conventionally_sensitive` is "
                              "a conventional analyst relationship, NOT measured "
                              "against PSX history — guidance for where to look, "
                              "not evidence. Neither moves any score.",
                "freshness_note":"Verdicts are cached; quotes are live. News is "
                                 "re-fetched only when older than max_age_minutes."}
    except Exception as e:
        return {"status":"error","reason":f"{type(e).__name__}: {e}",
                "note":"No headline or impact is fabricated when sources are unavailable."}


@app.post("/refresh-news")
def refresh_news(request:Request, min_volume:int=MIN_VOLUME, limit:int=30, window_hours:int=48):
    """Fetch real headlines for the most liquid names and write news_signals.json
    (the file news_feed.py reads, which has never existed until now).

    Verdicts are keyword-derived, not article-level judgment — confidence is
    capped at "medium" by design. Symbols with no matching credible headline get
    NO entry, so the engine treats them as neutral rather than positive.
    """
    _g=_require_admin(request)
    if _g: return _g
    try:
        import news_pipeline as _np
        rows=market_watch()
        syms=[x["symbol"] for x in sorted(rows,key=lambda z:-z["volume"])
              if x["volume"]>=min_volume][:limit]
        p=_np.run(syms, window_hours=window_hours)
        return {"symbols_requested":len(syms),
                "verdicts_written":len(p["signals"]),
                "no_headlines":p["symbols_with_no_news"],
                "macro_headlines":len(p["macro_headlines"]),
                "as_of":p["as_of"],"path":_np._default_path(),
                "note":p["note"]}
    except Exception as e:
        return {"status":"error","reason":f"{type(e).__name__}: {e}",
                "note":"No news verdict is fabricated when the source is unavailable."}


@app.get("/news-status")
def news_status():
    """Freshness and coverage of the authentic news feed."""
    try:
        import news_feed as _nf
        sig,meta=_nf.load_signals()
        out={"feed_status":meta.get("status"),"symbols":len(sig),
             "as_of":meta.get("as_of"),"status_line":_nf.status_line()}
        try:
            raw,rmeta=_nf.load_raw()
            out["raw_window"]=rmeta
        except Exception:
            pass
        if meta.get("status")!="ok":
            out["note"]=("No fresh verdicts — every symbol scores a neutral 50 "
                         "for news. Run POST /refresh-news.")
        return out
    except Exception as e:
        return {"status":"error","reason":f"{type(e).__name__}: {e}"}


@app.get("/news-verdict/{symbol}")
def news_verdict(symbol:str):
    """The stored verdict for one symbol, with its source URLs."""
    try:
        import news_feed as _nf
        v=_nf.get(symbol.upper())
        if not v:
            return {"symbol":symbol.upper(),"status":"no_verdict",
                    "note":"No fresh headline matched this ticker. News enters "
                           "the blend as a neutral 50 — silence is not scored "
                           "as good news."}
        return {"symbol":symbol.upper(),"status":"ok","verdict":v}
    except Exception as e:
        return {"status":"error","reason":f"{type(e).__name__}: {e}"}


@app.get("/regime-pro")
def regime_pro():
    """Benchmark-index regime gate from the ported V1 market_regime module."""
    if _v1_regime is None:
        return {"status":"unavailable",
                "reason":"market_regime not importable on this deployment",
                "note":"Use /market-regime for the breadth-based heuristic."}
    try:
        return {"status":"ok","regime":_v1_regime.assess_regime()}
    except Exception as e:
        return {"status":"error","reason":f"{type(e).__name__}: {e}",
                "note":"Regime unknown — gate fails OPEN by design."}

def backfill_ohlc_from_yahoo(symbol, range_="5y"):
    """Populate the daily_ohlc table (true O/H/L/C/V) for one symbol from Yahoo.

    WHY THIS EXISTS: PSX's EOD timeseries returns CLOSE ONLY. technical_analyzer
    reads its `ohlc` argument — not the close series — for the three indicators
    that genuinely require intraday range:
        * chaikin_money_flow  (where the close sits inside the day's range)
        * true ATR / ADX      (Wilder's true range)
    With daily_ohlc empty these correctly return None rather than being faked,
    which also means signal_generator's CMF Buy gate can never engage — and the
    graded history rates that gate highest (CMF-confirmed Buys beat the market
    83% vs 61% when flow was negative).

    ADJUSTMENT CAVEAT, stated plainly: Yahoo series are split/dividend adjusted;
    PSX EOD closes may not be. So the stored OHLC and the PSX close spine can sit
    on slightly different bases after a corporate action. Each indicator stays
    internally consistent (CMF/ATR read ONLY this table), and every row records
    its source, but the two are not interchangeable. Re-run after any split.
    """
    rows = yahoo_ohlcv(symbol.upper(), range_=range_)
    good = []
    for x in rows:
        try:
            o, h, l, c = (x.get("open"), x.get("high"), x.get("low"), x.get("close"))
            if None in (o, h, l, c):
                continue
            o, h, l, c = float(o), float(h), float(l), float(c)
            # reject rows that are not internally valid OHLC
            if not (l <= min(o, c) <= max(o, c) <= h) or c <= 0:
                continue
            d = datetime.fromtimestamp(int(x["time"]) / 1000,
                                       tz=timezone.utc).strftime("%Y-%m-%d")
            good.append((symbol.upper(), d, o, h, l, c,
                         float(x.get("volume") or 0), x.get("source", "Yahoo Finance")))
        except Exception:
            continue
    if good:
        ensure_ohlc()
        with db() as c:
            c.executemany("INSERT OR REPLACE INTO daily_ohlc VALUES(?,?,?,?,?,?,?,?)", good)
            c.commit()
    return {"symbol": symbol.upper(), "fetched": len(rows), "stored": len(good),
            "range": range_,
            "note": "Yahoo series are split/dividend adjusted; PSX EOD closes may "
                    "not be. CMF and true ATR/ADX read this table only."}


@app.post("/backfill-ohlc/{symbol}")
def backfill_ohlc(symbol:str, request:Request, range_:str="5y"):
    """Backfill true OHLC for one symbol so CMF and true ATR/ADX can compute."""
    _g=_require_admin(request)
    if _g: return _g
    try:
        r=backfill_ohlc_from_yahoo(symbol, range_)
        r["stored_sessions_now"]=len(ohlc_rows(symbol,10000))
        return r
    except Exception as e:
        return {"symbol":symbol.upper(),"status":"error",
                "reason":f"{type(e).__name__}: {e}",
                "note":"No OHLC is fabricated when the source is unavailable."}


@app.post("/backfill-ohlc-bulk")
def backfill_ohlc_bulk(request:Request, min_volume:int=MIN_VOLUME, limit:int=40, range_:str="5y"):
    """Backfill the most liquid names. Yahoo coverage of PSX tickers is partial —
    symbols with no data are listed as `missing`, never silently skipped."""
    _g=_require_admin(request)
    if _g: return _g
    import time as _t
    rows=market_watch()
    syms=[x["symbol"] for x in sorted(rows,key=lambda z:-z["volume"])
          if x["volume"]>=min_volume][:limit]
    done,missing=[],[]
    for s in syms:
        try:
            r=backfill_ohlc_from_yahoo(s, range_)
            (done if r["stored"]>0 else missing).append(
                {"symbol":s,"stored":r["stored"]} if r["stored"]>0 else s)
        except Exception:
            missing.append(s)
        _t.sleep(0.4)
    return {"requested":len(syms),"backfilled":len(done),"missing":missing,
            "detail":done,
            "note":"Run occasionally, not per request. Re-run after splits."}

def _reload_fundamentals_cache():
    """fundamentals_analyzer loads fundamentals.json ONCE at import and memoizes
    sector peer values. A freshly written file is therefore invisible to the
    running server (uvicorn --reload only watches .py). Reset both so new ratios
    take effect without a restart."""
    try:
        import fundamentals_analyzer as _fa
        _fa._CACHE = _fa._load_cache()
        _fa._SECTOR_VALUES = None
        return len((_fa._CACHE or {}).get("data", {}))
    except Exception:
        return None


def _sync_sectors_from_psx(rows):
    """Populate config.SECTORS from PSX's own sector names.

    fundamentals_analyzer blends each ratio with a SECTOR-RELATIVE percentile.
    Symbols absent from config.SECTORS fall back to "?" — so without this, every
    newly fetched symbol pools into one bucket and a bank's P/E gets ranked
    against a cement company's. `rows` already carries the resolved sector
    name (market_watch() translates PSX's raw numeric code via
    psx_sector_codes.name_for before this ever sees it), so just use it.
    Only fills gaps: hand-maintained config entries are never overwritten.
    """
    try:
        import config as _cfg
        sec = getattr(_cfg, "SECTORS", None)
        if sec is None:
            sec = {}; _cfg.SECTORS = sec
        added = 0
        for x in rows:
            s, name = x.get("symbol"), (x.get("sector") or "").strip()
            if s and name and s not in sec:
                sec[s] = name; added += 1
        return added
    except Exception:
        return 0


@app.post("/backfill-fundamentals")
def backfill_fundamentals(request:Request, min_volume:int=MIN_VOLUME, limit:int=60):
    """Fetch fundamental ratios for the most liquid PSX names, not just the
    10-symbol config.STOCKS universe the V1 engine shipped with.

    Merges into fundamentals.json (existing entries are kept), syncs
    config.SECTORS from PSX sector codes so the sector-relative blend is
    comparing like with like, and reloads the analyzer's in-memory cache.
    """
    _g=_require_admin(request)
    if _g: return _g
    try:
        import json as _json, time as _t
        import fundamentals_fetcher as _ff
        import requests as _rq

        rows=market_watch()
        synced=_sync_sectors_from_psx(rows)
        syms=[x["symbol"] for x in sorted(rows,key=lambda z:-z["volume"])
              if x["volume"]>=min_volume][:limit]

        path=os.path.join(os.path.dirname(os.path.abspath(__file__)),"fundamentals.json")
        try:
            with open(path,encoding="utf-8") as f: payload=_json.load(f)
        except Exception:
            payload={"as_of":None,"source":"stockanalysis.com (PSX)","data":{}}
        data=payload.get("data") or {}

        sess=_rq.Session(); sess.headers.update(_ff.UA)
        got,empty=[],[]
        for s in syms:
            try:
                d=_ff.fetch(s,sess)
            except Exception:
                d=None
            if d:
                data[s]=d; got.append({"symbol":s,"ratios":len(d)})
            else:
                empty.append(s)
            _t.sleep(0.5)

        payload["data"]=data
        payload["as_of"]=datetime.now(timezone.utc).date().isoformat()
        with open(path,"w",encoding="utf-8") as f:
            _json.dump(payload,f,indent=2)

        n=_reload_fundamentals_cache()
        return {"requested":len(syms),"fetched":len(got),"no_data":empty,
                "total_symbols_in_cache":n,"sectors_synced_from_psx":synced,
                "detail":got,
                "note":"Ratios change quarterly — re-run occasionally, not per "
                       "request. Symbols with no data keep a neutral 50 and stay "
                       "flagged low_confidence; nothing is invented."}
    except Exception as e:
        return {"status":"error","reason":f"{type(e).__name__}: {e}",
                "note":"No fundamentals are fabricated when the source is unavailable."}


@app.post("/reload-fundamentals")
def reload_fundamentals(request:Request):
    """Re-read fundamentals.json into the running process (no restart needed)."""
    _g=_require_admin(request)
    if _g: return _g
    n=_reload_fundamentals_cache()
    return ({"status":"ok","symbols_in_cache":n} if n is not None
            else {"status":"error","reason":"fundamentals_analyzer not importable"})

# ---- V2.6 explainable unified conviction engine ----
def clamp(v,a=0,b=100): return max(a,min(b,v))

def unified_components(q, hist, ohlc):
    # Scores are transparent heuristics, not probabilities.
    liquidity=clamp(20 + 16*math.log10(max(q.get("volume",1),1))) if q else 0
    momentum=clamp(50 + (q.get("pct",0) if q else 0)*6)
    trend=50; structure_score=50; wy=50
    if hist:
        v=_closes(hist)
        if len(v)>=20:
            ma20=sum(v[-20:])/20; trend += 20 if v[-1]>ma20 else -20
        if len(v)>=50:
            ma50=sum(v[-50:])/50; trend += 15 if v[-1]>ma50 else -15
        r=_rsi(v)
        if r is not None:
            trend += 10 if 50<=r<=70 else -8 if r<35 else 0
    if ohlc:
        st=structure_ohlc(ohlc); t=st.get("trend","")
        structure_score=75 if "UPTREND" in t else 25 if "DOWNTREND" in t else 50
        w=wyckoff_ohlc(ohlc); wy=clamp(w.get("confidence",45))
        if "SOS" in w.get("label","") or "Spring" in w.get("label",""): wy=clamp(wy+10)
    return {"liquidity":round(liquidity,1),"momentum":round(momentum,1),
            "trend":round(clamp(trend),1),"structure":round(structure_score,1),"wyckoff":round(wy,1)}

def conviction(q,hist,ohlc,symbol=None):
    c=unified_components(q,hist,ohlc)
    # V4.8: fundamentals are now INCLUDED (previously excluded as "not reliably
    # normalized"). fundamentals_analyzer returns a normalized 0-100 with an
    # explicit low_confidence flag — which is exactly the normalization that was
    # missing. When data is thin it returns a neutral 50 flagged low_confidence,
    # so we drop its weight to near-zero and redistribute: a symbol with no
    # audited ratios is neither rewarded nor punished for the absence.
    fund_meta=None
    weights={"liquidity":.20,"momentum":.20,"trend":.30,"structure":.20,"wyckoff":.10}
    if symbol:
        try:
            f=fundamental_analysis(symbol.upper())
            c["fundamentals"]=round(float(f.get("score",50)),1)
            fund_meta={"as_of":f.get("as_of"),"have":f.get("have",[]),
                       "low_confidence":bool(f.get("low_confidence")),
                       "notes":f.get("notes",[])}
            fw=.05 if f.get("low_confidence") else .20
            scale=1.0-fw
            weights={k:v*scale for k,v in weights.items()}
            weights["fundamentals"]=fw
        except Exception as e:
            fund_meta={"status":"error","message":str(e)}
    score=round(sum(c[k]*weights[k] for k in weights if k in c),1)
    reasons=[]
    for k,v in sorted(c.items(),key=lambda kv:kv[1],reverse=True):
        if v>=65: reasons.append(f"{k.title()} supportive ({v:.0f}/100)")
        elif v<=35: reasons.append(f"{k.title()} weak ({v:.0f}/100)")
    label="HIGH CONVICTION WATCH" if score>=75 else "CONSTRUCTIVE" if score>=62 else "NEUTRAL / WAIT" if score>=45 else "WEAK / AVOID"
    out={"score":score,"label":label,"components":c,"reasons":reasons,
         "weights":{k:round(v,3) for k,v in weights.items()},
         "meaning":"Explainable heuristic ranking score, not a probability of profit."}
    if fund_meta is not None: out["fundamentals_detail"]=fund_meta
    return out

@app.get("/conviction/{symbol}")
def conviction_symbol(symbol:str):
    rows=market_watch(); q=next((x for x in rows if x["symbol"]==symbol.upper()),None)
    if not q:return {"symbol":symbol.upper(),"status":"not_found"}
    hist=eod(symbol.upper()); oh=ohlc_rows(symbol,300)
    x=conviction(q,hist,oh,symbol=symbol)
    x.update({"symbol":symbol.upper(),"eligible":q["volume"]>=MIN_VOLUME,
              "liquidity_gate":MIN_VOLUME,"quote":q,
              "data_status":{"market":"PSX portal / delayed","ohlc_sessions":len(oh)}})
    return x

@app.get("/ranked-opportunities")
def ranked_opportunities(min_volume:int=MIN_VOLUME,shariah:bool=False,limit:int=30):
    rows=market_watch(); out=[]
    for q in rows:
        if q["volume"]<min_volume or (shariah and not q["shariah"]): continue
        # Trend/RSI in unified_components() only need close prices, which the
        # locally-stored daily_ohlc already has — reuse it instead of a live
        # eod() network fetch per symbol (was N sequential PSX round-trips per
        # request, blowing well past the dashboard's 20s timeout).
        oh=ohlc_rows(q["symbol"],300)
        x=conviction(q,oh,oh)
        out.append({"symbol":q["symbol"],"sector":q["sector"],"price":q["price"],"pct":q["pct"],
                    "volume":q["volume"],"shariah":q["shariah"],**x})
    out.sort(key=lambda z:z["score"],reverse=True)
    return out[:limit]

# ---- V2.7 market + sector intelligence ----
@app.get("/market-regime")
def market_regime():
    rows=market_watch()
    elig=[x for x in rows if x["volume"]>=MIN_VOLUME]
    adv=sum(x["pct"]>0 for x in elig); dec=sum(x["pct"]<0 for x in elig)
    breadth=100*adv/max(1,adv+dec)
    avg=sum(x["pct"] for x in elig)/max(1,len(elig))
    # Membership-aware breadth for major index universes.
    universes={}
    for idx in ["KSE100","KMI30","ALLSHR","KMIALLSHR"]:
        a=[x for x in rows if idx in x.get("listed","")]
        ia=sum(x["pct"]>0 for x in a); idc=sum(x["pct"]<0 for x in a)
        universes[idx]={"members":len(a),"adv":ia,"dec":idc,
                        "breadth_pct":round(100*ia/max(1,ia+idc),1),
                        "avg_change_pct":round(sum(x["pct"] for x in a)/max(1,len(a)),2)}
    score=clamp(.6*breadth + .4*clamp(50+avg*10))
    label="RISK-ON" if score>=65 else "CONSTRUCTIVE" if score>=55 else "MIXED" if score>=45 else "RISK-OFF"
    return {"label":label,"score":round(score,1),"eligible_stocks":len(elig),
            "breadth_pct":round(breadth,1),"avg_change_pct":round(avg,2),"indices":universes,
            "note":"Breadth/regime heuristic from current PSX market-watch constituents; not a forecast."}

@app.get("/sector-rotation")
def sector_rotation():
    rows=market_watch(); d={}
    for x in rows:
        if x["volume"]<MIN_VOLUME: continue
        a=d.setdefault(x["sector"],{"sector":x["sector"],"n":0,"adv":0,"pct":0.0,"volume":0.0,"leaders":[]})
        a["n"]+=1;a["adv"]+=x["pct"]>0;a["pct"]+=x["pct"];a["volume"]+=x["volume"]
        a["leaders"].append((x["pct"],x["symbol"]))
    out=[]
    for a in d.values():
        breadth=100*a["adv"]/max(1,a["n"]); avg=a["pct"]/max(1,a["n"])
        strength=clamp(.55*breadth+.45*clamp(50+avg*10))
        leaders=[s for _,s in sorted(a["leaders"],reverse=True)[:3]]
        out.append({"sector":a["sector"],"eligible_members":a["n"],"breadth_pct":round(breadth,1),
                    "avg_change_pct":round(avg,2),"volume":a["volume"],"strength":round(strength,1),
                    "leaders":leaders})
    return sorted(out,key=lambda z:z["strength"],reverse=True)

@app.get("/relative-strength/{symbol}")
def relative_strength(symbol:str):
    rows=market_watch(); q=next((x for x in rows if x["symbol"]==symbol.upper()),None)
    if not q:return {"status":"not_found"}
    sector=[x for x in rows if x["sector"]==q["sector"] and x["volume"]>=MIN_VOLUME]
    secavg=sum(x["pct"] for x in sector)/max(1,len(sector))
    kse=[x for x in rows if "KSE100" in x.get("listed","")]
    kavg=sum(x["pct"] for x in kse)/max(1,len(kse))
    return {"symbol":q["symbol"],"stock_change_pct":q["pct"],"sector":q["sector"],
            "vs_sector_pct":round(q["pct"]-secavg,2),"vs_kse100_constituents_pct":round(q["pct"]-kavg,2),
            "note":"Current-session relative strength proxy; multi-session RS requires historical benchmark series."}


def _rs_multi_for(sym, a, rows=None):
    """Shared by /relative-strength-multi and /dss so both compute the exact
    same real multi-period relative strength, not two slightly different
    versions. `a`: this symbol's stored true-OHLC (may be empty/None)."""
    if not a or len(a) < 10:
        return {"status": "insufficient_history",
                "reason": "Needs stored true-OHLC — backfill this symbol from the More tab."}
    rows = rows if rows is not None else market_watch()
    q = next((x for x in rows if x["symbol"] == sym), None)
    idx_hist = _psx_live.index_history("KSE100", limit=280) if _psx_live else None
    peers = {}
    if q:
        cov = ohlc_coverage()
        peer_syms = {r["symbol"] for r in cov if r["symbol"] != sym}
        same_sector = [x["symbol"] for x in rows if x["symbol"] in peer_syms and x["sector"] == q["sector"]]
        peers = ohlc_rows_multi(same_sector, 300)
    return _rse.compute(a, idx_hist, peers)


@app.get("/relative-strength-multi/{symbol}")
def relative_strength_multi(symbol:str):
    """STEP 32: real 1W/1M/3M/6M/12M relative strength vs KSE-100 (from
    psx_live.index_history — confirmed public) and vs same-sector backfilled
    peers, using each stock's own stored true-OHLC. Upgrades /relative-strength's
    single-session proxy with an actual historical benchmark series."""
    sym = symbol.upper()
    result = _rs_multi_for(sym, ohlc_rows(sym, 300))
    result["symbol"] = sym
    return result


@app.get("/relative-strength-series/{symbol}")
def relative_strength_series(symbol:str, lookback:int=252):
    """STEP 60 Dashboard Page 8: the actual plottable rebased-to-100 daily
    series (stock/KSE-100/sector) — the chart, not just period-return numbers."""
    sym = symbol.upper()
    a = ohlc_rows(sym, lookback + 20)
    if not a or len(a) < 10:
        return {"symbol": sym, "status": "insufficient_history"}
    rows = market_watch()
    q = next((x for x in rows if x["symbol"] == sym), None)
    idx_hist = _psx_live.index_history("KSE100", limit=lookback + 30) if _psx_live else None
    peers = {}
    if q:
        cov = ohlc_coverage()
        peer_syms = {r["symbol"] for r in cov if r["symbol"] != sym}
        for x in rows:
            if x["symbol"] in peer_syms and x["sector"] == q["sector"]:
                peers[x["symbol"]] = ohlc_rows(x["symbol"], lookback + 20)
    result = _rse.daily_series(a, idx_hist, peers, lookback=lookback)
    result["symbol"] = sym
    return result


@app.get("/market-command-center")
def market_command_center():
    """STEP 60 Dashboard Page 1: KSE-100 trend/regime/momentum/volatility,
    breadth, top/bottom sectors — one glance at the whole market, built from
    endpoints that already exist (no new analysis, just assembled)."""
    regime = market_regime()
    sectors = sector_rotation()
    top_sectors = sorted(sectors, key=lambda s: -s["strength"])[:3]
    bottom_sectors = sorted(sectors, key=lambda s: s["strength"])[:3]
    idx_hist = _psx_live.index_history("KSE100", limit=280) if _psx_live else None
    vol = _wyckoff2.volatility_regime(idx_hist) if idx_hist else {"status": "unavailable"}
    return {"status": "ok", "market_regime": regime, "top_sectors": top_sectors,
            "bottom_sectors": bottom_sectors, "kse100_volatility_regime": vol}


# ---- V2.8 announcements intelligence + grounded AI-ready synthesis ----
POS=["dividend","bonus","right issue","contract","award","growth","increase","profit","approval","expansion"]
NEG=["loss","decline","decrease","suspension","default","penalty","adverse","termination","shutdown"]
HIGH=["material information","financial results","dividend","merger","acquisition","right issue","bonus","default","suspension"]

def classify_headline(title):
    t=(title or "").lower()
    pos=sum(x in t for x in POS); neg=sum(x in t for x in NEG)
    direction="POSITIVE" if pos>neg else "NEGATIVE" if neg>pos else "NEUTRAL / REVIEW"
    materiality="HIGH" if any(x in t for x in HIGH) else "MEDIUM"
    return {"direction":direction,"materiality":materiality}

@app.get("/announcement-intelligence/{symbol}")
def announcement_intelligence(symbol:str):
    # Company pages expose Financial Results / Board Meetings / Others.
    url=f"{PSX}/company/{symbol.upper()}"
    r=requests.get(url,headers=HEAD,timeout=15);r.raise_for_status()
    from bs4 import BeautifulSoup
    soup=BeautifulSoup(r.text,"html.parser")
    items=[]
    # Conservative extraction: classify only visible titles; never invent document contents.
    for tr in soup.select("tr"):
        cells=[x.get_text(" ",strip=True) for x in tr.select("td")]
        if len(cells)>=2 and any(k in cells[1].lower() for k in
            ["financial","material","board","dividend","report","meeting","appointment","change","notice","result"]):
            title=cells[1][:240]
            items.append({"date":cells[0][:40],"title":title,**classify_headline(title)})
    return {"symbol":symbol.upper(),"source":url,"items":items[:30],
            "warning":"Classification uses headline text only; open the official document before acting."}

@app.get("/ai-brief/{symbol}")
def ai_brief(symbol:str):
    # Grounded deterministic brief. A remote LLM can later rewrite this evidence, but may not alter facts.
    cv=conviction_symbol(symbol)
    if cv.get("status")=="not_found":return cv
    try: anns=announcement_intelligence(symbol).get("items",[])[:5]
    except: anns=[]
    try: rs=relative_strength(symbol)
    except: rs={}
    try: regime=market_regime()
    except: regime={}
    bull=[];bear=[];confirm=[];invalidate=[]
    comp=cv.get("components",{})
    if comp.get("trend",50)>=65:bull.append("Historical trend evidence is supportive.")
    if comp.get("structure",50)>=65:bull.append("Stored OHLC structure is constructive.")
    if comp.get("liquidity",0)>=65:bull.append("Liquidity evidence is adequate.")
    if comp.get("trend",50)<=35:bear.append("Historical trend evidence is weak.")
    if comp.get("structure",50)<=35:bear.append("Stored OHLC structure is bearish.")
    if rs.get("vs_sector_pct",0)>0:bull.append("Stock is outperforming its sector today.")
    elif rs.get("vs_sector_pct",0)<0:bear.append("Stock is underperforming its sector today.")
    if regime.get("label")=="RISK-OFF":bear.append("Broad market regime is risk-off.")
    elif regime.get("label") in ["RISK-ON","CONSTRUCTIVE"]:bull.append("Broad market context is supportive.")
    if anns: confirm.append("Review the latest official PSX disclosures before taking a position.")
    confirm.append("Require price/volume confirmation; a high evidence score is not a profit probability.")
    invalidate.append("Reassess if structure/trend components deteriorate or new material disclosures contradict the thesis.")
    # Additional intelligence engines
    try:
        hist, _hist_src = best_history(symbol.upper())

        candles = []

        for x in hist[-30:]:
            candles.append(
                type("Candle", (), {
                    "o": x.get("open",0) or 0,
                    "h": x.get("high",0) or 0,
                    "l": x.get("low",0) or 0,
                    "c": x.get("close",0) or 0,
                    "v": x.get("volume",0) or 0
                })()
            )

        volume_intel = volume_analysis(candles)

    except Exception as e:
        volume_intel = {
            "status":"error",
            "message":str(e)
        }


    try:
        fundamentals = fundamental_analysis(symbol.upper())

    except Exception as e:
        fundamentals = {
            "status":"error",
            "message":str(e)
        }


    try:
        from news_feed import get as news_get
        news_intel = news_get(symbol.upper()) or {
            "status":"no_news_signal"
        }

    except Exception as e:
        news_intel = {
            "status":"error",
            "message":str(e)
        }

    return {"symbol":symbol.upper(),
            "evidence_score":cv.get("score"),
            "label":cv.get("label"),
            "volume_intelligence":volume_intel,
            "fundamentals":fundamentals,
            "news_intelligence":news_intel,
            "bull_case":bull,"bear_case":bear,"confirmation":confirm,"invalidation":invalidate,
            "latest_announcements":anns,
            "llm_policy":"Any future LLM layer must summarize this grounded evidence and cite sources; it may not invent prices, indicators, filings or probabilities."}

# ---- V3.0 Wyckoff Pro: conservative event/quality engine ----
def _avg(xs): return sum(xs)/len(xs) if xs else 0
def _spread(x): return max(0.000001, x["high"]-x["low"])
def _close_pos(x): return (x["close"]-x["low"])/_spread(x)

def effort_result(a, lookback=20):
    if len(a)<lookback+2:return {"status":"insufficient_history"}
    recent=a[-lookback:]
    avgv=_avg([x["volume"] for x in recent[:-1]])
    avgs=_avg([_spread(x) for x in recent[:-1]])
    x=recent[-1]
    vr=x["volume"]/max(1,avgv); sr=_spread(x)/max(.000001,avgs)
    progress=abs(x["close"]-recent[-2]["close"])/max(.000001,avgs)
    if vr>=1.5 and progress<.5: state="HIGH EFFORT / LOW RESULT — possible absorption or supply"
    elif vr>=1.2 and sr>=1.2: state="EFFORT & RESULT IN HARMONY"
    elif vr<.8 and progress>=1.0: state="LOW EFFORT / LARGE RESULT — low opposing supply/demand"
    else: state="BALANCED / INCONCLUSIVE"
    return {"volume_ratio":round(vr,2),"spread_ratio":round(sr,2),"progress_ratio":round(progress,2),"state":state}

def trading_range(a, window=40):
    if len(a)<window:return None
    r=a[-window:]
    hi=max(x["high"] for x in r[:-3]); lo=min(x["low"] for x in r[:-3])
    width=(hi-lo)/max(.000001,(hi+lo)/2)
    return {"support":lo,"resistance":hi,"width_pct":round(width*100,2),"bars":window}

def spring_quality(a):
    tr=trading_range(a)
    if not tr or len(a)<45:return {"status":"UNRESOLVED"}
    sup=tr["support"]; cand=None
    for k in range(max(0,len(a)-8),len(a)):
        x=a[k]
        if x["low"]<sup and x["close"]>sup:
            cand=k
    if cand is None:return {"status":"NOT DETECTED"}
    x=a[cand]; prev=a[max(0,cand-20):cand]
    avgv=_avg([q["volume"] for q in prev]); penetration=(sup-x["low"])/max(.000001,sup)*100
    recovery=0
    for k in range(cand,min(len(a),cand+4)):
        if a[k]["close"]>sup: recovery=k-cand+1;break
    test=None
    for k in range(cand+1,min(len(a),cand+8)):
        if a[k]["low"]>x["low"] and a[k]["volume"]<x["volume"]:
            test=k;break
    sos=False
    for k in range(cand+1,len(a)):
        if a[k]["close"]>tr["resistance"] and a[k]["volume"]>max(1,avgv):
            sos=True;break
    pts=0;criteria={}
    criteria["closed_back_in_range"]=x["close"]>sup; pts+=20 if criteria["closed_back_in_range"] else 0
    criteria["recovery_1_3_bars"]=1<=recovery<=3; pts+=20 if criteria["recovery_1_3_bars"] else 0
    criteria["volume_not_extreme"]=x["volume"]<=avgv*1.5 if avgv else False; pts+=15 if criteria["volume_not_extreme"] else 0
    criteria["successful_test"]=test is not None; pts+=20 if test is not None else 0
    criteria["sos_confirmed"]=sos; pts+=25 if sos else 0
    stage="CONFIRMED" if sos and test is not None else "TESTED" if test is not None else "CANDIDATE"
    evidence="HIGH" if pts>=75 else "MEDIUM" if pts>=50 else "LOW"
    return {"status":stage,"evidence":evidence,"quality_score":pts,"penetration_pct":round(penetration,2),
            "recovery_bars":recovery or None,"criteria":criteria,"support":sup,"resistance":tr["resistance"],
            "note":"Evidence score is not a probability of profit."}

def upthrust_quality(a):
    tr=trading_range(a)
    if not tr or len(a)<45:return {"status":"UNRESOLVED"}
    res=tr["resistance"]; cand=None
    for k in range(max(0,len(a)-8),len(a)):
        x=a[k]
        if x["high"]>res and x["close"]<res:cand=k
    if cand is None:return {"status":"NOT DETECTED"}
    x=a[cand]; prev=a[max(0,cand-20):cand]; avgv=_avg([q["volume"] for q in prev])
    penetration=(x["high"]-res)/max(.000001,res)*100
    sow=False
    for k in range(cand+1,len(a)):
        if a[k]["close"]<tr["support"] and a[k]["volume"]>max(1,avgv):sow=True;break
    pts=20 + (20 if x["volume"]>=avgv else 5) + (25 if sow else 0)
    prompt=(cand==len(a)-1 or any(a[k]["close"]<res for k in range(cand,min(len(a),cand+3))))
    pts+=20 if prompt else 0
    criteria={"closed_back_in_range":True,"prompt_rejection":prompt,"elevated_volume":x["volume"]>=avgv,"sow_confirmed":sow}
    stage="CONFIRMED" if sow else "CANDIDATE"
    return {"status":stage,"evidence":"HIGH" if pts>=75 else "MEDIUM" if pts>=50 else "LOW",
            "quality_score":min(100,pts),"penetration_pct":round(penetration,2),"criteria":criteria,
            "support":tr["support"],"resistance":res,"note":"UT/UTAD distinction requires broader phase context."}

def _is_pausing(a, tr, recent=15, contraction_ratio=0.55):
    """Distinguishes a genuine re-accumulation/re-distribution pause (price is
    consolidating into a tighter range within an ongoing trend) from plain
    markup/markdown (price is still trending/expanding, no pause at all).
    Compares the width of the most recent `recent` bars against the broader
    40-bar trading_range width — a real pause meaningfully contracts, it
    isn't just labeled from trend direction alone."""
    if not tr or len(a) < recent + 5:
        return False
    window = a[-recent:]
    hi, lo = max(x["high"] for x in window), min(x["low"] for x in window)
    mid = _avg([x["close"] for x in window])
    if not mid:
        return False
    recent_width_pct = (hi - lo) / mid * 100
    return tr["width_pct"] > 0 and recent_width_pct <= tr["width_pct"] * contraction_ratio


def wyckoff_pro(a):
    if len(a)<50:return {"phase":"UNRESOLVED","reason":"Need >=50 genuine OHLCV sessions"}
    tr=trading_range(a); er=effort_result(a); sp=spring_quality(a); ut=upthrust_quality(a); st=structure_ohlc(a)
    phase="UNRESOLVED"
    if sp.get("status")=="CONFIRMED":phase="ACCUMULATION — Phase D candidate"
    elif sp.get("status") in ("CANDIDATE","TESTED"):phase="ACCUMULATION — Phase C hypothesis"
    elif ut.get("status")=="CONFIRMED":phase="DISTRIBUTION — Phase D candidate"
    elif ut.get("status")=="CANDIDATE":phase="DISTRIBUTION — Phase C hypothesis"
    elif "UPTREND" in st.get("trend",""):
        phase="RE-ACCUMULATION — trend pausing into a tighter range" if _is_pausing(a, tr) else "MARKUP — trend continuing, no pause detected"
    elif "DOWNTREND" in st.get("trend",""):
        phase="RE-DISTRIBUTION — trend pausing into a tighter range" if _is_pausing(a, tr) else "MARKDOWN — trend continuing, no pause detected"
    return {"phase":phase,"trading_range":tr,"effort_vs_result":er,"spring":sp,"upthrust":ut,
            "structure":st,"principle":"Conservative labeling: unresolved when classic criteria are not met. "
            "Re-accumulation/re-distribution requires a genuine range contraction within the trend, not just "
            "trend direction — plain trend continuation is labeled MARKUP/MARKDOWN instead."}

@app.get("/wyckoff-pro/{symbol}")
def wyckoff_pro_endpoint(symbol:str):
    a=ohlc_rows(symbol,400)
    if not a:return {"symbol":symbol.upper(),"status":"awaiting_true_ohlcv"}
    return {"symbol":symbol.upper(),"sessions":len(a),**wyckoff_pro(a)}


# ============================================================================
# V4.10 — psx_brain / psx_live merge
# ============================================================================

def _brain_frame(symbol):
    """Build the OHLCV DataFrame psx_brain.analyse() needs.

    Prefers stored true OHLC (daily_ohlc, backfilled from Yahoo) since it's
    already on disk and validated; falls back to a direct Yahoo pull. PSX EOD
    alone is close-only and can't feed Bollinger/Keltner/Ichimoku/ATR, so it is
    deliberately not used here — same rule /technical-pro follows.
    Returns (df, source) or (None, reason).
    """
    if _psx_report is None:
        return None, "psx_report not importable on this deployment"
    sym = symbol.upper()
    a = ohlc_rows(sym, 400)
    if len(a) >= 60:
        try:
            import pandas as _pd
            df = _pd.DataFrame(a)
            df["date"] = _pd.to_datetime(df["trade_date"])
            df = df.set_index("date")[["open", "high", "low", "close", "volume"]]
            return _psx_report.normalise(df), "stored daily_ohlc"
        except Exception as e:
            pass
    try:
        rows = yahoo_ohlcv(sym)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    if len(rows) >= 60:
        try:
            import pandas as _pd
            df = _pd.DataFrame(rows)
            df["date"] = _pd.to_datetime(df["time"], unit="ms")
            df = df.set_index("date")[["open", "high", "low", "close", "volume"]]
            return _psx_report.normalise(df), f"Yahoo Finance {sym}.KA"
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"
    return None, "fewer than 60 true-OHLC sessions available (stored or Yahoo)"


@app.get("/verdict/{symbol}")
def verdict(symbol:str):
    """psx_brain's full verdict: score, bull/bear reasoning, trade plan.

    This is a second, independent read on top of /technical-pro and
    /wyckoff-pro — same truth rule: no score is produced without >=60 real
    OHLCV sessions, and the response says exactly why when it can't run.
    """
    if _psx_brain is None:
        return {"symbol":symbol.upper(),"status":"unavailable",
                "reason":"psx_brain not importable on this deployment"}
    df, source_or_err = _brain_frame(symbol)
    if df is None:
        return {"symbol":symbol.upper(),"status":"unavailable","reason":source_or_err,
                "note":"No verdict is fabricated without real OHLCV history."}
    try:
        res = _psx_brain.analyse(symbol.upper(), df)
        res["status"] = "ok"
        res["history_source"] = source_or_err
        return res
    except Exception as e:
        return {"symbol":symbol.upper(),"status":"error","reason":f"{type(e).__name__}: {e}"}


@app.get("/wyckoff-events/{symbol}")
def wyckoff_events(symbol:str):
    """Full named Wyckoff event sequence (STEP 9-10) plus the 9 classical
    Buying/Selling Tests (STEP 14-15) — heuristic, evidence-cited, honest
    about what wasn't found. Extends /wyckoff-pro (phase/spring/upthrust,
    left untouched) rather than replacing it."""
    sym = symbol.upper()
    a = ohlc_rows(sym, 400)
    if not a:
        return {"symbol": sym, "status": "awaiting_true_ohlcv"}
    rs = relative_strength(sym)
    rs_positive = None
    if rs.get("status") != "not_found":
        rs_positive = (rs.get("vs_sector_pct", 0) + rs.get("vs_kse100_constituents_pct", 0)) > 0
    accum = _wyckoff2.accumulation_events(a)
    distrib = _wyckoff2.distribution_events(a)
    return {"symbol": sym, "status": "ok",
            "accumulation": accum, "distribution": distrib,
            "buying_tests": _wyckoff2.nine_buying_tests(a, accum, rs_positive),
            "selling_tests": _wyckoff2.nine_selling_tests(a, distrib, rs_positive),
            "volatility_regime": _wyckoff2.volatility_regime(a)}


@app.get("/price-action/{symbol}")
def price_action(symbol:str):
    """Al Brooks bar-by-bar classification, trend strength, and breakout/
    pullback quality (STEP 19-22) — the layer between raw structure and
    candlestick psychology."""
    sym = symbol.upper()
    a = ohlc_rows(sym, 400)
    if not a:
        return {"symbol": sym, "status": "awaiting_true_ohlcv"}
    st = structure_ohlc(a)
    bullish = "UPTREND" in st.get("trend", "")
    tr = trading_range(a) or {}
    level = tr.get("resistance") if bullish else tr.get("support")
    bo = _pae.breakout_quality(a, level, "up" if bullish else "down") if level else {"status": "no_level"}
    return {"symbol": sym, "status": "ok",
            "recent_bars": _pae.classify_recent_bars(a, 10),
            "trend_strength": _pae.trend_strength(a, 10, bullish=bullish),
            "breakout_quality": bo}


def _weekly_structure(a):
    """STEP 56: resample daily true-OHLC to weekly bars and read the same
    HH/HL structure test used daily — the 'strategic' timeframe layer."""
    if len(a) < 60:
        return {"status": "insufficient_history"}
    df = pd.DataFrame(a)
    df["date"] = pd.to_datetime(df["trade_date"])
    df = df.set_index("date").sort_index()
    weekly = df.resample("W").agg({"open": "first", "high": "max", "low": "min",
                                    "close": "last", "volume": "sum"}).dropna()
    if len(weekly) < 20:
        return {"status": "insufficient_history"}
    wa = [{"trade_date": str(d.date()), "open": r.open, "high": r.high, "low": r.low,
           "close": r.close, "volume": r.volume} for d, r in weekly.iterrows()]
    return {"status": "ok", "bars": len(wa), "structure": structure_ohlc(wa)}


@app.get("/dss/{symbol}")
def dss(symbol:str):
    """Decision Support System — assembles market regime, sector regime,
    Wyckoff phase/effort-vs-result, structure, candlesticks, momentum,
    relative strength, psx_brain's trade plan and /decision's integrated
    signal into one confluence matrix, evidence score, confidence grade and
    final action. See dss_engine.py for the full methodology and for which
    layers (historical pattern stats, quant baseline validation) are
    explicitly PENDING rather than fabricated.
    """
    sym = symbol.upper()
    rows = market_watch()
    q = next((x for x in rows if x["symbol"] == sym), None)
    if not q:
        return {"symbol": sym, "status": "not_found"}
    _sync_sectors_from_psx(rows)

    regime = market_regime()
    sec_all = sector_rotation()
    sector_row = next((s for s in sec_all if s["sector"] == q["sector"]), None)
    rs = relative_strength(sym)

    a = ohlc_rows(sym, 400)
    wy = {"symbol": sym, "status": "awaiting_true_ohlcv"} if not a else {"symbol": sym, "sessions": len(a), **wyckoff_pro(a)}
    technical, _terr = v1_technical(sym, quote=q)
    candles = intelligence(sym)
    v = verdict(sym)
    dec = decision(sym, record=False)

    weekly = _weekly_structure(a) if a else {"status": "awaiting_true_ohlcv"}
    vol_regime = _wyckoff2.volatility_regime(a) if a else {"status": "awaiting_true_ohlcv"}
    event_risk = _event_risk(sym)
    rs_multi = _rs_multi_for(sym, a, rows) if a else {"status": "insufficient_history"}
    dq = _dq.audit(a) if a else {"status": "missing"}
    liq = _dq.classify_liquidity(a) if a else {"status": "insufficient_history"}

    result = _dss.compute(symbol=sym, quote=q, regime=regime, sector_row=sector_row, rs=rs,
                           wy=wy, technical=technical, candles=candles, verdict=v, decision_=dec,
                           weekly=weekly, event_risk=event_risk, rs_multi=rs_multi,
                           liquidity=liq, data_quality=dq, ohlc_rows=a)
    result["status"] = "ok"
    result["volatility_regime"] = vol_regime
    result["relative_strength_multi"] = rs_multi

    # STEP 67-70: diff against the prior saved snapshot BEFORE overwriting it,
    # map the Wyckoff event chain onto a lifecycle stage, then persist this
    # run as the new latest snapshot for next time.
    wyckoff_events = None
    if a:
        wyckoff_events = {"accumulation": _wyckoff2.accumulation_events(a),
                          "distribution": _wyckoff2.distribution_events(a)}
    prev_snapshot = _audit.latest_snapshot(sym)
    result["since_last_check"] = _audit.diff_snapshots(prev_snapshot, result, wyckoff_events)
    result["signal_state"] = _audit.signal_state(wyckoff_events, result.get("final_action"))
    result["wyckoff_events"] = wyckoff_events
    _audit.save_snapshot(sym, result, wyckoff_events)
    return result


@app.get("/dss/{symbol}/report")
def dss_formal_report(symbol:str):
    """STEP 61: the 16-part formal stock report, built entirely from the same
    /dss/{symbol} result — a formatting layer, not a second analysis pass."""
    sym = symbol.upper()
    d = dss(sym)
    if d.get("status") != "ok":
        return d
    return {"symbol": sym, "status": "ok", "report_markdown": _dss.format_formal_report(d)}


@app.get("/dss/{symbol}/history")
def dss_history(symbol:str, limit:int=30):
    """STEP 70: audit trail — every past snapshot for this symbol, for
    verifying whether past recommendations held up."""
    return {"symbol": symbol.upper(), "status": "ok", "snapshots": _audit.get_history(symbol, limit)}


def _run_failure_analysis_full(min_age_days=20, horizon_days=20):
    result = _audit.grade_outcomes(lambda sym: ohlc_rows(sym, 5000),
                                    min_age_days=min_age_days, horizon_days=horizon_days)
    result["status"] = "ok"
    return result


@app.get("/audit/failure-analysis")
def failure_analysis(request:Request, min_age_days:int=20, horizon_days:int=20, force:bool=False):
    """STEP 71: retroactively grade past BUY-leaning snapshots against real
    subsequent stored true-OHLC — target-vs-invalidation race, with cited
    failure reasons for losses. Cached (auto-refreshed daily alongside the
    other heavy analyses) for the default parameters; non-default parameters
    or force=true always recompute live and admin-gate that path."""
    is_default = (min_age_days, horizon_days) == (20, 20)
    if is_default and not force:
        cached = _scan_cache.latest("failure_analysis")
        if cached:
            return cached
    _g=_require_admin(request)
    if _g: return _g
    result = _run_failure_analysis_full(min_age_days, horizon_days)
    if is_default:
        _scan_cache.save("failure_analysis", result)
    return result


def _event_risk(sym):
    """STEP 37: is there a real recent HIGH-materiality company announcement
    that could explain a volume spike, so it isn't misread as Wyckoff
    accumulation/distribution? Best-effort — degrades to UNKNOWN, never
    silently treated as 'no risk'."""
    try:
        items = announcement_intelligence(sym).get("items", [])[:10]
    except Exception:
        return {"level": "UNKNOWN", "reason": "Announcement page unavailable.", "items": []}
    high = [x for x in items if x.get("materiality") == "HIGH"]
    if high:
        return {"level": "HIGH", "items": high[:3],
                "reason": "Recent HIGH-materiality announcement(s) — a volume/price move around "
                          "this time may be event-driven, not pure supply/demand."}
    if items:
        return {"level": "MEDIUM", "items": items[:3], "reason": "Recent announcements, none flagged HIGH materiality."}
    return {"level": "LOW", "items": [], "reason": "No recent announcements found on the company page."}


def _run_backtest_full():
    cov = ohlc_coverage()
    universe = {r["symbol"]: ohlc_rows(r["symbol"], 5000) for r in cov if r["sessions"] >= 60}
    if not universe:
        return {"status": "unavailable", "reason": "No symbols with >=60 stored true-OHLC sessions. "
                                                     "Backfill some from the More tab first."}
    summary = _bt.run_backtest(universe)
    summary["status"] = "ok"
    return summary


@app.post("/backtest/run")
def backtest_run(request:Request, force:bool=False):
    """Real walk-forward pattern backtest over every symbol with stored
    true-OHLC (daily_ohlc) — see backtest_engine.py. Auto-refreshed once a
    day in the background (patterns computed from daily bars don't shift
    within a day) and served from cache instantly; force=true or a stale
    cache falls back to a live (admin-gated) recompute.
    """
    cached = _scan_cache.latest("backtest_run")
    result, err = _serve_cached_and_refresh("backtest_run", _run_backtest_full, cached,
                                             _scan_cache.HEAVY_MAX_AGE_SECONDS, force,
                                             lambda: _require_admin(request))
    if err: return err
    result = dict(result); result["_background_refresh_running"] = _bg_job_running("backtest_run")
    return result


@app.get("/backtest/status")
def backtest_status():
    """Latest backtest run metadata plus the top patterns by expectancy at
    the 20-day horizon, for a quick sanity check without pulling everything."""
    run = _bt.latest_run()
    if not run:
        return {"status": "not_run", "reason": "No backtest has been run yet. POST /backtest/run."}
    top = _bt.all_pattern_stats(horizon=_dss.STATS_HORIZON, run_id=run["id"])
    baselines = _bt.all_baseline_stats(horizon=_dss.STATS_HORIZON, run_id=run["id"])
    return {"status": "ok", "run": run, "horizon": _dss.STATS_HORIZON,
            "patterns": top, "baselines": baselines}


def _run_walkforward_full(train_frac=0.6, val_frac=0.2, cost_pct=_wf.DEFAULT_ROUND_TRIP_COST_PCT, horizon=20):
    cov = ohlc_coverage()
    universe = {r["symbol"]: ohlc_rows(r["symbol"], 5000) for r in cov if r["sessions"] >= 100}
    if not universe:
        return {"status": "unavailable", "reason": "No symbols with >=100 stored true-OHLC sessions "
                                                     "(walk-forward needs more history per symbol than "
                                                     "the single-pass backtest to leave a usable test slice)."}
    result = _wf.run_walkforward(universe, train_frac=train_frac, val_frac=val_frac,
                                  cost_pct=cost_pct, horizon=horizon)
    result["status"] = "ok"
    result["universe_symbols"] = len(universe)
    return result


@app.post("/backtest/walkforward")
def backtest_walkforward(request:Request, train_frac:float=0.6, val_frac:float=0.2,
                          cost_pct:float=_wf.DEFAULT_ROUND_TRIP_COST_PCT, horizon:int=20, force:bool=False):
    """STEP 52-53/65-66: chronological train/validation/out-of-sample split,
    net-of-cost expectancy, feature importance, calibration. Auto-refreshed
    daily in the background for the default parameters and served from cache
    instantly; non-default parameters or force=true always recompute live
    (admin-gated) — same expense profile as /backtest/run, just partitioned.
    """
    is_default = (train_frac, val_frac, cost_pct, horizon) == (0.6, 0.2, _wf.DEFAULT_ROUND_TRIP_COST_PCT, 20)
    if not is_default:
        # Non-default params can't be cached under the shared "walkforward" key
        # (they'd clobber the default run's cache) — these are rare, manual,
        # single-operator calls, so run synchronously rather than adding
        # per-parameter cache keys for a path nobody hits repeatedly.
        _g=_require_admin(request)
        if _g: return _g
        return _run_walkforward_full(train_frac, val_frac, cost_pct, horizon)
    cached = _scan_cache.latest("walkforward")
    result, err = _serve_cached_and_refresh(
        "walkforward", lambda: _run_walkforward_full(train_frac, val_frac, cost_pct, horizon),
        cached, _scan_cache.HEAVY_MAX_AGE_SECONDS, force, lambda: _require_admin(request))
    if err: return err
    result = dict(result); result["_background_refresh_running"] = _bg_job_running("walkforward")
    return result


def _run_regime_split_full(horizon=20):
    cov = ohlc_coverage()
    universe = {r["symbol"]: ohlc_rows(r["symbol"], 5000) for r in cov if r["sessions"] >= 100}
    if not universe:
        return {"status": "unavailable", "reason": "No symbols with >=100 stored true-OHLC sessions."}
    index_rows = _psx_live.index_history("KSE100", limit=1500) if _psx_live else None
    if not index_rows:
        return {"status": "unavailable", "reason": "KSE-100 historical index data unavailable right now."}
    result = _rbt.run_regime_split(universe, index_rows, horizon=horizon)
    result["status"] = "ok"
    result["universe_symbols"] = len(universe)
    return result


@app.post("/backtest/regime-split")
def backtest_regime_split(request:Request, horizon:int=20, force:bool=False):
    """STEP 27: pattern performance split by market regime (Bull/Bear/Range)
    and volatility regime. Auto-refreshed daily for the default horizon and
    served from cache instantly; non-default horizon or force=true recomputes
    live (admin-gated) — same expense profile as the other full-history scans.
    """
    if horizon != 20:
        _g=_require_admin(request)
        if _g: return _g
        return _run_regime_split_full(horizon)
    cached = _scan_cache.latest("regime_split")
    result, err = _serve_cached_and_refresh("regime_split", lambda: _run_regime_split_full(horizon),
                                             cached, _scan_cache.HEAVY_MAX_AGE_SECONDS, force,
                                             lambda: _require_admin(request))
    if err: return err
    result = dict(result); result["_background_refresh_running"] = _bg_job_running("regime_split")
    return result


def _run_discover_edges_full(horizon=20):
    cov = ohlc_coverage()
    universe = {r["symbol"]: ohlc_rows(r["symbol"], 5000) for r in cov if r["sessions"] >= 100}
    if not universe:
        return {"status": "unavailable", "reason": "No symbols with >=100 stored true-OHLC sessions."}
    result = _rbt.discover_psx_edges(universe, horizon=horizon)
    result["status"] = "ok"
    result["universe_symbols"] = len(universe)
    return result


@app.post("/backtest/discover-edges")
def backtest_discover_edges(request:Request, horizon:int=20, force:bool=False):
    """STEP 64: tests PSX-specific pattern combinations with the same
    forward-return machinery as every textbook pattern. Auto-refreshed daily
    for the default horizon and served from cache instantly; non-default
    horizon or force=true recomputes live (admin-gated).
    """
    if horizon != 20:
        _g=_require_admin(request)
        if _g: return _g
        return _run_discover_edges_full(horizon)
    cached = _scan_cache.latest("discover_edges")
    result, err = _serve_cached_and_refresh("discover_edges", lambda: _run_discover_edges_full(horizon),
                                             cached, _scan_cache.HEAVY_MAX_AGE_SECONDS, force,
                                             lambda: _require_admin(request))
    if err: return err
    result = dict(result); result["_background_refresh_running"] = _bg_job_running("discover_edges")
    return result


def _scan_one_symbol(r, rows, sec_all, regime):
    """One symbol's worth of _run_dss_scan's work — Wyckoff/candlestick/DSS
    analysis is fully independent per symbol (reads only the pre-computed,
    read-only `rows`/`sec_all`/`regime`), so this is safe to run concurrently
    across many symbols. Returns a result dict, or None to skip."""
    if r["sessions"] < 60:
        return None
    sym = r["symbol"]
    q = next((x for x in rows if x["symbol"] == sym), None)
    if not q:
        return None
    try:
        sector_row = next((s for s in sec_all if s["sector"] == q["sector"]), None)
        rs = relative_strength(sym)
        a = ohlc_rows(sym, 400)
        wy = {"symbol": sym, "sessions": len(a), **wyckoff_pro(a)}
        technical, _terr = v1_technical(sym, quote=q)
        candles = intelligence(sym)
        v = verdict(sym)
        dec = decision(sym, record=False)
        weekly = _weekly_structure(a)
        rs_multi = _rs_multi_for(sym, a, rows)
        wyckoff_events = {"accumulation": _wyckoff2.accumulation_events(a),
                          "distribution": _wyckoff2.distribution_events(a)}
        d = _dss.compute(symbol=sym, quote=q, regime=regime, sector_row=sector_row, rs=rs,
                          wy=wy, technical=technical, candles=candles, verdict=v, decision_=dec,
                          weekly=weekly, event_risk=None, rs_multi=rs_multi, ohlc_rows=a)
        sstate = _audit.signal_state(wyckoff_events, d["final_action"])
        return {"symbol": sym, "name": _names.name(sym, default=None), "price": q["price"],
                "pct": q["pct"], "sector": q["sector"], "phase": (wy or {}).get("phase"),
                "score": d["evidence_score"], "grade": d["confidence_grade"],
                "action": d["final_action"], "signal_stage": sstate.get("stage"),
                "signal_furthest": sstate.get("furthest"),
                "breakout": bool((technical or {}).get("breakout")),
                "rs_vs_index": (rs_multi or {}).get("weighted_avg_vs_index"),
                "rs_class": (rs_multi or {}).get("classification"),
                "entry": (d.get("entry_engine", {}).get("standard") or {}).get("price"),
                "stop": d.get("risk", {}).get("invalidation"),
                "target": d.get("risk", {}).get("target_1"),
                "rr": d.get("risk", {}).get("reward_risk")}
    except Exception as e:
        return None


DSS_SCAN_WORKERS = int(os.getenv("PSX_DSS_SCAN_WORKERS", "10"))


def _run_dss_scan():
    """The actual whole-market scan — extracted from the route so the
    background auto-refresh scheduler can call it directly (server-internal,
    no HTTP admin gate needed) as well as the on-demand endpoint.

    Runs each symbol's independent analysis across a small thread pool
    (PSX_DSS_SCAN_WORKERS, default 10) instead of one at a time — this used
    to be a strictly serial loop over every backfilled symbol (hundreds of
    symbols x full Wyckoff/candlestick/DSS pass each), taking 15-20+ minutes.
    Each symbol only reads the pre-computed, read-only rows/sec_all/regime
    and touches the DB (WAL mode, safe for concurrent readers) — there's no
    shared mutable state between symbols to race on.
    """
    rows = market_watch()
    _sync_sectors_from_psx(rows)
    cov = ohlc_coverage()
    regime = market_regime()
    sec_all = sector_rotation()
    results = []
    with _cf.ThreadPoolExecutor(max_workers=DSS_SCAN_WORKERS) as pool:
        futures = [pool.submit(_scan_one_symbol, r, rows, sec_all, regime) for r in cov]
        for fut in _cf.as_completed(futures):
            res = fut.result()
            if res is not None:
                results.append(res)

    def top(items, n=10):
        return sorted(items, key=lambda z: -(z.get("score") or 0))[:n]

    strongest_buy = top([x for x in results if x["action"] in ("STRONG BUY", "BUY")])
    # Mutually exclusive by phase prefix — "ACCUMULATION" is a substring of
    # "RE-ACCUMULATION" too, so this used to double-count the same names into
    # both buckets. True Wyckoff accumulation (spring-based) is its own
    # bucket; re-accumulation (a trend pausing into a tighter range) is
    # separate and genuinely distinct, not a near-duplicate list.
    accumulation = top([x for x in results if (x["phase"] or "").startswith("ACCUMULATION")])
    reaccumulation = top([x for x in results if (x["phase"] or "").startswith("RE-ACCUMULATION")])
    breakout_setups = top([x for x in results if x["breakout"] or x["signal_furthest"] == "SOS"])
    early_reversal = top([x for x in results if x["signal_furthest"] in ("SPRING", "TEST", "PS", "SC")])
    strongest_rs = sorted([x for x in results if x.get("rs_vs_index") is not None],
                          key=lambda z: -z["rs_vs_index"])[:10]
    distribution_warnings = top([x for x in results if
                                 (x["action"] in ("WATCH FOR SELL", "SELL / REDUCE") or
                                  x["signal_furthest"] in ("UT", "SOW")) and
                                 x["action"] not in ("BUY", "STRONG BUY", "ACCUMULATE")])
    markdown_avoid = sorted([x for x in results if x["action"] in ("STRONG SELL / AVOID", "AVOID")],
                            key=lambda z: (z.get("score") or 0))[:10]

    return {"status": "ok", "scanned": len(results), "market_regime": regime,
            "top_10_strongest_buy_setups": strongest_buy,
            "top_10_accumulation_setups": accumulation,
            "top_10_reaccumulation_setups": reaccumulation,
            "top_10_breakout_setups": breakout_setups,
            "top_10_early_reversal_watchlist": early_reversal,
            "top_10_strongest_relative_strength": strongest_rs,
            "top_10_distribution_warnings": distribution_warnings,
            "top_10_markdown_avoid": markdown_avoid,
            "note": "The 8 named market-wide lists (STEP 62), ranked from the same Decision Support "
                    "System each symbol's own page uses — not a separate, looser scoring pass. "
                    "signal_furthest is the furthest Wyckoff event reached (see /wyckoff-events)."}


def _refresh_all_backfilled_ohlc(max_new_per_run=600):
    """Two jobs in one, both idempotent (INSERT OR REPLACE on symbol+date):
    (1) appends the latest daily bar(s) for every symbol ALREADY backfilled —
    a short Yahoo range (5d), not a full 5y re-download — so daily_ohlc never
    goes stale. (2) attempts a full 5y backfill for every symbol in the
    live market_watch() universe NOT YET covered, so the DSS/backtest/scan
    universe grows toward the WHOLE market instead of staying pinned to
    whichever symbols were manually backfilled early on. Yahoo's PSX coverage
    is partial (confirmed by direct testing, not assumed) — symbols with no
    data there are recorded as `no_data`, never silently faked.
    """
    cov = ohlc_coverage()
    covered = {r["symbol"] for r in cov}
    refreshed, refresh_failed = 0, 0
    for r in cov:
        try:
            backfill_ohlc_from_yahoo(r["symbol"], range_="5d")
            refreshed += 1
        except Exception:
            refresh_failed += 1

    rows = market_watch()
    all_syms = sorted({x["symbol"] for x in rows} - covered)
    new_ok, new_missing = 0, 0
    for s in all_syms[:max_new_per_run]:
        try:
            r = backfill_ohlc_from_yahoo(s, range_="5y")
            if r["stored"] > 0:
                new_ok += 1
            else:
                new_missing += 1
        except Exception:
            new_missing += 1
    return {"refreshed_existing": refreshed, "refresh_failed": refresh_failed,
            "new_symbols_added": new_ok, "new_symbols_no_data": new_missing,
            "total_universe_after": len(ohlc_coverage())}


# ---- Background auto-refresh: keeps every expensive analysis warm without
# anyone having to click a button and wait, and without the HTTP admin gate
# getting in the way of routine use. Two cadences, because they genuinely
# differ (see scan_cache_engine.py's module docstring):
#   FAST  (SCAN_REFRESH_INTERVAL, default 30 min): dss_scan, alerts — partly
#         live-price/volume dependent.
#   HEAVY (HEAVY_REFRESH_INTERVAL, default 24h): daily-bar refresh, then
#         backtest/walkforward/regime-split/edge-discovery/failure-analysis —
#         pure historical-bar analysis that doesn't shift within a day.
# Both call the plain _run_*_full() functions directly (server-internal),
# bypassing the HTTP admin gate — that gate exists to stop OUTSIDE callers
# from triggering these in a loop, which is exactly what this scheduler does
# deliberately and on its own fixed cadence.
SCAN_REFRESH_INTERVAL = int(os.getenv("PSX_SCAN_REFRESH_INTERVAL", str(_scan_cache.DEFAULT_MAX_AGE_SECONDS)))
HEAVY_REFRESH_INTERVAL = int(os.getenv("PSX_HEAVY_REFRESH_INTERVAL", str(_scan_cache.HEAVY_MAX_AGE_SECONDS)))

# ---- Event-driven early refresh (plan point #20): don't just sit on a flat
# 30-min timer for dss_scan. Check cheaply every EVENT_CHECK_INTERVAL whether
# anything meaningful happened to a symbol already in the last scan's named
# lists, and if so recompute early instead of waiting out the rest of the
# interval. "Cheap" is the operative word — this reuses market_watch()'s
# already-cached quotes and the alerts cache's already-computed VOLUME_SURGE
# flags; it never re-runs Wyckoff/candlestick/technical analysis itself.
# Defaults chosen to match the volume_surge_x=2.0 convention already used
# elsewhere in this file, loosened slightly since this is a "worth checking
# early" gate, not the alert threshold itself.
EVENT_CHECK_INTERVAL = int(os.getenv("PSX_EVENT_CHECK_INTERVAL", "300"))       # 5 min
EVENT_PRICE_MOVE_PCT = float(os.getenv("PSX_EVENT_PRICE_PCT", "1.5"))          # vs price at last scan

# ---- Market-hours gating for the deep scan (dss_scan/alerts). Each full
# scan reads OHLC + peer history for every symbol -- on Turso that's real
# rows-read cost, not a free local-disk read. Running it on a flat 30-min
# timer around the clock, 7 days a week, is what actually exhausted a
# 500M-row/month free-tier quota in a matter of hours. PSX only trades
# Mon-Fri, roughly 09:30-15:30 PKT -- there is nothing to re-scan overnight
# or on weekends. DEEP_SCAN_SLOTS_PKT replaces the flat interval with three
# fixed daily targets: near market open, midday, and shortly after close.
PSX_TZ = ZoneInfo("Asia/Karachi")
DEEP_SCAN_SLOTS_PKT = [(9, 35), (13, 0), (20, 0)]


def _is_market_week(now_pkt=None):
    now_pkt = now_pkt or datetime.now(PSX_TZ)
    return now_pkt.weekday() < 5  # Mon=0 .. Fri=4; Sat=5, Sun=6 excluded


def _due_scan_slot(now_pkt=None):
    """Index of the DEEP_SCAN_SLOTS_PKT entry we've just entered (within one
    EVENT_CHECK_INTERVAL-sized window of its start), or None. Weekday only."""
    now_pkt = now_pkt or datetime.now(PSX_TZ)
    if not _is_market_week(now_pkt):
        return None
    for i, (h, m) in enumerate(DEEP_SCAN_SLOTS_PKT):
        slot_start = now_pkt.replace(hour=h, minute=m, second=0, microsecond=0)
        elapsed = (now_pkt - slot_start).total_seconds()
        if 0 <= elapsed < EVENT_CHECK_INTERVAL:
            return i
    return None
EVENT_TRIGGER_DIST_PCT = float(os.getenv("PSX_EVENT_TRIGGER_PCT", "1.0"))     # vs entry/stop/target
EVENT_RVOL_X = float(os.getenv("PSX_EVENT_RVOL_X", "1.5"))                     # from cached alerts


def _scan_event_triggered(cached_scan):
    """Cheap check: has anything material happened to a symbol already
    sitting in the last dss_scan's 8 named lists? Three conditions, any one
    of which is enough:
      1. Live price has moved >= EVENT_PRICE_MOVE_PCT since the price the
         scan was computed at.
      2. Live price is now within EVENT_TRIGGER_DIST_PCT of that symbol's
         stored entry/stop/target level (i.e. a trigger/stop/target is about
         to be hit or just was).
      3. The symbol shows up in the last cached alerts run with a
         VOLUME_SURGE >= EVENT_RVOL_X (already time-of-day-adjusted there).
    Returns (bool, reason_str_or_None). Never raises — caller falls back to
    the normal fixed-interval refresh on any failure here.
    """
    bucket_keys = [k for k in cached_scan if k.startswith("top_10_")]
    entries = {}
    for k in bucket_keys:
        for e in cached_scan.get(k) or []:
            sym = e.get("symbol")
            if sym and sym not in entries:
                entries[sym] = e
    if not entries:
        return False, None

    rows = market_watch()
    quote_lookup = {x["symbol"]: x for x in rows}

    for sym, e in entries.items():
        q = quote_lookup.get(sym)
        if not q:
            continue
        live_price = q.get("price")
        cached_price = e.get("price")
        if live_price and cached_price:
            pct_move = abs(live_price - cached_price) / cached_price * 100
            if pct_move >= EVENT_PRICE_MOVE_PCT:
                return True, (f"{sym}: price moved {pct_move:.1f}% since last scan "
                              f"({cached_price} -> {live_price})")
        if live_price:
            for label in ("entry", "stop", "target"):
                lvl = e.get(label)
                if lvl:
                    dist = abs(live_price - lvl) / lvl * 100
                    if dist <= EVENT_TRIGGER_DIST_PCT:
                        return True, f"{sym}: live price {live_price} is {dist:.1f}% from its {label} ({lvl})"

    cached_alerts = _scan_cache.latest("alerts")
    if cached_alerts:
        for flagged in cached_alerts.get("alerts") or []:
            sym = flagged.get("symbol")
            if sym not in entries:
                continue
            vol_x = flagged.get("vol_x_avg")
            if vol_x is not None and vol_x >= EVENT_RVOL_X:
                return True, f"{sym}: {vol_x:.1f}x time-adjusted RVOL in the last alerts cache"

    return False, None


async def _fast_refresh_loop():
    """Ticks every EVENT_CHECK_INTERVAL (5 min) to CHECK cheaply, but only
    actually recomputes dss_scan/alerts (the expensive Wyckoff/candlestick/
    technical/CMF passes) at one of DEEP_SCAN_SLOTS_PKT's three fixed daily
    times (weekdays only) OR when an event fires early DURING market hours.
    Replaces a flat 30-min-around-the-clock timer, which read enough rows on
    Turso to exhaust a 500M/month free-tier quota in hours — there's nothing
    new to scan overnight or on a weekend PSX isn't even open.
    """
    last_scan_slot = None    # (date, slot_index) already run today
    last_alerts_slot = None
    while True:
        now_pkt = datetime.now(PSX_TZ)
        slot = _due_scan_slot(now_pkt)
        today = now_pkt.date()
        try:
            cached = _scan_cache.latest_scan()
            due = (cached is None and slot is not None) or (slot is not None and last_scan_slot != (today, slot))
            reason = None
            # Event-early-trigger stays on, but only during the trading week —
            # off-hours/weekend price data isn't moving in any way that
            # justifies the extra scan cost.
            if not due and cached and _is_market_week(now_pkt):
                try:
                    triggered, reason = await asyncio.to_thread(_scan_event_triggered, cached)
                    due = due or triggered
                except Exception as e:
                    print(f"[scan_cache] event check failed (falling back to fixed slots): {type(e).__name__}: {e}")
            if due:
                # _run_guarded shares its lock with the HTTP /dss-scan?force=true
                # path — if an admin's manual force-run is already in flight this
                # tick is skipped rather than double-computing the same scan.
                ran, result = await asyncio.to_thread(_run_guarded, "dss_scan", _run_dss_scan)
                if ran and result:
                    if slot is not None:
                        last_scan_slot = (today, slot)
                    why = f" (event-triggered: {reason})" if reason else ""
                    print(f"[scan_cache] dss_scan refreshed: {result.get('scanned')} symbols{why}")
                elif not ran:
                    print("[scan_cache] dss_scan refresh skipped — a force-run was already in flight")
        except Exception as e:
            print(f"[scan_cache] dss_scan refresh failed: {type(e).__name__}: {e}")
        if slot is not None and last_alerts_slot != (today, slot):
            try:
                ran, result = await asyncio.to_thread(
                    _run_guarded, "alerts", _run_alerts_full, None, lambda r: isinstance(r, dict))
                if ran and result:
                    last_alerts_slot = (today, slot)
                    print(f"[scan_cache] alerts refreshed: {result.get('flagged')} flagged")
                elif not ran:
                    print("[scan_cache] alerts refresh skipped — a force-run was already in flight")
            except Exception as e:
                print(f"[scan_cache] alerts refresh failed: {type(e).__name__}: {e}")
        await asyncio.sleep(EVENT_CHECK_INTERVAL)


async def _heavy_refresh_loop():
    while True:
        try:
            ohlc_summary = await asyncio.to_thread(_refresh_all_backfilled_ohlc)
            print(f"[scan_cache] daily OHLC refresh: {ohlc_summary}")
        except Exception as e:
            print(f"[scan_cache] OHLC refresh failed: {type(e).__name__}: {e}")

        for name, fn in (("backtest_run", _run_backtest_full),
                          ("walkforward", _run_walkforward_full),
                          ("regime_split", _run_regime_split_full),
                          ("discover_edges", _run_discover_edges_full),
                          ("failure_analysis", _run_failure_analysis_full),
                          # Grades stored /decision runs against real subsequent
                          # price paths — the learning loop was previously
                          # manual-only (POST /grade-outcomes), so confidence
                          # adjustment and indicator-accuracy tracking stayed
                          # permanently "no history yet" unless an operator
                          # remembered to trigger it. Same defaults as the
                          # manual endpoint (min_age_days=7, limit=500).
                          ("grade_outcomes", _run_grade_outcomes_full)):
            try:
                # Shares its lock with the matching HTTP force=true endpoint
                # (backtest_run/walkforward/regime_split/discover_edges) — a
                # manual force-run in flight makes this tick skip rather than
                # double-computing the same multi-minute analysis.
                pred = (lambda r: isinstance(r, dict)) if name == "failure_analysis" else None
                kwargs = {} if pred is None else {"should_save": pred}
                ran, result = await asyncio.to_thread(lambda: _run_guarded(name, fn, **kwargs))
                if ran and result:
                    print(f"[scan_cache] {name} refreshed")
                elif not ran:
                    print(f"[scan_cache] {name} refresh skipped — a force-run was already in flight")
            except Exception as e:
                print(f"[scan_cache] {name} refresh failed: {type(e).__name__}: {e}")
        await asyncio.sleep(HEAVY_REFRESH_INTERVAL)


@app.on_event("startup")
async def _start_background_refresh_loops():
    if os.getenv("PSX_DISABLE_SCAN_AUTOREFRESH"):
        print("[scan_cache] PSX_DISABLE_SCAN_AUTOREFRESH is set — background refresh loops "
              "(dss_scan, alerts, backtest family, OHLC refresh) will NOT start. All cached "
              "analysis will go stale until this is unset and the server restarts.")
        return
    asyncio.create_task(_fast_refresh_loop())
    asyncio.create_task(_heavy_refresh_loop())


import threading as _threading

_BG_JOBS = {}  # cache_key -> {"running": bool, "lock": threading.Lock}
_BG_JOBS_LOCK = _threading.Lock()  # guards creation of each per-key Lock


def _bg_job_running(cache_key):
    return _BG_JOBS.get(cache_key, {}).get("running", False)


def _bg_job(cache_key):
    with _BG_JOBS_LOCK:
        return _BG_JOBS.setdefault(cache_key, {"running": False, "lock": _threading.Lock()})


def _run_guarded(cache_key, compute_fn, save_key=None,
                  should_save=lambda r: isinstance(r, dict) and r.get("status") == "ok"):
    """THE single execution gate for every heavy whole-universe computation
    (dss_scan, alerts, scan_brain, backtest_run, walkforward, regime_split,
    discover_edges). Both the background scheduler (_fast_refresh_loop /
    _heavy_refresh_loop, on their normal cadence) and HTTP force-run endpoints
    call through this same function for the same cache_key, sharing one
    running-flag/lock per key — so a scheduled refresh and a manual "force
    re-run" click can never compute the same expensive analysis twice at once
    (previously the scheduler bypassed the HTTP endpoints' lock entirely and
    called _run_dss_scan()/_run_alerts_full()/etc. directly).
    Runs synchronously in the calling thread; saves on success. Returns
    (ran: bool, result_or_None) — ran=False means a job for this key was
    already in flight and this call was skipped rather than double-computing.
    """
    save_key = save_key or cache_key
    job = _bg_job(cache_key)
    with job["lock"]:
        if job["running"]:
            return False, None
        job["running"] = True
    try:
        result = compute_fn()
        if should_save(result):
            _scan_cache.save(save_key, result)
        return True, result
    except Exception as e:
        print(f"[{cache_key}] guarded job failed: {type(e).__name__}: {e}")
        return True, None
    finally:
        job["running"] = False


def _start_bg_job(cache_key, compute_fn, save_key=None):
    """Kick off _run_guarded(cache_key, compute_fn, save_key) in a background
    thread so an HTTP request returns immediately instead of blocking for the
    minutes a full-universe scan can take. Returns True if a new job was
    started, False if one for this cache_key was already running (in which
    case the caller should just poll /cache-status/<cache_key>).
    """
    if _bg_job_running(cache_key):
        return False
    _threading.Thread(target=_run_guarded, args=(cache_key, compute_fn, save_key), daemon=True).start()
    return True


def _serve_cached_and_refresh(cache_key, compute_fn, cached, max_age_seconds, force, admin_check):
    """Stale-while-revalidate for every whole-universe scan/backtest endpoint.

    ALWAYS serves the last cached result immediately if one exists, even when
    it's stale — a full-universe scan can take 15-20+ minutes, well past the
    30-min cache window, so a naive "recompute when stale" endpoint got stuck
    perpetually returning a bare {"status":"running"} placeholder instead of
    real data on ordinary page loads (the cache almost never had a chance to
    look "fresh" by the time the next request arrived). A background refresh
    is still kicked off when stale or forced — just never at the cost of
    blocking or hiding data the caller could otherwise see right now.
    `admin_check` (a zero-arg callable returning an error dict or None) is
    enforced ONLY for an explicit force=true — an organic staleness-triggered
    refresh needs no token, exactly like the scheduler's own background
    refreshes never go through admin gating either.
    Returns (cached_dict_or_None, error_dict_or_None) — the caller returns
    `error` if present, otherwise uses `cached` (which is None only when this
    cache_key has genuinely never completed a run).
    """
    stale = cached is None or cached["_cache_age_seconds"] >= max_age_seconds
    if force:
        blocked = admin_check()
        if blocked:
            return (cached, None) if cached is not None else (None, blocked)
        _start_bg_job(cache_key, compute_fn)
    elif stale:
        _start_bg_job(cache_key, compute_fn)
    if cached is not None:
        return cached, None
    return None, {"status": "running",
                   "reason": f"No cached result yet for '{cache_key}' — first computation is "
                             "running in the background. This can take several minutes for a "
                             "whole-universe scan; try again shortly or poll /cache-status/"
                             f"{cache_key}."}


@app.get("/dss-scan")
def dss_scan(request:Request, force:bool=False, max_age_seconds:int=_scan_cache.DEFAULT_MAX_AGE_SECONDS):
    """STEP 54-55/62: the 8 named market-wide lists — but now CACHED, because
    the underlying Wyckoff/candlestick/evidence-score analysis is computed
    from daily bars and genuinely does not change within a trading day.
    Always serves the last cached run instantly (with live price/% patched on
    top from market_watch's own 60s-TTL cache) — a full-universe scan
    genuinely takes 15-20+ minutes, far longer than max_age_seconds, so this
    NEVER blocks a normal page load on "nothing to show yet": stale cache or
    force=true just kicks off a background refresh alongside serving whatever
    is already cached (see _serve_cached_and_refresh). Only a symbol that has
    never completed a single scan returns a bare "running" placeholder.
    """
    cached = _scan_cache.latest_scan()
    result, err = _serve_cached_and_refresh("dss_scan", _run_dss_scan, cached,
                                             max_age_seconds, force, lambda: _require_admin(request))
    if err: return err
    rows = market_watch()
    quote_lookup = {x["symbol"]: x for x in rows}
    out = _scan_cache.refresh_live_overlay(dict(result), quote_lookup)
    out["_background_refresh_running"] = _bg_job_running("dss_scan")
    return out


@app.get("/dss-scan/status")
def dss_scan_status():
    """Cache age + last-run time, so the UI can show 'last full scan: 12 min
    ago, prices live' instead of pretending every load is a fresh analysis."""
    cached = _scan_cache.latest_scan()
    if not cached:
        return {"status": "never_run", "reason": "No market scan has been run yet.",
                "job_running": _bg_job_running("dss_scan")}
    return {"status": "ok", "run_at": cached.get("_cache_run_at"),
            "age_seconds": cached.get("_cache_age_seconds"),
            "max_age_seconds": _scan_cache.DEFAULT_MAX_AGE_SECONDS,
            "scanned": cached.get("scanned"),
            "job_running": _bg_job_running("dss_scan")}


@app.get("/cache-status/{cache_key}")
def cache_status(cache_key:str):
    """Freshness of any background-refreshed analysis (alerts, backtest_run,
    walkforward, regime_split, discover_edges, failure_analysis) without
    pulling the whole cached payload — for the UI's 'last refreshed N ago' line."""
    s = _scan_cache.status(cache_key)
    s["max_age_seconds"] = (_scan_cache.DEFAULT_MAX_AGE_SECONDS if cache_key in ("dss_scan", "alerts")
                            else _scan_cache.HEAVY_MAX_AGE_SECONDS)
    s["job_running"] = _bg_job_running(cache_key)
    return s


def _run_brain_scan(min_volume, limit, top):
    if _psx_brain is None:
        return {"status":"unavailable","reason":"psx_brain not importable on this deployment"}
    rows=market_watch()
    syms=[x["symbol"] for x in sorted(rows,key=lambda z:-z["volume"])
          if x["volume"]>=min_volume][:limit]
    results, skipped = [], []
    for s in syms:
        df, source_or_err = _brain_frame(s)
        if df is None:
            skipped.append({"symbol":s,"reason":source_or_err}); continue
        try:
            r=_psx_brain.analyse(s, df); r["history_source"]=source_or_err
            results.append(r)
        except Exception as e:
            skipped.append({"symbol":s,"reason":f"{type(e).__name__}: {e}"})
    ranked=_psx_brain.compare(results)
    return {"status":"ok","requested":len(syms),"scored":len(results),"skipped":skipped,
            "ranked":ranked["ranked"][:top],"commentary":ranked["commentary"]}


@app.get("/scan")
def scan(request:Request, min_volume:int=MIN_VOLUME, limit:int=40, top:int=20, force:bool=False):
    """Whole-book scan: psx_brain.analyse() over the most liquid names, ranked.

    Expensive — one OHLCV fetch + full indicator pass per symbol — so for the
    default parameters this always serves the last cached result instantly
    (even if stale) and refreshes in the background rather than ever leaving
    a normal page load with nothing to show (see _serve_cached_and_refresh);
    non-default parameters are rare, manual, single-operator calls and just
    run synchronously. Symbols without enough real OHLCV history are reported
    in `skipped`, never silently dropped from the count.
    """
    is_default = (min_volume, limit, top) == (MIN_VOLUME, 40, 20)
    if not is_default:
        _g=_require_admin(request)
        if _g: return _g
        return _run_brain_scan(min_volume, limit, top)

    cached = _scan_cache.latest("scan_brain")
    result, err = _serve_cached_and_refresh("scan_brain", lambda: _run_brain_scan(min_volume, limit, top),
                                             cached, _scan_cache.DEFAULT_MAX_AGE_SECONDS, force,
                                             lambda: _require_admin(request))
    if err: return err
    result = dict(result)
    result["_background_refresh_running"] = _bg_job_running("scan_brain")
    return result


PSX_TZ=ZoneInfo("Asia/Karachi")
PSX_SESSION_OPEN=dtime(9,15)
PSX_SESSION_CLOSE=dtime(15,30)


def _psx_session_elapsed_fraction(now=None):
    """Fraction of today's PSX trading session that has elapsed, clamped to
    [0.05, 1.0]. `q["volume"]` from market_watch() is the LIVE, still-
    accumulating volume for TODAY while it's a trading day — comparing that
    directly to a 20-day average of full CLOSED days (as this used to do)
    understates every ratio in the morning and overstates it near the close.
    A stock trading completely normally at 10:30 AM would show ~0.3-0.4x and
    never trip VOLUME_SURGE. This scales the average down to "expected volume
    by this point in the session" instead, assuming a roughly even intraday
    pace — a coarse but honest correction, not a claim of a measured intraday
    volume curve (which would need historical intraday snapshots we don't
    store). Before/after session hours (or on non-trading days) this returns
    1.0, i.e. no adjustment, since q["volume"] is then a finished day's total.
    """
    now=now or datetime.now(PSX_TZ)
    t=now.time()
    if t<=PSX_SESSION_OPEN or t>=PSX_SESSION_CLOSE:
        return 1.0
    open_s=PSX_SESSION_OPEN.hour*3600+PSX_SESSION_OPEN.minute*60
    close_s=PSX_SESSION_CLOSE.hour*3600+PSX_SESSION_CLOSE.minute*60
    now_s=t.hour*3600+t.minute*60+t.second
    return max(0.05, min(1.0, (now_s-open_s)/(close_s-open_s)))


def _run_alerts_full(min_volume=MIN_VOLUME, limit=60, volume_surge_x=2.0, cmf_threshold=0.05):
    rows=market_watch()
    syms=[x for x in sorted(rows,key=lambda z:-z["volume"])
          if x["volume"]>=min_volume][:limit]
    session_frac=_psx_session_elapsed_fraction()
    flagged, skipped = [], 0
    for q in syms:
        sym=q["symbol"]
        tech,terr=v1_technical(sym, quote=q)
        if not tech:
            skipped+=1; continue
        avgv=tech.get("avg_volume")
        expected_by_now=avgv*session_frac if avgv else None
        vol_x=round(q["volume"]/expected_by_now,2) if expected_by_now else None
        cmf=tech.get("cmf")
        obv_up=tech.get("obv_up")
        found=[]
        if vol_x is not None and vol_x>=volume_surge_x:
            session_note=f" ({session_frac*100:.0f}% of session elapsed)" if session_frac<1.0 else ""
            found.append({"type":"VOLUME_SURGE",
                          "detail":f"{vol_x:.1f}x the time-adjusted 20-day average volume{session_note}"})
        if cmf is not None:
            if cmf>cmf_threshold and obv_up and q["pct"]>0:
                found.append({"type":"ACCUMULATION",
                              "detail":f"CMF {cmf:+.2f}, OBV rising, price up {q['pct']:+.1f}%"})
            elif cmf<-cmf_threshold and obv_up is False and q["pct"]<0:
                found.append({"type":"DISTRIBUTION",
                              "detail":f"CMF {cmf:+.2f}, OBV falling, price down {q['pct']:+.1f}%"})
        if found:
            flagged.append({"symbol":sym,"name":_names.name(sym,default=None),
                            "price":q["price"],"pct":q["pct"],"volume":q["volume"],
                            "vol_x_avg":vol_x,"cmf":cmf,"alerts":found})
    flagged.sort(key=lambda x:-(x.get("vol_x_avg") or 0))
    return {"status":"ok","scanned":len(syms),"skipped_no_data":skipped,"flagged":len(flagged),
            "alerts":flagged,
            "note":"~5min delayed via PSX's portal, not tick-level. "
                   "Accumulation/distribution are indicator-derived (CMF+OBV) "
                   "proxies for buying/selling pressure, not confirmed "
                   "institutional trades — PSX does not publish real-time "
                   "order-level data. VOLUME_SURGE needs backfilled true "
                   "OHLC for the 20-day average; symbols without it are in "
                   "skipped_no_data, not silently scored as normal."}


@app.get("/alerts")
def alerts(request:Request, min_volume:int=MIN_VOLUME, limit:int=60,
           volume_surge_x:float=2.0, cmf_threshold:float=0.05, force:bool=False):
    """Volume-surge and accumulation/distribution alerts — see
    _run_alerts_full's docstring history for the VOLUME_SURGE/ACCUMULATION/
    DISTRIBUTION definitions. Auto-refreshed every SCAN_REFRESH_INTERVAL
    (default 30 min, same cadence as /dss-scan — this depends on today's
    live volume, not just daily bars) and served from cache instantly for
    the default parameters; non-default parameters or force=true recompute
    live (admin-gated).
    """
    is_default = (min_volume, limit, volume_surge_x, cmf_threshold) == (MIN_VOLUME, 60, 2.0, 0.05)
    if not is_default:
        # Deliberate override with non-default params — admin-gated like every
        # other force/custom-parameter path.
        _g=_require_admin(request)
        if _g: return _g
        return _run_alerts_full(min_volume, limit, volume_surge_x, cmf_threshold)
    cached = _scan_cache.latest("alerts")
    if force:
        _g=_require_admin(request)
        if _g:
            return cached if cached is not None else _g
    # Organic staleness (no force) never needs the admin gate — same rule as
    # every other whole-universe endpoint (_serve_cached_and_refresh) and the
    # scheduler's own background refreshes. Alerts is cheap enough (<=60
    # symbols) to just run inline here rather than backgrounding it, sharing
    # its lock with the scheduler so the two can never double-compute.
    stale = cached is None or cached["_cache_age_seconds"] >= _scan_cache.DEFAULT_MAX_AGE_SECONDS
    if force or stale:
        ran, result = _run_guarded("alerts", lambda: _run_alerts_full(min_volume, limit, volume_surge_x, cmf_threshold))
        if ran and result:
            return result  # _run_guarded already saved this to the "alerts" cache
        # Not ran (scheduler already had the lock) or it failed — fall through
        # to serving whatever's cached rather than surfacing a dead end.
    if cached is not None:
        return cached
    return {"status": "running", "reason": "No alerts computed yet — first run is in progress in the background."}


@app.get("/live-market")
def live_market():
    """Live index snapshot from psxterminal.com (KSE100/KMI30/KSE30/ALLSHR).

    psxterminal.com's public API narrowed since this was first wired up —
    confirmed by direct probing, not assumed: per-stock data now 403s
    ("Access denied", deliberately gated — not something to work around) and
    the old breadth/sector endpoints 404 (gone). Index-level daily OHLCV is
    still genuinely public, so that's what this returns; /market stays the
    primary, official, whole-market source this always supplemented rather
    than replaced. See psx_live.py's module docstring for the full picture."""
    if _psx_live is None:
        return {"status":"unavailable","reason":"psx_live not importable on this deployment"}
    snap=_psx_live.index_snapshot()
    return {"status":"ok" if snap else "unavailable","indices":snap,
            "index_report":_psx_live.index_report(snap),
            "unavailable_upstream":{
                "per_stock_snapshot":"gated (403) on psxterminal.com's current API",
                "breadth":"endpoint removed (404) on psxterminal.com's current API",
                "sectors":"endpoint removed (404) on psxterminal.com's current API"},
            "source":"psxterminal.com (unofficial, supplementary, index-level only)"}


@app.get("/live-tape")
def live_tape(min_value:float=100_000):
    """Institutional-footprint read of the live tape: volume surges, block
    trades, accumulation/distribution. UNAVAILABLE on the current
    psxterminal.com API: this needs a per-stock live snapshot, and that
    endpoint now returns 403 (deliberately gated, confirmed by direct
    probing — see psx_live.py). Left in place in case it's ever un-gated;
    reports why rather than a bare failure."""
    if _psx_live is None:
        return {"status":"unavailable","reason":"psx_live not importable on this deployment"}
    alerts=_psx_live.tape_signals(min_value=min_value)
    if alerts is None:
        return {"status":"unavailable",
                "reason":_psx_live.last_error("/api/market-data?market=REG")
                         or "psxterminal.com per-stock snapshot unavailable",
                "note":"Per-stock live data is gated on the current API. "
                       "/live-market still returns real index-level data."}
    return {"status":"ok","alerts":alerts,"summary":_psx_live.tape_summary(alerts)}


# ============================================================================
# V4.11 — psxwatch bridge (fundamentals / forensics-adjacent / news / exposure)
# ============================================================================

@app.get("/fundamentals-deep/{symbol}")
def fundamentals_deep(symbol:str):
    """psxwatch's 53-metric deterministic ratio engine — the full-depth
    fundamentals /fundamentals/{symbol} only scrapes a summary of."""
    if _pw is None:
        return {"symbol":symbol.upper(),"status":"unavailable","reason":"psxwatch_bridge not importable"}
    return _pw.fundamentals_deep(symbol)


@app.get("/news-impact/{symbol}")
def news_impact(symbol:str, limit:int=20):
    """psxwatch's evidence-quoted news impact scores (direction/magnitude/
    mechanism/priced_in) — a deeper read than /news-verdict's keyword pass."""
    if _pw is None:
        return {"symbol":symbol.upper(),"status":"unavailable","reason":"psxwatch_bridge not importable"}
    return _pw.news_impact(symbol, limit=limit)


@app.get("/exposure/{symbol}")
def exposure_priors(symbol:str):
    """psxwatch's driver-exposure matrix for one company — every row a PRIOR."""
    if _pw is None:
        return {"symbol":symbol.upper(),"status":"unavailable","reason":"psxwatch_bridge not importable"}
    return _pw.exposure(symbol)


@app.get("/exposure-evidence/{symbol}")
def exposure_evidence_endpoint(symbol:str):
    """psxwatch's grounded verification of exposure priors against real annual
    reports (verify.py) — confirmed / revised / unverifiable, with page cites."""
    if _pw is None:
        return {"symbol":symbol.upper(),"status":"unavailable","reason":"psxwatch_bridge not importable"}
    return _pw.exposure_evidence(symbol)
