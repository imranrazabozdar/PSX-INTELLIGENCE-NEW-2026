#!/usr/bin/env python3
"""watchlist_breakout_audit.py — READ-ONLY Phase D SHELF_BREAKOUT audit for the watchlist.

Signals come from the production detector itself (fire_engine/phase_d_detector.evaluate),
replayed day by day on the same last-90-bars window the daily batch uses, so
SOS_IGNITION / ACTIVE_SHELF / SHELF_BREAKOUT match the scanner exactly. Nothing is
written to any database: only SELECTs are issued. Output goes to stdout and
analysis/watchlist_breakout_dates.csv.

Trade model (Rule 2), one open position per symbol at a time:
  entry      next session's open after the SHELF_BREAKOUT close (flagged when that
             open is an upper-circuit lock (H==L, up) or gaps > 4% above signal close)
  crash stop intraday low <= entry * 0.75 -> exit at that level (or the open, if it gapped through)
  initial    first close <= EMA20 -> exit next session's open        (20EMA_STOP)
  trailing   once any close >= entry * 1.10, the EMA20 stop is replaced by:
             first close <  EMA10 -> exit next session's open        (10EMA_TRAIL)
  data end   still open -> marked at the last close                   (OPEN)

Data sources, first one that works:
  --local-db PATH   SQLite file with daily_ohlc (production schema)
  LIBSQL_URL env    production Turso via backend/turso_db.py (daily_ohlc)
  --host HOST       Turso HTTP pipeline (default: psx-library), table daily_ohlc else price_daily

  python analysis/watchlist_breakout_audit.py [--symbols A,B] [--local-db PATH] [--host HOST]
"""
import argparse
import csv
import json
import os
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)
from fire_engine import phase_d_detector as D  # noqa: E402

DEFAULT_WATCHLIST = ["EFERT", "ENGROH", "BAHL", "NBP", "BOP", "BAFL", "SSGC",
                     "APL", "PRL", "PASL", "TPLP", "AMBL", "SINDM"]
DEFAULT_HOST = "psx-library-turso202601.aws-us-east-1.turso.io"
OUT_CSV = ROOT / "analysis" / "watchlist_breakout_dates.csv"
COLUMNS = ["symbol", "ignition_date", "breakout_date", "news_lookup_window", "shelf_days",
           "signal_close", "next_open", "rvol_at_breakout", "mfe_pct", "mfe_date",
           "exit_date", "exit_price", "rule2_return_pct", "exit_reason", "entry_flag"]
CRASH, TRAIL_ON, GAP = 0.25, 0.10, 0.04


# ---------------------------------------------------------------- read-only data access
class HttpDB:
    def __init__(self, host):
        self.url = f"https://{host}/v2/pipeline"

    def query(self, sql, params=()):
        args = [{"type": "float" if isinstance(v, float) else "text", "value": str(v)} for v in params]
        body = json.dumps({"requests": [{"type": "execute", "stmt": {"sql": sql, "args": args}},
                                        {"type": "close"}]}).encode()
        req = urllib.request.Request(self.url, body, {"Content-Type": "application/json",
                                                      "Authorization": "Bearer proxy-injected"})
        res = json.load(urllib.request.urlopen(req, timeout=60))["results"][0]
        if res["type"] != "ok":
            raise RuntimeError(res["error"]["message"])
        r = res["response"]["result"]
        names = [c["name"] for c in r["cols"]]
        return [dict(zip(names, [c.get("value") for c in row])) for row in r["rows"]]


class ConnDB:
    def __init__(self, conn):
        self.conn = conn

    def query(self, sql, params=()):
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def open_db(a):
    if a.local_db:
        import sqlite3
        conn = sqlite3.connect(f"file:{a.local_db}?mode=ro", uri=True)   # read-only open
        conn.row_factory = sqlite3.Row
        return ConnDB(conn), f"sqlite:{a.local_db}"
    if os.getenv("LIBSQL_URL") and not a.host:
        import turso_db
        return ConnDB(turso_db.get_connection()), "turso:LIBSQL_URL"
    return HttpDB(a.host or DEFAULT_HOST), f"turso-http:{a.host or DEFAULT_HOST}"


def tables(db):
    return {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}


def load_watchlist(db, have):
    saved = []
    if "user_watchlist" in have:
        try:
            saved = [r["value"].upper() for r in db.query(
                "SELECT value FROM user_watchlist WHERE item_type='ticker' AND enabled=1")]
        except Exception as e:  # noqa: BLE001
            print(f"  (user_watchlist unreadable: {e})")
    return saved


def load_bars(db, table, sym):
    rows = db.query(f"SELECT trade_date, open, high, low, close, volume FROM {table} "
                    "WHERE symbol = ? ORDER BY trade_date", (sym,))
    return D.as_bars(rows)


# ---------------------------------------------------------------- signals + simulation
def ema(vals, span):
    return D._ema(vals, span)


def breakouts(bars):
    """Every SHELF_BREAKOUT the daily batch would have emitted (90-bar window per date)."""
    n, out = D.RULES["bars"], []
    for t in range(D.RULES["min_bars"] - 1, len(bars)):
        sig = D.evaluate(bars[max(0, t - n + 1):t + 1])
        if sig and sig["signal_type"] == "SHELF_BREAKOUT":
            out.append((t, sig))
    return out


def simulate(bars, t, e20, e10):
    """Rule 2 trade from the session after signal bar t. Returns dict or None (no next bar)."""
    if t + 1 >= len(bars):
        return None
    sig, nxt = bars[t], bars[t + 1]
    entry = nxt["open"]
    flags = []
    if nxt["high"] == nxt["low"] and nxt["close"] > sig["close"]:
        flags.append("UPPER_LOCK_UNFILLABLE")
    if entry > sig["close"] * (1 + GAP):
        flags.append(f"GAP>{GAP:.0%}")
    trailing, mfe, mfe_date = False, -1e9, None
    exit_i = exit_px = reason = None
    pending = None
    for j in range(t + 1, len(bars)):
        b = bars[j]
        if pending:                                   # exit at this session's open
            exit_i, exit_px, reason = j, b["open"], pending
            break
        g = (b["high"] / entry - 1) * 100
        if g > mfe:
            mfe, mfe_date = g, b["date"]
        crash = entry * (1 - CRASH)
        if b["low"] <= crash:
            exit_i, exit_px, reason = j, min(b["open"], crash), "CRASH_STOP_-25%"
            break
        if b["close"] >= entry * (1 + TRAIL_ON):
            trailing = True
        if trailing and b["close"] < e10[j]:
            pending = "10EMA_TRAIL"
        elif not trailing and b["close"] <= e20[j]:
            pending = "20EMA_STOP"
    if exit_i is None:
        exit_i, exit_px, reason = len(bars) - 1, bars[-1]["close"], "OPEN" + (f"({pending})" if pending else "")
    return {"next_open": entry, "exit_i": exit_i, "exit_date": bars[exit_i]["date"], "exit_price": exit_px,
            "ret": (exit_px / entry - 1) * 100, "reason": reason, "mfe": mfe, "mfe_date": mfe_date,
            "flags": ";".join(flags)}


def audit_symbol(sym, bars):
    closes = [b["close"] for b in bars]
    e20, e10 = ema(closes, 20), ema(closes, 10)
    trades, busy_until = [], -1
    for t, sig in breakouts(bars):
        if t < busy_until:                            # position still open -> no overlap
            continue
        bd = date.fromisoformat(sig["date"])
        sim = simulate(bars, t, e20, e10)
        row = {"symbol": sym, "ignition_date": sig["ignition_date"], "breakout_date": sig["date"],
               "news_lookup_window": f"{bd - timedelta(days=5)} to {bd + timedelta(days=2)}",
               "shelf_days": sig["shelf_days"], "signal_close": round(sig["close"], 2),
               "rvol_at_breakout": round(sig["rvol"], 2)}
        if sim is None:
            row.update(next_open="", mfe_pct="", mfe_date="", exit_date="", exit_price="",
                       rule2_return_pct="", exit_reason="NO_NEXT_SESSION", entry_flag="")
            busy_until = len(bars)
        else:
            row.update(next_open=round(sim["next_open"], 2), mfe_pct=round(sim["mfe"], 2),
                       mfe_date=sim["mfe_date"], exit_date=sim["exit_date"],
                       exit_price=round(sim["exit_price"], 2), rule2_return_pct=round(sim["ret"], 2),
                       exit_reason=sim["reason"], entry_flag=sim["flags"])
            busy_until = sim["exit_i"] if not sim["reason"].startswith("OPEN") else len(bars)
        trades.append(row)
    return trades


# ---------------------------------------------------------------- output
def print_table(rows, cols):
    w = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    print("  ".join(c.ljust(w[c]) for c in cols))
    print("  ".join("-" * w[c] for c in cols))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(w[c]) for c in cols))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default=None, help="comma list (overrides saved + default watchlist)")
    ap.add_argument("--local-db", default=None)
    ap.add_argument("--host", default=None)
    ap.add_argument("--out", default=str(OUT_CSV))
    a = ap.parse_args(argv)

    db, src = open_db(a)
    have = tables(db)
    table = "daily_ohlc" if "daily_ohlc" in have else "price_daily" if "price_daily" in have else None
    if not table:
        sys.exit(f"No daily_ohlc / price_daily table at {src}")
    if a.symbols:
        syms, wl_src = [s.strip().upper() for s in a.symbols.split(",") if s.strip()], "--symbols"
    else:
        saved = load_watchlist(db, have)
        syms = list(dict.fromkeys(saved + DEFAULT_WATCHLIST))
        wl_src = f"user_watchlist ({len(saved)}) + defaults" if saved else "defaults (no saved user_watchlist found)"
    print(f"Source: {src}  table={table}")
    print(f"Watchlist [{wl_src}]: {', '.join(syms)}\n")

    all_rows, coverage = [], []
    for s in syms:
        bars = load_bars(db, table, s)
        coverage.append((s, len(bars), bars[0]["date"] if bars else "-", bars[-1]["date"] if bars else "-"))
        if len(bars) >= D.RULES["min_bars"]:
            all_rows += audit_symbol(s, bars)

    print("Data coverage:")
    for s, n, f, l in coverage:
        print(f"  {s:<7} {n:>5} bars  {f} -> {l}" + ("   ** NO DATA / TOO SHORT **" if n < D.RULES["min_bars"] else ""))

    all_rows.sort(key=lambda r: (r["breakout_date"], r["symbol"]))
    with open(a.out, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=COLUMNS)
        wr.writeheader()
        wr.writerows(all_rows)

    print(f"\nSHELF_BREAKOUT trades (chronological) -> {a.out}\n")
    if all_rows:
        print_table(all_rows, COLUMNS)
    else:
        print("  (no SHELF_BREAKOUT signals in the available history)")

    print("\nPer-symbol summary (closed + open-marked trades):")
    summ = []
    for s, n, *_ in coverage:
        rs = [r for r in all_rows if r["symbol"] == s and r["rule2_return_pct"] != ""]
        if not rs:
            summ.append({"symbol": s, "triggers": 0, "win_rate_pct": "", "mean_return_pct": "", "best_runner": ""})
            continue
        best = max(rs, key=lambda r: r["rule2_return_pct"])
        summ.append({"symbol": s, "triggers": len(rs),
                     "win_rate_pct": round(100 * sum(r["rule2_return_pct"] > 0 for r in rs) / len(rs), 1),
                     "mean_return_pct": round(sum(r["rule2_return_pct"] for r in rs) / len(rs), 2),
                     "best_runner": f"{best['breakout_date']} {best['rule2_return_pct']:+.2f}% (MFE {best['mfe_pct']:+.2f}%)"})
    print_table(summ, ["symbol", "triggers", "win_rate_pct", "mean_return_pct", "best_runner"])


if __name__ == "__main__":
    main()
