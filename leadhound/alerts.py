"""What happens after an automatic search (Pro): check for replies, then email yourself the best new matches.

The digest goes from your connected email account to that same address, so nothing new is set up and no
third party sees it. It lists at most 10 leads with their score and link. It is only sent when there is
something above your minimum score, so a quiet search sends nothing.
"""
from __future__ import annotations

from . import config, replies
from .i18n import msg
from .send import SendError, mail

MAX_ITEMS = 10


def digest(cfg, leads: list) -> tuple[str, str]:
    """(subject, body) for the new matches, in your message language (English when that is automatic)."""
    lang = cfg.draft_language if cfg.draft_language != "auto" else "en"
    lines = [msg(lang, "al.intro", n=len(leads), min=cfg.alert_min_score), ""]
    for l in leads[:MAX_ITEMS]:
        lines += [f"[{l.score}] {l.title}", f"    {l.budget + ' · ' if l.budget else ''}{l.url}", ""]
    lines.append(msg(lang, "al.footer"))
    return msg(lang, "al.subject", n=len(leads)), "\n".join(lines)


def new_matches(store, cfg, since: float) -> list:
    return [l for l in store.query(status="new", min_score=cfg.alert_min_score, limit=200, sort="score")
            if l.first_seen >= since]


def after_auto_search(ctx, job, send=mail._send, imap_factory=None) -> dict:
    """Run by the job manager when an automatic search ends. Never raises: a failed alert must not break searching."""
    out = {"replied": 0, "emailed": 0}
    if not job.auto or job.status != "done" or not ctx.license.is_pro():
        return out
    acct = ctx.accounts.get("email")
    if not acct:
        return out
    try:
        out["replied"] = replies.check(ctx.accounts, ctx.store, ctx.lock, bool(ctx.auth), imap_factory)["replied"]
    except SendError as e:
        job.add(f"reply check: {e}")
    cfg = config.load(ctx.config_path)
    if not cfg.alert_email:
        return out
    with ctx.lock:
        leads = new_matches(ctx.store, cfg, job.started)
    if not leads:
        return out
    subject, body = digest(cfg, leads)
    try:
        send(acct, acct["address"], subject, body)
        out["emailed"] = min(len(leads), MAX_ITEMS)
        job.add(f"emailed you {out['emailed']} new matches")
    except SendError as e:
        job.add(f"alert email failed: {e}")
    return out
