"""Config: dataclass, INI load/save (stdlib configparser, works on Python 3.10), and API validation.

API keys never live in the config file. They come from environment variables.
"""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field, fields

DEFAULT_PATH = "leadhound.ini"
LLM_PROVIDERS = ("none", "anthropic", "openai")

PROFILE_STR = ("name", "pitch", "portfolio", "signature")
LIST_FIELDS = ("skills", "avoid", "reddit_subreddits", "github_labels", "github_languages", "rss_feeds",
               "categories")
BOOL_FIELDS = ("hn", "github")


@dataclass
class Config:
    name: str = ""
    pitch: str = "I build fast, reliable websites and web apps for small businesses"
    skills: list = field(default_factory=lambda: ["python", "javascript", "wordpress"])
    avoid: list = field(default_factory=lambda: ["unpaid", "equity only", "rev share", "for exposure"])
    portfolio: str = ""
    min_budget: float = 0
    min_rate: float = 0
    signature: str = ""
    reddit_subreddits: list = field(default_factory=lambda: ["forhire", "jobbit", "hiring"])
    hn: bool = True
    github: bool = True
    github_labels: list = field(default_factory=lambda: ["bounty", "help wanted"])
    github_languages: list = field(default_factory=list)
    rss_feeds: list = field(default_factory=list)
    max_age_days: int = 21
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
    sec = {s: cp[s] for s in ("profile", "sources", "local", "llm") if cp.has_section(s)}

    def get(section, key, default):
        return sec[section].get(key, default) if section in sec else default

    cfg.name = get("profile", "name", cfg.name)
    cfg.pitch = get("profile", "pitch", cfg.pitch)
    cfg.skills = _split(get("profile", "skills", ",".join(cfg.skills)))
    cfg.avoid = _split(get("profile", "avoid", ",".join(cfg.avoid)))
    cfg.portfolio = get("profile", "portfolio", "")
    cfg.min_budget = float(get("profile", "min_budget", 0) or 0)
    cfg.min_rate = float(get("profile", "min_rate", 0) or 0)
    cfg.signature = get("profile", "signature", "") or cfg.name
    cfg.reddit_subreddits = _split(get("sources", "reddit_subreddits", ",".join(cfg.reddit_subreddits)))
    cfg.hn = str(get("sources", "hn", "true")).lower() in ("1", "true", "yes", "on")
    cfg.github = str(get("sources", "github", "true")).lower() in ("1", "true", "yes", "on")
    cfg.github_labels = _split(get("sources", "github_labels", ",".join(cfg.github_labels)))
    cfg.github_languages = _split(get("sources", "github_languages", ""))
    cfg.rss_feeds = _split(get("sources", "rss_feeds", ""), newline_only=True)
    cfg.max_age_days = int(get("sources", "max_age_days", cfg.max_age_days))
    cfg.categories = _split(get("local", "categories", ",".join(cfg.categories)))
    cfg.radius_m = int(get("local", "radius_m", cfg.radius_m))
    cfg.max_businesses = int(get("local", "max_businesses", cfg.max_businesses))
    cfg.llm_provider = (get("llm", "provider", "none") or "none").strip().lower()
    cfg.llm_model = get("llm", "model", "").strip()
    cfg.llm_base_url = get("llm", "base_url", "").strip()
    return cfg


def render(cfg: Config) -> str:
    j = lambda xs: ", ".join(_oneline(x) for x in xs)  # noqa: E731
    feeds = "".join(f"\n    {_oneline(u)}" for u in cfg.rss_feeds)
    return f"""\
# leadhound config. Edit here or in the Settings tab of the app.
# API keys are NOT stored here: set GITHUB_TOKEN, ANTHROPIC_API_KEY or OPENAI_API_KEY in your environment.

[profile]
name = {_oneline(cfg.name)}
pitch = {_oneline(cfg.pitch)}
skills = {j(cfg.skills)}
avoid = {j(cfg.avoid)}
portfolio = {_oneline(cfg.portfolio)}
min_budget = {cfg.min_budget:g}
min_rate = {cfg.min_rate:g}
signature = {_oneline(cfg.signature)}

[sources]
reddit_subreddits = {j(cfg.reddit_subreddits)}
hn = {str(cfg.hn).lower()}
github = {str(cfg.github).lower()}
github_labels = {j(cfg.github_labels)}
github_languages = {j(cfg.github_languages)}
rss_feeds ={feeds}
max_age_days = {cfg.max_age_days}

[local]
categories = {j(cfg.categories)}
radius_m = {cfg.radius_m}
max_businesses = {cfg.max_businesses}

[llm]
# none | anthropic | openai  (openai = any OpenAI-compatible API, e.g. Ollama)
provider = {cfg.llm_provider}
model = {_oneline(cfg.llm_model)}
base_url = {_oneline(cfg.llm_base_url)}
"""


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


def from_dict(base: Config, d: dict) -> Config:
    """Apply user input over `base`. Unknown keys are ignored. Raises ValueError on bad values."""
    new = Config(**{f.name: getattr(base, f.name) for f in fields(base)})
    for key, val in d.items():
        if key in PROFILE_STR or key in ("llm_model", "llm_base_url"):
            setattr(new, key, _oneline(val)[:500])
        elif key in LIST_FIELDS:
            items = _split(val, key == "rss_feeds") if isinstance(val, str) else [_oneline(x) for x in val]
            setattr(new, key, [x for x in items if x][:100])
        elif key in BOOL_FIELDS:
            setattr(new, key, bool(val))
        elif key in ("min_budget", "min_rate"):
            n = float(val or 0)
            if n < 0:
                raise ValueError(f"{key} cannot be negative")
            setattr(new, key, n)
        elif key in ("max_age_days", "radius_m", "max_businesses"):
            n = int(val)
            lo, hi = {"max_age_days": (1, 90), "radius_m": (100, 20000), "max_businesses": (1, 200)}[key]
            if not lo <= n <= hi:
                raise ValueError(f"{key} must be between {lo} and {hi}")
            setattr(new, key, n)
        elif key == "llm_provider":
            if val not in LLM_PROVIDERS:
                raise ValueError(f"llm_provider must be one of {', '.join(LLM_PROVIDERS)}")
            new.llm_provider = val
    bad = [u for u in new.rss_feeds if not u.startswith(("http://", "https://"))]
    if bad:
        raise ValueError(f"RSS feed must start with http:// or https://: {bad[0][:60]}")
    if new.llm_base_url and not new.llm_base_url.startswith(("http://", "https://")):
        raise ValueError("LLM base URL must start with http:// or https://")
    new.signature = new.signature or new.name
    return new
