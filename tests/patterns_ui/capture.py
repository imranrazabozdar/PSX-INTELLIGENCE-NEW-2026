"""Run streamlit_app.py against the fixture backend with Streamlit's AppTest
and dump every rendered dataframe (by widget key) and every text element.

  python tests/patterns_ui/capture.py FIXTURES.json OUT.json [key=value ...]

Extra key=value pairs are set in session_state before the run (e.g. a
"Show Historical Signals" checkbox key=true)."""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fake_backend import serve  # noqa: E402

APP = str(HERE.parents[1] / "streamlit_app.py")


def _val(v):
    if v in ("true", "false"):
        return v == "true"
    return v


def run(fixtures, state=None, script=APP):
    srv = serve(fixtures)
    os.environ["PSX_BACKEND"] = f"http://127.0.0.1:{srv.server_address[1]}"
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(script, default_timeout=300)
    for k, v in (state or {}).items():
        at.session_state[k] = v
    at.run()
    at._fixture_server = srv   # kept alive so clicks can re-run the script
    return at


def dump(at):
    import pandas as pd
    out = {"tables": {}, "text": [], "exceptions": [e.value[:300] for e in at.exception]}
    for d in at.dataframe:
        key = d.proto.id.split("-", 2)[-1] if d.proto.id else None
        v = d.value
        if hasattr(v, "data"):
            v = v.data
        if isinstance(v, pd.DataFrame):
            out["tables"].setdefault(key or f"_anon{len(out['tables'])}", []).append(
                {"columns": [str(c) for c in v.columns], "rows": json.loads(v.to_json(orient="values", date_format="iso"))})
    for kind in ("markdown", "caption", "warning", "error", "info", "success", "expander"):
        for e in getattr(at, kind):
            txt = getattr(e, "label", None) if kind == "expander" else getattr(e, "value", None)
            out["text"].append([kind, str(txt)])
    return out


if __name__ == "__main__":
    fx = json.load(open(sys.argv[1]))
    state = dict(a.split("=", 1) for a in sys.argv[3:])
    at = run(fx, {k: _val(v) for k, v in state.items()})
    res = dump(at)
    Path(sys.argv[2]).write_text(json.dumps(res, indent=1, default=str))
    print(f"{len(res['tables'])} tables, {len(res['text'])} text elements, exceptions={res['exceptions']}")
