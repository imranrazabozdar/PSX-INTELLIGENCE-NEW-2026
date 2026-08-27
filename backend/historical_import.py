"""
PSX Intelligence V2.5 historical OHLCV importer.

Use with daily historical/market-summary CSV files that you are authorized to use.
This deliberately does not bypass the PSX website or automate prohibited scraping.
"""
import argparse, sqlite3, pandas as pd
from pathlib import Path

ALIASES={
 "symbol":["SYMBOL","SCRIP","TICKER"],
 "date":["DATE","TRADE_DATE","TRADE DATE"],
 "open":["OPEN","OPEN PRICE"],
 "high":["HIGH","HIGH PRICE"],
 "low":["LOW","LOW PRICE"],
 "close":["CLOSE","CLOSE PRICE","PRICE"],
 "volume":["VOLUME","TURNOVER","SHARES"]
}
def col(df,n):
    up={str(c).strip().upper():c for c in df.columns}
    for a in ALIASES[n]:
        if a in up:return up[a]
    return None

def import_file(path,db_path="psx_v2.db",source="Authorized PSX historical file"):
    df=pd.read_csv(path)
    cols={k:col(df,k) for k in ALIASES}
    need=["symbol","date","open","high","low","close"]
    missing=[k for k in need if cols[k] is None]
    if missing: raise ValueError("Missing columns: "+", ".join(missing))
    c=sqlite3.connect(db_path)
    c.execute("""CREATE TABLE IF NOT EXISTS daily_ohlc(
      symbol TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
      source TEXT, PRIMARY KEY(symbol,trade_date))""")
    n=0
    for _,r in df.iterrows():
        try:
            row=(str(r[cols["symbol"]]).strip().upper(),str(r[cols["date"]]).strip(),
                 float(str(r[cols["open"]]).replace(",","")),float(str(r[cols["high"]]).replace(",","")),
                 float(str(r[cols["low"]]).replace(",","")),float(str(r[cols["close"]]).replace(",","")),
                 float(str(r[cols["volume"]]).replace(",","")) if cols["volume"] else 0.0,source)
            c.execute("INSERT OR REPLACE INTO daily_ohlc VALUES(?,?,?,?,?,?,?,?)",row); n+=1
        except Exception: pass
    c.commit();c.close();return n

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("files",nargs="+")
    p.add_argument("--db",default="psx_v2.db")
    args=p.parse_args()
    total=0
    for f in args.files:
        n=import_file(f,args.db);total+=n;print(f"{f}: {n} rows")
    print("Total imported:",total)
