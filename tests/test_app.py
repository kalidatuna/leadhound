"""Store, pipeline, CLI and dashboard API."""
import contextlib
import http.client
import io
import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timezone

from helpers import NOW, FakeFetcher, cfg

from leadhound import cli, config, pipeline
from leadhound.dashboard.server import make_server
from leadhound.models import Lead
from leadhound.store import Store

LISTING = ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry>'
           '<author><name>/u/bob</name></author><content type="html">Budget $400</content><id>t3_p1</id>'
           '<link href="https://www.reddit.com/r/forhire/comments/p1/"/>'
           f'<published>{datetime.fromtimestamp(NOW - 3600, timezone.utc).isoformat()}</published>'
           '<title>[Hiring] Python scraping script</title></entry></feed>')


def lead(eid="1", score=50, **kw):
    return Lead(source="reddit", external_id=eid, kind="post", title=f"Lead {eid}", url="https://x/" + eid,
                score=score, **kw)


class StoreTest(unittest.TestCase):
    def test_upsert_keeps_user_fields(self):
        s = Store(":memory:")
        lid, new = s.upsert(lead(score=40))
        self.assertTrue(new)
        s.update(lid, status="contacted", notes="called", draft="hi")
        lid2, new2 = s.upsert(lead(score=70, body="edited"))
        self.assertEqual((lid2, new2), (lid, False))
        got = s.get(lid)
        self.assertEqual((got.status, got.notes, got.draft, got.score, got.body), ("contacted", "called", "hi", 70, "edited"))
        with self.assertRaises(ValueError):
            s.update(lid, status="bogus")
        with self.assertRaises(ValueError):
            s.update(lid, score=1)

    def test_query(self):
        s = Store(":memory:")
        s.upsert(lead("a", 90))
        s.upsert(lead("b", 20))
        ign, _ = s.upsert(lead("c", 99))
        s.update(ign, status="ignored")
        self.assertEqual([l.external_id for l in s.query()], ["a", "b"])
        self.assertEqual([l.external_id for l in s.query(min_score=50)], ["a"])
        self.assertEqual([l.external_id for l in s.query(status="ignored")], ["c"])
        self.assertEqual(s.stats()["total"], 3)


class PipelineTest(unittest.TestCase):
    def test_scan_isolates_failures(self):
        s = Store(":memory:")
        f = FakeFetcher([("reddit.com", LISTING), ("jobs.example", RuntimeError("feed down"))])
        rep = pipeline.scan(s, cfg(), f, ["reddit", "rss", "nope"], now=NOW, log=lambda *_: None)
        self.assertEqual(rep.found, {"reddit": 1})
        self.assertIn("rss", rep.errors)
        self.assertIn("nope", rep.errors)
        top = s.query()[0]
        self.assertGreater(top.score, 60)
        self.assertEqual(top.budget, "$400")
        rep2 = pipeline.scan(s, cfg(), f, ["reddit"], now=NOW, log=lambda *_: None)
        self.assertEqual(rep2.new, {"reddit": 0})  # dedupe on rescan

    def test_local_without_audit(self):
        s = Store(":memory:")
        f = FakeFetcher([("nominatim", [{"lat": "41.7", "lon": "44.8", "display_name": "Tbilisi"}]),
                         ("overpass", {"elements": [
                             {"type": "node", "id": 1, "tags": {"name": "Has Site", "amenity": "dentist", "website": "x.ge"}},
                             {"type": "node", "id": 2, "tags": {"name": "No Site", "amenity": "dentist", "phone": "1"}}]})])
        rep = pipeline.local(s, cfg(), f, "Tbilisi", ["dentist"], 1000, do_audit=False, log=lambda *_: None)
        self.assertEqual(rep.new, {"osm": 2})
        self.assertEqual(s.query()[0].title, "No Site")


class CLITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "t.db")
        self.ini = os.path.join(self.tmp.name, "t.ini")
        s = Store(self.db)
        s.upsert(lead("a", 80, body="Need Django help", budget="$900"))
        s.close()

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["--db", self.db, "--config", self.ini, *args])
        return code, out.getvalue()

    def test_flow(self):
        self.assertEqual(self.run_cli("init")[0], 0)
        self.assertEqual(config.load(self.ini).llm_provider, "none")
        self.assertIn("already exists", self.run_cli("init")[1])
        code, out = self.run_cli("list")
        self.assertIn("Lead a", out)
        self.assertIn("[$900]", out)
        self.assertIn("why this score", self.run_cli("show", "1")[1])
        code, out = self.run_cli("draft", "1")
        self.assertIn("[template]", out)
        self.assertEqual(self.run_cli("status", "1", "contacted", "--note", "sent DM")[0], 0)
        self.assertIn("sent DM", self.run_cli("show", "1")[1])
        self.assertEqual(self.run_cli("show", "99")[0], 1)
        out_csv = os.path.join(self.tmp.name, "o.csv")
        self.run_cli("export", "--out", out_csv)
        with open(out_csv) as fh:
            self.assertIn("contacted", fh.read())


class DashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        db = os.path.join(cls.tmp.name, "d.db")
        s = Store(db)
        s.upsert(lead("a", 80))
        s.close()
        cls.httpd, cls.token = make_server(db, cfg(), 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.tmp.cleanup()

    def req(self, method, path, body=None, token=True, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": host or f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
        if token:
            h["X-Leadhound-Token"] = self.token
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        data = r.read()
        return r.status, (json.loads(data) if r.getheader("Content-Type", "").startswith("application/json") else data)

    def test_security(self):
        self.assertEqual(self.req("GET", "/api/leads", token=False)[0], 403)
        self.assertEqual(self.req("GET", "/api/leads", host="evil.com")[0], 403)
        self.assertEqual(self.req("GET", "/", token=False, host="evil.com")[0], 403)
        status, page = self.req("GET", "/", token=False)
        self.assertEqual(status, 200)
        self.assertIn(self.token.encode(), page)

    def test_api(self):
        status, leads = self.req("GET", "/api/leads?min=50")
        self.assertEqual((status, len(leads)), (200, 1))
        lid = leads[0]["id"]
        status, l = self.req("POST", f"/api/leads/{lid}", {"status": "shortlisted", "notes": "good"})
        self.assertEqual((status, l["status"], l["notes"]), (200, "shortlisted", "good"))
        self.assertEqual(self.req("POST", f"/api/leads/{lid}", {"status": "bad"})[0], 400)
        status, d = self.req("POST", f"/api/leads/{lid}/draft", {"llm": False})
        self.assertEqual((status, d["engine"]), (200, "template"))
        self.assertEqual(self.req("GET", "/api/leads/999")[0], 404)
        self.assertEqual(self.req("GET", "/api/stats")[1]["by_status"], {"shortlisted": 1})


if __name__ == "__main__":
    unittest.main()
