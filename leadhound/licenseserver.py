"""The leadhound license server: one trial per person, and the paid AI.

You (the seller) host this, not users. It needs only the standard library:

    LICENSE_PRIVATE_KEY=<hex from `leadhound license keygen`>  ANTHROPIC_API_KEY=...  python -m leadhound.licenseserver

It does two jobs:
  POST /v1/trial {email, device}   gives a signed 7-day trial. One per email and per device, a few per IP a day.
                                   Asking again returns the same trial, so reinstalling never restarts the clock.
  POST /v1/redeem {license_key}   turns a Gumroad license key into a signed Pro token (35 days, renewed by the app
                                   while the purchase is still good: refunds and cancelled payments stop renewing).
  POST /v1/ai {token, system, prompt}   writes a draft with YOUR Anthropic key, for holders of a valid Pro key or
                                   trial. This is the one paid feature that cannot be patched out of the app.
The app checks trial tokens and license keys offline; this server only issues trials and relays AI.
Stores: email (as given), a device code (a hash, not the machine's name), the IP, and start times. Nothing else.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import licensing

TRIAL_DAYS = licensing.TRIAL_DAYS
TRIALS_PER_IP_PER_DAY = 3
PRO_TOKEN_DAYS = 35
GUMROAD_PRODUCT_ID = os.environ.get("GUMROAD_PRODUCT_ID", "")
AI_PER_DAY = int(os.environ.get("AI_DAILY_CAP", "40"))
AI_MODEL = os.environ.get("AI_MODEL", "claude-haiku-4-5-20251001")
MAX_BODY = 20_000
EMAIL_RX = re.compile(r"^[^\s@<>\",;]{1,64}@[a-z0-9-]+(\.[a-z0-9-]+)+$")
DEVICE_RX = re.compile(r"^[0-9a-f]{64}$")
SCHEMA = """
CREATE TABLE IF NOT EXISTS trials (
    email TEXT PRIMARY KEY, device TEXT NOT NULL, ip TEXT, started REAL NOT NULL, exp REAL NOT NULL, token TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trials_device ON trials(device);
CREATE TABLE IF NOT EXISTS ai_usage (who TEXT, day TEXT, n INTEGER, PRIMARY KEY (who, day));
CREATE TABLE IF NOT EXISTS hits (ip TEXT, kind TEXT, at REAL);
"""


def canonical_email(email: str) -> str:
    """The same inbox written differently counts once: dots and +tags in Gmail, +tags elsewhere."""
    local, _, domain = email.strip().lower().partition("@")
    local = local.split("+")[0]
    if domain in ("gmail.com", "googlemail.com"):
        local, domain = local.replace(".", ""), "gmail.com"
    return f"{local}@{domain}"


class Service:
    def __init__(self, db_path: str, secret: bytes, clock=time.time, anthropic=None, gumroad=None):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.secret, self.clock, self.lock = secret, clock, threading.Lock()
        self.anthropic = anthropic or call_anthropic
        self.gumroad = gumroad or call_gumroad

    # ---- rate limits ----
    def _hits(self, ip: str, kind: str, window: float) -> int:
        now = self.clock()
        self.db.execute("DELETE FROM hits WHERE at < ?", (now - 86400,))
        return self.db.execute("SELECT COUNT(*) FROM hits WHERE ip=? AND kind=? AND at>?", (ip, kind, now - window)).fetchone()[0]

    def _hit(self, ip: str, kind: str) -> None:
        self.db.execute("INSERT INTO hits VALUES (?,?,?)", (ip, kind, self.clock()))

    # ---- trials ----
    def trial(self, ip: str, email: str, device: str) -> dict:
        if not isinstance(email, str) or not EMAIL_RX.match(email.strip().lower()) or len(email) > 120:
            raise ServiceError(400, "Enter a valid email address.")
        if not isinstance(device, str) or not DEVICE_RX.match(device):
            raise ServiceError(400, "This copy of leadhound is too old to start a trial.")
        who = canonical_email(email)
        with self.lock:
            row = self.db.execute("SELECT token, exp FROM trials WHERE email=? OR device=? ORDER BY started LIMIT 1", (who, device)).fetchone()
            if row:  # already had a trial: give the same one back, never a new window
                return {"token": row[0], "exp": row[1], "new": False}
            if self._hits(ip, "trial", 86400) >= TRIALS_PER_IP_PER_DAY:
                raise ServiceError(429, "Too many trials started from this network today. Try again tomorrow.")
            now = self.clock()
            token = licensing.make_key(self.secret, email.strip().lower(), TRIAL_DAYS, plan="trial", now=now)
            exp = int(now + TRIAL_DAYS * licensing.DAY)
            self.db.execute("INSERT INTO trials VALUES (?,?,?,?,?,?)", (who, device, ip, now, exp, token))
            self._hit(ip, "trial")
            self.db.commit()
            return {"token": token, "exp": exp, "new": True}

    # ---- paid keys (Gumroad) ----
    def redeem(self, ip: str, license_key: str) -> dict:
        key = (license_key or "").strip() if isinstance(license_key, str) else ""
        if not 8 <= len(key) <= 100:
            raise ServiceError(400, "That does not look like a license key.")
        with self.lock:
            if self._hits(ip, "redeem", 3600) >= 20:
                raise ServiceError(429, "Too many tries. Wait a little and try again.")
            self._hit(ip, "redeem")
            self.db.commit()
        try:
            info = self.gumroad(key)
        except Exception:
            raise ServiceError(502, "Could not check your purchase right now. Try again in a minute.")
        buy = (info or {}).get("purchase") or {}
        if not (info or {}).get("success"):
            raise ServiceError(404, "That license key was not found. Copy it from your Gumroad receipt.")
        if buy.get("refunded") or buy.get("chargebacked") or buy.get("disputed"):
            raise ServiceError(403, "That purchase was refunded.")
        if buy.get("subscription_ended_at") or buy.get("subscription_failed_at"):
            raise ServiceError(403, "That subscription has ended. Renew it on Gumroad to keep Pro.")
        email = str(buy.get("email", ""))[:120] or "customer"
        token = licensing.make_key(self.secret, email, PRO_TOKEN_DAYS, plan="pro", now=self.clock())
        return {"token": token, "exp": int(self.clock() + PRO_TOKEN_DAYS * licensing.DAY), "email": email}

    # ---- paid AI ----
    def ai(self, ip: str, token: str, system: str, prompt: str, max_tokens: int) -> dict:
        key = licensing.read_key(token or "", licensing.public_hex(self.secret))
        if not key or key["exp"] <= self.clock() or key.get("plan") not in ("pro", "trial"):
            raise ServiceError(402, "Your Pro key or trial is not valid. Open the Pro dialog in leadhound.")
        if not (isinstance(system, str) and isinstance(prompt, str)) or len(system) > 4000 or len(prompt) > 8000 or not prompt.strip():
            raise ServiceError(400, "That request is too large.")
        max_tokens = max(50, min(int(max_tokens or 400), 600))
        who, day = canonical_email(key.get("email", "")) or key.get("id", ""), date.fromtimestamp(self.clock()).isoformat()
        with self.lock:
            if self._hits(ip, "ai", 3600) >= 120:
                raise ServiceError(429, "Slow down.")
            used = (self.db.execute("SELECT n FROM ai_usage WHERE who=? AND day=?", (who, day)).fetchone() or [0])[0]
            if used >= AI_PER_DAY:
                raise ServiceError(429, f"Daily AI limit reached ({AI_PER_DAY}). It resets tomorrow.")
            self.db.execute("INSERT INTO ai_usage VALUES (?,?,1) ON CONFLICT(who, day) DO UPDATE SET n = n + 1", (who, day))
            self._hit(ip, "ai")
            self.db.commit()
        try:
            return {"text": self.anthropic(system, prompt, max_tokens)}
        except Exception as e:  # the user's count is kept: a failed call still costs us time
            raise ServiceError(502, f"The AI is not available right now ({str(e)[:80]}).")


class ServiceError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code, self.msg = code, msg


def call_gumroad(license_key: str) -> dict:
    """Ask Gumroad about a license key. Does not use up one of the key's activations."""
    if not GUMROAD_PRODUCT_ID:
        raise RuntimeError("server has no GUMROAD_PRODUCT_ID")
    data = urllib.parse.urlencode({"product_id": GUMROAD_PRODUCT_ID, "license_key": license_key, "increment_uses_count": "false"}).encode()
    req = urllib.request.Request("https://api.gumroad.com/v2/licenses/verify", data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read(100_000))
    except urllib.error.HTTPError as e:
        if e.code == 404:  # Gumroad answers 404 for an unknown key
            return {"success": False}
        raise


def call_anthropic(system: str, prompt: str, max_tokens: int) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("server has no AI key")
    body = {"model": AI_MODEL, "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(), method="POST",
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            parts = json.loads(r.read(200_000)).get("content", [])
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}")
    return "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()


def make_server(service: Service, port: int = 8080, host: str = "0.0.0.0", trust_proxy: bool = False):
    class Handler(BaseHTTPRequestHandler):
        server_version = "leadhound-license"

        def log_message(self, *a):
            pass

        def _send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            for k, v in {"Content-Type": "application/json", "Content-Length": str(len(data)), "Cache-Control": "no-store",
                         "X-Content-Type-Options": "nosniff"}.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _ip(self):
            fwd = self.headers.get("X-Forwarded-For", "")
            return fwd.split(",")[-1].strip() if trust_proxy and fwd else self.client_address[0]

        def do_GET(self):
            self._send(200, {"ok": True}) if self.path == "/health" else self._send(404, {"error": "not found"})

        def do_POST(self):
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                if n > MAX_BODY:
                    return self._send(413, {"error": "too large"})
                b = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(b, dict):
                    raise ValueError
            except (ValueError, json.JSONDecodeError):
                return self._send(400, {"error": "bad json"})
            try:
                if self.path == "/v1/trial":
                    return self._send(200, service.trial(self._ip(), b.get("email", ""), b.get("device", "")))
                if self.path == "/v1/redeem":
                    return self._send(200, service.redeem(self._ip(), b.get("license_key", "")))
                if self.path == "/v1/ai":
                    return self._send(200, service.ai(self._ip(), b.get("token", ""), b.get("system", ""), b.get("prompt", ""), b.get("max_tokens", 400)))
            except ServiceError as e:
                return self._send(e.code, {"error": e.msg})
            self._send(404, {"error": "not found"})

    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    hexkey = os.environ.get("LICENSE_PRIVATE_KEY", "").strip()
    if len(hexkey) != 64:
        raise SystemExit("set LICENSE_PRIVATE_KEY to the 64-character hex key from `leadhound license keygen`")
    service = Service(os.environ.get("LICENSE_DB", "licenses.db"), bytes.fromhex(hexkey))
    httpd = make_server(service, int(os.environ.get("PORT", 8080)), trust_proxy=bool(os.environ.get("TRUST_PROXY")))
    print(f"leadhound license server on port {httpd.server_address[1]}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
