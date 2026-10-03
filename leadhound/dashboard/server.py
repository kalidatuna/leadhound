"""The leadhound app server: stdlib HTTP server with a small JSON API.

Local mode (default): binds to 127.0.0.1, rejects foreign Host headers (DNS rebinding) and needs a
per-run token on every API call. Cloud mode (--cloud): binds to all interfaces and adds a password
login with an HttpOnly session cookie. Both send a strict Content-Security-Policy.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import threading
import time
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import __version__, accounts as accts, config, i18n, licensing, paths, profiles, sending, updates
from ..draft import make_draft
from ..jobs import AutoScanner, JobBusy, JobManager
from ..langs import LANGUAGES
from ..models import KINDS, STATUSES
from ..money import CURRENCIES
from ..net import Fetcher
from ..send import SendError
from ..sources import SOURCES, osm
from ..store import Store
from .auth import Auth, TooManyAttempts, cookie_value

STATIC = Path(__file__).parent
STATIC_FILES = {name: ("text/css" if name.endswith(".css") else "text/javascript")
                for name in ("app.css", "app.js", "util.js", "i18n.js", "icons.js", "today.js", "compose.js", "accounts.js", "plan.js",
                             "leads.js", "find.js", "settings.js", "login.js")}
FONT_RX = re.compile(r"fonts/([a-z-]+)\.woff2")
LOCALE_RX = re.compile(r"locales/([a-z]{2})\.json")
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


class HttpError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code, self.msg = code, msg


class Ctx:
    """Everything a request needs; one per server."""

    def __init__(self, store, config_path, token, port, jobs, auth=None, fetcher_factory=Fetcher):
        self.store, self.config_path, self.token, self.port = store, config_path, token, port
        self.jobs, self.auth, self.fetcher_factory = jobs, auth, fetcher_factory
        self.lock = threading.Lock()
        self.license = licensing.License(os.path.join(os.path.dirname(os.path.abspath(config_path)), "license.json"))
        self.accounts = accts.Accounts(os.path.join(os.path.dirname(os.path.abspath(config_path)), "accounts.json"))
        self.stop = None  # set by make_server: stops the HTTP server (Quit button)
        self.update_cache = os.path.join(os.path.dirname(os.path.abspath(config_path)), "update.json")

    def cfg(self):
        return config.load(self.config_path)


def build_routes(c: Ctx) -> list:
    store = c.store

    def meta(m, q, b):
        cfg = c.cfg()
        return 200, {"version": __version__, "first_run": not os.path.exists(c.config_path), "cloud": bool(c.auth),
                     "mode": updates.install_mode(), "categories": sorted(osm.CATEGORY_TAGS),
                     "sources": list(SOURCES), "statuses": list(STATUSES), "kinds": list(KINDS),
                     "languages": LANGUAGES, "currencies": sorted(CURRENCIES), "professions": profiles.summary(),
                     "llm_ready": cfg.llm_provider != "none", "hosted_ai": bool(licensing.SERVER), "profession": cfg.profession,
                     "config_path": c.config_path, "db_path": store_path(store)}

    def pro(feature: str):
        try:
            c.license.require(feature)
        except licensing.ProRequired:
            raise HttpError(402, "This is a Pro feature. Start your free trial or upgrade.")

    def leads_list(m, q, b):
        leads = store.query(status=q.get("status") or None, kind=q.get("kind") or None,
                            source=q.get("source") or None, min_score=int(q.get("min", 0) or 0),
                            search=q.get("q", ""), limit=min(int(q.get("limit", 300)), 1000, c.license.max_leads()),
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
        if isinstance(b.get("via"), str):  # how it was contacted (email, whatsapp, manual...); only used with status=contacted
            fields["via"] = b["via"]
        for k in ("notes", "draft"):
            if k in fields and (not isinstance(fields[k], str) or len(fields[k]) > 20000):
                raise HttpError(400, f"{k} must be text under 20000 characters")
        was = store.get(lid).status
        store.update(lid, **fields)
        if fields.get("status") == "contacted" and was != "contacted":
            c.license.count_use()
        return 200, asdict(store.get(lid))

    def lead_draft(m, q, b):  # runs unlocked: an LLM call can take a minute and must not freeze the app
        with c.lock:
            lead = store.get(int(m.group(1)))
        if not lead:
            raise HttpError(404, "lead not found")
        if b.get("llm"):
            pro("ai")
        cfg = c.cfg()
        token = c.license.ai_token() if cfg.llm_provider == "leadhound" else None
        text, engine = make_draft(lead, cfg, use_llm=bool(b.get("llm")), ai_token=token)
        if b.get("llm"):
            c.license.count_use()
        with c.lock:
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
        for l in leads:  # prefix formula characters so Excel/Sheets never run a lead's text as a formula
            w.writerow([("'" + str(v)) if str(v)[:1] in "=+-@" and str(v) else v for v in (getattr(l, k) for k in cols)])
        return 200, ("text/csv; charset=utf-8", out.getvalue().encode())

    def config_set(m, q, b):
        base = c.cfg()
        if b.get("profession_defaults"):  # one click: fill skills, sources and targets for a profession
            pid = b["profession_defaults"]
            if pid not in profiles.BY_ID:
                raise HttpError(400, "unknown profession")
            b = {**profiles.defaults(pid), **{k: v for k, v in b.items() if k != "profession_defaults"}}
        try:
            new = config.from_dict(base, b)
        except (ValueError, TypeError) as e:
            raise HttpError(400, str(e))
        if new.auto_scan_hours and not base.auto_scan_hours:
            pro("autosearch")
        config.save(new, c.config_path)
        return 200, config.to_dict(new)

    def job_start(m, q, b):
        kind = str(b.get("kind", ""))
        if kind in ("local", "audit"):
            pro("business")
        try:
            job = c.jobs.start(str(b.get("kind", "")), b.get("params") or {})
        except JobBusy as e:
            raise HttpError(409, str(e))
        except (ValueError, TypeError) as e:
            raise HttpError(400, str(e))
        if kind == "scan":
            try:
                c.license.use_search()
            except licensing.ProRequired:
                c.jobs.cancel(job.id)
                raise HttpError(402, "You used today's free searches. Upgrade for unlimited searches.")
        return 200, job.to_dict()

    def job_get(m, q, b):
        job = c.jobs.get(m.group(1))
        if not job:
            raise HttpError(404, "job not found")
        return 200, job.to_dict()

    def update_info(m, q, b):  # network call: unlocked
        return 200, updates.check(c.fetcher_factory(), c.update_cache, force=bool(q.get("force")))

    def restart(m, q, b):
        if c.auth or updates.install_mode() not in ("pip", "source"):
            raise HttpError(400, "restart is only available for local pip installs")
        threading.Timer(0.5, updates.restart, args=(c.port,)).start()
        return 200, {"restarting": True}

    def quit_app(m, q, b):
        if c.auth or not c.stop:
            raise HttpError(400, "quit is only available for local installs")
        threading.Timer(0.3, c.stop).start()
        return 200, {"stopping": True}

    def need_lead(lid: int):
        lead = store.get(lid)
        if not lead:
            raise HttpError(404, "lead not found")
        return lead

    def lead_channels(m, q, b):
        return 200, sending.channels_for(need_lead(int(m.group(1))), c.accounts.public())

    def lead_send(m, q, b):  # network call: unlocked, store access is locked by hand
        pro("send")
        with c.lock:
            lead = need_lead(int(m.group(1)))
        try:
            res = sending.send_lead(c.accounts, lead, str(b.get("channel", "")), str(b.get("to", "")),
                                    b.get("subject", ""), b.get("body", ""))
        except SendError as e:
            raise HttpError(e.code, str(e))
        with c.lock:
            store.update(lead.id, status="contacted", draft=b["body"], via=res["via"])
            c.license.count_use()
        return 200, res

    def accounts_get(m, q, b):
        return 200, c.accounts.public()

    def account_post(m, q, b):  # a connect check talks to the service: unlocked
        pid, action = m.group(1), b.get("action")
        spec = accts.PLATFORMS.get(pid)
        if not spec:
            raise HttpError(404, "unknown platform")
        if action == "connect":
            pro("send")
            try:
                who = sending.connect(c.accounts, pid, b.get("fields") or {}, bool(c.auth))
            except SendError as e:
                raise HttpError(e.code, str(e))
            return 200, {"as": who, **c.accounts.public()[pid]}
        if action == "disconnect" and spec["mode"] == "send":
            c.accounts.disconnect(pid)
        elif action == "toggle" and spec["mode"] == "link":
            c.accounts.set_link(pid, bool(b.get("on")))
        else:
            raise HttpError(400, "unknown action")
        return 200, c.accounts.public()[pid]

    def plan_get(m, q, b):
        return 200, c.license.status()

    def plan_post(m, q, b):
        try:
            if b.get("action") == "activate":
                return 200, c.license.activate(str(b.get("key", "")))
            if b.get("action") == "remove":
                return 200, c.license.remove_key()
            if b.get("action") == "signup":
                return 200, c.license.signup(str(b.get("email", "")))
        except ValueError as e:
            raise HttpError(400, str(e))
        raise HttpError(400, "unknown action")

    def i18n_catalog(m, q, b):
        lang = m.group(1)
        if lang not in LANGUAGES:
            raise HttpError(404, "unknown language")
        return 200, i18n.merged(lang)

    return [
        ("GET", r"/api/meta", meta), ("GET", r"/api/stats", lambda m, q, b: (200, store.stats())),
        ("GET", r"/api/leads", leads_list), ("GET", r"/api/leads/(\d+)", lead_get),
        ("POST", r"/api/leads/(\d+)", lead_update), ("POST", r"/api/leads/(\d+)/draft", lead_draft, False),
        ("GET", r"/api/leads/(\d+)/channels", lead_channels), ("POST", r"/api/leads/(\d+)/send", lead_send, False),
        ("GET", r"/api/plan", plan_get), ("POST", r"/api/plan", plan_post, False),
        ("GET", r"/api/accounts", accounts_get), ("POST", r"/api/accounts/([a-z]+)", account_post, False),
        ("POST", r"/api/leads/bulk", bulk), ("GET", r"/api/export", export),
        ("GET", r"/api/config", lambda m, q, b: (200, config.to_dict(c.cfg()))), ("POST", r"/api/config", config_set),
        ("POST", r"/api/jobs", job_start),
        ("GET", r"/api/jobs/current", lambda m, q, b: (200, c.jobs.current.to_dict() if c.jobs.current else None)),
        ("GET", r"/api/jobs/([0-9a-f]{10})", job_get),
        ("POST", r"/api/jobs/([0-9a-f]{10})/cancel", lambda m, q, b: (200, {"cancelled": c.jobs.cancel(m.group(1))})),
        ("GET", r"/api/update", update_info, False), ("POST", r"/api/restart", restart),
        ("GET", r"/api/i18n/([a-z]{2})", i18n_catalog), ("POST", r"/api/quit", quit_app),
    ]


def make_handler(c: Ctx):
    routes = build_routes(c)
    allowed_hosts = {f"127.0.0.1:{c.port}", f"localhost:{c.port}"}
    extra_hosts = {h.strip() for h in os.environ.get("LEADHOUND_ALLOWED_HOSTS", "").split(",") if h.strip()}

    class Handler(BaseHTTPRequestHandler):
        server_version = "leadhound"

        def log_message(self, *args):
            pass

        def _send(self, code: int, body, ctype="application/json", headers=None):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            for k, v in {"Content-Type": ctype, "Content-Length": str(len(data)), "Cache-Control": "no-store",
                         "X-Content-Type-Options": "nosniff", "Content-Security-Policy": CSP,
                         "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY", **(headers or {})}.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self) -> bool:
            host = self.headers.get("Host", "")
            if c.auth:  # cloud: the password protects the app; optionally pin the public host name
                return not extra_hosts or host in extra_hosts
            return host in allowed_hosts

        def _session(self) -> str | None:
            return cookie_value(self.headers.get("Cookie", ""))

        def _authed(self) -> bool:
            return not c.auth or c.auth.valid(self._session())

        def _client(self) -> str:
            fwd = self.headers.get("X-Forwarded-For", "")
            return fwd.split(",")[0].strip() if (c.auth and fwd) else self.client_address[0]

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length", 0) or 0)
            body = json.loads(self.rfile.read(min(n, 200_000)) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
            return body

        def _login(self):
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc != self.headers.get("Host", ""):
                return self._send(403, {"error": "bad origin"})
            try:
                pw = str(self._body().get("password", ""))
                session = c.auth.login(self._client(), pw)
            except TooManyAttempts:
                return self._send(429, {"error": "too many attempts, wait 10 minutes"})
            except (ValueError, json.JSONDecodeError):
                return self._send(400, {"error": "bad json"})
            if not session:
                time.sleep(0.5)  # slow down guessing
                return self._send(401, {"error": "wrong password"})
            secure = "; Secure" if self.headers.get("X-Forwarded-Proto", "") == "https" else ""
            cookie = f"lh_session={session}; HttpOnly; SameSite=Strict; Path=/; Max-Age={30 * 86400}{secure}"
            return self._send(200, {"ok": True}, headers={"Set-Cookie": cookie})

        def _handle(self, method: str):
            u = urlparse(self.path)
            if not self._host_ok():
                return self._send(403, {"error": "bad host"})
            if method == "GET" and u.path in ("/", "/index.html"):
                page = "index.html" if self._authed() else "login.html"
                html = (STATIC / page).read_text(encoding="utf-8").replace("__LEADHOUND_TOKEN__", c.token if page == "index.html" else "")
                return self._send(200, html.encode(), "text/html; charset=utf-8")
            if method == "GET" and u.path.startswith("/static/"):
                name = u.path[len("/static/"):]
                if name in STATIC_FILES:
                    return self._send(200, (STATIC / name).read_bytes(), STATIC_FILES[name] + "; charset=utf-8")
                f = FONT_RX.fullmatch(name)
                if f and (STATIC / "fonts" / f"{f.group(1)}.woff2").is_file():
                    return self._send(200, (STATIC / "fonts" / f"{f.group(1)}.woff2").read_bytes(), "font/woff2",
                                      {"Cache-Control": "public, max-age=86400"})
                m = LOCALE_RX.fullmatch(name)
                if m and m.group(1) in LANGUAGES:
                    return self._send(200, (STATIC / "locales" / f"{m.group(1)}.json").read_bytes())
                return self._send(404, {"error": "not found"})
            if not u.path.startswith("/api/"):
                return self._send(404, {"error": "not found"})
            if c.auth and method == "POST" and u.path == "/api/login":
                return self._login()
            if c.auth and method == "POST" and u.path == "/api/logout":
                c.auth.logout(self._session())
                return self._send(200, {"ok": True}, headers={"Set-Cookie": "lh_session=; Path=/; Max-Age=0"})
            if method == "GET" and u.path == "/api/ping":  # lets a second launch find this one; reveals only the version
                return self._send(200, {"leadhound": __version__, "cloud": bool(c.auth)})
            if not self._authed():
                return self._send(401, {"error": "please sign in"})
            if not secrets.compare_digest(self.headers.get("X-Leadhound-Token", ""), c.token):
                return self._send(403, {"error": "missing or bad token"})
            body = {}
            if method == "POST":
                try:
                    body = self._body()
                except (ValueError, json.JSONDecodeError):
                    return self._send(400, {"error": "bad json"})
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            for route in routes:
                meth, pattern, fn = route[:3]
                m = re.fullmatch(pattern, u.path)
                if meth != method or not m:
                    continue
                try:
                    if len(route) > 3 and route[3] is False:
                        code, payload = fn(m, q, body)
                    else:
                        with c.lock:
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


def make_server(db_path: str, config_path: str, port: int = 8787, fetcher_factory=None,
                host: str = "127.0.0.1", password: str | None = None):
    store = Store(db_path)
    token = secrets.token_urlsafe(24)
    auth = Auth(password) if password else None
    factory = fetcher_factory or Fetcher
    jm = JobManager(db_path, config_path, fetcher_factory=factory, cloud=bool(auth))
    httpd = ThreadingHTTPServer((host, port), BaseHTTPRequestHandler)
    # build the handler after binding so the Host allow-list uses the real port (port 0 = any free port)
    ctx = Ctx(store, config_path, token, httpd.server_address[1], jm, auth, factory)
    ctx.stop = httpd.shutdown
    httpd.RequestHandlerClass = make_handler(ctx)
    httpd.jobs = jm
    httpd.ctx = ctx
    httpd.auto = AutoScanner(jm, os.path.join(os.path.dirname(os.path.abspath(config_path)), "state.json"))
    return httpd, token


def find_running(port: int = 8787, tries: int = 20) -> int | None:
    """Port of a leadhound already running on this computer, if any."""
    import urllib.request
    for p in range(port, port + tries):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{p}/api/ping", timeout=0.4) as r:
                info = json.loads(r.read(500))
            if info.get("leadhound") and not info.get("cloud"):
                return p
        except Exception:
            continue
    return None


def bind(db_path: str, config_path: str, port: int, tries: int = 20, **kw):
    """Try port, port+1, ... so a busy port never blocks startup."""
    for p in range(port, port + tries):
        try:
            return make_server(db_path, config_path, p, **kw)
        except OSError:
            continue
    raise OSError(f"no free port in {port}-{port + tries - 1}")


def serve(db_path: str, config_path: str, port: int = 8787, open_browser: bool = True, cloud: bool = False) -> None:
    if cloud:
        password = os.environ.get("LEADHOUND_PASSWORD", "")
        if len(password) < 8:
            raise SystemExit("cloud mode needs LEADHOUND_PASSWORD (at least 8 characters) in the environment")
        httpd, _ = make_server(db_path, config_path, int(os.environ.get("PORT", port)), host="0.0.0.0", password=password)
        print(f"leadhound (cloud mode) listening on port {httpd.server_address[1]}", flush=True)
        open_browser = False
    else:
        running = find_running(port) if open_browser else None
        if running:  # double-clicked twice: just show the window that is already there
            print(f"leadhound is already running at http://127.0.0.1:{running}/, opening it.", flush=True)
            webbrowser.open(f"http://127.0.0.1:{running}/")
            return
        httpd, _ = bind(db_path, config_path, port)
        url = f"http://127.0.0.1:{httpd.server_address[1]}/"
        print(f"leadhound is running at {url}  (close this window or press Ctrl+C to stop)", flush=True)
        if open_browser:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    print(f"your data: {paths.data_dir() if db_path.startswith(paths.data_dir()) else db_path}", flush=True)
    httpd.auto.start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.auto.stop()
        httpd.server_close()
        print("leadhound stopped.", flush=True)
