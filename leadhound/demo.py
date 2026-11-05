"""Demo mode: `leadhound demo` opens the app with sample leads, so you can try everything in ten seconds.

The demo keeps its own folder (~/.leadhound/demo), never touches your real leads, and turns off sending
from connected accounts. Every lead here is made up: the names, links and addresses use example domains.
Searching still works for real, so you can see fresh results next to the samples.
"""
from __future__ import annotations

import os
import time

from . import config, paths
from .audit import AuditResult, Finding
from .i18n import msg
from .models import Lead
from .score import score
from .store import Store

DAY = 86400


def folder() -> str:
    return os.path.join(paths.data_dir(), "demo")


def _finding(code: str, severity: int, **args) -> Finding:
    return Finding(code=code, severity=severity, title=msg("en", f"t.{code}", **args), detail="",
                   pitch=msg("en", f"f.{code}", **args), args=args)


def _business(eid, name, category, city, country, website="", lang="", findings=(), contact="", booking=False, tech=()):
    extra = {"website": website, "category": category, "booking_relevant": booking, "country": country, "city": city}
    parts = [c.strip() for c in contact.split(",") if c.strip()]
    extra.update({k: v for k, v in (("email", next((c for c in parts if "@" in c), "")),
                                    ("phone", next((c for c in parts if "@" not in c), ""))) if v})  # as OpenStreetMap lists them
    if website:
        extra["audit"] = AuditResult(url=website, final_url=website, status=200, seconds=1.4, findings=list(findings),
                                     tech=list(tech), lang=lang).to_dict()
    return Lead(source="osm", external_id=eid, kind="business", title=name, url=f"https://www.openstreetmap.example/node/{eid}",
                contact=contact, location=city, signals=[f.title for f in findings], extra=extra)


def sample_leads(now: float) -> list[Lead]:
    h = 3600
    return [
        Lead(source="freelancer", external_id="demo-1", kind="post", title="WordPress booking site for a physiotherapy clinic",
             url="https://www.freelancer.example/projects/demo-1", created_at=now - 2 * h, budget="$750 USD",
             body="We need a clean WordPress site with online booking for 3 therapists, plus a simple blog. "
                  "Please share similar work. Deadline in 3 weeks.",
             contact="bid on Freelancer.com", signals=["client project post"],
             extra={"skills": ["WordPress", "PHP", "Website Design"], "category": "WordPress"}),
        Lead(source="reddit", external_id="demo-2", kind="post", title="[Hiring] Shopify store is slow, need a fix this week",
             url="https://www.reddit.example/r/forhire/comments/demo2/", author="u/beanroaster", created_at=now - 5 * h,
             budget="$400", body="Paid gig for our small coffee roastery. Looking to hire a developer to speed up the Shopify "
                                 "theme and fix the checkout on phones. Email hello@roaster.example with similar work.",
             contact="hello@roaster.example, reddit DM: u/beanroaster"),
        Lead(source="reddit", external_id="demo-3", kind="post", title="[Hiring] Python script to clean 40k rows of CSV data",
             url="https://www.reddit.example/r/forhire/comments/demo3/", author="u/opsdata", created_at=now - 26 * h,
             budget="$250", body="Need someone this week. Messy supplier CSVs, dedupe and normalise addresses.",
             contact="reddit DM: u/opsdata"),
        Lead(source="hn", external_id="demo-4", kind="post", title="SEEKING FREELANCER | Data engineer | 3-month contract | Remote",
             url="https://news.ycombinator.example/item?id=demo4", author="northwind", created_at=now - 50 * h,
             body="Seeking freelancer: Python + Postgres pipelines, part-time contract. Email jobs@northwind.example",
             contact="jobs@northwind.example, HN: northwind", signals=["seeking freelancer thread"]),
        Lead(source="github", external_id="demo-5", kind="issue", title="[acme/exporter] CSV export breaks on non-ASCII names",
             url="https://github.example/acme/exporter/issues/1", author="acme", created_at=now - 30 * h, budget="$200",
             body="Bounty: $200 paid on merge. Python 3.12.", signals=["paid bounty"], extra={"language": "Python"}),
        Lead(source="himalayas", external_id="demo-6", kind="post", title="Shopify developer (contract) · Northwind Goods",
             url="https://himalayas.example/companies/northwind/jobs/demo-6", author="Northwind Goods", created_at=now - 8 * h,
             budget="$50-$80/hr", body="Remote contract. Theme fixes, faster checkout, app integrations.",
             contact="apply via himalayas.app", signals=["remote contract role"], extra={"skills": ["Shopify", "JavaScript"]}),
        Lead(source="mastodon", external_id="demo-7", kind="post", title="Busco diseñador web para la página de mi panadería",
             url="https://mastodon.example/@panaderia/demo7", author="panaderia", created_at=now - 20 * h,
             body="¿Alguien recomienda un diseñador? Pagamos, presupuesto 300 €.", contact="Mastodon: @panaderia@mastodon.example",
             extra={"language": "es"}),
        Lead(source="rss", external_id="demo-8", kind="post", title="Freelance copywriter for a SaaS landing page",
             url="https://weworkremotely.example/jobs/demo-8", created_at=now - 3 * DAY,
             body="Contract, 2 weeks. Rewrite our landing page and onboarding emails.", contact="apply via weworkremotely.example"),
        _business("demo-9", "Smile Dental Vake", "dentist", "Tbilisi", "ge", website="http://smile-dental.example", lang="ka",
                  booking=True, contact="info@smile-dental.example, +995 32 200 00 00", tech=["WordPress 5.4"],
                  findings=[_finding("no_https", 3), _finding("no_booking", 2), _finding("stale", 2, year=2021)]),
        _business("demo-10", "Café Lisboa", "cafe", "Lisbon", "pt", contact="+351 21 000 0000"),
        _business("demo-11", "Hotel Mar Azul", "hotel", "Valencia", "es", website="https://hotelmarazul.example", lang="es",
                  booking=True, contact="reservas@hotelmarazul.example",
                  findings=[_finding("no_mobile", 3), _finding("slow", 2, secs=6.2), _finding("no_description", 1)]),
        Lead(source="freelancer", external_id="demo-12", kind="post", title="Translate a restaurant menu from English to Spanish",
             url="https://www.freelancer.example/projects/demo-12", created_at=now - 4 * h, budget="€120 EUR",
             body="Two-page menu, needs a native Spanish speaker.", contact="bid on Freelancer.com",
             signals=["client project post"], extra={"skills": ["Translation", "Spanish"], "category": "Translation"}),
    ]


DEMO_CONFIG = dict(name="Alex", signature="Alex · alex.example", profession="developer",
                   skills=["wordpress", "python", "shopify", "csv"], portfolio="https://alex.example",
                   proof=["wordpress, booking: Rebuilt a clinic's WordPress site with online booking: https://alex.example/clinic",
                          "csv, python: Cleaned and merged 120k supplier rows for a wholesaler: https://alex.example/data",
                          "shopify, checkout: Cut a Shopify store's mobile load time from 7 s to 2 s: https://alex.example/shop"],
                   min_budget=150, min_rate=25, mastodon=True, categories=["dentist", "cafe", "hotel"])


def seed(config_path: str, db_path: str, now: float | None = None) -> int:
    """Write the demo profile and sample leads (only into an empty demo database). Returns how many leads it added."""
    now = now or time.time()
    if not os.path.exists(config_path):
        config.save(config.from_dict(config.Config(), DEMO_CONFIG), config_path)
    cfg = config.load(config_path)
    store = Store(db_path)
    try:
        if store.stats()["total"]:
            return 0
        ids = {}
        for lead in sample_leads(now):
            ids[lead.external_id], _ = store.upsert(score(lead, cfg, now))
        # some history, so follow-ups, reply rates and the week chart have something to show
        for eid, status, days in (("demo-3", "contacted", 4), ("demo-8", "contacted", 5), ("demo-4", "contacted", 6),
                                  ("demo-12", "contacted", 2)):
            store.update(ids[eid], status=status, draft="(sent in the demo)")
            store.db.execute("UPDATE activity SET at = ? WHERE lead_id = ?", (now - days * DAY, ids[eid]))
        store.update(ids["demo-4"], status="replied")
        store.log(ids["demo-4"], "replied", "email")
        store.update(ids["demo-12"], status="won")
        store.db.commit()
        return len(ids)
    finally:
        store.close()


def paths_for_demo(reset: bool = False) -> tuple[str, str]:
    d = folder()
    os.makedirs(d, exist_ok=True)
    cfg, db = os.path.join(d, "config.ini"), os.path.join(d, "leadhound.db")
    if reset:
        for p in (cfg, db, db + "-wal", db + "-shm"):
            if os.path.exists(p):
                os.remove(p)
    return cfg, db
