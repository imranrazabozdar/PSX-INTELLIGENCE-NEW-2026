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

SYMBOLS = ["AICL", "SHFA", "THCCL", "FNEL", "MDTL", "FPJM", "BNL", "DSIL", "SYM", "PREMA", "JSBL", "ILP"]
MOVE_START = {
    "AICL": "2026-07-23",
    "SHFA": "2026-06-12",
    "THCCL": "2026-06-30",
    "FNEL": "2026-04-06",
    "MDTL": "2026-07-23",
    "FPJM": "2026-08-13",
    "BNL": "2025-05-09",
    "DSIL": "2026-07-31",
    "SYM": "2026-04-30",
    "PREMA": "2026-03-30",
    "JSBL": "2026-05-19",
    "ILP": "2026-06-02",
}

# FNEL's fetched series shows an abrupt ~90% single-day price adjustment
# on 2026-02-02 (close 17.70 on 2026-01-30 -> 1.65 on 2026-02-02, volume
# 191M vs a typical 10-20M) -- the signature of a large bonus/rights
# share issue on PSX rather than a real one-day price return, and not a
# wrong-scrip mixup (the post-2026-02-02 trajectory continues organically
# at the new scale and its window-end values, 1.16 on 04-06 -> 1.74 on
# 04-24, match the user-given reference prices almost exactly). This was
# originally handled as a FNEL-specific hardcoded trim; as of this round
# it's superseded by the general detect_price_cliffs()/trim_to_last_cliff()
# mechanism below, applied to every symbol (asserted in main() to still
# find this exact FNEL cliff, so the generalization doesn't silently
# change the already-shipped FNEL finding).
FNEL_KNOWN_CLIFF_DATE = "2026-02-02"


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


def typical_price(b):
    return (b["high"] + b["low"] + b["close"]) / 3


def obv(bars):
    """On-Balance Volume: cumulative volume, added on an up close, subtracted
    on a down close, unchanged on a flat close. Starts at 0 (bar 0 contributes
    no direction yet, since there's no prior close to compare against)."""
    out = [0]
    for i in range(1, len(bars)):
        prev_val = out[-1]
        if bars[i]["close"] > bars[i - 1]["close"]:
            out.append(prev_val + bars[i]["volume"])
        elif bars[i]["close"] < bars[i - 1]["close"]:
            out.append(prev_val - bars[i]["volume"])
        else:
            out.append(prev_val)
    return out


def ad_line(bars):
    """Accumulation/Distribution Line: cumulative money-flow-volume, where
    each bar's money flow multiplier reflects WHERE in its own high-low
    range the close sits (+1 = closed at the high, -1 = closed at the low,
    0 = closed at the midpoint) -- unlike OBV, which only looks at
    close-to-close direction. A high-low range of 0 (no intrabar range)
    contributes a multiplier of 0, not a division error."""
    out = []
    cum = 0.0
    for b in bars:
        rng = b["high"] - b["low"]
        mfm = ((b["close"] - b["low"]) - (b["high"] - b["close"])) / rng if rng > 0 else 0.0
        cum += mfm * b["volume"]
        out.append(cum)
    return out


def mfi(bars, period=14):
    """Money Flow Index: volume-weighted RSI. Typical price up day -> that
    day's (typical_price * volume) counts as positive money flow; down day
    -> negative. MFI = 100 - 100/(1 + positive_sum/negative_sum) over the
    trailing `period` days. Uses simple (non-Wilder) rolling sums, the
    standard MFI convention, distinct from this module's Wilder-smoothed
    RSI -- documented here since the two indicators use different
    smoothing by design, not an inconsistency."""
    n = len(bars)
    out = [None] * n
    tp = [typical_price(b) for b in bars]
    raw_mf = [tp[i] * bars[i]["volume"] for i in range(n)]
    pos = [0.0] * n
    neg = [0.0] * n
    for i in range(1, n):
        if tp[i] > tp[i - 1]:
            pos[i] = raw_mf[i]
        elif tp[i] < tp[i - 1]:
            neg[i] = raw_mf[i]
    for i in range(period, n):
        pos_sum = sum(pos[i - period + 1:i + 1])
        neg_sum = sum(neg[i - period + 1:i + 1])
        if neg_sum == 0:
            out[i] = 100.0
        else:
            mr = pos_sum / neg_sum
            out[i] = 100 - (100 / (1 + mr))
    return out


def atr(bars, period=14):
    """Average True Range, Wilder-smoothed (simple average of the first
    `period` true-range values, then Wilder smoothing thereafter -- same
    smoothing convention already used for this module's RSI)."""
    n = len(bars)
    tr = [None] * n
    tr[0] = bars[0]["high"] - bars[0]["low"]
    for i in range(1, n):
        tr[i] = max(
            bars[i]["high"] - bars[i]["low"],
            abs(bars[i]["high"] - bars[i - 1]["close"]),
            abs(bars[i]["low"] - bars[i - 1]["close"]),
        )
    out = [None] * n
    if n <= period:
        return out
    avg = sum(tr[1:period + 1]) / period
    out[period] = avg
    for i in range(period + 1, n):
        avg = (avg * (period - 1) + tr[i]) / period
        out[i] = avg
    return out


def anchored_vwap(rows):
    """Cumulative VWAP anchored at the FIRST row passed in (i.e. the
    report window's start), not a true intraday VWAP -- only daily OHLCV
    is available, so "VWAP" here means the volume-weighted average of each
    day's typical price ((H+L+C)/3), accumulated from the window's first
    day forward. This is an approximation, documented as such in the
    report's method note; call this with the already-windowed report_rows
    (not the full lookback series) so the anchor lands on the window's own
    first day."""
    out = []
    cum_pv, cum_v = 0.0, 0.0
    for r in rows:
        tp = (r["high"] + r["low"] + r["close"]) / 3
        cum_pv += tp * r["volume"]
        cum_v += r["volume"]
        out.append(cum_pv / cum_v if cum_v else None)
    return out


def ichimoku(bars, tenkan_period=9, kijun_period=26, senkou_b_period=52, displacement=26):
    """Standard-period Ichimoku Cloud. Tenkan-sen/Kijun-sen are the
    midpoint of the highest-high/lowest-low over their lookback; Senkou
    Span A/B are the forward-plotted cloud boundaries (displaced +26
    periods, i.e. index i's cloud-on-the-chart value is stored at
    out["senkou_a"][i + displacement]); Chikou Span is the close plotted
    26 periods back (out["chikou"][i - displacement] = close[i]). Because
    of that forward shift, the cloud values covering the LAST `displacement`
    days of any report window are necessarily produced from Tenkan/Kijun
    computed inside the window itself, not from data further back --
    documented in the report's method note as "provisional/still being
    drawn in" for those trailing days, same caveat as real charting
    platforms show for the unclosed forward cloud."""
    n = len(bars)
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    closes = [b["close"] for b in bars]

    def midpoint_channel(period):
        out = [None] * n
        for i in range(n):
            if i + 1 < period:
                continue
            window_h = highs[i + 1 - period:i + 1]
            window_l = lows[i + 1 - period:i + 1]
            out[i] = (max(window_h) + min(window_l)) / 2
        return out

    tenkan = midpoint_channel(tenkan_period)
    kijun = midpoint_channel(kijun_period)
    senkou_b_base = midpoint_channel(senkou_b_period)

    senkou_a = [None] * n
    senkou_b = [None] * n
    for i in range(n):
        if tenkan[i] is not None and kijun[i] is not None:
            target = i + displacement
            if target < n:
                senkou_a[target] = (tenkan[i] + kijun[i]) / 2
        if senkou_b_base[i] is not None:
            target = i + displacement
            if target < n:
                senkou_b[target] = senkou_b_base[i]

    chikou = [None] * n
    for i in range(n):
        target = i - displacement
        if target >= 0:
            chikou[target] = closes[i]

    return {"tenkan": tenkan, "kijun": kijun, "senkou_a": senkou_a,
            "senkou_b": senkou_b, "chikou": chikou}


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


# ------------------------------------------------------- price-cliff detector

def detect_price_cliffs(bars, drop_threshold=0.30, vol_multiplier=3, trailing_window=10):
    """General discontinuity check, applied to every symbol (not just
    FNEL) per this round's instruction: flags a day whose close DROPS
    >30% from the prior close AND whose volume is >3x the trailing
    10-bar average volume -- the same signature (large price cliff +
    abnormal volume) that caught FNEL's real 2026-02-02 bonus/rights
    adjustment. Deliberately one-sided (drops only, not any large move in
    either direction): a bonus or rights share issue mechanically dilutes
    the per-share price DOWN, it never explains a price rising sharply --
    an upward 30%+ day with high volume (FNEL's real 2026-04-08 breakout
    included) is exactly the kind of genuine pre-move signal this whole
    study exists to find, and must never be trimmed away as if it were a
    data artifact. A plain >30% drop without the volume confirmation is
    left alone too (that's just real volatility, not a capital-structure
    artifact); requiring both keeps this from false-flagging an ordinary
    limit-down session."""
    cliffs = []
    for i in range(1, len(bars)):
        prev, cur = bars[i - 1], bars[i]
        if not prev["close"]:
            continue
        ratio = cur["close"] / prev["close"]
        if ratio > (1 - drop_threshold):
            continue
        window = bars[max(0, i - trailing_window):i]
        vols = [b["volume"] for b in window if b["volume"]]
        avg_vol = sum(vols) / len(vols) if vols else None
        if avg_vol and cur["volume"] > vol_multiplier * avg_vol:
            cliffs.append({
                "date": cur["date"], "prev_date": prev["date"],
                "prev_close": prev["close"], "close": cur["close"],
                "ratio": round(ratio, 4), "volume": cur["volume"],
                "avg_vol_trailing10": round(avg_vol, 0),
            })
    return cliffs


def trim_to_last_cliff(bars, cliffs):
    """If any cliffs were found, keep only bars from the LAST cliff's
    date onward (the cliff day itself already reflects the new,
    post-adjustment scale) so no moving-average/volatility calc spans
    the discontinuity. Returns (trimmed_bars, applied_cliff_or_None)."""
    if not cliffs:
        return bars, None
    last = cliffs[-1]
    trimmed = [b for b in bars if b["date"] >= last["date"]]
    return trimmed, last


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

    mfi14 = mfi(bars, 14)
    obv_vals = obv(bars)
    ad_vals = ad_line(bars)
    atr14 = atr(bars, 14)
    ich = ichimoku(bars)

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

        # Ichimoku cloud position at this bar (senkou_a/b already carry the
        # +26 forward displacement baked in by ichimoku(), so index i here
        # is the cloud value actually plotted over bar i on the chart).
        sa, sb = ich["senkou_a"][i], ich["senkou_b"][i]
        if sa is not None and sb is not None:
            cloud_top, cloud_bottom = max(sa, sb), min(sa, sb)
            if closes[i] > cloud_top:
                cloud_position = "above cloud"
            elif closes[i] < cloud_bottom:
                cloud_position = "below cloud"
            else:
                cloud_position = "inside cloud"
            cloud_color = "bullish (green)" if sa > sb else ("bearish (red)" if sa < sb else "flat")
            cloud_thickness = round(abs(sa - sb), 2)
            ichimoku_note = f"{cloud_position}, cloud {cloud_color}, thickness {cloud_thickness:.2f}"
        else:
            ichimoku_note = "cloud not yet formed (insufficient history)"

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
            "mfi_14": round(mfi14[i], 1) if mfi14[i] is not None else None,
            "obv": round(obv_vals[i], 0),
            "ad_line": round(ad_vals[i], 0),
            "atr_14": round(atr14[i], 4) if atr14[i] is not None else None,
            "tenkan_sen": round(ich["tenkan"][i], 2) if ich["tenkan"][i] is not None else None,
            "kijun_sen": round(ich["kijun"][i], 2) if ich["kijun"][i] is not None else None,
            "ichimoku_note": ichimoku_note,
        })

    # Flow divergence: does OBV/A-D Line move opposite to price on a given
    # day? This is the "quiet accumulation/distribution" signal that a
    # plain close-to-close volume ratio can't show -- price and volume
    # both look ordinary, but the flow indicator is quietly leaning the
    # other way. Computed as a second pass since it needs the prior row's
    # already-rounded obv/ad_line values for a stable, reproducible read.
    for i in range(1, len(rows)):
        price_dir = "up" if rows[i]["close"] > rows[i - 1]["close"] else ("down" if rows[i]["close"] < rows[i - 1]["close"] else "flat")
        obv_dir = "up" if rows[i]["obv"] > rows[i - 1]["obv"] else ("down" if rows[i]["obv"] < rows[i - 1]["obv"] else "flat")
        ad_dir = "up" if rows[i]["ad_line"] > rows[i - 1]["ad_line"] else ("down" if rows[i]["ad_line"] < rows[i - 1]["ad_line"] else "flat")
        notes = []
        if price_dir != "flat" and obv_dir != "flat" and price_dir != obv_dir:
            notes.append(f"OBV diverges from price (price {price_dir}, OBV {obv_dir})")
        if price_dir != "flat" and ad_dir != "flat" and price_dir != ad_dir:
            notes.append(f"A/D Line diverges from price (price {price_dir}, A/D {ad_dir})")
        if obv_dir != "flat" and ad_dir != "flat" and obv_dir != ad_dir:
            notes.append(f"OBV and A/D Line disagree with each other (OBV {obv_dir}, A/D {ad_dir})")
        rows[i]["flow_divergence"] = "; ".join(notes) if notes else ""
    if rows:
        rows[0]["flow_divergence"] = ""
    return rows


def find_crosses(rows):
    """EMA20/EMA50 golden/death crosses, MACD histogram sign flips, and
    Tenkan-sen/Kijun-sen crosses, over whatever rows are passed in (call
    with the FULL series, not the report-window slice, so a cross just
    before the window's start is still visible)."""
    ema_crosses, macd_crosses, tk_crosses = [], [], []
    prev_ema_state, prev_macd_state, prev_tk_state = None, None, None
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
        if r["tenkan_sen"] is not None and r["kijun_sen"] is not None:
            state = r["tenkan_sen"] > r["kijun_sen"]
            if prev_tk_state is not None and state != prev_tk_state:
                tk_crosses.append({"date": r["date"], "type": "bullish (Tenkan>Kijun)" if state else "bearish (Tenkan<Kijun)"})
            prev_tk_state = state
    return ema_crosses, macd_crosses, tk_crosses


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
    out, full_out, crosses, first_occ, cliffs_applied = {}, {}, {}, {}, {}
    for sym in SYMBOLS:
        raw_bars = data["ohlc"][sym]["bars"]

        cliffs = detect_price_cliffs(raw_bars)
        bars, applied_cliff = trim_to_last_cliff(raw_bars, cliffs)
        cliffs_applied[sym] = {"all_cliffs_detected": cliffs, "trim_applied": applied_cliff}

        if sym == "FNEL":
            assert applied_cliff is not None and applied_cliff["date"] == FNEL_KNOWN_CLIFF_DATE, (
                f"General cliff detector no longer reproduces the known FNEL 2026-02-02 finding "
                f"(got {applied_cliff}) -- investigate before trusting this run's output.")

        full_rows = analyze(sym, bars)
        ema_crosses, macd_crosses, tk_crosses = find_crosses(full_rows)

        report_start = data["ohlc"][sym]["report_start"]
        report_end = data["ohlc"][sym]["report_end"]
        report_rows = [r for r in full_rows if report_start <= r["date"] <= report_end]
        report_dates = [r["date"] for r in report_rows]

        # VWAP is anchored at the report window's own start (see
        # anchored_vwap()'s docstring) -- computed here, after windowing,
        # not inside analyze(), since it isn't a fixed-lookback indicator.
        vwap_vals = anchored_vwap(report_rows)
        for r, vw in zip(report_rows, vwap_vals):
            r["vwap"] = round(vw, 2) if vw is not None else None
            r["price_vs_vwap"] = ("above" if r["close"] > vw else ("below" if r["close"] < vw else "at")) if vw is not None else "n/a"

        golden_in_window = [c for c in ema_crosses if c["type"].startswith("golden") and report_start <= c["date"] <= report_end]
        tk_in_window = [c for c in tk_crosses if report_start <= c["date"] <= report_end]

        out[sym] = report_rows
        full_out[sym] = full_rows
        crosses[sym] = {"ema_crosses": ema_crosses, "macd_crosses": macd_crosses,
                         "tk_crosses": tk_crosses, "tk_crosses_in_window": tk_in_window,
                         "report_start": report_start, "report_end": report_end}
        occ = first_occurrences(report_rows, report_dates, MOVE_START[sym])
        if golden_in_window:
            c0 = golden_in_window[0]
            offs = day_offsets(report_dates, MOVE_START[sym])
            occ["first_ema_golden_cross"] = {"date": c0["date"], "day_offset": offs.get(c0["date"])}
        first_occ[sym] = occ

    json.dump({"rows": out, "full_rows": full_out, "crosses": crosses,
               "first_occurrences": first_occ, "move_start": MOVE_START,
               "price_cliffs": cliffs_applied},
              open(OUT_PATH, "w"), indent=2)

    for sym in SYMBOLS:
        print(f"\n=== {sym} (report window {crosses[sym]['report_start']} to {crosses[sym]['report_end']}, move start {MOVE_START[sym]}) ===")
        for r in out[sym]:
            print(r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"],
                  r["vol_ratio"], r["candle_pattern"], r["price_vs_ma20"], r["price_vs_ma50"],
                  r["bb_position"], r["macd_hist"], r["macd_hist_direction"], r["ema20_vs_ema50"],
                  r["rsi_14"], r["support_resistance_note"], r["mfi_14"], r["obv"], r["ad_line"],
                  r["atr_14"], r["vwap"], r["price_vs_vwap"], r["ichimoku_note"], r["flow_divergence"])
        print("First occurrences:", first_occ[sym])


if __name__ == "__main__":
    main()
