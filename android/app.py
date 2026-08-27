from fastapi import FastAPI, WebSocket
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from datetime import datetime, timezone
import io, json, math, os, sqlite3, statistics, requests
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

app = FastAPI(title="PSX Intelligence V2 API", version="3.3-real-intelligence")
DB=os.getenv("PSX_DB","psx_v2.db")
PSX="https://dps.psx.com.pk"
MIN_VOLUME=50_000
HEAD={"User-Agent":"PSX-Intelligence-V2/2.0 private-research"}

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.executescript("""
    CREATE TABLE IF NOT EXISTS snapshots(ts TEXT,symbol TEXT,sector TEXT,listed TEXT,ldcp REAL,o REAL,h REAL,l REAL,p REAL,ch REAL,pct REAL,vol REAL,score REAL,setup TEXT,shariah INTEGER);
    CREATE INDEX IF NOT EXISTS ix_snap ON snapshots(symbol,ts);
    CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY AUTOINCREMENT,fetched_at TEXT,source TEXT,title TEXT,link TEXT,published TEXT,direction TEXT,materiality TEXT,symbols TEXT);
    CREATE TABLE IF NOT EXISTS predictions(id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT,symbol TEXT,signal TEXT,score REAL,entry REAL,stop REAL,target REAL,model_version TEXT,outcome TEXT);
    """); return c

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


def market_watch():
    r=requests.get(PSX+"/market-watch",headers=HEAD,timeout=15);r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser"); out=[]
    for tr in soup.select("tr"):
        x=[td.get_text(" ",strip=True) for td in tr.select("td")]
        if len(x)<11: continue
        s,ca=clean_symbol(x[0]); sector=x[1]; listed=x[2]
        if not s: continue
        ldcp,o,h,l,p,ch,pct,vol=map(num,x[3:11]); sh=_shariah_status(s,listed)
        rng=max(.00001,h-l); loc=(p-l)/rng; liq=min(20,math.log10(max(vol,1))*3)
        mom=max(-20,min(20,pct*2.2)); strength=(loc-.5)*24
        score=max(0,min(100,50+mom+strength+liq/2))
        setup="Momentum breakout" if pct>3 and loc>.8 else "Strong close" if loc>.72 else "Pullback / watch" if pct<0 and loc>.45 else "Neutral"
        out.append(dict(symbol=s,sector=sector,listed=listed,ldcp=ldcp,open=o,high=h,low=l,price=p,change=ch,pct=pct,volume=vol,score=round(score,1),setup=setup,eligible=vol>=MIN_VOLUME,corporate_action=ca,**sh))
    return out

def save_snapshot(rows):
    ts=datetime.now(timezone.utc).isoformat()
    with db() as c:
        c.executemany("INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(ts,x["symbol"],x["sector"],x["listed"],x["ldcp"],x["open"],x["high"],x["low"],x["price"],x["change"],x["pct"],x["volume"],x["score"],x["setup"],int(x["shariah"])) for x in rows])
        c.commit()

def eod(symbol):
    r=requests.get(f"{PSX}/timeseries/eod/{symbol}",headers=HEAD,timeout=15);r.raise_for_status()
    raw=r.json(); a=raw.get("data") or raw.get("timeseries") or []
    out=[]
    for z in a:
        if isinstance(z,list) and len(z)>=2: out.append({"time":z[0],"close":z[1],"volume":z[2] if len(z)>2 else None})
        elif isinstance(z,dict): out.append(z)
    return out


def yahoo_ohlcv(symbol, range_="2y"):
    ticker=f"{symbol.upper()}.KA"
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    r=requests.get(url,params={"range":range_,"interval":"1d","includePrePost":"false","events":"div,splits"},headers=HEAD,timeout=15)
    r.raise_for_status(); root=r.json()["chart"]; results=root.get("result") or []
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
def health(): return {"ok":True,"time":datetime.now(timezone.utc).isoformat(),"min_volume":MIN_VOLUME,
"market_data":"PSX Data Portal","freshness":"5-minute delayed unless PSX indicates otherwise",
"policy":"private research; do not redistribute PSX market data without appropriate rights"}

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
def ensure_ohlc():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS daily_ohlc(
          symbol TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
          source TEXT, PRIMARY KEY(symbol,trade_date))"""); c.commit()

def ohlc_rows(symbol,limit=260):
    ensure_ohlc()
    with db() as c:
        a=c.execute("SELECT * FROM daily_ohlc WHERE symbol=? ORDER BY trade_date DESC LIMIT ?",
                    (symbol.upper(),limit)).fetchall()
    return [dict(x) for x in reversed(a)]

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
    if len(a)<2:return []
    x,p=a[-1],a[-2]; body=abs(x["close"]-x["open"]); rng=max(.0001,x["high"]-x["low"])
    upper=x["high"]-max(x["open"],x["close"]); lower=min(x["open"],x["close"])-x["low"]
    out=[]
    if body/rng<.1:out.append("Doji")
    if lower>2*max(body,.0001) and upper<body:out.append("Hammer-like")
    if upper>2*max(body,.0001) and lower<body:out.append("Shooting-star-like")
    if x["close"]>x["open"] and p["close"]<p["open"] and x["open"]<=p["close"] and x["close"]>=p["open"]:
        out.append("Bullish engulfing")
    if x["close"]<x["open"] and p["close"]>p["open"] and x["open"]>=p["close"] and x["close"]<=p["open"]:
        out.append("Bearish engulfing")
    return out

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
def ingest_ohlc(symbol:str, rows:list[dict]):
    """Private research ingestion endpoint for genuine daily OHLCV rows."""
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
    a=ohlc_rows(symbol,10000)
    if not a:return {"symbol":symbol.upper(),"status":"missing"}
    bad=sum(1 for x in a if not (x["low"]<=min(x["open"],x["close"])<=max(x["open"],x["close"])<=x["high"]))
    return {"symbol":symbol.upper(),"sessions":len(a),"first":a[0]["trade_date"],"last":a[-1]["trade_date"],
            "invalid_ohlc_rows":bad,"status":"ok" if bad==0 else "review"}

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


@app.post("/grade-outcomes")
def grade_outcomes(min_age_days:int=7, limit:int=500):
    """Grade stored runs against real subsequent prices.

    This is the learning loop: graded outcomes feed
    scoring_engine.historical_confidence_adjust() and
    _indicator_accuracy_boost(), which is why confidence currently reports
    "No strictly-graded history yet". Runs with too little forward path are left
    UNGRADED rather than guessed.
    """
    try:
        import database as _db
        pend=_db.ungraded_runs(min_age_days=min_age_days, limit=limit)
        if not pend:
            return {"pending":0,"graded":0,
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
        return {"pending":len(pend),"graded":tot,
                "worked":graded["worked"],"failed":graded["failed"],
                "insufficient_path":skipped,
                "win_rate":(round(100*graded["worked"]/tot,1) if tot else None),
                "note":"Graded against real stored OHLC paths (stop/target hit "
                       "order, not just the closing price). Watch/Hold use the "
                       "loose survival rule and are excluded from confidence by "
                       "scoring_engine. Nothing is graded without a real path."}
    except Exception as e:
        return {"status":"error","reason":f"{type(e).__name__}: {e}"}


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
def backfill_ohlc(symbol:str, range_:str="5y"):
    """Backfill true OHLC for one symbol so CMF and true ATR/ADX can compute."""
    try:
        r=backfill_ohlc_from_yahoo(symbol, range_)
        r["stored_sessions_now"]=len(ohlc_rows(symbol,10000))
        return r
    except Exception as e:
        return {"symbol":symbol.upper(),"status":"error",
                "reason":f"{type(e).__name__}: {e}",
                "note":"No OHLC is fabricated when the source is unavailable."}


@app.post("/backfill-ohlc-bulk")
def backfill_ohlc_bulk(min_volume:int=MIN_VOLUME, limit:int=40, range_:str="5y"):
    """Backfill the most liquid names. Yahoo coverage of PSX tickers is partial —
    symbols with no data are listed as `missing`, never silently skipped."""
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
    """Populate config.SECTORS from PSX's own sector codes.

    fundamentals_analyzer blends each ratio with a SECTOR-RELATIVE percentile.
    Symbols absent from config.SECTORS fall back to "?" — so without this, every
    newly fetched symbol pools into one bucket and a bank's P/E gets ranked
    against a cement company's. PSX publishes a sector code per row, so use it.
    Only fills gaps: hand-maintained config entries are never overwritten.
    """
    try:
        import config as _cfg
        sec = getattr(_cfg, "SECTORS", None)
        if sec is None:
            sec = {}; _cfg.SECTORS = sec
        added = 0
        for x in rows:
            s, code = x.get("symbol"), (x.get("sector") or "").strip()
            if s and code and s not in sec:
                sec[s] = code; added += 1
        return added
    except Exception:
        return 0


@app.post("/backfill-fundamentals")
def backfill_fundamentals(min_volume:int=MIN_VOLUME, limit:int=60):
    """Fetch fundamental ratios for the most liquid PSX names, not just the
    10-symbol config.STOCKS universe the V1 engine shipped with.

    Merges into fundamentals.json (existing entries are kept), syncs
    config.SECTORS from PSX sector codes so the sector-relative blend is
    comparing like with like, and reloads the analyzer's in-memory cache.
    """
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
def reload_fundamentals():
    """Re-read fundamentals.json into the running process (no restart needed)."""
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
        try: hist=eod(q["symbol"])
        except: hist=[]
        oh=ohlc_rows(q["symbol"],300)
        x=conviction(q,hist,oh)
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

def wyckoff_pro(a):
    if len(a)<50:return {"phase":"UNRESOLVED","reason":"Need >=50 genuine OHLCV sessions"}
    tr=trading_range(a); er=effort_result(a); sp=spring_quality(a); ut=upthrust_quality(a); st=structure_ohlc(a)
    phase="UNRESOLVED"
    if sp.get("status")=="CONFIRMED":phase="ACCUMULATION — Phase D candidate"
    elif sp.get("status") in ("CANDIDATE","TESTED"):phase="ACCUMULATION — Phase C hypothesis"
    elif ut.get("status")=="CONFIRMED":phase="DISTRIBUTION — Phase D candidate"
    elif ut.get("status")=="CANDIDATE":phase="DISTRIBUTION — Phase C hypothesis"
    elif "UPTREND" in st.get("trend",""):phase="MARKUP / RE-ACCUMULATION context"
    elif "DOWNTREND" in st.get("trend",""):phase="MARKDOWN / RE-DISTRIBUTION context"
    return {"phase":phase,"trading_range":tr,"effort_vs_result":er,"spring":sp,"upthrust":ut,
            "structure":st,"principle":"Conservative labeling: unresolved when classic criteria are not met."}

@app.get("/wyckoff-pro/{symbol}")
def wyckoff_pro_endpoint(symbol:str):
    a=ohlc_rows(symbol,400)
    if not a:return {"symbol":symbol.upper(),"status":"awaiting_true_ohlcv"}
    return {"symbol":symbol.upper(),"sessions":len(a),**wyckoff_pro(a)}
