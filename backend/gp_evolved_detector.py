"""gp_evolved_detector.py — Genetic-Programming (GP) evolved trading
formula, translated from a reference systematic-trading repo
(ZiadFrancis/Genetics_Trading_Part_1, gp_strategy_progress_vectorbt.py +
trading_system_Load_Infer.py). NOT a fixed rule like this project's other
detectors -- it's a meta-strategy generator: DEAP evolves a symbolic
expression tree that maps raw OHLC inputs to a continuous target
position-percent (-100%..+100%), fitted per instrument by genetic search,
then that ONE evolved formula is deployed live.

SOURCE DESIGN: the reference repo evolves a formula over 4 correlated FX
pairs' OHLC (16 terminals) on 5-minute bars, trading USDJPY, evaluated via
vectorbt's vectorised Portfolio.from_orders (target-percent sizing).

PSX ADAPTATION (stated plainly, per this project's translation discipline):
  - INPUTS: PSX has no natural "4 correlated pairs" basket and no intraday
    feed in this backend (daily OHLC only). Per explicit user direction,
    each symbol's own daily OHLC is paired with the KSE-100 index's own
    daily OHLC as the GP's 8 terminals (STK_Open/High/Low/Close,
    KSE_Open/High/Low/Close) -- the closest PSX analog to "instrument +
    correlated benchmark", instead of the source's 4-pair FX basket.
  - ENGINE: vectorbt is NOT used here (heavy optional dependency, JIT
    compile overhead unhelpful at this data scale) -- evaluate_individual()
    below is a hand-written vectorised pandas/numpy backtest that
    reproduces vectorbt's target-percent semantics: a desired weight in
    [-1, +1], a NO_TRADE_BAND dead-zone before rebalancing, and a
    proportional-to-turnover commission cost. Same shape, no new
    dependency.
  - NO-LOOKAHEAD (this project's hard rule, not present in the source):
    the source sizes and fills an order off bar i's own OHLC/close in the
    same bar -- fine for its own research purposes, but lookahead by this
    project's standard. Here, the desired weight computed from bar i's
    (fully known, completed) OHLC is applied to the close-to-close return
    REALISED FROM i to i+1 (weight.shift(1) * pct_change()), and any
    turnover cost is charged on that same i->i+1 step. Live serving
    mirrors this: the weight computed from the latest COMPLETED bar is a
    forward-looking target to hold INTO the next session, never claimed as
    already-realised.
  - COMMISSION: the source's 0.0015% (COMMISSION_PCT=0.000015) is an
    FX-ECN rate, meaningless for PSX equities -- re-expressed as 0.15%
    (COMMISSION_PCT=0.0015) per unit of turnover, a more realistic PSX
    retail-equity round-trip-ish friction. Explicit rescaling, not a
    silent reuse.
  - MIN_TRADES guard: the source requires >=20 trades on its training
    slice to avoid rewarding a near-static, statistically meaningless
    individual -- tuned for 5-minute bars over ~1.5 years (tens of
    thousands of bars). Daily PSX history is two to three orders of
    magnitude sparser (typically several hundred to ~1,300 bars total),
    so this is rescaled down to MIN_TRADES = 8 on the training slice,
    documented here rather than silently reused at a threshold that would
    reject nearly every individual.
  - GP primitives, fitness shape (exp(-total_return), minimized), the
    dead-band mechanism (NO_TRADE_BAND=10 percentage points), MAX_DEPTH/
    MAX_LEN, and population/tournament/crossover/mutation operators are
    kept at the source's own literal defaults -- these are dimensionless
    structural GP parameters, not FX-scale-specific, so no rescaling
    applies to them.
  - TERMINAL NORMALISATION (a real bug caught during synthetic testing,
    not present in the source): the source's 4 FX pairs are all
    naturally comparable in magnitude (roughly 0.6-160), so raw-price
    arithmetic/comparisons (gtpct(EURUSD_Close, GBPUSD_Close), etc.) stay
    meaningful across the whole series. A PSX stock's price (single
    digits to low thousands of rupees) and the KSE-100 index level
    (tens of thousands) differ by orders of magnitude -- feeding raw
    OHLC directly made gtpct/arithmetic terminals degenerate: whichever
    side happens to be bigger wins every single comparison regardless of
    actual market state, so evolved individuals collapsed onto a
    constant extreme desired_pct (verified: an early test run produced
    desired_pct==100.0 for 100 consecutive out-of-sample bars). Fixed by
    z-scoring every terminal with a trailing (causal, no-lookahead)
    ZSCORE_WINDOW=20-bar rolling mean/std BEFORE the GP ever sees it --
    both series now vary in the same dimensionless range regardless of
    absolute price level. This is an addition needed for the PSX
    adaptation to function at all, not an optional refinement.

MODEL STORAGE: a trained individual (a DEAP PrimitiveTree) is not JSON-
serialisable -- pickled via `dill`, base64-encoded, and stored as a string
field inside the same analysis_cache table every other backtest in this
project writes to (see run_gp_evolution_training.py). Loading requires
this module's own pset/toolbox (built once at import time, deterministic)
to already be registered, exactly like the source's GPModelManager needs
its own toolbox.compile() available before dill.load() can be used.
"""

import base64
import math
import random

import dill
import numpy as np
import pandas as pd
from deap import base, creator, gp, tools

RNG_SEED = 42

PAIR_TERMINALS = ["STK_Open", "STK_High", "STK_Low", "STK_Close",
                   "KSE_Open", "KSE_High", "KSE_Low", "KSE_Close"]

POP_SIZE_DEFAULT = 150
N_GEN_DEFAULT = 12
P_CX, P_MUT = 0.90, 0.15
MAX_DEPTH, MAX_LEN = 8, 60

INITIAL_CASH = 1_000_000
COMMISSION_PCT = 0.0015           # PSX-equity turnover friction (see module docstring)
NO_TRADE_BAND = 10                # +/-10 percentage points, dimensionless (source default, reused)
MIN_TRADES = 8                    # rescaled down from the source's 20 (see module docstring)

TRAIN_FRAC, VAL_FRAC = 0.6, 0.2   # remaining 0.2 is the out-of-sample test slice
ZSCORE_WINDOW = 20                # trailing, causal — see module docstring
MIN_BARS_REQUIRED = 300 + ZSCORE_WINDOW  # need a meaningful 60/20/20 split after the warm-up is dropped

PATTERN_NAME_GP_EVOLVED = "GP-Evolved Formula"


# ─────────────────────────────────────────────
# 1. GP primitives (mirrors the source's pset/toolbox, 8 terminals not 16)
# ─────────────────────────────────────────────
def vdiv(a, b):
    """Element-wise protected division."""
    return np.divide(a, b, out=np.zeros_like(a, dtype="float64"), where=np.abs(b) > 1e-8)


def gtpct(a, b):
    """Vectorised a>b ? 100 : -100."""
    return np.where(a > b, 100.0, -100.0)


def rand_uniform():
    return random.uniform(-1, 1)


pset = gp.PrimitiveSet("PSX", len(PAIR_TERMINALS), prefix="inp")
for op in (np.add, np.subtract, np.multiply):
    pset.addPrimitive(op, 2)
pset.addPrimitive(vdiv, 2, name="pdiv")
for f, name in [(np.sin, "sin"), (np.cos, "cos"), (np.tan, "tan"), (np.tanh, "tanh")]:
    pset.addPrimitive(f, 1, name=name)
pset.addPrimitive(gtpct, 2, name="gtpct")
pset.addEphemeralConstant("gp_evolved_rand", rand_uniform)
for i, n in enumerate(PAIR_TERMINALS):
    pset.renameArguments(**{f"inp{i}": n})

if not hasattr(creator, "GPEvolvedFitnessMin"):
    creator.create("GPEvolvedFitnessMin", base.Fitness, weights=(-1.0,))
if not hasattr(creator, "GPEvolvedIndividual"):
    creator.create("GPEvolvedIndividual", gp.PrimitiveTree, fitness=creator.GPEvolvedFitnessMin)

toolbox = base.Toolbox()
toolbox.register("expr", gp.genHalfAndHalf, pset=pset, min_=1, max_=MAX_DEPTH)
toolbox.register("individual", tools.initIterate, creator.GPEvolvedIndividual, toolbox.expr)
toolbox.register("population", tools.initRepeat, list, toolbox.individual)
toolbox.register("compile", gp.compile, pset=pset)
toolbox.register("select", tools.selTournament, tournsize=3)
toolbox.register("mate", gp.cxOnePoint)
toolbox.register("expr_mut", gp.genFull, min_=0, max_=2)
toolbox.register("mutate", gp.mutUniform, expr=toolbox.expr_mut, pset=pset)
toolbox.decorate("mate", gp.staticLimit(key=len, max_value=MAX_LEN))
toolbox.decorate("mutate", gp.staticLimit(key=len, max_value=MAX_LEN))


# ─────────────────────────────────────────────
# 2. Data alignment: stock OHLC + KSE-100 OHLC, no-lookahead vectorised backtest
# ─────────────────────────────────────────────
def _zscore(series: pd.Series, window=ZSCORE_WINDOW) -> pd.Series:
    """Trailing, causal rolling z-score — bar i uses only bars
    [i-window+1, i], never a future bar. See module docstring
    (TERMINAL NORMALISATION) for why this is required, not optional."""
    mean = series.rolling(window).mean()
    std = series.rolling(window).std()
    return (series - mean) / std.replace(0.0, np.nan)


def build_training_frame(stock_rows, index_rows):
    """stock_rows: list of {date/trade_date, open, high, low, close} ascending
    (this project's daily_ohlc shape). index_rows: psx_live.index_history()
    output ({timestamp epoch-ms, open, high, low, close}). Returns a single
    DataFrame indexed by date, inner-joined on the trading date, with the 8
    GP terminal columns (STK_Open..KSE_Close) z-scored per module docstring
    plus a separate STK_Close_raw column (actual rupee price, used only for
    computing realised returns in the backtest) -- or None if too little
    overlap/history."""
    sd = pd.DataFrame(stock_rows)
    date_col = "date" if "date" in sd.columns else "trade_date"
    sd["date"] = pd.to_datetime(sd[date_col]).dt.date
    sd = sd[["date", "open", "high", "low", "close"]].rename(
        columns={"open": "STK_Open", "high": "STK_High", "low": "STK_Low", "close": "STK_Close"})

    idx_recs = []
    for r in (index_rows or []):
        ts, o, h, l, c = r.get("timestamp"), r.get("open"), r.get("high"), r.get("low"), r.get("close")
        if ts is None or None in (o, h, l, c):
            continue
        d = pd.Timestamp(ts, unit="ms", tz="UTC").date()
        idx_recs.append({"date": d, "KSE_Open": float(o), "KSE_High": float(h),
                          "KSE_Low": float(l), "KSE_Close": float(c)})
    if not idx_recs:
        return None
    kd = pd.DataFrame(idx_recs).drop_duplicates(subset="date")

    merged = sd.merge(kd, on="date", how="inner").sort_values("date").reset_index(drop=True)
    if len(merged) < MIN_BARS_REQUIRED:
        return None
    for c in PAIR_TERMINALS:
        merged[c] = merged[c].astype("float64")

    merged["STK_Close_raw"] = merged["STK_Close"]
    for c in PAIR_TERMINALS:
        merged[c] = _zscore(merged[c])
    merged = merged.dropna(subset=PAIR_TERMINALS).reset_index(drop=True)
    if len(merged) < MIN_BARS_REQUIRED - ZSCORE_WINDOW:
        return None
    return merged


def build_live_frame(stock_rows, index_rows, window=ZSCORE_WINDOW):
    """Same shape as build_training_frame() but for live scanning: only
    requires window+1 merged bars (not the full MIN_BARS_REQUIRED training
    threshold), and returns the tail of the z-scored frame -- callers
    should fetch at least window*2 raw daily bars so a short recent gap in
    either series doesn't starve the rolling window entirely."""
    sd = pd.DataFrame(stock_rows)
    if sd.empty:
        return None
    date_col = "date" if "date" in sd.columns else "trade_date"
    sd["date"] = pd.to_datetime(sd[date_col]).dt.date
    sd = sd[["date", "open", "high", "low", "close"]].rename(
        columns={"open": "STK_Open", "high": "STK_High", "low": "STK_Low", "close": "STK_Close"})

    idx_recs = []
    for r in (index_rows or []):
        ts, o, h, l, c = r.get("timestamp"), r.get("open"), r.get("high"), r.get("low"), r.get("close")
        if ts is None or None in (o, h, l, c):
            continue
        d = pd.Timestamp(ts, unit="ms", tz="UTC").date()
        idx_recs.append({"date": d, "KSE_Open": float(o), "KSE_High": float(h),
                          "KSE_Low": float(l), "KSE_Close": float(c)})
    if not idx_recs:
        return None
    kd = pd.DataFrame(idx_recs).drop_duplicates(subset="date")

    merged = sd.merge(kd, on="date", how="inner").sort_values("date").reset_index(drop=True)
    if len(merged) < window + 1:
        return None
    for c in PAIR_TERMINALS:
        merged[c] = merged[c].astype("float64")
    merged["STK_Close_raw"] = merged["STK_Close"]
    for c in PAIR_TERMINALS:
        merged[c] = _zscore(merged[c], window=window)
    merged = merged.dropna(subset=PAIR_TERMINALS).reset_index(drop=True)
    return merged if len(merged) else None


def split_frame(df):
    n = len(df)
    n_train = int(n * TRAIN_FRAC)
    n_val = int(n * VAL_FRAC)
    return (df.iloc[:n_train].reset_index(drop=True),
            df.iloc[n_train:n_train + n_val].reset_index(drop=True),
            df.iloc[n_train + n_val:].reset_index(drop=True))


def _weights_from_signal(desired_pct):
    """desired_pct: raw GP output array. Clip to [-100,100], apply the
    NO_TRADE_BAND dead-zone (hold last kept weight until the signal moves
    far enough), ffill -- same mechanism as the source."""
    desired_pct = np.where(np.isfinite(desired_pct), desired_pct, 0.0)
    desired_pct = np.clip(desired_pct, -100.0, 100.0)
    weights = desired_pct / 100.0
    delta = np.abs(np.diff(weights, prepend=weights[0]))
    weights = np.where(delta < (NO_TRADE_BAND / 100.0), np.nan, weights)
    weights = pd.Series(weights).ffill().fillna(0.0).to_numpy()
    return weights


def simulate_weights(weights, stk_close):
    """No-lookahead vectorised backtest: weight decided from bar i is
    applied to the close-to-close return realised i->i+1, and turnover
    cost is charged on that same step (see module docstring)."""
    stk_close = np.asarray(stk_close, dtype="float64")
    ret = np.diff(stk_close) / stk_close[:-1]           # ret[i] = return realised over i -> i+1
    ret = np.insert(ret, 0, 0.0)                         # align length, ret[0] unused (no prior weight)

    weight_change = np.abs(np.diff(weights, prepend=weights[0]))
    cost = weight_change * COMMISSION_PCT

    applied_weight = np.roll(weights, 1)
    applied_weight[0] = 0.0
    applied_cost = np.roll(cost, 1)
    applied_cost[0] = 0.0

    strategy_ret = applied_weight * ret - applied_cost
    n_trades = int(np.sum(weight_change > 1e-9))
    return strategy_ret, n_trades


def evaluate_individual(ind, df_slice: pd.DataFrame, min_trades=MIN_TRADES):
    """Compile the GP tree, run it over df_slice's 8 terminals, backtest
    the resulting weight series. Returns a DEAP-style (fitness,) tuple —
    lower is better (FitnessMin), matching the source's exp(-total_return)
    shape so a bigger realised return -> lower (better) fitness."""
    try:
        func = toolbox.compile(expr=ind)
        cols = [df_slice[c].to_numpy(dtype="float64") for c in PAIR_TERMINALS]
        desired_pct = func(*cols)
        if np.isscalar(desired_pct) or getattr(desired_pct, "shape", None) == ():
            desired_pct = np.full(len(df_slice), float(desired_pct))
        weights = _weights_from_signal(np.asarray(desired_pct, dtype="float64"))

        strategy_ret, n_trades = simulate_weights(weights, df_slice["STK_Close_raw"].to_numpy())
        total_ret = float(np.prod(1.0 + strategy_ret) - 1.0)

        if not np.isfinite(total_ret) or n_trades < min_trades:
            return (1e6,)
        return (math.exp(-total_ret),)
    except Exception:
        return (1e6,)


def backtest_stats(ind, df_slice: pd.DataFrame):
    """Human-readable out-of-sample metrics for a trained individual —
    used for the val-set winner pick and the test-set (out-of-sample)
    report saved alongside the model."""
    func = toolbox.compile(expr=ind)
    cols = [df_slice[c].to_numpy(dtype="float64") for c in PAIR_TERMINALS]
    desired_pct = func(*cols)
    if np.isscalar(desired_pct) or getattr(desired_pct, "shape", None) == ():
        desired_pct = np.full(len(df_slice), float(desired_pct))
    weights = _weights_from_signal(np.asarray(desired_pct, dtype="float64"))
    strategy_ret, n_trades = simulate_weights(weights, df_slice["STK_Close_raw"].to_numpy())

    total_ret = float(np.prod(1.0 + strategy_ret) - 1.0)
    days = len(strategy_ret)
    ann_ret = float((1.0 + total_ret) ** (252.0 / days) - 1.0) if days > 0 and (1.0 + total_ret) > 0 else None
    std = float(np.std(strategy_ret))
    sharpe = float((np.mean(strategy_ret) / std) * math.sqrt(252)) if std > 1e-12 else None
    wins = strategy_ret[strategy_ret > 0]
    losses = strategy_ret[strategy_ret < 0]
    # "win rate" here is % of DAYS with a positive strategy return, not a per-trade
    # win rate -- this is a continuous position-sizing strategy (see module
    # docstring), not discrete entry/exit trades, so there is no single trade to
    # score win/loss against; days is the only well-defined denominator.
    win_rate = float(len(wins) / days) if days > 0 else None
    gross_win = float(wins.sum()) if len(wins) else 0.0
    gross_loss = float(-losses.sum()) if len(losses) else 0.0
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None
    max_dd = float(_max_drawdown(strategy_ret))

    return {
        "total_return_pct": round(total_ret * 100, 3),
        "annualized_return_pct": round(ann_ret * 100, 3) if ann_ret is not None else None,
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "n_trades": n_trades,
        "win_rate_pct": round(win_rate * 100, 2) if win_rate is not None else None,
        "profit_factor": round(profit_factor, 3) if profit_factor is not None else None,
        "max_drawdown_pct": round(max_dd * 100, 3),
        "n_bars": days,
    }


def _max_drawdown(strategy_ret):
    equity = np.cumprod(1.0 + strategy_ret)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    return dd.min() if len(dd) else 0.0


# ─────────────────────────────────────────────
# 3. Evolution loop (single-process, mirrors the source's run_evolution)
# ─────────────────────────────────────────────
def run_evolution(train_df, pop_size=POP_SIZE_DEFAULT, n_gen=N_GEN_DEFAULT, seed=RNG_SEED, log=None):
    random.seed(seed)
    np.random.seed(seed)

    pop = toolbox.population(n=pop_size)
    hof = tools.HallOfFame(5, similar=lambda a, b: a == b)

    def _ev(ind):
        return evaluate_individual(ind, train_df)

    for gen in range(1, n_gen + 1):
        invalid = [i for i in pop if not i.fitness.valid]
        for ind in invalid:
            ind.fitness.values = _ev(ind)

        hof.update(pop)

        offspring = list(map(toolbox.clone, toolbox.select(pop, len(pop))))
        for c1, c2 in zip(offspring[::2], offspring[1::2]):
            if random.random() < P_CX:
                toolbox.mate(c1, c2)
                del c1.fitness.values, c2.fitness.values
        for m in offspring:
            if random.random() < P_MUT:
                toolbox.mutate(m)
                del m.fitness.values

        pop[:] = offspring
        invalid = [i for i in pop if not i.fitness.valid]
        for ind in invalid:
            ind.fitness.values = _ev(ind)

        hof.update(pop)
        if log:
            best = min(i.fitness.values[0] for i in pop)
            log(gen, n_gen, best)

    return hof


def train_symbol(train_df, val_df, test_df, pop_size=POP_SIZE_DEFAULT, n_gen=N_GEN_DEFAULT,
                  seed=RNG_SEED, log=None):
    """Full pipeline: evolve on train_df, pick the Hall-of-Fame member with
    the best VALIDATION fitness (matching the source's own selection
    scheme), report OUT-OF-SAMPLE test_df stats. Returns
    (best_individual, val_fitness, test_stats) or None if evolution failed
    to produce a usable individual (e.g. every individual hit the
    n_trades guard)."""
    hof = run_evolution(train_df, pop_size=pop_size, n_gen=n_gen, seed=seed, log=log)
    if not hof:
        return None

    scored = [(ind, evaluate_individual(ind, val_df)[0]) for ind in hof]
    scored.sort(key=lambda t: t[1])
    best, val_fitness = scored[0]
    if val_fitness >= 1e6:
        return None

    test_stats = backtest_stats(best, test_df)
    return best, val_fitness, test_stats


# ─────────────────────────────────────────────
# 4. Model (de)serialisation for Turso analysis_cache storage
# ─────────────────────────────────────────────
def serialize_individual(ind) -> str:
    return base64.b64encode(dill.dumps(ind)).decode("ascii")


def deserialize_individual(blob: str):
    return dill.loads(base64.b64decode(blob.encode("ascii")))


def get_live_signal(ind, recent_frame: pd.DataFrame) -> dict:
    """recent_frame: a build_training_frame()-shaped window ending at the
    latest COMPLETED daily bar, with AT LEAST ZSCORE_WINDOW rows so the
    same trailing z-score used in training can be computed for that final
    bar (the raw OHLC of a single day, unlike training, carries no scale
    information on its own -- see TERMINAL NORMALISATION in the module
    docstring). Returns the raw desired_pct and a 3-way classification for
    display (BUY/SELL/HOLD around the same NO_TRADE_BAND dead-zone used in
    training) -- this is a forward-looking TARGET exposure to hold into
    the next session, not a same-bar fill."""
    if len(recent_frame) < ZSCORE_WINDOW:
        return {"desired_pct": 0.0, "classification": "HOLD", "error": "insufficient_history"}

    func = toolbox.compile(expr=ind)
    latest = recent_frame.iloc[-1]
    args = [float(latest[c]) for c in PAIR_TERMINALS]
    raw = func(*args)
    desired_pct = float(np.clip(raw, -100.0, 100.0)) if np.isfinite(raw) else 0.0

    if desired_pct >= NO_TRADE_BAND:
        classification = "BUY"
    elif desired_pct <= -NO_TRADE_BAND:
        classification = "SELL"
    else:
        classification = "HOLD"

    return {"desired_pct": round(desired_pct, 2), "classification": classification}
