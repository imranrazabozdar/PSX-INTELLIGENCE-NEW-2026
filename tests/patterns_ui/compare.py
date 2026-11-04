"""Compare the redesigned Patterns tab against the pre-redesign baseline.

  python tests/patterns_ui/compare.py BASELINE.json NEW_VIEWS.json [FIXTURES.json]

Per module: same symbols in the same order, same values in every shared
column, and every row reachable (old 50-row caps -> full count). Text: every
baseline warning / caption / info / rule text is still rendered somewhere."""
import json
import sys

MAP = {"_anon2": "obv_mfi_scan_table", "_anon24": "vw_table", "_anon25": "vol_alerts",
       "_anon19": "vol_stale", "_anon20": "vol_unav", "_anon27": "w2_stale", "_anon28": "w2_unav"}
FIRE_STATUS = {"🔴 FIRE": "FIRE", "🟡 PRE-FIRE": "PRE-FIRE"}
WY_SIGNAL = {"🔴 EXTREME": "EXTREME", "🟡 READY": "READY", "🟢 WATCH": "WATCH"}


def tables(new):
    out = {}
    for view, d in new.items():
        for k, v in d["tables"].items():
            out.setdefault(k if not k.startswith("_anon") else f"{view}:{k}", v[0])
    return out


def frame(t):
    return [dict(zip(t["columns"], r)) for r in t["rows"]]


def main(bpath, npath):
    base = json.load(open(bpath))
    new = json.load(open(npath))
    nt = tables(new)
    problems, report = [], []
    for k, v in base["tables"].items():
        old = frame(v[0])
        if k == "fire_scan_table":
            for r in old:
                r["status"] = FIRE_STATUS[r["status"]]
            got = frame(nt["fire_scan_table_FIRE"]) + frame(nt["fire_scan_table_PRE-FIRE"])
            old = [r for r in old if r["status"] == "FIRE"] + [r for r in old if r["status"] == "PRE-FIRE"]
            nk = "fire_scan_table_FIRE+PRE-FIRE"
        else:
            nk = MAP.get(k, k)
            if nk not in nt:
                # unkeyed tables (stale / unavailable lists): find one with identical content
                same = [kk for kk, t in nt.items() if t["columns"] == v[0]["columns"] and t["rows"] == v[0]["rows"]]
                if not same:
                    problems.append(f"{k}: no table '{nk}' in redesigned tab")
                    continue
                nk = same[0]
            got = frame(nt[nk])
        if k == "wyckoff_scan_table":
            for r in old:
                r["signal"] = WY_SIGNAL.get(r["signal"], r["signal"])
        cols = [c for c in v[0]["columns"] if c in nt.get(nk, {"columns": list(got[0]) if got else []})["columns"]] \
            if nk in nt else [c for c in v[0]["columns"] if got and c in got[0]]
        missing_cols = [c for c in v[0]["columns"] if c not in cols]
        n_old = len(old)
        head = [{c: r.get(c) for c in cols} for r in got[:n_old]]
        want = [{c: r.get(c) for c in cols} for r in old]
        ok = head == want
        report.append((k, nk, n_old, len(got), ok, missing_cols))
        if not ok:
            for i, (a, b) in enumerate(zip(want, head)):
                if a != b:
                    problems.append(f"{k}: first difference at row {i}: old={a} new={b}")
                    break
            else:
                problems.append(f"{k}: row count old={n_old} new={len(got)}")
        if missing_cols:
            problems.append(f"{k}: columns not in new table: {missing_cols}")
    # text
    new_text = " \n".join(t for d in new.values() for _, t in d["text"])
    lost = []
    for kind, t in base["text"]:
        if kind in ("markdown",) and (t.startswith("<style") or t.startswith("<div")):
            continue
        probe = t.replace("📖 ", "") if kind == "expander" else t
        if probe not in new_text:
            lost.append((kind, t[:140]))
    return report, problems, lost


if __name__ == "__main__":
    report, problems, lost = main(sys.argv[1], sys.argv[2])
    print(f"{'baseline table':34} {'new table':34} {'old rows':>8} {'new rows':>8}  same order+values")
    for k, nk, a, b, ok, mc in report:
        print(f"{k:34} {nk:34} {a:8} {b:8}  {'yes' if ok else 'NO'}{'  (dropped cols ' + str(mc) + ')' if mc else ''}")
    print("\nPROBLEMS:", *problems, sep="\n  ") if problems else print("\nno table problems")
    print(f"\nbaseline texts not found in redesigned tab: {len(lost)}")
    for x in lost:
        print("  ", x)
