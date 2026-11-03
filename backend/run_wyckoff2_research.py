#!/usr/bin/env python3
"""run_wyckoff2_research.py — daily RESEARCH / NOT PRODUCTION scan for
Wyckoff Accumulation 2.0. Runs as a separate, continue-on-error step of the
pattern-refresh job, after the production steps.

Reads: daily_ohlc via the job's local snapshot (0 Turso reads), KSE-100 from
the public index API, frozen thresholds from analysis_cache
'wyckoff2_research_stats' (1 read). Writes ONE research row:
analysis_cache 'wyckoff2_research_scan'. Touches no production table,
alert, marker or engine.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pandas as pd

import turso_db
import volatility_engine as ve
import wyckoff2_research as w2


def _market():
    try:
        import psx_live
        rows = psx_live.index_history("KSE100", limit=400)
        if rows:
            return pd.Series({pd.to_datetime(r["timestamp"], unit="ms").normalize(): float(r["close"]) for r in rows}).sort_index(), "KSE-100"
    except Exception as e:
        print(f"KSE-100 unavailable ({type(e).__name__})")
    return None, None


def main():
    t0 = time.time()
    conn = turso_db.get_connection()
    session = os.getenv("PSX_SESSION_DATE")
    uni, exc = ve.configured_universe()
    active = [s for s in uni if s not in set(exc)]
    st = conn.execute("SELECT result_json FROM analysis_cache WHERE cache_key=?", ("wyckoff2_research_stats",)).fetchall()
    stats = json.loads(st[0]["result_json"]) if st else None
    th = (stats or {}).get("thresholds_train_p70") or w2.DEFAULT_THRESHOLDS
    market, msrc = _market()
    data, unavailable = {}, []
    from_scs = os.getenv("W2_SOURCE") == "scs"     # research workflow: SCS directly, 0 Turso reads for prices
    for s in active:
        if from_scs:
            import scs_daily
            from datetime import timedelta
            df = scs_daily.fetch_scs_daily_ohlc(s, start_date=(datetime.now(timezone.utc) - timedelta(days=600)).strftime("%Y-%m-%d"),
                                                end_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            if len(df):
                df = df[(df["low"] <= df[["open", "close"]].min(axis=1)) & (df[["open", "close"]].max(axis=1) <= df["high"])]
            rows = df.to_dict("records") if len(df) else []
            time.sleep(0.2)
        else:            # served by the pattern-refresh job's local daily_ohlc snapshot
            rows = [dict(r) for r in conn.execute("SELECT trade_date, open, high, low, close, volume FROM daily_ohlc "
                                                  "WHERE symbol=? ORDER BY trade_date DESC LIMIT 400", (s,)).fetchall()][::-1]
        if len(rows) < 120:
            unavailable.append({"symbol": s, "reason": f"{len(rows)} daily bars (needs 120)"})
            continue
        data[s] = w2.normalise(pd.DataFrame(rows))
    if market is None:
        rets = pd.DataFrame({s: d["close"].pct_change().where(lambda x: x.abs() <= 0.11) for s, d in data.items()})
        market, msrc = (1 + rets.mean(axis=1).fillna(0)).cumprod(), "equal-weight universe proxy (KSE-100 unavailable)"
    session = session or max(str(d.index[-1].date()) for d in data.values())
    out = []
    for s, d in data.items():
        try:
            f = w2.compute(d, market, thresholds=th)
        except Exception as e:
            unavailable.append({"symbol": s, "reason": f"error {type(e).__name__}"})
            continue
        r = f.iloc[-1]
        row = {k: (None if pd.isna(r[k]) else (round(float(r[k]), 2) if not isinstance(r[k], (bool, str)) else r[k]))
               for k in ("abs_q", "obv_q", "struct_q", "rs_q", "range_hi", "range_lo", "dist_res_pct", "pos_in_base",
                         "atr_contraction", "excess20", "excess60", "down_day_resilience", "hv_days", "div_strength",
                         "close", "chg_pct")}
        row.update({k: bool(r[k]) for k in ("higher_lows", "spring", "extended", "rs_leading", "obv_div",
                                            "near_support", "two_sided")})
        last_date = str(f.index[-1].date())
        stale = last_date != session
        prev = f["enh_class"].iloc[-2] if len(f) > 1 else None
        # signal date = first bar of the current class run
        cls = f["enh_class"].to_numpy()
        i = len(cls) - 1
        while i > 0 and cls[i - 1] == cls[-1]:
            i -= 1
        row.update({"symbol": s, "last_bar_date": last_date, "stale": stale, "actionable": not stale,
                    "enh_class": "STALE DATA — NOT ACTIONABLE" if stale else r["enh_class"],
                    "enh_class_raw": r["enh_class"], "prev_class": prev, "class_since": str(f.index[i].date()),
                    "confirming": int(r["confirming"]), "research_orig_score_daily_only": int(r["orig_score"]),
                    "explain": w2.explain(row, th)})
        out.append(row)
    res = {"status": "ok", "label": "RESEARCH / NOT PRODUCTION", "session": session, "benchmark": msrc,
           "thresholds": th, "thresholds_source": "train-period 70th percentile" if stats else "provisional defaults (backtest not run yet)",
           "universe": len(uni), "excluded": sorted(exc), "unavailable": unavailable,
           "rows": out, "run_at": datetime.now(timezone.utc).isoformat()}
    conn.execute("""INSERT INTO analysis_cache(cache_key, run_at, run_at_epoch, result_json) VALUES(?,?,?,?)
        ON CONFLICT(cache_key) DO UPDATE SET run_at=excluded.run_at, run_at_epoch=excluded.run_at_epoch,
        result_json=excluded.result_json""", ("wyckoff2_research_scan", res["run_at"], time.time(), json.dumps(res, default=str)))
    conn.commit()
    print(f"[wyckoff2] {len(out)} symbols, session {session}, {sum(r['stale'] for r in out)} stale, "
          f"{len(unavailable)} unavailable, classes {pd.Series([r['enh_class'] for r in out]).value_counts().to_dict()} "
          f"in {time.time() - t0:.0f}s")
    turso_db.print_usage_report(label="run_wyckoff2_research.py")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[wyckoff2] research scan failed (production unaffected): {type(e).__name__}: {e}")
        sys.exit(0)
