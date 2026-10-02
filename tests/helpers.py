import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from leadhound.config import Config  # noqa: E402
from leadhound.net import FetchError, Response  # noqa: E402

NOW = 1_790_000_000.0  # fixed clock for deterministic tests


def cfg(**kw):
    c = Config(skills=["python", "django", "react", "wordpress", "scraping"], avoid=["unpaid", "equity only"],
               min_budget=300, min_rate=25, pitch="I build fast web apps", portfolio="https://me.dev",
               signature="Dato", reddit_subreddits=["forhire"], rss_feeds=["https://jobs.example/feed.rss"],
               github_labels=["bounty"], github_languages=[], max_age_days=14)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


class FakeFetcher:
    """Routes URL substrings to canned payloads. Records every URL requested."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def _find(self, url):
        self.calls.append(url)
        for key, payload in self.routes:
            if key in url:
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise FetchError(f"no route for {url}")

    def get_json(self, url, headers=None, data=None):
        p = self._find(url)
        return json.loads(p) if isinstance(p, str) else p

    def get_text(self, url, headers=None):
        return self._find(url)

    def request(self, url, method="GET", data=None, headers=None, timeout=None):
        p = self._find(url)
        if isinstance(p, Response):
            return p
        body = p.encode() if isinstance(p, str) else json.dumps(p).encode()
        return Response(200, url, {"content-type": "application/json"}, body, 0.01)
