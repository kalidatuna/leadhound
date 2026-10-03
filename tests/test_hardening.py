"""Hostile input: slow patterns, odd requests, stolen logins, lockout spoofing, runaway servers."""
import http.client
import http.server
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from helpers import FakeFetcher  # noqa: F401  (sets sys.path)

from leadhound import licensing, licenseserver
from leadhound.dashboard.server import make_server
from leadhound.net import Fetcher
from leadhound.sources import freelancer, osm
from leadhound.store import Store
from leadhound.textutil import csv_cell, find_emails, strip_html


def took(fn, *a):
    t0 = time.monotonic()
    out = fn(*a)
    return out, time.monotonic() - t0


class SlowPatternTests(unittest.TestCase):
    """A hostile post or website must not be able to freeze a search."""

    def test_email_search_is_fast_on_hostile_text(self):
        for text in ("a." * 500_000, "a-b" * 300_000, "a@" * 400_000, "x" * 1_000_000, "<" * 1_000_000, "(at)" * 200_000):
            _, secs = took(find_emails, text)
            self.assertLess(secs, 3, f"{text[:6]!r}... took {secs:.1f}s")

    def test_html_stripping_is_fast_on_hostile_text(self):
        for text in ("<" * 1_000_000, "<br" * 500_000, "<a " * 300_000, "&" * 1_000_000):
            _, secs = took(strip_html, text)
            self.assertLess(secs, 12, f"{text[:6]!r}... took {secs:.1f}s")

    def test_real_addresses_are_still_found(self):
        self.assertEqual(find_emails("mail a@b.io or c [at] d [dot] com, logo@2x.png, John_Doe+x@Mail-Host.co.uk."),
                         ["a@b.io", "john_doe+x@mail-host.co.uk", "c@d.com"])   # plain addresses first, then the "[at]" ones
        self.assertEqual(find_emails("x" * 300 + " hire@acme.com " + "y" * 300), ["hire@acme.com"])
        self.assertEqual(find_emails("a@b@c.com"), ["b@c.com"])
        self.assertEqual(strip_html("<p>Hi &amp; bye</p><p>two</p>"), "Hi & bye\n\ntwo")

    def test_freelancer_budget_note_is_parsed_and_cannot_stall(self):
        xml = ("<rss><channel><item><title>Site</title><link>https://www.freelancer.com/projects/php/x-1.html</link>"
               "<description>{}</description><pubDate>Mon, 01 Jan 2035 00:00:00 +0000</pubDate></item></channel></rss>")
        leads = freelancer.parse(xml.format("Need a site. (Budget: $30 - $250 USD, Jobs: PHP, HTML)"), "php", 0)
        self.assertEqual((leads[0].budget, leads[0].body), ("$30 - $250 USD", "Need a site…"))
        self.assertIn("skill: PHP", leads[0].signals)
        hostile = "(Budget: x" * 200_000
        leads, secs = took(freelancer.parse, xml.format(hostile), "php", 0)
        self.assertLess(secs, 12)

    def test_csv_cells_cannot_run_as_formulas(self):
        self.assertEqual(csv_cell("=HYPERLINK(\"http://x\")"), "'=HYPERLINK(\"http://x\")")
        self.assertEqual([csv_cell(v) for v in ("@x", "+1", "-1", "ok", "", None, 5)], ["'@x", "'+1", "'-1", "ok", "", None, 5])


class MapTagTests(unittest.TestCase):
    def test_raw_map_tags_cannot_rewrite_the_query(self):
        self.assertEqual(osm.category_tag("shop=bicycle"), ("shop", "bicycle"))
        self.assertEqual(osm.category_tag("contact:website=yes"), ("contact:website", "yes"))
        for bad in ('shop=x"];out;//', 'sh"op=bicycle', "shop=a b", "=x", "shop=", "a=" + "b" * 80):
            with self.assertRaises(ValueError, msg=bad):
                osm.category_tag(bad)


class Receiver(http.server.BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        Receiver.seen.append((self.server.server_address[1], self.path, self.headers.get("Authorization"), self.headers.get("X-Api-Key")))
        if self.path == "/hop":
            self.send_response(302)
            self.send_header("Location", self.server.next_url)
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")


class RedirectTests(unittest.TestCase):
    def test_logins_do_not_follow_a_redirect_to_another_host(self):
        a, b = (http.server.ThreadingHTTPServer(("127.0.0.1", 0), Receiver) for _ in range(2))
        a.next_url = f"http://127.0.0.1:{b.server_address[1]}/landed"     # another port = another host
        b.next_url = ""
        self.addCleanup(lambda: [s.shutdown() or s.server_close() for s in (a, b)])
        for s in (a, b):
            threading.Thread(target=s.serve_forever, daemon=True).start()
        Receiver.seen.clear()
        r = Fetcher(min_interval=0, retries=0).request(f"http://127.0.0.1:{a.server_address[1]}/hop",
                                                       headers={"Authorization": "Bearer SECRET", "X-Api-Key": "SECRET"})
        self.assertEqual(r.status, 200)
        first, landed = Receiver.seen
        self.assertEqual(first[2:], ("Bearer SECRET", "SECRET"))   # the host we meant to talk to still gets it
        self.assertEqual(landed[1:], ("/landed", None, None))      # the host we were sent on to does not

    def test_only_web_addresses_are_fetched_or_followed(self):
        from leadhound.net import FetchError
        for url in ("file:///etc/passwd", "ftp://example.com/x", "gopher://x", "//example.com", "javascript:1"):
            with self.assertRaises(FetchError, msg=url):
                Fetcher(min_interval=0, retries=0).request(url)
        a = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
        a.next_url = "ftp://127.0.0.1:1/x"
        self.addCleanup(lambda: a.shutdown() or a.server_close())
        threading.Thread(target=a.serve_forever, daemon=True).start()
        r = Fetcher(min_interval=0, retries=0).request(f"http://127.0.0.1:{a.server_address[1]}/hop")
        self.assertEqual(r.status, 302)                  # the redirect to ftp: is not followed

    def test_logins_are_kept_for_a_redirect_inside_the_same_host(self):
        a = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
        a.next_url = f"http://127.0.0.1:{a.server_address[1]}/landed"
        self.addCleanup(lambda: a.shutdown() or a.server_close())
        threading.Thread(target=a.serve_forever, daemon=True).start()
        Receiver.seen.clear()
        Fetcher(min_interval=0, retries=0).request(f"http://127.0.0.1:{a.server_address[1]}/hop", headers={"Authorization": "Bearer SECRET"})
        self.assertEqual([s[2] for s in Receiver.seen], ["Bearer SECRET", "Bearer SECRET"])


def raw(port, method, path, headers=None, body=b"", host=None, timeout=5):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    c.putheader("Host", host or f"127.0.0.1:{port}")
    headers = dict(headers or {})
    if body and "Content-Length" not in headers:
        headers["Content-Length"] = str(len(body))
    for k, v in headers.items():
        c.putheader(k, v)
    c.endheaders(body or None)
    try:
        r = c.getresponse()
        data = r.read()
        return r.status, data
    finally:
        c.close()


class LocalServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.httpd, cls.token = make_server(os.path.join(cls.tmp.name, "d.db"), os.path.join(cls.tmp.name, "c.ini"), 0,
                                           fetcher_factory=lambda: FakeFetcher([]))
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    @property
    def h(self):
        return {"X-Leadhound-Token": self.token, "Content-Type": "application/json"}

    def test_bad_content_lengths_get_a_quick_400(self):
        for cl in ("-1", "99999999999", "abc", "200001"):
            status, _ = raw(self.port, "POST", "/api/config", {**self.h, "Content-Length": cl})
            self.assertEqual(status, 400, cl)

    def test_enormous_ids_are_just_not_found(self):
        self.assertEqual(raw(self.port, "GET", "/api/leads/99999999999999999999", self.h)[0], 404)
        self.assertEqual(raw(self.port, "POST", "/api/leads/bulk", self.h, json.dumps({"ids": [2**80], "status": "new"}).encode())[0], 400)

    def test_a_negative_limit_does_not_lift_the_cap(self):
        self.assertEqual(raw(self.port, "GET", "/api/leads?limit=-1", self.h)[0], 200)
        self.assertEqual(Store(":memory:").get(2**70), None)

    def test_an_unexpected_bug_answers_500_json_instead_of_dropping_the_connection(self):
        ctx = self.httpd.ctx
        with mock.patch.object(ctx.store, "stats", side_effect=RuntimeError("boom")), mock.patch("traceback.print_exc"):
            status, body = raw(self.port, "GET", "/api/stats", self.h)
        self.assertEqual(status, 500)
        self.assertNotIn(b"boom", body)                  # no internal details in the answer
        self.assertEqual(raw(self.port, "GET", "/api/meta", self.h)[0], 200)   # and the server carries on


class CloudLockoutTests(unittest.TestCase):
    PASSWORD = "correct horse battery"

    def start(self, hops=None):
        env = {} if hops is None else {"LEADHOUND_TRUST_PROXY": str(hops)}
        with mock.patch.dict(os.environ, env):
            if hops is None:
                os.environ.pop("LEADHOUND_TRUST_PROXY", None)
            tmp = tempfile.TemporaryDirectory()
            httpd, _ = make_server(os.path.join(tmp.name, "d.db"), os.path.join(tmp.name, "c.ini"), 0, host="127.0.0.1", password=self.PASSWORD)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close(), tmp.cleanup()))
        return httpd.server_address[1]

    def login(self, port, password, xff=None):
        h = {"Content-Type": "application/json", **({"X-Forwarded-For": xff} if xff else {})}
        return raw(port, "POST", "/api/login", h, json.dumps({"password": password}).encode())[0]

    def test_a_made_up_forwarded_address_does_not_reset_the_lockout(self):
        port = self.start()
        codes = [self.login(port, f"wrong-{i}", xff=f"203.0.113.{i}") for i in range(7)]
        self.assertEqual(codes, [401] * 5 + [429] * 2)
        self.assertEqual(self.login(port, self.PASSWORD, xff="198.51.100.77"), 429)   # even the right password, from a "new" address

    def test_behind_your_own_proxy_visitors_are_told_apart_by_the_address_it_added(self):
        port = self.start(hops=1)
        # the client writes "9.9.9.9" itself; the proxy then appends the real address after it
        codes = [self.login(port, f"wrong-{i}", xff=f"9.9.9.{i}, 10.0.0.1") for i in range(6)]
        self.assertEqual(codes, [401] * 5 + [429])                                    # one real visitor, however it writes the header
        self.assertEqual(self.login(port, self.PASSWORD, xff="9.9.9.1, 10.0.0.2"), 200)   # a different real visitor is unaffected


class LicenseServerHardeningTests(unittest.TestCase):
    SECRET = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")

    def setUp(self):
        self.ai_calls = 0
        self.service = licenseserver.Service(":memory:", self.SECRET, anthropic=self.fake_ai, gumroad=lambda k: {"success": False})
        self.httpd = licenseserver.make_server(self.service, 0, "127.0.0.1", timeout=1)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.httpd.shutdown(), self.httpd.server_close()))
        self.port = self.httpd.server_address[1]

    def fake_ai(self, system, prompt, max_tokens):
        self.ai_calls += 1
        return "ok"

    def post(self, path, body):
        status, data = raw(self.port, "POST", path, {"Content-Type": "application/json"}, json.dumps(body).encode())
        return status, json.loads(data)

    def trial_token(self, email="t@example.com", device="a" * 64):
        return self.post("/v1/trial", {"email": email, "device": device})[1]["token"]

    def test_odd_json_types_get_clean_errors(self):
        tok = self.trial_token()
        for body in ({"token": tok, "system": "s", "prompt": "hi", "max_tokens": "abc"},
                     {"token": tok, "system": "s", "prompt": "hi", "max_tokens": [1]},
                     {"token": 123, "system": "s", "prompt": "hi"}, {"token": [1], "system": "s", "prompt": "hi"},
                     {"token": {"a": 1}, "system": "s", "prompt": "hi"}):
            status, out = self.post("/v1/ai", body)
            self.assertIn(status, (200, 402), body)       # answered with JSON, never a dropped connection
            self.assertTrue(out)
        self.assertEqual(self.post("/v1/ai", {"token": tok, "system": "s", "prompt": "hi", "max_tokens": "abc"})[0], 200)

    def test_bad_lengths_and_stalled_clients_do_not_hold_the_server(self):
        status, _ = raw(self.port, "POST", "/v1/trial", {"Content-Length": "-1"})
        self.assertEqual(status, 400)
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        self.addCleanup(s.close)
        s.sendall(b"POST /v1/trial HTTP/1.1\r\nHost: x\r\nContent-Length: 50\r\n\r\n")   # promises a body, never sends it
        t0 = time.monotonic()
        self.assertEqual(s.recv(10), b"")                 # the server hangs up on its own
        self.assertLess(time.monotonic() - t0, 4)
        self.assertEqual(raw(self.port, "GET", "/health")[0], 200)

    def test_one_bad_day_cannot_cost_more_than_the_global_cap(self):
        with mock.patch.object(licenseserver, "AI_ALL_PER_DAY", 3), mock.patch.object(licenseserver, "TRIALS_PER_IP_PER_DAY", 100):
            toks = [self.trial_token(f"user{i}@example.com", f"{i:064x}") for i in range(4)]
            codes = [self.post("/v1/ai", {"token": t, "system": "s", "prompt": "hi"})[0] for t in toks]
        self.assertEqual(codes, [200, 200, 200, 503])
        self.assertEqual(self.ai_calls, 3)


class LicenseFileTests(unittest.TestCase):
    def test_the_downloadable_app_ignores_environment_overrides_of_the_license_settings(self):
        with mock.patch.dict(os.environ, {"LEADHOUND_PUBLIC_KEY": "", "LEADHOUND_LICENSE_SERVER": ""}):
            self.assertEqual(licensing._setting("LEADHOUND_PUBLIC_KEY", "abc"), "")   # a pip install or fork: override works
            with mock.patch.object(sys, "frozen", True, create=True):
                self.assertEqual(licensing._setting("LEADHOUND_PUBLIC_KEY", "abc"), "abc")
                self.assertEqual(licensing._setting("LEADHOUND_LICENSE_SERVER", "https://x"), "https://x")

    def test_tokens_that_are_not_text_are_just_invalid(self):
        for tok in (None, 5, [], {}, b"LH1.a.b"):
            self.assertIsNone(licensing.read_key(tok))


if __name__ == "__main__":
    unittest.main()
