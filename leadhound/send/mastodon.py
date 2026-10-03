"""Mastodon direct messages with an access token the user creates on their own server."""
from __future__ import annotations

import re
import urllib.parse

from . import SendError, call, clean_host

LIMIT = 500
ACCT_RX = re.compile(r"^@?([\w.-]{1,60})(@[\w.-]{3,100})?$")


def base(instance: str) -> str:
    return f"https://{instance}"


def verify(f: dict, cloud: bool) -> tuple[dict, str]:
    instance, token = clean_host(str(f.get("instance", "")), cloud), str(f.get("token", "")).strip()
    if len(token) < 10:
        raise SendError("Paste the access token from your server's Development settings.")
    status, body = call("GET", f"{base(instance)}/api/v1/accounts/verify_credentials", {"Authorization": f"Bearer {token}"})
    if status in (401, 403):
        raise SendError("The server refused that token.")
    if status != 200 or not isinstance(body, dict) or not body.get("acct"):
        raise SendError(f"The server answered with an error ({status}).")
    return {"instance": instance, "token": token}, f"@{body['acct'].split('@')[0]}@{instance}"


def send(secrets: dict, to: str, body: str) -> None:
    m = ACCT_RX.match(to or "")
    if not m:
        raise SendError("The lead's Mastodon name looks wrong.")
    text = f"@{m.group(1)}{m.group(2) or ''} {body}"
    if len(text) > LIMIT:
        raise SendError(f"Mastodon allows {LIMIT} characters. Shorten the message by {len(text) - LIMIT}.")
    data = urllib.parse.urlencode({"status": text, "visibility": "direct"}).encode()
    status, resp = call("POST", f"{base(secrets['instance'])}/api/v1/statuses",
                        {"Authorization": f"Bearer {secrets['token']}", "Content-Type": "application/x-www-form-urlencoded"}, data)
    if status in (401, 403):
        raise SendError("The server refused the token. Reconnect Mastodon.")
    if status == 429:
        raise SendError("Mastodon says slow down. Try again in a few minutes.")
    if status >= 400:
        raise SendError(f"Mastodon did not accept the message ({status}).")
