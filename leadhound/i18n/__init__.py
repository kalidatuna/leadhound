"""Translations for message drafts, website findings and score reasons.

One module per language (en.py, es.py, ...), each a dict M of key -> text with {placeholders}.
Missing keys fall back to English, so a partial translation never breaks anything.
Translations were machine-assisted; corrections are welcome as pull requests.
"""
from __future__ import annotations

import importlib

from ..langs import LANGUAGES

_cache: dict[str, dict] = {}


def catalog(lang: str) -> dict:
    lang = lang if lang in LANGUAGES else "en"
    if lang not in _cache:
        _cache[lang] = importlib.import_module(f".{lang}", __name__).M
    return _cache[lang]


def msg(lang: str, key: str, **kw) -> str:
    text = catalog(lang).get(key) or catalog("en").get(key) or key
    try:
        return text.format(**kw)
    except (KeyError, IndexError, ValueError):
        return catalog("en").get(key, key).format(**kw)


def merged(lang: str) -> dict:
    """English with the language's keys on top: what the app downloads."""
    return {**catalog("en"), **catalog(lang)}
