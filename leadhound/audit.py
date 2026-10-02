"""Website weakness audit. Each finding carries a plain-language pitch a business owner understands.

Polite by design: fetches the homepage plus at most `max_links` internal links.
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from .net import FetchError
from .textutil import find_emails


@dataclass
class Finding:
    code: str
    severity: int  # 1 minor, 2 costs customers, 3 critical
    title: str
    detail: str
    pitch: str


@dataclass
class AuditResult:
    url: str
    final_url: str = ""
    status: int = 0
    seconds: float = 0.0
    html_kb: int = 0
    findings: list = field(default_factory=list)
    tech: list = field(default_factory=list)
    blocked: bool = False  # site refused automated checks: inconclusive, never pitch it as broken
    contacts: list = field(default_factory=list)  # emails and phones the site publishes itself

    @property
    def severity_total(self) -> int:
        return sum(f.severity for f in self.findings)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity_total"] = self.severity_total
        return d


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self.links: list[str] = []
        self.scripts: list[str] = []
        self.imgs: list[tuple[str, str | None]] = []
        self.resources: list[str] = []  # src/href of loaded resources (for mixed content)
        self.forms = 0
        self.ldjson = 0
        self.embeds: list[str] = []
        self.text_parts: list[str] = []
        self._in_title = False
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or a.get("http-equiv") or "").lower()
            if key:
                self.meta[key] = a.get("content", "")
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "script":
            if a.get("type", "").lower() == "application/ld+json":
                self.ldjson += 1
            if a.get("src"):
                self.scripts.append(a["src"])
                self.resources.append(a["src"])
            self._skip += 1
        elif tag == "style":
            self._skip += 1
        elif tag == "img":
            self.imgs.append((a.get("src", ""), dict(attrs).get("alt")))  # None = attribute absent
            if a.get("src"):
                self.resources.append(a["src"])
        elif tag == "link" and a.get("href") and a.get("rel", "").lower() in ("stylesheet", "icon"):
            self.resources.append(a["href"])
        elif tag == "form":
            self.forms += 1
        elif tag in ("embed", "object", "iframe"):
            self.embeds.append(a.get("src") or a.get("data") or "")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.text_parts.append(data)

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.text_parts))


COPYRIGHT_RX = re.compile(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?((?:19|20)\d{2})", re.I)
JQUERY_RX = re.compile(r"jquery[.-]?(\d+)\.(\d+)(?:\.\d+)?(?:\.min)?\.js|jquery(?:\.min)?\.js\?ver=(\d+)\.(\d+)", re.I)
BOOKING_RX = re.compile(r"\b(book|booking|reserve|reservation|appointment|schedule online|order online)\b|"
                        r"calendly|opentable|resy|booksy|fresha|treatwell|simplybook|setmore|square\.site", re.I)
CONTACT_RX = re.compile(r"\bcontact\b|kontakt|контакт", re.I)
BLOCKED_STATUSES = (401, 403, 406, 429, 503)
BROKEN_STATUSES = (404, 410)
BUILDERS = {"wix.com": "Wix", "squarespace": "Squarespace", "wp-content": "WordPress",
            "shopify": "Shopify", "webflow": "Webflow", "weebly": "Weebly", "godaddy": "GoDaddy builder"}


def _add(res: AuditResult, code, sev, title, detail, pitch):
    res.findings.append(Finding(code, sev, title, detail, pitch))


def analyze_html(res: AuditResult, html: str, booking_relevant: bool = False, now_year: int | None = None) -> PageParser:
    now_year = now_year or time.gmtime().tm_year
    p = PageParser()
    try:
        p.feed(html)
    except Exception:  # malformed HTML: keep what was parsed
        pass
    low = html.lower()
    for needle, name in BUILDERS.items():
        if needle in low and name not in res.tech:
            res.tech.append(name)
    gen = p.meta.get("generator", "")
    if gen:
        res.tech.append(gen.split(";")[0].strip()[:60])
    if "viewport" not in p.meta:
        _add(res, "no_mobile", 3, "Not mobile-friendly", "No viewport meta tag.",
             "Your site isn't set up for phones, and most local searches happen on a phone.")
    if not p.title.strip():
        _add(res, "no_title", 2, "Missing page title", "No <title> tag.",
             "Your homepage has no title, so Google shows a poor result for your business.")
    if not p.meta.get("description"):
        _add(res, "no_description", 1, "Missing meta description", "No meta description.",
             "Google has no summary to show under your link, which lowers clicks.")
    # visible text only: inline library licenses ("Copyright 2015 jQuery") must not count
    years = [int(y) for y in COPYRIGHT_RX.findall(p.text)]
    if years and max(years) < now_year - 1:
        _add(res, "stale", 2, f"Looks unmaintained (© {max(years)})", f"Latest copyright year {max(years)}.",
             f"The footer still says {max(years)}, which makes visitors wonder if you're still open.")
    wp = re.search(r"wordpress\s+(\d+)\.(\d+)", gen, re.I)
    if wp and int(wp.group(1)) < 6:
        _add(res, "old_wordpress", 3, f"Outdated WordPress {wp.group(1)}.{wp.group(2)}", gen,
             "The site runs an old WordPress version with known security holes.")
    for src in p.scripts:
        m = JQUERY_RX.search(src)
        if m:
            major = int(m.group(1) or m.group(3))
            if major < 3:
                _add(res, "old_jquery", 1, "Outdated jQuery", src,
                     "The site uses old JavaScript libraries that slow it down and have known security issues.")
            break
    if any(e.lower().endswith(".swf") for e in p.embeds) or "shockwave-flash" in low:
        _add(res, "flash", 3, "Uses Flash", "Flash content found.",
             "Part of the site uses Flash, which no browser can show anymore.")
    if res.final_url.startswith("https://"):
        mixed = [r for r in p.resources if r.startswith("http://")]
        if mixed:
            _add(res, "mixed_content", 2, "Mixed content", f"{len(mixed)} insecure resources, e.g. {mixed[0][:80]}",
                 "Some images or scripts load insecurely, so browsers may block them or warn visitors.")
    has_contact = any(h.lower().startswith(("mailto:", "tel:")) for h in p.links) or p.forms > 0 \
        or CONTACT_RX.search(" ".join(p.links) + " " + p.text) is not None
    if not has_contact:
        _add(res, "no_contact", 2, "No clear way to contact", "No mailto/tel link, form, or contact page.",
             "Visitors can't easily call, email or message you from the homepage.")
    if booking_relevant and not BOOKING_RX.search(p.text + " " + " ".join(p.links)):
        _add(res, "no_booking", 2, "No online booking", "No booking/reservation option found.",
             "Customers can't book online, so many will pick a competitor who lets them.")
    if p.ldjson == 0:
        _add(res, "no_schema", 1, "No structured data", "No JSON-LD found.",
             "Google can't read your hours, address and reviews in a structured way, which hurts maps ranking.")
    if len(p.imgs) >= 4:
        missing = sum(1 for _, alt in p.imgs if alt is None)
        if missing / len(p.imgs) > 0.5:
            _add(res, "img_alt", 1, "Images missing alt text", f"{missing}/{len(p.imgs)} images.",
                 "Most images have no description, which hurts accessibility and image search.")
    return p


PHONE_RX = re.compile(r"^tel:\+?[\d\s().-]{6,}$", re.I)


def extract_contacts(p: PageParser, limit: int = 4) -> list:
    """Emails first (mailto: links, then visible text), then phone numbers. Only what the site publishes."""
    emails = [h[7:].split("?")[0].strip().lower() for h in p.links if h.lower().startswith("mailto:")]
    emails = [e for e in emails if find_emails(e)] + find_emails(p.text)
    phones = [h[4:].strip() for h in p.links if PHONE_RX.match(h.strip())]
    out = []
    for c in emails + phones:
        if c not in out:
            out.append(c)
    return out[:limit]


def apply_contacts(lead, res: AuditResult) -> None:
    """Fill in lead contact details from the website when the directory listing had none."""
    if not res.contacts:
        return
    emails = [c for c in res.contacts if "@" in c]
    if emails and not lead.extra.get("email"):
        lead.extra["email"] = emails[0]
    if not lead.contact:
        lead.contact = ", ".join(res.contacts)


def check_links(res: AuditResult, p: PageParser, fetcher, max_links: int) -> None:
    host = urlparse(res.final_url).netloc
    seen, broken = set(), []
    for href in p.links:
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        u = urljoin(res.final_url, href).split("#")[0]
        if urlparse(u).netloc != host or u in seen or u.rstrip("/") == res.final_url.rstrip("/"):
            continue
        seen.add(u)
        if len(seen) > max_links:
            break
        try:
            r = fetcher.request(u, method="HEAD", timeout=10)
            if r.status >= 400 and r.status not in BROKEN_STATUSES:
                r = fetcher.request(u, timeout=10)  # many servers mishandle HEAD
            # only clear breakage counts; 401/403/412/429 usually mean "bot blocked", not "broken"
            if r.status in BROKEN_STATUSES or r.status >= 500:
                broken.append(f"{u} ({r.status})")
        except FetchError:
            pass  # timeouts on one link are too noisy to pitch
    if broken:
        _add(res, "broken_links", 2, f"{len(broken)} broken link(s)", "; ".join(broken[:5]),
             f"{len(broken)} link(s) on your homepage lead to error pages.")


def audit(url: str, fetcher, booking_relevant: bool = False, max_links: int = 8) -> AuditResult:
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    res = AuditResult(url=url)
    try:
        r = fetcher.request(url, timeout=20)
    except FetchError as e:
        msg = str(e)
        if "CERTIFICATE" in msg.upper() or "SSL" in msg.upper():
            _add(res, "tls_error", 3, "Broken HTTPS certificate", msg[:200],
                 "Browsers show a full-page security warning before visitors can reach your site.")
        else:
            _add(res, "down", 3, "Site unreachable", msg[:200],
                 "Your website didn't load at all when I tried it, so customers who search for you hit a dead end.")
        return res
    res.final_url, res.status, res.seconds = r.url, r.status, round(r.elapsed, 2)
    res.html_kb = len(r.body) // 1024
    if r.status in BLOCKED_STATUSES:
        res.blocked = True  # bot protection (Cloudflare etc.); real visitors likely see the site fine
        return res
    if r.status >= 400:
        _add(res, "http_error", 3, f"Homepage returns HTTP {r.status}", r.url,
             f"Your homepage returns an error ({r.status}) instead of your site.")
        return res
    if r.url.startswith("http://"):
        https_ok = False
        try:
            https_ok = fetcher.request("https://" + r.url[len("http://"):], timeout=10).status < 400
        except FetchError:
            pass
        _add(res, "no_https", 3, "No HTTPS" if not https_ok else "Not redirecting to HTTPS",
             "Site served over plain HTTP.",
             "Chrome marks your site 'Not secure', which scares off visitors and hurts Google ranking.")
    if r.elapsed > 3:
        _add(res, "slow", 2, f"Slow response ({r.elapsed:.1f}s)", "Homepage HTML took over 3 seconds.",
             f"Your homepage took {r.elapsed:.1f} seconds to load in my test; many visitors leave after 3.")
    if res.html_kb > 1500:
        _add(res, "heavy", 1, f"Heavy page ({res.html_kb} KB HTML)", "", "The page is very heavy and slow on mobile data.")
    p = analyze_html(res, r.text(), booking_relevant)
    res.contacts = extract_contacts(p)
    if max_links:
        check_links(res, p, fetcher, max_links)
    res.findings.sort(key=lambda f: -f.severity)
    return res
