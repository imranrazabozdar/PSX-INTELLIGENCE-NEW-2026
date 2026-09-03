#!/usr/bin/env python3
"""Ad hoc technical pre-move analysis for AICL/SHFA, computed locally
(no network) from the real PSX-portal OHLCV already fetched via GitHub
Actions (analysis/fetch_premove_data.py) and saved to premove_data.json.

Implements the classic/textbook rule for each requested indicator/pattern
directly (not this project's own bespoke pattern-engine modules, which
carry PSX-calibrated thresholds tuned for live scanning, not this kind
of literal after-the-fact single-stock study) -- documented inline so
every number in the report is reproducible from this script.
"""
import json
import math

DATA_PATH = str(__import__("pathlib").Path(__file__).parent / "premove_data_raw.json")
OUT_PATH = str(__import__("pathlib").Path(__file__).parent / "premove_analysis.json")


def ema(values, period):
    if len(values) < 1:
        return [None] * len(values)
    k = 2 / (period + 1)
    out = []
    prev = None
    for i, v in enumerate(values):
        if prev is None:
            prev = v  # seed with first value (standard when no true prior EMA exists)
        else:
            prev = v * k + prev * (1 - k)
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
    return upper, mid, lower


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


def scan_patterns(bars):
    """Returns {date: [pattern names]} using classic textbook rules,
    literal, no PSX-scale tuning (see module docstring)."""
    flags = {b["date"]: [] for b in bars}
    n = len(bars)
    for i in range(n):
        c = bars[i]
        b = body(c)
        r = rng(c) or 1e-9

        # Doji: body is a tiny fraction of the day's range
        if b <= 0.1 * r:
            flags[c["date"]].append("Doji")

        # Hammer: small body in the upper third of the range, long lower
        # wick (>=2x body), little/no upper wick
        if b > 0 and lower_wick(c) >= 2 * b and upper_wick(c) <= 0.3 * b and (c["high"] - max(c["open"], c["close"])) <= 0.15 * r:
            flags[c["date"]].append("Hammer")

        if i >= 1:
            p = bars[i - 1]
            # Bullish Engulfing: prior bearish, current bullish, current
            # body fully engulfs prior body
            if is_bearish(p) and is_bullish(c) and c["open"] <= p["close"] and c["close"] >= p["open"]:
                flags[c["date"]].append("Bullish Engulfing")
            # Piercing Line: prior bearish, current opens below prior
            # low, closes above the midpoint of the prior body, below
            # prior open
            p_mid = (p["open"] + p["close"]) / 2
            if is_bearish(p) and is_bullish(c) and c["open"] < p["low"] and p_mid < c["close"] < p["open"]:
                flags[c["date"]].append("Piercing Line")

        if i >= 2:
            p2, p1 = bars[i - 2], bars[i - 1]
            c0 = bars[i]
            # Morning Star: long bearish, small-body (star) gapping down,
            # long bullish closing well into the first candle's body
            p2_body = body(p2)
            p1_body = body(p1)
            c0_body = body(c0)
            if (is_bearish(p2) and p2_body > 0 and p1_body <= 0.5 * p2_body
                    and max(p1["open"], p1["close"]) < p2["close"]
                    and is_bullish(c0) and c0["close"] > (p2["open"] + p2["close"]) / 2):
                flags[c0["date"]].append("Morning Star")
    return flags


def analyze(symbol, bars):
    closes = [b["close"] for b in bars]
    vols = [b["volume"] for b in bars]
    dates = [b["date"] for b in bars]

    vol_sma20 = sma(vols, 20)
    vol_sma50 = sma(vols, 50)
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    bb_up, bb_mid, bb_low = bollinger(closes, 20, 2)
    macd_line, signal_line, hist = macd(closes)
    rsi14 = rsi(closes, 14)
    patterns = scan_patterns(bars)

    rows = []
    for i, b in enumerate(bars):
        vol_ratio_20 = (vols[i] / vol_sma20[i]) if vol_sma20[i] else None
        vol_ratio_50 = (vols[i] / vol_sma50[i]) if vol_sma50[i] else None
        vol_flag = None
        if vol_ratio_20 is not None:
            if vol_ratio_20 >= 3:
                vol_flag = f">3x 20d avg ({vol_ratio_20:.2f}x)"
            elif vol_ratio_20 >= 2:
                vol_flag = f">2x 20d avg ({vol_ratio_20:.2f}x)"
            elif vol_ratio_20 >= 1.5:
                vol_flag = f">1.5x 20d avg ({vol_ratio_20:.2f}x)"

        bb_flag = None
        if bb_low[i] is not None:
            if closes[i] <= bb_low[i]:
                bb_flag = "at/below lower band (oversold)"
            elif closes[i] <= bb_low[i] * 1.02:
                bb_flag = "near lower band"

        rows.append({
            "date": dates[i], "close": closes[i], "volume": vols[i],
            "vol_ratio_20d": round(vol_ratio_20, 2) if vol_ratio_20 else None,
            "vol_ratio_50d": round(vol_ratio_50, 2) if vol_ratio_50 else None,
            "vol_flag": vol_flag,
            "patterns": patterns[dates[i]],
            "ema20": round(ema20[i], 2) if ema20[i] else None,
            "ema50": round(ema50[i], 2) if ema50[i] else None,
            "ema20_gt_ema50": (ema20[i] > ema50[i]) if (ema20[i] and ema50[i]) else None,
            "bb_lower": round(bb_low[i], 2) if bb_low[i] else None,
            "bb_flag": bb_flag,
            "macd_hist": round(hist[i], 4) if hist[i] is not None else None,
            "rsi14": round(rsi14[i], 1) if rsi14[i] is not None else None,
        })
    return rows


def find_crosses(rows):
    """EMA20/EMA50 golden/death crosses and MACD histogram sign flips,
    over whatever rows are passed in (call with the FULL series, not the
    report-window slice, so a cross just before the window's start is
    still visible)."""
    ema_crosses, macd_crosses = [], []
    prev_ema_state = None
    prev_macd_state = None
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


def main():
    data = json.load(open(DATA_PATH))
    out = {}
    crosses = {}
    for sym in ["AICL", "SHFA"]:
        bars = data["ohlc"][sym]["bars"]
        full_rows = analyze(sym, bars)
        ema_crosses, macd_crosses = find_crosses(full_rows)
        report_start = data["ohlc"][sym]["report_start"]
        report_end = data["ohlc"][sym]["report_end"]
        report_rows = [r for r in full_rows if report_start <= r["date"] <= report_end]
        out[sym] = report_rows
        crosses[sym] = {"ema_crosses": ema_crosses, "macd_crosses": macd_crosses,
                         "report_start": report_start, "report_end": report_end}

    json.dump({"rows": out, "crosses": crosses},
              open(OUT_PATH, "w"), indent=2)

    for sym in ["AICL", "SHFA"]:
        print(f"\n=== {sym} (report window {crosses[sym]['report_start']} to {crosses[sym]['report_end']}) ===")
        for r in out[sym]:
            flags = []
            if r["vol_flag"]: flags.append(r["vol_flag"])
            if r["patterns"]: flags.append(",".join(r["patterns"]))
            if r["bb_flag"]: flags.append(r["bb_flag"])
            print(r["date"], r["close"], r["volume"], f"EMA20={r['ema20']} EMA50={r['ema50']} "
                  f"MACDh={r['macd_hist']} RSI={r['rsi14']}", " | ".join(flags))
        print("EMA crosses (full lookback):", crosses[sym]["ema_crosses"])
        print("MACD hist sign flips (full lookback):", crosses[sym]["macd_crosses"])


if __name__ == "__main__":
    main()
