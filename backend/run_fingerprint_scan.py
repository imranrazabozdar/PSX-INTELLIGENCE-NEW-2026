#!/usr/bin/env python3
"""Out-of-sample scan for two pre-specified pre-move fingerprints
(extracted from SHFA and FNEL in analysis/AICL_SHFA_premove_study.md)
against the full PSX universe cached in Turso's daily_ohlc table.

Reuses analysis/analyze_premove.py's indicator computation (analyze())
directly -- MFI, RSI, ATR, OBV, vol_ratio are NOT reimplemented here.

Runs in GitHub Actions (same Turso-secrets pattern as the other
run_*_backtest.py scripts in this repo: LIBSQL_URL / LIBSQL_AUTH_TOKEN).
Prints results as a single JSON blob between ===JSON_START===/
===JSON_END=== markers, same data-transport convention used by
analysis/fetch_premove_data.py for this session's own sandbox, which
cannot reach Turso directly either.

Thresholds are pre-specified (see FINGERPRINT_1/2 docstrings below) and
are NOT tuned after seeing results -- this is a genuine out-of-sample
test, not curve-fitting.
"""
import json
import sys
import statistics
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
_ANALYSIS_DIR = str(Path(__file__).parent.parent / "analysis")
if _ANALYSIS_DIR not in sys.path:
    sys.path.insert(0, _ANALYSIS_DIR)

import turso_db
from analyze_premove import analyze

MIN_BARS = 120  # need real 90-day ATR-median history plus warmup

# Exclusion windows: SHFA's and FNEL's own documented pre-move report
# windows (analysis/AICL_SHFA_premove_study.md) -- any match for these
# two symbols whose trigger day falls inside these windows is the
# source case itself, not out-of-sample evidence, and is excluded.
EXCLUDE_WINDOWS = {
    "SHFA": ("2026-05-28", "2026-06-18"),
    "FNEL": ("2026-03-22", "2026-04-24"),
}

FP2_MAX_LOOKAHEAD = 60  # trading days after a breakout to search for a second build
FP2_SPAN_LENGTHS = (3, 4, 5)


def load_universe():
    conn = turso_db.get_connection()
    rows = conn.execute("SELECT DISTINCT symbol FROM daily_ohlc").fetchall()
    symbols = [r["symbol"] if isinstance(r, dict) else r[0] for r in rows]
    universe = {}
    for sym in symbols:
        recs = conn.execute(
            "SELECT trade_date, open, high, low, close, volume FROM daily_ohlc "
            "WHERE symbol = ? ORDER BY trade_date ASC", (sym,)
        ).fetchall()
        if len(recs) < MIN_BARS:
            continue
        bars = []
        for r in recs:
            if isinstance(r, dict):
                d, o, h, l, c, v = r["trade_date"], r["open"], r["high"], r["low"], r["close"], r["volume"]
            else:
                d, o, h, l, c, v = r
            if None in (o, h, l, c, v):
                continue
            bars.append({"date": d, "open": float(o), "high": float(h), "low": float(l),
                         "close": float(c), "volume": float(v)})
        if len(bars) >= MIN_BARS:
            universe[sym] = bars
    return universe


def rolling_median(values, period):
    out = [None] * len(values)
    for i in range(len(values)):
        if i + 1 < period:
            continue
        window = [v for v in values[i + 1 - period:i + 1] if v is not None]
        if window:
            out[i] = statistics.median(window)
    return out


def pct_change(closes, i, lookback):
    if i - lookback < 0 or closes[i - lookback] == 0:
        return None
    return (closes[i] - closes[i - lookback]) / closes[i - lookback]


def excluded(sym, date):
    win = EXCLUDE_WINDOWS.get(sym)
    if not win:
        return False
    return win[0] <= date <= win[1]


def forward_returns(closes, i):
    out = {}
    for h in (5, 10, 20):
        j = i + h
        out[f"fwd_{h}d"] = (closes[j] - closes[i]) / closes[i] if j < len(closes) and closes[i] else None
    return out


def breakout_within(rows, i, horizon=15):
    for j in range(i + 1, min(i + 1 + horizon, len(rows))):
        if rows[j]["vol_ratio"] is not None and rows[j]["vol_ratio"] >= 2.5 and rows[j]["close"] > rows[j]["open"]:
            return True, rows[j]["date"]
    return False, None


def scan_fingerprint_1(sym, rows):
    """SHFA-style MFI-deep-oversold base:
    - MFI(14) <= 25 on >= 2 days within any 10-trading-day window
    - RSI(14) >= 40 on those same days (RSI-MFI gap >= 15)
    - ATR(14) on those days below its own trailing 90-day median
    - price NOT already down > 10% over the preceding 20 trading days
    Non-overlapping: after a match, no new match is started until the
    index has advanced past the triggering 10-day window, so one
    oversold base is not counted many times over."""
    n = len(rows)
    closes = [r["close"] for r in rows]
    atr = [r["atr_14"] for r in rows]
    atr_median90 = rolling_median(atr, 90)

    qualifying = [i for i in range(n)
                  if rows[i]["mfi_14"] is not None and rows[i]["mfi_14"] <= 25
                  and rows[i]["rsi_14"] is not None and rows[i]["rsi_14"] >= 40]

    matches = []
    last_taken_upto = -1
    for idx, i in enumerate(qualifying):
        if i <= last_taken_upto:
            continue
        # look for an earlier qualifying day within the last 9 trading days
        prior = [j for j in qualifying if j < i and i - j <= 9]
        if not prior:
            continue
        if atr[i] is None or atr_median90[i] is None or atr[i] >= atr_median90[i]:
            continue
        chg20 = pct_change(closes, i, 20)
        if chg20 is None or chg20 <= -0.10:
            continue
        if excluded(sym, rows[i]["date"]):
            continue
        j = prior[-1]
        bo, bo_date = breakout_within(rows, i)
        fr = forward_returns(closes, i)
        matches.append({
            "fingerprint": 1, "symbol": sym,
            "match_date_range": [rows[j]["date"], rows[i]["date"]],
            "trigger_date": rows[i]["date"],
            "mfi_14": rows[i]["mfi_14"], "rsi_14": rows[i]["rsi_14"],
            "prior_qualifying_date": rows[j]["date"], "prior_mfi_14": rows[j]["mfi_14"],
            "atr_14": atr[i], "atr_90d_median": atr_median90[i],
            "price_chg_20d_pre": chg20,
            "breakout_within_15d": bo, "breakout_date": bo_date,
            **fr,
        })
        last_taken_upto = i + 9

    return matches


def scan_fingerprint_2(sym, rows):
    """FNEL-style OBV/MFI quiet build AFTER an already-completed breakout:
    - OBV rises over a 3-5 trading day span by more than 1.5x the
      stock's own 20-day average daily volume (measured at span start)
    - price flat or up less than 5% over that same span
    - MFI(14) rises from below 50 to above 70 over that same span
    - must occur after a prior volume-confirmed breakout (vol>=2.5x
      20-day avg + up day), searched within a 60-trading-day lookahead"""
    n = len(rows)
    closes = [r["close"] for r in rows]

    breakout_days = [i for i in range(n)
                      if rows[i]["vol_ratio"] is not None and rows[i]["vol_ratio"] >= 2.5
                      and rows[i]["close"] > rows[i]["open"]]

    matches = []
    for b in breakout_days:
        s = b + 1
        limit = min(b + 1 + FP2_MAX_LOOKAHEAD, n)
        while s < limit:
            found = False
            for span in FP2_SPAN_LENGTHS:
                e = s + span - 1
                if e >= n or e >= limit:
                    continue
                vol_avg20 = rows[s]["vol_20d_avg"]
                if not vol_avg20:
                    continue
                obv_delta = rows[e]["obv"] - rows[s]["obv"]
                if obv_delta <= 1.5 * vol_avg20:
                    continue
                price_chg = (closes[e] - closes[s]) / closes[s] if closes[s] else None
                if price_chg is None or not (-0.02 <= price_chg < 0.05):
                    continue
                mfi_s, mfi_e = rows[s]["mfi_14"], rows[e]["mfi_14"]
                if mfi_s is None or mfi_e is None or not (mfi_s < 50 and mfi_e > 70):
                    continue
                if excluded(sym, rows[e]["date"]):
                    s = e + 1
                    found = True
                    break
                bo, bo_date = breakout_within(rows, e)
                fr = forward_returns(closes, e)
                matches.append({
                    "fingerprint": 2, "symbol": sym,
                    "prior_breakout_date": rows[b]["date"], "prior_breakout_vol_ratio": rows[b]["vol_ratio"],
                    "match_date_range": [rows[s]["date"], rows[e]["date"]],
                    "trigger_date": rows[e]["date"],
                    "obv_delta": obv_delta, "vol_20d_avg_at_start": vol_avg20,
                    "obv_delta_vs_vol20davg_ratio": obv_delta / vol_avg20,
                    "price_chg_over_span": price_chg,
                    "mfi_start": mfi_s, "mfi_end": mfi_e,
                    "breakout_within_15d": bo, "breakout_date": bo_date,
                    **fr,
                })
                s = e + 1
                found = True
                break
            if not found:
                s += 1
    return matches


def baseline_win_rate_10d(all_rows_by_symbol):
    """Freshly computed from the SAME universe/timeframe as this scan,
    same methodology as backend/indicator_backtester.py's BASELINE row:
    % of ANY eligible bar (enough forward history) with positive
    forward-10-trading-day close-to-close return."""
    total, positive = 0, 0
    for sym, rows in all_rows_by_symbol.items():
        closes = [r["close"] for r in rows]
        n = len(closes)
        for i in range(n - 10):
            if closes[i]:
                total += 1
                if closes[i + 10] > closes[i]:
                    positive += 1
    return {"n_eligible_bars": total, "win_rate_10d_pct": (positive / total * 100) if total else None}


def wilson_interval(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)) / denom
    return {"low_pct": (center - half) * 100, "high_pct": (center + half) * 100, "point_pct": p * 100}


def main():
    db_status = turso_db.status()
    print(f"Database backend: {db_status}", file=sys.stderr)
    if db_status.get("on_local_fallback"):
        print("ERROR: on local Turso fallback, daily_ohlc would be empty. Aborting.", file=sys.stderr)
        sys.exit(1)

    print("Loading full universe from Turso daily_ohlc ...", file=sys.stderr)
    universe = load_universe()
    print(f"Universe: {len(universe)} symbols with >= {MIN_BARS} bars", file=sys.stderr)

    all_rows = {}
    fp1_matches, fp2_matches = [], []
    for i, (sym, bars) in enumerate(universe.items()):
        rows = analyze(sym, bars)
        all_rows[sym] = rows
        fp1_matches.extend(scan_fingerprint_1(sym, rows))
        fp2_matches.extend(scan_fingerprint_2(sym, rows))
        if (i + 1) % 50 == 0:
            print(f"  processed {i + 1}/{len(universe)} symbols "
                  f"(fp1={len(fp1_matches)}, fp2={len(fp2_matches)} so far)", file=sys.stderr)

    print(f"Scan complete: {len(fp1_matches)} fingerprint-1 matches, "
          f"{len(fp2_matches)} fingerprint-2 matches", file=sys.stderr)

    baseline = baseline_win_rate_10d(all_rows)

    def summarize(matches):
        out = {"n_matches": len(matches)}
        for h in (5, 10, 20):
            vals = [m[f"fwd_{h}d"] for m in matches if m.get(f"fwd_{h}d") is not None]
            if vals:
                wins = sum(1 for v in vals if v > 0)
                out[f"h{h}d"] = {
                    "n": len(vals), "mean_pct": statistics.mean(vals) * 100,
                    "median_pct": statistics.median(vals) * 100,
                    "win_rate_pct": wins / len(vals) * 100,
                }
                if h == 10:
                    out[f"h{h}d"]["wilson_95ci"] = wilson_interval(wins, len(vals))
            else:
                out[f"h{h}d"] = None
        n_bo = sum(1 for m in matches if m.get("breakout_within_15d"))
        out["breakout_within_15d_pct"] = (n_bo / len(matches) * 100) if matches else None
        return out

    output = {
        "universe_symbol_count": len(universe),
        "min_bars_required": MIN_BARS,
        "baseline_win_rate_10d_freshly_computed": baseline,
        "baseline_win_rate_10d_cited": 44.55,
        "fingerprint_1": {"definition": "SHFA-style MFI-deep-oversold base",
                           "summary": summarize(fp1_matches), "matches": fp1_matches},
        "fingerprint_2": {"definition": "FNEL-style OBV/MFI quiet build after a breakout",
                           "summary": summarize(fp2_matches), "matches": fp2_matches},
    }

    print("===JSON_START===")
    print(json.dumps(output, indent=2, default=str))
    print("===JSON_END===")


if __name__ == "__main__":
    main()
