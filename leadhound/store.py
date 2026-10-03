"""SQLite lead store. Re-scans update content and score but never touch status, notes or draft."""
from __future__ import annotations

import json
import sqlite3
import time

from .models import STATUSES, Lead

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    body TEXT DEFAULT '',
    author TEXT DEFAULT '',
    created_at REAL DEFAULT 0,
    contact TEXT DEFAULT '',
    location TEXT DEFAULT '',
    budget TEXT DEFAULT '',
    signals TEXT DEFAULT '[]',
    score INTEGER DEFAULT 0,
    reasons TEXT DEFAULT '[]',
    status TEXT DEFAULT 'new',
    draft TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    extra TEXT DEFAULT '{}',
    first_seen REAL,
    updated_at REAL,
    UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(score DESC);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
"""

CONTENT_FIELDS = ("kind", "title", "url", "body", "author", "created_at", "contact",
                  "location", "budget", "signals", "score", "reasons", "extra")
JSON_FIELDS = ("signals", "reasons", "extra")


class Store:
    def __init__(self, path: str = "leadhound.db"):
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        if path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")  # dashboard and background jobs share the file
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    @staticmethod
    def _row(r: sqlite3.Row) -> Lead:
        d = dict(r)
        for f in JSON_FIELDS:
            d[f] = json.loads(d[f] or ("{}" if f == "extra" else "[]"))
        d["first_seen"] = d.get("first_seen") or 0.0
        d.pop("updated_at", None)
        return Lead(**d)

    def upsert(self, lead: Lead) -> tuple[int, bool]:
        """Insert or refresh a lead. Returns (id, is_new)."""
        vals = {f: getattr(lead, f) for f in CONTENT_FIELDS}
        for f in JSON_FIELDS:
            vals[f] = json.dumps(vals[f])
        now = time.time()
        cur = self.db.execute("SELECT id FROM leads WHERE source=? AND external_id=?",
                              (lead.source, lead.external_id))
        row = cur.fetchone()
        if row:
            sets = ", ".join(f"{f}=?" for f in CONTENT_FIELDS)
            self.db.execute(f"UPDATE leads SET {sets}, updated_at=? WHERE id=?",
                            (*vals.values(), now, row["id"]))
            self.db.commit()
            return row["id"], False
        cols = ("source", "external_id", *CONTENT_FIELDS, "first_seen", "updated_at")
        cur = self.db.execute(
            f"INSERT INTO leads ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            (lead.source, lead.external_id, *vals.values(), now, now))
        self.db.commit()
        return cur.lastrowid, True

    def get(self, lead_id: int) -> Lead | None:
        r = self.db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        return self._row(r) if r else None

    ORDERS = {"score": "score DESC, created_at DESC", "newest": "first_seen DESC, score DESC",
              "oldest": "first_seen ASC"}

    def query(self, status: str | None = None, kind: str | None = None, source: str | None = None,
              min_score: int = 0, search: str = "", limit: int = 100, include_ignored: bool = False,
              sort: str = "score") -> list[Lead]:
        where, args = ["score >= ?"], [min_score]
        if status:
            where.append("status = ?")
            args.append(status)
        elif not include_ignored:
            where.append("status != 'ignored'")
        if kind:
            where.append("kind = ?")
            args.append(kind)
        if source:
            where.append("source = ?")
            args.append(source)
        if search:
            where.append("(title LIKE ? OR body LIKE ? OR location LIKE ?)")
            args += [f"%{search}%"] * 3
        sql = f"SELECT * FROM leads WHERE {' AND '.join(where)} ORDER BY {self.ORDERS.get(sort, self.ORDERS['score'])} LIMIT ?"
        return [self._row(r) for r in self.db.execute(sql, (*args, limit))]

    def update(self, lead_id: int, **fields) -> bool:
        allowed = {"status", "notes", "draft"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"cannot update {sorted(bad)}")
        if "status" in fields and fields["status"] not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        if not fields:
            return False
        sets = ", ".join(f"{k}=?" for k in fields)
        cur = self.db.execute(f"UPDATE leads SET {sets}, updated_at=? WHERE id=?",
                              (*fields.values(), time.time(), lead_id))
        self.db.commit()
        return cur.rowcount > 0

    def update_many(self, ids: list, status: str) -> int:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        ids = [int(i) for i in ids][:5000]
        if not ids:
            return 0
        marks = ",".join("?" * len(ids))
        cur = self.db.execute(f"UPDATE leads SET status=?, updated_at=? WHERE id IN ({marks})",
                              (status, time.time(), *ids))
        self.db.commit()
        return cur.rowcount

    def stats(self) -> dict:
        out = {"total": 0, "by_status": {}, "by_source": {}}
        for r in self.db.execute("SELECT status, COUNT(*) c FROM leads GROUP BY status"):
            out["by_status"][r["status"]] = r["c"]
            out["total"] += r["c"]
        for r in self.db.execute("SELECT source, COUNT(*) c FROM leads GROUP BY source"):
            out["by_source"][r["source"]] = r["c"]
        return out
