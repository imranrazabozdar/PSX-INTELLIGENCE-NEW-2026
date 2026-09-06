"""market_hours.py — PSX weekday/session-hours checks.

Two separate things live here, deliberately not conflated:

  - is_trading_day() -- the ACTUAL guard the scheduled batch entry points
    (run_daily_batch.py, run_wyckoff_batch.py) use: Mon-Fri only. This is
    the real requirement ("disable automated runs on Saturday-Sunday").
  - is_market_open()/get_market_status() -- informational only, for the
    log line ("Market Status: Market Open (Friday, 16:15 PKT)"). NOT
    wired into the batch as an abort condition: this batch runs AFTER
    market close by design (the cron fires at 15:40 PKT Mon-Thu / 16:40
    PKT Fri, specifically once that day's session has finished), so a
    guard requiring the market to be currently OPEN would make Friday's
    scheduled run -- dispatched at 16:40 PKT, an hour past this module's
    own close time -- abort every single week. Gating on "is it a
    trading day" (not "is the market open right now") is what actually
    matches how this batch is used.

PKT is UTC+5, no DST -- same fixed-offset convention scraper.py already
uses (NOT datetime.now().astimezone().tzinfo, which is whatever timezone
the HOST MACHINE happens to be in -- on a GitHub Actions runner that's
UTC, silently mislabeled as PKT, throwing every check off by 5 hours).
"""
from datetime import datetime, timezone, timedelta

_PKT = timezone(timedelta(hours=5))

# Matches this project's own session hours (fire_config.yaml's
# session.market_open/market_close), not a separately-guessed window.
MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE = 9, 0
MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE = 16, 30


def _now_pkt() -> datetime:
    return datetime.now(timezone.utc).astimezone(_PKT)


def is_trading_day(now_pkt: datetime = None) -> bool:
    """True Mon-Fri, False Sat/Sun. This is the guard the scheduled batch
    entry points actually use."""
    now_pkt = now_pkt or _now_pkt()
    return now_pkt.weekday() < 5  # 0=Mon .. 4=Fri, 5=Sat, 6=Sun


def is_market_open(now_pkt: datetime = None) -> bool:
    """Informational: True if `now` (PKT) falls within this project's
    09:00-16:30 PKT session window on a trading day. Not used to gate
    the post-close batch -- see module docstring."""
    now_pkt = now_pkt or _now_pkt()
    if not is_trading_day(now_pkt):
        return False
    market_open = now_pkt.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
    market_close = now_pkt.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0)
    return market_open <= now_pkt <= market_close


def get_market_status(now_pkt: datetime = None) -> str:
    """Human-readable status for a log line, e.g. "Market Open (Friday,
    16:15 PKT)" or "Market Closed (Saturday)"."""
    now_pkt = now_pkt or _now_pkt()
    day_name = now_pkt.strftime("%A")

    if not is_trading_day(now_pkt):
        return f"Market Closed ({day_name})"

    market_open = now_pkt.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
    market_close = now_pkt.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0)

    if now_pkt < market_open:
        return f"Market Opening Soon ({day_name}, {market_open.strftime('%H:%M PKT')})"
    if now_pkt > market_close:
        return f"Market Closed ({day_name}, after {market_close.strftime('%H:%M PKT')})"
    return f"Market Open ({day_name}, {now_pkt.strftime('%H:%M PKT')})"
