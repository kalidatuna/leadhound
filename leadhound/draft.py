"""First-message drafts built from the lead's own evidence, in the lead's language. You send them yourself.

Language: your setting, or "auto" = the business website's language, then its country, else English.
In English drafts your own pitch is used; in other languages a translated sentence for your profession
replaces it, so a message never mixes two languages.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from . import llm
from .i18n import msg
from .langs import LANGUAGES, language_for
from .models import Lead
from .net import FetchError
from .textutil import word_hit

SOURCE_LABEL = {"reddit": "Reddit", "hn": "Hacker News", "github": "GitHub", "rss": "the job board",
                "freelancer": "Freelancer.com", "mastodon": "Mastodon"}
WEB_WORK = {"", "developer", "designer", "marketer", "writer"}  # professions that fix websites
DEADLINE_RX = re.compile(r"\b(deadline|by (monday|tuesday|wednesday|thursday|friday|the end)|asap|urgent|weeks?|days?)\b|"
                         r"urgente|plazo|prazo|délai|frist|срочно|срок", re.I)

SYSTEM = ("You write short, specific first-contact messages for a freelancer. Rules: under 120 words; "
          "plain, friendly, no hype or flattery; mention only facts given in the lead evidence; never "
          "invent past clients, numbers or results; end with one concrete question; no subject line "
          "unless the lead is a business; output only the message.")


def draft_language(lead: Lead, cfg) -> str:
    if cfg.draft_language and cfg.draft_language != "auto":
        return cfg.draft_language
    if lead.kind == "business":
        audit = lead.extra.get("audit") or {}
        return language_for(audit.get("lang", ""), lead.extra.get("country", ""), "en")
    lang = (lead.extra.get("language") or "").split("-")[0] if lead.source == "mastodon" else ""
    return lang if lang in LANGUAGES else "en"


def _sentence(s: str) -> str:
    s = s.strip()
    return s if not s or s.endswith((".", "!", "?", "。", "।")) else s + "."


def _offer(cfg, lang: str) -> str:
    if lang == "en" and cfg.pitch:
        return _sentence(cfg.pitch)
    return msg(lang, f"o.{cfg.profession}") if cfg.profession else msg(lang, "o.generic")


def _name(author: str) -> str:
    a = (author or "").removeprefix("u/").strip()
    return "" if a.lower() in ("", "[deleted]", "deleted") else a


def template_post(lead: Lead, cfg, lang: str = "en") -> str:
    skills = [s for s in cfg.skills if word_hit(s, lead.text.lower())][:3]
    skill_line = msg(lang, "p.skills", skills=", ".join(skills)) if skills else msg(lang, "p.generic")
    title = re.sub(r"^\[[^\]]*\]\s*", "", lead.title).strip()[:90]  # drop [Hiring] / [repo] prefixes
    name = _name(lead.author)
    lines = [msg(lang, "p.hi", name=name) if name else msg(lang, "p.hi_anon"), ""]
    if lead.source == "github":
        lines.append(f"{msg(lang, 'p.github', title=title)} {skill_line}")
    else:
        where = SOURCE_LABEL.get(lead.source, lead.source)
        lines.append(f"{msg(lang, 'p.saw', where=where, title=title)} {skill_line} {_offer(cfg, lang)}")
    if cfg.portfolio:
        lines.append(msg(lang, "p.recent", portfolio=cfg.portfolio))
    if not lead.budget:
        q = "p.q_budget"
    elif not DEADLINE_RX.search(lead.text):
        q = "p.q_deadline"
    else:
        q = "p.q_files"
    lines += ["", msg(lang, q), "", cfg.signature or cfg.name]
    return "\n".join(lines)


def _finding_line(f: dict, lang: str) -> str:
    code = f.get("code", "")
    text = msg(lang, f"f.{code}", **(f.get("args") or {})) if code else ""
    return "- " + (text if text and text != f"f.{code}" else f.get("pitch", ""))


def template_business(lead: Lead, cfg, lang: str = "en") -> str:
    name = lead.title
    website = lead.extra.get("website", "")
    domain = (urlparse(website).netloc or website).removeprefix("www.")
    audit = lead.extra.get("audit") or {}
    findings = [] if audit.get("blocked") else audit.get("findings", [])[:3]
    web = cfg.profession in WEB_WORK
    subject = lambda key, **kw: f"{msg(lang, 'b.subject')}: {msg(lang, key, **kw)}"  # noqa: E731
    hello = msg(lang, "b.hello", name=name)
    if not website and web:
        offer_key = "b.nosite_offer_booking" if lead.extra.get("booking_relevant") else "b.nosite_offer"
        body = [subject("b.subj_nosite", name=name), "", hello, "",
                f"{msg(lang, 'b.nosite_found', name=name)} {msg(lang, 'b.nosite_why')}", "",
                f"{_offer(cfg, lang)} {msg(lang, offer_key)}", msg(lang, "b.ask_call")]
    elif findings and web:
        body = [subject("b.subj_site", domain=domain), "", hello, "", msg(lang, "b.site_intro", domain=domain),
                "\n".join(_finding_line(f, lang) for f in findings), "",
                f"{_offer(cfg, lang)} {msg(lang, 'b.quick_fixes')}", msg(lang, "b.ask_report")]
    else:  # healthy site, blocked check, or work that is not about websites: no invented problems
        intro = msg(lang, "b.healthy_intro", domain=domain) if website else msg(lang, "b.generic_intro", name=name)
        extra = f" {msg(lang, 'b.healthy_offer')}" if web else ""
        body = [subject("b.subj_generic", name=name), "", hello, "", f"{intro} {_offer(cfg, lang)}{extra}", "",
                msg(lang, "b.ask_call")]
    body += ["", cfg.signature or cfg.name]
    return "\n".join(body)


def llm_prompt(lead: Lead, cfg, lang: str) -> str:
    evidence = lead.body[:2500]
    if lead.kind == "business":
        findings = (lead.extra.get("audit") or {}).get("findings", [])
        evidence = "\n".join(f"- {f['title']}: {f['pitch']}" for f in findings) or "No website listed."
    return (f"About me: {cfg.name}. {cfg.pitch}. Skills: {', '.join(cfg.skills)}. "
            f"Portfolio: {cfg.portfolio or 'none'}. Sign as: {cfg.signature or cfg.name}.\n\n"
            f"Lead type: {lead.kind} from {lead.source}\nName/author: {lead.author or lead.title}\n"
            f"Title: {lead.title}\nCategory: {lead.extra.get('category', '')}\n"
            f"Budget: {lead.budget or 'not stated'}\nEvidence:\n{evidence}\n\n"
            f"Write the first message in {LANGUAGES.get(lang, 'English')} ({lang}).")


def make_draft(lead: Lead, cfg, use_llm: bool = False, fetcher=None) -> tuple[str, str]:
    """Return (draft, engine). Falls back to the template when the LLM fails."""
    lang = draft_language(lead, cfg)
    template = template_business(lead, cfg, lang) if lead.kind == "business" else template_post(lead, cfg, lang)
    if not use_llm or cfg.llm_provider == "none":
        return template, "template"
    try:
        text = llm.complete(cfg, SYSTEM, llm_prompt(lead, cfg, lang), fetcher=fetcher)
        return (text or template), (cfg.llm_provider if text else "template")
    except (llm.LLMError, FetchError, KeyError, ValueError) as e:
        return template, f"template (LLM failed: {str(e)[:120]})"
