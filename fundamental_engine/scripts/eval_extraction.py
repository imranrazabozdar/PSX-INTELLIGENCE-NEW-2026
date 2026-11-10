"""Reproducible extraction-quality evaluation. Deterministic, NO model calls, NO database writes.
  python fundamental_engine/scripts/eval_extraction.py                 # controlled synthetic sample (offline)
  python fundamental_engine/scripts/eval_extraction.py --production    # read-only metrics over real candidates/headlines (needs LIBSQL_URL)
  add --json to print JSON only"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from extract import evaluate

if __name__ == "__main__":
    a = sys.argv[1:]
    out = {"controlled": evaluate.controlled(json.loads((ROOT / "tests" / "fixtures" / "eval_sample.json").read_text(encoding="utf-8")))}
    if "--production" in a:
        from core.db import TursoClient
        out["production"] = evaluate.production(TursoClient())
    print(json.dumps(out, indent=None if "--json" in a else 1, sort_keys=True, ensure_ascii=False))
