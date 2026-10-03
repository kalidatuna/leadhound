"""Sending messages through a connected account. One small module per platform.

Every function takes the stored secrets and raises SendError with a message fit to show the user.
HTTP goes through `fetcher()` so tests can swap it; it never retries (a retry could send twice).
"""
from __future__ import annotations

import re

from ..net import Fetcher, FetchError, is_public_host


class SendError(Exception):
    def __init__(self, msg: str, code: int = 400):
        super().__init__(msg)
        self.code = code  # HTTP status for the dashboard: 400 bad input, 429 slow down, 502 the service refused


def fetcher():
    return Fetcher(min_interval=0, retries=0, timeout=20)


def call(method: str, url: str, headers: dict | None = None, data: bytes | None = None):
    """One HTTP call. Returns (status, parsed json or {})."""
    try:
        r = fetcher().request(url, method=method, data=data, headers=headers)
    except FetchError as e:
        raise SendError(f"Could not reach the service: {e}") from e
    try:
        body = r.json() if r.body else {}
    except ValueError:
        body = {}
    return r.status, body if isinstance(body, (dict, list)) else {}


HOST_RX = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def clean_host(host: str, cloud: bool) -> str:
    h = (host or "").strip().lower().removeprefix("https://").strip("/")
    if not HOST_RX.match(h):
        raise SendError("That does not look like a server name.")
    if cloud and not is_public_host(h):
        raise SendError("That server is not allowed.")
    return h
