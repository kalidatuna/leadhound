"""Text helpers: HTML stripping, contact extraction, whole-word matching. Budgets live in money.py."""
from __future__ import annotations

import html
import re

from .money import Budget, parse_budget  # noqa: F401  (re-exported for older imports)

# Text from posts and websites is untrusted. Every pattern below is bounded so that a page made of
# "<<<<<" or "a.a.a.a." cannot make a search run for hours (quadratic backtracking).
MAX_TEXT = 100_000
TAG_RX = re.compile(r"<[^>]{1,600}>")
BLOCK_RX = re.compile(r"<\s*(?:br|/p|p|/div|li|/li)\b[^>]{0,600}>", re.I)
EMAIL_RX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# "name [at] domain [dot] com" obfuscation, common in HN posts
OBF_EMAIL_RX = re.compile(r"\b([A-Za-z0-9._%+-]+)\s*[\[(]\s*at\s*[\])]\s*([A-Za-z0-9-]+)\s*[\[(]\s*dot\s*[\])]\s*([A-Za-z]{2,})\b", re.I)
OBF_MARK_RX = re.compile(r"[\[(]\s*at\s*[\])]", re.I)
_LOCAL_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._%+-")
_DOMAIN_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-")


def strip_html(s: str) -> str:
    s = BLOCK_RX.sub("\n", (s or "")[:MAX_TEXT])
    s = html.unescape(TAG_RX.sub("", s))
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


def _email_windows(text: str):
    """The short stretch of text around each '@' (an address is at most 64 + 1 + 255 characters)."""
    i = text.find("@")
    while i != -1:
        a = i
        while a > 0 and i - a < 64 and text[a - 1] in _LOCAL_CHARS:
            a -= 1
        b = i + 1
        while b < len(text) and b - i <= 255 and text[b] in _DOMAIN_CHARS:
            b += 1
        yield text[a:b]
        i = text.find("@", i + 1)


def find_emails(text: str) -> list[str]:
    text = (text or "")[:MAX_TEXT]
    found = [e for w in _email_windows(text) for e in EMAIL_RX.findall(w)]
    for m in OBF_MARK_RX.finditer(text):
        found += [f"{a}@{b}.{c}" for a, b, c in OBF_EMAIL_RX.findall(text[max(0, m.start() - 70):m.end() + 120])]
    out = []
    for e in found:
        e = e.strip(".").lower()
        if e not in out and not e.endswith((".png", ".jpg", ".gif", ".svg", ".webp")):
            out.append(e)
    return out


def csv_cell(v):
    """A value for a CSV file. Text that starts with = + - @ gets a leading ' so Excel and Sheets never run it as a formula."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") and s else v


def word_hit(phrase: str, text_lower: str) -> bool:
    """Whole-word match so 'go' does not match 'google' and 'c++' still works."""
    p = re.escape(phrase.lower())
    return re.search(rf"(?<![\w]){p}(?![\w])", text_lower) is not None
