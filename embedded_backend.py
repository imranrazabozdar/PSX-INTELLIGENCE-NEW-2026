"""embedded_backend.py — run backend/app.py inside the Streamlit process
(PSX_EMBED_BACKEND=1, the Streamlit Cloud deploy) and make sure a deploy
actually swaps in the NEW backend code.

Streamlit Cloud reloads the script on a deploy but keeps the same Python
process, so a uvicorn server started by the previous code keeps answering on
:8000 with the OLD routes (e.g. a new endpoint returns 404). This module
records which version is serving (process-wide, survives script reruns), and
when the requested version differs it stops the running server -- including
one started before this module existed, found via gc -- reloads the backend
modules and starts a fresh server.
"""
import gc
import importlib
import os
import socket
import sys
import threading
import time
import types

import requests

PORT = 8000
_REG_NAME = "_psx_embedded_backend_registry"


def _registry():
    reg = sys.modules.get(_REG_NAME)
    if reg is None:
        reg = types.ModuleType(_REG_NAME)
        reg.version, reg.server, reg.lock = None, None, threading.Lock()
        sys.modules[_REG_NAME] = reg
    return reg


def _healthy(timeout=2):
    try:
        return requests.get(f"http://127.0.0.1:{PORT}/health", timeout=timeout).ok
    except Exception:
        return False


def _port_free():
    s = socket.socket()
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _running_servers():
    try:
        import uvicorn
    except ImportError:
        return []
    # ONLY the backend's own server: Streamlit itself may run on uvicorn too (on another port) and must
    # never be touched -- match on the configured port, not just the type.
    out = []
    for o in gc.get_objects():
        if isinstance(o, uvicorn.Server) and not o.should_exit:
            cfg = getattr(o, "config", None)
            if cfg is not None and getattr(cfg, "port", None) == PORT and \
                    getattr(cfg, "host", None) in ("127.0.0.1", "localhost"):
                out.append(o)
    return out


def _stop(reg, wait=15):
    servers = _running_servers()
    if reg.server is not None and reg.server not in servers:
        servers.append(reg.server)
    for s in servers:
        s.should_exit = True                 # graceful: finishes in-flight requests
    t0 = time.time()
    while time.time() - t0 < wait and not _port_free():
        if time.time() - t0 > 5:
            for s in servers:
                s.force_exit = True          # don't wait on long-lived connections
        time.sleep(0.2)
    reg.server = None
    return len(servers)


def _load_app(backend_dir):
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    for m in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        try:
            importlib.reload(sys.modules[m])
        except Exception:
            pass
    import app as backend_app
    return backend_app.app


def ensure(version, backend_dir, load_app=None, log=print):
    """Serve `version` of the backend on :8000. Returns 'reused', 'started' or 'restarted'."""
    reg = _registry()
    with reg.lock:
        if reg.version == version and _healthy():
            return "reused"
        action = "started"
        if _healthy() or _running_servers():
            n = _stop(reg)
            action = "restarted"
            log(f"[embed] backend version {reg.version or 'unknown (pre-versioned)'} -> {version}: "
                f"stopped {n} running server(s)")
        os.environ.setdefault("PSX_DB", os.path.join(backend_dir, "psx_v2.db"))
        import uvicorn
        app = (load_app or _load_app)(backend_dir)
        server = uvicorn.Server(uvicorn.Config(app=app, host="127.0.0.1", port=PORT, log_level="warning"))
        orig_bind = socket.socket.bind

        def _reuse_bind(self, addr):
            self.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            return orig_bind(self, addr)
        socket.socket.bind = _reuse_bind
        try:
            threading.Thread(target=server.run, daemon=True).start()
        finally:
            socket.socket.bind = orig_bind
        reg.server, reg.version = server, version
        # read by streamlit_app._backend_up() so a backend still starting is waited for, not duplicated
        os.environ["PSX_EMBED_STARTED_AT"] = str(time.time())
        for _ in range(30):
            if _healthy(timeout=1):
                break
            time.sleep(1)
        log(f"[embed] backend {version} {action} on :{PORT}")
        return action
