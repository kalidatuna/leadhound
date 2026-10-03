"""Text helpers: HTML stripping, contact extraction, whole-word matching. Budgets live in money.py."""
from __future__ import annotations

import html
import re

from .money import Budget, parse_budget  # noqa: F401  (re-exported for older imports)

TAG_RX = re.compile(r"<[^>]+>")
BLOCK_RX = re.compile(r"<\s*(?:br|/p|p|/div|li|/li)\b[^>]*>", re.I)
EMAIL_RX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# "name [at] domain [dot] com" obfuscation, common in HN posts
OBF_EMAIL_RX = re.compile(r"\b([A-Za-z0-9._%+-]+)\s*[\[(]\s*at\s*[\])]\s*([A-Za-z0-9-]+)\s*[\[(]\s*dot\s*[\])]\s*([A-Za-z]{2,})\b", re.I)


def strip_html(s: str) -> str:
    s = BLOCK_RX.sub("\n", s or "")
    s = html.unescape(TAG_RX.sub("", s))
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


def find_emails(text: str) -> list[str]:
    found = EMAIL_RX.findall(text or "")
    found += [f"{a}@{b}.{c}" for a, b, c in OBF_EMAIL_RX.findall(text or "")]
    out = []
    for e in found:
        e = e.strip(".").lower()
        if e not in out and not e.endswith((".png", ".jpg", ".gif", ".svg", ".webp")):
            out.append(e)
    return out


def word_hit(phrase: str, text_lower: str) -> bool:
    """Whole-word match so 'go' does not match 'google' and 'c++' still works."""
    p = re.escape(phrase.lower())
    return re.search(rf"(?<![\w]){p}(?![\w])", text_lower) is not None
