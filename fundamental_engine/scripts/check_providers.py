"""Owner-run provider readiness check. Never prints keys.
  python fundamental_engine/scripts/check_providers.py            # config + key presence (no network)
  RUN_LIVE_LLM_TESTS=1 python fundamental_engine/scripts/check_providers.py --live   # one tiny real call per provider with a key
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.db import sqlite_connect
from llm import config as cfgmod
from llm.budget import Budget
from llm.providers import OpenAICompatProvider
from llm.router import Router

SAMPLE = "OGDC announced a final cash dividend. The Board meeting will be held on 27 November 2026."

if __name__ == "__main__":
    for s in cfgmod.status():
        print(json.dumps(s))
    if "--live" in sys.argv and os.environ.get("RUN_LIVE_LLM_TESTS") == "1":
        root = Path(__file__).resolve().parent.parent
        for p in cfgmod.load_config()["providers"]:
            if not os.environ.get(p["api_key_env"]):
                print(p["name"], "SKIPPED (no key in environment)")
                continue
            db = sqlite_connect(); db.script((root / "migrations" / "0010_baseline_snapshot.sql").read_text())
            db.execute("INSERT INTO sources(source_id,name,source_type,access_status,created_at_utc,updated_at_utc) VALUES('s','s','exchange','verified_permitted','t','t')")
            db.execute("INSERT INTO companies(company_id,legal_name,listing_status,created_at_utc,updated_at_utc) VALUES('cmp-ogdc','OGDC','listed','t','t')")
            db.execute("INSERT INTO company_identifiers(company_id,id_type,value,verified_at_utc) VALUES('cmp-ogdc','psx_ticker','OGDC','t')")
            item = db.execute("INSERT INTO source_items(source_id,external_id,collected_at_utc,content_sha256) VALUES('s','e','t',?)", ("a" * 64,)).lastrowid
            prov = OpenAICompatProvider(p["name"], p["base_url"], p["model"], p["api_key_env"], p.get("max_output_tokens", 800),
                                        p.get("timeout_s", 60), p.get("json_mode", False), p.get("extra_headers"), None, p.get("extra_body"))
            print(p["name"], Router(db, [prov], {p["name"]: Budget(max_calls_per_day=2)}).extract(item, SAMPLE))
