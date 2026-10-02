"""Reddit: client posts from freelance subreddits via the public Atom feed.

Reddit blocks anonymous JSON requests (HTTP 403) but still serves /new/.rss, so the feed is used.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime

from ..models import Lead
from ..textutil import find_emails, strip_html
from .base import collect_each

FEED = "https://www.reddit.com/r/{}/new/.rss?limit=100"
ATOM = "{http://www.w3.org/2005/Atom}"
HIRING_RX = re.compile(r"[\[(]\s*(hiring|task|paid|request|job)\s*[\])]", re.I)
FOR_HIRE_RX = re.compile(r"[\[(]\s*for\s*hire\s*[\])]|\bfor hire\b", re.I)
# Plain-language intent when the post has no tag
ASK_RX = re.compile(
    r"\b(looking for|need|seeking|hire|hiring)\b.{0,40}\b(developer|dev|programmer|freelancer|designer|"
    r"someone|expert|engineer|agency|help)\b", re.I)


def is_client_post(title: str) -> bool:
    if FOR_HIRE_RX.search(title):
        return False  # a competitor offering services, not a client
    return bool(HIRING_RX.search(title) or ASK_RX.search(title))


def _ts(s: str) -> float:
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def clean_body(content_html: str) -> str:
    # drop Reddit's footer: "submitted by /u/x [link] [comments]"
    content_html = content_html.split("<!-- SC_ON -->")[0]
    return strip_html(content_html)


def parse_feed(xml_text: str, sub: str, min_created: float) -> list[Lead]:
    root = ET.fromstring(xml_text.encode("utf-8"))
    leads = []
    for e in root.iter(f"{ATOM}entry"):
        title = e.findtext(f"{ATOM}title", "")
        if not is_client_post(title):
            continue
        created = _ts(e.findtext(f"{ATOM}published", "") or e.findtext(f"{ATOM}updated", ""))
        if created < min_created:
            continue
        link = e.find(f"{ATOM}link")
        author = (e.findtext(f"{ATOM}author/{ATOM}name", "") or "").removeprefix("/u/").strip()
        body = clean_body(e.findtext(f"{ATOM}content", "") or "")
        contacts = find_emails(body)
        if author and author != "[deleted]":
            contacts.append(f"reddit DM: u/{author}")
        eid = (e.findtext(f"{ATOM}id", "") or "").removeprefix("t3_")
        leads.append(Lead(
            source="reddit", external_id=eid, kind="post", title=title,
            url=link.get("href", "") if link is not None else "", body=body[:6000],
            author=f"u/{author}" if author else "", created_at=created, contact=", ".join(contacts),
            signals=[f"r/{sub}"],
        ))
    return leads


def collect(fetcher, cfg, now: float) -> list[Lead]:
    min_created = now - cfg.max_age_days * 86400
    subs = [s.strip().removeprefix("r/") for s in cfg.reddit_subreddits]
    return collect_each(subs, lambda sub: parse_feed(fetcher.get_text(FEED.format(sub)), sub, min_created))
