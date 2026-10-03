"""Cloud mode login, auto-search scheduler, update/restart guards, SSRF guard, translation endpoints."""
import http.client
import json
import os
import re
import tempfile
import threading
import unittest

from helpers import FakeFetcher  # noqa: F401  (sets sys.path)

from leadhound import config
from leadhound.dashboard.auth import Auth, TooManyAttempts, cookie_value
from leadhound.dashboard.server import make_server
from leadhound.jobs import AutoScanner, JobManager

PASSWORD = "correct horse battery"


class AuthUnitTest(unittest.TestCase):
    def test_login_and_rate_limit(self):
        a = Auth(PASSWORD)
        tok = a.login("1.2.3.4", PASSWORD)
        self.assertTrue(a.valid(tok))
        a.logout(tok)
        self.assertFalse(a.valid(tok))
        for _ in range(5):
            self.assertIsNone(a.login("5.6.7.8", "nope"))
        with self.assertRaises(TooManyAttempts):
            a.login("5.6.7.8", PASSWORD)  # locked out even with the right password
        self.assertTrue(a.login("9.9.9.9", PASSWORD))  # other clients unaffected
        with self.assertRaises(ValueError):
            Auth("short")
        self.assertEqual(cookie_value("a=1; lh_session=xyz; b=2"), "xyz")


class CloudServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cfgp = os.path.join(cls.tmp.name, "config.ini")
        cls.httpd, cls.token = make_server(os.path.join(cls.tmp.name, "d.db"), cls.cfgp, 0, host="127.0.0.1",
                                           password=PASSWORD, fetcher_factory=lambda: FakeFetcher([]))
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.tmp.cleanup()

    def req(self, method, path, body=None, cookie=None, token=None, host=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or f"leads.example.com", "Content-Type": "application/json", **(headers or {})}
        if cookie:
            h["Cookie"] = f"lh_session={cookie}"
        if token:
            h["X-Leadhound-Token"] = token
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        return r.status, r.read(), r

    def test_login_flow(self):
        status, page, _ = self.req("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"login.js", page)
        self.assertNotIn(self.token.encode(), page)  # no token before sign-in
        self.assertEqual(self.req("GET", "/api/meta", token=self.token)[0], 401)  # token alone is not enough
        self.assertEqual(self.req("POST", "/api/login", {"password": "wrong"})[0], 401)
        self.assertEqual(self.req("POST", "/api/login", {"password": PASSWORD}, headers={"Origin": "https://evil.example"})[0], 403)
        status, _, r = self.req("POST", "/api/login", {"password": PASSWORD}, headers={"X-Forwarded-Proto": "https"})
        self.assertEqual(status, 200)
        set_cookie = r.getheader("Set-Cookie")
        for flag in ("HttpOnly", "SameSite=Strict", "Secure"):
            self.assertIn(flag, set_cookie)
        session = re.search(r"lh_session=([^;]+)", set_cookie).group(1)
        status, page, _ = self.req("GET", "/", cookie=session)
        self.assertIn(self.token.encode(), page)
        self.assertEqual(self.req("GET", "/api/meta", cookie=session)[0], 403)  # cookie alone is not enough either
        status, body, _ = self.req("GET", "/api/meta", cookie=session, token=self.token)
        meta = json.loads(body)
        self.assertTrue(meta["cloud"])
        self.assertEqual(len(meta["languages"]), 11)
        # cloud: private addresses can't be audited from the server
        status, body, _ = self.req("POST", "/api/jobs", {"kind": "audit", "params": {"url": "http://169.254.169.254/latest"}}, cookie=session, token=self.token)
        self.assertEqual(status, 400)
        self.assertEqual(self.req("POST", "/api/restart", {}, cookie=session, token=self.token)[0], 400)
        self.req("POST", "/api/logout", {}, cookie=session)
        self.assertEqual(self.req("GET", "/api/meta", cookie=session, token=self.token)[0], 401)


class LocalServerExtrasTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.httpd, cls.token = make_server(os.path.join(cls.tmp.name, "d.db"), os.path.join(cls.tmp.name, "c.ini"), 0,
                                           fetcher_factory=lambda: FakeFetcher([("pypi.org", {"info": {"version": "0.0.1"}})]))
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.tmp.cleanup()

    def get(self, path, token=True, method="GET", body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
        if token:
            h["X-Leadhound-Token"] = self.token
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        return r.status, r.read()

    def test_i18n_locales_update_profession(self):
        status, body = self.get("/api/i18n/ka")
        self.assertEqual(status, 200)
        self.assertIn("why.skills", json.loads(body))
        self.assertEqual(self.get("/api/i18n/xx")[0], 404)
        self.assertEqual(self.get("/static/locales/ar.json", token=False)[0], 200)
        for bad in ("/static/locales/xx.json", "/static/locales/../server.py", "/static/locales/en.json.bak"):
            self.assertEqual(self.get(bad, token=False)[0], 404, bad)
        status, body = self.get("/api/update")
        self.assertEqual((status, json.loads(body)["newer"]), (200, False))
        status, body = self.get("/api/config", method="POST", body={"profession_defaults": "photographer", "name": "Gio"})
        c = json.loads(body)
        self.assertEqual((status, c["profession"], c["name"]), (200, "photographer", "Gio"))
        self.assertIn("Photography", c["freelancer_categories"])
        self.assertEqual(self.get("/api/config", method="POST", body={"profession_defaults": "wizard"})[0], 400)
        status, body = self.get("/api/jobs", method="POST", body={"kind": "update", "params": {}})
        self.assertEqual(status, 400)  # running from a git checkout: updates come from git, not pip


class SchedulerTest(unittest.TestCase):
    def test_tick(self):
        with tempfile.TemporaryDirectory() as d:
            cfgp = os.path.join(d, "c.ini")
            config.save(config.Config(auto_scan_hours=6, hn=False, github=False, freelancer=False, reddit_subreddits=[]), cfgp)
            jm = JobManager(os.path.join(d, "d.db"), cfgp, fetcher_factory=lambda: FakeFetcher([]))
            auto = AutoScanner(jm, os.path.join(d, "state.json"))
            self.assertTrue(auto.tick(now=1_000_000))
            jm.wait()
            self.assertFalse(auto.tick(now=1_000_000 + 3600))  # not due yet
            self.assertTrue(auto.tick(now=1_000_000 + 7 * 3600))
            jm.wait()
            config.save(config.Config(auto_scan_hours=0), cfgp)
            self.assertFalse(auto.tick(now=2_000_000))  # off


if __name__ == "__main__":
    unittest.main()
