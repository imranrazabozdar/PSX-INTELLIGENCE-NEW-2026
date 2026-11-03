#!/usr/bin/env python3
"""verify_session.py — READ-ONLY verification of one session's stored outputs.

Writes nothing to the database (no INSERT/UPDATE/DELETE anywhere in this
file). Reads, all through indexed lookups (~300-450 rows):
  * batch_runs markers
  * wyckoff_scans + wyckoff_accumulation for the session and the previous one
  * analysis_cache 'volatility_engine_scan' and 'volatility_wyckoff_combined'
  * newest daily_ohlc date per configured symbol (LIMIT 1 each)
  * 4-hour bar count per configured symbol for the session (indexed range)
Prints a markdown report (also saved as session_verification.md).

Usage: python verify_session.py --date 2026-11-03 --prev 2026-11-02
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import turso_db
import volatility_engine as ve

REPORT = Path(__file__).parent.parent / "session_verification.md"


def q(c, sql, p=()):
    return [dict(r) for r in c.execute(sql, p).fetchall()]


def wy_rows(c, d):
    rows = q(c, "SELECT symbol, scan_date, accumulation_score, signal_type, bb_width_score, dry_supply_score, "
                "absorption_score, obv_divergence_score, is_consolidating, macd_confirmation, bb_width, "
                "consolidation_pct, current_price, components FROM wyckoff_accumulation WHERE scan_date=?", (d,))
    for r in rows:
        try:
            r["components"] = json.loads(r["components"] or "{}")
        except Exception:
            r["components"] = {}
    return {r["symbol"]: r for r in rows}


def cache(c, key):
    r = q(c, "SELECT run_at, result_json FROM analysis_cache WHERE cache_key=?", (key,))
    if not r:
        return None, None
    return r[0]["run_at"], json.loads(r[0]["result_json"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--prev", required=True)
    a = ap.parse_args()
    D, P = a.date, a.prev
    c = turso_db.get_connection()
    uni, exc = ve.configured_universe()
    active = [s for s in uni if s not in set(exc)]
    L = [f"# Read-only session verification — {D} (previous {P})", ""]

    # ---- markers
    try:
        mk = q(c, "SELECT job, session_date, status, finished_at, detail FROM batch_runs "
                  "WHERE session_date IN (?, ?) ORDER BY session_date, job", (P, D))
    except Exception as e:
        mk = [{"error": str(e)}]
    L += ["## Batch-guard markers", ""] + [f"- {m}" for m in mk] + [""]

    # ---- freshness (independent of every engine)
    last = {}
    for s in uni:
        r = q(c, "SELECT trade_date, close, volume FROM daily_ohlc WHERE symbol=? ORDER BY trade_date DESC LIMIT 1", (s,))
        last[s] = r[0] if r else None
    fresh = [s for s in active if last[s] and last[s]["trade_date"] == D]
    stale = [(s, last[s]["trade_date"]) for s in active if last[s] and last[s]["trade_date"] != D]
    missing = [s for s in active if not last[s]]
    zero_vol = [s for s in fresh if not last[s]["volume"]]
    L += ["## Daily candle freshness (configured universe minus exclusions)", "",
          f"- Configured {len(uni)}, excluded {len(exc)} {exc}, active {len(active)}",
          f"- Newest candle dated {D}: **{len(fresh)}** · stale: {stale} · no data: {missing}",
          f"- Fresh but zero volume on {D}: {zero_vol}", ""]

    # ---- 4-hour availability
    h4 = {}
    for s in active:
        r = q(c, "SELECT COUNT(*) AS n FROM ohlcv_4h WHERE symbol=? AND datetime >= ? AND datetime < ?",
              (s, f"{D} 00:00:00", f"{D} 23:59:59"))
        h4[s] = r[0]["n"] if r else 0
    no4h = sorted(s for s, n in h4.items() if n == 0)
    L += ["## 4-hour bars for the session", "",
          f"- Bars per symbol: {dict(Counter(h4.values()))} · symbols with NO 4-hour bar for {D}: {no4h}", ""]

    # ---- Wyckoff
    wP, wD = wy_rows(c, P), wy_rows(c, D)
    scans = q(c, "SELECT scan_date, scan_time, stocks_scanned, stocks_with_signal FROM wyckoff_scans "
                 "WHERE scan_date IN (?, ?)", (P, D))
    L += ["## Wyckoff (stored rows)", "", f"- wyckoff_scans: {scans}"]
    for d, w in ((P, wP), (D, wD)):
        cls = Counter(r["signal_type"] for r in w.values())
        comp = Counter(k for r in w.values() for k, v in r["components"].items() if v)
        L.append(f"- {d}: {len(w)} rows · {dict(cls)} · components true: {dict(comp)}")
    dup = len(wD) != len({r["symbol"] for r in wD.values()})
    stale_rows = [(s, last[s]["trade_date"], wD[s]["current_price"], last[s]["close"]) for s in wD
                  if last.get(s) and last[s]["trade_date"] != D]
    zero_bb_with_4h = [s for s, r in wD.items() if not r["bb_width"] and h4.get(s, 0) > 0]
    zero_bb_no_4h = [s for s, r in wD.items() if not r["bb_width"] and h4.get(s, 0) == 0]
    L += [f"- Rows for {D} whose newest daily candle is NOT {D} (stored from stale data): {stale_rows}",
          f"- 4-hour component: bb_width stored as 0 with no 4-hour bars (missing data shown as 0): {zero_bb_no_4h}",
          f"- bb_width 0 although 4-hour bars exist: {zero_bb_with_4h}",
          f"- Duplicate symbols for {D}: {dup}", "",
          "### Classification changes", "",
          "| Symbol | Prev | Today | Prev score | Today score | Components changed | Gates prev→today |",
          "|---|---|---|---|---|---|---|"]
    for s in sorted(set(wP) & set(wD)):
        x, y = wP[s], wD[s]
        if x["signal_type"] == y["signal_type"]:
            continue
        diff = [f"{k}:{'+' if y['components'].get(k) else '−'}" for k in
                ("bb_compression", "supply_exhaustion", "absorption", "obv_divergence")
                if bool(x["components"].get(k)) != bool(y["components"].get(k))]
        gates = (f"consol {x['is_consolidating']}→{y['is_consolidating']}, "
                 f"MACD {x['macd_confirmation']}→{y['macd_confirmation']}")
        L.append(f"| {s} | {x['signal_type']} | {y['signal_type']} | {x['accumulation_score']} | "
                 f"{y['accumulation_score']} | {', '.join(diff) or '—'} | {gates} |")
    L.append("")

    # ---- Volatility
    vr, vol = cache(c, "volatility_engine_scan")
    L += ["## Volatility Intelligence (stored scan)", ""]
    if vol:
        rows = vol.get("rows", [])
        fr = [r for r in rows if not r.get("stale")]
        syms = [r["symbol"] for r in rows]
        dates = Counter(r.get("last_bar_date") for r in rows)
        L += [f"- Saved {vr} · session {vol.get('session')} · rows {len(rows)} (fresh {len(fr)}) · "
              f"duplicate symbols: {len(syms) != len(set(syms))}",
              f"- last_bar_date distribution: {dict(dates)}",
              f"- stale: {vol.get('stale_symbols')} · unavailable: {vol.get('unavailable')} · excluded: {vol.get('excluded')}",
              f"- Bollinger ddof in stored config: {vol.get('config', {}).get('bb_ddof')} · market: {vol.get('market_source')}",
              f"- Rows outside the active universe: {sorted(set(syms) - set(active))}",
              f"- Stage counts (fresh): {dict(sorted(Counter(r['stage_label'] for r in fr).items()))}",
              f"- Compression ≥ 60: {sum((r['compression_score'] or 0) >= 60 for r in fr)} · "
              f"bullish evidence ≥ 60: {sum((r['bull_score'] or 0) >= 60 for r in fr)} · "
              f"bearish evidence ≥ 60: {sum((r['bear_score'] or 0) >= 60 for r in fr)}",
              f"- Bullish expansion score > 0: {sum((r['bull_expansion_score'] or 0) > 0 for r in fr)} · "
              f"bearish expansion score > 0: {sum((r['bear_expansion_score'] or 0) > 0 for r in fr)}",
              f"- Confirmed breakouts: {[r['symbol'] for r in fr if r['stage'] == 4 and r['stage_dir'] > 0]}",
              f"- Confirmed breakdowns: {[r['symbol'] for r in fr if r['stage'] == 4 and r['stage_dir'] < 0]}",
              f"- Alerts stored: {len(vol.get('alerts', []))} · baseline session: "
              f"{(vol.get('alert_baseline') or {}).get('session')} · duplicate alert symbols: "
              f"{len(vol.get('alerts', [])) != len({x['symbol'] for x in vol.get('alerts', [])})}", "",
              "Top 10 compression:", ""]
        for r in sorted(fr, key=lambda r: -(r["compression_score"] or 0))[:10]:
            L.append(f"- {r['symbol']}: compression {r['compression_score']} · bull {r['bull_score']} · "
                     f"bear {r['bear_score']} · {r['stage_detail']} · BBW pct {r['bbw_pct100']}")
    else:
        L.append("- No stored volatility scan")
    L.append("")

    # ---- Combined
    cr, comb = cache(c, "volatility_wyckoff_combined")
    L += ["## Wyckoff × Volatility (stored combined view)", ""]
    if comb:
        rows = comb.get("rows", [])
        syms = [r["symbol"] for r in rows]
        recompute = {}
        for r in rows:
            sig = r.get("wyckoff_signal")
            has = sig not in (None, "NO_SIGNAL", "NOT IN WYCKOFF SCAN")
            conf = bool(has and r.get("stage") in (1, 2, 3, 4) and (r.get("stage_dir") or 0) >= 0
                        and (r.get("bull_score") or 0) >= (r.get("bear_score") or 0))
            confl = bool(has and ((r.get("bear_score") or 0) - (r.get("bull_score") or 0) >= 15
                                  or (r.get("stage") in (4, 5) and r.get("stage_dir") == -1)))
            recompute[r["symbol"]] = (conf, confl)
        mism = [s for r in rows for s in [r["symbol"]] if (r.get("confluence"), r.get("conflict")) != recompute[s]]
        wy_mismatch = [r["symbol"] for r in rows if r["symbol"] in wD and r.get("wyckoff_score") != wD[r["symbol"]]["accumulation_score"]]
        L += [f"- Saved {cr} · wyckoff_date {comb.get('wyckoff_date')} · volatility_rows_date {comb.get('volatility_rows_date')}",
              f"- Rows {len(rows)} · duplicates: {len(syms) != len(set(syms))} · "
              f"no Wyckoff row: {[r['symbol'] for r in rows if r.get('wyckoff_signal') == 'NOT IN WYCKOFF SCAN']}",
              f"- Wyckoff symbols missing from the combined view: {sorted(set(wD) - set(syms))}",
              f"- Combined Wyckoff score differs from stored {D} Wyckoff row: {wy_mismatch}",
              f"- Confluence: {sum(r.get('confluence') for r in rows)} {[r['symbol'] for r in rows if r.get('confluence')]}",
              f"- Conflict: {sum(r.get('conflict') for r in rows)} {[r['symbol'] for r in rows if r.get('conflict')]}",
              f"- Confluence/conflict flags that disagree with an independent recomputation: {mism}",
              f"- Stale rows in combined view: {[r['symbol'] for r in rows if r.get('stale')]}"]
    else:
        L.append("- No stored combined view")
    REPORT.write_text("\n".join(L))
    print("\n".join(L))
    if hasattr(turso_db, "print_usage_report"):
        turso_db.print_usage_report(label="verify_session.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
