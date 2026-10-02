"""Text helpers: HTML stripping, contact extraction, budget parsing."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

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


@dataclass
class Budget:
    low: float
    high: float
    hourly: bool
    text: str


MULT = {"k": 1_000, "m": 1_000_000}
CUR = r"(?:\$|usd|€|eur|£|gbp|₾|gel)"
NUM = r"(\d{1,3}(?:[,.]\d{3})+|\d+(?:\.\d+)?)\s*([kKmM])?(?![\w])"
RANGE_RX = re.compile(
    rf"(?:{CUR}\s*){NUM}\s*(?:{CUR})?\s*(?:-|–|to)\s*(?:{CUR}\s*)?{NUM}\s*(?:{CUR})?(\s*(?:/|per|an?)\s*(?:h|hr|hour))?",
    re.I)
SINGLE_RX = re.compile(
    rf"(?:{CUR}\s*{NUM}|{NUM}\s*{CUR})(\s*(?:/|per|an?)\s*(?:h|hr|hour))?", re.I)
LABELLED_RX = re.compile(rf"\b(?:budget|pay(?:ing)?|rate|compensation)\b\s*(?:is|of|:)?\s*(?:{CUR}\s*)?{NUM}", re.I)


def _num(raw: str, mult: str | None) -> float:
    raw = raw.replace(",", "") if re.fullmatch(r"\d{1,3}(?:,\d{3})+", raw) else raw
    raw = raw.replace(".", "") if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw) else raw
    return float(raw) * MULT.get((mult or "").lower(), 1)


def parse_budget(text: str) -> Budget | None:
    """Find the first money amount. Returns None if no explicit amount."""
    text = text or ""
    m = RANGE_RX.search(text)
    if m:
        # "$100-150k": the low end shares the high end's multiplier
        lo_mult = m.group(2) or (m.group(4) if m.group(4) else None)
        lo, hi = _num(m.group(1), lo_mult), _num(m.group(3), m.group(4))
        return Budget(min(lo, hi), max(lo, hi), bool(m.group(5)), m.group(0).strip())
    m = SINGLE_RX.search(text)
    if m:
        raw, mult = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        v = _num(raw, mult)
        return Budget(v, v, bool(m.group(5)), m.group(0).strip())
    m = LABELLED_RX.search(text)
    if m:
        v = _num(m.group(1), m.group(2))
        after = text[m.end():m.end() + 12].lower()
        hourly = bool(re.match(r"\s*(?:/|per|an?)\s*(?:h|hr|hour)", after))
        return Budget(v, v, hourly, m.group(0).strip())
    return None


def word_hit(phrase: str, text_lower: str) -> bool:
    """Whole-word match so 'go' does not match 'google' and 'c++' still works."""
    p = re.escape(phrase.lower())
    return re.search(rf"(?<![\w]){p}(?![\w])", text_lower) is not None
