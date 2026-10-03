"""Mastodon / Fediverse: public hashtag timelines, any language. Only posts that ask for help are kept."""
from __future__ import annotations

from datetime import datetime

from ..langs import is_freelance_client
from ..models import Lead
from ..textutil import find_emails, strip_html
from .base import collect_each

TIMELINE = "https://{host}/api/v1/timelines/tag/{tag}?limit=40"


def _ts(s: str) -> float:
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def parse(statuses: list, tag: str, min_created: float) -> list[Lead]:
    leads = []
    for st in statuses or []:
        if st.get("reblog") or st.get("sensitive"):
            continue
        text = strip_html(st.get("content", ""))
        if not is_freelance_client(text):
            continue
        created = _ts(st.get("created_at", ""))
        if created and created < min_created:
            continue
        acct = (st.get("account") or {}).get("acct", "")
        first = text.split("\n", 1)[0].strip()
        title = first if len(first) <= 120 else first[:117] + "..."
        leads.append(Lead(
            source="mastodon", external_id=st.get("uri") or st.get("url") or str(st.get("id")), kind="post",
            title=title, url=st.get("url") or st.get("uri", ""), body=text[:4000], author=acct, created_at=created,
            contact=", ".join(find_emails(text) + ([f"Mastodon: @{acct}"] if acct else [])),
            signals=[f"#{tag}"], extra={"language": st.get("language") or "", "comments": st.get("replies_count", 0)},
        ))
    return leads


def collect(fetcher, cfg, now: float) -> list[Lead]:
    if not cfg.mastodon:
        return []
    min_created = now - cfg.max_age_days * 86400
    pairs = [(h, t) for h in cfg.mastodon_instances for t in cfg.mastodon_tags]
    raw = collect_each(pairs, lambda ht: parse(fetcher.get_json(TIMELINE.format(host=ht[0], tag=ht[1])), ht[1], min_created))
    seen, leads = set(), []
    for lead in raw:  # the same post shows up under several tags and servers
        if lead.external_id not in seen:
            seen.add(lead.external_id)
            leads.append(lead)
    return leads
