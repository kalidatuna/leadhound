"""Local dashboard: stdlib HTTP server on 127.0.0.1 with a small JSON API.

Security: binds to loopback only, rejects foreign Host headers (DNS rebinding), requires a per-run
token header on every API call, and sends a strict Content-Security-Policy. Other websites open in
your browser cannot read or change your leads.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import threading
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import __version__, config
from ..draft import make_draft
from ..jobs import JobBusy, JobManager
from ..models import KINDS, STATUSES
from ..sources import SOURCES, osm
from ..store import Store

STATIC = Path(__file__).parent
STATIC_FILES = {"app.css": "text/css", "app.js": "text/javascript", "util.js": "text/javascript",
                "leads.js": "text/javascript", "find.js": "text/javascript", "settings.js": "text/javascript"}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


class HttpError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code, self.msg = code, msg


def make_handler(store: Store, config_path: str, token: str, port: int, jobs: JobManager):
    lock = threading.Lock()
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    def cfg():
        return config.load(config_path)

    # ---- API routes: (method, regex) -> function(match, query, body) -> (status, payload) ----
    def meta(m, q, b):
        c = cfg()
        return 200, {"version": __version__, "first_run": not os.path.exists(config_path),
                     "categories": sorted(osm.CATEGORY_TAGS), "sources": list(SOURCES), "statuses": list(STATUSES),
                     "kinds": list(KINDS), "llm_ready": c.llm_provider != "none",
                     "config_path": config_path, "db_path": store_path(store)}

    def leads_list(m, q, b):
        leads = store.query(status=q.get("status") or None, kind=q.get("kind") or None,
                            source=q.get("source") or None, min_score=int(q.get("min", 0) or 0),
                            search=q.get("q", ""), limit=min(int(q.get("limit", 300)), 1000),
                            sort=q.get("sort", "score"))
        return 200, [asdict(l) for l in leads]

    def lead_get(m, q, b):
        lead = store.get(int(m.group(1)))
        if not lead:
            raise HttpError(404, "lead not found")
        return 200, asdict(lead)

    def lead_update(m, q, b):
        lid = int(m.group(1))
        if not store.get(lid):
            raise HttpError(404, "lead not found")
        fields = {k: b[k] for k in ("status", "notes", "draft") if k in b}
        for k in ("notes", "draft"):
            if k in fields and (not isinstance(fields[k], str) or len(fields[k]) > 20000):
                raise HttpError(400, f"{k} must be text under 20000 characters")
        store.update(lid, **fields)
        return 200, asdict(store.get(lid))

    def lead_draft(m, q, b):  # runs unlocked: an LLM call can take a minute and must not freeze the app
        with lock:
            lead = store.get(int(m.group(1)))
        if not lead:
            raise HttpError(404, "lead not found")
        text, engine = make_draft(lead, cfg(), use_llm=bool(b.get("llm")))
        with lock:
            store.update(lead.id, draft=text)
        return 200, {"draft": text, "engine": engine}

    def bulk(m, q, b):
        ids = b.get("ids")
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            raise HttpError(400, "ids must be a list of numbers")
        return 200, {"updated": store.update_many(ids, b.get("status", ""))}

    def export(m, q, b):
        leads = store.query(status=q.get("status") or None, min_score=int(q.get("min", 0) or 0),
                            limit=100000, include_ignored=bool(q.get("status")))
        out = io.StringIO()
        w = csv.writer(out)
        cols = ["id", "score", "status", "source", "kind", "title", "url", "contact", "location", "budget", "notes"]
        w.writerow(cols)
        for l in leads:
            # prefix formula characters so Excel/Sheets never run a lead's text as a formula
            w.writerow([("'" + str(v)) if str(v)[:1] in "=+-@" and str(v) else v
                        for v in (getattr(l, c) for c in cols)])
        return 200, ("text/csv; charset=utf-8", out.getvalue().encode())

    def config_get(m, q, b):
        return 200, config.to_dict(cfg())

    def config_set(m, q, b):
        try:
            new = config.from_dict(cfg(), b)
        except (ValueError, TypeError) as e:
            raise HttpError(400, str(e))
        config.save(new, config_path)
        return 200, config.to_dict(new)

    def job_start(m, q, b):
        try:
            job = jobs.start(str(b.get("kind", "")), b.get("params") or {})
        except JobBusy as e:
            raise HttpError(409, str(e))
        except (ValueError, TypeError) as e:
            raise HttpError(400, str(e))
        return 200, job.to_dict()

    def job_current(m, q, b):
        return 200, jobs.current.to_dict() if jobs.current else None

    def job_get(m, q, b):
        job = jobs.get(m.group(1))
        if not job:
            raise HttpError(404, "job not found")
        return 200, job.to_dict()

    def job_cancel(m, q, b):
        return 200, {"cancelled": jobs.cancel(m.group(1))}

    ROUTES = [
        ("GET", r"/api/meta", meta), ("GET", r"/api/stats", lambda m, q, b: (200, store.stats())),
        ("GET", r"/api/leads", leads_list), ("GET", r"/api/leads/(\d+)", lead_get),
        ("POST", r"/api/leads/(\d+)", lead_update), ("POST", r"/api/leads/(\d+)/draft", lead_draft, False),
        ("POST", r"/api/leads/bulk", bulk), ("GET", r"/api/export", export),
        ("GET", r"/api/config", config_get), ("POST", r"/api/config", config_set),
        ("POST", r"/api/jobs", job_start), ("GET", r"/api/jobs/current", job_current),
        ("GET", r"/api/jobs/([0-9a-f]{10})", job_get), ("POST", r"/api/jobs/([0-9a-f]{10})/cancel", job_cancel),
    ]

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
            self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in allowed_hosts

        def _handle(self, method: str):
            u = urlparse(self.path)
            if not self._host_ok():
                return self._send(403, {"error": "bad host"})
            if method == "GET" and u.path in ("/", "/index.html"):
                html = (STATIC / "index.html").read_text(encoding="utf-8").replace("__LEADHOUND_TOKEN__", token)
                return self._send(200, html.encode(), "text/html; charset=utf-8")
            if method == "GET" and u.path.startswith("/static/"):
                name = u.path[len("/static/"):]
                if name in STATIC_FILES:
                    return self._send(200, (STATIC / name).read_bytes(), STATIC_FILES[name] + "; charset=utf-8")
                return self._send(404, {"error": "not found"})
            if not u.path.startswith("/api/"):
                return self._send(404, {"error": "not found"})
            if not secrets.compare_digest(self.headers.get("X-Leadhound-Token", ""), token):
                return self._send(403, {"error": "missing or bad token"})
            body = {}
            if method == "POST":
                try:
                    n = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(min(n, 200_000)) or b"{}")
                    if not isinstance(body, dict):
                        raise ValueError
                except (ValueError, json.JSONDecodeError):
                    return self._send(400, {"error": "bad json"})
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            for route in ROUTES:
                meth, pattern, fn = route[:3]
                locked = route[3] if len(route) > 3 else True
                m = re.fullmatch(pattern, u.path)
                if meth == method and m:
                    try:
                        if locked:
                            with lock:
                                code, payload = fn(m, q, body)
                        else:
                            code, payload = fn(m, q, body)
                    except HttpError as e:
                        return self._send(e.code, {"error": e.msg})
                    except (ValueError, TypeError) as e:
                        return self._send(400, {"error": str(e)})
                    if isinstance(payload, tuple):  # (content type, bytes) for downloads
                        return self._send(code, payload[1], payload[0])
                    return self._send(code, payload)
            self._send(404, {"error": "not found"})

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

    return Handler


def store_path(store: Store) -> str:
    row = store.db.execute("PRAGMA database_list").fetchone()
    return row[2] or ":memory:"


def make_server(db_path: str, config_path: str, port: int = 8787, fetcher_factory=None):
    store = Store(db_path)
    token = secrets.token_urlsafe(24)
    jm = JobManager(db_path, config_path, **({"fetcher_factory": fetcher_factory} if fetcher_factory else {}))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
    # build the handler after binding so the Host allow-list uses the real port (port 0 = any free port)
    httpd.RequestHandlerClass = make_handler(store, config_path, token, httpd.server_address[1], jm)
    httpd.jobs = jm
    return httpd, token


def bind(db_path: str, config_path: str, port: int, tries: int = 20):
    """Try port, port+1, ... so a busy port never blocks startup."""
    for p in range(port, port + tries):
        try:
            return make_server(db_path, config_path, p)
        except OSError:
            continue
    raise OSError(f"no free port in {port}-{port + tries - 1}")


def serve(db_path: str, config_path: str, port: int = 8787, open_browser: bool = True) -> None:
    httpd, _ = bind(db_path, config_path, port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"leadhound is running at {url}  (close this window or press Ctrl+C to stop)", flush=True)
    print(f"your data: {db_path}", flush=True)
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
