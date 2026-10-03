"""Plans: a free taste, a 7-day trial after sign-up, Free, and Pro by license key.

How a copy of leadhound moves through them:
  taste    full Pro for the first TASTE_USES uses (a search, a sent message, an AI draft).
  sign-up  then it asks for an email. The license server (licenseserver.py) gives one signed 7-day trial per email
           and per device, so deleting files or reinstalling does not start a new one.
  trial    7 days of Pro. Ends for good; asking the server again returns the same, already ended, trial.
  free     3 searches a day, your top 10 matches, and "open Gmail / WhatsApp with the message ready".
  pro      a license key (`LH1.<payload>.<signature>`) signed by the seller's private key, checked offline.

Where the lock is real: the AI drafts run on the seller's server and need a valid key or trial, so they cannot be
unlocked by editing this app. Searching and sending run on the user's computer, and leadhound is open source, so
a developer who edits the code can skip those checks. The server, the signed tokens and the device record stop the
ordinary routes (deleting license.json, reinstalling, copying a file between computers), not a patched copy.

While PUBLIC_KEY_HEX is empty (a fresh checkout, a fork) licensing is off and everything is unlocked.
If SERVER is empty the sign-up step is skipped and the trial is a plain 7-day clock on this computer.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import platform
import re
import secrets
import time
import urllib.error
import urllib.request
import uuid
from datetime import date

from . import ed25519

PUBLIC_KEY_HEX = os.environ.get("LEADHOUND_PUBLIC_KEY", "b87d8ad3a99c643ab15c3cd13978df8c5c609e5c01f12ce2a9a50e144b7c72d3")  # set by the seller: `leadhound license keygen`, then paste the public key here
SERVER = os.environ.get("LEADHOUND_LICENSE_SERVER", "https://leadhound-license-nino.fly.dev").rstrip("/")  # the seller's license server (https://...)
BUY_URL = os.environ.get("LEADHOUND_BUY_URL", "https://paypal.me/SupplierIndexUK")  # where "Get Pro" goes (PayPal link, shop page...)
PRICE_MONTH = os.environ.get("LEADHOUND_PRICE_MONTH", "$12.99")
PRICE_YEAR = os.environ.get("LEADHOUND_PRICE_YEAR", "$89.99")
TRIAL_DAYS = 7
TASTE_USES = 7         # uses before the email sign-up (needs SERVER)
FREE_SEARCHES = 3      # "find new clients" runs per day on Free
FREE_MAX_LEADS = 10    # matches shown on Free
FEATURES = ("send", "ai", "business", "autosearch")  # what Free does not include
DAY = 86400
EMAIL_RX = re.compile(r"^[^\s@<>\",;]{1,64}@[^\s@<>\",;]+\.[^\s@<>\",;]+$")


class ProRequired(Exception):
    """A Free user asked for a Pro feature. The dashboard answers 402 and opens the plan dialog."""


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def public_hex(secret: bytes) -> str:
    return ed25519.public_key(secret).hex()


def make_key(secret: bytes, email: str, days: int, plan: str = "pro", now: float | None = None) -> str:
    now = now or time.time()
    payload = json.dumps({"v": 1, "plan": plan, "email": email, "iat": int(now), "exp": int(now + days * DAY),
                          "id": secrets.token_hex(4)}, separators=(",", ":")).encode()
    return f"LH1.{_b64(payload)}.{_b64(ed25519.sign(secret, payload))}"


def read_key(token: str, public: str | None = None) -> dict | None:
    """The token's payload if the signature is genuine, else None. Does not check the end date."""
    try:
        tag, body, sig = token.strip().split(".")
        payload = _unb64(body)
        if tag != "LH1" or not ed25519.verify(bytes.fromhex(public or PUBLIC_KEY_HEX), payload, _unb64(sig)):
            return None
        data = json.loads(payload)
        return data if isinstance(data, dict) and isinstance(data.get("exp"), int) else None
    except (ValueError, TypeError):
        return None


def device_id() -> str:
    """A stable code for this computer (a hash, not its name). The same after a reinstall."""
    return hashlib.sha256(f"leadhound|{uuid.getnode()}|{platform.node()}".encode()).hexdigest()


def post_json(path: str, body: dict, timeout: float = 20) -> dict:
    """Call the license server. Raises ValueError with a message fit to show."""
    if not SERVER.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        raise ValueError("The license server is not set up.")
    req = urllib.request.Request(SERVER + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "leadhound"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read(200_000))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read(5000)).get("error", "")
        except (ValueError, OSError):
            msg = ""
        raise ValueError(msg or f"The server said no ({e.code}).")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ValueError("Could not reach the sign-up server. Check your internet and try again.")


class License:
    def __init__(self, path: str, clock=time.time):
        self.path, self.clock = path, clock

    def _read(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, d: dict) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, self.path)

    @property
    def configured(self) -> bool:
        return bool(PUBLIC_KEY_HEX)

    def status(self) -> dict:
        now, d = self.clock(), self._read()
        base = {"configured": self.configured, "server": bool(SERVER), "buy_url": BUY_URL, "price_month": PRICE_MONTH,
                "price_year": PRICE_YEAR, "trial_days": TRIAL_DAYS, "free_searches": FREE_SEARCHES,
                "free_max_leads": FREE_MAX_LEADS, "taste_uses": TASTE_USES, "email": "", "expires": 0, "trial_left": 0,
                "uses_left": None, "key_state": "none", "searches_left": None, "need_signup": False, "trial_used": False}
        if not self.configured:  # fresh checkout or fork: nothing is locked
            return {**base, "plan": "pro"}
        key = read_key(d["key"]) if d.get("key") else None
        if d.get("key") and (not key or key.get("plan") != "pro"):
            base["key_state"] = "invalid"
        elif key and key["exp"] > now:
            return {**base, "plan": "pro", "email": key.get("email", ""), "expires": key["exp"], "key_state": "ok"}
        elif key:
            base["key_state"], base["email"], base["expires"] = "expired", key.get("email", ""), key["exp"]
        trial = read_key(d["trial_token"]) if d.get("trial_token") else None
        if trial and trial.get("plan") == "trial":
            if trial["exp"] > now:
                return {**base, "plan": "trial", "email": trial.get("email", ""), "expires": trial["exp"],
                        "trial_left": max(1, math.ceil((trial["exp"] - now) / DAY))}
            base["trial_used"] = True
        if "first_use" not in d:
            d["first_use"] = now
            self._write(d)
        if not base["trial_used"]:
            if not SERVER:  # no sign-up server: a plain clock on this computer
                left = d["first_use"] + TRIAL_DAYS * DAY - now
                if left > 0:
                    return {**base, "plan": "trial", "trial_left": max(1, math.ceil(left / DAY))}
            else:
                uses = d.get("uses", 0)
                if uses < TASTE_USES and d["first_use"] + TRIAL_DAYS * DAY > now:
                    return {**base, "plan": "taste", "uses_left": TASTE_USES - uses}
                base["need_signup"] = True
        used = d.get("searches", {}).get(date.fromtimestamp(now).isoformat(), 0)
        return {**base, "plan": "free", "searches_left": max(0, FREE_SEARCHES - used)}

    def is_pro(self) -> bool:
        return self.status()["plan"] in ("pro", "trial", "taste")

    def require(self, feature: str) -> None:
        if feature not in FEATURES:
            raise ValueError(f"unknown feature {feature}")
        if not self.is_pro():
            raise ProRequired(feature)

    def max_leads(self) -> int:
        return 100000 if self.is_pro() else FREE_MAX_LEADS

    def count_use(self) -> None:
        """One use of the product (a search, a sent message, an AI draft). Only the free taste counts them."""
        if self.status()["plan"] != "taste":
            return
        d = self._read()
        d["uses"] = d.get("uses", 0) + 1
        self._write(d)

    def use_search(self) -> None:
        """Count one 'find new clients' run. Free users get FREE_SEARCHES a day."""
        st = self.status()
        if st["plan"] != "free":
            self.count_use()
            return
        d, today = self._read(), date.fromtimestamp(self.clock()).isoformat()
        used = d.setdefault("searches", {}).get(today, 0)
        if used >= FREE_SEARCHES:
            raise ProRequired("searches")
        d["searches"] = {today: used + 1}  # older days are not needed
        self._write(d)

    def signup(self, email: str) -> dict:
        """Ask the server for the one free trial for this email and device."""
        email = (email or "").strip()
        if not EMAIL_RX.match(email) or len(email) > 120:
            raise ValueError("Enter a valid email address.")
        resp = post_json("/v1/trial", {"email": email, "device": device_id()})
        token = str(resp.get("token", ""))
        t = read_key(token)
        if not t or t.get("plan") != "trial":
            raise ValueError("The server sent something leadhound could not verify.")
        d = self._read()
        d["trial_token"] = token
        self._write(d)
        st = self.status()
        if st["plan"] != "trial":
            raise ValueError("You already used your free trial on this email or computer.")
        return st

    def ai_token(self) -> str | None:
        """The key or trial that proves to the server this user may use the hosted AI."""
        d = self._read()
        for name in ("key", "trial_token"):
            t = read_key(d[name]) if d.get(name) else None
            if t and t["exp"] > self.clock():
                return d[name]
        return None

    def activate(self, token: str) -> dict:
        key = read_key(token)
        if not key or key.get("plan") != "pro":
            raise ValueError("That key is not valid. Check that you copied all of it.")
        if key["exp"] <= self.clock():
            raise ValueError("That key has expired.")
        d = self._read()
        d["key"] = token.strip()
        self._write(d)
        return self.status()

    def remove_key(self) -> dict:
        d = self._read()
        d.pop("key", None)
        self._write(d)
        return self.status()
