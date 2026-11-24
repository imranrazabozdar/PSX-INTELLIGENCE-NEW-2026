#!/usr/bin/env python3
"""three_pillar_backtest.py — READ-ONLY backtest of 15 pre-registered PSX long setups.

Pillar 1 indicator combos (C1-C6), Pillar 2 chart patterns (P1-P5), Pillar 3 market
structure (MS1-MS4). Only SELECT queries are issued; data loading, the PSX circuit
band and the Rule 2 exit engine are reused from analysis/watchlist_breakout_audit.py.

No look-ahead
  * every signal is evaluated on a completed daily (or weekly) close; entry is the
    NEXT daily session's open
  * swing pivots use N=3 bars each side and become visible only at bar t+3
  * weekly bars are W-FRI resamples; a week's values are attached to its last
    trading day and forward-filled, so a day only ever sees completed weeks
  * RVOL = volume / mean volume of the 20 bars BEFORE the bar (production definition)
Filters: 20-day average turnover (close*volume) >= PKR 5M on the signal bar; one open
position per symbol per strategy; next-open entries locked at the upper circuit
(Open == Low == upper lock) are skipped.
Exit: Rule 2 (A.simulate): -25% intraday crash stop; close <= EMA20 -> next open;
after any close >= +10% the stop becomes close < EMA10 -> next open; exits deferred
past lower-circuit locked sessions.

  python analysis/three_pillar_backtest.py [--local-db PATH] [--out-dir DIR]
"""
import argparse
import bisect
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import watchlist_breakout_audit as A  # noqa: E402  (loader, circuit band, Rule 2 engine, stats)

N_PIV = 3
MIN_TURNOVER = 5_000_000
IS_YEARS, OOS_YEARS = range(2021, 2025), range(2025, 2027)
STRATS = [  # (code, pillar, timeframe)
    ("C1_EMA_RSI_TREND", "P1_INDICATOR", "1D"), ("C2_OBV_MFI_ACCUM", "P1_INDICATOR", "1D"),
    ("C3_UPTREND_PULLBACK", "P1_INDICATOR", "1D"), ("C4_DUAL_OVERSOLD_BOUNCE", "P1_INDICATOR", "1D"),
    ("C5_FOUR_FACTOR_CONFLUENCE", "P1_INDICATOR", "1D"), ("C6_WEEKLY_LEADER", "P1_INDICATOR", "1W"),
    ("P1_VCP", "P2_PATTERN", "1D"), ("P2_CUP_HANDLE", "P2_PATTERN", "1D"), ("P3_BULL_FLAG", "P2_PATTERN", "1D"),
    ("P4_ASCENDING_TRIANGLE", "P2_PATTERN", "1D"), ("P5_DOUBLE_BOTTOM", "P2_PATTERN", "1D"),
    ("MS1_CHOCH_REVERSAL", "P3_STRUCTURE", "1D"), ("MS2_BOS_CONTINUATION", "P3_STRUCTURE", "1D"),
    ("MS3_SR_FLIP_RETEST", "P3_STRUCTURE", "1D"), ("MS4_WEEKLY_DAILY_ALIGN", "P3_STRUCTURE", "1D+1W"),
]
TRADE_COLS = ["strategy", "pillar", "timeframe", "symbol", "signal_date", "entry_date", "next_open",
              "exit_date", "exit_price", "rule2_return_pct", "mfe_pct", "mfe_date", "hold_days",
              "exit_reason", "sample", "price_tier", "year", "entry_flag"]
SUM_COLS = ["strategy", "split", "total_signals", "fillable_trades", "unfillable_lock_pct", "win_rate_pct",
            "mean_return_pct", "median_return_pct", "mean_mfe_pct", "p90_mfe_pct", "worst_loss_pct",
            "avg_hold_days"]


# ---------------------------------------------------------------- vectorized indicators
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def mfi(h, l, c, v, n=14):
    tp = (h + l + c) / 3
    mf = tp * v
    pos = mf.where(tp > tp.shift(1), 0.0).rolling(n).sum()
    neg = mf.where(tp < tp.shift(1), 0.0).rolling(n).sum()
    return 100 - 100 / (1 + pos / neg.replace(0, np.nan))


def obv(c, v):
    return (np.sign(c.diff()).fillna(0) * v).cumsum()


def atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def pivots(h, l, n=N_PIV):
    """Boolean SH / SL at the pivot bar itself (strict on the left, so ties register once)."""
    w = 2 * n + 1
    sh = (h == h.rolling(w, center=True).max()) & (h > h.shift(1).rolling(n).max())
    sl = (l == l.rolling(w, center=True).min()) & (l < l.shift(1).rolling(n).min())
    return sh.fillna(False).to_numpy(), sl.fillna(False).to_numpy()


def visible_last_two(vals, mask, n=N_PIV):
    """(last, previous) confirmed pivot value as seen at each bar (pivot t visible at t+n)."""
    s = pd.Series(np.where(mask, vals, np.nan))
    p = s.dropna()
    last = pd.Series(np.nan, index=s.index)
    prev = pd.Series(np.nan, index=s.index)
    last[p.index] = p.values
    prev[p.index] = p.shift(1).values
    return last.ffill().shift(n).to_numpy(), prev.ffill().shift(n).to_numpy()


def structure(h, l):
    sh, sl = pivots(h, l)
    lsh, psh = visible_last_two(h.to_numpy(), sh)
    lsl, psl = visible_last_two(l.to_numpy(), sl)
    up = (lsh > psh) & (lsl > psl)
    down = (lsh < psh) & (lsl < psl)
    return sh, sl, lsh, lsl, up, down


def add_indicators(df):
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    df["ema10"], df["ema20"], df["ema50"], df["ema200"] = ema(c, 10), ema(c, 20), ema(c, 50), ema(c, 200)
    df["rsi"], df["mfi"], df["obv"], df["atr"] = rsi(c), mfi(h, l, c, v), obv(c, v), atr(h, l, c)
    df["rvol"] = v / v.shift(1).rolling(20).mean()
    df["turn20"] = (c * v).rolling(20).mean()
    return df


# ---------------------------------------------------------------- weekly (W-FRI, completed weeks only)
def weekly_frames(df):
    d = df.set_index(pd.to_datetime(df["date"]))
    w = d.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last",
                                 "volume": "sum", "date": "last"}).dropna(subset=["close"])
    w = w.reset_index(drop=True)
    c, v = w["close"], w["volume"]
    e10, e30, r, o = ema(c, 10), ema(c, 30), rsi(c), obv(c, v)
    c6 = (c > e10) & (e10 > e30) & (r > 55) & (o >= o.rolling(12).max())
    *_, up, _ = structure(w["high"], w["low"])
    idx = pd.Index(df["date"])
    pos = idx.get_indexer(w["date"])                    # daily index of each week's last session
    c6_daily = np.zeros(len(df), bool)
    c6_daily[pos[c6.to_numpy()]] = True
    up_daily = pd.Series(np.nan, index=range(len(df)))
    up_daily[pos] = up.astype(float)
    return c6_daily, up_daily.ffill().fillna(0).astype(bool).to_numpy()


# ---------------------------------------------------------------- pattern scans (on candidate bars only)
def cross_up(c, level, k):
    return level == level and c[k] > level and c[k - 1] <= level


def scan_patterns(df, sh, sl):
    n = len(df)
    H, L, C = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    V, E20, E50, E200 = df["volume"].to_numpy(), df["ema20"].to_numpy(), df["ema50"].to_numpy(), df["ema200"].to_numpy()
    RV, OBV, ATR = df["rvol"].to_numpy(), df["obv"].to_numpy(), df["atr"].to_numpy()
    atr_med = df["atr"].rolling(20).median().to_numpy()
    sh_idx, sl_idx = np.flatnonzero(sh), np.flatnonzero(sl)
    piv = sorted([(i, "H", H[i]) for i in sh_idx] + [(i, "L", L[i]) for i in sl_idx])
    piv_i = [p[0] for p in piv]
    out = {k: np.zeros(n, bool) for k in ("P1_VCP", "P2_CUP_HANDLE", "P3_BULL_FLAG",
                                           "P4_ASCENDING_TRIANGLE", "P5_DOUBLE_BOTTOM")}
    for k in np.flatnonzero(np.nan_to_num(RV) >= 1.8):
        if k < 30:
            continue
        nv = bisect.bisect_right(piv_i, k - N_PIV)       # pivots visible at k
        vis = piv[:nv]
        # alternate H/L, keep the extreme of consecutive same-type pivots
        alt = []
        for p in vis[-12:]:
            if alt and alt[-1][1] == p[1]:
                if (p[1] == "H" and p[2] >= alt[-1][2]) or (p[1] == "L" and p[2] <= alt[-1][2]):
                    alt[-1] = p
            else:
                alt.append(p)
        hs = [p for p in vis if p[1] == "H"][-2:]
        ls = [p for p in vis if p[1] == "L"][-2:]
        rv2 = RV[k] >= 2.0

        # P1 VCP: >= 2 contracting SH->SL swings, last < 8%, ATR contraction, break of pivot high
        if rv2 and C[k] > E50[k] > E200[k] and ATR[k - 1] < atr_med[k - 1]:
            sw = [(alt[j][2], alt[j + 1][2]) for j in range(len(alt) - 1) if alt[j][1] == "H" and alt[j + 1][1] == "L"]
            if len(sw) >= 2 and alt[-1][1] == "L":
                d1, d2 = [(a - b) / a for a, b in sw[-2:]]
                if d2 < d1 and d2 < 0.08 and cross_up(C, sw[-1][0], k):
                    out["P1_VCP"][k] = True

        # P2 cup & handle (handle h bars before k, base b bars before the handle)
        if rv2 and not out["P2_CUP_HANDLE"][k]:
            for hh in range(4, 16):
                hs_, he = k - hh, k
                if hs_ - 20 < 0:
                    break
                h_hi, h_lo, h_vol = H[hs_:he].max(), L[hs_:he].min(), V[hs_:he].mean()
                if (h_hi - h_lo) / h_hi >= 0.08:
                    continue
                bmax = min(65, hs_)
                seg_h, seg_l, seg_v = H[hs_ - bmax:hs_][::-1], L[hs_ - bmax:hs_][::-1], V[hs_ - bmax:hs_][::-1]
                rim, low = np.maximum.accumulate(seg_h), np.minimum.accumulate(seg_l)
                bvol = np.cumsum(seg_v) / np.arange(1, bmax + 1)
                b = np.arange(1, bmax + 1)
                depth = (rim - low) / rim
                ok = (b >= 20) & (depth >= 0.12) & (depth <= 0.35) & (h_hi <= rim) \
                    & (h_lo >= low + (2 / 3) * (rim - low)) & (h_vol < 0.7 * bvol) \
                    & (C[k] > rim) & (C[k - 1] <= np.maximum(rim, h_hi))
                if ok.any():
                    out["P2_CUP_HANDLE"][k] = True
                    break

        # P3 bull flag: pole p bars (+20%), flag f bars (< 12% off pole top, closes > EMA20, light volume)
        for f in range(3, 11):
            fs = k - f
            f_hi, f_lo = H[fs:k].max(), L[fs:k].min()
            if not (C[k] > f_hi and np.all(C[fs:k] > E20[fs:k])):
                continue
            hit = False
            for p in range(5, 16):
                ps = fs - p
                if ps < 1:
                    break
                top = H[ps:fs].max()
                if C[fs - 1] / C[ps - 1] - 1 >= 0.20 and (top - f_lo) / top < 0.12 \
                        and V[fs:k].mean() < 0.5 * V[ps:fs].mean():
                    hit = True
                    break
            if hit:
                out["P3_BULL_FLAG"][k] = True
                break

        # P4 ascending triangle: two SH within 1.5%, rising SLs after the first SH, OBV rising
        if rv2 and len(hs) == 2 and len(ls) == 2:
            (i1, _, h1), (i2, _, h2) = hs
            (j1, _, l1), (j2, _, l2) = ls
            ceil = max(h1, h2)
            if abs(h1 - h2) / ceil <= 0.015 and l2 > l1 and j2 > i1 and OBV[k - 1] > OBV[max(0, k - 21)] \
                    and cross_up(C, ceil, k):
                out["P4_ASCENDING_TRIANGLE"][k] = True

        # P5 double bottom: two SL within 3%, 15-50 bars apart, neckline >= +10%
        if rv2 and len(ls) == 2:
            (j1, _, l1), (j2, _, l2) = ls
            if 15 <= j2 - j1 <= 50 and abs(l1 - l2) / min(l1, l2) <= 0.03:
                neck = H[j1 + 1:j2].max()
                if neck >= 1.10 * max(l1, l2) and cross_up(C, neck, k):
                    out["P5_DOUBLE_BOTTOM"][k] = True
    return out


def scan_ms3(df, lsh, lsl, up):
    """Retest of a broken SH within 15 bars of a bullish BOS, without closing below the HL."""
    H, L, C, O, M = (df[x].to_numpy() for x in ("high", "low", "close", "open", "mfi"))
    out = np.zeros(len(df), bool)
    act = None
    for k in range(1, len(df)):
        if up[k] and lsh[k] == lsh[k] and C[k] > lsh[k] and C[k - 1] <= lsh[k]:
            act = {"k": k, "lvl": lsh[k], "hl": lsl[k], "dip": False}
            continue
        if not act:
            continue
        if k - act["k"] > 15 or C[k] < act["hl"]:
            act = None
            continue
        if L[k] <= act["lvl"] * 1.015:
            act["dip"] = True
        if act["dip"] and C[k] > O[k] and C[k] > H[k - 1] and M[k] > 50:
            out[k] = True
            act = None
    return out


def signals(df):
    c, s = df["close"], df
    sh, sl, lsh, lsl, up, down = structure(df["high"], df["low"])
    C = c.to_numpy()
    prevC = np.r_[np.nan, C[:-1]]
    rv = np.nan_to_num(df["rvol"].to_numpy())
    sig = {
        "C1_EMA_RSI_TREND": (c > s.ema20) & (s.ema20 > s.ema50) & (s.rsi.shift(1) <= 55) & (s.rsi > 55) & (s.rsi < 70),
        "C2_OBV_MFI_ACCUM": (c > s.ema20) & (s.obv > s.obv.shift(1).rolling(20).max()) & (s.mfi > 60),
        "C3_UPTREND_PULLBACK": (c > s.ema50) & (s.ema50 > s.ema200) & (s.rsi.shift(1) < 40) & (s.rsi > 42) & (s.mfi > 50),
        "C4_DUAL_OVERSOLD_BOUNCE": (s.rsi.shift(1) < 30) & (s.mfi.shift(1) < 25) & (c > s.high.shift(1)) & (s.obv > s.obv.shift(1)),
        "C5_FOUR_FACTOR_CONFLUENCE": (c > s.ema20) & s.rsi.between(55, 72) & (s.mfi >= 65) & (s.obv > ema(s.obv, 20)),
    }
    sig = {k: v.fillna(False).to_numpy() for k, v in sig.items()}
    brk = (C > lsh) & (prevC <= lsh)
    sig["MS1_CHOCH_REVERSAL"] = down & brk & (rv >= 1.8)
    sig["MS2_BOS_CONTINUATION"] = up & brk & (rv >= 1.5)
    sig["MS3_SR_FLIP_RETEST"] = scan_ms3(df, lsh, lsl, up)
    c6, wup = weekly_frames(df)
    sig["C6_WEEKLY_LEADER"] = c6
    sig["MS4_WEEKLY_DAILY_ALIGN"] = wup & (sig["MS1_CHOCH_REVERSAL"] | sig["MS2_BOS_CONTINUATION"])
    sig.update(scan_patterns(df, sh, sl))
    liquid = (df["turn20"] >= MIN_TURNOVER).to_numpy()
    return {k: v & liquid for k, v in sig.items()}


# ---------------------------------------------------------------- execution
def run_symbol(sym, df):
    bars = df[["date", "open", "high", "low", "close", "volume"]].to_dict("records")
    e20, e10 = df["ema20"].tolist(), df["ema10"].tolist()
    trades = []
    for code, pillar, tf in STRATS:
        busy = -1
        for t in np.flatnonzero(SIGS[code]):
            if t < busy or t + 1 >= len(bars):
                continue
            nxt = bars[t + 1]
            locked = abs(nxt["open"] - nxt["low"]) < A.TICK and nxt["low"] >= A.upper_lock(bars[t]["close"]) - A.TICK
            sim = A.simulate(bars, t, e20, e10)
            if not locked:                                # unfillable upper lock -> logged, no position taken
                busy = len(bars) if sim["reason"].startswith("OPEN") else sim["exit_i"]
            yr = int(bars[t]["date"][:4])
            trades.append({
                "strategy": code, "pillar": pillar, "timeframe": tf, "symbol": sym, "signal_date": bars[t]["date"],
                "entry_date": nxt["date"], "next_open": round(sim["next_open"], 2), "exit_date": sim["exit_date"],
                "exit_price": round(sim["exit_price"], 2), "rule2_return_pct": round(sim["ret"], 2),
                "mfe_pct": round(sim["mfe"], 2), "mfe_date": sim["mfe_date"], "hold_days": sim["hold"],
                "exit_reason": sim["reason"], "sample": "IS" if yr in IS_YEARS else "OOS",
                "price_tier": "<= Rs. 25" if sim["next_open"] <= 25 else "> Rs. 25", "year": yr,
                "entry_flag": ";".join(f for f, on in (("UNFILLABLE_UPPER_LOCK", locked),
                                                        ("GAP_GT_4PCT", "GAP_GT_4PCT" in sim["flags"])) if on)})
    return trades


SIGS = {}


def main(argv=None):
    global SIGS
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
        if len(df) < 60:
            continue
        add_indicators(df)
        SIGS = signals(df)
        trades += run_symbol(sym, df)
        if i % 50 == 0 or i == len(groups):
            print(f"  {i}/{len(groups)} symbols | {len(trades)} trades | {time.time() - t0:.0f}s")

    trades.sort(key=lambda r: (r["strategy"], r["signal_date"], r["symbol"]))
    summ = []
    for code, *_ in STRATS:
        rs = [r for r in trades if r["strategy"] == code]
        for split, sub in (("ALL", rs), ("IS_2021_2024", [r for r in rs if r["sample"] == "IS"]),
                           ("OOS_2025_2026", [r for r in rs if r["sample"] == "OOS"]),
                           ("PRICE_<=25", [r for r in rs if r["price_tier"] == "<= Rs. 25"]),
                           ("PRICE_>25", [r for r in rs if r["price_tier"] == "> Rs. 25"])):
            st = A.bucket_stats(code, split, sub)
            summ.append({"strategy": code, "split": split, **{k: st[k] for k in SUM_COLS[2:]}})
    pd.DataFrame(trades, columns=TRADE_COLS).to_csv(out / "three_pillar_trades.csv", index=False)
    s = pd.DataFrame(summ, columns=SUM_COLS)
    s.to_csv(out / "three_pillar_summary.csv", index=False)
    print(f"\nSaved {len(trades)} trades + {len(s)} summary rows -> {out} | total {time.time() - t0:.0f}s\n")
    with pd.option_context("display.max_rows", None, "display.width", 250, "display.max_columns", None):
        print(s.to_string(index=False))


if __name__ == "__main__":
    main()
