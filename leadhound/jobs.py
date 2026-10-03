"""Background jobs for the dashboard: one search at a time, with a live log and cancel."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from urllib.parse import urlparse

from . import audit as audit_mod
from . import config, pipeline, updates
from .models import Lead
from .net import Fetcher, is_public_host
from .score import score_business
from .sources import SOURCES, osm
from .store import Store

MAX_LOG = 300


class JobBusy(Exception):
    pass


class Job:
    def __init__(self, kind: str, params: dict):
        self.id = uuid.uuid4().hex[:10]
        self.kind, self.params = kind, params
        self.status = "running"  # running | done | error | cancelled
        self.log: list[str] = []
        self.result: dict = {}
        self.started = time.time()
        self.finished = 0.0
        self.stop = threading.Event()

    def add(self, line: str) -> None:
        self.log.append(str(line).strip()[:300])
        del self.log[:-MAX_LOG]

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "params": self.params, "status": self.status,
                "log": list(self.log), "result": self.result, "started": self.started, "finished": self.finished}


def clean_params(kind: str, p: dict, cloud: bool = False) -> dict:
    """Validate and normalise user input; raises ValueError with a message safe to show."""
    if kind == "update":
        if updates.install_mode() != "pip":
            raise ValueError("in-app updates work for pip/pipx installs only")
        return {}
    if kind == "scan":
        srcs = p.get("sources") or list(SOURCES)
        bad = [s for s in srcs if s not in SOURCES]
        if bad:
            raise ValueError(f"unknown source: {bad[0]}")
        return {"sources": list(srcs)}
    if kind == "local":
        place = str(p.get("place", "")).strip()
        if not 2 <= len(place) <= 200:
            raise ValueError("enter a city or address")
        cats = [str(c).strip() for c in (p.get("categories") or []) if str(c).strip()]
        for c in cats:
            osm.category_tag(c)  # raises ValueError for unknown categories
        radius = p.get("radius")
        radius = None if radius in (None, "") else int(radius)  # 0 = whole city
        limit = int(p.get("limit") or 0)
        if radius and not 100 <= radius <= 20000:
            raise ValueError("radius must be 0 (whole city) or between 100 and 20000 meters")
        if limit and not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        website = p.get("website", "any")
        if website not in ("any", "yes", "no"):
            raise ValueError("website must be any, yes or no")
        return {"place": place, "categories": cats, "radius": radius, "limit": limit or None,
                "website": website, "audit": bool(p.get("audit", True))}
    if kind == "audit":
        url = str(p.get("url", "")).strip()
        if not url or len(url) > 500 or " " in url:
            raise ValueError("enter a website address")
        if not url.startswith(("http://", "https://")):
            url = "http://" + url
        host = urlparse(url).hostname or ""
        if "." not in host:
            raise ValueError("that does not look like a website address")
        if cloud and not is_public_host(host):
            raise ValueError("private network addresses can't be checked")
        return {"url": url, "booking": bool(p.get("booking")), "name": str(p.get("name", "")).strip()[:120]}
    raise ValueError(f"unknown job type: {kind}")


class JobManager:
    def __init__(self, db_path: str, config_path: str, fetcher_factory=Fetcher, cloud: bool = False):
        self.db_path, self.config_path, self.fetcher_factory = db_path, config_path, fetcher_factory
        self.cloud = cloud
        self.jobs: dict[str, Job] = {}
        self.current: Job | None = None
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    def start(self, kind: str, params: dict) -> Job:
        params = clean_params(kind, params, self.cloud)
        with self._lock:
            if self.current and self.current.status == "running":
                raise JobBusy("another search is still running")
            job = Job(kind, params)
            self.jobs[job.id] = job
            self.current = job
            for old in sorted(self.jobs.values(), key=lambda j: j.started)[:-20]:
                self.jobs.pop(old.id, None)  # keep the last 20
        t = threading.Thread(target=self._run, args=(job,), daemon=True)
        self._threads.append(t)
        t.start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if job and job.status == "running":
            job.stop.set()
            job.add("stopping after the current step...")
            return True
        return False

    def wait(self, timeout: float = 30) -> None:  # for tests
        for t in list(self._threads):
            t.join(timeout)

    def _run(self, job: Job) -> None:
        store = None
        try:
            cfg = config.load(self.config_path)  # fresh: Settings changes apply to the next search
            store = Store(self.db_path)
            fetcher = self.fetcher_factory()
            p = job.params
            if job.kind == "update":
                cache = os.path.join(os.path.dirname(os.path.abspath(self.config_path)), "update.json")
                info = updates.check(self.fetcher_factory(), cache, force=True)
                ok = info["newer"] and updates.upgrade(job.add, info["latest"])
                if not info["newer"]:
                    job.add("already up to date")
                job.result = {"found": {}, "new": {}, "errors": {} if ok else {"update": "pip failed, see log"},
                              "restart": ok}
                job.status = "done" if ok else "error"
                return
            if job.kind == "scan":
                rep = pipeline.scan(store, cfg, fetcher, p["sources"], log=job.add, should_stop=job.stop.is_set)
            elif job.kind == "local":
                rep = pipeline.local(store, cfg, fetcher, p["place"], p["categories"] or None, p["radius"],
                                     p["audit"], p["limit"], p["website"], log=job.add, should_stop=job.stop.is_set)
            else:
                rep = self._audit_one(store, cfg, fetcher, job)
            job.result = {"found": rep.found, "new": rep.new, "errors": rep.errors, **getattr(rep, "extra", {})}
            all_failed = bool(rep.errors) and not rep.found
            job.status = "cancelled" if job.stop.is_set() else "error" if all_failed else "done"
        except Exception as e:  # never let a job thread die silently
            job.add(f"failed: {e}")
            job.result = {"found": {}, "new": {}, "errors": {"job": str(e)[:300]}}
            job.status = "error"
        finally:
            if store:
                store.close()
            job.finished = time.time()

    def _audit_one(self, store, cfg, fetcher, job):
        p = job.params
        job.add(f"checking {p['url']} ...")
        res = audit_mod.audit(p["url"], fetcher, booking_relevant=p["booking"])
        host = urlparse(res.final_url or p["url"]).netloc.removeprefix("www.")
        lead = Lead(source="manual", external_id=host, kind="business", title=p["name"] or host,
                    url=res.final_url or p["url"], signals=[f.title for f in res.findings],
                    extra={"website": res.final_url or p["url"], "category": "website check",
                           "booking_relevant": p["booking"], "audit": res.to_dict()})
        audit_mod.apply_contacts(lead, res)
        lead_id, is_new = store.upsert(score_business(lead, cfg))
        job.add("blocked automated checks; open the site by hand" if res.blocked
                else f"{len(res.findings)} issue(s) found")
        rep = pipeline.RunReport(found={"manual": 1}, new={"manual": int(is_new)})
        rep.extra = {"lead_id": lead_id}
        return rep


class AutoScanner:
    """Runs a full search every N hours (Settings > auto search) while leadhound is running."""

    def __init__(self, jobs: JobManager, state_path: str, interval: float = 60):
        self.jobs, self.state_path, self.interval = jobs, state_path, interval
        self._stop = threading.Event()

    def _last(self) -> float:
        try:
            with open(self.state_path, encoding="utf-8") as f:
                return float(json.load(f).get("last_auto_scan", 0))
        except (OSError, ValueError):
            return 0.0

    def _mark(self, ts: float) -> None:
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump({"last_auto_scan": ts}, f)
        except OSError:
            pass

    def tick(self, now: float | None = None) -> bool:
        """Start a scan if one is due. Returns True if it started one."""
        now = now or time.time()
        hours = config.load(self.jobs.config_path).auto_scan_hours
        if not hours or now - self._last() < hours * 3600:
            return False
        try:
            job = self.jobs.start("scan", {})
        except JobBusy:
            return False
        job.add("automatic search (Settings > search automatically)")
        self._mark(now)
        return True

    def run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception:  # never let the scheduler thread die
                pass

    def start(self) -> None:
        threading.Thread(target=self.run, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
