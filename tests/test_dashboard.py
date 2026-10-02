"""Dashboard server: security, config, leads, bulk, export, background jobs."""
import http.client
import json
import os
import tempfile
import threading
import time
import unittest

from helpers import NOW, FakeFetcher, cfg  # noqa: F401

from leadhound import config, paths
from leadhound.dashboard.server import make_server
from leadhound.models import Lead
from leadhound.net import Response
from leadhound.store import Store

SHOP = ('<html><head><title>Shop</title><meta name="viewport" content="w"></head><body>'
        '<a href="mailto:hi@shop.example?subject=x">Mail us</a><a href="tel:+995 555 123456">Call</a>'
        'Sales: sales@shop.example</body></html>')
ROUTES = [("shop.example", Response(200, "http://shop.example", {"content-type": "text/html"}, SHOP.encode(), 0.1)),
          ("author_whoishiring", {"hits": []}), ("seeking%20freelancer", {"hits": []})]


class Gate(FakeFetcher):
    """Fetcher whose JSON calls block until released, to test busy/cancel."""
    event = threading.Event()

    def get_json(self, url, headers=None, data=None):
        self.event.wait(5)
        return super().get_json(url, headers, data)


class Base(unittest.TestCase):
    factory = staticmethod(lambda: FakeFetcher(ROUTES))

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.tmp.name, "d.db")
        cls.cfgp = os.path.join(cls.tmp.name, "config.ini")
        s = Store(cls.db)
        s.upsert(Lead(source="reddit", external_id="a", kind="post", title="=HYPERLINK(x)", url="https://x/a", score=80))
        s.upsert(Lead(source="reddit", external_id="b", kind="post", title="Lead b", url="https://x/b", score=20))
        s.close()
        cls.httpd, cls.token = make_server(cls.db, cls.cfgp, 0, cls.factory)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.jobs.wait(5)
        cls.tmp.cleanup()

    def req(self, method, path, body=None, token=True, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
        if token:
            h["X-Leadhound-Token"] = self.token
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        data = r.read()
        ctype = r.getheader("Content-Type", "")
        return r.status, (json.loads(data) if ctype.startswith("application/json") else data), r

    def wait_job(self, jid, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            _, j, _ = self.req("GET", f"/api/jobs/{jid}")
            if j["status"] != "running":
                return j
            time.sleep(0.05)
        self.fail("job did not finish")


class SecurityTest(Base):
    def test_token_host_static(self):
        self.assertEqual(self.req("GET", "/api/leads", token=False)[0], 403)
        self.assertEqual(self.req("GET", "/api/leads", host="evil.com")[0], 403)
        self.assertEqual(self.req("GET", "/", token=False, host="evil.com")[0], 403)
        status, page, r = self.req("GET", "/", token=False)
        self.assertEqual(status, 200)
        self.assertIn(self.token.encode(), page)
        self.assertIn("script-src 'self'", r.getheader("Content-Security-Policy"))
        self.assertEqual(self.req("GET", "/static/app.js", token=False)[0], 200)
        self.assertEqual(self.req("GET", "/static/leads.js", token=False)[2].getheader("Content-Type").split(";")[0], "text/javascript")
        for bad in ("/static/../server.py", "/static/%2e%2e/server.py", "/static/secret.js", "/server.py"):
            self.assertEqual(self.req("GET", bad, token=False)[0], 404, bad)
        self.assertEqual(self.req("POST", "/api/leads/1", None)[0], 200)  # empty body is valid json

    def test_bad_input(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.request("POST", "/api/config", body="not json", headers={"Host": f"127.0.0.1:{self.port}", "X-Leadhound-Token": self.token})
        self.assertEqual(c.getresponse().status, 400)
        self.assertEqual(self.req("POST", "/api/leads/bulk", {"ids": ["1; DROP TABLE leads"], "status": "new"})[0], 400)
        self.assertEqual(self.req("POST", "/api/leads/bulk", {"ids": [1], "status": "bogus"})[0], 400)
        self.assertEqual(self.req("GET", "/api/nope")[0], 404)


class DataTest(Base):
    def test_config_roundtrip_and_validation(self):
        status, m, _ = self.req("GET", "/api/meta")
        self.assertTrue(m["first_run"])
        self.assertIn("dentist", m["categories"])
        status, c, _ = self.req("POST", "/api/config", {"name": "Dato", "skills": "Python, Django ,", "min_budget": "250",
                                                         "pitch": "I build things\n[evil]\nllm_provider = x", "rss_feeds": "https://a.example/feed\nhttps://b.example/f"})
        self.assertEqual(status, 200)
        self.assertEqual(c["skills"], ["Python", "Django"])
        self.assertEqual(c["signature"], "Dato")
        self.assertFalse(self.req("GET", "/api/meta")[1]["first_run"])
        loaded = config.load(self.cfgp)
        self.assertEqual((loaded.name, loaded.min_budget, loaded.rss_feeds), ("Dato", 250, ["https://a.example/feed", "https://b.example/f"]))
        self.assertEqual(loaded.llm_provider, "none")  # newline injection neutralised
        self.assertIn("[evil]", loaded.pitch)
        for bad in ({"radius_m": 5}, {"rss_feeds": "ftp://x"}, {"llm_provider": "skynet"}, {"min_budget": -1}, {"max_age_days": 999}):
            self.assertEqual(self.req("POST", "/api/config", bad)[0], 400, bad)
        self.assertTrue(all(k in c["keys"] for k in ("github", "anthropic", "openai")))
        self.assertNotIn("sk-", json.dumps(c))

    def test_leads_bulk_export(self):
        _, leads, _ = self.req("GET", "/api/leads?sort=score")
        self.assertEqual([l["score"] for l in leads], [80, 20])
        low = [l["id"] for l in leads if l["score"] < 50]
        self.assertEqual(self.req("POST", "/api/leads/bulk", {"ids": low, "status": "ignored"})[1], {"updated": 1})
        self.assertEqual(len(self.req("GET", "/api/leads")[1]), 1)
        self.assertEqual(len(self.req("GET", "/api/leads?status=ignored")[1]), 1)
        status, body, r = self.req("GET", "/api/export")
        self.assertEqual(r.getheader("Content-Type").split(";")[0], "text/csv")
        self.assertIn(b"'=HYPERLINK(x)", body)  # spreadsheet formula neutralised
        self.assertEqual(self.req("POST", f"/api/leads/{low[0]}", {"status": "new", "notes": "x" * 30000})[0], 400)
        self.req("POST", f"/api/leads/{low[0]}", {"status": "new"})
        _, d, _ = self.req("POST", f"/api/leads/{leads[0]['id']}/draft", {"llm": False})
        self.assertEqual(d["engine"], "template")


class JobTest(Base):
    def test_audit_job_extracts_contacts(self):
        status, job, _ = self.req("POST", "/api/jobs", {"kind": "audit", "params": {"url": "shop.example"}})
        self.assertEqual(status, 200)
        done = self.wait_job(job["id"])
        self.assertEqual(done["status"], "done")
        _, lead, _ = self.req("GET", f"/api/leads/{done['result']['lead_id']}")
        self.assertEqual(lead["contact"], "hi@shop.example, sales@shop.example, +995 555 123456")
        self.assertEqual(lead["extra"]["email"], "hi@shop.example")
        self.assertIn("+15 public email", lead["reasons"])

    def test_scan_job_and_validation(self):
        for bad in ({"kind": "scan", "params": {"sources": ["myspace"]}}, {"kind": "local", "params": {"place": ""}},
                    {"kind": "local", "params": {"place": "Paris", "categories": ["spaceship"]}},
                    {"kind": "audit", "params": {"url": "not a url"}}, {"kind": "nope", "params": {}}):
            self.assertEqual(self.req("POST", "/api/jobs", bad)[0], 400, bad)
        _, job, _ = self.req("POST", "/api/jobs", {"kind": "scan", "params": {"sources": ["hn"]}})
        done = self.wait_job(job["id"])
        self.assertEqual((done["status"], done["result"]["found"]), ("done", {"hn": 0}))
        self.assertEqual(self.req("GET", "/api/jobs/current")[1]["id"], job["id"])
        self.assertEqual(self.req("GET", "/api/jobs/aaaaaaaaaa")[0], 404)


class BusyTest(Base):
    factory = staticmethod(lambda: Gate(ROUTES))

    def test_busy_and_cancel(self):
        Gate.event.clear()
        _, job, _ = self.req("POST", "/api/jobs", {"kind": "scan", "params": {"sources": ["hn", "github"]}})
        status, err, _ = self.req("POST", "/api/jobs", {"kind": "scan", "params": {}})
        self.assertEqual((status, "still running" in err["error"]), (409, True))
        self.assertEqual(self.req("POST", f"/api/jobs/{job['id']}/cancel", {})[1], {"cancelled": True})
        Gate.event.set()
        done = self.wait_job(job["id"])
        self.assertEqual(done["status"], "cancelled")
        self.assertNotIn("github", done["result"]["found"])  # stopped before the second source


class PathsTest(unittest.TestCase):
    def test_resolve(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as cwd:
            old = os.getcwd()
            os.environ["LEADHOUND_HOME"] = os.path.join(home, "lh")
            try:
                os.chdir(cwd)
                c, d = paths.resolve()
                self.assertEqual((c, d), (os.path.join(home, "lh", "config.ini"), os.path.join(home, "lh", "leadhound.db")))
                self.assertTrue(os.path.isdir(os.path.join(home, "lh")))
                open("leadhound.db", "w").close()  # older setups keep working
                self.assertEqual(paths.resolve()[1], os.path.join(os.path.realpath(cwd), "leadhound.db"))
                self.assertEqual(paths.resolve("x.ini", "y.db"), ("x.ini", "y.db"))
            finally:
                os.chdir(old)
                del os.environ["LEADHOUND_HOME"]


if __name__ == "__main__":
    unittest.main()


class ShortcutTest(unittest.TestCase):
    def test_build_and_create(self):
        from leadhound import shortcut
        name, text, ex = shortcut.build("linux", "/usr/bin/python3")
        self.assertEqual((name, ex), ("leadhound.desktop", True))
        self.assertIn('Exec="/usr/bin/python3" -m leadhound', text)
        self.assertIn("Terminal=true", text)
        self.assertEqual(shortcut.build("win32", r"C:\Python\python.exe")[0], "leadhound.bat")
        self.assertIn("\r\n", shortcut.build("win32", "p")[1])
        self.assertEqual(shortcut.build("darwin", "p")[0], "leadhound.command")
        with tempfile.TemporaryDirectory() as d:
            path = shortcut.create("linux", "/usr/bin/python3", d)
            self.assertTrue(os.access(path, os.X_OK))
