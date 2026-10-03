"""Email through the user's own mail account (SMTP with an app password)."""
from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage

from . import SendError, clean_host

PRESETS = {"gmail": ("smtp.gmail.com", 587), "outlook": ("smtp-mail.outlook.com", 587)}
ADDRESS_RX = re.compile(r"^[^\s@<>\",;]+@[^\s@<>\",;]+\.[^\s@<>\",;]+$")
LOOPBACK = ("127.0.0.1", "localhost", "::1")


def settings(f: dict, cloud: bool) -> dict:
    """Validate the connect form and return the full SMTP settings."""
    address = str(f.get("address", "")).strip()
    if not ADDRESS_RX.match(address):
        raise SendError("Enter a valid email address.")
    password = str(f.get("password", ""))
    provider = str(f.get("provider", "other")).lower()
    if provider in PRESETS:
        host, port = PRESETS[provider]
        password = password.replace(" ", "")  # Google shows app passwords in groups of four
    else:
        host = str(f.get("host", "")).strip().lower()
        if host not in LOOPBACK or cloud:
            host = clean_host(host, cloud)
        try:
            port = int(f.get("port") or 587)
        except (TypeError, ValueError):
            raise SendError("The port must be a number.")
        if not 1 <= port <= 65535:
            raise SendError("The port must be between 1 and 65535.")
    if len(password) < 8:
        raise SendError("The app password is at least 8 characters.")
    return {"provider": provider, "address": address, "password": password, "host": host, "port": port}


def _connect(s: dict) -> smtplib.SMTP:
    ctx = ssl.create_default_context()
    try:
        smtp = smtplib.SMTP_SSL(s["host"], s["port"], timeout=20, context=ctx) if s["port"] == 465 \
            else smtplib.SMTP(s["host"], s["port"], timeout=20)
        smtp.ehlo()
        if s["port"] != 465:
            if smtp.has_extn("starttls"):
                smtp.starttls(context=ctx)
                smtp.ehlo()
            elif s["host"] not in LOOPBACK:  # never send a password over a plain connection
                smtp.close()
                raise SendError("This mail server does not offer an encrypted connection.")
        smtp.login(s["address"], s["password"])
        return smtp
    except smtplib.SMTPAuthenticationError:
        raise SendError("The mail server refused that password. Use an app password, not your normal one.")
    except (smtplib.SMTPException, OSError) as e:
        raise SendError(f"Could not connect to the mail server: {e}")


def _send(s: dict, to: str, subject: str, body: str) -> None:
    msg = EmailMessage()  # refuses line breaks inside headers, so a subject can never inject one
    msg["From"], msg["To"], msg["Subject"] = s["address"], to, " ".join(subject.split())[:200] or "Hello"
    msg.set_content(body)
    smtp = _connect(s)
    try:
        smtp.send_message(msg)
    except smtplib.SMTPException as e:
        raise SendError(f"The mail server did not accept the message: {e}")
    finally:
        try:
            smtp.quit()
        except Exception:
            pass


def verify(s: dict) -> str:
    """Log in and send a test email to the user. Returns the account name."""
    _send(s, s["address"], "leadhound is connected", "This test message confirms leadhound can send from this address.")
    return s["address"]


def send(secrets: dict, to: str, subject: str, body: str) -> None:
    if not ADDRESS_RX.match(to):
        raise SendError("The lead's email address looks wrong.")
    _send(secrets, to, subject, body)
