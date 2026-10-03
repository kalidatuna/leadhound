"""Config: dataclass, INI load/save (stdlib configparser, works on Python 3.10), and API validation.

API keys never live in the config file. They come from environment variables.
"""
from __future__ import annotations

import configparser
import os
import re
from dataclasses import dataclass, field, fields

from .langs import LANGUAGES
from .money import CURRENCIES

DEFAULT_PATH = "leadhound.ini"
LLM_PROVIDERS = ("none", "anthropic", "openai")
AUTO_SCAN_HOURS = (0, 6, 12, 24)

# (section, key, kind). kind: str | list | lines | bool | float | int
SCHEMA = [
    ("profile", "name", "str"), ("profile", "profession", "str"), ("profile", "pitch", "str"),
    ("profile", "skills", "list"), ("profile", "avoid", "list"), ("profile", "portfolio", "str"),
    ("profile", "currency", "str"), ("profile", "min_budget", "float"), ("profile", "min_rate", "float"),
    ("profile", "signature", "str"), ("profile", "draft_language", "str"),
    ("sources", "freelancer", "bool"), ("sources", "freelancer_categories", "list"),
    ("sources", "reddit_subreddits", "list"), ("sources", "hn", "bool"), ("sources", "github", "bool"),
    ("sources", "github_labels", "list"), ("sources", "github_languages", "list"),
    ("sources", "mastodon", "bool"), ("sources", "mastodon_instances", "list"), ("sources", "mastodon_tags", "list"),
    ("sources", "rss_feeds", "lines"), ("sources", "max_age_days", "int"), ("sources", "auto_scan_hours", "int"),
    ("local", "categories", "list"), ("local", "radius_m", "int"), ("local", "max_businesses", "int"),
    ("llm", "llm_provider", "str"), ("llm", "llm_model", "str"), ("llm", "llm_base_url", "str"),
]
INI_KEY = {"llm_provider": "provider", "llm_model": "model", "llm_base_url": "base_url"}


@dataclass
class Config:
    name: str = ""
    profession: str = ""
    pitch: str = "I build fast, reliable websites and web apps for small businesses"
    skills: list = field(default_factory=lambda: ["python", "javascript", "wordpress"])
    avoid: list = field(default_factory=lambda: ["unpaid", "equity only", "rev share", "for exposure"])
    portfolio: str = ""
    currency: str = "USD"
    min_budget: float = 0
    min_rate: float = 0
    signature: str = ""
    draft_language: str = "auto"  # auto = the lead's language (website, then country), else a language code
    freelancer: bool = True
    freelancer_categories: list = field(default_factory=lambda: ["Website-Design", "WordPress", "PHP", "Python"])
    reddit_subreddits: list = field(default_factory=lambda: ["forhire", "jobbit", "hiring"])
    hn: bool = True
    github: bool = True
    github_labels: list = field(default_factory=lambda: ["bounty", "help wanted"])
    github_languages: list = field(default_factory=list)
    mastodon: bool = False  # opt-in: worldwide but low volume and noisy
    mastodon_instances: list = field(default_factory=lambda: ["mastodon.social"])
    mastodon_tags: list = field(default_factory=lambda: ["FediHire", "hiring", "freelance"])
    rss_feeds: list = field(default_factory=list)
    max_age_days: int = 21
    auto_scan_hours: int = 0
    categories: list = field(default_factory=lambda: ["restaurant", "dentist"])
    radius_m: int = 3000
    max_businesses: int = 60
    llm_provider: str = "none"
    llm_model: str = ""
    llm_base_url: str = ""

    @property
    def github_token(self) -> str:
        return os.environ.get("GITHUB_TOKEN", "")


def _split(v: str, newline_only: bool = False) -> list[str]:
    parts = v.splitlines() if newline_only else v.replace("\n", ",").split(",")
    return [x.strip() for x in parts if x.strip()]


def _oneline(s) -> str:
    return " ".join(str(s).split())  # no newlines: a value must never inject an INI line


def load(path: str = DEFAULT_PATH) -> Config:
    cfg = Config()
    if not os.path.exists(path):
        return cfg
    cp = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=None)
    cp.read(path, encoding="utf-8")
    for section, key, kind in SCHEMA:
        ini_key = INI_KEY.get(key, key)
        if not cp.has_section(section) or ini_key not in cp[section]:
            continue
        raw = cp[section][ini_key]
        try:
            if kind == "list":
                val = _split(raw)
            elif kind == "lines":
                val = _split(raw, newline_only=True)
            elif kind == "bool":
                val = raw.strip().lower() in ("1", "true", "yes", "on")
            elif kind == "float":
                val = float(raw or 0)
            elif kind == "int":
                val = int(raw or 0)
            else:
                val = raw.strip()
        except ValueError:
            continue  # keep the default for a hand-edited bad value
        setattr(cfg, key, val)
    cfg.llm_provider = (cfg.llm_provider or "none").lower()
    cfg.signature = cfg.signature or cfg.name
    return cfg


def render(cfg: Config) -> str:
    out = ["# leadhound config. Edit here or in the Settings tab of the app.",
           "# API keys are NOT stored here: set GITHUB_TOKEN, ANTHROPIC_API_KEY or OPENAI_API_KEY in your environment."]
    section = None
    for sec, key, kind in SCHEMA:
        if sec != section:
            out += ["", f"[{sec}]"]
            section = sec
        v = getattr(cfg, key)
        if kind == "list":
            text = ", ".join(_oneline(x) for x in v)
        elif kind == "lines":
            text = "".join(f"\n    {_oneline(u)}" for u in v)
        elif kind == "bool":
            text = str(v).lower()
        elif kind == "float":
            text = f"{v:g}"
        else:
            text = _oneline(v)
        out.append(f"{INI_KEY.get(key, key)} = {text}".rstrip() if kind != "lines" else f"{key} ={text}")
    return "\n".join(out) + "\n"


def save(cfg: Config, path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(render(cfg))
    os.replace(tmp, path)  # atomic: a crash never leaves a half-written config


def write_example(path: str = DEFAULT_PATH) -> bool:
    if os.path.exists(path):
        return False
    save(Config(name="Your Name", signature="Your Name | https://example.com", portfolio="https://example.com",
                min_budget=300, min_rate=25), path)
    return True


def to_dict(cfg: Config) -> dict:
    d = {f.name: getattr(cfg, f.name) for f in fields(cfg)}
    d["keys"] = {"github": bool(os.environ.get("GITHUB_TOKEN")),
                 "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
                 "openai": bool(os.environ.get("OPENAI_API_KEY"))}
    return d


SLUG_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,60}$")
HOST_RX = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
TAG_RX = re.compile(r"^\w{1,60}$")
RANGES = {"max_age_days": (1, 90), "radius_m": (100, 20000), "max_businesses": (1, 300), "auto_scan_hours": (0, 24)}
KINDS = {key: kind for _, key, kind in SCHEMA}


def from_dict(base: Config, d: dict) -> Config:
    """Apply user input over `base`. Unknown keys are ignored. Raises ValueError on bad values."""
    new = Config(**{f.name: getattr(base, f.name) for f in fields(base)})
    for key, val in d.items():
        kind = KINDS.get(key)
        if kind is None:
            continue
        if kind == "str":
            setattr(new, key, _oneline(val)[:500])
        elif kind in ("list", "lines"):
            items = _split(val, kind == "lines") if isinstance(val, str) else [_oneline(x) for x in val]
            setattr(new, key, [x for x in items if x][:100])
        elif kind == "bool":
            setattr(new, key, bool(val))
        elif kind == "float":
            n = float(val or 0)
            if n < 0:
                raise ValueError(f"{key} cannot be negative")
            setattr(new, key, n)
        elif kind == "int":
            n = int(val)
            lo, hi = RANGES[key]
            if not lo <= n <= hi:
                raise ValueError(f"{key} must be between {lo} and {hi}")
            setattr(new, key, n)
    _validate(new)
    new.signature = new.signature or new.name
    return new


def _validate(c: Config) -> None:
    from .profiles import BY_ID  # local import: profiles is optional data, avoid a cycle

    if c.llm_provider not in LLM_PROVIDERS:
        raise ValueError(f"llm_provider must be one of {', '.join(LLM_PROVIDERS)}")
    if c.currency.upper() not in CURRENCIES:
        raise ValueError(f"unknown currency {c.currency!r}")
    c.currency = c.currency.upper()
    if c.draft_language not in ("auto", *LANGUAGES):
        raise ValueError("unknown draft language")
    if c.profession and c.profession not in BY_ID:
        raise ValueError("unknown profession")
    if c.auto_scan_hours not in AUTO_SCAN_HOURS:
        raise ValueError("auto search must be off, 6, 12 or 24 hours")
    bad = [u for u in c.rss_feeds if not u.startswith(("http://", "https://"))]
    if bad:
        raise ValueError(f"RSS feed must start with http:// or https://: {bad[0][:60]}")
    if c.llm_base_url and not c.llm_base_url.startswith(("http://", "https://")):
        raise ValueError("LLM base URL must start with http:// or https://")
    for slug in c.freelancer_categories:
        if not SLUG_RX.match(slug):
            raise ValueError(f"bad Freelancer.com category: {slug[:40]}")
    c.mastodon_instances = [h.lower().removeprefix("https://").strip("/") for h in c.mastodon_instances]
    for h in c.mastodon_instances:
        if not HOST_RX.match(h):
            raise ValueError(f"bad Mastodon server: {h[:60]}")
    c.mastodon_tags = [t.lstrip("#") for t in c.mastodon_tags]
    for t in c.mastodon_tags:
        if not TAG_RX.match(t):
            raise ValueError(f"bad hashtag: {t[:40]}")
