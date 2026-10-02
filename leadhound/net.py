"""Polite HTTP client: identifying User-Agent, per-host rate limit, retry on 429/5xx."""
from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from . import __version__

USER_AGENT = f"leadhound/{__version__} (+https://github.com/kalidatuna/leadhound)"
MAX_BYTES = 3_000_000
# Hosts with strict anonymous limits get extra spacing between requests (seconds)
HOST_INTERVALS = {"www.reddit.com": 7.0, "nominatim.openstreetmap.org": 1.1, "api.github.com": 2.5}


@dataclass
class Response:
    status: int
    url: str  # final URL after redirects
    headers: dict
    body: bytes
    elapsed: float

    def text(self) -> str:
        ctype = self.headers.get("content-type", "")
        enc = "utf-8"
        if "charset=" in ctype:
            enc = ctype.split("charset=")[-1].split(";")[0].strip() or "utf-8"
        return self.body.decode(enc, errors="replace")

    def json(self):
        return json.loads(self.body.decode("utf-8", errors="replace"))


class FetchError(Exception):
    pass


class Fetcher:
    def __init__(self, min_interval: float = 1.0, timeout: float = 20, retries: int = 2):
        self.min_interval = min_interval
        self.timeout = timeout
        self.retries = retries
        self._last: dict[str, float] = {}

    def _wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            interval = max(self.min_interval, HOST_INTERVALS.get(host, 0)) if self.min_interval else 0
            delay = interval - (time.monotonic() - last)
            if delay > 0:
                time.sleep(delay)
        self._last[host] = time.monotonic()

    def request(self, url: str, method: str = "GET", data: bytes | None = None,
                headers: dict | None = None, timeout: float | None = None) -> Response:
        h = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        h.update(headers or {})
        host = urlparse(url).netloc
        attempt = 0
        while True:
            self._wait(host)
            req = urllib.request.Request(url, data=data, headers=h, method=method)
            t0 = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                    body = r.read(MAX_BYTES)
                    return Response(r.status, r.geturl(), {k.lower(): v for k, v in r.headers.items()},
                                    body, time.monotonic() - t0)
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    attempt += 1
                    retry_after = e.headers.get("Retry-After", "") if e.headers else ""
                    time.sleep(min(float(retry_after), 60) if retry_after.isdigit() else 2 ** attempt)
                    continue
                body = e.read(MAX_BYTES) if hasattr(e, "read") else b""
                return Response(e.code, url, {k.lower(): v for k, v in (e.headers or {}).items()},
                                body, time.monotonic() - t0)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                reason = getattr(e, "reason", e)
                # TLS and DNS failures will not fix themselves on retry
                if attempt < self.retries and not isinstance(reason, (ssl.SSLError, socket.gaierror)):
                    attempt += 1
                    time.sleep(2 ** attempt)
                    continue
                raise FetchError(f"{url}: {reason}") from e

    def get_json(self, url: str, headers: dict | None = None, data: bytes | None = None):
        r = self.request(url, method="POST" if data else "GET", data=data,
                         headers={"Accept": "application/json", **(headers or {})})
        if r.status >= 400:
            raise FetchError(f"{url}: HTTP {r.status}")
        return r.json()

    def get_text(self, url: str, headers: dict | None = None) -> str:
        r = self.request(url, headers=headers)
        if r.status >= 400:
            raise FetchError(f"{url}: HTTP {r.status}")
        return r.text()
