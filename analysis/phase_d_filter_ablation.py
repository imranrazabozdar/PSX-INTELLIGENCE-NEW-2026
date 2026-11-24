#!/usr/bin/env python3
"""phase_d_filter_ablation.py — READ-ONLY filter ablation on the production Phase D SHELF_BREAKOUT trades.

Signals are the exact SHELF_BREAKOUT signals from watchlist_breakout_audit.breakouts(); execution and
exits are A.simulate (Rule 2). Each trade is tagged with pre-signal features and assigned to 7 slices:

  0_PHASE_D_BASELINE    all trades
  1_WITH_COIL_DRYUP     ATR14[t]/ATR14[t-14] <= 0.95 and volume dry-up <= 0.35
  2_WITH_1W_LEADER      completed weekly bar satisfies the C6 weekly-leader condition
  3_NO_EXHAUSTED_WARN   NOT (MFI14 > 80 or 10-day return > 12%)
  4_PRICE_CAP_100       signal close <= Rs 100
  4B_PRICE_LE_25        signal close <= Rs 25
  5_CLEAN_COMBO         slice 3 and slice 4 and (slice 1 or slice 2)

Only SELECTs are issued (local SQLite is opened with mode=ro); outputs are CSVs.

No look-ahead: features use bars <= t only; the weekly value for the week ending on day t is
attached to that week's last trading day and forward-filled, so it is visible from day t onward.

  python analysis/phase_d_filter_ablation.py [--local-db PATH] [--host HOST] [--out-dir DIR]
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import watchlist_breakout_audit as A  # noqa: E402  (loader, signals, Rule 2 engine, stats)
from three_pillar_backtest import ema, rsi, mfi, obv, atr  # noqa: E402

SLICES = ["0_PHASE_D_BASELINE", "1_WITH_COIL_DRYUP", "2_WITH_1W_LEADER", "3_NO_EXHAUSTED_WARN",
          "4_PRICE_CAP_100", "4B_PRICE_LE_25", "5_CLEAN_COMBO"]
TRADE_COLS = ["symbol", "signal_date", "year", "sample", "entry_flag", "next_open", "exit_date", "exit_price",
              "rule2_return_pct", "mfe_pct", "hold_days", "exit_reason", "atr_ratio", "dryup", "mfi14", "ret10",
              "close", "weekly_leader"] + SLICES
SUM_COLS = ["slice", "total_signals", "fillable_trades", "win_pct", "mean_pct", "median_pct", "worst_pct",
            "mean_mfe_pct", "avg_hold_days", "OOS_2025_2026_trades", "OOS_2025_2026_mean_pct",
            "IS_2021_2024_mean_pct"]


def slice_flags(f):
    coil = f["atr_ratio"] <= 0.95 and f["dryup"] <= 0.35
    lead = bool(f["weekly_leader"])
    no_exh = not (f["mfi14"] > 80 or f["ret10"] > 0.12)
    cap100 = f["close"] <= 100
    return {"0_PHASE_D_BASELINE": True, "1_WITH_COIL_DRYUP": coil, "2_WITH_1W_LEADER": lead,
            "3_NO_EXHAUSTED_WARN": no_exh, "4_PRICE_CAP_100": cap100, "4B_PRICE_LE_25": f["close"] <= 25,
            "5_CLEAN_COMBO": no_exh and cap100 and (coil or lead)}


def weekly_leader_daily(df):
    """Weekly C6 condition (W-FRI, completed weeks), attached to each week's last session and forward-filled."""
    n = len(df)
    d = df.set_index(pd.to_datetime(df["date"]))
    w = d.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last",
                                 "volume": "sum", "date": "last"}).dropna(subset=["close"])
    w = w.reset_index(drop=True)
    c, v = w["close"], w["volume"]
    e10, e30, o = ema(c, 10), ema(c, 30), obv(c, v)
    cond = (c > e10) & (e10 > e30) & (rsi(c) > 55) & (o >= o.rolling(12).max())
    pos = pd.Index(df["date"]).get_indexer(w["date"])
    keep = pos >= 0
    s = np.full(n, np.nan)
    s[pos[keep]] = cond.to_numpy(dtype=float)[keep]
    return pd.Series(s).ffill().fillna(0).to_numpy() > 0.5


def safe_div(a, b):
    return float(a) / float(b) if b not in (0, 0.0) and np.isfinite(b) else float("nan")


def run_symbol(sym, df):
    bars = df[["date", "open", "high", "low", "close", "volume"]].to_dict("records")
    closes = df["close"].tolist()
    e20, e10 = A.D._ema(closes, 20), A.D._ema(closes, 10)
    H, L, C, V = (df[x].to_numpy(dtype=float) for x in ("high", "low", "close", "volume"))
    atr14 = atr(df["high"], df["low"], df["close"]).to_numpy(dtype=float)
    mfi14 = mfi(df["high"], df["low"], df["close"], df["volume"]).to_numpy(dtype=float)
    wk = weekly_leader_daily(df)
    out, busy_until = [], -1
    for t, sig in A.breakouts(bars):
        if t < busy_until:
            continue
        sim = A.simulate(bars, t, e20, e10)
        if sim is None:
            continue
        busy_until = len(bars) if sim["reason"].startswith("OPEN") else sim["exit_i"]
        f = {"atr_ratio": safe_div(atr14[t], atr14[t - 14]),
             "dryup": safe_div(min(V[t - 2], V[t - 1], V[t]), V[t - 20:t].mean()),
             "mfi14": float(mfi14[t]), "ret10": safe_div(C[t], C[t - 10]) - 1,
             "close": float(C[t]), "weekly_leader": bool(wk[t])}
        yr = int(sig["date"][:4])
        row = {"symbol": sym, "signal_date": sig["date"], "year": yr,
               "sample": "OOS" if yr >= 2025 else "IS", "entry_flag": sim["flags"],
               "next_open": round(sim["next_open"], 2), "exit_date": sim["exit_date"],
               "exit_price": round(sim["exit_price"], 2), "rule2_return_pct": round(sim["ret"], 2),
               "mfe_pct": round(sim["mfe"], 2), "hold_days": sim["hold"], "exit_reason": sim["reason"],
               "atr_ratio": round(f["atr_ratio"], 4), "dryup": round(f["dryup"], 4),
               "mfi14": round(f["mfi14"], 2), "ret10": round(f["ret10"], 4), "close": round(f["close"], 2),
               "weekly_leader": int(f["weekly_leader"])}
        row.update({k: int(v) for k, v in slice_flags(f).items()})
        out.append(row)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local-db", default=None)
    ap.add_argument("--host", default=None)
    ap.add_argument("--out-dir", default=str(HERE))
    a = ap.parse_args(argv)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    db, src = A.open_db(a)
    have = A.table_names(db)
    table = "daily_ohlc" if "daily_ohlc" in have else "price_daily" if "price_daily" in have else None
    if not table:
        sys.exit(f"No daily_ohlc / price_daily table at {src}")
    raw = pd.DataFrame(db.query(f"SELECT symbol, trade_date AS date, open, high, low, close, volume "
                                f"FROM {table} ORDER BY symbol, trade_date"))
    for col in ("open", "high", "low", "close", "volume"):
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    raw["date"] = raw["date"].astype(str).str[:10]
    raw = raw.dropna(subset=["open", "high", "low", "close"])
    raw["volume"] = raw["volume"].fillna(0)
    print(f"Source: {src} | table={table} | symbols={raw['symbol'].nunique()} | rows={len(raw)} | "
          f"{raw['date'].min()} -> {raw['date'].max()} | loaded {time.time() - t0:.0f}s")
    if table != "daily_ohlc":
        print("WARNING: production daily_ohlc not reachable; not the multi-year history.")

    trades = []
    groups = list(raw.groupby("symbol", sort=True))
    for i, (sym, df) in enumerate(groups, 1):
        df = df.reset_index(drop=True)
        if len(df) >= 60:
            trades += run_symbol(sym, df)
        if i % 50 == 0 or i == len(groups):
            print(f"  {i}/{len(groups)} symbols | {len(trades)} trades | {time.time() - t0:.0f}s")

    trades.sort(key=lambda r: (r["signal_date"], r["symbol"]))
    tdf = pd.DataFrame(trades, columns=TRADE_COLS)
    tdf.to_csv(out / "phase_d_ablation_trades.csv", index=False)

    summ = []
    for name in SLICES:
        rows = [r for r in trades if r[name]]
        st = A.bucket_stats("slice", name, rows)
        oos = A.bucket_stats("slice", name, [r for r in rows if r["sample"] == "OOS"])
        ins = A.bucket_stats("slice", name, [r for r in rows if r["sample"] == "IS"])
        summ.append({"slice": name, "total_signals": st["total_signals"], "fillable_trades": st["fillable_trades"],
                     "win_pct": st["win_rate_pct"], "mean_pct": st["mean_return_pct"],
                     "median_pct": st["median_return_pct"], "worst_pct": st["worst_loss_pct"],
                     "mean_mfe_pct": st["mean_mfe_pct"], "avg_hold_days": st["avg_hold_days"],
                     "OOS_2025_2026_trades": oos["fillable_trades"],
                     "OOS_2025_2026_mean_pct": oos["mean_return_pct"],
                     "IS_2021_2024_mean_pct": ins["mean_return_pct"]})
    s = pd.DataFrame(summ, columns=SUM_COLS)
    s.to_csv(out / "phase_d_ablation_summary.csv", index=False)
    print(f"\nSaved {len(trades)} trades + {len(s)} summary rows -> {out} | total {time.time() - t0:.0f}s\n")
    with pd.option_context("display.max_rows", None, "display.width", 250, "display.max_columns", None):
        print(s.to_string(index=False))


if __name__ == "__main__":
    main()
