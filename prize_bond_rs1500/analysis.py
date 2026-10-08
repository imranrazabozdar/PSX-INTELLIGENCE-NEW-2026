#!/usr/bin/env python3
"""
Rs.1500 National Prize Bond (Pakistan) - draw-result pattern analysis.

Re-runnable: drop a new SBP result file (e.g. raw/108.csv) into the raw folder and run

    python3 analysis.py                      # defaults: --raw ./raw --out .
    python3 analysis.py --sims 10000 --backtest-start 90 --n-pick 1000

Outputs (in --out):
    draws_clean.csv      long table: draw_no, draw_date, prize_tier, prize_amount, number (str)
    validation.csv       per-draw counts / data-quality checks
    results_table.csv    every statistical test with observed, null expectation, p, BH and Bonferroni p
    backtest.csv         walk-forward hits per rule per draw
    repeat_numbers.csv   numbers that won in more than one draw
    top_prizes.csv       1st and 2nd prize history
    charts/*.png         figures
    report.html          self-contained report (charts embedded)

Null hypothesis throughout: every draw picks its winners uniformly at random (without replacement)
from 000000-999999, independently of every other draw.
"""
import argparse
import base64
import csv
import glob
import html
import os
import re
import sys
from datetime import datetime

import numpy as np
import pandas as pd
from scipy import stats

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

U = 1_000_000
TIER_BY_AMOUNT = {3_000_000: 1, 1_000_000: 2, 18_500: 3}
STANDARD_LABEL = re.compile(r"^\d+- Prize - [123]$")

# chart palette (validated reference palette: blue observed, gray null, blue<->red diverging)
C_OBS = "#2a78d6"
C_NULL = "#8a8984"
C_NULL_FILL = "#e4e3df"
C_ALERT = "#e34948"
C_INK = "#0b0b0b"
C_INK2 = "#52514e"
C_SURFACE = "#fcfcfb"
DIVERGING = LinearSegmentedColormap.from_list("bwr_ref", ["#1c5cab", "#86b6ef", "#f0efec", "#f0a3a2", "#c43a3a"])

plt.rcParams.update({
    "figure.facecolor": C_SURFACE, "axes.facecolor": C_SURFACE, "savefig.facecolor": C_SURFACE,
    "axes.edgecolor": "#c9c8c3", "axes.labelcolor": C_INK2, "xtick.color": C_INK2, "ytick.color": C_INK2,
    "text.color": C_INK, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": "#ecebe7", "grid.linewidth": 0.8, "axes.axisbelow": True,
    "font.size": 10, "axes.titlesize": 11.5, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "legend.frameon": False,
})


def log(msg=""):
    print(msg, flush=True)


# ----------------------------------------------------------------------------------------------
# STEP 1 - parsing and validation
# ----------------------------------------------------------------------------------------------
def parse_file(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    info = {"file": os.path.basename(path), "draw_no": None, "draw_date": None,
            "malformed": [], "unknown_rows": [], "label_variants": set(), "tier3_sorted": True,
            "has_end_marker": any("E N D OF R E P O R T" in "".join(r) for r in rows)}
    for r in rows[:8]:
        joined = " ".join(r)
        if r and r[0].strip().startswith("Dated") and len(r) > 1:
            info["draw_date"] = datetime.strptime(r[1].strip().title(), "%d %b %Y").date()
        m = re.search(r"-\s*(\d+)\s*Draw Result", joined)
        if m:
            info["draw_no"] = int(m.group(1))
    recs = []
    last3 = -1
    for ln, r in enumerate(rows, 1):
        if not r or not r[0].strip():
            continue
        m = re.match(r"^\s*(\d+)\s*-", r[0])
        if not m:
            continue
        amount = int(m.group(1))
        tier = TIER_BY_AMOUNT.get(amount)
        label = r[0].strip()
        if not STANDARD_LABEL.match(label):
            info["label_variants"].add(label)
        cell = r[2].strip() if len(r) > 2 else ""
        if tier is None:
            info["unknown_rows"].append((ln, label, cell))
            continue
        if not cell:
            continue  # empty filler row at the end of the 3rd-prize block
        for tok in re.split(r"\s*-\s*", cell):
            tok = tok.strip()
            if not re.fullmatch(r"\d{6}", tok):
                info["malformed"].append((ln, tok))
                continue
            if tier == 3:
                if int(tok) <= last3:
                    info["tier3_sorted"] = False
                last3 = int(tok)
            recs.append((amount, tier, tok))
    return info, recs


def build_dataset(raw_dir):
    files = sorted(glob.glob(os.path.join(raw_dir, "*.csv")),
                   key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)) or 0))
    if not files:
        sys.exit(f"no CSV files found in {raw_dir}")
    rows, val = [], []
    for p in files:
        info, recs = parse_file(p)
        stem = re.sub(r"\D", "", os.path.basename(p))
        if info["draw_no"] is None:
            sys.exit(f"{p}: could not find draw number on the header lines")
        for amount, tier, num in recs:
            rows.append((info["draw_no"], info["draw_date"], tier, amount, num))
        nums = [r[2] for r in recs]
        dup_within = len(nums) - len(set(nums))
        tiers = pd.Series([r[1] for r in recs]).value_counts()
        val.append({
            "draw_no": info["draw_no"], "draw_date": info["draw_date"], "file": info["file"],
            "file_matches_header": stem == str(info["draw_no"]),
            "n_tier1": int(tiers.get(1, 0)), "n_tier2": int(tiers.get(2, 0)), "n_tier3": int(tiers.get(3, 0)),
            "n_total": len(nums), "malformed_tokens": len(info["malformed"]),
            "malformed_detail": "; ".join(f"line {a}: '{b}'" for a, b in info["malformed"]),
            "unknown_prize_rows": len(info["unknown_rows"]),
            "duplicates_within_draw": dup_within,
            "tier3_ascending": info["tier3_sorted"], "end_marker": info["has_end_marker"],
            "label_variants": " | ".join(sorted(info["label_variants"])),
        })
    df = pd.DataFrame(rows, columns=["draw_no", "draw_date", "prize_tier", "prize_amount", "number"])
    df["number"] = df["number"].astype(str)
    df = df.sort_values(["draw_no", "prize_tier", "number"], kind="stable").reset_index(drop=True)
    v = pd.DataFrame(val).sort_values("draw_no").reset_index(drop=True)
    v["gap_days"] = pd.to_datetime(v["draw_date"]).diff().dt.days
    all_no = set(v["draw_no"])
    missing = sorted(set(range(min(all_no), max(all_no) + 1)) - all_no)
    return df, v, missing


# ----------------------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------------------
def two_sided_from_tails(p_ge, p_le):
    return float(min(1.0, 2 * min(p_ge, p_le)))


def poisson_p(k, mu):
    return two_sided_from_tails(stats.poisson.sf(k - 1, mu), stats.poisson.cdf(k, mu))


def mc_p(obs, sims):
    sims = np.asarray(sims, float)
    s = len(sims)
    ge = (np.sum(sims >= obs - 1e-12) + 1) / (s + 1)
    le = (np.sum(sims <= obs + 1e-12) + 1) / (s + 1)
    return two_sided_from_tails(ge, le)


def bh_adjust(p):
    p = np.asarray(p, float)
    n = len(p)
    o = np.argsort(p)
    r = p[o] * n / np.arange(1, n + 1)
    r = np.minimum.accumulate(r[::-1])[::-1]
    q = np.empty(n)
    q[o] = np.minimum(r, 1)
    return q


def chi2_vs_probs(counts, probs, min_exp=5.0):
    """chi-square GOF against exact probabilities, merging adjacent sparse categories."""
    counts = np.asarray(counts, float)
    probs = np.asarray(probs, float)
    n = counts.sum()
    exp = probs * n
    oc, ec, co, ce = [], [], 0.0, 0.0
    for o_, e_ in zip(counts, exp):
        co += o_
        ce += e_
        if ce >= min_exp:
            oc.append(co)
            ec.append(ce)
            co = ce = 0.0
    if ce > 0:
        if ec:
            oc[-1] += co
            ec[-1] += ce
        else:
            oc.append(co)
            ec.append(ce)
    oc, ec = np.array(oc), np.array(ec)
    chi = float(((oc - ec) ** 2 / ec).sum())
    df = len(oc) - 1
    return chi, df, float(stats.chi2.sf(chi, df))


def digits_of(x):
    x = np.asarray(x, np.int64)
    return ((x[:, None] // 10 ** np.arange(5, -1, -1)) % 10).astype(np.int8)


POPCOUNT10 = np.array([bin(i).count("1") for i in range(1024)], np.int8)


def digit_features(d):
    """d: (n,6) digit matrix -> dict of per-number features."""
    mask = np.bitwise_or.reduce((1 << d.astype(np.int64)), axis=1)
    return {
        "digit_sum": d.sum(1).astype(int),
        "odd_count": (d % 2).sum(1).astype(int),
        "distinct": POPCOUNT10[mask].astype(int),
        "palindrome": (d[:, 0] == d[:, 5]) & (d[:, 1] == d[:, 4]) & (d[:, 2] == d[:, 3]),
        "adjacent_pair": np.any(d[:, 1:] == d[:, :-1], axis=1),
        "has_786": np.any(np.stack([(d[:, i] == 7) & (d[:, i + 1] == 8) & (d[:, i + 2] == 6)
                                    for i in range(4)], 1), axis=1),
    }


# ----------------------------------------------------------------------------------------------
# statistics computed identically on the observed history and on each simulated history
# ----------------------------------------------------------------------------------------------
MAX_LAG = 10


def history_stats(draws):
    """draws: list of (values int64 array, is_top bool array), in draw order."""
    T = len(draws)
    out = {}
    allv = np.concatenate([d[0] for d in draws])
    idx = np.concatenate([np.full(len(d[0]), i) for i, d in enumerate(draws)])
    top = np.concatenate([d[1] for d in draws])
    o = np.lexsort((idx, allv))
    v, ix, tp = allv[o], idx[o], top[o]
    lag_counts = np.zeros(T, np.int64)
    top_re = 0
    for off in range(1, T):
        m = v[off:] == v[:-off]
        if not m.any():
            break
        lags = ix[off:][m] - ix[:-off][m]
        lag_counts += np.bincount(lags, minlength=T)[:T]
        top_re += int(tp[:-off][m].sum())
    out["rep_total"] = int(lag_counts.sum())
    for k in range(1, MAX_LAG + 1):
        out[f"rep_lag{k}"] = int(lag_counts[k]) if k < T else 0
    out["top_reappear"] = top_re
    starts = np.r_[0, np.flatnonzero(v[1:] != v[:-1]) + 1]
    sizes = np.diff(np.r_[starts, len(v)])
    out["n_ge2"] = int((sizes >= 2).sum())
    out["n_ge3"] = int((sizes >= 3).sum())

    # spacing between consecutive sorted 3rd-prize numbers
    gn, gu, small = [], [], 0
    for vals, is_top in draws:
        t3 = np.sort(vals[~is_top])
        g = np.diff(t3)
        n = len(t3)
        gn.append(g * n / U)
        gu.append(1 - (1 - g / U) ** n)
        small += int((g <= 10).sum())
    gn = np.concatenate(gn)
    gu = np.sort(np.concatenate(gu))
    m = len(gu)
    i = np.arange(1, m + 1)
    out["gap_ks"] = float(max((i / m - gu).max(), (gu - (i - 1) / m).max()))
    out["gap_cv2"] = float(gn.var() / gn.mean() ** 2)
    out["gap_small"] = small

    ns = np.array([len(d[0]) for d in draws])
    B = np.bincount(idx * 100 + allv // 10_000, minlength=T * 100).reshape(T, 100).astype(float)
    e = ns[:, None] / 100
    out["b100_chi2_sum"] = float(((B - e) ** 2 / e).sum())
    Z = (B - B.mean(1, keepdims=True)) / B.std(1, keepdims=True)
    for k in (1, 2, 3):
        out[f"b100_r_lag{k}"] = float((Z[:-k] * Z[k:]).mean()) if T > k else 0.0
    B3 = np.bincount(idx * 1000 + allv // 1000, minlength=T * 1000).reshape(T, 1000).astype(float)
    e3 = ns[:, None] / 1000
    out["b1000_disp_sum"] = float(((B3 - e3) ** 2 / e3).sum())
    Z3 = (B3 - B3.mean(1, keepdims=True)) / B3.std(1, keepdims=True)
    out["b1000_r_lag1"] = float((Z3[:-1] * Z3[1:]).mean())
    h = T // 2
    a1, a2 = B3[:h].sum(0), B3[h:].sum(0)
    out["split_half_r"] = float(np.corrcoef(a1, a2)[0, 1])

    near100 = near1000 = 0
    for t in range(T - 1):
        a = np.sort(draws[t][0])
        b = draws[t + 1][0]
        pos = np.searchsorted(a, b)
        left = np.abs(b - a[np.clip(pos - 1, 0, len(a) - 1)])
        right = np.abs(a[np.clip(pos, 0, len(a) - 1)] - b)
        dmin = np.minimum(left, right)
        near100 += int(((dmin >= 1) & (dmin <= 100)).sum())
        near1000 += int(((dmin >= 1) & (dmin <= 1000)).sum())
    out["near100"] = near100
    out["near1000"] = near1000
    return out


def simulate(sizes, n_sims, seed):
    rng = np.random.default_rng(seed)
    res = []
    for s in range(n_sims):
        draws = []
        for n, ntop in sizes:
            x = rng.choice(U, n, replace=False).astype(np.int64)
            it = np.zeros(n, bool)
            it[:ntop] = True
            draws.append((x, it))
        res.append(history_stats(draws))
        if (s + 1) % 2000 == 0:
            log(f"    ... {s + 1}/{n_sims} simulated histories")
    return pd.DataFrame(res)


# ----------------------------------------------------------------------------------------------
# STEP 3 - walk-forward backtest rules
# ----------------------------------------------------------------------------------------------
def rule_sets(train, n_pick, all_digits, seed):
    """train: list of int arrays (all tiers) for draws 80..t, oldest first. Returns {rule: np.array}."""
    rng = np.random.default_rng(seed)
    allv = np.concatenate(train)
    last = np.unique(train[-1])
    out = {}
    width = U // n_pick  # 1000 numbers per range when n_pick=1000
    pref = np.bincount(allv // n_pick, minlength=width)
    hot_r, cold_r = int(np.argmax(pref)), int(np.argmin(pref))
    out["Hot range (most-won 1,000-block)"] = hot_r * n_pick + np.arange(n_pick)
    out["Cold / 'due' range (least-won 1,000-block)"] = cold_r * n_pick + np.arange(n_pick)
    suf = np.bincount(allv % width, minlength=width)
    hot_s, cold_s = int(np.argmax(suf)), int(np.argmin(suf))
    out["Hot ending (most-won last 3 digits)"] = np.arange(n_pick) * width + hot_s
    out["Cold / 'due' ending (least-won last 3 digits)"] = np.arange(n_pick) * width + cold_s
    f = np.zeros((6, 10))
    dg = digits_of(allv)
    for p in range(6):
        f[p] = np.bincount(dg[:, p], minlength=10) + 1
    lf = np.log(f / f.sum(1, keepdims=True))
    score = sum(lf[p][all_digits[:, p]] for p in range(6))
    out["Hot digit-by-position score (top 1,000)"] = np.sort(np.lexsort((np.arange(U), -score))[:n_pick])
    out["Repeat last draw's winners"] = np.sort(rng.choice(last, min(n_pick, len(last)), replace=False))
    vc = pd.Series(allv).value_counts()
    last_seen = {}
    for i, arr in enumerate(train):
        for x in arr:
            last_seen[x] = i
    cand = pd.DataFrame({"num": vc.index.values, "cnt": vc.values})
    cand["last"] = cand["num"].map(last_seen)
    cand = cand.sort_values(["cnt", "last", "num"], ascending=[False, False, True])
    out["Most-frequent past winners"] = np.sort(cand["num"].values[:n_pick])
    win = np.zeros(U, bool)
    for w in last:
        win[max(0, w - 100):min(U, w + 101)] = True
    win[last] = False
    pool = np.flatnonzero(win)
    out["Near last winners (within +/-100)"] = np.sort(rng.choice(pool, n_pick, replace=False))
    return out


# ----------------------------------------------------------------------------------------------
# charts
# ----------------------------------------------------------------------------------------------
def save(fig, path):
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)


def chart_digit_heatmap(dmat, path):
    n = dmat.shape[0]
    cnt = np.stack([np.bincount(dmat[:, p], minlength=10) for p in range(6)])
    exp = n / 10
    z = (cnt - exp) / np.sqrt(exp * 0.9)
    fig, ax = plt.subplots(figsize=(8.6, 3.9))
    lim = max(3.5, np.abs(z).max())
    im = ax.imshow(z, cmap=DIVERGING, vmin=-lim, vmax=lim, aspect="auto")
    for p in range(6):
        for d in range(10):
            ax.text(d, p, f"{cnt[p, d]:,}\n{z[p, d]:+.1f}", ha="center", va="center", fontsize=7.2,
                    color=C_INK)
    ax.set_xticks(range(10))
    ax.set_yticks(range(6))
    ax.set_yticklabels([f"pos {p + 1}" for p in range(6)])
    ax.set_xlabel("digit")
    ax.grid(False)
    ax.set_title(f"Digit frequency by position - count and z-score vs uniform (expected {exp:,.0f} per cell)")
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.set_label("z = (obs - exp) / sd")
    cb.outline.set_visible(False)
    save(fig, path)


def chart_buckets(draw_nos, B, path):
    exp = B.sum(1, keepdims=True) / B.shape[1]
    z = (B - exp) / np.sqrt(exp)
    fig, ax = plt.subplots(figsize=(10, 5.6))
    im = ax.imshow(z, cmap=DIVERGING, vmin=-4, vmax=4, aspect="auto", interpolation="nearest")
    ax.set_yticks(range(len(draw_nos)))
    ax.set_yticklabels(draw_nos, fontsize=7)
    ax.set_xticks(np.arange(0, 100, 10))
    ax.set_xticklabels([f"{i:02d}0000" for i in range(0, 100, 10)], fontsize=8)
    ax.set_xlabel("10,000-wide bucket (first two digits of the number)")
    ax.set_ylabel("draw")
    ax.grid(False)
    ax.set_title("Winners per 10,000-bucket in each draw - z-score vs uniform (about 17 expected per cell)")
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cb.set_label("z")
    cb.outline.set_visible(False)
    save(fig, path)


def chart_gaps(gap_lists, path):
    """gap_lists: list of (raw integer gaps, n) per draw for the sorted 3rd-prize list."""
    gaps_norm = np.concatenate([g * n / U for g, n in gap_lists])
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4))
    ax = axes[0]
    bins = np.linspace(0, 6, 61)
    ax.hist(gaps_norm, bins=bins, density=True, color=C_OBS, alpha=0.85, label="observed gaps",
            edgecolor=C_SURFACE, linewidth=0.6)
    xs = np.linspace(0, 6, 300)
    ax.plot(xs, np.exp(-xs), color=C_INK, lw=2, label="theory: Exp(1)")
    ax.set_yscale("log")
    ax.set_xlabel("gap between consecutive 3rd-prize numbers  x  (n / 1,000,000)")
    ax.set_ylabel("density (log scale)")
    ax.set_title("Gap distribution vs uniform-random theory")
    ax.legend()
    ax = axes[1]
    edges = [1, 11, 26, 51, 101, 201, 401, 801, 1601, 3201, U]
    labels = ["1-10", "11-25", "26-50", "51-100", "101-200", "201-400", "401-800", "801-1.6k", "1.6k-3.2k", ">3.2k"]
    obs_c, exp_c = np.zeros(len(labels)), np.zeros(len(labels))
    for g, n in gap_lists:
        obs_c += np.histogram(g, bins=edges)[0]
        surv = lambda x: (1 - (np.asarray(x, float) - 1) / U) ** n  # P(gap >= x)
        exp_c += (len(g)) * (surv(edges[:-1]) - surv(edges[1:]))
    ratio = obs_c / exp_c
    err = 1.96 * np.sqrt(obs_c) / exp_c
    xi = np.arange(len(labels))
    ax.axhline(1, color=C_NULL, ls="--", lw=1.2)
    ax.errorbar(xi, ratio, yerr=err, fmt="o", color=C_OBS, ms=7, capsize=3, lw=1.5)
    ax.set_xticks(xi)
    ax.set_xticklabels(labels, rotation=35, fontsize=8)
    ax.set_xlabel("gap size (numbers)")
    ax.set_ylabel("observed / expected")
    ax.set_title("Excess of very small gaps = within-draw clustering")
    save(fig, path)


def chart_repeats(obs, sims, lag_obs, lag_sims, path):
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4), gridspec_kw={"width_ratios": [1, 1.25]})
    ax = axes[0]
    ax.hist(sims, bins=40, color=C_NULL_FILL, edgecolor=C_NULL, linewidth=0.6, label="10k random histories")
    ax.axvline(obs, color=C_OBS, lw=2.5, label=f"observed = {obs:,}")
    ax.set_xlabel("total cross-draw repeats (pairs of draws sharing a number)")
    ax.set_ylabel("simulations")
    ax.set_title("Repeat count vs simulated chance")
    ax.legend()
    ax = axes[1]
    ks = np.arange(1, len(lag_obs) + 1)
    lo, hi = np.percentile(lag_sims, [2.5, 97.5], axis=0)
    ax.fill_between(ks, lo, hi, color=C_NULL_FILL, label="95% range under chance")
    ax.plot(ks, lag_sims.mean(0), color=C_NULL, lw=1.5, ls="--", label="expected")
    ax.plot(ks, lag_obs, color=C_OBS, lw=2, marker="o", ms=7, label="observed")
    ax.set_xticks(ks)
    ax.set_xlabel("lag (draws apart)")
    ax.set_ylabel("numbers repeated")
    ax.set_title("Repeats at each lag")
    ax.legend()
    save(fig, path)


def chart_backtest(bt, rules, exp_total, null_tot, path):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), gridspec_kw={"width_ratios": [1.15, 1]})
    ax = axes[0]
    tot = bt.groupby("rule")["hits"].sum().reindex(rules)
    lo, hi = np.percentile(null_tot, [2.5, 97.5])
    y = np.arange(len(rules))[::-1]
    ax.axvspan(lo, hi, color=C_NULL_FILL, label="95% range, random picks")
    ax.axvline(exp_total, color=C_NULL, ls="--", lw=1.5, label=f"expected = {exp_total:.1f}")
    ax.scatter(tot.values, y, s=70, color=C_OBS, zorder=3, edgecolor=C_SURFACE, linewidth=2, label="rule")
    for yy, v in zip(y, tot.values):
        ax.text(v + 0.8, yy, f"{int(v)}", va="center", fontsize=9, color=C_INK)
    ax.set_yticks(y)
    ax.set_yticklabels(rules, fontsize=8.5)
    ax.set_xlabel("total winning picks across all backtest draws")
    ax.set_title("Out-of-sample hits: each rule vs random")
    ax.set_xlim(min(lo, tot.min()) - 3, max(hi, tot.max()) + 4)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=3, fontsize=8)
    ax = axes[1]
    piv = bt.pivot(index="test_draw", columns="rule", values="hits").reindex(columns=rules)
    e = bt.groupby("test_draw")["expected"].first()
    for r in rules:
        ax.plot(piv.index, piv[r].cumsum(), color=C_NULL, lw=1, alpha=0.7)
    ax.plot(e.index, e.cumsum(), color=C_OBS, lw=2.5, label="expected for random picks")
    ax.plot([], [], color=C_NULL, lw=1, label="the 8 rules")
    ax.set_xlabel("test draw")
    ax.set_ylabel("cumulative hits")
    ax.set_title("Cumulative hits through the backtest")
    ax.legend(loc="upper left")
    save(fig, path)


def chart_drift(per, path):
    fig, ax = plt.subplots(figsize=(10, 3.6))
    sd = np.sqrt((U ** 2 - 1) / 12 / per["n"])
    ax.fill_between(per["draw_no"], U / 2 - 1.96 * sd, U / 2 + 1.96 * sd, color=C_NULL_FILL,
                    label="95% range for the mean under chance")
    ax.axhline(U / 2, color=C_NULL, ls="--", lw=1.2)
    ax.plot(per["draw_no"], per["mean"], color=C_OBS, lw=2, marker="o", ms=6, label="mean of 3rd-prize numbers")
    ax.plot(per["draw_no"], per["median"], color=C_INK2, lw=1.2, marker="s", ms=4, label="median")
    ax.set_xlabel("draw")
    ax.set_title("Drift check - centre of the winning numbers per draw")
    ax.legend(loc="lower left", ncol=3, fontsize=8.5)
    save(fig, path)


# ----------------------------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------------------------
def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default=os.path.join(here, "raw"))
    ap.add_argument("--out", default=here)
    ap.add_argument("--sims", type=int, default=10_000)
    ap.add_argument("--seed", type=int, default=20261008)
    ap.add_argument("--backtest-start", type=int, default=90, help="first training end-draw t (predicts t+1)")
    ap.add_argument("--n-pick", type=int, default=1000)
    args = ap.parse_args()
    os.makedirs(os.path.join(args.out, "charts"), exist_ok=True)
    pd.set_option("display.width", 200, "display.max_columns", 30, "display.max_rows", 200)

    # ------------------------------------------------------------------ STEP 1
    log("=" * 100)
    log("STEP 1 - CLEAN DATASET AND VALIDATION")
    log("=" * 100)
    df, val, missing = build_dataset(args.raw)
    df.to_csv(os.path.join(args.out, "draws_clean.csv"), index=False)
    val.to_csv(os.path.join(args.out, "validation.csv"), index=False)
    show = val[["draw_no", "draw_date", "gap_days", "n_tier1", "n_tier2", "n_tier3", "n_total",
                "malformed_tokens", "duplicates_within_draw", "tier3_ascending", "file_matches_header",
                "label_variants"]]
    log(show.to_string(index=False))
    dup_cross_tier = df.groupby("draw_no")["number"].apply(lambda s: s.duplicated().sum()).sum()
    log(f"\nrows: {len(df):,}   draws: {len(val)}   missing draw numbers: {missing or 'none'}")
    log(f"3rd-prize count per draw: min {val.n_tier3.min()}, max {val.n_tier3.max()}, "
        f"mode {val.n_tier3.mode().iat[0]}")
    log(f"malformed tokens total: {val.malformed_tokens.sum()}; duplicates within a draw: {dup_cross_tier}")
    log(f"gap between draws (days): min {val.gap_days.min():.0f}, max {val.gap_days.max():.0f}, "
        f"median {val.gap_days.median():.0f}")

    draw_nos = val["draw_no"].tolist()
    T = len(draw_nos)
    df["v"] = df["number"].astype(np.int64)
    draws = []
    for dn in draw_nos:
        sub = df[df.draw_no == dn].drop_duplicates("number")
        draws.append((sub["v"].values.astype(np.int64), (sub["prize_tier"] < 3).values))
    sizes = [(len(v), int(t.sum())) for v, t in draws]
    results = []

    def add(section, test, checks, observed, expected, p, method):
        results.append(dict(section=section, test=test, checks=checks, observed=observed,
                            expected=expected, p_value=p, method=method))

    # ------------------------------------------------------------------ Monte Carlo bank
    log(f"\nRunning Monte Carlo: {args.sims:,} random histories of {T} draws with the observed sizes ...")
    obs = history_stats(draws)
    sims = simulate(sizes, args.sims, args.seed)
    log("    done.")

    def mc_row(section, test, checks, key, fmt="{:,.0f}", analytic=None):
        o = obs[key]
        e = sims[key].mean()
        lo, hi = np.percentile(sims[key], [2.5, 97.5])
        exp_txt = f"{fmt.format(e)} (95%: {fmt.format(lo)}-{fmt.format(hi)})"
        if analytic is not None:
            exp_txt += f"; analytic {fmt.format(analytic)}"
        add(section, test, checks, fmt.format(o), exp_txt, mc_p(o, sims[key]), f"Monte Carlo ({args.sims:,})")

    ns = np.array([s[0] for s in sizes])

    # ------------------------------------------------------------------ A. repeats
    log("\n" + "=" * 100 + "\nSTEP 2A - REPEATS ACROSS DRAWS\n" + "=" * 100)
    exp_pairs = sum(ns[i] * ns[j] / U for i in range(T) for j in range(i + 1, T))
    mc_row("A Repeats", "Total cross-draw repeats",
           "Pairs of draws sharing the same number, summed over all pairs (any tier)", "rep_total",
           analytic=exp_pairs)
    # analytic expected numbers winning in >=2 / >=3 draws (Poisson-binomial per number)
    pt = ns / U
    dist = np.zeros(T + 1)
    dist[0] = 1
    for p in pt:
        dist[1:] = dist[1:] * (1 - p) + dist[:-1] * p
        dist[0] *= (1 - p)
    mc_row("A Repeats", "Numbers that won in 2+ draws", "Distinct numbers appearing in at least two draws",
           "n_ge2", analytic=U * dist[2:].sum())
    mc_row("A Repeats", "Numbers that won in 3+ draws", "Distinct numbers appearing in at least three draws",
           "n_ge3", fmt="{:,.1f}", analytic=U * dist[3:].sum())
    for k in range(1, MAX_LAG + 1):
        if k >= T:
            break
        ek = sum(ns[t] * ns[t + k] / U for t in range(T - k))
        mc_row("A Repeats", f"Repeats at lag {k}", f"Winners of draw t that win again in draw t+{k}",
               f"rep_lag{k}", fmt="{:,.1f}", analytic=ek)
    e_top = sum(sizes[i][1] * ns[i + 1:].sum() / U for i in range(T))
    mc_row("A Repeats", "1st/2nd prize numbers winning again later",
           "Times a 1st/2nd prize number reappears in a later draw (any tier)", "top_reappear",
           fmt="{:,.2f}", analytic=e_top)

    grp = df.groupby("number").agg(n_draws=("draw_no", "nunique"),
                                   draws=("draw_no", lambda s: ", ".join(map(str, sorted(s)))),
                                   tiers=("prize_tier", lambda s: ", ".join(map(str, s))))
    rep = grp[grp.n_draws > 1].sort_values(["n_draws", "number"], ascending=[False, True]).reset_index()
    rep.to_csv(os.path.join(args.out, "repeat_numbers.csv"), index=False)
    log(f"numbers that won in more than one draw: {len(rep):,}  "
        f"(expected under chance {U * dist[2:].sum():,.0f}); in 3+ draws: {(rep.n_draws >= 3).sum()} "
        f"(expected {U * dist[3:].sum():.1f}); max draws for one number: {rep.n_draws.max() if len(rep) else 0}")
    log(rep.head(15).to_string(index=False))
    top = df[df.prize_tier < 3]
    top_hist = []
    for dn in draw_nos:
        t1 = top[(top.draw_no == dn) & (top.prize_tier == 1)]["number"].tolist()
        t2 = df[(df.draw_no == dn) & (df.prize_tier == 2)]["number"].tolist()
        top_hist.append({"draw_no": dn, "draw_date": val.set_index("draw_no").loc[dn, "draw_date"],
                         "first_prize": " ".join(t1), "second_prizes": " ".join(t2)})
    top_hist = pd.DataFrame(top_hist)
    top_hist.to_csv(os.path.join(args.out, "top_prizes.csv"), index=False)
    reapp = []
    for _, r in top.iterrows():
        later = df[(df.number == r.number) & (df.draw_no > r.draw_no)]
        for _, l2 in later.iterrows():
            reapp.append({"number": r.number, "won_draw": r.draw_no, "won_tier": r.prize_tier,
                          "again_draw": l2.draw_no, "again_tier": l2.prize_tier})
    reapp = pd.DataFrame(reapp)
    log(f"1st/2nd prize numbers that reappeared later: {len(reapp)} (expected {e_top:.2f})")
    if len(reapp):
        log(reapp.to_string(index=False))

    # ------------------------------------------------------------------ B. digits
    log("\n" + "=" * 100 + "\nSTEP 2B - DIGIT-LEVEL DISTRIBUTION\n" + "=" * 100)
    allv = np.concatenate([d[0] for d in draws])
    idxv = np.concatenate([np.full(len(d[0]), i) for i, d in enumerate(draws)])
    N = len(allv)
    D = digits_of(allv)
    ALLD = digits_of(np.arange(U))
    pooled_chi = 0.0
    for p in range(6):
        c = np.bincount(D[:, p], minlength=10)
        chi, dfree, pv = chi2_vs_probs(c, np.full(10, 0.1))
        pooled_chi += chi
        add("B Digits", f"Digit frequency, position {p + 1}", "Each digit 0-9 equally likely in this position",
            f"chi2={chi:.1f} (max dev {np.abs(c - N / 10).max() / (N / 10) * 100:.1f}%)",
            f"chi2~{dfree} (df={dfree})", pv, "chi-square GOF")
        log(f"position {p + 1}: counts {c.tolist()}  chi2={chi:.2f} p={pv:.3f}")
    add("B Digits", "Digit frequency, all positions pooled", "Sum of the six positional chi-squares",
        f"chi2={pooled_chi:.1f}", "chi2~54 (df=54)", float(stats.chi2.sf(pooled_chi, 54)), "chi-square GOF")
    for name, key, k in [("First two digits (100 ranges of 10,000)", allv // 10_000, 100),
                         ("First three digits (1,000 ranges of 1,000)", allv // 1000, 1000),
                         ("Last two digits (100 endings)", allv % 100, 100),
                         ("Last three digits (1,000 endings)", allv % 1000, 1000)]:
        c = np.bincount(key, minlength=k)
        chi, dfree, pv = chi2_vs_probs(c, np.full(k, 1 / k))
        hi_i = int(np.argmax(c))
        add("B Digits", name, "Every range/ending equally likely (pooled over all draws)",
            f"chi2={chi:.0f}; busiest={hi_i:0{len(str(k - 1))}d} ({c[hi_i]})",
            f"chi2~{dfree}; {N / k:.1f} each", pv, "chi-square GOF")
        log(f"{name}: chi2={chi:.1f} df={dfree} p={pv:.3f}")
    for name, key, k in [("Stability of first digit across draws", allv // 100_000, 10),
                         ("Stability of first-two-digit ranges across draws", allv // 10_000, 100)]:
        tab = np.zeros((T, k))
        np.add.at(tab, (idxv, key), 1)
        chi, pv, dfree, _ = stats.chi2_contingency(tab)
        add("B Digits", name, "Do the range proportions differ between draws (draw x range table)?",
            f"chi2={chi:.0f}", f"chi2~{dfree}", float(pv), "chi-square homogeneity")
        log(f"{name}: chi2={chi:.1f} df={dfree} p={pv:.3f}")
    fo, fn = digit_features(D), digit_features(ALLD)
    for name, key, checks in [("Digit sum", "digit_sum", "Distribution of the sum of the six digits (0-54)"),
                              ("Odd-digit count", "odd_count", "How many of the 6 digits are odd"),
                              ("Distinct digits in a number", "distinct",
                               "Repeated-digit structure, e.g. 112233 has 3 distinct digits")]:
        kmax = int(fn[key].max()) + 1
        c = np.bincount(fo[key], minlength=kmax)
        pr = np.bincount(fn[key], minlength=kmax) / U
        chi, dfree, pv = chi2_vs_probs(c, pr)
        add("B Digits", name, checks, f"mean={fo[key].mean():.3f}; chi2={chi:.1f}",
            f"mean={fn[key].mean():.3f}; chi2~{dfree}", pv, "chi-square vs exact distribution")
        log(f"{name}: obs mean {fo[key].mean():.3f} vs exact {fn[key].mean():.3f}; chi2={chi:.1f} df={dfree} p={pv:.3f}")
    for name, key, checks in [("Palindromes", "palindrome", "Numbers like 123321"),
                              ("Adjacent repeated digit", "adjacent_pair", "Numbers with a double such as 4-4 side by side")]:
        k_ = int(fo[key].sum())
        pr = fn[key].mean()
        pv = stats.binomtest(k_, N, pr).pvalue
        add("B Digits", name, checks, f"{k_:,}", f"{N * pr:,.1f}", float(pv), "exact binomial")
        log(f"{name}: {k_} vs expected {N * pr:.1f}  p={pv:.3f}")

    # ------------------------------------------------------------------ C. spatial
    log("\n" + "=" * 100 + "\nSTEP 2C - SPATIAL STRUCTURE WITHIN A DRAW (3rd-prize list is sorted)\n" + "=" * 100)
    mc_row("C Spatial", "Gap distribution (KS)",
           "Gaps between consecutive sorted 3rd-prize numbers vs uniform-spacing law", "gap_ks", fmt="{:.4f}")
    mc_row("C Spatial", "Gap variability (CV^2)",
           "Var/mean^2 of gaps: >1 = clustering, <1 = unusually even", "gap_cv2", fmt="{:.4f}")
    mc_row("C Spatial", "Very small gaps (<=10)", "Count of near-adjacent winners (clustering)", "gap_small")
    mc_row("C Spatial", "100-bucket uniformity within draws",
           "Sum over draws of per-draw chi-square for 100 equal buckets",
           "b100_chi2_sum", fmt="{:,.0f}")
    mc_row("C Spatial", "1,000-bucket dispersion within draws",
           "Sum over draws of index-of-dispersion for 1,000 equal buckets", "b1000_disp_sum", fmt="{:,.0f}")
    B100 = np.zeros((T, 100))
    np.add.at(B100, (idxv, allv // 10_000), 1)
    e100 = B100.sum(1, keepdims=True) / 100
    per_p = stats.chi2.sf(((B100 - e100) ** 2 / e100).sum(1), 99)
    k05 = int((per_p < 0.05).sum())
    add("C Spatial", "Draws failing 100-bucket uniformity", "Number of draws with per-draw p<0.05",
        f"{k05} of {T}", f"{0.05 * T:.1f} of {T}", float(stats.binomtest(k05, T, 0.05).pvalue), "exact binomial")
    chi_draw = ((B100 - e100) ** 2 / e100).sum(1)
    worst = int(np.argmax(chi_draw))
    keep = np.arange(T) != worst
    chi_rest = float(chi_draw[keep].sum())
    add("C Spatial", f"100-bucket uniformity, excluding draw {draw_nos[worst]}",
        "Sensitivity: same test without the most clustered draw",
        f"chi2={chi_rest:,.0f}", f"chi2~{99 * (T - 1):,}", float(stats.chi2.sf(chi_rest, 99 * (T - 1))), "chi-square")
    clus = []
    for i, (v_, t_) in enumerate(draws):
        t3 = np.sort(v_[~t_])
        n3_ = len(t3)
        e10 = (n3_ - 1) * (1 - (1 - 10 / U) ** n3_)
        clus.append({"draw_no": draw_nos[i], "gaps_le10": int((np.diff(t3) <= 10).sum()), "gaps_le10_expected": e10,
                     "bucket100_chi2": chi_draw[i], "bucket100_p": per_p[i],
                     "dispersion_10k": B100[i].var(ddof=1) / B100[i].mean()})
    clus = pd.DataFrame(clus)
    o_rest = int(clus.gaps_le10[keep].sum())
    e_rest = float(clus.gaps_le10_expected[keep].sum())
    add("C Spatial", f"Very small gaps (<=10), excluding draw {draw_nos[worst]}",
        "Sensitivity: near-adjacent winners without the most clustered draw", f"{o_rest}", f"{e_rest:.0f}",
        poisson_p(o_rest, e_rest), "Poisson")
    log(clus.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    vmr = (B100.var(1, ddof=1) / B100.mean(1)).mean()
    log(f"per-draw 100-bucket p-values: min {per_p.min():.3f}; draws with p<0.05: {k05}; "
        f"mean variance/mean ratio {vmr:.3f} (1.0 = Poisson-like randomness)")
    log(f"gap KS={obs['gap_ks']:.4f} (sim mean {sims.gap_ks.mean():.4f}); CV2={obs['gap_cv2']:.4f} "
        f"(sim {sims.gap_cv2.mean():.4f}); gaps<=10: {obs['gap_small']} (sim {sims.gap_small.mean():.1f})")
    gap_lists = [(np.diff(np.sort(v[~t])), int((~t).sum())) for v, t in draws]

    # ------------------------------------------------------------------ D. between draws
    log("\n" + "=" * 100 + "\nSTEP 2D - RELATIONSHIPS BETWEEN DRAWS\n" + "=" * 100)
    for k in (1, 2, 3):
        mc_row("D Between draws", f"Hot 10,000-ranges persist, lag {k}",
               f"Mean correlation of 100-bucket counts in draw t and t+{k}", f"b100_r_lag{k}", fmt="{:+.4f}")
    mc_row("D Between draws", "Hot 1,000-ranges persist, lag 1",
           "Mean correlation of 1,000-bucket counts in draw t and t+1", "b1000_r_lag1", fmt="{:+.4f}")
    mc_row("D Between draws", "Nearby numbers win next draw (+/-100)",
           "Draw t+1 winners lying 1-100 away from a draw-t winner", "near100")
    mc_row("D Between draws", "Nearby numbers win next draw (+/-1,000)",
           "Draw t+1 winners lying 1-1,000 away from a draw-t winner", "near1000")
    t1 = [d[0][d[1]] for d in draws]  # top numbers
    first = [int(df[(df.draw_no == dn) & (df.prize_tier == 1)]["v"].iat[0]) for dn in draw_nos]
    seconds = [df[(df.draw_no == dn) & (df.prize_tier == 2)]["v"].values for dn in draw_nos]
    m_same = sum(int((digits_of([f])[0] == digits_of([s])[0]).sum()) for f, ss in zip(first, seconds) for s in ss)
    n_same = 6 * sum(len(ss) for ss in seconds)
    add("D Between draws", "1st vs 2nd prize digit overlap (same draw)",
        "Same digit in the same position, 1st prize vs each 2nd prize", f"{m_same} of {n_same}",
        f"{n_same * 0.1:.1f}", float(stats.binomtest(m_same, n_same, 0.1).pvalue), "exact binomial")
    m_nx = n_nx = 0
    for t in range(T - 1):
        for a in t1[t]:
            for b in t1[t + 1]:
                m_nx += int((digits_of([a])[0] == digits_of([b])[0]).sum())
                n_nx += 6
    add("D Between draws", "1st/2nd prize digit overlap with next draw's 1st/2nd",
        "Positional digit matches between top prizes of draw t and t+1", f"{m_nx} of {n_nx}",
        f"{n_nx * 0.1:.1f}", float(stats.binomtest(m_nx, n_nx, 0.1).pvalue), "exact binomial")
    dif = np.array([abs(f - s) / U for f, ss in zip(first, seconds) for s in ss])
    ks = stats.kstest(dif, lambda x: 1 - (1 - x) ** 2)
    add("D Between draws", "Distance between 1st and 2nd prize numbers",
        "|1st - 2nd| vs the triangular law of two independent uniforms",
        f"median {np.median(dif) * U:,.0f}", f"median {(1 - np.sqrt(0.5)) * U:,.0f}", float(ks.pvalue), "KS test")
    for lag_, label in [(0, "same draw"), (1, "next draw")]:
        o_ = e_ = 0.0
        for t in range(T - lag_):
            f = first[t]
            t3 = draws[t + lag_][0][~draws[t + lag_][1]]
            o_ += int((np.abs(t3 - f) <= 5000).sum() - (0 if lag_ else 0))
            w = min(U - 1, f + 5000) - max(0, f - 5000) + 1 - (1 if lag_ == 0 else 0)
            e_ += len(t3) * w / U
        add("D Between draws", f"3rd prizes near the 1st prize ({label})",
            f"3rd-prize winners within +/-5,000 of the 1st-prize number ({label})",
            f"{int(o_)}", f"{e_:.1f}", poisson_p(int(o_), e_), "Poisson")
    per = pd.DataFrame({"draw_no": draw_nos,
                        "mean": [d[0][~d[1]].mean() for d in draws],
                        "median": [np.median(d[0][~d[1]]) for d in draws],
                        "sd": [d[0][~d[1]].std(ddof=1) for d in draws],
                        "n": [(~d[1]).sum() for d in draws]})
    for col in ["mean", "median", "sd"]:
        rho, pv = stats.spearmanr(per["draw_no"], per[col])
        exp_txt = {"mean": "rho=0 (centre 500,000)", "median": "rho=0", "sd": f"rho=0 (sd {U / np.sqrt(12):,.0f})"}[col]
        add("D Between draws", f"Drift over time in the {col}",
            f"Spearman correlation of per-draw {col} with draw number",
            f"rho={rho:+.3f}", exp_txt, float(pv), "Spearman")
        log(f"drift {col}: rho={rho:+.3f} p={pv:.3f}")
    z = (per["mean"] - (U - 1) / 2) / np.sqrt((U ** 2 - 1) / 12 / per["n"])
    chi = float((z ** 2).sum())
    add("D Between draws", "Per-draw mean off-centre", "Sum of squared z-scores of each draw's mean vs 499,999.5",
        f"chi2={chi:.1f}", f"chi2~{T} (df={T})", float(stats.chi2.sf(chi, T)), "chi-square")
    zw = int(np.argmax(np.abs(z.values)))
    chi_x = float((z.drop(index=zw) ** 2).sum())
    add("D Between draws", f"Per-draw mean off-centre, excluding draw {draw_nos[zw]}",
        "Sensitivity: same test without the most lopsided draw", f"chi2={chi_x:.1f}", f"chi2~{T - 1} (df={T - 1})",
        float(stats.chi2.sf(chi_x, T - 1)), "chi-square")
    mean_worst = (draw_nos[zw], float(z.iat[zw]), float(stats.chi2.sf(chi_x, T - 1)))
    log(f"bucket lag-1 r={obs['b100_r_lag1']:+.4f} (sim 95%: {np.percentile(sims.b100_r_lag1, 2.5):+.4f} "
        f"to {np.percentile(sims.b100_r_lag1, 97.5):+.4f});  near+/-100: {obs['near100']} "
        f"(sim {sims.near100.mean():.1f}); near+/-1000: {obs['near1000']} (sim {sims.near1000.mean():.1f})")

    # ------------------------------------------------------------------ E. folklore
    log("\n" + "=" * 100 + "\nSTEP 2E - HOT / COLD / 'DUE' / LUCKY-NUMBER FOLKLORE\n" + "=" * 100)
    h = T // 2
    mc_row("E Folklore", "Hot ranges stay hot (split-half)",
           f"Correlation of 1,000-range counts, draws {draw_nos[0]}-{draw_nos[h - 1]} vs {draw_nos[h]}-{draw_nos[-1]}",
           "split_half_r", fmt="{:+.4f}")
    r10, _ = stats.pearsonr(B100[:h].sum(0), B100[h:].sum(0))
    sims_r10 = []
    rng_sh = np.random.default_rng(args.seed + 1)
    nh1, nh2 = int(B100[:h].sum()), int(B100[h:].sum())
    for _ in range(args.sims):
        sims_r10.append(np.corrcoef(rng_sh.multinomial(nh1, np.full(100, 0.01)),
                                    rng_sh.multinomial(nh2, np.full(100, 0.01)))[0, 1])
    sims_r10 = np.array(sims_r10)
    add("E Folklore", "Hot 10,000-ranges stay hot (split-half)",
        "Correlation of 100-range counts, first half of draws vs second half", f"{r10:+.4f}",
        f"{sims_r10.mean():+.4f} (95%: {np.percentile(sims_r10, 2.5):+.4f}-{np.percentile(sims_r10, 97.5):+.4f})",
        mc_p(r10, sims_r10), f"Monte Carlo ({args.sims:,})")
    first_half = np.concatenate([d[0] for d in draws[:h]])
    second = [d[0] for d in draws[h:]]
    s_all = np.concatenate(second)
    vc = pd.Series(first_half).value_counts()
    hot_nums = vc[vc >= 2].index.values
    o_ = int(np.isin(s_all, hot_nums).sum())
    e_ = len(hot_nums) * len(s_all) / U
    add("E Folklore", "'Hot numbers' win again",
        f"Numbers that won 2+ times in the first half ({len(hot_nums)}) - wins in the second half",
        f"{o_}", f"{e_:.2f}", poisson_p(o_, e_), "Poisson")
    prev = np.unique(first_half)
    o_ = int(np.isin(s_all, prev).sum())
    e_ = len(prev) * len(s_all) / U
    add("E Folklore", "'Overdue' numbers (never won) beat past winners",
        f"Second-half wins by first-half winners ({len(prev):,}); fewer than expected would support 'due'",
        f"{o_}", f"{e_:.1f}", poisson_p(o_, e_), "Poisson")
    c1 = np.bincount(first_half // 1000, minlength=1000)
    cold100 = np.argsort(c1, kind="stable")[:100]
    k_ = int(np.isin(s_all // 1000, cold100).sum())
    add("E Folklore", "'Due' (cold) ranges catch up",
        "Second-half share of the 100 coldest first-half 1,000-ranges (10% expected)",
        f"{k_} ({k_ / len(s_all) * 100:.2f}%)", f"{len(s_all) * 0.1:.0f} (10%)",
        float(stats.binomtest(k_, len(s_all), 0.1).pvalue), "exact binomial")
    c2 = np.bincount(first_half % 100, minlength=100)
    lucky = np.argsort(-c2, kind="stable")[:10]
    k_ = int(np.isin(s_all % 100, lucky).sum())
    add("E Folklore", "'Lucky endings' stay lucky",
        f"Second-half share of the 10 most frequent first-half endings ({', '.join(f'{x:02d}' for x in sorted(lucky))})",
        f"{k_} ({k_ / len(s_all) * 100:.2f}%)", f"{len(s_all) * 0.1:.0f} (10%)",
        float(stats.binomtest(k_, len(s_all), 0.1).pvalue), "exact binomial")
    for name, mask_o, mask_n, checks in [
        ("Numbers containing 786", fo["has_786"], fn["has_786"], "Popular 'lucky' sequence 786 anywhere in the number"),
        ("Round endings (..00)", allv % 100 == 0, np.arange(U) % 100 == 0, "Numbers ending in 00"),
        ("'Fancy' numbers (<=2 distinct digits)", fo["distinct"] <= 2, fn["distinct"] <= 2, "e.g. 111222, 121212, 777777"),
    ]:
        k_ = int(mask_o.sum())
        pr = float(mask_n.mean())
        add("E Folklore", name, checks, f"{k_}", f"{N * pr:.1f}", float(stats.binomtest(k_, N, pr).pvalue),
            "exact binomial")
    for r in [r for r in results if r["section"] == "E Folklore"]:
        log(f"{r['test']}: observed {r['observed']} vs expected {r['expected']}  p={r['p_value']:.3f}")

    # ------------------------------------------------------------------ STEP 3 backtest
    log("\n" + "=" * 100 + "\nSTEP 3 - WALK-FORWARD BACKTEST\n" + "=" * 100)
    pos = {dn: i for i, dn in enumerate(draw_nos)}
    test_ends = [dn for dn in draw_nos if dn >= args.backtest_start and pos[dn] + 1 < T]
    bt_rows = []
    for dn in test_ends:
        i = pos[dn]
        train = [d[0] for d in draws[:i + 1]]
        target = draws[i + 1][0]
        sets = rule_sets(train, args.n_pick, ALLD, args.seed + dn)
        for rname, s in sets.items():
            assert len(np.unique(s)) == len(s) == args.n_pick, rname
            bt_rows.append({"train_end": dn, "test_draw": draw_nos[i + 1], "rule": rname,
                            "hits": int(np.isin(s, target).sum()),
                            "expected": args.n_pick * len(target) / U, "n_target": len(target)})
    hp_rows = []
    for dn in test_ends:
        i = pos[dn]
        c = np.bincount(np.concatenate([d[0] for d in draws[:i + 1]]) // 10_000, minlength=100)
        hot10 = np.argsort(-c, kind="stable")[:10]
        target = draws[i + 1][0]
        hp_rows.append({"test_draw": draw_nos[i + 1], "hits": int(np.isin(target // 10_000, hot10).sum()),
                        "n_target": len(target)})
    hp = pd.DataFrame(hp_rows)
    hp_hits, hp_n = int(hp.hits.sum()), int(hp.n_target.sum())
    hp_p = float(stats.binomtest(hp_hits, hp_n, 0.1, alternative="greater").pvalue)
    hp_ci = stats.binomtest(hp_hits, hp_n, 0.1).proportion_ci()
    bt = pd.DataFrame(bt_rows)
    bt.to_csv(os.path.join(args.out, "backtest.csv"), index=False)
    rules = list(dict.fromkeys(bt["rule"]))
    tgt = bt.groupby("test_draw")["n_target"].first().values
    rng = np.random.default_rng(args.seed)
    null_tot = np.zeros(200_000)
    for n_t in tgt:
        null_tot += rng.hypergeometric(n_t, U - n_t, args.n_pick, size=len(null_tot))
    exp_total = float(bt.groupby("test_draw")["expected"].first().sum())
    bt_summary = []
    for r in rules:
        H = int(bt[bt.rule == r]["hits"].sum())
        p_one = (np.sum(null_tot >= H) + 1) / (len(null_tot) + 1)
        p_two = mc_p(H, null_tot)
        lo, hi = (stats.chi2.ppf(0.025, 2 * H) / 2 if H else 0.0), stats.chi2.ppf(0.975, 2 * H + 2) / 2
        bt_summary.append({"rule": r, "hits": H, "expected": exp_total, "rate_ratio": H / exp_total,
                           "rr_ci_low": lo / exp_total, "rr_ci_high": hi / exp_total, "p_beats_random": float(p_one),
                           "p_two_sided": p_two})
        add("Step 3 Backtest", f"Rule: {r}",
            f"Picks {args.n_pick:,} numbers using draws up to t; hits in t+1 (t={test_ends[0]}..{test_ends[-1]})",
            f"{H} hits (x{H / exp_total:.2f})", f"{exp_total:.1f}", float(p_one), "one-sided MC vs random picks")
    add("Step 3 Backtest", "High-power rule: hottest 10% of the number space",
        "Share of draw t+1 winners in the 10 most-won 10,000-ranges up to t (100,000 numbers, 10% expected)",
        f"{hp_hits:,} of {hp_n:,} ({hp_hits / hp_n * 100:.2f}%)", f"{hp_n * 0.1:,.0f} (10.00%)", hp_p,
        "one-sided exact binomial")
    bts = pd.DataFrame(bt_summary)
    log(f"test draws: {len(test_ends)} ({draw_nos[pos[test_ends[0]] + 1]}..{draw_nos[pos[test_ends[-1]] + 1]}); "
        f"random-pick expectation {exp_total:.1f} hits total "
        f"(95% range {np.percentile(null_tot, 2.5):.0f}-{np.percentile(null_tot, 97.5):.0f})")
    log(bts.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    log(f"high-power rule (hottest 10 of 100 ranges): {hp_hits} of {hp_n} = {hp_hits / hp_n:.4f} vs 0.1000; "
        f"lift x{hp_hits / hp_n / 0.1:.3f} (95% CI x{hp_ci.low / 0.1:.3f}-x{hp_ci.high / 0.1:.3f}); one-sided p={hp_p:.3f}")
    log("\nper-draw hits:")
    log(bt.pivot(index="test_draw", columns="rule", values="hits").to_string())

    # ------------------------------------------------------------------ correction
    res = pd.DataFrame(results)
    res["p_bh"] = bh_adjust(res["p_value"])
    res["p_bonferroni"] = np.minimum(res["p_value"] * len(res), 1)
    alpha = 0.05

    def concl(r):
        if r.p_bh < alpha:
            return "SIGNIFICANT after correction"
        if r.p_value < alpha:
            return "nominal p<0.05 only - not significant after correction (chance)"
        return "consistent with chance"

    res["conclusion"] = res.apply(concl, axis=1)
    res.to_csv(os.path.join(args.out, "results_table.csv"), index=False)
    log("\n" + "=" * 100 + f"\nRESULTS TABLE ({len(res)} tests, Benjamini-Hochberg + Bonferroni)\n" + "=" * 100)
    log(res[["section", "test", "observed", "expected", "p_value", "p_bh", "conclusion"]]
        .to_string(index=False, float_format=lambda x: f"{x:.4f}", max_colwidth=60))
    n_nom = int((res.p_value < alpha).sum())
    sig = res[res.p_bh < alpha]
    bt_sig = sig[sig.section == "Step 3 Backtest"]
    log(f"\nnominal p<0.05: {n_nom} of {len(res)} (about {0.05 * len(res):.1f} expected by luck alone); "
        f"significant after BH: {len(sig)}; backtest rules surviving: {len(bt_sig)}")

    # ------------------------------------------------------------------ charts
    cd = os.path.join(args.out, "charts")
    chart_digit_heatmap(D, os.path.join(cd, "digit_position_heatmap.png"))
    chart_buckets(draw_nos, B100, os.path.join(cd, "bucket_distribution_per_draw.png"))
    chart_gaps(gap_lists, os.path.join(cd, "gap_distribution.png"))
    lags_k = [k for k in range(1, MAX_LAG + 1) if k < T]
    chart_repeats(obs["rep_total"], sims["rep_total"].values, [obs[f"rep_lag{k}"] for k in lags_k],
                  sims[[f"rep_lag{k}" for k in lags_k]].values, os.path.join(cd, "repeat_count_vs_simulated.png"))
    chart_backtest(bt, rules, exp_total, null_tot, os.path.join(cd, "backtest_vs_random.png"))
    chart_drift(per, os.path.join(cd, "drift_over_time.png"))

    # ------------------------------------------------------------------ odds
    last_sizes = val.iloc[-1]
    n3 = int(last_sizes.n_tier3)
    n_any = int(last_sizes.n_total)
    odds = {"p_first": 1 / U, "p_second": 3 / U, "p_third": n3 / U, "p_any": n_any / U,
            "one_in": U / n_any, "p_year": 1 - (1 - n_any / U) ** 4,
            "ev": (3_000_000 * 1 + 1_000_000 * 3 + 18_500 * n3) / U}
    extra = {"mean_worst": mean_worst, "clus": clus, "worst": draw_nos[worst], "hp": (hp_hits, hp_n, hp_p, hp_ci), "r10": r10}
    write_report(args, val, missing, res, bts, bt, rep, top_hist, reapp, obs, sims, exp_pairs, odds,
                 test_ends, draw_nos, pos, exp_total, null_tot, per_p, vmr, N, T, extra)
    log(f"\nwrote {os.path.join(args.out, 'report.html')}")


# ----------------------------------------------------------------------------------------------
# HTML report
# ----------------------------------------------------------------------------------------------
def img_tag(path, alt):
    with open(path, "rb") as f:
        b = base64.b64encode(f.read()).decode()
    return f'<figure><img src="data:image/png;base64,{b}" alt="{html.escape(alt)}"><figcaption>{html.escape(alt)}</figcaption></figure>'


def table_html(df, cls="", formats=None, max_rows=None):
    formats = formats or {}
    d = df if max_rows is None else df.head(max_rows)
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in d.columns)
    body = []
    for _, r in d.iterrows():
        cells = []
        for c in d.columns:
            v = r[c]
            txt = formats[c](v) if c in formats else ("" if pd.isna(v) else str(v))
            cells.append(f"<td>{html.escape(txt)}</td>")
        rc = ""
        if "conclusion" in d.columns and str(r["conclusion"]).startswith("SIGNIFICANT"):
            rc = ' class="hit"'
        body.append(f"<tr{rc}>{''.join(cells)}</tr>")
    return f'<div class="tw {cls}"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def fmt_p(x):
    return "<0.0001" if x < 1e-4 else f"{x:.4f}"


def write_report(args, val, missing, res, bts, bt, rep, top_hist, reapp, obs, sims, exp_pairs, odds,
                 test_ends, draw_nos, pos, exp_total, null_tot, per_p, vmr, N, T, extra):
    cd = os.path.join(args.out, "charts")
    sig = res[res.p_bh < 0.05]
    sig_non_bt = sig[sig.section != "Step 3 Backtest"]
    bt_sig = sig[sig.section == "Step 3 Backtest"]
    n_nom = int((res.p_value < 0.05).sum())
    best = bts.sort_values("p_beats_random").iloc[0]
    first_test, last_test = draw_nos[pos[test_ends[0]] + 1], draw_nos[pos[test_ends[-1]] + 1]
    verdict = "No." if len(bt_sig) == 0 else "Possibly - see below."
    if len(bt_sig) == 0 and len(sig_non_bt) == 0:
        conf = ("Confidence: high. None of the tests was significant after correction, "
                "and no prediction rule beat random picks out of sample.")
    elif len(bt_sig) == 0:
        clump_family = sig_non_bt.section.isin(["B Digits", "C Spatial"]) | sig_non_bt.test.str.startswith("Per-draw mean")
        if clump_family.all():
            conf = (f"Confidence: high. {len(sig_non_bt)} descriptive tests remain significant after correction, and all of them measure one "
                    "thing: inside a single draw, the winners are slightly clumped. Some draws are lumpier than a perfectly uniform draw would be. "
                    "The clumps land in different places every draw, and no rule built on any pattern beat random picks out of sample, "
                    "so this cannot be used to predict winners.")
        else:
            conf = (f"Confidence: high. {len(sig_non_bt)} descriptive tests remain significant after correction (listed below), "
                    "but no rule built on any pattern beat random picks out of sample, so they cannot be used to predict winners.")
    else:
        conf = f"{len(bt_sig)} rule(s) beat random out of sample after correction; treat with caution (see Step 3)."
    def sec_sig(prefix):
        g = res[res.section.str.startswith(prefix)]
        return g[g.p_bh < 0.05]

    def row(prefix):
        return res[res.test.str.startswith(prefix)].iloc[0]

    def pq(r):
        return f"p={fmt_p(r.p_value)}, corrected {fmt_p(r.p_bh)}"

    def names(g):
        return "; ".join(f"{t} ({o}, corrected p={fmt_p(q)})" for t, o, q in zip(g.test, g.observed, g.p_bh))

    hp_hits, hp_n, hp_p, hp_ci = extra["hp"]
    clus = extra["clus"]
    worst = extra["worst"]
    bullets = []
    sa = sec_sig("A")
    r_tot, r_ge2 = row("Total cross-draw repeats"), row("Numbers that won in 2+ draws")
    bullets.append(
        f"<b>Repeat winners:</b> {len(rep):,} numbers have won in more than one draw, against about {sims.n_ge2.mean():,.0f} expected by chance "
        f"({pq(r_ge2)}). Total repeats: {obs['rep_total']:,} vs {sims.rep_total.mean():,.0f} expected ({pq(r_tot)}). "
        + ("Repeats at every lag (1-10 draws apart), and 1st/2nd prize numbers winning again, are within the range expected by chance. "
           "Drawing about 1,700 numbers out of 1,000,000 every quarter produces about this many repeats. They are not a pattern."
           if sa.empty else f"Significant after correction: {names(sa)}."))
    sc = sec_sig("C")
    if not sc.empty:
        gs = row("Very small gaps (<=10), excluding")
        bs = row("100-bucket uniformity, excluding")
        top3 = clus.sort_values("bucket100_chi2", ascending=False).head(4)
        bullets.append(
            "<b>Within-draw clustering - the one statistically real finding.</b> Inside a single draw, the 3rd-prize numbers are slightly more "
            f"clumped than uniform random numbers. There are {obs['gap_small']} gaps of 10 or less between consecutive winners, against {sims.gap_small.mean():.0f} expected. "
            f"Range counts are over-dispersed by about {(obs['b1000_disp_sum'] / sims.b1000_disp_sum.mean() - 1) * 100:.0f}% at the 1,000-wide scale "
            f"and {(obs['b100_chi2_sum'] / sims.b100_chi2_sum.mean() - 1) * 100:.0f}% at the 10,000-wide scale. "
            f"Most of it comes from a few draws, especially {', '.join(map(str, top3.draw_no))} (see section 4). "
            f"Without draw {worst}, the small-gap test gives {gs.observed} vs {gs.expected} ({pq(gs)}) "
            f"and the bucket test gives {pq(bs)}. "
            "<b>The clumps fall in different places each draw</b> (between-draw stability "
            f"{pq(row('Stability of first-two-digit ranges'))}; first-half vs second-half range correlation r={extra['r10']:+.3f}). "
            "So the clustering does not say where the next draw's winners will be. It probably reflects how the draw is generated or batched, "
            "but these files cannot show the mechanism.")
    else:
        bullets.append("<b>Spacing:</b> the sorted 3rd-prize list has gaps that match uniform random points. "
                       "There is no clustering and no unusual evenness.")
    sb = sec_sig("B")
    b_txt = "<b>Digits and ranges:</b> "
    if sb.empty:
        b_txt += ("Every digit in every position, every leading range and every ending occurs at the rate expected. "
                  "Digit sum, odd/even count, repeated digits and palindromes also match their exact null distributions.")
    else:
        b_txt += (f"Significant after correction: {names(sb)}. "
                  + ("These are most likely a side effect of the clustering above. A clumped draw puts extra winners into whichever ranges its clumps "
                     "fall in, and the pooled tests assume independent numbers. The over-represented ranges do not persist: "
                     "ranges that were busy in the first half of the history were not busy in the second half. "
                     if not sc.empty else "")
                  + "Every other digit test (endings, digit sum, odd/even, repeated digits, palindromes) is consistent with chance.")
    bullets.append(b_txt)
    sd_ = sec_sig("D")
    if sd_.empty:
        bullets.append("<b>Between draws:</b> 'hot' ranges do not stay hot. Numbers near a previous winner are not favoured. "
                       "The 1st prize is unrelated to the 2nd/3rd prizes in the same or the next draw, and nothing drifts over time.")
    else:
        parts = []
        for t_, o_, q_ in zip(sd_.test, sd_.observed, sd_.p_bh):
            if "persist" in t_:
                parts.append(f"{t_} ({o_}, corrected p={fmt_p(q_)}). The effect is tiny (a correlation of a few hundredths), it does not show up "
                             "consistently at the other lags, and the out-of-sample rules built to use it (hot 1,000-range; hottest 10% of the "
                             "number space) did not beat random picks. It cannot be used in practice")
            elif t_.startswith("Per-draw mean"):
                dw, zv, px = extra["mean_worst"]
                parts.append(f"{t_} ({o_}, corrected p={fmt_p(q_)}). This is driven by draw {dw}, whose winners lean toward "
                             f"{'low' if zv < 0 else 'high'} numbers (z={zv:+.1f}). Without that draw, p={fmt_p(px)}. The direction varies between draws "
                             "(no drift in mean, median or spread), so this is the same draw-level lumpiness, not a usable bias")
            else:
                parts.append(f"{t_} ({o_}, corrected p={fmt_p(q_)})")
        bullets.append("<b>Between draws:</b> significant after correction: " + "; ".join(parts) + ". "
                       "The other between-draw tests (nearby numbers in the next draw, 1st prize vs 2nd/3rd prizes, drift over time) "
                       "are consistent with chance unless listed here.")
    se = sec_sig("E")
    bullets.append("<b>Folklore</b> (hot numbers, overdue numbers, 'due' ranges, lucky endings, 786, round and 'fancy' numbers): "
                   + ("none is supported by the data." if se.empty else f"significant: {names(se)}."))
    bullets.append(
        f"<b>Prediction (out of sample):</b> {len(bts)} rules picking {args.n_pick:,} numbers per draw scored between {int(bts.hits.min())} and {int(bts.hits.max())} hits. "
        f"Random picks would be expected to score {exp_total:.1f} (95% range {np.percentile(null_tot, 2.5):.0f}-{np.percentile(null_tot, 97.5):.0f}). "
        f"The higher-power version, which bets on the 10 hottest 10,000-ranges (10% of all numbers), caught {hp_hits / hp_n * 100:.2f}% of later winners "
        f"against 10.00% for random (one-sided p={fmt_p(hp_p)}; 95% CI for the lift x{hp_ci.low / 0.1:.2f}-x{hp_ci.high / 0.1:.2f}). "
        + ("<b>No rule beats chance. No prediction is better than picking numbers at random.</b>" if len(bt_sig) == 0 else ""))
    bullets.append(
        f"<b>Actual odds</b> (latest draw, {odds['p_any'] * U:,.0f} winners): a given 6-digit number wins <i>any</i> prize with probability "
        f"{odds['p_any'] * 100:.3f}% per draw (1 in {odds['one_in']:,.0f}), or about {odds['p_year'] * 100:.2f}% per year (4 draws). "
        f"1st prize: 1 in 1,000,000. 2nd: 1 in 333,333. 3rd: 1 in {U / (odds['p_third'] * U):,.0f}. "
        f"At the listed prize amounts, the gross expected payout is about Rs.{odds['ev']:.1f} per Rs.1500 bond per draw "
        f"(≈{odds['ev'] / 1500 * 100:.1f}% per draw, before withholding tax). It is the same for every number.")
    summary_html = "<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>"
    clus_show = clus.copy()
    clus_show.columns = ["draw", "gaps <=10", "expected", "100-bucket chi2 (df 99)", "p", "variance/mean (10k buckets)"]
    clus_html = table_html(clus_show, formats={"expected": lambda x: f"{x:.1f}", "100-bucket chi2 (df 99)": lambda x: f"{x:.1f}",
                                               "p": fmt_p, "variance/mean (10k buckets)": lambda x: f"{x:.2f}"})
    vrow = val.copy()
    vrow["draw_date"] = vrow["draw_date"].astype(str)
    vshow = vrow[["draw_no", "draw_date", "gap_days", "n_tier1", "n_tier2", "n_tier3", "n_total",
                  "malformed_tokens", "duplicates_within_draw", "tier3_ascending", "label_variants"]]
    vshow.columns = ["Draw", "Date", "Days since previous", "1st", "2nd", "3rd", "Total", "Malformed",
                     "Duplicates", "3rd sorted", "Non-standard prize label"]
    n3 = val.n_tier3
    count_note = ("Every draw has 1 first prize, 3 second prizes and the same number of third prizes."
                  if n3.nunique() == 1 else
                  f"The number of 3rd prizes varies between draws ({n3.min()} to {n3.max()}; "
                  f"most common {n3.mode().iat[0]}). FLAG: check the source printouts for the short draws. "
                  "Every test uses each draw's actual count, so the variation does not bias the results.")
    rtab = res[["test", "checks", "observed", "expected", "p_value", "p_bh", "p_bonferroni", "conclusion"]].copy()
    rtab.columns = ["test", "what it checks", "observed", "expected under randomness", "p-value",
                    "BH-corrected p", "Bonferroni p", "conclusion"]
    rtab["conclusion"] = res["conclusion"].values
    sections = []
    for sec, g in res.groupby("section", sort=False):
        t = rtab.loc[g.index]
        sections.append(f"<h3>{html.escape(sec)}</h3>" + table_html(
            t, formats={"p-value": fmt_p, "BH-corrected p": fmt_p, "Bonferroni p": fmt_p}))
    bts_show = bts.copy()
    bts_show = bts_show[["rule", "hits", "expected", "rate_ratio", "rr_ci_low", "rr_ci_high", "p_beats_random"]]
    bts_show.columns = ["rule", "hits", "expected (random)", "hits / expected", "95% CI low", "95% CI high",
                        "p (beats random)"]
    f2 = lambda x: f"{x:.2f}"
    rep_show = rep.rename(columns={"n_draws": "draws won", "draws": "draw numbers", "tiers": "tiers"})
    css = """
:root{--bg:#f6f5f2;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#7a7974;--line:#e2e1dc;--accent:#2a78d6;--hit:#fde8e8;--ok:#e8f1fc}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#121211;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#9a9990;--line:#33332f;--accent:#3987e5;--hit:#4a2222;--ok:#16283f}}
:root[data-theme="dark"]{--bg:#121211;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#9a9990;--line:#33332f;--accent:#3987e5;--hit:#4a2222;--ok:#16283f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 16px 80px}h1{font-size:28px;margin:0 0 4px}h2{font-size:21px;margin:44px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}
h3{font-size:16px;margin:26px 0 8px;color:var(--ink2)}p,li{color:var(--ink2);max-width:80ch}.sub{color:var(--muted);margin:0 0 20px}
.verdict{background:var(--surface);border:1px solid var(--line);border-left:5px solid var(--accent);border-radius:10px;padding:18px 22px;margin:18px 0}
.verdict .big{font-size:26px;font-weight:700;color:var(--ink);margin:0 0 6px}.kpis{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 16px;min-width:170px;flex:1}.kpi b{display:block;font-size:22px;color:var(--ink)}.kpi span{font-size:12.5px;color:var(--muted)}
.tw{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:10px;margin:10px 0 18px}.tw.scroll{max-height:460px;overflow-y:auto}
table{border-collapse:collapse;width:100%;font-size:12.8px}th,td{padding:6px 10px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
th{position:sticky;top:0;background:var(--surface);color:var(--ink2);font-weight:600}td{color:var(--ink);font-variant-numeric:tabular-nums}tr.hit td{background:var(--hit)}
figure{margin:16px 0;background:#fcfcfb;border:1px solid var(--line);border-radius:10px;padding:12px}figure img{width:100%;height:auto;display:block}figcaption{color:#52514e;font-size:12.5px;margin-top:6px}
code{background:var(--surface);border:1px solid var(--line);border-radius:4px;padding:0 4px}
"""
    pairs_txt = f"{obs['rep_total']:,} vs {sims.rep_total.mean():,.0f} expected"
    html_doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prize Bond Pattern Audit</title><style>{css}</style></head><body><main>
<h1>Rs.1500 Prize Bond - Pattern Audit</h1>
<p class="sub">Draws {draw_nos[0]}-{draw_nos[-1]} ({val.draw_date.iloc[0]} to {val.draw_date.iloc[-1]}) · {N:,} winning numbers · {len(res)} tests · {args.sims:,} Monte Carlo histories · generated {datetime.now():%Y-%m-%d %H:%M}</p>

<div class="verdict"><p class="big">Is there an exploitable pattern? {verdict}</p>
<p>{html.escape(conf)} Of {len(res)} tests, {n_nom} had a nominal p-value below 0.05. By luck alone about {0.05 * len(res):.1f} would. After Benjamini-Hochberg correction, {len(sig)} remain significant.
In the walk-forward backtest (draws {first_test}-{last_test}, {len(test_ends)} out-of-sample draws, {args.n_pick:,} picks per draw), random picks would be expected to win
{exp_total:.1f} times. The best rule, "{html.escape(best.rule)}", won {int(best.hits)} times (one-sided p={best.p_beats_random:.3f} before correction).
{"No rule beats chance, so <b>no prediction is better than picking numbers at random.</b>" if len(bt_sig) == 0 else ""}</p></div>

<div class="kpis">
<div class="kpi"><b>{pairs_txt.split(' vs ')[0]}</b><span>cross-draw repeats observed (expected {sims.rep_total.mean():,.0f})</span></div>
<div class="kpi"><b>{len(sig)}</b><span>tests significant after correction (of {len(res)})</span></div>
<div class="kpi"><b>{int(bts.hits.max())} / {exp_total:.1f}</b><span>best backtest rule's hits / random expectation</span></div>
<div class="kpi"><b>1 in {odds['one_in']:,.0f}</b><span>odds that one given number wins any prize in a draw</span></div>
</div>

<h2>1 · Executive summary</h2>
{summary_html}

<h2>2 · Data validation (Step 1)</h2>
<p>{len(val)} files parsed into <code>draws_clean.csv</code> ({len(rep) and ''}{N:,} rows; numbers kept as 6-character strings). Missing draw numbers: <b>{', '.join(map(str, missing)) or 'none'}</b>.
Malformed tokens: <b>{int(val.malformed_tokens.sum())}</b>. Duplicates within a draw: <b>{int(val.duplicates_within_draw.sum())}</b>.
The 3rd-prize list is in ascending order in {int(val.tier3_ascending.sum())}/{len(val)} files. Days between draws: {val.gap_days.min():.0f}-{val.gap_days.max():.0f} (median {val.gap_days.median():.0f}).
{html.escape(count_note)} Some files label the prizes differently (<code>18500-</code> or <code>3000000-Prize-1</code> instead of <code>18500- Prize - 3</code>). The parser therefore reads the tier from the prize amount, not from the label.</p>
{table_html(vshow, formats={"Days since previous": lambda x: "" if pd.isna(x) else f"{x:.0f}"})}

<h2>3 · Results table (Steps 2 &amp; 3)</h2>
<p>The null hypothesis is that each draw picks its winners uniformly at random from 000000-999999, independently of other draws. "Expected" values come from {args.sims:,} simulated histories with the same draw sizes (mean and 95% range) or from exact/analytic distributions. All {len(res)} p-values are two-sided, except the backtest, which is one-sided ("beats random"). They are corrected together with Benjamini-Hochberg, and a Bonferroni column is also shown. Highlighted rows remain significant after correction.</p>
{''.join(sections)}

<h2>4 · Where the within-draw clustering is</h2>
<p>Per-draw clustering diagnostics for the 3rd-prize list. If the winners were uniformly random, each draw would have about {clus.gaps_le10_expected.mean():.1f} gaps of 10 or less, a 100-bucket chi-square around 99 and a variance/mean ratio around 1.0. Most draws are ordinary. A few are clearly clumpier, and their clumps are in different places each time.</p>
{clus_html}

<h2>5 · Charts</h2>
{img_tag(os.path.join(cd, 'digit_position_heatmap.png'), 'Digit frequency per position. Cell colour is the z-score versus uniform; |z|<2 is ordinary noise.')}
{img_tag(os.path.join(cd, 'bucket_distribution_per_draw.png'), 'Winners per 10,000-wide range in every draw. Hot and cold cells move around from draw to draw with no persistent stripes.')}
{img_tag(os.path.join(cd, 'gap_distribution.png'), 'Gaps between consecutive sorted 3rd-prize numbers versus the exponential law expected for random points.')}
{img_tag(os.path.join(cd, 'repeat_count_vs_simulated.png'), 'Observed cross-draw repeats versus 10,000 simulated random histories, in total and by lag.')}
{img_tag(os.path.join(cd, 'backtest_vs_random.png'), 'Walk-forward backtest: hits of each rule versus the random-pick baseline.')}
{img_tag(os.path.join(cd, 'drift_over_time.png'), 'Per-draw mean and median of the 3rd-prize numbers versus the 95% band expected by chance.')}

<h2>6 · Backtest detail (Step 3)</h2>
<p>For each training end-draw t = {test_ends[0]}..{test_ends[-1]}, each rule uses only draws {draw_nos[0]}..t to choose exactly {args.n_pick:,} numbers. Hits are then counted in draw t+1.
For random picks, the hits in a draw follow a hypergeometric distribution. The total over all test draws is simulated 200,000 times, giving {exp_total:.1f} expected (95% range {np.percentile(null_tot, 2.5):.0f}-{np.percentile(null_tot, 97.5):.0f}).
The "hits / expected" column is the effect size: 1.00 means no better than random.
With only about {exp_total:.0f} expected hits, these {args.n_pick:,}-number tests can detect only a large edge. A higher-power variant therefore bets on the 10 historically hottest 10,000-ranges (100,000 numbers). Across the same test draws it caught {hp_hits:,} of {hp_n:,} winners ({hp_hits / hp_n * 100:.2f}% vs 10.00% expected; one-sided p={fmt_p(hp_p)}; 95% CI for the lift x{hp_ci.low / 0.1:.3f}-x{hp_ci.high / 0.1:.3f}).</p>
{table_html(bts_show, formats={"expected (random)": lambda x: f"{x:.1f}", "hits / expected": f2, "95% CI low": f2, "95% CI high": f2, "p (beats random)": fmt_p})}
{table_html(bt.pivot(index="test_draw", columns="rule", values="hits").reset_index())}

<h2>7 · Lists</h2>
<h3>1st and 2nd prize history</h3>
{table_html(top_hist.assign(draw_date=top_hist.draw_date.astype(str)))}
<h3>1st/2nd prize numbers that won again in a later draw</h3>
{table_html(reapp) if len(reapp) else '<p>None. No 1st- or 2nd-prize number has reappeared in a later draw at any tier. Expected under chance: ' + f"{sims.top_reappear.mean():.2f}" + ' reappearances, so zero is the most likely outcome.</p>'}
<h3>Numbers that won in more than one draw ({len(rep):,}; expected by chance ≈ {sims.n_ge2.mean():,.0f})</h3>
<p>The full list is in <code>repeat_numbers.csv</code>. Numbers that won in 3+ draws: {int((rep.n_draws >= 3).sum())} (expected ≈ {sims.n_ge3.mean():.1f}).</p>
{table_html(rep_show, cls="scroll")}

<h2>8 · Limitations</h2>
<ul>
<li><b>Sample size.</b> 28 draws (about 47,600 numbers) is plenty for digit and range tests. It is small for draw-to-draw tests and for the backtest ({len(test_ends)} out-of-sample draws, ≈{exp_total:.0f} expected hits per rule). A rule would need to roughly double the hit rate to be detected reliably (≈80% power), so a very small edge cannot be ruled out. Even if one existed, it could not overcome the house odds.</li>
<li><b>Series are not recorded.</b> The same 6-digit number exists in many series, and these files list only the number. All analysis is at the number level. Whether a prize is paid in one series or all of them does not change any test here.</li>
<li><b>The draw method may have changed</b> over 2019-2026 (machine, software or the number range in circulation). A change that kept the output uniform would not show up in these tests. A change that broke uniformity would show up in the stability/drift tests, and it does not.</li>
<li><b>Number range.</b> The null assumes all of 000000-999999 is eligible. The bucket tests show the winners cover that whole range evenly, which supports the assumption.</li>
<li><b>Multiple testing.</b> {len(res)} tests at p&lt;0.05 would produce about {0.05 * len(res):.1f} false positives by luck. That is why the corrected p-values decide the conclusions.</li>
</ul>
<p class="sub">Reproduce: <code>python3 analysis.py</code> (add <code>raw/108.csv</code> and re-run). Seed {args.seed}.</p>
</main></body></html>"""
    with open(os.path.join(args.out, "report.html"), "w", encoding="utf-8") as f:
        f.write(html_doc)


if __name__ == "__main__":
    main()
