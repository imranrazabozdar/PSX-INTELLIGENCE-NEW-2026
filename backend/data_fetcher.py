"""data_fetcher.py — Compatibility shim for the ported V1 modules.

V1's market_regime and backtester expect `fetch_eod(symbol) -> (DataFrame, meta)`
with columns [date, open, high, low, close, volume].

Rather than introduce a SECOND scraper, this delegates to the fetchers app.py
already owns (PSX DPS timeseries, then Yahoo .KA as fallback) and reshapes the
result with legacy_adapter-style normalization. One source of truth for market
data; no duplicated request logic to drift apart.

Honest by design: when neither source returns usable rows, this returns
(None, meta) — which market_regime already handles by reporting regime
"unknown" and failing the gate OPEN rather than fabricating an index level.
"""

import logging

import pandas as pd

log = logging.getLogger("data_fetcher")


def _rows_to_frame(rows):
    """Normalize app.py's history rows into the DataFrame V1 expects."""
    rec = []
    for z in rows or []:
        if isinstance(z, (list, tuple)):
            rec.append({"ts": z[0] if len(z) > 0 else None,
                        "close": z[1] if len(z) > 1 else None,
                        "volume": z[2] if len(z) > 2 else 0,
                        "open": None, "high": None, "low": None})
        else:
            close = z.get("close", z.get("price"))
            rec.append({"ts": z.get("time", z.get("timestamp")),
                        "close": close,
                        "open": z.get("open", close),
                        "high": z.get("high", close),
                        "low": z.get("low", close),
                        "volume": z.get("volume", 0) or 0})
    df = pd.DataFrame(rec)
    if not len(df):
        return df
    # app.py emits epoch MILLIseconds; fall back to seconds if that looks wrong.
    df["date"] = pd.to_datetime(df["ts"], unit="ms", errors="coerce")
    if df["date"].isna().all():
        df["date"] = pd.to_datetime(df["ts"], unit="s", errors="coerce")
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0]
    return df.sort_values("date").reset_index(drop=True)


def fetch_eod(symbol):
    """Return (DataFrame, meta). DataFrame is None when no source has data."""
    # Imported lazily: app.py imports this module's consumers, so a top-level
    # `import app` here would be circular.
    try:
        from app import best_history
    except Exception as e:
        log.warning("cannot reach app.best_history: %s", e)
        return None, {"source": "unavailable", "error": str(e)}

    try:
        rows, source = best_history(symbol.upper())
    except Exception as e:
        log.warning("%s: history fetch failed: %s", symbol, e)
        return None, {"source": "error", "error": str(e)}

    df = _rows_to_frame(rows)
    if not len(df):
        return None, {"source": source, "rows": 0,
                      "note": "No usable EOD rows — caller must not fabricate."}
    return df, {"source": source, "rows": len(df),
                "first": str(df["date"].iloc[0]),
                "last": str(df["date"].iloc[-1])}
