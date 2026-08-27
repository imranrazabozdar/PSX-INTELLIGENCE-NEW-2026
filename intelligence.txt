"""Explainable PSX intelligence primitives. No fabricated probabilities."""
from dataclasses import dataclass
from typing import List, Dict

@dataclass
class Candle:
    o: float; h: float; l: float; c: float; v: float = 0

def candlestick_patterns(bars: List[Candle]) -> List[Dict]:
    if not bars: return []
    x=bars[-1]; rng=max(x.h-x.l,1e-9); body=abs(x.c-x.o); upper=x.h-max(x.o,x.c); lower=min(x.o,x.c)-x.l
    out=[]
    def add(name,bias,evidence): out.append({'pattern':name,'bias':bias,'evidence':evidence})
    if body/rng <= .10: add('Doji','neutral','Body <=10% of candle range; context required')
    if lower/rng >= .55 and body/rng <= .35: add('Hammer-like rejection','bullish-context','Long lower rejection; only meaningful near support/downtrend exhaustion')
    if upper/rng >= .55 and body/rng <= .35: add('Shooting-star-like rejection','bearish-context','Long upper rejection; only meaningful near resistance/uptrend exhaustion')
    if len(bars)>=2:
        p=bars[-2]
        if p.c<p.o and x.c>x.o and x.o<=p.c and x.c>=p.o: add('Bullish engulfing','bullish-context','Current real body engulfs prior bearish body')
        if p.c>p.o and x.c<x.o and x.o>=p.c and x.c<=p.o: add('Bearish engulfing','bearish-context','Current real body engulfs prior bullish body')
    return out

def market_structure(closes: List[float]) -> Dict:
    if len(closes)<20:return {'trend':'unconfirmed','reason':'Need at least 20 observations'}
    ma20=sum(closes[-20:])/20; last=closes[-1]
    recent=closes[-10:]
    return {'trend':'bullish' if last>ma20 else 'bearish','ma20':round(ma20,2),'last':round(last,2),
            'range10':[round(min(recent),2),round(max(recent),2)],
            'reason':'Price relative to 20-observation mean; swing-point BOS/CHoCH requires OHLC swing extraction'}

def ai_evidence_packet(symbol:str, quote:dict, structure:dict, wyckoff:dict, patterns:list, news:list=None, fundamentals:dict=None)->dict:
    return {'symbol':symbol,'quote':quote,'structure':structure,'wyckoff':wyckoff,'candlesticks':patterns,
            'news':news or [],'fundamentals':fundamentals or {},
            'instruction':'Explain bull case, bear case, confirmation, invalidation, catalysts, risks and conflicts. Never invent missing data or call confidence a probability.'}
