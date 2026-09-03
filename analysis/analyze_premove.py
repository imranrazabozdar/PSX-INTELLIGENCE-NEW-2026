#!/usr/bin/env python3
"""Day-by-day forensic technical analysis for AICL/SHFA/THCCL/FNEL,
computed locally (no network) from real PSX-portal OHLCV already fetched
via GitHub Actions (analysis/fetch_premove_data.py) and saved to
premove_data_raw.json.

Implements the classic/textbook rule for each requested indicator/pattern
directly (not this project's own bespoke pattern-engine modules, which
carry PSX-calibrated thresholds tuned for live scanning, not this kind
of literal after-the-fact single-stock study) -- documented inline so
every number in the report is reproducible from this script.

This version (deepened per the second round of the study) adds, beyond
the first pass: open/high/low retained per row, SMA20/SMA50-based
price-vs-MA labels (distinct from the EMA20/EMA50 cross), Bollinger
position expressed in sigma units, MACD histogram direction (day over
day), a human-readable "criteria met" string per detected candlestick
pattern (built from the actual OHLC numbers, not hand-written), a
support/resistance note from a simple retrospective swing-point scan,
and day-offset-from-move-start tracking so a cross-stock first-occurrence
table can be built.

MOVE_START holds the user-given date each stock's move began (day 0),
used only to label rows as "Day -N"/"Day +N" and to build the
cross-stock first-occurrence comparison -- it does not affect any
indicator computation.
"""
import json
import math
from pathlib import Path

DATA_PATH = str(Path(__file__).parent / "premove_data_raw.json")
OUT_PATH = str(Path(__file__).parent / "premove_analysis.json")

SYMBOLS = ["AICL", "SHFA", "THCCL", "FNEL"]
MOVE_START = {
    "AICL": "2026-07-23",
    "SHFA": "2026-06-12",
    "THCCL": "2026-06-30",
    "FNEL": "2026-04-06",
}

# FNEL's fetched series shows an abrupt ~90% single-day price adjustment
# on 2026-02-02 (close 17.70 on 2026-01-30 -> 1.65 on 2026-02-02, volume
# 191M vs a typical 10-20M) -- the signature of a large bonus/rights
# share issue on PSX rather than a real one-day price return, and not a
# wrong-scrip mixup (the post-2026-02-02 trajectory continues organically
# at the new scale and its window-end values, 1.16 on 04-06 -> 1.74 on
# 04-24, match the user-given reference prices almost exactly). Trimming
# pre-adjustment bars keeps every moving-average/volatility calc for FNEL
# from spanning that capital-structure discontinuity; see the report's
# "Ticker identity & data-quality notes" section for FNEL.
FNEL_TRIM_START = "2026-02-02"


# ---------------------------------------------------------------- indicators

def ema(values, period):
    if len(values) < 1:
        return [None] * len(values)
    k = 2 / (period + 1)
    out = []
    prev = None
    for v in values:
        prev = v if prev is None else v * k + prev * (1 - k)
        out.append(prev)
    return out


def sma(values, period):
    out = []
    for i in range(len(values)):
        if i + 1 < period:
            out.append(None)
        else:
            out.append(sum(values[i + 1 - period:i + 1]) / period)
    return out


def rolling_std(values, period):
    out = []
    for i in range(len(values)):
        if i + 1 < period:
            out.append(None)
        else:
            window = values[i + 1 - period:i + 1]
            m = sum(window) / period
            var = sum((x - m) ** 2 for x in window) / period
            out.append(math.sqrt(var))
    return out


def rsi(closes, period=14):
    out = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains, losses = [], []
    for i in range(1, len(closes)):
        chg = closes[i] - closes[i - 1]
        gains.append(max(chg, 0))
        losses.append(max(-chg, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rs = avg_gain / avg_loss if avg_loss > 0 else float("inf")
    out[period] = 100 - (100 / (1 + rs)) if avg_loss > 0 else 100.0
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else float("inf")
        out[i + 1] = 100 - (100 / (1 + rs)) if avg_loss > 0 else 100.0
    return out


def macd(closes, fast=12, slow=26, signal=9):
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = ema(macd_line, signal)
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, hist


def bollinger(closes, period=20, mult=2):
    mid = sma(closes, period)
    std = rolling_std(closes, period)
    upper = [m + mult * s if m is not None else None for m, s in zip(mid, std)]
    lower = [m - mult * s if m is not None else None for m, s in zip(mid, std)]
    return upper, mid, lower, std


# ------------------------------------------------------------- candle geometry

def body(c):
    return abs(c["close"] - c["open"])


def is_bullish(c):
    return c["close"] > c["open"]


def is_bearish(c):
    return c["close"] < c["open"]


def upper_wick(c):
    return c["high"] - max(c["open"], c["close"])


def lower_wick(c):
    return min(c["open"], c["close"]) - c["low"]


def rng(c):
    return c["high"] - c["low"]


# ------------------------------------------------------------- pattern scan

def scan_patterns(bars):
    """Returns {date: [(pattern_name, criteria_met_text), ...]} using
    classic textbook rules, literal, no PSX-scale tuning (see module
    docstring). criteria_met_text is built from the bar's actual OHLC
    numbers so it states exactly what fired, not just the pattern name."""
    flags = {b["date"]: [] for b in bars}
    n = len(bars)
    for i in range(n):
        c = bars[i]
        b = body(c)
        r = rng(c) or 1e-9

        if b <= 0.1 * r:
            flags[c["date"]].append((
                "Doji",
                f"body({b:.2f}) <= 0.1*range({r:.2f}) [body/range={b / r:.2f}]"
            ))

        if b > 0 and lower_wick(c) >= 2 * b and upper_wick(c) <= 0.3 * b and (c["high"] - max(c["open"], c["close"])) <= 0.15 * r:
            flags[c["date"]].append((
                "Hammer",
                f"lower_wick({lower_wick(c):.2f}) >= 2*body({b:.2f}) AND "
                f"upper_wick({upper_wick(c):.2f}) <= 0.3*body({b:.2f}) AND "
                f"high({c['high']:.2f})-max(open,close)({max(c['open'], c['close']):.2f})={c['high'] - max(c['open'], c['close']):.2f} <= 0.15*range({r:.2f})"
            ))

        if i >= 1:
            p = bars[i - 1]
            if is_bearish(p) and is_bullish(c) and c["open"] <= p["close"] and c["close"] >= p["open"]:
                flags[c["date"]].append((
                    "Bullish Engulfing",
                    f"prior_close({p['close']:.2f})<prior_open({p['open']:.2f}, bearish) AND "
                    f"close({c['close']:.2f})>open({c['open']:.2f}, bullish) AND "
                    f"open({c['open']:.2f}) <= prior_close({p['close']:.2f}) AND "
                    f"close({c['close']:.2f}) >= prior_open({p['open']:.2f}) "
                    f"[today body {c['open']:.2f}→{c['close']:.2f} engulfs prior {p['open']:.2f}→{p['close']:.2f}]"
                ))
            p_mid = (p["open"] + p["close"]) / 2
            if is_bearish(p) and is_bullish(c) and c["open"] < p["low"] and p_mid < c["close"] < p["open"]:
                flags[c["date"]].append((
                    "Piercing Line",
                    f"open({c['open']:.2f}) < prior_low({p['low']:.2f}) AND "
                    f"prior_mid({p_mid:.2f}) < close({c['close']:.2f}) < prior_open({p['open']:.2f})"
                ))

        if i >= 2:
            p2, p1 = bars[i - 2], bars[i - 1]
            c0 = bars[i]
            p2_body = body(p2)
            p1_body = body(p1)
            if (is_bearish(p2) and p2_body > 0 and p1_body <= 0.5 * p2_body
                    and max(p1["open"], p1["close"]) < p2["close"]
                    and is_bullish(c0) and c0["close"] > (p2["open"] + p2["close"]) / 2):
                flags[c0["date"]].append((
                    "Morning Star",
                    f"day-2 long bearish body({p2_body:.2f}) AND day-1 star body({p1_body:.2f}) <= 0.5*day-2 body AND "
                    f"day-1 gapped below day-2 close({p2['close']:.2f}) AND "
                    f"today close({c0['close']:.2f}) > day-2 midpoint({(p2['open'] + p2['close']) / 2:.2f})"
                ))
    return flags


# ------------------------------------------------------------- swing points

def find_swings(bars, k=3):
    """Retrospective structural annotation only (uses bars on both sides
    of a candidate pivot) -- NOT a causal/live signal. Documented as such
    in the report; used purely to describe, after the fact, which prior
    swing highs/lows a given day's price action tested."""
    lows = [b["low"] for b in bars]
    highs = [b["high"] for b in bars]
    n = len(bars)
    swing_lows, swing_highs = [], []
    for i in range(k, n - k):
        window_low = lows[i - k:i + k + 1]
        if lows[i] == min(window_low) and window_low.count(lows[i]) == 1:
            swing_lows.append((i, bars[i]["date"], lows[i]))
        window_high = highs[i - k:i + k + 1]
        if highs[i] == max(window_high) and window_high.count(highs[i]) == 1:
            swing_highs.append((i, bars[i]["date"], highs[i]))
    return swing_lows, swing_highs


def support_resistance_note(i, bars, swing_lows, swing_highs, pct=0.02):
    c = bars[i]
    notes = []
    prior_lows = [s for s in swing_lows if s[0] < i]
    if prior_lows:
        nearest = min(prior_lows, key=lambda s: abs(s[2] - c["low"]))
        if abs(nearest[2] - c["low"]) <= pct * nearest[2]:
            verb = "held" if c["close"] >= nearest[2] else "broke below"
            notes.append(f"tested prior swing low at {nearest[2]:.2f} ({nearest[1]}), {verb}")
    prior_highs = [s for s in swing_highs if s[0] < i]
    if prior_highs:
        nearest = min(prior_highs, key=lambda s: abs(s[2] - c["high"]))
        if abs(nearest[2] - c["high"]) <= pct * nearest[2]:
            verb = "broke above" if c["close"] > nearest[2] else "rejected at"
            notes.append(f"tested prior swing high at {nearest[2]:.2f} ({nearest[1]}), {verb}")
    return "; ".join(notes) if notes else ""


# ------------------------------------------------------------- main analysis

def analyze(symbol, bars):
    closes = [b["close"] for b in bars]
    opens = [b["open"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    vols = [b["volume"] for b in bars]
    dates = [b["date"] for b in bars]

    vol_sma20 = sma(vols, 20)
    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    bb_up, bb_mid, bb_low, bb_std = bollinger(closes, 20, 2)
    macd_line, signal_line, hist = macd(closes)
    rsi14 = rsi(closes, 14)
    patterns = scan_patterns(bars)
    swing_lows, swing_highs = find_swings(bars, k=3)

    rows = []
    for i, b in enumerate(bars):
        vol_ratio = (vols[i] / vol_sma20[i]) if vol_sma20[i] else None

        if sma20[i] is not None:
            pct = (closes[i] - sma20[i]) / sma20[i] * 100
            price_vs_ma20 = f"{pct:+.1f}% vs SMA20({sma20[i]:.2f})"
        else:
            price_vs_ma20 = "insufficient history"

        if sma50[i] is not None:
            pct = (closes[i] - sma50[i]) / sma50[i] * 100
            price_vs_ma50 = f"{pct:+.1f}% vs SMA50({sma50[i]:.2f})"
        else:
            price_vs_ma50 = "insufficient history"

        if bb_std[i] is not None and bb_std[i] > 0:
            z = (closes[i] - bb_mid[i]) / bb_std[i]
            bb_position = "within bands" if -1 <= z <= 1 else f"{z:+.1f} sigma"
        else:
            bb_position = "insufficient history"

        if hist[i] is not None and i > 0 and hist[i - 1] is not None:
            d = hist[i] - hist[i - 1]
            macd_hist_direction = "flat" if abs(d) < 1e-6 else ("rising" if d > 0 else "falling")
        else:
            macd_hist_direction = "n/a"

        if ema20[i] is not None and ema50[i] is not None:
            ema20_vs_ema50 = f"EMA20({ema20[i]:.2f}) {'>' if ema20[i] > ema50[i] else '<'} EMA50({ema50[i]:.2f})"
        else:
            ema20_vs_ema50 = "insufficient history"

        pats = patterns[dates[i]]
        candle_pattern = "; ".join(p[0] for p in pats)
        pattern_criteria_met = " | ".join(p[1] for p in pats)

        rows.append({
            "date": dates[i],
            "open": opens[i], "high": highs[i], "low": lows[i], "close": closes[i],
            "volume": vols[i],
            "vol_20d_avg": round(vol_sma20[i], 0) if vol_sma20[i] else None,
            "vol_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
            "candle_pattern": candle_pattern,
            "pattern_criteria_met": pattern_criteria_met,
            "price_vs_ma20": price_vs_ma20,
            "price_vs_ma50": price_vs_ma50,
            "bb_position": bb_position,
            "macd_hist": round(hist[i], 4) if hist[i] is not None else None,
            "macd_hist_direction": macd_hist_direction,
            "ema20_vs_ema50": ema20_vs_ema50,
            "ema20_gt_ema50": (ema20[i] > ema50[i]) if (ema20[i] is not None and ema50[i] is not None) else None,
            "rsi_14": round(rsi14[i], 1) if rsi14[i] is not None else None,
            "support_resistance_note": support_resistance_note(i, bars, swing_lows, swing_highs),
        })
    return rows


def find_crosses(rows):
    """EMA20/EMA50 golden/death crosses and MACD histogram sign flips,
    over whatever rows are passed in (call with the FULL series, not the
    report-window slice, so a cross just before the window's start is
    still visible)."""
    ema_crosses, macd_crosses = [], []
    prev_ema_state, prev_macd_state = None, None
    for r in rows:
        if r["ema20_gt_ema50"] is not None:
            state = r["ema20_gt_ema50"]
            if prev_ema_state is not None and state != prev_ema_state:
                ema_crosses.append({"date": r["date"], "type": "golden (EMA20>EMA50)" if state else "death (EMA20<EMA50)"})
            prev_ema_state = state
        if r["macd_hist"] is not None:
            state = r["macd_hist"] > 0
            if prev_macd_state is not None and state != prev_macd_state:
                macd_crosses.append({"date": r["date"], "type": "bullish (hist>0)" if state else "bearish (hist<0)"})
            prev_macd_state = state
    return ema_crosses, macd_crosses


def day_offsets(dates, move_start):
    """Trading-day offsets relative to move_start (day 0). If move_start
    isn't itself a trading day in `dates`, offsets are still computed
    relative to its position via nearest-following trading day."""
    if move_start in dates:
        zero_idx = dates.index(move_start)
    else:
        later = [d for d in dates if d > move_start]
        zero_idx = dates.index(later[0]) if later else len(dates) - 1
    return {d: i - zero_idx for i, d in enumerate(dates)}


def first_occurrences(rows, dates, move_start):
    offs = day_offsets(dates, move_start)
    out = {"first_vol_2x": None, "first_pattern": None, "first_bb_oversold": None,
           "first_macd_sign_change": None, "first_ema_golden_cross": None, "breakout_day": None}
    prev_macd_sign = None
    for r in rows:
        d = r["date"]
        if out["first_vol_2x"] is None and r["vol_ratio"] is not None and r["vol_ratio"] >= 2.0:
            out["first_vol_2x"] = {"date": d, "day_offset": offs[d], "vol_ratio": r["vol_ratio"]}
        if out["first_pattern"] is None and r["candle_pattern"]:
            out["first_pattern"] = {"date": d, "day_offset": offs[d], "pattern": r["candle_pattern"]}
        if out["first_bb_oversold"] is None and r["bb_position"] not in ("within bands", "insufficient history"):
            try:
                z = float(r["bb_position"].split(" sigma")[0])
            except ValueError:
                z = None
            if z is not None and z <= -1.5:
                out["first_bb_oversold"] = {"date": d, "day_offset": offs[d], "bb_position": r["bb_position"]}
        if r["macd_hist"] is not None:
            sign = r["macd_hist"] > 0
            if prev_macd_sign is not None and sign and not prev_macd_sign and out["first_macd_sign_change"] is None:
                out["first_macd_sign_change"] = {"date": d, "day_offset": offs[d], "macd_hist": r["macd_hist"]}
            prev_macd_sign = sign
        if out["breakout_day"] is None and r["vol_ratio"] is not None and r["vol_ratio"] >= 2.5 and r["close"] > r["open"]:
            out["breakout_day"] = {"date": d, "day_offset": offs[d], "vol_ratio": r["vol_ratio"]}
    return out


def main():
    data = json.load(open(DATA_PATH))
    out, crosses, first_occ = {}, {}, {}
    for sym in SYMBOLS:
        bars = data["ohlc"][sym]["bars"]
        if sym == "FNEL":
            bars = [b for b in bars if b["date"] >= FNEL_TRIM_START]
        full_rows = analyze(sym, bars)
        ema_crosses, macd_crosses = find_crosses(full_rows)

        report_start = data["ohlc"][sym]["report_start"]
        report_end = data["ohlc"][sym]["report_end"]
        report_rows = [r for r in full_rows if report_start <= r["date"] <= report_end]
        report_dates = [r["date"] for r in report_rows]

        golden_in_window = [c for c in ema_crosses if c["type"].startswith("golden") and report_start <= c["date"] <= report_end]

        out[sym] = report_rows
        crosses[sym] = {"ema_crosses": ema_crosses, "macd_crosses": macd_crosses,
                         "report_start": report_start, "report_end": report_end}
        occ = first_occurrences(report_rows, report_dates, MOVE_START[sym])
        if golden_in_window:
            c0 = golden_in_window[0]
            offs = day_offsets(report_dates, MOVE_START[sym])
            occ["first_ema_golden_cross"] = {"date": c0["date"], "day_offset": offs.get(c0["date"])}
        first_occ[sym] = occ

    json.dump({"rows": out, "crosses": crosses, "first_occurrences": first_occ,
               "move_start": MOVE_START}, open(OUT_PATH, "w"), indent=2)

    for sym in SYMBOLS:
        print(f"\n=== {sym} (report window {crosses[sym]['report_start']} to {crosses[sym]['report_end']}, move start {MOVE_START[sym]}) ===")
        for r in out[sym]:
            print(r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"],
                  r["vol_ratio"], r["candle_pattern"], r["price_vs_ma20"], r["price_vs_ma50"],
                  r["bb_position"], r["macd_hist"], r["macd_hist_direction"], r["ema20_vs_ema50"],
                  r["rsi_14"], r["support_resistance_note"])
        print("First occurrences:", first_occ[sym])


if __name__ == "__main__":
    main()
