"""Himalayas: remote contract roles (contractors only, not full-time jobs), searched by your skills.

Public JSON API (https://himalayas.app/api). Each lead links back to the role on Himalayas, which is
the attribution they ask for. Three searches per run at most, one per top skill.
"""
from __future__ import annotations

from urllib.parse import quote

from ..models import Lead
from ..textutil import find_emails, strip_html
from .base import PartialFailure, collect_each

SEARCH = "https://himalayas.app/jobs/api/search?q={}&employment_type=Contractor"
SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£"}
MAX_QUERIES = 3


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def budget(job: dict) -> str:
    """'$50-$80/hr' or '$90,000-$120,000' (a year); empty when the role states no pay."""
    lo, hi = _num(job.get("minSalary")), _num(job.get("maxSalary"))
    if not lo and not hi:
        return ""
    cur = (job.get("currency") or "USD").upper()
    sym = SYMBOL.get(cur)
    fmt = (lambda v: f"{sym}{v:,.0f}") if sym else (lambda v: f"{v:,.0f} {cur}")
    text = fmt(lo or hi) if not (lo and hi) or lo == hi else f"{fmt(lo)}-{fmt(hi)}"
    return text + ("/hr" if (job.get("salaryPeriod") or "").lower().startswith("hour") else "")


def parse(data: dict, min_created: float) -> list[Lead]:
    leads = []
    for job in data.get("jobs") or []:
        url = job.get("applicationLink") or job.get("guid") or ""
        guid = job.get("guid") or url
        if not url.startswith("https://") or not job.get("title"):
            continue
        created = _num(job.get("pubDate"))
        if created and created < min_created:
            continue
        body = strip_html(job.get("description") or job.get("excerpt") or "")
        company = (job.get("companyName") or "").strip()
        places = job.get("locationRestrictions") or []
        leads.append(Lead(
            source="himalayas", external_id=guid.rstrip("/").rsplit("/", 1)[-1][:120] or guid[-120:], kind="post",
            title=f"{job['title'].strip()[:160]}" + (f" · {company[:60]}" if company else ""), url=url,
            body=body[:6000], author=company, created_at=created, budget=budget(job),
            contact=", ".join(find_emails(body)) or "apply via himalayas.app",
            location=", ".join(str(p) for p in places[:4]) if isinstance(places, list) else "",
            signals=["remote contract role"],
            extra={"skills": [str(c).replace("-", " ") for c in (job.get("categories") or [])[:12]],
                   "category": ((job.get("parentCategories") or [""])[0] or "")},
        ))
    return leads


def collect(fetcher, cfg, now: float) -> list[Lead]:
    if not getattr(cfg, "himalayas", False):
        return []
    queries = [s for s in cfg.skills if s.strip()][:MAX_QUERIES]
    if not queries:
        return []
    min_created = now - cfg.max_age_days * 86400
    partial = None
    try:
        raw = collect_each(queries, lambda q: parse(fetcher.get_json(SEARCH.format(quote(q))), min_created))
    except PartialFailure as pf:
        raw, partial = pf.leads, pf
    seen, leads = set(), []
    for lead in raw:  # the same role can match two skills
        if lead.external_id not in seen:
            seen.add(lead.external_id)
            leads.append(lead)
    if partial:
        raise PartialFailure(leads, partial.errors)
    return leads
