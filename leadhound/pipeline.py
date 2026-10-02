"""Collect -> score -> store. One failing source never stops the others."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import audit as audit_mod
from .score import score
from .sources import SOURCES, PartialFailure, osm


@dataclass
class RunReport:
    found: dict = field(default_factory=dict)  # source -> leads collected
    new: dict = field(default_factory=dict)  # source -> leads not seen before
    errors: dict = field(default_factory=dict)  # source -> message


def scan(store, cfg, fetcher, sources: list | None = None, now: float | None = None, log=print) -> RunReport:
    now = now or time.time()
    rep = RunReport()
    for name in sources or list(SOURCES):
        if name not in SOURCES:
            rep.errors[name] = f"unknown source (choose from {', '.join(SOURCES)})"
            continue
        log(f"  {name}: collecting...")
        try:
            leads = SOURCES[name](fetcher, cfg, now)
        except PartialFailure as pf:  # keep what worked, report the rest
            leads = pf.leads
            rep.errors[name] = str(pf)[:300]
            log(f"  {name}: partly failed: {rep.errors[name]}")
        except Exception as e:  # network, parse, rate limit: report and move on
            rep.errors[name] = str(e)[:300]
            log(f"  {name}: FAILED {rep.errors[name]}")
            continue
        new = 0
        for lead in leads:
            _, is_new = store.upsert(score(lead, cfg, now))
            new += is_new
        rep.found[name], rep.new[name] = len(leads), new
        log(f"  {name}: {len(leads)} leads ({new} new)")
    return rep


def local(store, cfg, fetcher, place: str, categories: list | None = None, radius: int | None = None,
          do_audit: bool = True, limit: int | None = None, website: str = "any", log=print) -> RunReport:
    rep = RunReport()
    cats = categories or cfg.categories
    log(f"  osm: searching {', '.join(cats)} near '{place}'...")
    try:
        leads, display = osm.find_businesses(fetcher, place, cats, radius or cfg.radius_m)
    except Exception as e:
        rep.errors["osm"] = str(e)[:300]
        log(f"  osm: FAILED {rep.errors['osm']}")
        return rep
    log(f"  osm: {len(leads)} businesses around {display[:80]}")
    if website in ("yes", "no"):
        leads = [l for l in leads if bool(l.extra.get("website")) == (website == "yes")]
    # without a website first: strongest leads and no audit needed
    leads.sort(key=lambda l: bool(l.extra.get("website")))
    leads = leads[: limit or cfg.max_businesses]
    new = 0
    for i, lead in enumerate(leads, 1):
        site = lead.extra.get("website")
        if do_audit and site:
            log(f"  audit {i}/{len(leads)}: {site}")
            res = audit_mod.audit(site, fetcher, booking_relevant=lead.extra.get("booking_relevant", False))
            lead.extra["audit"] = res.to_dict()
            lead.signals = [f.title for f in res.findings]
        _, is_new = store.upsert(score(lead, cfg, time.time()))
        new += is_new
    rep.found["osm"], rep.new["osm"] = len(leads), new
    return rep
