"""Read-only historical backtest of fire_engine/phase_d_detector.py.

Replays the live detector bar by bar (the same 90-bar window the daily batch uses, no lookahead),
then measures forward returns from the signal day's close. SELECT statements only; any other SQL
raises. Thresholds are never changed except in the in-memory shelf-cap sensitivity copies.
Usage: python /tmp/backtest_phase_d.py [--repo DIR] [--local-db FILE] [--months 18]
"""
import argparse
import os
import statistics as stx
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta

ap = argparse.ArgumentParser()
ap.add_argument("--repo", default=os.getcwd())
ap.add_argument("--local-db")
ap.add_argument("--months", type=int, default=18)
A = ap.parse_args()
sys.path[:0] = [A.repo, os.path.join(A.repo, "backend")]
from fire_engine import phase_d_detector as D  # noqa: E402
from fire_engine import run_phase_d_tracker as R  # noqa: E402

W = D.RULES["bars"]
HORIZONS = (5, 10, 20)


class ReadOnly:
    def __init__(self, c):
        self.c = c

    def execute(self, sql, params=()):
        if not sql.lstrip().upper().startswith("SELECT"):
            raise RuntimeError("read-only backtest: refused " + sql[:40])
        return self.c.execute(sql, params)


def connect():
    if A.local_db:
        import sqlite3
        c = sqlite3.connect(A.local_db)
        c.row_factory = sqlite3.Row
        return ReadOnly(c)
    import turso_db
    return ReadOnly(turso_db.get_connection())


def rowdict(r, keys):
    try:
        return {k: r[k] for k in keys}
    except (TypeError, IndexError, KeyError):
        return dict(zip(keys, r))


conn = connect()
syms = R.universe()
end = rowdict(conn.execute("SELECT MAX(trade_date) AS d FROM daily_ohlc").fetchone(), ("d",))["d"]
start = (date.fromisoformat(str(end)[:10]) - timedelta(days=int(A.months * 30.44))).isoformat()
K = ("trade_date", "open", "high", "low", "close", "volume")
data = {}
for s in syms:
    rows = conn.execute("SELECT trade_date, open, high, low, close, volume FROM daily_ohlc WHERE symbol = ? "
                        "ORDER BY trade_date", (s,)).fetchall()
    rows = [rowdict(r, K) for r in rows if r is not None]
    rows = [r for r in rows if r["close"] is not None and r["high"] is not None and r["low"] is not None]
    if len(rows) >= D.RULES["min_bars"]:
        data[s] = D.as_bars(rows)
if not data:
    sys.exit("no data")


def replay(bars, r):
    """{t: signal} for every bar t inside the test window, live 90-bar window, rules r."""
    out = {}
    for t in range(len(bars)):
        if bars[t]["date"] < start:
            continue
        w = bars[max(0, t - W + 1):t + 1]
        if len(w) < D.RULES["min_bars"]:
            continue
        sig = D.evaluate(w, r)
        if sig:
            out[t] = sig
    return out


def fwd(bars, t, k):
    return bars[t + k]["close"] / bars[t]["close"] - 1 if t + k < len(bars) and bars[t]["close"] else None


def stopped(bars, ema, t, floor, n=10):
    """Any close in t+1..t+n at or below max(EMA20 that day, ignition floor)."""
    for j in range(t + 1, min(t + n + 1, len(bars))):
        if bars[j]["close"] <= max(ema[j], floor if floor is not None else -1):
            return True
    return False if t + n < len(bars) else None


def bucket(tv):
    return "Liquid >=25M" if tv >= 25e6 else ("Mid/Small 5-25M" if tv >= 5e6 else "<5M")


base = {s: replay(b, D.RULES) for s, b in data.items()}
ema_full = {s: D._ema([x["close"] for x in b], 20) for s, b in data.items()}
in_win = [b for b in data.values() for x in b if x["date"] >= start]
dates = sorted({x["date"] for b in data.values() for x in b if x["date"] >= start})

print("=" * 100)
print("1. DATASET SCOPE")
print(f"   window {dates[0]} -> {dates[-1]}  ({len(dates)} trading sessions; requested {A.months} months back "
      f"from {end}; earliest daily_ohlc bar {min(b[0]['date'] for b in data.values())})")
print(f"   symbols evaluated {len(data)} of {len(syms)} in the configured universe "
      f"(rest have < {D.RULES['min_bars']} bars); bar-evaluations {len(in_win):,}")
print(f"   detector: fire_engine/phase_d_detector.py evaluate(), live {W}-bar window, RULES unchanged")
print(f"   signals: {dict(Counter(s['signal_type'] for v in base.values() for s in v.values()))}")

# ---------------------------------------------------------------- 2. funnel
print("\n" + "=" * 100)
print("2. CONVERSION FUNNEL (per SOS_IGNITION event)")
fun = Counter()
shelf_fate = Counter()
for s, sig in base.items():
    bars = data[s]
    idx = {b["date"]: i for i, b in enumerate(bars)}
    for t, x in sig.items():
        if x["signal_type"] != "SOS_IGNITION":
            continue
        fun["sos"] += 1
        ign = x["date"]
        shelf_ts = [u for u, y in sig.items() if y["signal_type"] == "ACTIVE_SHELF" and y["ignition_date"] == ign]
        bo = [u for u, y in sig.items() if y["signal_type"] == "SHELF_BREAKOUT" and y["ignition_date"] == ign]
        if t + D.RULES["shelf_min_age"] >= len(bars):
            fun["too_recent"] += 1
            continue
        if not shelf_ts:
            fun["no_shelf"] += 1
            continue
        fun["shelf"] += 1
        last = max(shelf_ts)
        if bo:
            shelf_fate["breakout"] += 1
            continue
        age = last - t
        if last + 1 >= len(bars):
            shelf_fate["still open"] += 1
            continue
        nxt = D.evaluate(bars[max(0, last + 2 - W):last + 2])
        if nxt and nxt["signal_type"] == "SOS_IGNITION":
            shelf_fate["superseded by new SOS"] += 1
            continue
        if age >= D.RULES["shelf_max_age"]:
            shelf_fate["expired (Day 12, no breakout)"] += 1
            continue
        w = bars[max(0, last + 2 - W):last + 2]
        off = max(0, last + 2 - W)
        ema = D._ema([b["close"] for b in w], 20)
        m = D.shelf_metrics(w, t - off, last + 1 - off, ema)
        if not m["held"]:
            shelf_fate["cancelled: close <= 20 EMA / ignition floor"] += 1
        elif not m["depth_ok"]:
            shelf_fate["cancelled: >25% pullback"] += 1
        elif not m["vol_ok"]:
            shelf_fate["cancelled: volume rule"] += 1
        else:
            shelf_fate["other"] += 1
n = fun["sos"]
done = n - fun["too_recent"]
print(f"   SOS_IGNITION events            {n}")
print(f"   too recent to judge (< 3 days)  {fun['too_recent']}")
print(f"   formed ACTIVE_SHELF (Day 3+)    {fun['shelf']}  = {fun['shelf'] / done * 100 if done else 0:.1f}% of {done}")
print(f"   never formed a shelf            {fun['no_shelf']}  = {fun['no_shelf'] / done * 100 if done else 0:.1f}%")
tot = sum(shelf_fate.values())
print(f"   fate of the {tot} shelves:")
for k, v in shelf_fate.most_common():
    print(f"     {k:<46} {v:>4}  {v / tot * 100:5.1f}%")

# ---------------------------------------------------------------- 3. forward performance


def trades(sig_map, pick):
    out = []
    for s, sig in sig_map.items():
        bars = data[s]
        for t, x in sig.items():
            if pick(x):
                out.append(dict(sym=s, t=t, date=x["date"], close=x["close"], rvol=x["rvol"], tv=x["turnover_pkr"],
                                floor=x.get("ignition_floor"), **{f"r{k}": fwd(bars, t, k) for k in HORIZONS},
                                stop=stopped(bars, ema_full[s], t, x.get("ignition_floor"))))
    return out


def report(name, tr):
    print(f"\n   {name}")
    groups = [("ALL", tr)] + [(b, [x for x in tr if bucket(x["tv"]) == b])
                              for b in ("Liquid >=25M", "Mid/Small 5-25M", "<5M")]
    print(f"   {'group':<17}{'n':>5} | " + " | ".join(f"+{k}d win  >=15%  mean  median" for k in HORIZONS)
          + " | stop<=10d")
    for g, xs in groups:
        if not xs:
            continue
        cells = []
        for k in HORIZONS:
            r = [x[f"r{k}"] for x in xs if x[f"r{k}"] is not None]
            if r:
                cells.append(f"{len(r):>3}:{sum(v > 0 for v in r) / len(r) * 100:4.0f}% {sum(v >= .15 for v in r) / len(r) * 100:4.0f}% "
                             f"{stx.mean(r) * 100:+5.1f}% {stx.median(r) * 100:+5.1f}%")
            else:
                cells.append(" " * 28)
        st_ = [x["stop"] for x in xs if x["stop"] is not None]
        cells.append(f"{sum(st_) / len(st_) * 100:4.0f}% ({len(st_)})" if st_ else "  —")
        print(f"   {g:<17}{len(xs):>5} | " + " | ".join(cells))


print("\n" + "=" * 100)
print("3. FORWARD PERFORMANCE (entry = signal-day close; '+Nd n:' = trades with N days of data)")
A_tr = trades(base, lambda x: x["signal_type"] == "SHELF_BREAKOUT")
B_tr = trades(base, lambda x: x["signal_type"] == "ACTIVE_SHELF" and x["shelf_days"] == 4
              and x["rvol"] is not None and x["rvol"] <= 0.80)
report("Strategy A — SHELF_BREAKOUT, Day-1 close", A_tr)
report("Strategy B — ACTIVE_SHELF Day 4 close, RVOL <= 0.80x", B_tr)
print("   stop = any close within 10 trading days at or below max(20 EMA that day, ignition floor)")

# ---------------------------------------------------------------- 4. shelf-cap sensitivity
print("\n" + "=" * 100)
print("4. SHELF WINDOW SENSITIVITY (in-memory RULES copies; production file unchanged)")
base_keys = {(x["sym"], x["date"]) for x in A_tr}
for cap in (12, 15, 18):
    r = dict(D.RULES, shelf_max_age=cap)
    sm = base if cap == 12 else {s: replay(b, r) for s, b in data.items()}
    tr = trades(sm, lambda x: x["signal_type"] == "SHELF_BREAKOUT")
    extra = [x for x in tr if (x["sym"], x["date"]) not in base_keys]

    def wr(xs, k):
        v = [x[f"r{k}"] for x in xs if x[f"r{k}"] is not None]
        return f"{sum(a > 0 for a in v) / len(v) * 100:4.0f}% (n={len(v)}, mean {stx.mean(v) * 100:+.1f}%)" if v else "—"
    print(f"   cap {cap:>2}: {len(tr):>4} breakouts  (+{len(extra)} vs 12) | all +10d {wr(tr, 10)} +20d {wr(tr, 20)}"
          f" | extra only +10d {wr(extra, 10)} +20d {wr(extra, 20)}")

# ---------------------------------------------------------------- 5. case audit
print("\n" + "=" * 100)
print("5. CASE AUDIT — SHELF_BREAKOUT")


def line(x):
    f = lambda v: f"{v * 100:+6.1f}%" if v is not None else "    —  "
    return (f"   {x['sym']:<9}{x['date']}  Rs {x['close']:>9.2f}  RVOL {x['rvol'] or 0:5.2f}x  "
            f"TO {x['tv'] / 1e6:8.1f}M  +5d {f(x['r5'])}  +10d {f(x['r10'])}  +20d {f(x['r20'])}  stop {x['stop']}")


print("   10 best by +20d:")
for x in sorted([x for x in A_tr if x["r20"] is not None], key=lambda x: -x["r20"])[:10]:
    print(line(x))
print("   10 worst by +10d:")
for x in sorted([x for x in A_tr if x["r10"] is not None], key=lambda x: x["r10"])[:10]:
    print(line(x))
if hasattr(sys.modules.get("turso_db"), "print_usage_report"):
    sys.modules["turso_db"].print_usage_report(label="backtest_phase_d.py (read-only)")
