"""Config loading. INI format (stdlib configparser) so Python 3.10 works without extra deps.

API keys never live in the config file. They come from environment variables.
"""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field

DEFAULT_PATH = "leadhound.ini"

EXAMPLE = """\
# leadhound config. Keys and tokens go in environment variables, never here.

[profile]
name = Your Name
# One sentence: what you do and the result clients get.
pitch = I build fast, reliable websites and web apps for small businesses
skills = Python, Django, JavaScript, React, WordPress, Shopify, automation, web scraping
# Leads containing these phrases are pushed down hard.
avoid = unpaid, equity only, rev share, revenue share, for exposure, internship
portfolio = https://example.com
# Smallest project budget (any currency) and hourly rate you accept.
min_budget = 300
min_rate = 25
signature = Your Name | https://example.com

[sources]
reddit_subreddits = forhire, jobbit, freelance_forhire, hiring, b2bforhire
hn = true
github = true
github_labels = bounty, help wanted
# Optional: limit GitHub issues to these languages.
github_languages = python, javascript, typescript
rss_feeds = https://weworkremotely.com/categories/remote-programming-jobs.rss
max_age_days = 21

[local]
# Categories for `leadhound local`. See README for the full list.
categories = restaurant, cafe, dentist, hairdresser, beauty, plumber, lawyer, hotel
radius_m = 3000
max_businesses = 60

[llm]
# none | anthropic | openai  (openai = any OpenAI-compatible API, e.g. Ollama)
provider = none
model =
base_url =
"""


def _list(v: str) -> list[str]:
    return [x.strip() for x in v.split(",") if x.strip()]


@dataclass
class Config:
    name: str = "Your Name"
    pitch: str = "I build fast, reliable websites and web apps"
    skills: list = field(default_factory=lambda: ["python", "javascript", "wordpress"])
    avoid: list = field(default_factory=lambda: ["unpaid", "equity only", "rev share"])
    portfolio: str = ""
    min_budget: float = 0
    min_rate: float = 0
    signature: str = ""
    reddit_subreddits: list = field(default_factory=lambda: ["forhire", "jobbit"])
    hn: bool = True
    github: bool = True
    github_labels: list = field(default_factory=lambda: ["bounty", "help wanted"])
    github_languages: list = field(default_factory=list)
    rss_feeds: list = field(default_factory=list)
    max_age_days: int = 14
    categories: list = field(default_factory=lambda: ["restaurant", "dentist"])
    radius_m: int = 3000
    max_businesses: int = 60
    llm_provider: str = "none"
    llm_model: str = ""
    llm_base_url: str = ""

    @property
    def github_token(self) -> str:
        return os.environ.get("GITHUB_TOKEN", "")


def load(path: str = DEFAULT_PATH) -> Config:
    cfg = Config()
    if not os.path.exists(path):
        return cfg
    cp = configparser.ConfigParser(inline_comment_prefixes=(";",))
    cp.read(path, encoding="utf-8")
    p = cp["profile"] if cp.has_section("profile") else {}
    s = cp["sources"] if cp.has_section("sources") else {}
    loc = cp["local"] if cp.has_section("local") else {}
    llm = cp["llm"] if cp.has_section("llm") else {}
    cfg.name = p.get("name", cfg.name)
    cfg.pitch = p.get("pitch", cfg.pitch)
    cfg.skills = _list(p.get("skills", ",".join(cfg.skills)))
    cfg.avoid = _list(p.get("avoid", ",".join(cfg.avoid)))
    cfg.portfolio = p.get("portfolio", "")
    cfg.min_budget = float(p.get("min_budget", 0) or 0)
    cfg.min_rate = float(p.get("min_rate", 0) or 0)
    cfg.signature = p.get("signature", "") or cfg.name
    cfg.reddit_subreddits = _list(s.get("reddit_subreddits", ",".join(cfg.reddit_subreddits)))
    cfg.hn = str(s.get("hn", "true")).lower() in ("1", "true", "yes", "on")
    cfg.github = str(s.get("github", "true")).lower() in ("1", "true", "yes", "on")
    cfg.github_labels = _list(s.get("github_labels", ",".join(cfg.github_labels)))
    cfg.github_languages = _list(s.get("github_languages", ""))
    cfg.rss_feeds = _list(s.get("rss_feeds", ""))
    cfg.max_age_days = int(s.get("max_age_days", cfg.max_age_days))
    cfg.categories = _list(loc.get("categories", ",".join(cfg.categories)))
    cfg.radius_m = int(loc.get("radius_m", cfg.radius_m))
    cfg.max_businesses = int(loc.get("max_businesses", cfg.max_businesses))
    cfg.llm_provider = (llm.get("provider", "none") or "none").strip().lower()
    cfg.llm_model = llm.get("model", "").strip()
    cfg.llm_base_url = llm.get("base_url", "").strip()
    return cfg


def write_example(path: str = DEFAULT_PATH) -> bool:
    if os.path.exists(path):
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(EXAMPLE)
    return True
