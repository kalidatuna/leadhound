"""Explainable 0-100 lead score. Every point comes with a reason the user can read and disagree with.

Reasons are stored twice: English text in `lead.reasons` (CLI, export) and structured
[points, key, args] in `lead.extra["why"]` so the app can show them in the user's language.
"""
from __future__ import annotations

import re

from .langs import CLIENT_RX
from .models import Lead
from .money import compare_min
from .textutil import find_emails, parse_budget, word_hit

INTENT = [
    (re.compile(r"[\[(]\s*hiring\s*[\])]", re.I), 20, "tag_hiring", "tagged [Hiring]"),
    (re.compile(r"\bseeking freelancers?\b", re.I), 20, "seeking_freelancer", "seeking a freelancer"),
    (re.compile(r"\b(looking (for|to hire)|need|seeking)\b.{0,25}\b(developer|dev|programmer|freelancer|"
                r"designer|engineer|agency|expert|writer|editor|translator|photographer|assistant)\b", re.I),
     15, "wants_hire", "explicitly looking to hire"),
    (re.compile(r"\b(will pay|paid (task|gig|project|work)|paying)\b", re.I), 12, "says_paid", "says it is paid"),
    (re.compile(r"\bbudget\b|presupuesto|orçamento|бюджет", re.I), 8, "mentions_budget", "mentions a budget"),
    (re.compile(r"\b(contract|freelance|part[- ]time)\b", re.I), 8, "contract_work", "contract / freelance work"),
    (re.compile(r"\b(quote|estimate|proposal|rfp)\b", re.I), 6, "asks_quote", "asks for a quote"),
    (re.compile(r"\b(asap|urgent|this week|deadline)\b|urgente|срочно", re.I), 5, "urgency", "has urgency"),
]


class Why:
    def __init__(self):
        self.text: list[str] = []
        self.items: list[list] = []
        self.total = 0

    def add(self, pts: int | None, key: str, text: str, **args) -> None:
        """pts=None records a note (caps) without changing the total."""
        if pts is not None:
            self.total += pts
            sign = "+" if pts >= 0 else ""
            self.text.append(f"{sign}{pts} {text}")
        else:
            self.text.append(text)
        self.items.append([pts, key, args])

    def finish(self, lead: Lead) -> Lead:
        lead.score = max(0, min(100, self.total))
        lead.reasons = self.text
        lead.extra["why"] = self.items
        return lead


def _age(w: Why, created: float, now: float) -> None:
    if not created:
        return w.add(0, "age_unknown", "age unknown")
    hours = (now - created) / 3600
    if hours < 24:
        w.add(15, "fresh_24h", "posted in the last 24h")
    elif hours < 72:
        w.add(10, "fresh_3d", "posted in the last 3 days")
    elif hours < 168:
        w.add(5, "fresh_week", "posted this week")
    else:
        w.add(0, "age_days", f"posted {int(hours // 24)} days ago", days=int(hours // 24))


def score_intent_lead(lead: Lead, cfg, now: float) -> Lead:
    w = Why()
    text = lead.text
    low, title_low = text.lower(), lead.title.lower()

    # 1. Relevance to your skills (max 35). Freelancer.com lists the project's skills explicitly.
    rel, hits = 0, []
    lang = (lead.extra.get("language") or "").lower() if lead.source == "github" else ""
    tagged = " | ".join(lead.extra.get("skills", [])).lower()
    for skill in cfg.skills:
        if word_hit(skill, title_low) or skill.lower() == lang or word_hit(skill, tagged):
            rel += 12
            hits.append(skill)
        elif word_hit(skill, low):
            rel += 7
            hits.append(skill)
    rel = min(rel, 35)
    if hits:
        w.add(rel, "skills", f"skills: {', '.join(hits)}", skills=", ".join(hits))
    else:
        w.add(0, "no_skill", "no skill match")

    # 2. Hiring intent (max 25)
    before = w.total
    for rx, pts, key, why in INTENT:
        if rx.search(text):
            w.add(pts, key, why)
    if w.total == before and CLIENT_RX.search(text):
        w.add(15, "asks_help", "asks for help")  # non-English request
    if lead.source == "freelancer":
        w.add(20, "client_project", "client project post (they pay through Freelancer.com)")
    elif "paid bounty" in lead.signals:
        w.add(20, "paid_bounty", "paid bounty")
    elif "bounty label (no amount)" in lead.signals:
        w.add(10, "bounty_label", "bounty label, amount unknown (may be points, not cash)")
    elif lead.source == "github":
        w.add(5, "help_wanted", "help wanted (often unpaid; good door-opener)")
    if lead.source == "hn" and "seeking freelancer" in " ".join(lead.signals).lower():
        w.add(15, "hn_thread", "HN seeking-freelancer thread")
    intent = w.total - before
    if intent > 25:
        w.total = before + 25
        w.add(None, "intent_cap", f"intent capped at 25 (raw {intent})", raw=intent)

    # 3. Budget (max 15): compared with your minimum in your currency, scaled by size
    b = parse_budget(lead.budget) if lead.budget else None
    b = b or parse_budget(text)
    if b:
        lead.budget = b.text
        minimum = cfg.min_rate if b.hourly else cfg.min_budget
        ok = compare_min(b, minimum, getattr(cfg, "currency", "USD"))
        if ok is False:
            unit = "/h" if b.hourly else ""
            key = "rate_low" if b.hourly else "budget_low"
            label = "rate" if b.hourly else "budget"
            w.add(-15, key, f"{label} {b.text} below your min {minimum:g}{unit}", amount=b.text, min=f"{minimum:g}")
        else:  # bigger budgets rank higher; unknown currency counts as mid-size
            usd = b.usd() if b.currency else None
            if b.hourly:
                pts = 8 if usd is None else 4 if usd < 15 else 8 if usd < 40 else 12
                w.add(pts, "rate_ok", f"hourly rate stated: {b.text}", amount=b.text)
            else:
                pts = 10 if usd is None else 4 if usd < 50 else 8 if usd < 250 else 12 if usd < 1000 else 15
                w.add(pts, "budget_ok", f"budget stated: {b.text}", amount=b.text)

    # 4. Freshness (max 15)
    _age(w, lead.created_at, now)

    # 5. Contactability (max 10)
    if find_emails(lead.contact) or find_emails(text):
        w.add(10, "email", "public email given")
    elif lead.contact:
        via = lead.contact.split(",")[0].split(":")[0]
        w.add(5, "reachable", f"reachable via {via}", via=via)

    # 6. Competition
    comments = lead.extra.get("comments")
    if comments == 0:
        w.add(5, "no_replies", "no replies yet")
    elif isinstance(comments, int) and comments > 20:
        w.add(-5, "crowded", f"crowded ({comments} replies)", n=comments)

    # 7. Deal-breakers from your avoid list
    neg = 0
    for phrase in cfg.avoid:
        if word_hit(phrase, low) and neg < 60:
            neg += 30
            w.add(-30, "avoid", f"contains '{phrase}'", phrase=phrase)

    if not hits and w.total > 45:
        w.add(None, "cap_no_skill", f"capped at 45: no skill match (raw {w.total})", raw=w.total)
        w.total = 45
    return w.finish(lead)


def score_business(lead: Lead, cfg=None, now: float = 0) -> Lead:
    w = Why()
    audit = lead.extra.get("audit")
    website = lead.extra.get("website")
    if not website:
        w.add(60, "no_website", "no website listed in OpenStreetMap (verify before pitching: OSM can be incomplete)")
        if lead.extra.get("booking_relevant"):
            w.add(5, "booking_type", "business type that needs online booking")
    elif audit and audit.get("blocked"):
        w.add(10, "audit_blocked", f"site blocked the automated audit (HTTP {audit.get('status')}); check it by hand",
              status=audit.get("status"))
    elif audit:
        findings = audit.get("findings", [])
        sev = sum(f["severity"] for f in findings)
        pts = min(60, sev * 6)
        w.add(pts, "site_issues", f"{len(findings)} website issue(s), severity {sev}", n=len(findings), sev=sev)
        crit = [f["code"] if "code" in f else f["title"] for f in findings if f["severity"] >= 3]
        if crit:
            titles = [f["title"] for f in findings if f["severity"] >= 3]
            w.add(10, "critical", f"critical: {', '.join(titles[:3])}", codes=",".join(crit[:3]))
        if not findings:
            w.add(0, "site_healthy", "website looks healthy")
    else:
        w.add(10, "not_audited", "has website (not audited yet; run with --audit)")
    if lead.extra.get("email"):
        w.add(15, "public_email", "public email")
    elif lead.extra.get("phone"):
        w.add(10, "public_phone", "public phone")
    else:
        w.add(0, "no_contact", "no public contact found")
    return w.finish(lead)


def score(lead: Lead, cfg, now: float) -> Lead:
    if lead.kind == "business":
        return score_business(lead, cfg, now)
    return score_intent_lead(lead, cfg, now)
