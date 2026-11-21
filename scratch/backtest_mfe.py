"""Read-only follow-up to /tmp/backtest_phase_d.py: MFE before cancel + trailing exits for SHELF_BREAKOUT.
Same detector, window and no-lookahead replay. SELECT-only connection. Usage: python /tmp/backtest_mfe.py [--repo .] [--local-db F]"""
import argparse, os, statistics as stx, sys
from datetime import date, timedelta
ap = argparse.ArgumentParser(); ap.add_argument("--repo", default=os.getcwd()); ap.add_argument("--local-db")
ap.add_argument("--months", type=int, default=18); ap.add_argument("--cap", type=int, default=60)
A = ap.parse_args(); sys.path[:0] = [A.repo, os.path.join(A.repo, "backend")]
from fire_engine import phase_d_detector as D  # noqa
from fire_engine import run_phase_d_tracker as R  # noqa
W = D.RULES["bars"]

class RO:
    def __init__(s, c): s.c = c
    def execute(s, q, p=()):
        if not q.lstrip().upper().startswith("SELECT"): raise RuntimeError("read-only")
        return s.c.execute(q, p)
if A.local_db:
    import sqlite3; c = sqlite3.connect(A.local_db); c.row_factory = sqlite3.Row; conn = RO(c)
else:
    import turso_db; conn = RO(turso_db.get_connection())
def rd(r, k):
    try: return {x: r[x] for x in k}
    except (TypeError, IndexError, KeyError): return dict(zip(k, r))
K = ("trade_date", "open", "high", "low", "close", "volume")
end = rd(conn.execute("SELECT MAX(trade_date) AS d FROM daily_ohlc").fetchone(), ("d",))["d"]
start = (date.fromisoformat(str(end)[:10]) - timedelta(days=int(A.months * 30.44))).isoformat()
trades = []
for s in [u for u in R.universe() if u not in ("NPL", "NCPL", "PAEL")]:   # same 146 as the 37-trade run
    rows = [rd(r, K) for r in conn.execute("SELECT trade_date, open, high, low, close, volume FROM daily_ohlc "
                                            "WHERE symbol = ? ORDER BY trade_date", (s,)).fetchall()]
    rows = [r for r in rows if None not in (r["close"], r["high"], r["low"])]
    if len(rows) < D.RULES["min_bars"]: continue
    b = D.as_bars(rows); cl = [x["close"] for x in b]
    e20, e10 = D._ema(cl, 20), D._ema(cl, 10)
    for t in range(len(b)):
        if b[t]["date"] < start: continue
        w = b[max(0, t - W + 1):t + 1]
        if len(w) < D.RULES["min_bars"]: continue
        x = D.evaluate(w)
        if x and x["signal_type"] == "SHELF_BREAKOUT":
            trades.append(dict(sym=s, t=t, b=b, e20=e20, e10=e10, F=x["ignition_floor"], E=b[t]["close"], date=b[t]["date"]))
print(f"window {start} -> {end}; SHELF_BREAKOUT trades: {len(trades)}")

def pct(v, q):
    v = sorted(v); k = (len(v) - 1) * q; f = int(k); c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)

# 1. MFE before cancel (or +30 days)
mh, mc, dp, rows_ = [], [], [], []
for T in trades:
    b, t, E = T["b"], T["t"], T["E"]; best_h, best_c, dpk, stopd = 0.0, -9, 0, None
    for j in range(t + 1, min(t + 31, len(b))):
        if b[j]["high"] / E - 1 > best_h: best_h, dpk = b[j]["high"] / E - 1, j - t
        best_c = max(best_c, b[j]["close"] / E - 1)
        if b[j]["close"] <= max(T["e20"][j], T["F"]): stopd = j - t; break
    if best_c == -9: continue
    mh.append(best_h); mc.append(best_c); dp.append(dpk); rows_.append((T["sym"], T["date"], best_h, best_c, dpk, stopd))
print("\n1. MFE BEFORE CANCEL (close <= max(20 EMA, ignition floor)) or +30 days; n =", len(mh))
print(f"   {'':22}{'P25':>8}{'Median':>8}{'Mean':>8}{'P75':>8}{'P90':>8}")
for nm, v in (("Peak intraday high %", mh), ("Peak daily close %", mc)):
    print(f"   {nm:22}" + "".join(f"{x * 100:+7.1f}%" for x in (pct(v, .25), pct(v, .5), stx.mean(v), pct(v, .75), pct(v, .9))))
print(f"   {'Days to peak (high)':22}" + "".join(f"{x:8.1f}" for x in (pct(dp, .25), pct(dp, .5), stx.mean(dp), pct(dp, .75), pct(dp, .9))))
for th in (.05, .10, .15, .25):
    print(f"   reached >= +{th * 100:.0f}% before stop: high {sum(v >= th for v in mh) / len(mh) * 100:4.0f}%   "
          f"close {sum(v >= th for v in mc) / len(mc) * 100:4.0f}%")
print(f"   stopped within 30d: {sum(r[5] is not None for r in rows_)}/{len(rows_)}")

# 2. trailing exits: trigger on a close -> exit next open; cap at A.cap days (exit that close); open if data ends
def sim(T, rule):
    b, t, E, F, e20, e10 = T["b"], T["t"], T["E"], T["F"], T["e20"], T["e10"]
    armed, half, legs = False, False, []
    for j in range(t + 1, len(b)):
        h, c = b[j]["high"], b[j]["close"]
        if rule == 3 and not half and h >= 1.10 * E:
            legs.append((0.5, max(b[j]["open"], 1.10 * E) / E - 1)); half = True
        if rule == 2 and not armed and c >= 1.10 * E: armed = True
        if rule == 1 or (rule == 2 and not armed) or (rule == 3 and not half): trig = c <= max(e20[j], F)
        elif rule == 2: trig = c < e10[j]
        else: trig = c <= e20[j]
        cap = j - t >= A.cap
        if trig or cap:
            if cap and not trig: px, dd = c, j - t
            elif j + 1 < len(b): px, dd = b[j + 1]["open"], j + 1 - t
            else: return None
            w = 0.5 if half and rule == 3 else 1.0
            legs.append((w, px / E - 1)); return sum(a * r for a, r in legs), dd
    return None
print(f"\n2. TRAILING EXITS (entry Day-1 close; close trigger -> next open; max hold {A.cap} days)")
print(f"   {'rule':44}{'n':>4}{'win':>7}{'mean':>8}{'median':>8}{'max loss':>9}{'avg days':>9}{'open':>6}")
for k, nm in ((1, "1 Pure trail: close <= max(20EMA, floor)"), (2, "2 Tighten to 10 EMA after +10% close"),
              (3, "3 Sell 50% at +10%, rest trail 20 EMA")):
    res = [sim(T, k) for T in trades]; done = [r for r in res if r]; rr = [r[0] for r in done]
    print(f"   {nm:44}{len(done):>4}{sum(r > 0 for r in rr) / len(rr) * 100:6.0f}%{stx.mean(rr) * 100:+7.1f}%"
          f"{stx.median(rr) * 100:+7.1f}%{min(rr) * 100:+8.1f}%{stx.mean(r[1] for r in done):9.1f}{len(res) - len(done):>6}")
if hasattr(sys.modules.get("turso_db"), "print_usage_report"):
    sys.modules["turso_db"].print_usage_report(label="backtest_mfe.py (read-only)")
