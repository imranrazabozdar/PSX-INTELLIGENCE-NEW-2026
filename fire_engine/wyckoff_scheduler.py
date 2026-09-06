"""wyckoff_scheduler.py — Phase 6: daily batch orchestration for the
Wyckoff Institutional Stealth Accumulation Detector.

Runs after the FIRE Engine's own daily batch (same GitHub Actions job,
see .github/workflows/fire_engine_daily_batch.yml), against the same
89-symbol universe and the same exclusion filter -- deliberately reusing
`cfg["stocks"]["universe"]` rather than a second, parallel stock list, so
the two scanners can never drift out of sync with each other.

No new API endpoint or "trigger a refresh" step here (per the prompt's
own "do NOT add new API endpoints" rule): this just writes into
wyckoff_accumulation in the same shared Turso DB backend/app.py already
reads from, the same way fire_engine/scheduler.py's FIRE batch does --
the next /patterns/wyckoff-scan request picks up new rows on its own.
"""
from datetime import datetime, timedelta

from fire_engine.exclusions import filter_excluded_stocks, load_exclusions_from_config
from fire_engine.wyckoff_data_fetcher import fetch_daily_and_4h
from fire_engine.wyckoff_detector import WyckoffDetector

MIN_DAILY_BARS = 30  # below this, the 20-day consolidation/SMA windows are too thin to trust


def _get_or_create_scan(db, scan_date: str) -> int:
    db.conn.execute(
        "INSERT INTO wyckoff_scans (scan_date, scan_time, stocks_scanned, stocks_with_signal) "
        "VALUES (?, ?, 0, 0) ON CONFLICT(scan_date) DO UPDATE SET scan_time=excluded.scan_time",
        (scan_date, datetime.now().strftime("%H:%M:%S")),
    )
    db.conn.commit()
    row = db.conn.execute("SELECT id FROM wyckoff_scans WHERE scan_date = ?", (scan_date,)).fetchone()
    return row["id"]


def _store_result(db, scan_id: int, prepared: dict) -> None:
    db.ensure_stock(prepared["symbol"])
    db.conn.execute(
        """INSERT INTO wyckoff_accumulation
           (scan_id, symbol, scan_date, accumulation_score, signal_type,
            bb_width_score, dry_supply_score, absorption_score, obv_divergence_score,
            is_consolidating, macd_confirmation, bb_width, obv_slope, price_slope,
            consolidation_pct, consolidation_atr, spread_atr_ratio, co_atr_ratio,
            volume_sma_20, atr_14, current_price, current_volume, components)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(scan_date, symbol) DO UPDATE SET
             scan_id=excluded.scan_id, accumulation_score=excluded.accumulation_score,
             signal_type=excluded.signal_type, bb_width_score=excluded.bb_width_score,
             dry_supply_score=excluded.dry_supply_score, absorption_score=excluded.absorption_score,
             obv_divergence_score=excluded.obv_divergence_score,
             is_consolidating=excluded.is_consolidating, macd_confirmation=excluded.macd_confirmation,
             bb_width=excluded.bb_width, obv_slope=excluded.obv_slope, price_slope=excluded.price_slope,
             consolidation_pct=excluded.consolidation_pct, consolidation_atr=excluded.consolidation_atr,
             spread_atr_ratio=excluded.spread_atr_ratio, co_atr_ratio=excluded.co_atr_ratio,
             volume_sma_20=excluded.volume_sma_20, atr_14=excluded.atr_14,
             current_price=excluded.current_price, current_volume=excluded.current_volume,
             components=excluded.components""",
        (scan_id, prepared["symbol"], prepared["scan_date"], prepared["accumulation_score"],
         prepared["signal_type"], prepared["bb_width_score"], prepared["dry_supply_score"],
         prepared["absorption_score"], prepared["obv_divergence_score"],
         int(prepared["is_consolidating"]), int(prepared["macd_confirmation"]),
         prepared["bb_width"], prepared["obv_slope"], prepared["price_slope"],
         prepared["consolidation_pct"], prepared["consolidation_atr"], prepared["spread_atr_ratio"],
         prepared["co_atr_ratio"], prepared["volume_sma_20"], prepared["atr_14"],
         prepared["current_price"], prepared["current_volume"], prepared["components"]),
    )
    db.conn.commit()


def run_symbol_wyckoff(db, symbol: str, scan_id: int, scan_date: str, detector: WyckoffDetector) -> dict:
    """Fetch + detect + store for one symbol. Returns the prepared dict,
    or None if there isn't enough daily history yet to compute anything
    meaningful (a new/thinly-traded listing) -- never a fabricated score."""
    df_daily, df_4h = fetch_daily_and_4h(db, symbol, end_date=scan_date)
    if len(df_daily) < MIN_DAILY_BARS:
        return None

    result = detector.detect_stealth_accumulation(df_daily, df_4h)
    prepared = detector.prepare_for_db_and_ui(result, symbol, scan_date)
    _store_result(db, scan_id, prepared)
    return prepared


def _default_progress(msg):
    print(msg, flush=True)


def run_daily_wyckoff_batch(db, cfg: dict, date: str = None, progress=_default_progress) -> dict:
    """Entry point: run every non-excluded configured symbol for `date`
    (defaults to yesterday, matching fire_engine.scheduler's own default).
    Returns {date, scan_id, results: [prepared dicts], stocks_with_signal}."""
    if date is None:
        date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    universe = cfg["stocks"]["universe"]
    if cfg["exclusion"]["enabled"]:
        excluded = load_exclusions_from_config()
        universe = filter_excluded_stocks(universe, excluded)

    detector = WyckoffDetector(cfg)
    scan_id = _get_or_create_scan(db, date)

    results = []
    signals = 0
    for i, symbol in enumerate(universe, 1):
        try:
            prepared = run_symbol_wyckoff(db, symbol, scan_id, date, detector)
        except Exception as exc:
            progress(f"[{i}/{len(universe)}] {symbol}: ERROR={exc!r}")
            continue
        if prepared is None:
            progress(f"[{i}/{len(universe)}] {symbol}: insufficient daily history, skipped")
            continue
        results.append(prepared)
        if prepared["signal_type"] != "NO_SIGNAL":
            signals += 1
        progress(f"[{i}/{len(universe)}] {symbol}: score={prepared['accumulation_score']} "
                 f"signal={prepared['signal_type']}")

    db.conn.execute(
        "UPDATE wyckoff_scans SET stocks_scanned=?, stocks_with_signal=? WHERE id=?",
        (len(results), signals, scan_id),
    )
    db.conn.commit()

    return {"date": date, "scan_id": scan_id, "results": results, "stocks_with_signal": signals}
