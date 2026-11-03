"""Deterministic backend payloads for the Patterns-tab UI regression harness.

Shapes come from the real producers: the Volatility payload is built by
backend/volatility_engine.analyze_universe + combine_with_wyckoff, the
Wyckoff 2.0 rows by backend/wyckoff2_research.compute/explain (same field
selection as run_wyckoff2_research.py), on synthetic OHLCV. Pattern-scan hits
use the exact keys streamlit_app.py reads. Nothing here touches a database.
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

SESSION = "2026-11-03"
_names_map = json.load(open(ROOT / "backend" / "symbol_names.json", encoding="utf-8"))["map"]
SYMBOLS = [s for s, v in _names_map.items() if not (v or {}).get("is_debt") and s.isalpha()][:150]


def _d(days_ago):
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _ohlcv(sym, k, n=320):
    rng = np.random.default_rng(k)
    dates = pd.bdate_range(end=SESSION, periods=n)
    price = 20 + (k % 40) * 5.0
    rows = []
    for i, d in enumerate(dates):
        vol = 0.004 if (k % 5 == 0 and i > n - 30) else 0.018
        c = price * (1 + rng.normal(0.0004 * ((k % 3) - 1), vol))
        h, lo = max(price, c) * (1 + abs(rng.normal(0, vol / 2))), min(price, c) * (1 - abs(rng.normal(0, vol / 2)))
        rows.append({"trade_date": d.strftime("%Y-%m-%d"), "open": round(price, 2), "high": round(h, 2),
                     "low": round(lo, 2), "close": round(c, 2), "volume": float(rng.integers(5e4, 3e6))})
        price = c
    if k % 23 == 7:      # stale symbol
        rows = rows[:-1]
    return rows


def _hits(n, seed, extra, date_key="pattern_date", directions=None, recent_only=False):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        sym = SYMBOLS[(seed * 7 + i * 3) % len(SYMBOLS)]
        e = round(float(rng.uniform(10, 400)), 2)
        h = {"symbol": sym, date_key: _d(0 if recent_only else int(rng.integers(0, 40))),
             "entry_price": e, "stop_loss": round(e * 0.95, 2), "target_1": round(e * 1.08, 2)}
        if directions:
            h["direction"] = directions[i % len(directions)]
        h.update(extra(i, rng, h))
        out.append(h)
    return out


def _scan(hits, scanned=212, age=5 * 3600):
    return {"status": "ok", "scanned": scanned, "hits": hits, "_cache_age_seconds": age,
            "_background_refresh_running": False}


def build():
    import volatility_engine as ve
    import wyckoff2_research as w2
    data = {s: _ohlcv(s, k) for k, s in enumerate(SYMBOLS[:120])}
    sectors = {s: (_names_map.get(s) or {}).get("sector") for s in data}
    universe = SYMBOLS[:124]
    vol, _det = ve.analyze_universe(data, sectors, universe=universe, excluded=SYMBOLS[120:122], session=SESSION)
    vol["_cache_age_seconds"] = 4 * 3600

    rng = np.random.default_rng(5)
    wy_rows, wy_hits = [], []
    for k, s in enumerate(SYMBOLS[:120]):
        score = int(rng.choice([20, 40, 60, 65, 70, 80, 90, 100]))
        sig = "EXTREME" if score >= 85 and k % 2 else "READY" if 70 <= score < 85 else "WATCH" if 60 <= score < 70 else "NO_SIGNAL"
        comp = {"bb_compression": bool(k % 2), "supply_exhaustion": bool(k % 3), "absorption": bool(k % 4),
                "obv_divergence": bool(k % 5), "is_consolidating": True, "macd_confirmation": sig != "NO_SIGNAL"}
        r = {"symbol": s, "scan_date": SESSION, "accumulation_score": score, "signal_type": sig,
             "bb_width_score": 20 if comp["bb_compression"] else 0, "dry_supply_score": 20 if comp["supply_exhaustion"] else 0,
             "absorption_score": 30 if comp["absorption"] else 0, "obv_divergence_score": 30 if comp["obv_divergence"] else 0,
             "is_consolidating": 1, "macd_confirmation": int(comp["macd_confirmation"]),
             "current_price": round(float(rng.uniform(10, 300)), 2), "components": json.dumps(comp)}
        wy_rows.append(r)
        if sig != "NO_SIGNAL":
            wy_hits.append(r)
    wy_hits.sort(key=lambda r: -r["accumulation_score"])
    combined = ve.combine_with_wyckoff(dict(vol, _cache_run_at="2026-11-03T12:01:00+00:00"), wy_rows)

    market = None
    rets = pd.DataFrame({s: pd.Series([r["close"] for r in v]).pct_change() for s, v in data.items()})
    w2rows = []
    for s, rows in list(data.items())[:110]:
        d = w2.normalise(pd.DataFrame(rows))
        if market is None:
            market = (1 + rets.mean(axis=1).fillna(0)).cumprod()
            market.index = d.index[-len(market):] if len(d) >= len(market) else market.index
        f = w2.compute(d, None)
        r = f.iloc[-1]
        row = {k: (None if pd.isna(r[k]) else (round(float(r[k]), 2) if not isinstance(r[k], (bool, str)) else r[k]))
               for k in ("abs_q", "obv_q", "struct_q", "rs_q", "range_hi", "range_lo", "dist_res_pct", "pos_in_base",
                         "atr_contraction", "excess20", "excess60", "down_day_resilience", "hv_days", "div_strength",
                         "close", "chg_pct")}
        row.update({k: bool(r[k]) for k in ("higher_lows", "spring", "extended", "rs_leading", "obv_div",
                                            "near_support", "two_sided")})
        last = str(f.index[-1].date())
        stale = last != SESSION
        th = w2.DEFAULT_THRESHOLDS
        row.update({"symbol": s, "last_bar_date": last, "stale": stale, "actionable": not stale,
                    "enh_class": "STALE DATA — NOT ACTIONABLE" if stale else r["enh_class"],
                    "enh_class_raw": r["enh_class"], "prev_class": None, "class_since": _d(3),
                    "confirming": int(r["confirming"]), "research_orig_score_daily_only": int(r["orig_score"]),
                    "explain": w2.explain(row, th)})
        w2rows.append(row)
    w2res = {"status": "ok", "label": "RESEARCH / NOT PRODUCTION", "session": SESSION,
             "benchmark": "equal-weight universe proxy (KSE-100 unavailable)", "thresholds": w2.DEFAULT_THRESHOLDS,
             "thresholds_source": "provisional defaults (backtest not run yet)", "universe": 115,
             "excluded": ["XAAA"], "unavailable": [{"symbol": "XBBB", "reason": "no data"}],
             "rows": w2rows, "run_at": "2026-11-03T16:58:41+00:00"}

    def bull_bear(i, rng, h):
        return {}

    fire_hits = []
    for i in range(37):
        cls = "FIRE" if i % 3 == 0 else "PRE_FIRE"
        fire_hits.append({"symbol": SYMBOLS[i * 2], "event_type": cls, "classification": cls,
                          "fire_score": int(95 - i), "mfi_value": round(40 + i * 1.3, 1),
                          "relative_volume": 0.0 if i == 5 else round(0.4 + (i % 7) * 0.55, 2),
                          "volume_condition": "ABNORMAL_OR_ABOVE" if cls == "FIRE" else ("NORMAL_OR_THIN" if i % 2 else "ELEVATED_OR_ABOVE"),
                          "event_time": f"{11 + i % 5:02d}:{i % 60:02d}:00",
                          "notes": f"rating=STRONG confidence=HIGH" if cls == "FIRE" else None})

    vstats = {"status": "not_run", "reason": "Volatility backtest not run yet."}
    return {
        "/patterns/regime": {"status": "ok", "label": "BEAR", "current": 152340.0, "ma_200": 158000.0},
        "/company-names": {"names": {s: {"name": (v or {}).get("name")} for s, v in _names_map.items()}},
        "/patterns/mharris-scan": _scan(_hits(30, 1, bull_bear, directions=["BULL", "BEAR"])),
        "/patterns/engulfing-star-scan": _scan(_hits(12, 2, bull_bear, directions=["BULL", "BEAR", "BEAR"])),
        "/patterns/macdema-scan": _scan(_hits(18, 3, lambda i, r, h: {"target_1": None} if i % 2 else {},
                                              directions=["BULL", "BEAR"])),
        "/patterns/triangle-regression-scan": _scan(_hits(129, 4, bull_bear)),
        "/patterns/obv-mfi-scan": _scan([{"symbol": SYMBOLS[i + 40], "close": 55.5 + i, "day0_date": _d(10 + i),
                                          "days_since_day0": 7 + i, "pullback_pct": 8.25 + i, "vol_drought_pct": 31.0,
                                          "mfi_now": 48.2, "obv_retention_pct": 94.1, "atr_ratio": 0.0 if i == 1 else 0.81}
                                         for i in range(3)]),
        "/patterns/level-breakout-scan": _scan(_hits(9, 5, lambda i, r, h: {"level_price": round(h["entry_price"] * 0.98, 2)},
                                                     directions=["BULL", "BEAR"])),
        "/patterns/gp-evolved-scan": _scan([{"symbol": SYMBOLS[60 + i], "classification": "BUY" if i % 2 else "SELL",
                                             "desired_pct": (-1) ** i * (20 + i * 7.5),
                                             "test_stats": {"total_return_pct": 4.2 + i, "sharpe": 0.8, "win_rate_pct": 52.0,
                                                            "profit_factor": 1.1}} for i in range(6)], scanned=40),
        "/patterns/gp-evolved-ranking": {"ranked": [1], "symbols_trained": 40, "symbols_skipped": 49},
        "/patterns/fire-scan": dict(_scan(fire_hits, scanned=len(fire_hits), age=6 * 3600), date=SESSION),
        "/patterns/wyckoff-scan": dict(_scan(wy_hits, scanned=len(wy_rows), age=6 * 3600), date=SESSION),
        "/patterns/bullish-engulfing-scan": _scan(_hits(14, 6, lambda i, r, h: {"classification": "VALID" if i % 3 else "GEOMETRY_ONLY"})),
        "/patterns/morning-star-scan": _scan(_hits(4, 7, bull_bear, date_key="date")),
        "/patterns/three-line-strike-scan": _scan([]),
        "/patterns/bearish-engulfing-scan": _scan(_hits(61, 8, lambda i, r, h: {"classification": "VALID" if i % 4 else "FAILED"})),
        "/patterns/evening-star-scan": _scan(_hits(2, 9, bull_bear, date_key="date")),
        "/patterns/advanced-scan": _scan(_hits(5, 10, lambda i, r, h: {"pattern_type": ["INVERSE_HS", "DOUBLE_BOTTOM"][i % 2],
                                                                       "risk_reward_measured": 1.2 + i * 0.3},
                                               date_key="signal_date")),
        "/patterns/hstop-scan": _scan(_hits(2, 11, lambda i, r, h: {"pattern_type": "HEAD_SHOULDERS_TOP",
                                                                    "risk_reward_measured": 0.9}, date_key="signal_date")),
        "/patterns/volatility-engine": vol,
        "/patterns/volatility-engine/stats": vstats,
        "/patterns/volatility-wyckoff": combined,
        "/patterns/wyckoff2-research": w2res,
        "/patterns/wyckoff2-research/stats": {"status": "not_run", "reason": "Wyckoff 2.0 research backtest not run yet."},
    }


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "fixtures.json")
    out.write_text(json.dumps(build(), default=str))
    print(f"wrote {out}")
