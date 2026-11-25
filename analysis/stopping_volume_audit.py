#!/usr/bin/env python3
"""stopping_volume_audit.py -- READ-ONLY stopping-volume / absorption-in-downtrend audit.

Standalone causal implementation (does not reuse fire_engine/wyckoff_detector.py absorption,
backend/wyckoff_engine.py SC/BC, or fire_engine/absorption.py). Every T0 quantity uses data
through T0 only; the entry is the next session's open (T0+1).

Signal (day T0, all causal):
  Down state    Close < SMA20 AND Close < SMA50 AND Close <= 0.90 * Highest_High_30D (30 sessions incl. T0)
  Abnormal vol  Volume / Vol_SMA20 >= 2.0, where Vol_SMA20 = mean Volume over the 20 sessions ending T0-1
                MODERATE 2.0 <= ratio < 3.0 ; EXTREME ratio >= 3.0
  Absorption    |Close - PrevClose| / PrevClose <= 2%  (NET_LE_2PCT; STRICT = <= 1%)
                AND (Close - Low) / max(High - Low, 1e-6) >= 0.50
                zero-range bars (High == Low) are excluded from the signal
  Liquidity     median(Close * Volume) over the 20 sessions ending T0-1 >= 5,000,000 PKR
  Entry         Open(T0+1). Signal dropped if the entry session is an upper-circuit lock
                (O == H == L at A.upper_lock(Close[T0])); counted separately.
  Dedupe        after a qualifying candidate, candidates T0+1..T0+10 are ignored (per symbol)

View A  forward excursion from entry, windows of 5 / 10 / 20 sessions (entry = day 1), no stops.
View B  tradable exits net of 0.45% round-trip friction:
  S1  target E*1.06, stop S, max hold 10 sessions
  S2  target E*1.08, stop S, max hold 15 sessions
  S3  no target, hard stop STOP_ATR, time exit at Close of day 10
  STOP_ATR = Low(T0) - 0.5*ATR14(T0);  S (S1, S2) = max(STOP_ATR, E*0.96);  S3 uses STOP_ATR only.

Data: daily_ohlc, 2021-09-01 .. 2026-11-24, one SELECT per symbol (GuardDB refuses non-reads).
Universe: fire_engine/config/fire_config.yaml stocks.universe.

  python analysis/stopping_volume_audit.py [--local-db PATH] [--out-dir DIR] [--symbols A,B]
"""
import argparse
import csv
import os
import statistics
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "backend"), str(ROOT / "analysis")):
    if p not in sys.path:
        sys.path.insert(0, p)
import watchlist_breakout_audit as A  # noqa: E402
import phase_d_ytd_audit as Y  # noqa: E402

TABLE = "daily_ohlc"
START, YTD_START, END = "2021-09-01", "2026-01-01", "2026-11-24"
SIG_2025 = "2025-01-01"
TICK = A.TICK
FRICTION = 0.45
LIQ_PKR = 5_000_000
COOLDOWN = 10
MIN_BARS = 60
WINDOWS = (5, 10, 20)
THRESH = (5, 8, 10, 15)
STRATS = {  # name: (target multiple of E or None, max hold sessions, stop floor at 0.96E?)
    "S1": (1.06, 10, True),
    "S2": (1.08, 15, True),
    "S3": (None, 10, False),
}
OUT_CSV = "stopping_volume_trades.csv"
OUT_RPT = "stopping_volume_report.txt"


# ---------------------------------------------------------------- indicators (causal)
def atr14_series(bars):
    n = len(bars)
    tr = [0.0] * n
    for i in range(1, n):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    atr = [None] * n
    if n > 14:
        atr[14] = sum(tr[1:15]) / 14.0
        for i in range(15, n):
            atr[i] = (atr[i - 1] * 13 + tr[i]) / 14.0  # Wilder smoothing
    return atr


def is_upper_lock(b, prev_close):
    """O == H == L sitting at the upper circuit computed from the prior close."""
    return (abs(b["open"] - b["high"]) < TICK and abs(b["high"] - b["low"]) < TICK
            and abs(b["open"] - A.upper_lock(prev_close)) < TICK)


def qualifies(bars, atr, i):
    """Signal conditions on T0 = i. Returns dict or None. Uses bars[0..i] only (plus entry existence)."""
    n = len(bars)
    if i < 50 or i + 1 >= n:
        return None
    b = bars[i]
    C, H, L = b["close"], b["high"], b["low"]
    if H <= L:  # zero-range locked bar: excluded from the signal
        return None
    sma20 = sum(x["close"] for x in bars[i - 19:i + 1]) / 20.0
    sma50 = sum(x["close"] for x in bars[i - 49:i + 1]) / 50.0
    hh30 = max(x["high"] for x in bars[i - 29:i + 1])
    if not (C < sma20 and C < sma50 and C <= 0.90 * hh30):
        return None
    prior = bars[i - 20:i]  # sessions ending T0-1
    vol_sma = sum(x["volume"] for x in prior) / 20.0
    if vol_sma <= 0:
        return None
    ratio = b["volume"] / vol_sma
    if ratio < 2.0:
        return None
    pc = bars[i - 1]["close"]
    if pc <= 0:
        return None
    chg = abs(C - pc) / pc
    if chg > 0.02:
        return None
    if (C - L) / max(H - L, 1e-6) < 0.50:
        return None
    if statistics.median(x["close"] * x["volume"] for x in prior) < LIQ_PKR:
        return None
    return {"ratio": ratio, "chg": chg, "t0_chg_pct": (C / pc - 1) * 100.0,
            "strict": chg <= 0.01, "atr": atr[i]}


# ---------------------------------------------------------------- View B simulation
def sim(bars, e, E, S, T, hold):
    """Walk sessions e.. (day 1 = e). Returns (reason, exit_px, day) or ('CENSORED', None, None)."""
    n = len(bars)
    for j in range(e, e + hold):
        if j >= n:
            return "CENSORED", None, None
        b = bars[j]
        pc = bars[j - 1]["close"]
        upl = is_upper_lock(b, pc)
        stop_hit = b["low"] <= S
        tgt_hit = T is not None and (not upl) and (b["open"] >= T or b["high"] >= T)
        # same-bar conflict: stop first unless the open is already through the target
        if tgt_hit and not (stop_hit and b["open"] < T):
            px = b["open"] if b["open"] >= T else T
            return "TARGET", px, j - e + 1
        if stop_hit:
            if A.locked_down(b, pc):  # lower-circuit lock: stop cannot fill, defer
                k = A.fill_exit(bars, j)
                if k >= n:
                    return "CENSORED", None, None
                return "STOP", bars[k]["open"], k - e + 1
            px = b["open"] if b["open"] < S else S
            return "STOP", px, j - e + 1
        if j == e + hold - 1:
            return "TIME", b["close"], hold
    return "CENSORED", None, None


# ---------------------------------------------------------------- per-symbol scan
def scan_symbol(sym, bars):
    atr = atr14_series(bars)
    rows, dropped_locked, last = [], 0, None
    for i in range(len(bars)):
        q = qualifies(bars, atr, i)
        if not q or (last is not None and i <= last + COOLDOWN):
            continue
        last = i  # cooldown anchored to the qualifying candidate
        e = i + 1
        E = bars[e]["open"]
        if E <= 0:
            continue
        if is_upper_lock(bars[e], bars[i]["close"]):
            dropped_locked += 1
            continue
        n = len(bars)
        row = {"symbol": sym, "t0_date": bars[i]["date"], "entry_date": bars[e]["date"],
               "entry_price": E, "rvol": q["ratio"], "bucket": "EXTREME" if q["ratio"] >= 3.0 else "MODERATE",
               "strict": int(q["strict"]), "t0_net_chg_pct": q["t0_chg_pct"], "atr14_t0": q["atr"]}
        # View A
        for w in WINDOWS:
            if e + w - 1 >= n:
                row[f"a{w}_cens"] = 1
                row[f"a{w}_gain"] = row[f"a{w}_dd"] = None
            else:
                seg = bars[e:e + w]
                row[f"a{w}_cens"] = 0
                row[f"a{w}_gain"] = (max(x["high"] for x in seg) / E - 1) * 100.0
                row[f"a{w}_dd"] = (min(x["low"] for x in seg) / E - 1) * 100.0
        # View B
        stop_atr = bars[i]["low"] - 0.5 * q["atr"]
        row["stop_atr"] = stop_atr
        for name, (tmult, hold, floor) in STRATS.items():
            S = max(stop_atr, E * 0.96) if floor else stop_atr
            T = E * tmult if tmult else None
            reason, px, day = sim(bars, e, E, S, T, hold)
            risk = (E - S) / E * 100.0
            if reason == "CENSORED":
                gross = net = R = None
            else:
                gross = (px / E - 1) * 100.0
                net = gross - FRICTION
                R = net / risk if risk > 0 else None
            row[f"{name}_reason"] = reason
            row[f"{name}_cens"] = int(reason == "CENSORED")
            row[f"{name}_days"] = day
            row[f"{name}_stop"] = S
            row[f"{name}_risk_pct"] = risk
            row[f"{name}_gross"] = gross
            row[f"{name}_net"] = net
            row[f"{name}_R"] = R
        rows.append(row)
    return rows, dropped_locked


# ---------------------------------------------------------------- aggregation / printing
def fmt(x, nd=2):
    if x is None:
        return "-"
    return f"{x:.{nd}f}"


def pct(k, n):
    return 100.0 * k / n if n else 0.0


def table1_block(rows, label):
    groups = [
        ("All Signals", lambda r: True),
        ("RVOL 2.0-2.99x", lambda r: r["rvol"] < 3.0),
        ("RVOL >= 3.0x", lambda r: r["rvol"] >= 3.0),
        ("Strict <= 1.0% chg", lambda r: r["strict"] == 1),
    ]
    out = [f"Table 1 -- Forward Bounce Hit Rates [{label}] (liquid, fillable)",
           f"{'Group':<20}{'Win':>4}{'N':>6}{'>=+5%':>8}{'>=+8%':>8}{'>=+10%':>8}{'>=+15%':>8}"
           f"{'MedMaxGain%':>13}{'MedMaxDD%':>11}"]
    for gname, f in groups:
        sub = [r for r in rows if f(r)]
        for w in WINDOWS:
            ok = [r for r in sub if not r[f"a{w}_cens"]]
            g = [r[f"a{w}_gain"] for r in ok]
            d = [r[f"a{w}_dd"] for r in ok]
            hits = [pct(sum(1 for x in g if x >= t), len(ok)) for t in THRESH]
            out.append(f"{gname:<20}{str(w)+'d':>4}{len(ok):>6}" + "".join(f"{h:>7.1f}%" for h in hits)
                       + (f"{statistics.median(g):>12.2f}%{statistics.median(d):>10.2f}%" if ok else f"{'-':>13}{'-':>11}"))
    return out


def table2_block(rows, label):
    out = [f"Table 2 -- Tradable exits, net of 0.45% [{label}, All signals]",
           f"{'Strategy':<26}{'Trades':>7}{'Target%':>9}{'Stop%':>8}{'Time%':>8}{'NetWin%':>9}"
           f"{'ExpR':>8}{'AvgNet%':>9}{'RowsR':>7}{'Cens':>6}"]
    desc = {"S1": "S1 T+6% / stop / 10d", "S2": "S2 T+8% / stop / 15d", "S3": "S3 stop_ATR / time 10d"}
    for name in STRATS:
        ok = [r for r in rows if not r[f"{name}_cens"]]
        cens = len(rows) - len(ok)
        n = len(ok)
        reasons = [r[f"{name}_reason"] for r in ok]
        tgt = sum(1 for x in reasons if x == "TARGET")
        stp = sum(1 for x in reasons if x == "STOP")
        tim = sum(1 for x in reasons if x == "TIME")
        nets = [r[f"{name}_net"] for r in ok]
        Rs = [r[f"{name}_R"] for r in ok if r[f"{name}_R"] is not None]
        out.append(f"{desc[name]:<26}{n:>7}{pct(tgt, n):>8.1f}%{pct(stp, n):>7.1f}%{pct(tim, n):>7.1f}%"
                   f"{pct(sum(1 for x in nets if x > 0), n):>8.1f}%"
                   f"{(statistics.mean(Rs) if Rs else float('nan')):>8.3f}"
                   f"{(statistics.mean(nets) if nets else float('nan')):>9.2f}{len(Rs):>7}{cens:>6}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local-db", default=None)
    ap.add_argument("--out-dir", default=str(ROOT / "out"))
    ap.add_argument("--symbols", default=None, help="optional comma list overriding the universe (testing)")
    a = ap.parse_args(argv)
    if not a.local_db and not (os.getenv("LIBSQL_URL") or os.getenv("TURSO_DATABASE_URL")):
        sys.exit("No data source: pass --local-db PATH or set LIBSQL_URL")

    raw, src = A.open_db(SimpleNamespace(local_db=a.local_db, host=None))  # address not printed
    db = Y.GuardDB(raw)
    if TABLE not in A.table_names(db):
        sys.exit(f"{TABLE} not found in data source")
    universe = ([s.strip().upper() for s in a.symbols.split(",") if s.strip()] if a.symbols
                else Y.load_universe())
    universe = list(dict.fromkeys(universe))

    print("[turso usage] read-only audit: SELECT/PRAGMA only, rows written: 0 (GuardDB refuses all other statements)")
    print(f"Data source: {src}")
    print(f"Universe: {len(universe)} symbols | window {START}..{END} | T0 YTD from {YTD_START}")

    all_rows, skipped, dropped_total = [], [], 0
    for sym in universe:
        raw_rows = db.query(f"SELECT trade_date, open, high, low, close, volume FROM {TABLE} "
                            "WHERE symbol = ? AND trade_date >= ? AND trade_date <= ? ORDER BY trade_date",
                            (sym, START, END))
        bars = A.D.as_bars(raw_rows)
        if len(bars) < MIN_BARS:
            skipped.append(f"{sym}({len(bars)})")
            continue
        rows, dropped = scan_symbol(sym, bars)
        dropped_total += dropped
        all_rows.extend(rows)

    # ---- outputs
    od = Path(a.out_dir)
    od.mkdir(parents=True, exist_ok=True)
    cols = list(all_rows[0].keys()) if all_rows else ["symbol"]
    with open(od / OUT_CSV, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        for r in all_rows:
            wr.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})

    ytd = [r for r in all_rows if r["t0_date"] >= YTD_START]
    cens_a = {w: sum(r[f"a{w}_cens"] for r in all_rows) for w in WINDOWS}
    cens_b = {s: sum(r[f"{s}_cens"] for r in all_rows) for s in STRATS}
    ytd_cens_a = {w: sum(r[f"a{w}_cens"] for r in ytd) for w in WINDOWS}
    ytd_cens_b = {s: sum(r[f"{s}_cens"] for r in ytd) for s in STRATS}
    n_moderate = sum(1 for r in all_rows if r["bucket"] == "MODERATE")
    n_extreme = len(all_rows) - n_moderate

    W = []
    W.append("STOPPING-VOLUME / ABSORPTION-IN-DOWNTREND AUDIT (read-only)")
    W.append(f"[turso usage] read-only audit: SELECT/PRAGMA only; rows written: 0")
    W.append(f"Signals (liquid, fillable): {len(all_rows)} total | MODERATE {n_moderate} | EXTREME {n_extreme} "
             f"| STRICT {sum(r['strict'] for r in all_rows)} | 2026 YTD {len(ytd)}")
    W.append(f"Dropped (entry session upper-circuit lock): {dropped_total}")
    W.append("")
    W += table1_block(all_rows, "MULTIYEAR 2021-09..2026-11")
    W.append("")
    W += table1_block(ytd, "2026_YTD 2026-01-01..2026-11-24")
    W.append("")
    W += table2_block(all_rows, "MULTIYEAR")
    W.append("")
    W += table2_block(ytd, "2026_YTD")
    W.append("")
    recent = [r for r in all_rows if r["t0_date"] >= SIG_2025 and not r["S2_cens"]]
    recent.sort(key=lambda r: r["S2_net"], reverse=True)
    W.append("Table 3 -- Top 15 recent examples (signals 2025-01-01..2026-11-24, sorted by S2 net desc)")
    W.append(f"{'Symbol':<9}{'Signal':>12}{'RVOL':>7}{'T0Chg%':>8}{'Entry':>10}{'10DMaxG%':>10}{'20DMaxG%':>10}{'S2Net%':>9}")
    for r in recent[:15]:
        g10 = "cens" if r["a10_cens"] else fmt(r["a10_gain"])
        g20 = "cens" if r["a20_cens"] else fmt(r["a20_gain"])
        W.append(f"{r['symbol']:<9}{r['t0_date']:>12}{r['rvol']:>7.2f}{r['t0_net_chg_pct']:>8.2f}"
                 f"{r['entry_price']:>10.2f}{g10:>10}{g20:>10}{r['S2_net']:>9.2f}")
    W.append("")
    W.append("ASSUMPTIONS")
    W.append(f"- Universe: fire_config.yaml stocks.universe, {len(universe)} symbols, no exclusions.")
    W.append(f"- Skipped (<{MIN_BARS} bars in {START}..{END}): " + (", ".join(skipped) if skipped else "none"))
    W.append("- Warm-up: indicators need 50 sessions of history inside the loaded window, so the first signals "
             "appear late 2021; no pre-2021-09 data is loaded.")
    W.append("- Stop: S = max(STOP_ATR, 0.96*E) for S1/S2 (tighter of the two); S3 uses STOP_ATR only, no floor.")
    W.append("- Dedupe: a qualifying candidate starts a 10-session cooldown (T0+1..T0+10 ignored) per symbol; "
             "the cooldown applies before the entry-lock check, so a locked-entry candidate still starts it.")
    W.append("- Lock handling: entry-session upper lock (O==H==L at A.upper_lock(Close T0)) drops the signal; "
             "in trades, an upper-locked bar cannot fill a target (hold); lower-locked stop defers via "
             "A.fill_exit to the next session whose Low is above the lower lock, at that Open.")
    W.append("- Same-bar target & stop: stop first unless Open >= target. Gap-through target fills at Open.")
    W.append("- Net % = gross % - 0.45. Net R = net% / risk%, risk% = (E-S)/E*100; R omitted when risk <= 0.")
    W.append("- Censoring: View A windows and View B strategies without enough forward sessions are flagged and "
             "excluded from that window's statistics. View B censored trades are excluded from Table 2 rows.")
    W.append("- Censored counts (all signals) View A: " + ", ".join(f"{w}d={cens_a[w]}" for w in WINDOWS)
             + " | View B: " + ", ".join(f"{s}={cens_b[s]}" for s in STRATS))
    W.append("- Censored counts (2026 YTD) View A: " + ", ".join(f"{w}d={ytd_cens_a[w]}" for w in WINDOWS)
             + " | View B: " + ", ".join(f"{s}={ytd_cens_b[s]}" for s in STRATS))
    W.append("")
    W.append("EXISTING-LOGIC COMPARISON (step 1)")
    W.append("- fire_engine/wyckoff_detector.py:187-198: absorption_active = Volume >= 2.0x volume_sma_20 AND "
             "(spread/ATR <= 1.45 OR close-open/ATR <= 0.85), 8-day memory. No down-state gate, no close-location "
             "rule, no net-change cap, no liquidity gate, no cooldown; it feeds a score, not an entry.")
    W.append("- backend/wyckoff_engine.py:52-70 (SC) and :164 (BC): vol >= 1.6x, spread >= 1.2x, red/green bar, close "
             "in bottom/top 40% of range, scored by lowest-low rank. Different thresholds and a window-level "
             "pick of one event, not per-bar signals.")
    W.append("- fire_engine/absorption.py detect_bullish/bearish_absorption: relative volume, displacement cap, "
             "support-holding and MFI trend. Different inputs; no SMA/30D-high down-state, no 2%/1% net-change rule.")
    W.append("- Conclusion: nothing matches these rules; this audit is a new standalone function. It is not reused.")
    report = "\n".join(W) + "\n"
    (od / OUT_RPT).write_text(report)
    print(report)
    print(f"Saved: {od / OUT_CSV} ({len(all_rows)} rows)")
    print(f"Saved: {od / OUT_RPT}")
    print(f"[turso usage] end of run: {db.reads} SELECT/PRAGMA, refused non-reads: {db.writes_refused}, rows written: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
