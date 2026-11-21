"""embedded_backend.ensure(): a deploy must swap a still-running OLD backend
server for the new code (the Breakouts 404: /patterns/phase-d-scan missing)."""
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import embedded_backend as E  # noqa: E402


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _app(with_phase_d):
    from fastapi import FastAPI
    a = FastAPI()

    @a.get("/health")
    def health():
        return {"ok": True}
    if with_phase_d:
        @a.get("/patterns/phase-d-scan")
        def phase_d():
            return {"status": "ok", "hits": []}
    return a


@pytest.fixture
def port(monkeypatch):
    p = _free_port()
    monkeypatch.setattr(E, "PORT", p)
    sys.modules.pop(E._REG_NAME, None)
    yield p
    reg = sys.modules.get(E._REG_NAME)
    if reg:
        E._stop(reg)
    sys.modules.pop(E._REG_NAME, None)


def _status(port, path):
    try:
        return requests.get(f"http://127.0.0.1:{port}{path}", timeout=2).status_code
    except Exception:
        return None


def test_old_unregistered_server_is_replaced_by_new_code(port):
    import uvicorn
    # an OLD server started outside the registry (like the pre-fix deploy), without the new route
    old = uvicorn.Server(uvicorn.Config(app=_app(False), host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=old.run, daemon=True).start()
    for _ in range(50):
        if _status(port, "/health") == 200:
            break
        time.sleep(0.1)
    assert _status(port, "/patterns/phase-d-scan") == 404
    assert E.ensure("v8-new", str(ROOT / "backend"), load_app=lambda d: _app(True), log=lambda m: None) == "restarted"
    assert old.should_exit
    assert _status(port, "/patterns/phase-d-scan") == 200


def test_same_version_reused_new_version_restarts(port):
    assert E.ensure("a", str(ROOT / "backend"), load_app=lambda d: _app(False), log=lambda m: None) == "started"
    assert E.ensure("a", str(ROOT / "backend"), load_app=lambda d: _app(True), log=lambda m: None) == "reused"
    assert _status(port, "/patterns/phase-d-scan") == 404
    assert E.ensure("b", str(ROOT / "backend"), load_app=lambda d: _app(True), log=lambda m: None) == "restarted"
    assert _status(port, "/patterns/phase-d-scan") == 200


def test_streamlit_cache_key_includes_version():
    src = (ROOT / "streamlit_app.py").read_text()
    assert "def _ensure_embedded_backend(version=None):" in src          # no leading underscore
    assert "_ensure_embedded_backend(_version=" not in src


def test_never_stops_a_server_on_another_port(port):
    """Streamlit 1.62 serves the app itself through uvicorn: that server must never be stopped."""
    import uvicorn
    other_port = _free_port()
    other = uvicorn.Server(uvicorn.Config(app=_app(False), host="127.0.0.1", port=other_port, log_level="warning"))
    threading.Thread(target=other.run, daemon=True).start()
    for _ in range(50):
        if _status(other_port, "/health") == 200:
            break
        time.sleep(0.1)
    E.ensure("v1", str(ROOT / "backend"), load_app=lambda d: _app(True), log=lambda m: None)
    E.ensure("v2", str(ROOT / "backend"), load_app=lambda d: _app(True), log=lambda m: None)
    assert not other.should_exit and _status(other_port, "/health") == 200
    other.should_exit = True
