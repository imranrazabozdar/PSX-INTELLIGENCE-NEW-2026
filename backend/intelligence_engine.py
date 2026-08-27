"""
PSX Intelligence Engine
Evidence based analysis primitives.
"""

from dataclasses import dataclass
from typing import List, Dict


@dataclass
class Candle:
    o: float
    h: float
    l: float
    c: float
    v: float = 0



def candlestick_patterns(bars: List[Candle]) -> List[Dict]:

    if not bars:
        return []

    x = bars[-1]

    rng = max(x.h - x.l, 1e-9)
    body = abs(x.c - x.o)

    upper = x.h - max(x.o, x.c)
    lower = min(x.o, x.c) - x.l

    result = []

    def add(name,bias,evidence):
        result.append({
            "pattern":name,
            "bias":bias,
            "evidence":evidence
        })


    if body/rng <= 0.10:
        add(
            "Doji",
            "neutral",
            "Small body indicates market indecision"
        )


    if lower/rng >= 0.55 and body/rng <= 0.35:
        add(
            "Hammer",
            "bullish-context",
            "Lower price rejection"
        )


    if upper/rng >= 0.55 and body/rng <= 0.35:
        add(
            "Shooting Star",
            "bearish-context",
            "Upper price rejection"
        )


    if len(bars) >= 2:

        p = bars[-2]


        if p.c < p.o and x.c > x.o:
            add(
                "Bullish Engulfing",
                "bullish-context",
                "Bullish candle after bearish candle"
            )


        if p.c > p.o and x.c < x.o:
            add(
                "Bearish Engulfing",
                "bearish-context",
                "Bearish candle after bullish candle"
            )


    return result



def market_structure(closes: List[float]) -> Dict:

    if len(closes) < 20:
        return {
            "trend":"unconfirmed",
            "reason":"Need 20 observations"
        }


    ma20 = sum(closes[-20:])/20
    last = closes[-1]


    return {
        "trend":"bullish" if last > ma20 else "bearish",
        "last":round(last,2),
        "ma20":round(ma20,2),
        "reason":"Price compared with 20 period average"
    }



def volume_analysis(bars: List[Candle]) -> Dict:

    if len(bars) < 20:
        return {
            "status":"insufficient_history"
        }


    avg = sum(x.v for x in bars[-20:])/20

    current = bars[-1].v

    ratio = current/max(avg,1)


    if ratio >= 2:
        signal="ABNORMAL_VOLUME_SURGE"

    elif ratio >= 1.5:
        signal="HIGH_VOLUME"

    else:
        signal="NORMAL"


    return {
        "current_volume":current,
        "average_volume":round(avg,2),
        "volume_ratio":round(ratio,2),
        "signal":signal
    }



def ai_evidence_packet(
        symbol,
        quote,
        structure,
        wyckoff,
        patterns,
        news=None,
        fundamentals=None,
        volume=None
):

    return {

        "symbol":symbol,

        "quote":quote,

        "structure":structure,

        "wyckoff":wyckoff,

        "candlesticks":patterns,

        "volume_analysis":volume or {},

        "news":news or [],

        "fundamentals":fundamentals or {},


        "instruction":
        "Generate bull case, bear case, confirmation, invalidation, catalysts and risks. Never invent missing data."

    }
