"""Generic RSS 2.0 / Atom feeds (job boards, forum searches, saved searches)."""
from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from ..models import Lead
from ..textutil import find_emails, strip_html
from .base import collect_each

ATOM = "{http://www.w3.org/2005/Atom}"


def _ts(s: str) -> float:
    s = (s or "").strip()
    if not s:
        return 0.0
    try:
        return parsedate_to_datetime(s).timestamp()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def parse_feed(xml_text: str, feed_url: str, min_created: float) -> list[Lead]:
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    host = urlparse(feed_url).netloc
    items = []
    for it in root.iter("item"):
        items.append((it.findtext("title", ""), it.findtext("link", ""),
                      it.findtext("description", ""), it.findtext("pubDate", ""), it.findtext("guid", "")))
    for e in root.iter(f"{ATOM}entry"):
        link = e.find(f"{ATOM}link")
        items.append((e.findtext(f"{ATOM}title", ""), link.get("href", "") if link is not None else "",
                      e.findtext(f"{ATOM}content", "") or e.findtext(f"{ATOM}summary", ""),
                      e.findtext(f"{ATOM}updated", "") or e.findtext(f"{ATOM}published", ""),
                      e.findtext(f"{ATOM}id", "")))
    leads = []
    for title, link, desc, date, guid in items:
        created = _ts(date)
        if created and created < min_created:
            continue
        body = strip_html(desc)
        ext = hashlib.sha1((guid or link or title).encode()).hexdigest()[:16]
        leads.append(Lead(
            source="rss", external_id=ext, kind="post", title=strip_html(title)[:200],
            url=link.strip(), body=body[:6000], created_at=created,
            contact=", ".join(find_emails(body)) or f"apply via {host}", signals=[f"feed {host}"],
        ))
    return leads


def collect(fetcher, cfg, now: float) -> list[Lead]:
    min_created = now - cfg.max_age_days * 86400
    return collect_each(cfg.rss_feeds, lambda url: parse_feed(fetcher.get_text(url), url, min_created))
