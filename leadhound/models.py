"""Core data types."""
from __future__ import annotations

from dataclasses import dataclass, field

KINDS = ("post", "issue", "business")
STATUSES = ("new", "shortlisted", "contacted", "replied", "won", "lost", "ignored")


@dataclass
class Lead:
    source: str  # reddit | hn | github | rss | osm
    external_id: str  # stable id inside the source, used for dedupe
    kind: str  # post | issue | business
    title: str
    url: str
    body: str = ""
    author: str = ""
    created_at: float = 0.0  # unix seconds; 0 = unknown
    contact: str = ""  # contact info the lead published themselves
    location: str = ""
    budget: str = ""
    signals: list = field(default_factory=list)  # audit findings or source tags
    score: int = 0
    reasons: list = field(default_factory=list)  # human-readable score breakdown
    status: str = "new"
    draft: str = ""
    notes: str = ""
    extra: dict = field(default_factory=dict)
    id: int | None = None

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.body}"
