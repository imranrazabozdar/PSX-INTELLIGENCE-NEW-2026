#!/usr/bin/env python3
"""
psx_brain.py — the analyst. Turns computed indicators into a verdict,
reasoning, and a trade plan. No API, no cost, runs offline.

Encodes the weighting used throughout our analysis:
  trend + money flow  >  structure/levels  >  momentum  >  candlesticks
and flags the specific traps (weekly accumulation vs daily distribution).
"""

import numpy as np
import pandas as pd

from psx_report import (adx_dmi, atr, bollinger, donchian, handle_partial_bar,
                        ichimoku, keltner,
                        macd, mfi, money_flow, moving_avgs, obv, vpt,
                        force_index, pattern_report, regression_quality,
                        rsi, supertrend, to_weekly, zscore)


def _vol_score(df):
    v, c = df.volume, df.close
    n = min(20, len(df) - 1)
    r = df.tail(n)
    up = r.loc[r.close >= r.close.shift(), "volume"].sum()
    dn = r.loc[r.close < r.close.shift(), "volume"].sum()
    share = up / (up + dn) * 100 if (up + dn) else 50
    ob, vp, fi = obv(df), vpt(df), force_index(df)
    _, cmf, _ = money_flow(df)

    def sl(s, k=10):
        s = s.dropna()
        if len(s) < k + 1:
            return 0
        ch = (s.iloc[-1] - s.iloc[-k-1]) / (abs(s.iloc[-k-1]) or 1)
        return 1 if ch > .02 else -1 if ch < -.02 else 0

    sc = sl(ob) + sl(vp)
    sc += 1 if fi.iloc[-1] > 0 else -1
    sc += 1 if cmf.iloc[-1] > .05 else -1 if cmf.iloc[-1] < -.05 else 0
    sc += 1 if share > 55 else -1 if share < 45 else 0
    return sc, share, cmf.iloc[-1]


def analyse(symbol, daily, bench=None, partial="drop"):
    """Returns a dict: verdict, score, reasoning bullets, levels, trade plan."""
    daily, partial_note = handle_partial_bar(daily, partial)
    wk = to_weekly(daily)
    last = daily.close.iloc[-1]

    # --- raw state -------------------------------------------------------
    d_adx, d_pdi, d_mdi = adx_dmi(daily)
    w_adx, w_pdi, w_mdi = adx_dmi(wk)
    d_st, d_dir = supertrend(daily)
    w_st, w_dir = supertrend(wk)
    d_bu, d_bm, d_bl = bollinger(daily.close)
    d_ku, d_km, d_kl = keltner(daily)
    du, dl, dm = donchian(daily)
    tk, kj, sa, sb = ichimoku(daily)
    wtk, wkj, wsa, wsb = ichimoku(wk)
    d_rsi, d_mfi = rsi(daily.close).iloc[-1], mfi(daily).iloc[-1]
    d_macd, d_sig, d_hist = [s.iloc[-1] for s in macd(daily.close)]
    mas = moving_avgs(daily.close)
    at = atr(daily).iloc[-1]
    rq = regression_quality(daily.close) or {"r2": 0, "slope_pct_ann": 0}
    z = zscore(daily.close)

    d_vol, d_share, d_cmf = _vol_score(daily)
    w_vol, w_share, w_cmf = _vol_score(wk)

    cl_lo, cl_hi = sorted([sa.iloc[-1], sb.iloc[-1]])
    wcl_lo, wcl_hi = sorted([wsa.iloc[-1], wsb.iloc[-1]])
    cloud = 1 if last > cl_hi else -1 if last < cl_lo else 0
    wcloud = 1 if last > wcl_hi else -1 if last < wcl_lo else 0
    d_up, w_up = int(d_dir.iloc[-1] == 1), int(w_dir.iloc[-1] == 1)
    squeeze = d_bu.iloc[-1] < d_ku.iloc[-1] and d_bl.iloc[-1] > d_kl.iloc[-1]
    vol_ratio = daily.volume.iloc[-1] / daily.volume.rolling(20).mean().iloc[-1]

    stacked = ("bull" if mas["SMA20"].iloc[-1] > mas["SMA50"].iloc[-1] >
               (mas["SMA200"].iloc[-1] if not pd.isna(mas["SMA200"].iloc[-1]) else -1e9)
               else "bear" if mas["SMA20"].iloc[-1] < mas["SMA50"].iloc[-1] <
               (mas["SMA200"].iloc[-1] if not pd.isna(mas["SMA200"].iloc[-1]) else 1e9)
               else "mixed")

    # --- scoring ---------------------------------------------------------
    s = 0.0
    bull, bear, flags = [], [], []

    # money flow — heaviest
    s += w_vol * 1.6
    s += d_vol * 1.2
    if w_vol >= 3:
        bull.append(f"Weekly accumulation confirmed ({w_vol:+d}/6) — "
                    f"{w_share:.0f}% of volume on up-weeks")
    if w_vol <= -3:
        bear.append(f"Weekly distribution ({w_vol:+d}/6) — sellers control the tape")
    if d_vol >= 3:
        bull.append(f"Daily flow positive ({d_vol:+d}/6) — near-term buying present")
    if d_vol <= -3:
        bear.append(f"Daily distribution ({d_vol:+d}/6), CMF {d_cmf:+.2f} — "
                    f"being sold right now")
    if w_vol >= 3 and d_vol <= -2:
        flags.append("TRAP PATTERN: strong weekly accumulation but active daily "
                     "distribution. Longer-term holders built a position; "
                     "near-term sellers are winning. Wait for the daily to stop bleeding.")
        s -= 3

    # trend
    s += 4 * d_up + 3 * w_up + 3 * cloud + 2 * wcloud
    if d_up:
        bull.append(f"Daily Supertrend UP (line {d_st.iloc[-1]:.2f}) — short-term trend turned")
    else:
        bear.append(f"Daily Supertrend DOWN — needs a close above {d_st.iloc[-1]:.2f} to flip")
    if w_up:
        bull.append(f"Weekly Supertrend UP (line {w_st.iloc[-1]:.2f}) — higher-timeframe intact")
    else:
        bear.append("Weekly Supertrend DOWN — the dominant trend is still against you")
    if cloud == 1:
        bull.append(f"Above the daily Ichimoku cloud ({cl_lo:.2f}-{cl_hi:.2f})")
    elif cloud == -1:
        bear.append(f"Below the daily cloud ({cl_lo:.2f}-{cl_hi:.2f}) — overhead resistance")
    else:
        flags.append(f"Price inside the daily cloud ({cl_lo:.2f}-{cl_hi:.2f}) — "
                     f"one decisive close from resolving. Watch closely.")
    if stacked == "bull":
        bull.append("Moving averages bull-stacked (20>50>200)")
    elif stacked == "bear":
        bear.append("Moving averages bear-stacked (20<50<200)")

    # trend strength
    adx = d_adx.iloc[-1]
    if adx < 20:
        flags.append(f"ADX {adx:.0f} — no trend exists. Trend-following entries "
                     f"have negative expectancy here; this is a range.")
    elif d_mdi.iloc[-1] > d_pdi.iloc[-1] and adx > 25:
        bear.append(f"ADX {adx:.0f} rising with -DI {d_mdi.iloc[-1]:.0f} > "
                    f"+DI {d_pdi.iloc[-1]:.0f} — downtrend strengthening. Do not buy dips.")
        s -= 3
    elif d_pdi.iloc[-1] > d_mdi.iloc[-1] and adx > 25:
        bull.append(f"ADX {adx:.0f} with +DI {d_pdi.iloc[-1]:.0f} dominant — "
                    f"genuine uptrend in force")
        s += 2
    s += 2 if d_pdi.iloc[-1] > d_mdi.iloc[-1] else -2

    # structure
    if squeeze:
        flags.append("Bollinger/Keltner SQUEEZE ON — volatility compressed, a move "
                     "is loading. Direction unresolved; squeezes are direction-agnostic.")
    if rq["r2"] > .7 and rq["slope_pct_ann"] > 0:
        bull.append(f"Regression R2 {rq['r2']:.2f} — clean, orderly advance "
                    f"({rq['slope_pct_ann']:+.0f}%/yr)")
        s += 1
    elif rq["r2"] > .7 and rq["slope_pct_ann"] < 0:
        bear.append(f"Regression R2 {rq['r2']:.2f} — a clean, persistent DECLINE "
                    f"({rq['slope_pct_ann']:+.0f}%/yr). Orderly selling, not a base.")
        s -= 2
    elif rq["r2"] < .3:
        flags.append(f"Regression R2 {rq['r2']:.2f} — choppy, no reliable trend structure")
    if z < -2:
        flags.append(f"Z-score {z:+.2f} — statistically stretched low, "
                     f"bounce-prone but not a reversal signal on its own")
    elif z > 2:
        flags.append(f"Z-score {z:+.2f} — stretched high, poor risk/reward for new entries")

    # momentum
    if 40 <= d_rsi <= 60:
        s += 2
    if d_rsi < 35:
        flags.append(f"RSI {d_rsi:.0f} oversold — but oversold in a downtrend "
                     f"is a description, not a signal")
    if d_mfi < 40 and d_rsi > 50:
        flags.append(f"MFI {d_mfi:.0f} vs RSI {d_rsi:.0f} — money flow not "
                     f"confirming price momentum")
    if d_hist > 0 and d_macd > d_sig and d_macd > 0:
        bull.append("MACD above signal and above zero — momentum positive")
    elif d_hist > 0 and d_macd > d_sig:
        flags.append("MACD crossed up but still below zero — improving, "
                     "not yet confirmed")
    elif d_hist < 0:
        bear.append(f"MACD below signal (hist {d_hist:+.2f})")

    # volume participation
    if vol_ratio < 0.5:
        flags.append(f"Volume {vol_ratio:.2f}x average — very thin participation. "
                     f"Moves on this volume are unreliable.")
    elif vol_ratio > 1.5:
        bull.append(f"Volume {vol_ratio:.1f}x average — participation confirming")

    # relative strength
    rs_note = None
    if bench is not None:
        try:
            b = bench.reindex(daily.index).ffill()
            n = min(63, len(daily) - 1)
            sr = (last / daily.close.iloc[-n] - 1) * 100
            br = (b.iloc[-1] / b.iloc[-n] - 1) * 100
            ex = sr - br
            rs_note = f"3m: stock {sr:+.1f}% vs KSE {br:+.1f}% (excess {ex:+.1f}%)"
            if ex > 5:
                bull.append(f"Outperforming the index by {ex:+.1f}% over 3 months")
                s += 2
            elif ex < -5:
                bear.append(f"Underperforming the index by {ex:+.1f}% — relative weakness")
                s -= 2
        except Exception:
            pass

    # liquidity — the model has no view on tradability, so say it plainly
    avg_val = (daily.close * daily.volume).rolling(20).mean().iloc[-1]
    thin = False
    if avg_val < 1e6:
        thin = True
        flags.append(f"THIN: ~Rs {avg_val/1e6:.2f}M traded per day. Slippage and "
                     f"gap risk are real here — size far smaller than the model suggests.")
        s -= 2

    # --- verdict ---------------------------------------------------------
    if s >= 14 and d_up and cloud >= 0:
        verdict, cls = "BUY", "buy"
    elif s >= 7:
        verdict, cls = "BUY ON TRIGGER", "trigger"
    elif s >= 0:
        verdict, cls = "WAIT", "wait"
    else:
        verdict, cls = "AVOID", "avoid"

    conf = int(max(5, min(95, 50 + s * 2.2)))
    if verdict == "BUY ON TRIGGER":
        conf = min(conf, 74)     # never outrank a confirmed BUY
    elif verdict == "WAIT":
        conf = min(conf, 55)
    elif verdict == "AVOID":
        conf = min(conf, 40)
    if thin:
        conf = min(conf, 60)

    # --- levels & plan ---------------------------------------------------
    trigger = float(d_st.iloc[-1]) if not d_up else float(du.iloc[-1])
    stop = float(min(d_bl.iloc[-1], daily.low.tail(10).min()))
    if last - stop <= 0:
        stop = last - 2 * at
    risk = (last - stop) / last * 100
    t1, t2, t3 = float(d_bm.iloc[-1]), float(du.iloc[-1]), float(d_bu.iloc[-1])
    if t1 <= last:
        t1 = last + 1.5 * at
    if t2 <= t1:
        t2 = last + 3 * at
    if t3 <= t2:
        t3 = last + 5 * at
    rr = (t2 - last) / (last - stop) if last > stop else 0
    size = round(min(7, 0.5 / max(risk, 0.5) * 100), 1)

    return {
        "symbol": symbol, "price": round(last, 2), "verdict": verdict,
        "class": cls, "score": round(s, 1), "confidence": conf,
        "bull": bull, "bear": bear, "flags": flags,
        "rs": rs_note, "partial": partial_note, "thin": thin,
        "levels": {"trigger": round(trigger, 2), "stop": round(stop, 2),
                   "t1": round(t1, 2), "t2": round(t2, 2), "t3": round(t3, 2),
                   "risk_pct": round(risk, 1), "rr": round(rr, 2),
                   "size_pct": size},
        "state": {"wVol": w_vol, "dVol": d_vol, "dTrend": "UP" if d_up else "DOWN",
                  "wTrend": "UP" if w_up else "DOWN",
                  "cloud": {1: "above", 0: "in", -1: "below"}[cloud],
                  "rsi": round(d_rsi), "adx": round(adx), "squeeze": bool(squeeze),
                  "volx": round(vol_ratio, 2)},
    }


def compare(results):
    """Rank several analysed stocks and explain the ordering."""
    if not results:
        return {"ranked": [], "commentary": "No stocks to compare."}
    r = sorted(results, key=lambda x: x["score"], reverse=True)
    best, worst = r[0], r[-1]

    lines = [f"Ranked {len(r)} stocks by weighted setup quality.", ""]
    lines.append(f"STRONGEST: {best['symbol']} ({best['verdict']}, "
                 f"score {best['score']}, confidence {best['confidence']}/100).")
    if best["bull"]:
        lines.append(f"  Why: {best['bull'][0]}")
    if best["verdict"] in ("BUY ON TRIGGER", "WAIT"):
        lines.append(f"  Not yet actionable — needs a close above "
                     f"{best['levels']['trigger']}.")

    trig = [x for x in r if x["verdict"] == "BUY ON TRIGGER"]
    if trig:
        lines.append("")
        lines.append("AWAITING TRIGGER: " + ", ".join(
            f"{x['symbol']} (>{x['levels']['trigger']})" for x in trig[:6]))

    traps = [x for x in r if any("TRAP PATTERN" in f for f in x["flags"])]
    if traps:
        lines.append("")
        lines.append("TRAP PATTERN (weekly accumulation, daily distribution) — "
                     "wait for the daily to turn: " +
                     ", ".join(x["symbol"] for x in traps))

    avoid = [x for x in r if x["verdict"] == "AVOID"]
    if avoid:
        lines.append("")
        lines.append("AVOID: " + ", ".join(x["symbol"] for x in avoid) +
                     ". Trend and flow both negative — no edge in owning these.")

    n_up = sum(1 for x in r if x["state"]["dTrend"] == "UP")
    n_above = sum(1 for x in r if x["state"]["cloud"] == "above")
    lines.append("")
    lines.append(f"BREADTH OF THIS LIST: {n_up}/{len(r)} with daily trend up, "
                 f"{n_above}/{len(r)} above the daily cloud.")
    if n_up / len(r) < 0.35:
        lines.append("Weak internal breadth — size down and demand the trigger "
                     "rather than anticipating it.")
    return {"ranked": r, "commentary": "\n".join(lines)}
