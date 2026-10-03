"""Turn a lead into the ways you can reach it, connect accounts, and send.

The browser never chooses a recipient. It names a channel and the address it was shown; the server checks
that against the stored lead, so a stolen page token cannot use your account to message anyone else.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from . import accounts as acc
from .models import Lead
from .send import SendError, github, mail, mastodon, reddit

EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RX = re.compile(r"^\+?[\d\s().-]{7,22}$")
MIN_GAP = 15.0     # seconds between two sends from the same account
SAME_LEAD_GAP = 60.0  # seconds before the same lead can be sent to again through the same channel
SAFE_URL = re.compile(r"^https?://", re.I)


def channels_for(lead: Lead, public: dict) -> list[dict]:
    """Every way to reach this lead. mode 'send' = through a connected account, 'link' = open it yourself."""
    out, seen = [], set()

    def add(pid, to, **kw):
        info = public.get(pid, {})
        if (pid, to) in seen:
            return
        seen.add((pid, to))
        out.append({"id": pid, "to": to, "mode": info.get("mode", "link"), "ready": bool(info.get("ready")), **kw})

    url = lead.url if SAFE_URL.match(lead.url or "") else ""
    for part in (p.strip() for p in (lead.contact or "").split(",") if p.strip()):
        if EMAIL_RX.fullmatch(part):
            q = quote(part, safe="@")
            add("gmail", part, link="https://mail.google.com/mail/?view=cm&fs=1&to=" + q)
            add("outlook", part, link="https://outlook.live.com/mail/0/deeplink/compose?to=" + q)
            add("email", part, link="mailto:" + q)
        elif part.startswith("reddit DM: u/"):
            user = part.split("u/", 1)[1]
            add("reddit", "u/" + user, link="https://www.reddit.com/message/compose/?to=" + quote(user, safe=""))
        elif part.startswith("Mastodon: @"):
            add("mastodon", part.split(": ", 1)[1], link=url)
        elif part.startswith("Telegram: @"):
            handle = part.split("@", 1)[1]
            add("telegram", "@" + handle, link="https://t.me/" + quote(handle, safe=""), copy=True)
        elif PHONE_RX.match(part):
            digits = re.sub(r"\D", "", part)
            if len(digits) >= 7:
                add("whatsapp", part, link="https://wa.me/" + digits, text_param="text")
    if lead.source == "github" and github.ISSUE_RX.match(lead.url or ""):
        add("github", lead.url.split("github.com/", 1)[1], link=url)
    if lead.source == "freelancer" and url:
        add("freelancer", "Bid on Freelancer.com", link=url, copy=True)
    if not out and url:
        add("page", re.sub(r"^https?://", "", url).split("/")[0], link=url, mode="link", ready=True, copy=True)
    return out[:8]


def connect(accounts: acc.Accounts, pid: str, fields: dict, cloud: bool) -> str:
    """Check the details work, then save them. Returns the account name to show."""
    spec = acc.PLATFORMS.get(pid)
    if not spec or spec["mode"] != "send":
        raise SendError("This platform has nothing to connect.")
    if not isinstance(fields, dict):
        raise SendError("Missing details.")
    if pid == "email":
        s = mail.settings(fields, cloud)
        who = mail.verify(s)
    elif pid == "mastodon":
        s, who = mastodon.verify(fields, cloud)
    elif pid == "github":
        s, who = github.verify(fields)
    else:
        s, who = reddit.verify(fields)
    accounts.connect(pid, {**s, "as": who})
    return who


def send_lead(accounts: acc.Accounts, lead: Lead, pid: str, to: str, subject: str, body: str) -> dict:
    """Send `body` to the lead through a connected account. Raises SendError with a user-facing message."""
    chans = channels_for(lead, accounts.public())
    ch = next((c for c in chans if c["id"] == pid and c["to"] == to), None)
    if not ch or ch["mode"] != "send":
        raise SendError("That channel is not available for this lead.")
    secrets = accounts.get(pid)
    if not secrets:
        raise SendError("Connect this account first.")
    if not isinstance(body, str) or not body.strip() or len(body) > 10000:
        raise SendError("Write a message first (under 10000 characters).")
    subject = " ".join(str(subject or "").split())[:200]
    cap = acc.PLATFORMS[pid]["cap"]
    if accounts.used_today(pid) >= cap:
        raise SendError(f"Daily limit reached: {cap} messages a day from this account. Try again tomorrow.", 429)
    if acc.too_soon(("lead", lead.id, pid, to), SAME_LEAD_GAP):
        raise SendError("You just sent this. Give it a minute.", 429)
    if acc.too_soon(("acct", pid), MIN_GAP):
        raise SendError("Sending too fast. Wait a few seconds between messages.", 429)
    try:
        if pid == "email":
            mail.send(secrets, to, subject or lead.title, body)
        elif pid == "mastodon":
            mastodon.send(secrets, to, body)
        elif pid == "github":
            github.send(secrets, lead.url, body)
        else:
            reddit.send(secrets, to, subject or lead.title, body)
    except SendError:
        acc._last.pop(("lead", lead.id, pid, to), None)  # a failed send may be retried straight away
        acc._last.pop(("acct", pid), None)
        raise
    used = accounts.bump(pid)
    return {"via": pid, "as": secrets.get("as", ""), "used": used, "cap": cap}
