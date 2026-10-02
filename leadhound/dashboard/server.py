"""Local dashboard: stdlib HTTP server on 127.0.0.1 with a JSON API.

Security: binds to loopback only, rejects foreign Host headers (DNS rebinding), and requires a
per-run token header on every API call, so other websites open in your browser cannot read or
change your leads.
"""
from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..draft import make_draft
from ..store import Store

INDEX = Path(__file__).with_name("index.html")


def make_handler(store: Store, cfg, token: str, port: int):
    lock = threading.Lock()
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "leadhound"

        def log_message(self, *args):
            pass

        def _send(self, code: int, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:")
            self.end_headers()
            self.wfile.write(data)

        def _guard(self, api: bool) -> bool:
            if self.headers.get("Host", "") not in allowed_hosts:
                self._send(403, {"error": "bad host"})
                return False
            if api and not secrets.compare_digest(self.headers.get("X-Leadhound-Token", ""), token):
                self._send(403, {"error": "missing or bad token"})
                return False
            return True

        def _lead_id(self, path: str) -> int | None:
            parts = path.strip("/").split("/")
            if len(parts) >= 3 and parts[0] == "api" and parts[1] == "leads" and parts[2].isdigit():
                return int(parts[2])
            return None

        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                if not self._guard(api=False):
                    return
                html = INDEX.read_text(encoding="utf-8").replace("__LEADHOUND_TOKEN__", token)
                return self._send(200, html.encode(), "text/html; charset=utf-8")
            if not u.path.startswith("/api/") or not self._guard(api=True):
                if not u.path.startswith("/api/"):
                    self._send(404, {"error": "not found"})
                return
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            with lock:
                if u.path == "/api/leads":
                    leads = store.query(status=q.get("status") or None, kind=q.get("kind") or None,
                                        source=q.get("source") or None, min_score=int(q.get("min", 0) or 0),
                                        search=q.get("q", ""), limit=min(int(q.get("limit", 200)), 1000))
                    return self._send(200, [asdict(l) for l in leads])
                if u.path == "/api/stats":
                    return self._send(200, store.stats())
                lid = self._lead_id(u.path)
                lead = store.get(lid) if lid else None
                if lead:
                    return self._send(200, asdict(lead))
            self._send(404, {"error": "not found"})

        def do_POST(self):
            u = urlparse(self.path)
            if not self._guard(api=True):
                return
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(min(n, 100_000)) or b"{}")
            except (ValueError, json.JSONDecodeError):
                return self._send(400, {"error": "bad json"})
            lid = self._lead_id(u.path)
            if lid is None:
                return self._send(404, {"error": "not found"})
            with lock:
                lead = store.get(lid)
                if not lead:
                    return self._send(404, {"error": "not found"})
                if u.path.endswith("/draft"):
                    text, engine = make_draft(lead, cfg, use_llm=bool(body.get("llm")))
                    store.update(lid, draft=text)
                    return self._send(200, {"draft": text, "engine": engine})
                fields = {k: body[k] for k in ("status", "notes", "draft") if k in body}
                try:
                    store.update(lid, **fields)
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, asdict(store.get(lid)))

    return Handler


def make_server(db_path: str, cfg, port: int = 8787):
    store = Store(db_path)
    token = secrets.token_urlsafe(24)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
    # build the handler after binding so the Host allow-list uses the real port (port 0 = any free port)
    httpd.RequestHandlerClass = make_handler(store, cfg, token, httpd.server_address[1])
    return httpd, token


def serve(db_path: str, cfg, port: int = 8787, open_browser: bool = True) -> None:
    httpd, _ = make_server(db_path, cfg, port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"leadhound dashboard: {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
