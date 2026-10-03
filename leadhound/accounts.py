"""Connected accounts: where leadhound can send messages from.

Credentials live in accounts.json next to the config file. The file is created readable by its owner
only (like ~/.ssh keys). It is not encrypted: anyone who can read your user folder can read it.
Nothing here ever reaches the browser: public() returns names and counters, never secrets.

Two kinds of platform:
  send  leadhound sends through the connected account (email, Mastodon, GitHub, Reddit)
  link  leadhound opens the app or page with the message ready (Gmail, Outlook, Freelancer.com, WhatsApp, Telegram).
        Nothing to connect: it uses whatever the user is already signed in to.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import date

PLATFORMS = {
    "email": {"mode": "send", "cap": 10, "fields": ("provider", "address", "password", "host", "port")},
    "mastodon": {"mode": "send", "cap": 10, "fields": ("instance", "token")},
    "github": {"mode": "send", "cap": 5, "fields": ("token",)},
    "reddit": {"mode": "send", "cap": 5, "fields": ("client_id", "client_secret", "username", "password")},
    "gmail": {"mode": "link"}, "outlook": {"mode": "link"}, "freelancer": {"mode": "link"},
    "whatsapp": {"mode": "link"}, "telegram": {"mode": "link"},
}
KEEP_DAYS = 14


class Accounts:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.Lock()

    # ---- file ----
    def _read(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        try:
            os.remove(tmp)
        except OSError:
            pass
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # owner-only from the first byte
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self.path)

    # ---- queries ----
    @staticmethod
    def _today() -> str:
        return date.today().isoformat()

    def public(self) -> dict:
        d = self._read()
        acc, links, used = d.get("accounts", {}), d.get("links", {}), d.get("usage", {}).get(self._today(), {})
        out = {}
        for pid, spec in PLATFORMS.items():
            if spec["mode"] == "send":
                a = acc.get(pid)
                out[pid] = {"mode": "send", "connected": bool(a), "ready": bool(a), "as": (a or {}).get("as", ""),
                            "used": int(used.get(pid, 0)), "cap": spec["cap"]}
            else:
                on = bool(links.get(pid, True))  # no account to connect: on unless the user turns it off
                out[pid] = {"mode": "link", "on": on, "ready": on}
        return out

    def get(self, pid: str) -> dict | None:
        """The stored secrets for one platform. Server side only."""
        return self._read().get("accounts", {}).get(pid)

    def used_today(self, pid: str) -> int:
        return int(self._read().get("usage", {}).get(self._today(), {}).get(pid, 0))

    # ---- changes ----
    def connect(self, pid: str, data: dict) -> None:
        with self.lock:
            d = self._read()
            d.setdefault("accounts", {})[pid] = data
            self._write(d)

    def disconnect(self, pid: str) -> bool:
        with self.lock:
            d = self._read()
            had = d.get("accounts", {}).pop(pid, None) is not None
            self._write(d)
            return had

    def set_link(self, pid: str, on: bool) -> None:
        with self.lock:
            d = self._read()
            d.setdefault("links", {})[pid] = bool(on)
            self._write(d)

    def bump(self, pid: str) -> int:
        with self.lock:
            d = self._read()
            usage = d.setdefault("usage", {})
            today = self._today()
            day = usage.setdefault(today, {})
            day[pid] = day.get(pid, 0) + 1
            for old in sorted(usage)[:-KEEP_DAYS]:
                del usage[old]
            self._write(d)
            return day[pid]


_last: dict[tuple, float] = {}


def too_soon(key: tuple, gap: float) -> bool:
    """True if `key` was used less than `gap` seconds ago. Records the use otherwise."""
    now = time.monotonic()
    if now - _last.get(key, -1e9) < gap:
        return True
    _last[key] = now
    return False
