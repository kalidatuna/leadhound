"""Audit tests against a real local HTTP server (no internet)."""
import http.server
import threading
import time
import unittest

from helpers import NOW  # noqa: F401  (sets sys.path)

from leadhound.audit import AuditResult, analyze_html, audit
from leadhound.net import Fetcher

YEAR = time.gmtime().tm_year

BAD = """<html><head><meta name="generator" content="WordPress 5.2">
<script src="/js/jquery-1.12.4.min.js"></script></head>
<body><img src="a.png"><img src="b.png"><img src="c.png"><img src="d.png" alt="">
<a href="/about">About</a><a href="/missing">Old page</a><a href="/guarded">Guarded</a>
<p>Welcome to our cafe</p><footer>© 2016 Cafe</footer></body></html>"""

GOOD = f"""<html><head><title>Smile Dental</title><meta name="viewport" content="width=device-width">
<meta name="description" content="Dentist in Tbilisi"><script type="application/ld+json">{{}}</script></head>
<body><a href="tel:+995">Call</a><a href="/book">Book an appointment</a>
<footer>© 2019-{YEAR} Smile</footer></body></html>"""

PAGES = {"/bad": BAD, "/good": GOOD, "/about": "<html>ok</html>", "/book": "<html>ok</html>"}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _reply(self, body=True):
        page = PAGES.get(self.path)
        special = {"/blocked": 403, "/guarded": 412}.get(self.path)
        self.send_response(special or (200 if page else 404))
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if body and page:
            self.wfile.write(page.encode())

    def do_GET(self):
        self._reply()

    def do_HEAD(self):
        self._reply(body=False)


class AuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"
        cls.f = Fetcher(min_interval=0, retries=0, timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def codes(self, res):
        return {f.code for f in res.findings}

    def test_bad_site(self):
        res = audit(self.base + "/bad", self.f, booking_relevant=True)
        c = self.codes(res)
        for want in ("no_https", "no_mobile", "no_title", "no_description", "stale", "old_wordpress",
                     "old_jquery", "no_booking", "no_schema", "img_alt", "broken_links", "no_contact"):
            self.assertIn(want, c)
        self.assertEqual(res.findings[0].severity, 3)  # sorted worst first
        broken = next(f for f in res.findings if f.code == "broken_links")
        self.assertIn("/missing (404)", broken.detail)
        self.assertNotIn("/about", broken.detail)
        self.assertNotIn("/guarded", broken.detail)  # 412 = bot guard, not broken
        self.assertIn("WordPress 5.2", res.tech)

    def test_good_site_only_https_flag(self):
        res = audit(self.base + "/good", self.f, booking_relevant=True)
        self.assertEqual(self.codes(res), {"no_https"})  # local test server is plain HTTP

    def test_unreachable_and_http_error(self):
        dead = audit("http://127.0.0.1:1/", self.f)
        self.assertEqual(self.codes(dead), {"down"})
        err = audit(self.base + "/nope", self.f)
        self.assertEqual(self.codes(err), {"http_error"})
        blocked = audit(self.base + "/blocked", self.f)
        self.assertTrue(blocked.blocked)
        self.assertEqual(blocked.findings, [])  # never pitch bot protection as a broken site

    def test_mixed_content_only_on_https(self):
        html = '<html><head><title>x</title><meta name="viewport" content="w"></head>' \
               '<body><img src="http://cdn/x.png" alt="x"><a href="mailto:a@b">mail</a></body></html>'
        res = AuditResult(url="https://x", final_url="https://x")
        analyze_html(res, html)
        self.assertIn("mixed_content", self.codes(res))
        plain = AuditResult(url="http://x", final_url="http://x")
        analyze_html(plain, html)
        self.assertNotIn("mixed_content", self.codes(plain))

    def test_script_license_not_stale(self):
        html = f"<html><head><title>t</title><meta name='viewport' content='w'><script>/* Copyright 2012 lib */</script>" \
               f"</head><body><a href='/contact'>Contact</a> © {YEAR}</body></html>"
        res = AuditResult(url="https://x", final_url="https://x")
        analyze_html(res, html)
        self.assertNotIn("stale", self.codes(res))


if __name__ == "__main__":
    unittest.main()
