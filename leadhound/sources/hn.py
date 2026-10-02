"""Hacker News: monthly 'Freelancer? Seeking freelancer?' and 'Who is hiring?' threads (Algolia API).

The freelancer thread is no longer posted by the `whoishiring` account, so it is found by title search.
"""
from __future__ import annotations

import re

from ..models import Lead
from ..textutil import find_emails, strip_html

HIRING_SEARCH = "https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=6"
FREELANCER_SEARCH = "https://hn.algolia.com/api/v1/search_by_date?query=%22seeking%20freelancer%22&tags=story&hitsPerPage=10"
ITEM = "https://hn.algolia.com/api/v1/items/{}"
FREELANCER_TITLE = "freelancer? seeking freelancer?"
SEEKING_RX = re.compile(r"^\s*seeking\s+freelancers?\b", re.I)
# Checked against the header line only ("Company | Role | Contract | Remote"), not the whole post
CONTRACT_RX = re.compile(r"\b(contract(or)?|freelance|part[- ]time|fractional)\b", re.I)


def latest_hiring(search: dict) -> str | None:
    for hit in search.get("hits", []):  # newest first
        if "who is hiring" in (hit.get("title") or "").lower():
            return hit["objectID"]
    return None


def latest_freelancer(search: dict) -> str | None:
    """Newest 'Freelancer? Seeking freelancer?' thread; if several appeared within 3 days, the busiest."""
    hits = [h for h in search.get("hits", []) if FREELANCER_TITLE in (h.get("title") or "").lower()]
    if not hits:
        return None
    newest = max(h.get("created_at_i", 0) for h in hits)
    recent = [h for h in hits if newest - h.get("created_at_i", 0) < 3 * 86400]
    return max(recent, key=lambda h: h.get("num_comments") or 0)["objectID"]


def header_line(text: str) -> str:
    """HN job posts start with a 'A | B | C' header; return it, or '' if the post has none."""
    for line in text.split("\n")[:3]:
        if line.count("|") >= 1:
            return line.strip()
    return ""


def parse_thread(item: dict, mode: str, min_created: float) -> list[Lead]:
    leads = []
    for c in item.get("children", []):
        raw = c.get("text") or ""
        if not raw or not c.get("author"):
            continue
        text = strip_html(raw)
        header = header_line(text)
        if mode == "freelancer" and not SEEKING_RX.match(text):
            continue  # skip "SEEKING WORK" posts (competitors)
        if mode == "hiring" and not (header and CONTRACT_RX.search(header)):
            continue  # full-time roles and misplaced job-seeker posts are not freelance clients
        created = float(c.get("created_at_i") or 0)
        if created and created < min_created:
            continue
        first = header or text.split("\n", 1)[0].strip()
        title = first if len(first) <= 140 else first[:137] + "..."
        contacts = find_emails(text) + [f"HN: {c['author']}"]
        leads.append(Lead(
            source="hn", external_id=str(c.get("id")), kind="post", title=title,
            url=f"https://news.ycombinator.com/item?id={c.get('id')}", body=text[:6000],
            author=c["author"], created_at=created, contact=", ".join(contacts),
            signals=["HN seeking freelancer" if mode == "freelancer" else "HN who is hiring (contract)"],
        ))
    return leads


def collect(fetcher, cfg, now: float) -> list[Lead]:
    if not cfg.hn:
        return []
    # Monthly threads: allow at least 35 days so the current month's thread is always in range
    min_created = now - max(cfg.max_age_days, 35) * 86400
    threads = {"freelancer": latest_freelancer(fetcher.get_json(FREELANCER_SEARCH)),
               "hiring": latest_hiring(fetcher.get_json(HIRING_SEARCH))}
    leads = []
    for mode, oid in threads.items():
        if oid:
            leads += parse_thread(fetcher.get_json(ITEM.format(oid)), mode, min_created)
    return leads
