"""Reply detection (Pro): find answers from leads you wrote to, and move those leads to Replied.

It uses the email account you connected for sending (the same app password) over IMAP with TLS, and opens the
inbox read-only: it only searches by sender and date. It never downloads, marks, moves or deletes a message,
and nothing leaves your computer except the login to your own mail server.
"""
from __future__ import annotations

import imaplib
import re
import ssl
import time

from .send import SendError, clean_host

EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
IMAP_HOSTS = {"smtp.gmail.com": "imap.gmail.com", "smtp-mail.outlook.com": "outlook.office365.com",
              "smtp.office365.com": "outlook.office365.com"}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
LOOK_BACK_DAYS = 60


def imap_host(settings: dict, cloud: bool = False) -> str:
    """The IMAP server for an SMTP account: known providers, else smtp.example.com -> imap.example.com."""
    host = IMAP_HOSTS.get(settings.get("host", "")) or re.sub(r"^(smtp|mail)\.", "imap.", settings.get("host", ""))
    return host if host in ("127.0.0.1", "localhost") and not cloud else clean_host(host, cloud)


def imap_date(ts: float) -> str:
    t = time.gmtime(ts)  # IMAP wants English month names whatever the computer's language
    return f"{t.tm_mday:02d}-{MONTHS[t.tm_mon - 1]}-{t.tm_year}"


def candidates(store, now: float | None = None, days: int = LOOK_BACK_DAYS) -> list[tuple[int, list[str], float]]:
    """(lead id, email addresses, when you first wrote) for contacted leads with a public email address."""
    now = now or time.time()
    out = []
    for lead in store.query(status="contacted", limit=500):
        addrs = EMAIL_RX.findall(lead.contact or "")
        first = store.outreach(lead.id)["contacted_at"]
        if addrs and first and first > now - days * 86400:
            out.append((lead.id, addrs[:3], first))
    return out


def find(settings: dict, items: list, cloud: bool = False, imap_factory=None) -> list[int]:
    """Ids of the leads in `items` that have a message from them in the inbox since you wrote."""
    if not items:
        return []
    host = imap_host(settings, cloud)
    try:
        conn = (imap_factory or (lambda h: imaplib.IMAP4_SSL(h, 993, ssl_context=ssl.create_default_context(), timeout=20)))(host)
    except (OSError, imaplib.IMAP4.error) as e:
        raise SendError(f"Could not reach your mail server ({host}): {e}", 502)
    found = []
    try:
        try:
            conn.login(settings["address"], settings["password"])
        except imaplib.IMAP4.error:
            raise SendError("Your mail server refused the login. Reconnect your email account with an app password.", 502)
        typ, _ = conn.select("INBOX", readonly=True)
        if typ != "OK":
            raise SendError("Could not open your inbox.", 502)
        for lead_id, addrs, since in items:
            for addr in addrs:  # the address came from EMAIL_RX: no quotes or spaces to escape
                typ, data = conn.search(None, "FROM", f'"{addr}"', "SINCE", imap_date(since))
                if typ == "OK" and data and data[0] and data[0].split():
                    found.append(lead_id)
                    break
    except (OSError, imaplib.IMAP4.error) as e:
        raise SendError(f"The mail server stopped answering: {e}", 502)
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return found


def apply(store, ids: list[int]) -> int:
    """Move leads that answered to Replied (only if they are still Contacted) and record it."""
    n = 0
    for lead_id in ids:
        lead = store.get(lead_id)
        if lead and lead.status == "contacted":
            store.update(lead_id, status="replied")
            store.log(lead_id, "replied", "email")
            n += 1
    return n


def check(accounts, store, lock, cloud: bool = False, imap_factory=None) -> dict:
    """The whole check. `lock` guards the shared store; the mail server is asked without holding it."""
    settings = accounts.get("email")
    if not settings:
        raise SendError("Connect your email account in Accounts first: replies are found in that inbox.")
    with lock:
        items = candidates(store)
    ids = find(settings, items, cloud, imap_factory)
    with lock:
        moved = apply(store, ids)
    return {"checked": len(items), "replied": moved}
