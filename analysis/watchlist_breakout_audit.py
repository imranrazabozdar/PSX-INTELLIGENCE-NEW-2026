#!/usr/bin/env python3
"""watchlist_breakout_audit.py — READ-ONLY multi-year Phase D SHELF_BREAKOUT backtest.

Signals come from the production detector itself (fire_engine/phase_d_detector.evaluate),
replayed for every historical date on the same last-90-bars window the daily batch uses,
so SOS_IGNITION -> ACTIVE_SHELF (3-12 days) -> SHELF_BREAKOUT match the scanner exactly.
Only SELECTs are issued (a local SQLite file is opened with mode=ro); outputs are CSVs.

  Audit A  watchlist (user_watchlist + defaults), every trigger  -> multiyear_watchlist_breakouts.csv
  Audit B  every symbol in the table, stratified by entry price
           tier and free-float tier (when float data exists)      -> multiyear_tier_summary.csv
           (+ all full-market trades                              -> multiyear_all_trades.csv)

PSX execution model
  circuit       limit = max(10% of previous close, Rs 1.00); a price within 0.01 of it is "at" the lock
  entry         next session's open after the SHELF_BREAKOUT close
  UNFILLABLE_UPPER_LOCK  breakout bar closed at its upper lock AND next session Open == Low == upper lock
                (trade is kept in the CSV but excluded from return statistics)
  GAP_GT_4PCT   next open > signal close * 1.04
  Rule 2 exit   crash stop: intraday low <= entry * 0.75 -> fill at that level (or the open if gapped through)
                initial: first close <= EMA20 -> exit next session's open           (20EMA_STOP)
                once any close >= entry * 1.10, that stop is replaced by
                first close < EMA10 -> exit next session's open                       (10EMA_TRAIL)
                if the exit session is locked at lower circuit (Open == High == lower lock), the fill
                is deferred to the open of the first later session whose Low > its lower lock
                still open at data end -> marked at last close                       (OPEN)

Data source (first that works):
  --local-db PATH   SQLite snapshot with daily_ohlc
  LIBSQL_URL env    production Turso via backend/turso_db.py (LIBSQL_AUTH_TOKEN)
  --host HOST       Turso HTTP pipeline (default psx-library; daily_ohlc else price_daily)

  python analysis/watchlist_breakout_audit.py [--audit A|B|AB] [--local-db PATH] [--out-dir DIR]
"""
import argparse
import csv
import json
import os
import statistics
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)
from fire_engine import phase_d_detector as D  # noqa: E402

R = D.RULES
DEFAULT_WATCHLIST = ["EFERT", "ENGROH", "BAHL", "NBP", "BOP", "BAFL", "SSGC",
                     "APL", "PRL", "PASL", "TPLP", "AMBL", "SINDM"]
DEFAULT_HOST = "psx-library-turso202601.aws-us-east-1.turso.io"
A_COLS = ["symbol", "year", "ignition_date", "breakout_date", "news_lookup_window", "shelf_days",
          "signal_close", "next_open", "entry_flag", "rvol_at_breakout", "mfe_pct", "mfe_date",
          "exit_date", "exit_price", "rule2_return_pct", "exit_reason"]
ALL_COLS = A_COLS + ["hold_days", "price_tier", "float_tier", "free_float_pct"]
B_COLS = ["tier_type", "bucket", "total_signals", "fillable_trades", "unfillable_lock_pct", "win_rate_pct",
          "mean_return_pct", "median_return_pct", "mean_mfe_pct", "p90_mfe_pct", "worst_loss_pct", "avg_hold_days"]
PRICE_TIERS = ["< Rs. 10", "Rs. 10-25", "Rs. 25.01-100", "> Rs. 100"]
FLOAT_TIERS = ["<= 20%", "20.01%-50%", "> 50%"]
CRASH, TRAIL_ON, GAP, TICK = 0.25, 0.10, 0.04, 0.011


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
        res = json.load(urllib.request.urlopen(req, timeout=120))["results"][0]
        if res["type"] != "ok":
            raise RuntimeError(res["error"]["message"])
        r = res["response"]["result"]
        names = [c["name"] for c in r["cols"]]
        return [dict(zip(names, [c.get("value") for c in row])) for row in r["rows"]]


class ConnDB:
    def __init__(self, conn):
        self.conn = conn

    def query(self, sql, params=()):
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]


def open_db(a):
    if a.local_db:
        import sqlite3
        conn = sqlite3.connect(f"file:{a.local_db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return ConnDB(conn), f"sqlite (read-only): {a.local_db}"
    url = os.getenv("LIBSQL_URL") or os.getenv("TURSO_DATABASE_URL")
    if url and not a.host:
        os.environ.setdefault("LIBSQL_URL", url)
        if not os.getenv("LIBSQL_AUTH_TOKEN") and os.getenv("TURSO_AUTH_TOKEN"):
            os.environ["LIBSQL_AUTH_TOKEN"] = os.environ["TURSO_AUTH_TOKEN"]
        import turso_db
        return ConnDB(turso_db.get_connection()), "turso (production, via LIBSQL_URL secret -- address not printed)"
    return HttpDB(a.host or DEFAULT_HOST), f"turso-http: {a.host or DEFAULT_HOST}"


def table_names(db):
    return {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}


def columns(db, table):
    return [r["name"] for r in db.query(f"PRAGMA table_info({table})")]


def load_watchlist(db, have):
    if "user_watchlist" not in have:
        return []
    try:
        return [r["value"].upper() for r in db.query(
            "SELECT value FROM user_watchlist WHERE item_type='ticker' AND enabled=1")]
    except Exception as e:  # noqa: BLE001
        print(f"  (user_watchlist unreadable: {e})")
        return []


def load_free_float(db, have):
    """{symbol: free_float_pct} from the first table with a symbol + free-float column, else {}."""
    for t in sorted(have):
        try:
            cols = columns(db, t)
        except Exception:  # noqa: BLE001
            continue
        low = {c.lower(): c for c in cols}
        fcol = next((low[k] for k in ("free_float_pct", "free_float", "freefloat", "free_float_percent") if k in low), None)
        scol = low.get("symbol") or low.get("ticker")
        if not (fcol and scol):
            continue
        out = {}
        for r in db.query(f"SELECT {scol} AS s, {fcol} AS f FROM {t} WHERE {fcol} IS NOT NULL"):
            try:
                v = float(str(r["f"]).rstrip("%"))
            except ValueError:
                continue
            out[str(r["s"]).upper()] = v * 100 if v <= 1.0 else v      # accept fraction or percent
        if out:
            print(f"Free float: {len(out)} symbols from {t}.{fcol}")
            return out
    print("Free float: no table with a symbol + free-float column found -> float tiers skipped")
    return {}


def load_bars(db, table, sym):
    return D.as_bars(db.query(f"SELECT trade_date, open, high, low, close, volume FROM {table} "
                              "WHERE symbol = ? ORDER BY trade_date", (sym,)))


# ---------------------------------------------------------------- PSX circuit helpers
def band(prev_close):
    return max(0.10 * prev_close, 1.0)


def upper_lock(prev_close):
    return prev_close + band(prev_close)


def lower_lock(prev_close):
    return prev_close - band(prev_close)


def locked_down(b, prev_close):
    ll = lower_lock(prev_close)
    return abs(b["open"] - b["high"]) < TICK and b["high"] <= ll + TICK


# ---------------------------------------------------------------- signals + Rule 2 simulation
def breakouts(bars):
    """Every SHELF_BREAKOUT the daily batch would have emitted (90-bar window per date).
    Bars that fail a necessary breakout condition (RVOL >= 2.5, strong close, turnover)
    are skipped before calling evaluate -- identical output, far fewer detector calls."""
    n, out = R["bars"], []
    vol = [b["volume"] for b in bars]
    for t in range(max(R["min_bars"] - 1, 20), len(bars)):
        b = bars[t]
        sma = sum(vol[t - 20:t]) / 20
        if not sma or b["volume"] < R["breakout_vol_mult"] * sma or b["close"] * b["volume"] < R["min_turnover_pkr"] \
                or not D._strong_close(b, bars[t - 1]["close"], R["strong_close"]):
            continue
        sig = D.evaluate(bars[max(0, t - n + 1):t + 1])
        if sig and sig["signal_type"] == "SHELF_BREAKOUT":
            out.append((t, sig))
    return out


def fill_exit(bars, j):
    """Exit at session j's open, deferred past lower-circuit locked sessions."""
    while j < len(bars) and locked_down(bars[j], bars[j - 1]["close"]):
        j += 1
    while j < len(bars) and not (bars[j]["low"] > lower_lock(bars[j - 1]["close"]) + 1e-9):
        j += 1
    return j


def simulate(bars, t, e20, e10):
    if t + 1 >= len(bars):
        return None
    sig, nxt = bars[t], bars[t + 1]
    entry = nxt["open"]
    flags = []
    ul = upper_lock(bars[t - 1]["close"])
    if sig["close"] >= ul - TICK and abs(nxt["open"] - nxt["low"]) < TICK and nxt["low"] >= upper_lock(sig["close"]) - TICK:
        flags.append("UNFILLABLE_UPPER_LOCK")
    if entry > sig["close"] * (1 + GAP):
        flags.append("GAP_GT_4PCT")
    trailing, mfe, mfe_date = False, float("-inf"), None
    exit_i = exit_px = reason = None
    for j in range(t + 1, len(bars)):
        b = bars[j]
        g = (b["high"] / entry - 1) * 100
        if g > mfe:
            mfe, mfe_date = g, b["date"]
        crash = entry * (1 - CRASH)
        if b["low"] <= crash:
            exit_i, exit_px, reason = j, min(b["open"], crash), "CRASH_STOP_-25%"
            break
        if b["close"] >= entry * (1 + TRAIL_ON):
            trailing = True
        hit = ("10EMA_TRAIL" if b["close"] < e10[j] else None) if trailing else \
              ("20EMA_STOP" if b["close"] <= e20[j] else None)
        if hit:
            k = fill_exit(bars, j + 1)
            if k < len(bars):
                for m in range(j + 1, k + 1):           # MFE through the fill session
                    g = (bars[m]["high"] / entry - 1) * 100
                    if g > mfe:
                        mfe, mfe_date = g, bars[m]["date"]
                exit_i, exit_px, reason = k, bars[k]["open"], hit + ("_LLOCK_DEFERRED" if k > j + 1 else "")
            else:
                exit_i, exit_px, reason = len(bars) - 1, bars[-1]["close"], f"OPEN({hit})"
            break
    if exit_i is None:
        exit_i, exit_px, reason = len(bars) - 1, bars[-1]["close"], "OPEN"
    return {"next_open": entry, "exit_i": exit_i, "exit_date": bars[exit_i]["date"], "exit_price": exit_px,
            "ret": (exit_px / entry - 1) * 100, "reason": reason, "mfe": mfe, "mfe_date": mfe_date,
            "flags": ";".join(flags), "hold": exit_i - (t + 1)}


def price_tier(p):
    return PRICE_TIERS[0] if p < 10 else PRICE_TIERS[1] if p <= 25 else PRICE_TIERS[2] if p <= 100 else PRICE_TIERS[3]


def float_tier(f):
    if f is None:
        return ""
    return FLOAT_TIERS[0] if f <= 20 else FLOAT_TIERS[1] if f <= 50 else FLOAT_TIERS[2]


def audit_symbol(sym, bars, ff=None):
    closes = [b["close"] for b in bars]
    e20, e10 = D._ema(closes, 20), D._ema(closes, 10)
    trades, busy_until = [], -1
    for t, sig in breakouts(bars):
        if t < busy_until:                              # one open position per symbol
            continue
        bd = date.fromisoformat(sig["date"])
        sim = simulate(bars, t, e20, e10)
        row = {"symbol": sym, "year": bd.year, "ignition_date": sig["ignition_date"], "breakout_date": sig["date"],
               "news_lookup_window": f"{bd - timedelta(days=5)} to {bd + timedelta(days=2)}",
               "shelf_days": sig["shelf_days"], "signal_close": round(sig["close"], 2),
               "rvol_at_breakout": round(sig["rvol"], 2), "free_float_pct": "" if ff is None else round(ff, 1),
               "float_tier": float_tier(ff)}
        if sim is None:
            row.update(next_open="", entry_flag="", mfe_pct="", mfe_date="", exit_date="", exit_price="",
                       rule2_return_pct="", exit_reason="NO_NEXT_SESSION", hold_days="",
                       price_tier=price_tier(sig["close"]))
            busy_until = len(bars)
        else:
            row.update(next_open=round(sim["next_open"], 2), entry_flag=sim["flags"], mfe_pct=round(sim["mfe"], 2),
                       mfe_date=sim["mfe_date"], exit_date=sim["exit_date"], exit_price=round(sim["exit_price"], 2),
                       rule2_return_pct=round(sim["ret"], 2), exit_reason=sim["reason"], hold_days=sim["hold"],
                       price_tier=price_tier(sim["next_open"]))
            busy_until = len(bars) if sim["reason"].startswith("OPEN") else sim["exit_i"]
        trades.append(row)
    return trades


# ---------------------------------------------------------------- stats + output
def bucket_stats(tier_type, bucket, rows):
    sims = [r for r in rows if r["rule2_return_pct"] != ""]
    unf = [r for r in sims if "UNFILLABLE_UPPER_LOCK" in r["entry_flag"]]
    fill = [r for r in sims if "UNFILLABLE_UPPER_LOCK" not in r["entry_flag"]]
    rets, mfes = [r["rule2_return_pct"] for r in fill], [r["mfe_pct"] for r in fill]
    p90 = (statistics.quantiles(mfes, n=10, method="inclusive")[-1] if len(mfes) >= 2 else (mfes[0] if mfes else ""))
    rnd = lambda v: round(v, 2) if v != "" else ""  # noqa: E731
    return {"tier_type": tier_type, "bucket": bucket, "total_signals": len(rows), "fillable_trades": len(fill),
            "unfillable_lock_pct": rnd(100 * len(unf) / len(sims)) if sims else "",
            "win_rate_pct": rnd(100 * sum(x > 0 for x in rets) / len(rets)) if rets else "",
            "mean_return_pct": rnd(statistics.mean(rets)) if rets else "",
            "median_return_pct": rnd(statistics.median(rets)) if rets else "",
            "mean_mfe_pct": rnd(statistics.mean(mfes)) if mfes else "", "p90_mfe_pct": rnd(p90),
            "worst_loss_pct": rnd(min(rets)) if rets else "",
            "avg_hold_days": rnd(statistics.mean(r["hold_days"] for r in fill)) if fill else ""}


def print_table(rows, cols):
    if not rows:
        print("  (none)")
        return
    w = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    print("  ".join(c.ljust(w[c]) for c in cols))
    print("  ".join("-" * w[c] for c in cols))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(w[c]) for c in cols))


def write_csv(path, rows, cols):
    with open(path, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)
    print(f"  saved {len(rows)} rows -> {path}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--audit", default="AB", help="A, B or AB (default)")
    ap.add_argument("--symbols", default=None, help="comma list overriding the Audit A watchlist")
    ap.add_argument("--local-db", default=None)
    ap.add_argument("--host", default=None)
    ap.add_argument("--out-dir", default=str(ROOT / "analysis"))
    a = ap.parse_args(argv)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    db, src = open_db(a)
    have = table_names(db)
    table = "daily_ohlc" if "daily_ohlc" in have else "price_daily" if "price_daily" in have else None
    if not table:
        sys.exit(f"No daily_ohlc / price_daily table at {src}")
    meta = db.query(f"SELECT COUNT(DISTINCT symbol) AS n, MIN(trade_date) AS lo, MAX(trade_date) AS hi, "
                    f"COUNT(*) AS rows FROM {table}")[0]
    print("=" * 78)
    print(f"Database source : {src}")
    print(f"Table           : {table}")
    print(f"Symbols covered : {meta['n']}   rows: {meta['rows']}")
    print(f"Date range      : {meta['lo']} -> {meta['hi']}")
    if table != "daily_ohlc":
        print("WARNING         : production daily_ohlc not reachable; this is NOT the multi-year history.")
    print("=" * 78)

    ff = load_free_float(db, have)
    cache = {}

    def bars_of(s):
        if s not in cache:
            cache[s] = load_bars(db, table, s)
        return cache[s]

    if "A" in a.audit.upper():
        if a.symbols:
            syms, wl = [s.strip().upper() for s in a.symbols.split(",") if s.strip()], "--symbols"
        else:
            saved = load_watchlist(db, have)
            syms = list(dict.fromkeys(saved + DEFAULT_WATCHLIST))
            wl = f"user_watchlist ({len(saved)}) + defaults" if saved else "defaults (no user_watchlist table)"
        print(f"\n### AUDIT A — watchlist [{wl}]: {', '.join(syms)}")
        rows = []
        for s in syms:
            b = bars_of(s)
            print(f"  {s:<8} {len(b):>5} bars  {b[0]['date'] if b else '-'} -> {b[-1]['date'] if b else '-'}"
                  + ("   ** NO DATA / TOO SHORT **" if len(b) < R["min_bars"] else ""))
            if len(b) >= R["min_bars"]:
                rows += audit_symbol(s, b, ff.get(s))
        rows.sort(key=lambda r: (r["breakout_date"], r["symbol"]))
        print("\nChronological SHELF_BREAKOUT triggers:")
        print_table(rows, A_COLS)
        write_csv(out / "multiyear_watchlist_breakouts.csv", rows, A_COLS)
        print("\nPer-symbol summary:")
        print_table([bucket_stats("symbol", s, [r for r in rows if r["symbol"] == s]) for s in syms
                     if any(r["symbol"] == s for r in rows)], B_COLS[1:])

    if "B" in a.audit.upper():
        universe = [r["symbol"] for r in db.query(f"SELECT DISTINCT symbol FROM {table} ORDER BY symbol")]
        print(f"\n### AUDIT B — full market: {len(universe)} symbols")
        rows, t0 = [], time.time()
        for k, s in enumerate(universe, 1):
            b = bars_of(s)
            if len(b) >= R["min_bars"]:
                rows += audit_symbol(s, b, ff.get(s.upper()))
            cache.pop(s, None)
            if k % 50 == 0:
                print(f"  {k}/{len(universe)} symbols, {len(rows)} signals, {time.time() - t0:.0f}s")
        rows.sort(key=lambda r: (r["breakout_date"], r["symbol"]))
        write_csv(out / "multiyear_all_trades.csv", rows, ALL_COLS)
        summ = [bucket_stats("ALL", "ALL", rows)]
        summ += [bucket_stats("price", t, [r for r in rows if r["price_tier"] == t]) for t in PRICE_TIERS]
        if ff:
            summ += [bucket_stats("free_float", t, [r for r in rows if r["float_tier"] == t]) for t in FLOAT_TIERS]
            summ.append(bucket_stats("free_float", "unknown", [r for r in rows if r["float_tier"] == ""]))
        years = sorted({r["year"] for r in rows})
        summ += [bucket_stats("year", str(y), [r for r in rows if r["year"] == y]) for y in years]
        print("\nTier summary (returns/MFE on fillable trades only):")
        print_table(summ, B_COLS)
        write_csv(out / "multiyear_tier_summary.csv", summ, B_COLS)


if __name__ == "__main__":
    main()
