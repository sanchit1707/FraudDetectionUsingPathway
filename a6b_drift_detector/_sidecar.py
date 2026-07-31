"""
Lightweight, dependency-free sidecar HTTP server.

Pathway's `pw.io.http.rest_connector` webserver doesn't emit CORS headers and
only exposes the single POST route it was built for, so a browser-based
dashboard can't call it directly (preflight OPTIONS fails) and has no way to
read live agent state (accuracy, counters, etc.) without submitting data.

This sidecar runs in a background thread inside the same container and:
  - answers GET /stats with the agent's *real* in-memory state (no mock data)
  - proxies POST bodies through to the real Pathway route and relays the
    real response back to the browser, with CORS headers attached.

Uses only the standard library so it adds zero new dependencies.
"""
import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def start_sidecar(port: int, upstream_url: str, get_stats):
    class Handler(BaseHTTPRequestHandler):
        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            if self.path.startswith("/stats") or self.path.startswith("/health"):
                try:
                    body = json.dumps(get_stats()).encode()
                    self.send_response(200)
                except Exception as e:
                    body = json.dumps({"error": str(e)}).encode()
                    self.send_response(500)
                self._cors()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self._cors()
                self.end_headers()

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b"{}"
                req = urllib.request.Request(
                    upstream_url,
                    data=raw,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    status = resp.status
                    resp_body = resp.read()
            except urllib.error.HTTPError as e:
                status = e.code
                resp_body = e.read() or json.dumps({"error": str(e)}).encode()
            except Exception as e:
                status = 502
                resp_body = json.dumps({"error": str(e)}).encode()

            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(resp_body)

        def log_message(self, *args):
            pass  # silence default stderr access logging

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True, name=f"sidecar-{port}")
    t.start()
    print(f"[sidecar] CORS/stats bridge listening on 0.0.0.0:{port} -> proxying POST to {upstream_url}")
    return server
