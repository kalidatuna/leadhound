"""Explainable 0-100 lead score. Every point comes with a reason the user can read and disagree with."""
from __future__ import annotations

import re

from .models import Lead
from .textutil import find_emails, parse_budget, word_hit

INTENT = [
    (re.compile(r"[\[(]\s*hiring\s*[\])]", re.I), 20, "tagged [Hiring]"),
    (re.compile(r"\bseeking freelancers?\b", re.I), 20, "seeking a freelancer"),
    (re.compile(r"\b(looking (for|to hire)|need|seeking)\b.{0,25}\b(developer|dev|programmer|freelancer|"
                r"designer|engineer|agency|expert)\b", re.I), 15, "explicitly looking to hire"),
    (re.compile(r"\b(will pay|paid (task|gig|project|work)|paying)\b", re.I), 12, "says it is paid"),
    (re.compile(r"\bbudget\b", re.I), 8, "mentions a budget"),
    (re.compile(r"\b(contract|freelance|part[- ]time)\b", re.I), 8, "contract / freelance work"),
    (re.compile(r"\b(quote|estimate|proposal|rfp)\b", re.I), 6, "asks for a quote"),
    (re.compile(r"\b(asap|urgent|this week|deadline)\b", re.I), 5, "has urgency"),
]


def _age_points(created: float, now: float) -> tuple[int, str]:
    if not created:
        return 0, "age unknown"
    hours = (now - created) / 3600
    if hours < 24:
        return 15, "posted in the last 24h"
    if hours < 72:
        return 10, "posted in the last 3 days"
    if hours < 168:
        return 5, "posted this week"
    return 0, f"posted {int(hours // 24)} days ago"


def score_intent_lead(lead: Lead, cfg, now: float) -> Lead:
    reasons, total = [], 0
    text = lead.text
    low = text.lower()
    title_low = lead.title.lower()

    # 1. Relevance to your skills (max 35)
    rel, hits = 0, []
    lang = (lead.extra.get("language") or "").lower()  # GitHub issue found via a language filter
    for skill in cfg.skills:
        if word_hit(skill, title_low) or skill.lower() == lang:
            rel += 12
            hits.append(skill)
        elif word_hit(skill, low):
            rel += 7
            hits.append(skill)
    rel = min(rel, 35)
    if hits:
        reasons.append(f"+{rel} skills: {', '.join(hits)}")
    else:
        reasons.append("+0 no skill match")
    total += rel

    # 2. Hiring intent (max 25)
    intent = 0
    for rx, pts, why in INTENT:
        if rx.search(text):
            intent += pts
            reasons.append(f"+{pts} {why}")
    if "paid bounty" in lead.signals:
        intent += 20
        reasons.append("+20 paid bounty")
    elif "bounty label (no amount)" in lead.signals:
        intent += 10
        reasons.append("+10 bounty label, amount unknown (may be points, not cash)")
    elif lead.source == "github":
        intent += 5
        reasons.append("+5 help wanted (often unpaid; good door-opener)")
    if lead.source == "hn" and "seeking freelancer" in " ".join(lead.signals).lower():
        intent += 15
        reasons.append("+15 HN seeking-freelancer thread")
    if intent > 25:
        reasons.append(f"intent capped at 25 (raw {intent})")
    total += min(intent, 25)

    # 3. Budget (max 15)
    b = parse_budget(text) or (parse_budget(lead.budget) if lead.budget else None)
    if b:
        lead.budget = b.text
        if b.hourly:
            if cfg.min_rate and b.high < cfg.min_rate:
                total -= 15
                reasons.append(f"-15 rate {b.text} below your min {cfg.min_rate:g}/h")
            else:
                total += 12
                reasons.append(f"+12 hourly rate stated: {b.text}")
        elif cfg.min_budget and b.high < cfg.min_budget:
            total -= 15
            reasons.append(f"-15 budget {b.text} below your min {cfg.min_budget:g}")
        else:
            total += 15
            reasons.append(f"+15 budget stated: {b.text}")

    # 4. Freshness (max 15)
    pts, why = _age_points(lead.created_at, now)
    total += pts
    reasons.append(f"+{pts} {why}")

    # 5. Contactability (max 10)
    if find_emails(lead.contact) or find_emails(text):
        total += 10
        reasons.append("+10 public email given")
    elif lead.contact:
        total += 5
        reasons.append(f"+5 reachable via {lead.contact.split(',')[0].split(':')[0]}")

    # 6. Competition
    comments = lead.extra.get("comments")
    if comments == 0:
        total += 5
        reasons.append("+5 no replies yet")
    elif isinstance(comments, int) and comments > 20:
        total -= 5
        reasons.append(f"-5 crowded ({comments} replies)")

    # 7. Deal-breakers from your avoid list
    neg = 0
    for phrase in cfg.avoid:
        if word_hit(phrase, low):
            neg += 30
            reasons.append(f"-30 contains '{phrase}'")
    total -= min(neg, 60)

    if not hits and total > 45:
        reasons.append(f"capped at 45: no skill match (raw {total})")
        total = 45
    lead.score = max(0, min(100, total))
    lead.reasons = reasons
    return lead


def score_business(lead: Lead, cfg=None, now: float = 0) -> Lead:
    reasons, total = [], 0
    audit = lead.extra.get("audit")
    website = lead.extra.get("website")
    if not website:
        total += 60
        reasons.append("+60 no website listed in OpenStreetMap (verify before pitching: OSM can be incomplete)")
        if lead.extra.get("booking_relevant"):
            total += 5
            reasons.append("+5 business type that needs online booking")
    elif audit and audit.get("blocked"):
        total += 10
        reasons.append(f"+10 site blocked the automated audit (HTTP {audit.get('status')}); check it by hand")
    elif audit:
        findings = audit.get("findings", [])
        sev = sum(f["severity"] for f in findings)
        pts = min(60, sev * 6)
        total += pts
        reasons.append(f"+{pts} {len(findings)} website issue(s), severity {sev}")
        crit = [f["title"] for f in findings if f["severity"] >= 3]
        if crit:
            total += 10
            reasons.append(f"+10 critical: {', '.join(crit[:3])}")
        if not findings:
            reasons.append("+0 website looks healthy")
    else:
        total += 10
        reasons.append("+10 has website (not audited yet; run with --audit)")
    if lead.extra.get("email"):
        total += 15
        reasons.append("+15 public email")
    elif lead.extra.get("phone"):
        total += 10
        reasons.append("+10 public phone")
    else:
        reasons.append("+0 no public contact found")
    lead.score = max(0, min(100, total))
    lead.reasons = reasons
    return lead


def score(lead: Lead, cfg, now: float) -> Lead:
    if lead.kind == "business":
        return score_business(lead, cfg, now)
    return score_intent_lead(lead, cfg, now)
