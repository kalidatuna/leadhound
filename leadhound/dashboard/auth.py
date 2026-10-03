"""Password login for cloud mode (when leadhound runs on a server you reach over the internet).

Sessions live in memory; restarting the server signs everyone out. Failed logins are rate-limited
per client address.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time

SESSION_DAYS = 30
MAX_FAILS = 5
FAIL_WINDOW = 600  # seconds


class TooManyAttempts(Exception):
    pass


class Auth:
    def __init__(self, password: str):
        if len(password) < 8:
            raise ValueError("LEADHOUND_PASSWORD must be at least 8 characters")
        self._digest = hashlib.sha256(password.encode()).digest()
        self._sessions: dict[str, float] = {}
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def login(self, client: str, password: str) -> str | None:
        now = time.time()
        with self._lock:
            fails = [t for t in self._fails.get(client, []) if now - t < FAIL_WINDOW]
            self._fails[client] = fails
            if len(fails) >= MAX_FAILS:
                raise TooManyAttempts()
            if hmac.compare_digest(hashlib.sha256(password.encode()).digest(), self._digest):
                token = secrets.token_urlsafe(32)
                self._sessions[token] = now + SESSION_DAYS * 86400
                self._fails.pop(client, None)
                return token
            fails.append(now)
            return None

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        with self._lock:
            exp = self._sessions.get(token)
            if exp and exp > time.time():
                return True
            self._sessions.pop(token, None)
            return False

    def logout(self, token: str | None) -> None:
        with self._lock:
            self._sessions.pop(token or "", None)


def cookie_value(header: str, name: str = "lh_session") -> str | None:
    for part in (header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return None
