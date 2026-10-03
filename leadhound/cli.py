"""leadhound command line."""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import asdict

from . import __version__, config, paths, pipeline, shortcut
from .audit import audit
from .draft import make_draft
from .models import KINDS, STATUSES
from .net import Fetcher
from .sources import SOURCES
from .store import Store


def _age(ts: float) -> str:
    if not ts:
        return "-"
    h = (time.time() - ts) / 3600
    return f"{int(h)}h" if h < 48 else f"{int(h // 24)}d"


def cmd_init(a, cfg):
    if config.write_example(a.config):
        print(f"wrote {a.config}. Run `leadhound` to open the app and finish setup there.")
    else:
        print(f"{a.config} already exists")
    return 0


def cmd_scan(a, cfg):
    store = Store(a.db)
    rep = pipeline.scan(store, cfg, Fetcher(), a.sources.split(",") if a.sources else None)
    print(f"\n{sum(rep.new.values())} new leads. Next: leadhound list   or   leadhound serve")
    return 1 if rep.errors and not rep.found else 0


def cmd_local(a, cfg):
    store = Store(a.db)
    cats = [c.strip() for c in a.category.split(",")] if a.category else None
    rep = pipeline.local(store, cfg, Fetcher(), a.place, cats, a.radius, not a.no_audit, a.limit, a.website)
    if rep.errors:
        return 1
    print(f"\n{rep.new.get('osm', 0)} new businesses. Next: leadhound list --kind business")
    return 0


def cmd_audit(a, cfg):
    res = audit(a.url, Fetcher(min_interval=0.3), booking_relevant=a.booking, max_links=a.links)
    if a.json:
        print(json.dumps(res.to_dict(), indent=2))
        return 0
    print(f"{res.final_url or res.url}  HTTP {res.status or '-'}  {res.seconds}s  {res.html_kb} KB")
    if res.tech:
        print("tech: " + ", ".join(res.tech))
    if res.blocked:
        print("site blocked the automated check (bot protection). Open it in a browser and check by hand.")
        return 0
    if not res.findings:
        print("no issues found")
    for f in res.findings:
        print(f"\n[{'!' * f.severity:<3}] {f.title}\n      {f.detail}\n      pitch: {f.pitch}")
    return 0


def cmd_list(a, cfg):
    leads = Store(a.db).query(status=a.status, kind=a.kind, source=a.source, min_score=a.min_score,
                              search=a.search or "", limit=a.limit)
    if not leads:
        print("no leads. Run: leadhound scan   or   leadhound local \"<city>\"")
        return 0
    print(f"{'id':>5} {'score':>5} {'age':>4} {'src':<7} {'status':<11} title")
    for l in leads:
        extra = f"  [{l.budget}]" if l.budget else ""
        print(f"{l.id:>5} {l.score:>5} {_age(l.created_at):>4} {l.source:<7} {l.status:<11} {l.title[:70]}{extra}")
    return 0


def cmd_show(a, cfg):
    l = Store(a.db).get(a.id)
    if not l:
        print(f"no lead {a.id}", file=sys.stderr)
        return 1
    print(f"#{l.id} {l.title}\n{l.url}\nscore {l.score} | {l.source} {l.kind} | status {l.status} | age {_age(l.created_at)}")
    for k in ("author", "contact", "location", "budget"):
        if getattr(l, k):
            print(f"{k}: {getattr(l, k)}")
    print("\nwhy this score:\n  " + "\n  ".join(l.reasons))
    findings = (l.extra.get("audit") or {}).get("findings", [])
    if findings:
        print("\nwebsite issues:")
        for f in findings:
            print(f"  [{'!' * f['severity']}] {f['title']}: {f['detail'][:100]}")
    if l.body:
        print("\n" + l.body[:1500] + ("..." if len(l.body) > 1500 else ""))
    if l.draft:
        print("\n--- draft ---\n" + l.draft)
    if l.notes:
        print("\nnotes: " + l.notes)
    return 0


def cmd_draft(a, cfg):
    store = Store(a.db)
    l = store.get(a.id)
    if not l:
        print(f"no lead {a.id}", file=sys.stderr)
        return 1
    text, engine = make_draft(l, cfg, use_llm=a.llm)
    store.update(l.id, draft=text)
    print(f"[{engine}]\n\n{text}")
    return 0


def cmd_status(a, cfg):
    fields = {"status": a.status}
    if a.note:
        old = Store(a.db).get(a.id)
        stamp = time.strftime("%Y-%m-%d")
        fields["notes"] = ((old.notes + "\n") if old and old.notes else "") + f"{stamp}: {a.note}"
    if not Store(a.db).update(a.id, **fields):
        print(f"no lead {a.id}", file=sys.stderr)
        return 1
    print(f"#{a.id} -> {a.status}")
    return 0


def cmd_export(a, cfg):
    leads = Store(a.db).query(status=a.status, min_score=a.min_score, limit=100000, include_ignored=True)
    out = open(a.out, "w", newline="", encoding="utf-8") if a.out else sys.stdout
    if a.format == "json":
        json.dump([asdict(l) for l in leads], out, indent=2)
    else:
        cols = ["id", "score", "status", "source", "kind", "title", "url", "contact", "location", "budget", "notes"]
        w = csv.writer(out)
        w.writerow(cols)
        for l in leads:
            w.writerow([getattr(l, c) for c in cols])
    if a.out:
        out.close()
        print(f"exported {len(leads)} leads to {a.out}")
    return 0


def cmd_shortcut(a, cfg):
    path = shortcut.create()
    print(f"created {path}\nDouble-click it any time to open leadhound.")
    return 0


def cmd_license(a, cfg):
    """Seller tools. The private key signs license keys; keep it off GitHub and out of this folder."""
    import secrets
    import time

    from . import ed25519, licensing
    if a.action == "keygen":
        if os.path.exists(a.out):
            raise ValueError(f"{a.out} already exists: refusing to overwrite a private key")
        secret = secrets.token_bytes(32)
        fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secret.hex() + "\n")
        print(f"private key saved to {a.out} (back it up; anyone with it can sell licenses, and losing it means no new keys)")
        print(f"public key (paste into PUBLIC_KEY_HEX in leadhound/licensing.py): {ed25519.public_key(secret).hex()}")
        print("license server: run it with LICENSE_PRIVATE_KEY set to the same 64 characters (see docs/LICENSE_SERVER.md)")
    elif a.action == "issue":
        secret = bytes.fromhex(open(a.key).read().strip())
        token = licensing.make_key(secret, a.email, a.days)
        print(token)
        print(f"valid {a.days} days for {a.email}", file=sys.stderr)
    else:  # check
        data = licensing.read_key(a.token, a.public or None)
        if not data:
            print("NOT VALID")
            return 1
        left = (data["exp"] - time.time()) / 86400
        print(f"valid signature for {data.get('email')}: plan {data.get('plan')}, {left:.1f} days left")
    return 0


def cmd_serve(a, cfg):
    from .dashboard.server import serve
    serve(a.db, a.config, a.port, open_browser=not a.no_browser, cloud=a.cloud)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="leadhound", description="Find clients by live intent, not stale lists.")
    ap.add_argument("--version", action="version", version=f"leadhound {__version__}")
    ap.add_argument("--config", help="config file (default ~/.leadhound/config.ini)")
    ap.add_argument("--db", help="lead database (default ~/.leadhound/leadhound.db)")
    sub = ap.add_subparsers(dest="cmd", metavar="command",
                            help="run with no command to open the app in your browser")

    sub.add_parser("init", help="write an example leadhound.ini").set_defaults(fn=cmd_init)

    p = sub.add_parser("scan", help="collect hiring posts and issues from intent sources")
    p.add_argument("--sources", help=f"comma list from: {', '.join(SOURCES)} (default all)")
    p.set_defaults(fn=cmd_scan)

    p = sub.add_parser("local", help="find local businesses (OpenStreetMap) and audit their websites")
    p.add_argument("place", help='city or address, e.g. "Tbilisi, Georgia"')
    p.add_argument("--category", help="comma list, e.g. dentist,restaurant or shop=bicycle")
    p.add_argument("--radius", type=int, help="meters (default from config); 0 = whole city")
    p.add_argument("--limit", type=int, help="max businesses (default from config)")
    p.add_argument("--website", choices=["any", "yes", "no"], default="any",
                   help="only businesses with (yes) or without (no) a website listed")
    p.add_argument("--no-audit", action="store_true", help="skip website audits")
    p.set_defaults(fn=cmd_local)

    p = sub.add_parser("audit", help="audit one website")
    p.add_argument("url")
    p.add_argument("--booking", action="store_true", help="flag missing online booking")
    p.add_argument("--links", type=int, default=8, help="internal links to check (0 = none)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_audit)

    p = sub.add_parser("list", help="list leads, best first")
    p.add_argument("--status", choices=STATUSES)
    p.add_argument("--kind", choices=KINDS)
    p.add_argument("--source")
    p.add_argument("--min-score", type=int, default=0)
    p.add_argument("--search", "-q")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("show", help="show a lead with its score breakdown")
    p.add_argument("id", type=int)
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("draft", help="draft a first message for a lead")
    p.add_argument("id", type=int)
    p.add_argument("--llm", action="store_true", help="use the LLM from [llm] config")
    p.set_defaults(fn=cmd_draft)

    p = sub.add_parser("status", help="set lead status")
    p.add_argument("id", type=int)
    p.add_argument("status", choices=STATUSES)
    p.add_argument("--note")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("export", help="export leads to CSV or JSON")
    p.add_argument("--format", choices=["csv", "json"], default="csv")
    p.add_argument("--out")
    p.add_argument("--status", choices=STATUSES)
    p.add_argument("--min-score", type=int, default=0)
    p.set_defaults(fn=cmd_export)

    sub.add_parser("shortcut", help="create a double-click launcher on your desktop").set_defaults(fn=cmd_shortcut)

    p = sub.add_parser("license", help="seller tools: make keys and sign license keys for Pro")
    ls = p.add_subparsers(dest="action", required=True)
    q = ls.add_parser("keygen", help="make your signing key pair (once)")
    q.add_argument("--out", default="leadhound-private.key")
    q = ls.add_parser("issue", help="sign a license key for a customer")
    q.add_argument("--key", default="leadhound-private.key")
    q.add_argument("--email", required=True)
    q.add_argument("--days", type=int, default=31)
    q = ls.add_parser("check", help="check that a license key is genuine")
    q.add_argument("token")
    q.add_argument("--public", default="")
    p.set_defaults(fn=cmd_license)

    p = sub.add_parser("serve", help="open the local dashboard")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--cloud", action="store_true",
                   help="run on a server: listen on all interfaces, require LEADHOUND_PASSWORD, use $PORT")
    p.set_defaults(fn=cmd_serve)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    a.config, a.db = paths.resolve(a.config, a.db)
    if a.cmd is None:  # double-click / bare `leadhound`: open the app
        a.fn, a.port, a.no_browser, a.cloud = cmd_serve, 8787, False, bool(os.environ.get("LEADHOUND_CLOUD"))
    cfg = config.load(a.config)
    try:
        return a.fn(a, cfg)
    except KeyboardInterrupt:
        return 130
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
