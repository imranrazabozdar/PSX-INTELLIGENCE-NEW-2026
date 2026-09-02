import os

BASE_DIR = os.path.dirname(__file__)

# PSX universe (expand later)
STOCKS = [
    "OGDC",
    "PPL",
    "HBL",
    "UBL",
    "LUCK",
    "FFC",
    "ENGRO",
    "MCB",
    "SYS",
    "MARI"
]

# Sector mapping
SECTORS = {
    "OGDC":"Oil & Gas",
    "PPL":"Oil & Gas",
    "HBL":"Banking",
    "UBL":"Banking",
    "MCB":"Banking",
    "LUCK":"Cement",
    "FFC":"Fertilizer",
    "ENGRO":"Fertilizer",
    "SYS":"Technology",
    "MARI":"Oil & Gas"
}


# Fundamentals
FUNDAMENTALS = {}
FUNDAMENTALS_AS_OF = ""


# Benchmark
BENCHMARK_INDEX = "KSE100"


# Regime
REGIME_EMA_SPAN = 50


# Relative strength
RS_LOOKBACKS = {
    "1m":21,
    "3m":63,
    "6m":126
}

RS_WEIGHTS = {
    "1m":0.4,
    "3m":0.35,
    "6m":0.25
}


# Scoring — keys MUST match what scoring_engine.compute() reads directly
# (macro_news, sentiment, technical, fundamentals). These are the renormalized
# values orchestrator.decide() was already computing at runtime every request
# (technical 0.70 / fundamental 0.15 / risk 0.05 summed to 1.0, but
# scoring_engine has no "fundamental"-singular or "risk" section, so those two
# were silently dropped and the remaining three renormalized against 0.95) —
# written explicitly here so nothing is silently lost and no request-time
# renormalization is needed for the default config. "risk" was never a
# scoring-blend input: risk_manager.assess() gates/vetoes and sizes positions
# separately (see RISK below) and never contributes to the 0-100 score.
# macro_news is 0 because macro_news_analyzer is not wired to a populated news
# table yet (orchestrator.py) — a nonzero weight here would just inject a
# perpetual neutral-50 into every score with no real signal. Raise it once
# that's wired.
WEIGHTS = {
    "technical":0.7368,
    "fundamentals":0.1579,
    "sentiment":0.1053,
    "macro_news":0.0
}


# Risk settings
RISK = {
    "max_risk_per_trade_pct":1,
    "max_position_pct":20,
    "min_headroom_rr":2,
    "min_avg_daily_volume":50000,
    "max_volatility_pct":8,
    "default_stop_atr_mult":2,
    "max_extension_pct":10,
    "max_extension_momentum_pct":15
}


PORTFOLIO_RISK = {
    "max_positions":10
}


# News
NEWS_SIGNALS_PATH = os.path.join(BASE_DIR,"news_signals.json")
NEWS_RAW_PATH = os.path.join(BASE_DIR,"news_raw_24h.json")

NEWS_SIGNALS_MAX_AGE_HOURS = 48

NEWS_SOURCE_ALLOWLIST = [
    "dawn.com",
    "brecorder.com",
]

NEWS_DISPLAY_PUBLISHERS = [
    "Dawn",
    "Business Recorder",
    "Profit"
]


COMPANY_NEWS_QUERY = {}

NEWS_FALLBACK_VADER = False


def headline_matches_company(symbol, title, summary=""):
    text = ((title or "")+" "+(summary or "")).upper()
    return symbol.upper() in text


# Email disabled
EMAIL_MODE="off"
SMTP_USER=""
SMTP_APP_PASSWORD=""
EMAIL_TO=""
SMTP_HOST=""
SMTP_PORT=587


ACTIONABLE_SIGNALS=[]


# Shariah placeholders
KMI30_VERIFIED=[]
KMIALLSHR_VERIFIED=[]
OTHER_COMPLIANT={}

KMI30_VERIFICATION_DATE="2026-01-01"
KMIALLSHR_VERIFICATION_DATE="2026-01-01"

KMI30_SOURCE="PSX"
KMIALLSHR_SOURCE="PSX"

SHARIAH_STALE_DAYS=180


# Macro
MACRO_ANCHORS={}
MACRO_STALE_DAYS=7


# Paths
REPORT_DIR=os.path.join(BASE_DIR,"reports")
PORTFOLIO_PATH=os.path.join(BASE_DIR,"portfolio.json")


DISCLAIMER = (
    "Research tool only. Not financial advice. "
    "Scores are evidence based, not profit probabilities."
)


# Signal settings — signal_generator.py binds T = config.SIGNAL_THRESHOLDS at
# import and indexes T["strong_buy"|"buy"|"watch"|"hold"] directly; an empty
# dict here relied on orchestrator.decide() to lazily backfill these at the
# first request. Declared explicitly at startup instead (same V1 band values
# orchestrator was already filling in): Buy band 70-80, Watch band 60-70,
# Hold band 50-60.
SIGNAL_THRESHOLDS={"strong_buy":80,"buy":70,"watch":60,"hold":50}
PURE_TECHNICAL=True
CHASE_GUARD_ENABLED=False
EARLY_WATCH_ENABLED=False

PULLBACK_EMA_SPAN=50
BUY_MIN_CMF=0

REGIME_GATE_ENABLED=False

RS_LAGGARD_VETO=-20

EARNINGS_BLACKOUT_DAYS=5

MIN_OHLC_BARS_FOR_TRUE=20
