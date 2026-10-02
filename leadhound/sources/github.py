"""GitHub: open, unassigned issues labelled bounty / help wanted (Search API).

Set GITHUB_TOKEN for higher rate limits. A label named "bounty" is not proof of money (many projects
use points), so only issues with a cash amount or an Algora 💎 label count as "paid bounty".
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import quote

from ..models import Lead
from .base import PartialFailure, collect_each

API = "https://api.github.com/search/issues?q={}&sort=created&order=desc&per_page=50"
MAX_PER_OWNER = 3
MONEY_RX = re.compile(r"(\$\s?\d[\d,]*(?:\.\d+)?k?|\d[\d,]*\s?(?:usd|\$))", re.I)


def iso_ts(s: str) -> float:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


def build_queries(labels: list, languages: list, since: str) -> list[tuple[str, str]]:
    """Return (query, language) pairs; language is '' when not filtered."""
    qs = []
    for label in labels:
        base = f'is:issue is:open label:"{label}" created:>={since} no:assignee'
        if languages:
            qs += [(f"{base} language:{lang}", lang) for lang in languages]
        else:
            qs.append((base, ""))
    return qs


def parse_search(data: dict, language: str = "") -> list[Lead]:
    leads = []
    for it in data.get("items", []):
        if it.get("pull_request"):
            continue
        labels = [l.get("name", "") for l in it.get("labels", [])]
        repo = "/".join(it.get("repository_url", "").split("/")[-2:])
        title = it.get("title", "")
        body = it.get("body") or ""
        signals = [f"repo {repo}"] + [f"label: {l}" for l in labels]
        money = MONEY_RX.search(" ".join(labels) + " " + title)
        if money or any("💎" in l for l in labels):
            signals.append("paid bounty")
        elif any("bounty" in l.lower() for l in labels):
            signals.append("bounty label (no amount)")
        leads.append(Lead(
            source="github", external_id=str(it.get("id")), kind="issue", title=f"[{repo}] {title}",
            url=it.get("html_url", ""), body=body[:6000], author=(it.get("user") or {}).get("login", ""),
            created_at=iso_ts(it.get("created_at", "")), contact=f"issue thread on {repo}",
            budget=money.group(0) if money else "", signals=signals,
            extra={"comments": it.get("comments", 0), "repo": repo, "labels": labels, "language": language,
                   "reactions": (it.get("reactions") or {}).get("total_count", 0)},
        ))
    return leads


def collect(fetcher, cfg, now: float) -> list[Lead]:
    if not cfg.github:
        return []
    since = datetime.fromtimestamp(now - cfg.max_age_days * 86400, timezone.utc).strftime("%Y-%m-%d")
    headers = {"Accept": "application/vnd.github+json"}
    if cfg.github_token:
        headers["Authorization"] = f"Bearer {cfg.github_token}"
    partial = None
    try:
        raw = collect_each(build_queries(cfg.github_labels, cfg.github_languages, since),
                           lambda ql: parse_search(fetcher.get_json(API.format(quote(ql[0])), headers=headers), ql[1]))
    except PartialFailure as pf:
        raw, partial = pf.leads, pf
    seen, per_owner, leads = set(), {}, []
    for lead in raw:
        owner = lead.extra["repo"].split("/")[0].lower()
        # one org labelling dozens of issues across its repos must not crowd out everyone else
        if lead.external_id in seen or per_owner.get(owner, 0) >= MAX_PER_OWNER:
            continue
        seen.add(lead.external_id)
        per_owner[owner] = per_owner.get(owner, 0) + 1
        leads.append(lead)
    if partial:
        raise PartialFailure(leads, partial.errors)
    return leads
