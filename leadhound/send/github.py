"""GitHub issue comments with a personal access token (needs permission to write issues)."""
from __future__ import annotations

import json
import re

from . import SendError, call

API = "https://api.github.com"
ISSUE_RX = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+)/(?:issues|pull)/(\d+)")
LIMIT = 60000


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def verify(f: dict) -> tuple[dict, str]:
    token = str(f.get("token", "")).strip()
    if len(token) < 20:
        raise SendError("Paste a GitHub personal access token.")
    status, body = call("GET", f"{API}/user", _headers(token))
    if status in (401, 403):
        raise SendError("GitHub refused that token.")
    if status != 200 or not isinstance(body, dict) or not body.get("login"):
        raise SendError(f"GitHub answered with an error ({status}).")
    return {"token": token}, body["login"]


def target(url: str) -> tuple[str, str, int]:
    m = ISSUE_RX.match(url or "")
    if not m:
        raise SendError("This lead is not a GitHub issue.")
    return m.group(1), m.group(2), int(m.group(3))


def send(secrets: dict, url: str, body: str) -> None:
    owner, repo, num = target(url)
    if len(body) > LIMIT:
        raise SendError("That comment is too long for GitHub.")
    status, _ = call("POST", f"{API}/repos/{owner}/{repo}/issues/{num}/comments",
                     {**_headers(secrets["token"]), "Content-Type": "application/json"}, json.dumps({"body": body}).encode())
    if status in (401, 403):
        raise SendError("GitHub refused. The token may lack permission to comment on this repository.")
    if status == 404:
        raise SendError("GitHub cannot find that issue, or the token cannot see it.")
    if status == 410 or status == 422:
        raise SendError("GitHub says comments are closed on this issue.")
    if status >= 400:
        raise SendError(f"GitHub did not accept the comment ({status}).")
