"""Deterministic relevance prefilter run BEFORE any model call (saves free-tier quota, raises signal-to-noise).

Inputs: a headline/text. Entities come from the database (psx tickers, company names/aliases, watchlist); keyword groups
and weights from extract/relevance_rules.json (versioned). Every decision carries its reasons, so it can be audited."""
import json
import re
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent / "relevance_rules.json"
_SUFFIX = re.compile(r"\b(limited|ltd|company|co|corporation|corp|pvt|private|plc|inc)\b\.?", re.I)


def load_rules(path=RULES_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\- ]+", " ", (text or "").lower())).strip()


def company_phrases(legal_name):
    """'The Hub Power Company Limited' -> 'hub power'; single-word / very short results are dropped (too ambiguous)."""
    n = norm(_SUFFIX.sub(" ", legal_name or ""))
    n = re.sub(r"^the ", "", n).strip()
    return n if len(n.split()) >= 2 and len(n) >= 8 else None


class Relevance:
    def __init__(self, tickers=(), names=(), watchlist=(), rules=None):
        self.rules = rules or load_rules()
        self.version = self.rules["version"]
        self.threshold = self.rules["threshold"]
        self.tickers = {t.upper() for t in tickers}
        self.watch = {t.upper() for t in watchlist}
        self.names = {n for n in (names or ()) if n}
        self.ambiguous = {t.upper() for t in self.rules.get("ambiguous_tickers", [])}
        self.source_bonus = self.rules.get("source_bonus", {})
        self._kw = {g: [(t, w, re.compile(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])")) for t, w in terms.items()]
                    for g, terms in self.rules["groups"].items()}
        self._tk = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{1,15})(?![A-Za-z0-9])")

    @classmethod
    def from_db(cls, db, rules=None):
        tickers = [r["value"] for r in db.execute("SELECT value FROM company_identifiers WHERE id_type='psx_ticker' AND valid_to IS NULL").rows]
        watch = [r["value"] for r in db.execute("SELECT value FROM user_watchlist WHERE item_type='ticker' AND enabled=1").rows]
        names = set()
        for r in db.execute("SELECT legal_name AS n FROM companies UNION SELECT alias AS n FROM company_aliases "
                            "WHERE alias_type IN ('legal_name','short_name')").rows:
            p = company_phrases(r["n"])
            if p:
                names.add(p)
        return cls(tickers, names, watch, rules)

    def score(self, text, source_id=None):
        pts = self.rules["entity_points"]
        reasons, total, ambiguous_hit = [], 0, None
        for t in sorted(set(self._tk.findall(text or ""))):
            if t in self.tickers:
                if t in self.ambiguous:
                    ambiguous_hit = t        # needs corroboration (company name or any keyword group) before it counts
                    continue
                total += pts["ticker"]; reasons.append(f"ticker:{t}")
                if t in self.watch:
                    total += pts["watchlist_bonus"]; reasons.append(f"watchlist:{t}")
                break                                    # one entity hit is enough; do not stack tickers
        low = norm(text)
        corroborated = False
        for n in sorted(self.names, key=len, reverse=True):
            if re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", low):
                total += pts["company_name"]; reasons.append(f"company:{n}"); corroborated = True
                break
        for g, rules in self._kw.items():
            best = max(((w, t) for t, w, rx in rules if rx.search(low)), default=None)
            if best:
                total += best[0]; reasons.append(f"{g}:{best[1]}({best[0]})")
                corroborated = corroborated or (g not in ("geo", "foreign_noise") and best[0] > 0)
        if ambiguous_hit and corroborated:
            total += pts["ticker"]; reasons.append(f"ticker(ambiguous, corroborated):{ambiguous_hit}")
        elif ambiguous_hit:
            reasons.append(f"ambiguous ticker {ambiguous_hit} ignored: no corroboration")
        sb = self.source_bonus.get(source_id or "", 0)
        if sb:
            total += sb; reasons.append(f"source:{source_id}(+{sb})")
        # context-only signals (geo, small source bonuses) never make an item relevant on their own
        if not (corroborated or sb >= 3 or any(r.startswith(("ticker:", "ticker(")) for r in reasons)):
            reasons.append("no substantive signal: context-only")
            total = 0
        return {"score": total, "pass": total >= self.threshold, "reasons": reasons, "version": self.version}
