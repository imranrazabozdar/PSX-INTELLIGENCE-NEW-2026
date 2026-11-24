#!/usr/bin/env python3
"""forensic_mover_study.py — READ-ONLY study: what separates explosive PSX movers from false starts.

Cohort A EXPLOSIVE_MOVERS: entry = next session's open t; within the 20-bar window [t, t+19] a bar
  reaches >= +30% vs the entry open before any bar reaches <= -12%. Non-overlapping per symbol.
Cohort B FALSE_STARTS: 10-day closing-high breakout on signal bar t-1 (rvol >= 1.5) that never
  reaches +10% in [t, t+19]. Kept only when its ISO week also holds an A event (any symbol).
Features use bars t-10..t-1 only (plus the pre-registered vol20/ATR/MFI definitions, all lagged).
Only SELECT queries are issued; loading, the PSX circuit band and indicators are reused from
analysis/watchlist_breakout_audit.py and analysis/three_pillar_backtest.py.

  python analysis/forensic_mover_study.py [--local-db PATH] [--host HOST] [--out-dir DIR]
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import watchlist_breakout_audit as A  # noqa: E402  (loader, circuit band)
from three_pillar_backtest import ema, mfi, obv, atr  # noqa: E402,F401  (ema unused, kept for parity)

MIN_TURNOVER = 5_000_000
MIN_T = 61                       # need 60 bars of history for the rolling quantile features
WIN = 20                         # forward window [t, t+19]
EXP_UP, EXP_DN, FALSE_UP = 1.30, 0.88, 1.10
TIER = "<= Rs. 25"
IS_YEARS = range(2021, 2025)
PERIODS = [("IS_2021_2024", "IS"), ("OOS_2025_2026", "OOS")]
# (feature, direction): "high" -> top quartile is the high end; "low" -> top quartile is the low end
FEATS = [("absorption_days", "high"), ("clv_top_days", "high"), ("vol_dryup_min", "low"),
         ("atr_compression", "low"), ("obv_slope_10d", "high"), ("mfi_14", "high"),
         ("rs_vs_market_10d", "high")]
FEAT_NAMES = [f for f, _ in FEATS]
EVENT_COLS = ["cohort", "symbol", "entry_date", "year", "period", "entry_open"] + FEAT_NAMES + ["entry_price_tier"]
SUM_COLS = ["period", "feature", "n_A", "n_B", "median_A", "median_B", "median_diff", "top_q_threshold",
            "top_q_hit_A_pct", "top_q_hit_B_pct", "hit_lift"]


# ---------------------------------------------------------------- per-symbol events and features
def prep_symbol(sym, df, mkt):
    """Return event dicts (cohort A then B) for one symbol. df: date-sorted rows incl. 'ret10'."""
    n = len(df)
    if n < MIN_T + WIN:
        return []
    O, H, L, C = (df[c].to_numpy(float) for c in ("open", "high", "low", "close"))
    Hs, Ls, Cs, Vs = df["high"], df["low"], df["close"], df["volume"]
    dates = df["date"].to_numpy()

    vol20 = Vs.shift(1).rolling(20).mean()
    rvol = Vs / vol20
    turn20 = (Cs * Vs).shift(1).rolling(20).mean()
    elig = (turn20 >= MIN_TURNOVER).to_numpy(bool)

    T = np.arange(MIN_T, n - WIN + 1)                     # entry bars with a full forward window
    fill = np.ones(n, bool)
    for t in T[elig[T]]:
        fill[t] = not (abs(O[t] - L[t]) < A.TICK and L[t] >= A.upper_lock(C[t - 1]) - A.TICK)

    Hw = sliding_window_view(H, WIN)[T]                  # row for t holds H[t..t+19]
    Lw = sliding_window_view(L, WIN)[T]

    # ---- Cohort A
    up_m = Hw >= (EXP_UP * O[T])[:, None]
    dn_m = Lw <= (EXP_DN * O[T])[:, None]
    up_any, dn_any = up_m.any(1), dn_m.any(1)
    up_first = up_m.argmax(1)
    dn_first = np.where(dn_any, dn_m.argmax(1), WIN)
    a_ok = up_any & (up_first < dn_first)                # same-bar hit of both -> fails
    A_mask = np.zeros(n, bool)
    A_mask[T] = a_ok
    A_mask &= elig & fill
    up_first_full = np.zeros(n, int)
    up_first_full[T] = up_first
    a_ts = []
    nxt_ok = -1
    for t in np.flatnonzero(A_mask):
        if t <= nxt_ok:
            continue
        a_ts.append(int(t))
        nxt_ok = int(t + up_first_full[t])               # hit_idx; next event needs t > hit_idx
    A_acc = np.zeros(n, bool)
    A_acc[a_ts] = True

    # ---- Cohort B
    sig_s = ((Cs >= Hs.rolling(10).max()) & (rvol >= 1.5)).fillna(False).astype(bool)
    sig_t = sig_s.shift(1).fillna(False).to_numpy(bool)
    B_mask = np.zeros(n, bool)
    B_mask[T] = Hw.max(1) < (FALSE_UP * O[T])
    B_mask &= sig_t & elig & fill & ~A_acc
    b_ts = []
    last = None
    for t in np.flatnonzero(B_mask):
        if last is not None and t <= last + WIN - 1:     # next B must have t > previous t + 19
            continue
        b_ts.append(int(t))
        last = t

    # ---- Features (all lagged to bars <= t-1)
    rng = (Hs - Ls) / Cs.shift(1)
    q25 = rng.rolling(60).quantile(0.25)
    absorb = ((Vs >= 1.3 * vol20) & (rng <= q25)).astype(float).rolling(10).sum().shift(1)
    clv = ((Cs - Ls) / (Hs - Ls)).where(Hs > Ls)
    clv_top = (clv >= 0.75).astype(float).rolling(10).sum().shift(1)
    vol_dry = pd.concat([Vs.shift(1), Vs.shift(2), Vs.shift(3)], axis=1).min(axis=1) / vol20
    atr14 = atr(Hs, Ls, Cs, 14)
    atr_comp = atr14.shift(1) / atr14.shift(15)
    obv_s = obv(Cs, Vs)
    sumv = Vs.rolling(10).sum().shift(1)
    obv_slope = ((obv_s.shift(1) - obv_s.shift(11)) / sumv).where(sumv != 0, 0.0)
    mfi14 = mfi(Hs, Ls, Cs, Vs, 14).shift(1)
    rs = (df["ret10"] - df["date"].map(mkt)).shift(1)
    fe = {"absorption_days": absorb.to_numpy(float), "clv_top_days": clv_top.to_numpy(float),
          "vol_dryup_min": vol_dry.to_numpy(float), "atr_compression": atr_comp.to_numpy(float),
          "obv_slope_10d": obv_slope.to_numpy(float), "mfi_14": mfi14.to_numpy(float),
          "rs_vs_market_10d": rs.to_numpy(float)}

    def make(ts, cohort):
        out = []
        for t in ts:
            yr = int(dates[t][:4])
            rec = {"cohort": cohort, "symbol": sym, "entry_date": dates[t], "year": yr,
                   "period": "IS" if yr in IS_YEARS else "OOS", "entry_open": float(O[t])}
            rec.update({k: float(fe[k][t]) for k in FEAT_NAMES})
            rec["entry_price_tier"] = TIER if O[t] <= 25 else "> Rs. 25"
            out.append(rec)
        return out

    return make(a_ts, "A") + make(b_ts, "B")


# ---------------------------------------------------------------- summary
def feature_row(label, feat, direction, a, b):
    high = direction == "high"
    pooled = pd.concat([a, b])
    thr = float(pooled.quantile(0.75 if high else 0.25)) if len(pooled) else np.nan
    hit = (lambda x: x >= thr) if high else (lambda x: x <= thr)
    pa = float(hit(a).mean() * 100) if len(a) else np.nan
    pb = float(hit(b).mean() * 100) if len(b) else np.nan
    med_a = float(a.median()) if len(a) else np.nan
    med_b = float(b.median()) if len(b) else np.nan
    lift = pa / pb if (pb == pb and pb > 0 and pa == pa) else np.nan
    return {"period": label, "feature": feat, "n_A": len(a), "n_B": len(b), "median_A": med_a,
            "median_B": med_b, "median_diff": med_a - med_b, "top_q_threshold": thr,
            "top_q_hit_A_pct": pa, "top_q_hit_B_pct": pb, "hit_lift": lift}


def tier_row(label, A_, B_):
    pa = float((A_["entry_price_tier"] == TIER).mean() * 100) if len(A_) else np.nan
    pb = float((B_["entry_price_tier"] == TIER).mean() * 100) if len(B_) else np.nan
    lift = pa / pb if (pb == pb and pb > 0 and pa == pa) else np.nan
    nan = np.nan
    return {"period": label, "feature": "entry_price_tier_le25", "n_A": len(A_), "n_B": len(B_),
            "median_A": nan, "median_B": nan, "median_diff": nan, "top_q_threshold": nan,
            "top_q_hit_A_pct": pa, "top_q_hit_B_pct": pb, "hit_lift": lift}


# ---------------------------------------------------------------- main
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

    # equal-weighted market 10-day return by date (needed before the per-symbol loop)
    raw = raw.sort_values(["symbol", "date"]).reset_index(drop=True)
    raw["ret10"] = raw["close"] / raw.groupby("symbol")["close"].shift(10) - 1
    mkt = raw.groupby("date")["ret10"].mean().to_dict()

    events = []
    groups = list(raw.groupby("symbol", sort=True))
    for i, (sym, df) in enumerate(groups, 1):
        events += prep_symbol(sym, df.reset_index(drop=True), mkt)
        if i % 50 == 0 or i == len(groups):
            print(f"  {i}/{len(groups)} symbols | {len(events)} raw events | {time.time() - t0:.0f}s")

    ev = pd.DataFrame(events, columns=EVENT_COLS)
    if len(ev):
        iso = pd.to_datetime(ev["entry_date"]).dt.isocalendar()
        ev["iso_week"] = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
    else:
        ev["iso_week"] = pd.Series(dtype=str)
    a_weeks = set(ev.loc[ev["cohort"] == "A", "iso_week"])
    b_total = int((ev["cohort"] == "B").sum())
    keep = (ev["cohort"] == "A") | ev["iso_week"].isin(a_weeks)
    ev = ev[keep].sort_values(["cohort", "entry_date", "symbol"]).reset_index(drop=True)
    b_kept = int((ev["cohort"] == "B").sum())
    ev[EVENT_COLS].to_csv(out / "forensic_mover_events.csv", index=False)

    rows = []
    counts = []
    for label, pcode in PERIODS:
        sub = ev[ev["period"] == pcode]
        A_, B_ = sub[sub["cohort"] == "A"], sub[sub["cohort"] == "B"]
        counts.append(f"{label}: A={len(A_)} B={len(B_)}")
        for feat, direction in FEATS:
            a = pd.to_numeric(A_[feat], errors="coerce").dropna()
            b = pd.to_numeric(B_[feat], errors="coerce").dropna()
            rows.append(feature_row(label, feat, direction, a, b))
        rows.append(tier_row(label, A_, B_))
    s = pd.DataFrame(rows, columns=SUM_COLS).round(4)
    s.to_csv(out / "forensic_mover_summary.csv", index=False)

    print(f"\nCohort counts (after ISO-week filter; B before filter={b_total}, after={b_kept}): " + " | ".join(counts))
    print(f"Saved {len(ev)} events + {len(s)} summary rows -> {out} | total {time.time() - t0:.0f}s\n")
    with pd.option_context("display.max_rows", None, "display.width", 250, "display.max_columns", None):
        print(s.to_string(index=False, na_rep=""))


if __name__ == "__main__":
    main()
