"""Lead sources. Each module exposes `collect(fetcher, cfg, now) -> list[Lead]`.

To add a source: create a module here with `collect`, then register it in SOURCES.
If some sub-requests fail (one feed of five), raise PartialFailure with the leads you did get.
"""
from .base import PartialFailure, collect_each  # noqa: F401
from . import freelancer, github, hn, mastodon, reddit, rss  # noqa: E402

SOURCES = {
    "freelancer": freelancer.collect,
    "reddit": reddit.collect,
    "hn": hn.collect,
    "github": github.collect,
    "mastodon": mastodon.collect,
    "rss": rss.collect,
}
