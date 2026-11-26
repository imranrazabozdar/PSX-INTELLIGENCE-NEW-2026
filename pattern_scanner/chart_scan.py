"""Chart-pattern scan over daily_ohlc (Bulkowski detector) shared by the Streamlit
Chart Patterns tab and the dated PDF report. READ-ONLY: the caller passes a connection
and this module only runs SELECT statements through pattern_scanner.recent_bars."""
import json as _json

import pandas as pd

CP_START = "2021-09-01"


def scan_chart_patterns(conn, root_dir):
    """Returns the same dict the Chart Patterns tab renders. Raises on read failure of the
    daily_ohlc bars; per-source failures of the two confluence joins come back as type names."""
    import os
    import yaml
    from pattern_scanner.bulkowski_detector import scan_universe
    from pattern_scanner.confluence import build_badges, obv_symbols_from_result
    from pattern_scanner.recent_bars import fetch_recent_bars
    with open(os.path.join(root_dir, "fire_engine", "config", "fire_config.yaml"), encoding="utf-8") as _f:
        universe = [str(x).upper() for x in yaml.safe_load(_f)["stocks"]["universe"]]
    by_sym = fetch_recent_bars(conn, universe)   # latest 250 sessions per symbol, ascending
    frames = {}
    for sym, rs in by_sym.items():
        d = pd.DataFrame([{"date": r["trade_date"], "open": r["open"], "high": r["high"],
                           "low": r["low"], "close": r["close"], "volume": r["volume"]} for r in rs])
        for col in ("open", "high", "low", "close", "volume"):
            d[col] = pd.to_numeric(d[col], errors="coerce")
        d = d.dropna(subset=["close", "high", "low", "volume"])
        if len(d):
            frames[sym] = d
    signals, breadth = scan_universe(frames)

    latest = None
    ph_rows, ph_err = [], None
    try:
        r = conn.execute("SELECT MAX(scan_date) AS d FROM phase_d_signals").fetchone()
        latest = r["d"] if r else None
        ph_rows = [dict(x) for x in conn.execute(
            "SELECT symbol, scan_date, signal_type FROM phase_d_signals "
            "WHERE signal_type IN (?, ?, ?) AND scan_date >= ?",
            ("SHELF_BREAKOUT", "SOS_IGNITION", "ACTIVE_SHELF", CP_START)).fetchall()]
    except Exception as _e:
        ph_err = type(_e).__name__
    obv_syms, obv_err = set(), None
    try:
        rows = conn.execute("SELECT result_json FROM analysis_cache WHERE cache_key=?",
                            ("obv_mfi_scan",)).fetchall()
        if rows:
            obv_syms = obv_symbols_from_result(_json.loads(rows[0]["result_json"]))
    except Exception as _e:
        obv_err = type(_e).__name__
    return {"signals": build_badges(signals, ph_rows, obv_syms, latest_session=latest),
            "breadth": breadth, "universe": len(universe), "scanned": len(frames),
            "latest_phase_d": latest, "phase_d_error": ph_err, "obv_error": obv_err,
            "obv_count": len(obv_syms)}
