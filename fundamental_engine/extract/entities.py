"""PSX entity resolution (entities@v1). Deterministic; matches text against the company master and NEVER invents a ticker.

direct   : the text itself names the company (ticker, legal/short name, brand/former/abbreviation alias, or a subsidiary that is
           itself in the master). Each match carries how it matched and a confidence.
indirect : a rule associates the text with SECTORS (and via company_classifications, companies). Kept strictly separate from direct,
           low confidence, rationale attached, direction unknown. Parent companies of a named subsidiary are also indirect.
unresolved: things that look like entities but are not assigned: unknown parenthesised tickers, names shared by several companies,
           ambiguous tickers without corroboration. Nothing in `unresolved` is ever promoted to a ticker.
"""
import json
import re
from pathlib import Path

VERSION = "entities@v1"
RULES_PATH = Path(__file__).resolve().parent / "exposure_rules.json"
_SUFFIX = re.compile(r"\b(limited|ltd|company|co|corporation|corp|pvt|private|plc|inc)\b\.?", re.I)
_TICKER_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{1,15})(?![A-Za-z0-9])")
_PAREN_RE = re.compile(r"\(([A-Z][A-Z0-9]{1,9})\)")
_CORROBORATION = re.compile(r"\b(shares?|stock|dividend|results?|profit|earnings|board|agm|bonus|ltd|limited|company|psx|kse|listed)\b", re.I)
ALIAS_CONF = {("legal_name", "verified"): 0.9, ("legal_name", "derived"): 0.8, ("legal_name", "candidate"): 0.75,
              ("short_name", "verified"): 0.8, ("short_name", "derived"): 0.7, ("short_name", "candidate"): 0.55}
OTHER_ALIAS_CONF = {"verified": 0.85, "derived": 0.65, "candidate": 0.5}
STRONG_ALIAS_TYPES = ("brand", "former_name", "abbreviation")


def norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\- ]+", " ", (text or "").lower())).strip()


def phrase_variants(name):
    """Full normalised name plus the suffix-stripped form ('The Hub Power Company Limited' -> 'hub power company limited', 'hub power')."""
    out = set()
    full = norm(name)
    core = norm(_SUFFIX.sub(" ", name or ""))
    core = re.sub(r"^the ", "", core).strip()
    full = re.sub(r"^the ", "", full).strip()
    for p in (full, core):
        if len(p.split()) >= 2 and len(p) >= 8:
            out.add(p)
    return out


def load_rules(path=RULES_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class Resolver:
    def __init__(self, companies, aliases=(), relationships=(), sector_ids=(), rules=None):
        """companies: {company_id: {"ticker","legal_name","sector_ids":[...]}}; aliases: [(company_id, alias, alias_type, confidence)];
        relationships: [(parent_id, child_company_id|None, child_name, type)]."""
        self.rules = rules or load_rules()
        self.version, self.rules_version = VERSION, self.rules["version"]
        self.companies = companies
        self.tickers = {c["ticker"]: cid for cid, c in companies.items() if c.get("ticker")}
        self.ambiguous = set(self.rules.get("ambiguous_tickers", []))
        self.warnings = []
        self.phrases = {}                                    # phrase -> {company_id: (confidence, kind)}
        for cid, c in companies.items():
            for p in phrase_variants(c.get("legal_name")):
                self._add(p, cid, ALIAS_CONF.get(("legal_name", "verified"), 0.9), "legal_name")
        for cid, alias, atype, conf in aliases:
            if atype == "ticker":
                continue
            if atype in ("legal_name", "short_name"):
                score = ALIAS_CONF.get((atype, conf), 0.5)
                for p in phrase_variants(alias):
                    self._add(p, cid, score, atype)
            elif atype in STRONG_ALIAS_TYPES:
                a = norm(alias)
                if len(a) >= 4 or len(a.split()) >= 2:
                    self._add(a, cid, OTHER_ALIAS_CONF.get(conf, 0.5), atype)
        self.children = {}                                    # normalised child name -> [(parent, child_company_id, type)]
        for parent, child_id, child_name, rtype in relationships:
            p = norm(child_name)
            if len(p) >= 4:
                self.children.setdefault(p, []).append((parent, child_id, rtype))
        known = set(sector_ids)
        self.rules_active = []
        for r in self.rules["rules"]:
            ok = [s for s in r["sector_ids"] if not known or s in known]
            for s in r["sector_ids"]:
                if known and s not in known:
                    self.warnings.append(f"rule {r['id']}: sector {s} not in master (skipped)")
            if ok:
                self.rules_active.append({**r, "sector_ids": ok,
                                          "rx": [(t, re.compile(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])")) for t in r["terms"]]})

    def _add(self, phrase, cid, conf, kind):
        cur = self.phrases.setdefault(phrase, {})
        if cid not in cur or cur[cid][0] < conf:
            cur[cid] = (conf, kind)

    @classmethod
    def from_db(cls, db, rules=None):
        comps = {}
        for r in db.execute("SELECT c.company_id, c.legal_name, ci.value AS ticker FROM companies c LEFT JOIN company_identifiers ci "
                            "ON ci.company_id=c.company_id AND ci.id_type='psx_ticker' AND ci.valid_to IS NULL").rows:
            comps[r["company_id"]] = {"ticker": r["ticker"], "legal_name": r["legal_name"], "sector_ids": []}
        for r in db.execute("SELECT company_id, sector_id FROM company_classifications WHERE valid_to IS NULL").rows:
            if r["company_id"] in comps:
                comps[r["company_id"]]["sector_ids"].append(r["sector_id"])
        aliases = [(r["company_id"], r["alias"], r["alias_type"], r["confidence"])
                   for r in db.execute("SELECT company_id, alias, alias_type, confidence FROM company_aliases").rows]
        rels = [(r["parent_company_id"], r["child_company_id"], r["child_name"], r["relationship_type"])
                for r in db.execute("SELECT parent_company_id, child_company_id, child_name, relationship_type FROM company_relationships "
                                    "WHERE relationship_id NOT IN (SELECT supersedes_relationship_id FROM company_relationships "
                                    "WHERE supersedes_relationship_id IS NOT NULL)").rows]
        sectors = [r["sector_id"] for r in db.execute("SELECT sector_id FROM sectors").rows]
        return cls(comps, aliases, rels, sectors, rules)

    # ------------------------------------------------------------------ resolution
    def resolve(self, text):
        text = text or ""
        low = norm(text)
        direct, indirect, unresolved = {}, [], []

        def put_direct(cid, how, conf, span):
            if cid not in direct or direct[cid]["confidence"] < conf:
                direct[cid] = {"company_id": cid, "ticker": self.companies[cid]["ticker"], "level": "direct", "matched_by": how,
                               "matched_text": span, "confidence": round(conf, 2)}

        corroborated = bool(_CORROBORATION.search(text))
        for t in sorted(set(_TICKER_RE.findall(text))):
            cid = self.tickers.get(t)
            if cid is None:
                continue
            if t in self.ambiguous and not corroborated:
                unresolved.append({"text": t, "reason": "ambiguous_ticker_without_corroboration", "candidates": [t]})
                continue
            put_direct(cid, "ticker", 0.7 if t in self.ambiguous else 0.95, t)
        covered = []
        for phrase in sorted(self.phrases, key=len, reverse=True):          # longest phrase first; a span counts once
            for m in re.finditer(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", low):
                if any(m.start() < e and m.end() > s for s, e in covered):
                    continue
                covered.append((m.start(), m.end()))
                cands = self.phrases[phrase]
                if len(cands) > 1:
                    unresolved.append({"text": phrase, "reason": "ambiguous_name",
                                       "candidates": sorted(self.companies[c]["ticker"] or c for c in cands)})
                else:
                    (cid, (conf, kind)), = cands.items()
                    put_direct(cid, kind, conf, phrase)
        for child, links in self.children.items():
            if re.search(rf"(?<![a-z0-9]){re.escape(child)}(?![a-z0-9])", low):
                for parent, child_id, rtype in links:
                    if child_id and child_id in self.companies:
                        put_direct(child_id, f"subsidiary_name({rtype})", 0.8, child)
                    else:
                        unresolved.append({"text": child, "reason": "child_not_in_master", "candidates": []})
                    if parent in self.companies:
                        indirect.append({"level": "indirect", "basis": f"{rtype}_of_named_entity", "company_id": parent,
                                         "ticker": self.companies[parent]["ticker"], "via": child, "confidence": 0.6,
                                         "rationale": f"text names {child}, a {rtype} of this company"})
        for m in _PAREN_RE.finditer(text):                                    # "(XYZ)" ticker-like but unknown: report, never assign
            if m.group(1) not in self.tickers:
                unresolved.append({"text": m.group(1), "reason": "ticker_like_not_in_master", "candidates": []})
        named = set(direct)
        for r in self.rules_active:
            hit = next((t for t, rx in r["rx"] if rx.search(low)), None)
            if not hit:
                continue
            cos = sorted({c["ticker"] for cid, c in self.companies.items()
                          if c.get("ticker") and set(c["sector_ids"]) & set(r["sector_ids"]) and cid not in named})
            indirect.append({"level": "indirect", "basis": "sector_rule", "rule_id": r["id"], "matched_term": hit,
                             "sector_ids": r["sector_ids"], "companies": cos, "confidence": r["confidence"],
                             "direction": "unknown", "rationale": r["rationale"]})
        return {"resolver_version": self.version, "rules_version": self.rules_version,
                "direct": sorted(direct.values(), key=lambda d: (-d["confidence"], d["ticker"] or "")),
                "indirect": indirect, "unresolved": unresolved}
