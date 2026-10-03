"""Freelancer.com: new client projects per category, worldwide, every profession (public RSS)."""
from __future__ import annotations

import re

from ..models import Lead
from .base import PartialFailure, collect_each
from .rss import parse_feed

FEED = "https://www.freelancer.com/rss/job_{}.xml"
TAIL_RX = re.compile(r"\(Budget:\s*(?P<budget>[^,]+?)\s*,\s*Jobs:\s*(?P<jobs>.*)\)\s*$", re.S)


def parse(xml_text: str, category: str, min_created: float) -> list[Lead]:
    leads = []
    for lead in parse_feed(xml_text, FEED.format(category), min_created):
        m = TAIL_RX.search(lead.body)
        jobs = []
        if m:
            lead.budget = m.group("budget").strip()
            jobs = [j.strip() for j in m.group("jobs").split(",") if j.strip()]
            lead.body = lead.body[:m.start()].rstrip(" .") + "…"
        # stable id from the project URL so the same project in two categories is one lead
        lead.external_id = lead.url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".html")[:120] or lead.external_id
        lead.source = "freelancer"
        lead.contact = "bid on Freelancer.com"
        lead.signals = ["client project post"] + [f"skill: {j}" for j in jobs[:10]]
        lead.extra = {"skills": jobs, "category": category}
        leads.append(lead)
    return leads


def collect(fetcher, cfg, now: float) -> list[Lead]:
    if not cfg.freelancer or not cfg.freelancer_categories:
        return []
    min_created = now - min(cfg.max_age_days, 7) * 86400  # projects get bids within hours; a week is plenty
    partial = None
    try:
        raw = collect_each(cfg.freelancer_categories,
                           lambda c: parse(fetcher.get_text(FEED.format(c)), c, min_created))
    except PartialFailure as pf:
        raw, partial = pf.leads, pf
    seen, leads = set(), []
    for lead in raw:
        if lead.external_id not in seen:
            seen.add(lead.external_id)
            leads.append(lead)
    if partial:
        raise PartialFailure(leads, partial.errors)
    return leads
