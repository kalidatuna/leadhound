"""Reddit private messages through the user's own script app (client id and secret from reddit.com/prefs/apps)."""
from __future__ import annotations

import base64
import urllib.parse

from . import SendError, call
from ..net import USER_AGENT

AUTH = "https://www.reddit.com"
API = "https://oauth.reddit.com"


def _token(s: dict) -> str:
    basic = base64.b64encode(f"{s['client_id']}:{s['client_secret']}".encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "password", "username": s["username"], "password": s["password"]}).encode()
    status, body = call("POST", f"{AUTH}/api/v1/access_token",
                        {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"}, data)
    if status == 429:
        raise SendError("Reddit says slow down. Try again in a few minutes.")
    if status != 200 or not isinstance(body, dict) or "access_token" not in body:
        raise SendError("Reddit refused those details. Check the app id, secret, username and password.")
    return body["access_token"]


def verify(f: dict) -> tuple[dict, str]:
    s = {k: str(f.get(k, "")).strip() for k in ("client_id", "client_secret", "username", "password")}
    if not all(s.values()):
        raise SendError("Fill in all four fields.")
    s["username"] = s["username"].removeprefix("u/")
    _token(s)
    return s, "u/" + s["username"]


def send(secrets: dict, to: str, subject: str, body: str) -> None:
    user = (to or "").removeprefix("u/")
    if not user.replace("-", "").replace("_", "").isalnum():
        raise SendError("The lead's Reddit name looks wrong.")
    token = _token(secrets)
    data = urllib.parse.urlencode({"api_type": "json", "to": user, "subject": " ".join(subject.split())[:100] or "Hello",
                                   "text": body}).encode()
    status, resp = call("POST", f"{API}/api/compose", {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT,
                                                        "Content-Type": "application/x-www-form-urlencoded"}, data)
    errors = ((resp or {}).get("json", {}) if isinstance(resp, dict) else {}).get("errors") or []
    if status == 429 or any("RATELIMIT" in str(e) for e in errors):
        raise SendError("Reddit says slow down. Try again in a few minutes.")
    if status >= 400 or errors:
        raise SendError("Reddit did not accept the message" + (f": {errors[0][1]}" if errors and len(errors[0]) > 1 else "."))
