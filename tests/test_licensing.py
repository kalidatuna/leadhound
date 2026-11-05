"""Ed25519, license keys, the trial, and the API gates for the few Pro features."""
import http.client
import json
import os
import tempfile
import threading
import unittest

from helpers import cfg  # noqa: F401

from leadhound import ed25519, licensing
from leadhound.dashboard.server import make_server
from leadhound.models import Lead
from leadhound.store import Store

SECRET = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
PUBLIC = ed25519.public_key(SECRET).hex()
T0 = 1_790_000_000.0
DAY = 86400


class Ed25519Tests(unittest.TestCase):
    def test_rfc8032_vector_1(self):
        pub = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        sig = bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
        self.assertEqual(ed25519.public_key(SECRET), pub)
        self.assertEqual(ed25519.sign(SECRET, b""), sig)
        self.assertTrue(ed25519.verify(pub, b"", sig))
        self.assertFalse(ed25519.verify(pub, b"x", sig))
        self.assertFalse(ed25519.verify(pub, b"", sig[:-1] + bytes([sig[-1] ^ 1])))
        self.assertFalse(ed25519.verify(pub, b"", b"\0" * 64))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (licensing.PUBLIC_KEY_HEX, licensing.SERVER)
        licensing.PUBLIC_KEY_HEX, licensing.SERVER = PUBLIC, ""  # these tests cover the plain local clock
        self.now = T0
        self.lic = licensing.License(os.path.join(self.tmp.name, "license.json"), clock=lambda: self.now)

    def tearDown(self):
        licensing.PUBLIC_KEY_HEX, licensing.SERVER = self.old
        self.tmp.cleanup()


class PlanTests(Base):
    def test_unconfigured_builds_unlock_everything(self):
        licensing.PUBLIC_KEY_HEX = ""
        st = self.lic.status()
        self.assertEqual((st["plan"], st["configured"]), ("pro", False))
        self.lic.require("autosearch")  # no error

    def test_trial_lasts_14_days_then_free(self):
        st = self.lic.status()
        self.assertEqual((st["plan"], st["trial_left"]), ("trial", 7))
        self.now = T0 + 4 * DAY
        self.assertEqual(self.lic.status()["trial_left"], 3)
        self.lic.require("ai")
        self.now = T0 + 7 * DAY + 5
        self.assertEqual(self.lic.status()["plan"], "free")
        for feature in ("ai", "autosearch", "replies"):
            with self.assertRaises(licensing.ProRequired):
                self.lic.require(feature)
        with self.assertRaises(ValueError):
            self.lic.require("send")  # sending is not a Pro feature any more

    def test_a_genuine_key_unlocks_pro_until_it_ends(self):
        self.lic.status()
        self.now = T0 + 30 * DAY  # trial over
        key = licensing.make_key(SECRET, "ann@example.com", 31, now=self.now)
        st = self.lic.activate(key)
        self.assertEqual((st["plan"], st["email"], st["key_state"]), ("pro", "ann@example.com", "ok"))
        self.lic.require("replies")
        self.now += 32 * DAY
        st = self.lic.status()
        self.assertEqual((st["plan"], st["key_state"]), ("free", "expired"))

    def test_forged_tampered_and_foreign_keys_are_refused(self):
        key = licensing.make_key(SECRET, "ann@example.com", 31, now=T0)
        self.assertIsNotNone(licensing.read_key(key))
        tag, body, sig = key.split(".")
        forged = ".".join([tag, licensing._b64(json.dumps({"v": 1, "plan": "pro", "email": "me", "exp": int(T0 + 9e9)}).encode()), sig])
        for bad in (forged, key[:-3] + "AAA", "LH1.x.y", "", "garbage"):
            self.assertIsNone(licensing.read_key(bad), bad)
            with self.assertRaises(ValueError):
                self.lic.activate(bad)
        other = bytes(range(32))
        self.assertIsNone(licensing.read_key(licensing.make_key(other, "x@y.z", 31, now=T0)))

    def test_removing_the_key_goes_back_to_trial_or_free(self):
        self.lic.activate(licensing.make_key(SECRET, "ann@example.com", 31, now=T0))
        self.assertEqual(self.lic.remove_key()["plan"], "trial")


class ApiGateTests(Base):
    def setUp(self):
        super().setUp()
        db, conf = os.path.join(self.tmp.name, "d.db"), os.path.join(self.tmp.name, "config.ini")
        s = Store(db)
        for i in range(15):
            s.upsert(Lead(source="reddit", external_id=str(i), kind="post", title=f"Lead {i}", url="https://x/a", score=90 - i))
        s.close()
        self.httpd, self.token = make_server(db, conf, 0)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        # make the server's license object use our clock, and end the trial
        ctx_lic = self.httpd.ctx.license
        ctx_lic.clock = lambda: self.now
        ctx_lic.status()
        self.now = T0 + 30 * DAY
        self.ctx_lic = ctx_lic

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        c.request(method, path, json.dumps(body) if body is not None else None,
                  {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json", "X-Leadhound-Token": self.token})
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, json.loads(raw)

    def test_free_plan_gates_only_pro_features_with_402(self):
        self.assertEqual(self.req("GET", "/api/plan")[1]["plan"], "free")
        self.assertEqual(self.req("POST", "/api/config", {"auto_scan_hours": 6})[0], 402)
        self.assertEqual(self.req("POST", "/api/config", {"llm_provider": "leadhound"})[0], 200)
        self.assertEqual(self.req("POST", "/api/leads/1/draft", {"llm": True})[0], 402)  # the hosted AI
        self.assertEqual(self.req("POST", "/api/config", {"llm_provider": "none"})[0], 200)
        self.assertEqual(self.req("POST", "/api/leads/1/draft", {"llm": True})[0], 200)  # your own AI (none here: template)
        self.assertEqual(self.req("POST", "/api/config", {"name": "Ann"})[0], 200)
        # everything you do yourself is free: sending, connecting accounts, local businesses, website checks
        self.assertEqual(self.req("POST", "/api/leads/1/send", {"channel": "email", "to": "a@b.co", "body": "x"})[0], 400)
        self.assertEqual(self.req("POST", "/api/accounts/email", {"action": "connect", "fields": {}})[0], 400)
        self.assertEqual(self.req("POST", "/api/jobs", {"kind": "audit", "params": {"url": "nodots"}})[0], 400)

    def test_free_plan_shows_every_lead(self):
        code, leads = self.req("GET", "/api/leads?limit=100")
        self.assertEqual((code, len(leads)), (200, 15))
        self.assertEqual(leads[0]["score"], 90)

    def test_automatic_search_stops_when_pro_ends(self):
        self.assertFalse(self.httpd.auto.allowed())
        self.ctx_lic.activate(licensing.make_key(SECRET, "ann@example.com", 31, now=self.now))
        self.assertTrue(self.httpd.auto.allowed())

    def test_a_key_unlocks_everything_and_can_be_removed(self):
        code, body = self.req("POST", "/api/plan", {"action": "activate", "key": "nonsense"})
        self.assertEqual(code, 400)
        key = licensing.make_key(SECRET, "ann@example.com", 31, now=self.now)
        code, st = self.req("POST", "/api/plan", {"action": "activate", "key": key})
        self.assertEqual((code, st["plan"]), (200, "pro"))
        self.assertEqual(self.req("POST", "/api/config", {"auto_scan_hours": 6})[0], 200)
        self.assertEqual(self.req("POST", "/api/config", {"auto_scan_hours": 6})[0], 200)
        self.assertEqual(self.req("POST", "/api/plan", {"action": "remove"})[1]["plan"], "free")


if __name__ == "__main__":
    unittest.main()
