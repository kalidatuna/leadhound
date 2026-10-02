"""First-message drafts built from the lead's own evidence. You review and send them yourself."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from . import llm
from .models import Lead
from .net import FetchError
from .textutil import word_hit

SOURCE_LABEL = {"reddit": "Reddit", "hn": "Hacker News", "github": "GitHub", "rss": "the job board"}

SYSTEM = ("You write short, specific first-contact messages for a freelancer. Rules: under 120 words; "
          "plain, friendly, no hype or flattery; mention only facts given in the lead evidence; never "
          "invent past clients, numbers or results; end with one concrete question; no subject line "
          "unless the lead is a business; output only the message.")


def _first_name(author: str) -> str:
    a = (author or "").removeprefix("u/").strip()
    if not a or a.lower() in ("[deleted]", "deleted"):
        return "there"
    return a


def _sentence(s: str) -> str:
    s = s.strip()
    return s if s.endswith((".", "!", "?")) else s + "."


def _question(lead: Lead) -> str:
    low = lead.text.lower()
    if not lead.budget:
        return "What budget and timeline do you have in mind?"
    if not re.search(r"\b(deadline|by (monday|tuesday|wednesday|thursday|friday|the end)|asap|urgent|weeks?|days?)\b", low):
        return "When do you need this live?"
    return "Is there an existing codebase or design I should look at first?"


def template_post(lead: Lead, cfg) -> str:
    skills = [s for s in cfg.skills if word_hit(s, lead.text.lower())][:3]
    skill_line = f"I work with {', '.join(skills)} day to day" if skills else "This is the kind of work I do"
    where = SOURCE_LABEL.get(lead.source, lead.source)
    title = re.sub(r"^\[[^\]]*\]\s*", "", lead.title).strip()  # drop [Hiring] / [repo] prefixes
    lines = [f"Hi {_first_name(lead.author)},", "",
             f"I saw your post on {where}: \"{title[:90]}\". {skill_line}. {_sentence(cfg.pitch)}"]
    if lead.source == "github":
        lines[-1] = (f"I saw \"{title[:90]}\" is open and unassigned. {skill_line}. "
                     f"I'd like to take it on: I'll comment my approach here before opening a PR.")
    if cfg.portfolio:
        lines.append(f"Recent work: {cfg.portfolio}")
    lines += ["", _question(lead), "", cfg.signature or cfg.name]
    return "\n".join(lines)


def template_business(lead: Lead, cfg) -> str:
    name = lead.title
    website = lead.extra.get("website", "")
    category = (lead.extra.get("category") or "business").replace("_", " ")
    city = lead.extra.get("city") or ""
    if not website:
        where = f" in {city}" if city else " nearby"
        body = [f"Subject: A website for {name}", "", f"Hi {name} team,", "",
                f"I was looking for a {category}{where} and found {name} on the map, but I couldn't find a website.",
                "People who search on Google can't see your hours, prices or photos, or contact you online,"
                " so many go to a competitor that has a site.",
                "", f"{_sentence(cfg.pitch)} I can set up a simple, fast site with your info"
                + (" and online booking" if lead.extra.get("booking_relevant") else "") + " at a fixed price."]
    else:
        domain = urlparse(website).netloc or website
        findings = (lead.extra.get("audit") or {}).get("findings", [])[:3]
        body = [f"Subject: Quick note about {domain}", "", f"Hi {name} team,", ""]
        if findings:
            body += [f"I was looking at {domain} and noticed a few things that are likely costing you customers:",
                     "\n".join(f"- {f['pitch']}" for f in findings), "",
                     f"{_sentence(cfg.pitch)} These are usually quick fixes."]
        else:  # healthy or unaudited site: no invented problems
            body += [f"I came across {domain}. {_sentence(cfg.pitch)}",
                     "If you're planning updates (speed, online booking, search ranking), I'd be glad to help."]
            body += ["", "Would a short call this week be useful?", "", cfg.signature or cfg.name]
            return "\n".join(body)
    body += ["Would it help if I sent a short free report with screenshots?", "", cfg.signature or cfg.name]
    return "\n".join(body)


def llm_prompt(lead: Lead, cfg) -> str:
    evidence = lead.body[:2500]
    if lead.kind == "business":
        findings = (lead.extra.get("audit") or {}).get("findings", [])
        evidence = "\n".join(f"- {f['title']}: {f['pitch']}" for f in findings) or "No website listed."
    return (f"About me: {cfg.name}. {cfg.pitch}. Skills: {', '.join(cfg.skills)}. "
            f"Portfolio: {cfg.portfolio or 'none'}. Sign as: {cfg.signature or cfg.name}.\n\n"
            f"Lead type: {lead.kind} from {lead.source}\nName/author: {lead.author or lead.title}\n"
            f"Title: {lead.title}\nCategory: {lead.extra.get('category', '')}\n"
            f"Budget: {lead.budget or 'not stated'}\nEvidence:\n{evidence}\n\n"
            "Write the first message.")


def make_draft(lead: Lead, cfg, use_llm: bool = False, fetcher=None) -> tuple[str, str]:
    """Return (draft, engine). Falls back to the template when the LLM fails."""
    template = template_business(lead, cfg) if lead.kind == "business" else template_post(lead, cfg)
    if not use_llm or cfg.llm_provider == "none":
        return template, "template"
    try:
        text = llm.complete(cfg, SYSTEM, llm_prompt(lead, cfg), fetcher=fetcher)
        return (text or template), (cfg.llm_provider if text else "template")
    except (llm.LLMError, FetchError, KeyError, ValueError) as e:
        return template, f"template (LLM failed: {str(e)[:120]})"
