"""Tiny read-only HTTP server that answers the dashboard's GET calls from a
fixtures JSON file (path -> payload). Unknown paths get a status=error body,
the same shape streamlit_app._get returns on a failed request."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


def serve(fixtures: dict, port: int = 0):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            body = fixtures.get(u.path)
            if u.path == "/patterns/volatility-engine/detail":
                body = {"status": "not_found", "reason": "no detail in fixtures"}
            if body is None:
                body = {"status": "error", "reason": f"fixture missing for {u.path}"}
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            data = json.dumps({"status": "error", "reason": "read-only fixture backend"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    srv = serve(json.load(open(sys.argv[1])), int(sys.argv[2]) if len(sys.argv) > 2 else 8765)
    print(f"serving on {srv.server_address}", flush=True)
    threading.Event().wait()
