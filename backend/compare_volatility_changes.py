#!/usr/bin/env python3
"""compare_volatility_changes.py — before/after evidence for the audit fixes
to the Volatility Intelligence Engine, on IDENTICAL data (local snapshot).

BEFORE = previous behaviour: sample-std Bollinger (ddof=1), every symbol in
daily_ohlc, no stale handling. AFTER = population-std Bollinger (ddof=0),
configured universe minus exclusions, stale rows flagged.
Reports: universe changes, latest-session stage/squeeze counts and the
symbols whose stage changed, and the share of ALL historical bars whose
squeeze flag / stage changed. 0 Turso writes.
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd

import turso_db
import volatility_engine as ve

REPORT = Path(__file__).parent.parent / "volatility_change_comparison.md"


def main():
    conn = turso_db.get_connection()
    syms = [r["symbol"] for r in conn.execute("SELECT DISTINCT symbol FROM daily_ohlc").fetchall()]
    data = {}
    for s in syms:
        rows = conn.execute("SELECT trade_date, open, high, low, close, volume FROM daily_ohlc WHERE symbol=? "
                            "ORDER BY trade_date", (s,)).fetchall()
        data[s] = [dict(r) for r in rows][-600:]
    uni, exc = ve.configured_universe()
    old_cfg = ve.cfg_with({"bb_ddof": 1})
    new_cfg = ve.cfg_with({"bb_ddof": 0})
    before, _ = ve.analyze_universe(data, {}, cfg=old_cfg)
    after, _ = ve.analyze_universe(data, {}, cfg=new_cfg, universe=uni, excluded=exc)
    b = {r["symbol"]: r for r in before["rows"]}
    a = {r["symbol"]: r for r in after["rows"]}
    L = ["# Volatility engine — before vs after the audit fixes (identical data)", "",
         f"Session {after['session']}", "",
         "## Universe", "",
         f"- Before: {len(b)} symbols analysed (everything in daily_ohlc).",
         f"- After: {len(a)} analysed = configured {len(uni)} − excluded {len(exc)} {exc} − unavailable "
         f"{[u['symbol'] for u in after['unavailable']]}.",
         f"- Removed from analysis: {sorted(set(b) - set(a))} · added: {sorted(set(a) - set(b))}",
         f"- Stale (newest candle older than {after['session']}): {after['stale_symbols']}", "",
         "## Latest session — stage and squeeze counts (common symbols)", "",
         "| | Before (ddof=1) | After (ddof=0) |", "|---|---|---|"]
    common = sorted(set(a) & set(b))
    for st in range(6):
        L.append(f"| Stage {st} {ve.STAGE_LABELS[st]} | {sum(b[s]['stage'] == st for s in common)} | "
                 f"{sum(a[s]['stage'] == st for s in common)} |")
    L.append(f"| Squeeze ON | {sum(b[s]['squeeze_on'] for s in common)} | {sum(a[s]['squeeze_on'] for s in common)} |")
    ch = [(s, b[s]["stage_detail"], a[s]["stage_detail"]) for s in common if b[s]["stage_detail"] != a[s]["stage_detail"]]
    L += ["", f"Symbols whose stage changed ({len(ch)}):", ""] + [f"- {s}: {x} → {y}" for s, x, y in ch]
    sq = [s for s in common if b[s]["squeeze_on"] != a[s]["squeeze_on"]]
    L += ["", f"Symbols whose squeeze flag changed ({len(sq)}): {sq}", ""]
    # full history, every bar
    tot = sq_ch = st_ch = 0
    trans = Counter()
    for s in common:
        df = pd.DataFrame(data[s])
        d0, d1 = ve.compute_frame(df, old_cfg), ve.compute_frame(df, new_cfg)
        c0, c1 = ve.classify_series(d0, old_cfg), ve.classify_series(d1, new_cfg)
        tot += len(d0)
        sq_ch += int((d0["SQZ"] != d1["SQZ"]).sum())
        diff = c0["stage"] != c1["stage"]
        st_ch += int(diff.sum())
        trans.update(zip(c0["stage"][diff], c1["stage"][diff]))
    L += ["## All bars in the last 600 sessions (common symbols)", "",
          f"- Bars: {tot:,} · squeeze flag changed on {sq_ch:,} ({100 * sq_ch / tot:.2f}%) · stage changed on "
          f"{st_ch:,} ({100 * st_ch / tot:.2f}%)",
          f"- Most common stage changes (before→after): {trans.most_common(8)}", "",
          "Population std gives ~2.6% narrower bands, so 'BB inside Keltner' is slightly easier to meet."]
    REPORT.write_text("\n".join(L))
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
