"""Follow-ups, proof of work, reply detection, insights, alerts, manual leads and demo data."""
import http.client
import json
import os
import tempfile
import threading
import time
import unittest

from helpers import cfg

from leadhound import config, draft, i18n
from leadhound.dashboard.server import make_server
from leadhound.langs import LANGUAGES
from leadhound.models import Lead
from leadhound.store import Store

DAY = 86400


def lead(eid="1", **kw):
    base = dict(source="reddit", external_id=eid, kind="post", title=f"[Hiring] Lead {eid}", url="https://x/" + eid,
                author="u/ann", contact="ann@example.com")
    return Lead(**{**base, **kw})


def backdate(s: Store, lead_id: int, days: float) -> None:
    s.db.execute("UPDATE activity SET at = at - ? WHERE lead_id = ?", (days * DAY, lead_id))
    s.db.commit()


class FollowupStoreTest(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")
        self.a, _ = self.s.upsert(lead("a"))
        self.b, _ = self.s.upsert(lead("b"))
        self.s.upsert(lead("c"))  # never contacted

    def test_due_after_the_wait_and_only_until_the_limit(self):
        self.s.update(self.a, status="contacted")
        self.s.update(self.b, status="contacted")
        self.assertEqual(self.s.followups_due(3, 2), [])  # just written to
        backdate(self.s, self.a, 4)
        due = self.s.followups_due(3, 2)
        self.assertEqual([(l.id, info["followups"], info["days"]) for l, info in due], [(self.a, 0, 4)])
        self.s.log(self.a, "followup", "email")
        self.assertEqual(self.s.followups_due(3, 2), [])  # the follow-up restarts the wait
        backdate(self.s, self.a, 4)
        self.assertEqual(len(self.s.followups_due(3, 2)), 1)
        self.s.log(self.a, "followup")
        backdate(self.s, self.a, 4)
        self.assertEqual(self.s.followups_due(3, 2), [])  # two follow-ups: done
        self.assertEqual(self.s.followups_due(3, 0), [])  # 0 = reminders off

    def test_stop_and_reply_end_the_reminders(self):
        for lid in (self.a, self.b):
            self.s.update(lid, status="contacted")
            backdate(self.s, lid, 5)
        self.s.log(self.a, "nofollow")
        self.s.update(self.b, status="replied")
        self.assertEqual(self.s.followups_due(3, 2), [])
        self.assertTrue(self.s.outreach(self.a)["stopped"])

    def test_follow_ups_count_as_sent_today(self):
        self.s.update(self.a, status="contacted")
        self.s.log(self.a, "followup")
        self.assertEqual(self.s.stats()["sent_today"], 2)
        with self.assertRaises(ValueError):
            self.s.log(self.a, "bogus")


class FollowupDraftTest(unittest.TestCase):
    def test_first_and_last_follow_up_in_every_language(self):
        c = cfg(name="Nino", signature="Nino", follow_up_max=2)
        post = lead(title="[Hiring] Logo for a bakery")
        first, last = draft.make_followup(post, c, 1), draft.make_followup(post, c, 2)
        self.assertIn('"Logo for a bakery"', first)
        self.assertIn(i18n.msg("en", "fu.ask"), first)
        self.assertIn(i18n.msg("en", "fu.last"), last)
        self.assertTrue(first.startswith("Hi ann,") and first.endswith("Nino"))
        for lang in LANGUAGES:
            biz = Lead(source="osm", external_id="1", kind="business", title="Café Sol", url="u", extra={"website": ""})
            text = draft.make_followup(biz, cfg(draft_language=lang, signature="N"), 1)
            self.assertNotIn("{", text, lang)
            self.assertTrue(text.startswith(i18n.msg(lang, "b.subject") + ":"), lang)


class Api(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db, self.conf = os.path.join(self.tmp.name, "d.db"), os.path.join(self.tmp.name, "config.ini")
        config.save(config.Config(name="Nino"), self.conf)
        s = Store(self.db)
        self.lid, _ = s.upsert(lead("a"))
        s.close()
        self.httpd, self.token = make_server(self.db, self.conf, 0)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.httpd.ctx.store.close()
        self.tmp.cleanup()

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        c.request(method, path, json.dumps(body) if body is not None else None,
                  {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json", "X-Leadhound-Token": self.token})
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, json.loads(raw) if raw[:1] in (b"{", b"[") else raw


class FollowupApiTest(Api):
    def test_follow_up_flow(self):
        self.assertEqual(self.req("POST", f"/api/leads/{self.lid}", {"status": "contacted", "draft": "first message"})[0], 200)
        self.assertEqual(self.req("GET", "/api/followups")[1], [])
        backdate(self.httpd.ctx.store, self.lid, 4)
        code, due = self.req("GET", "/api/followups")
        self.assertEqual((code, len(due), due[0]["outreach"]["max"]), (200, 1, 2))
        code, d = self.req("POST", f"/api/leads/{self.lid}/followup", {"action": "draft"})
        self.assertEqual((code, d["n"]), (200, 1))
        self.assertIn("Lead a", d["draft"])
        code, o = self.req("POST", f"/api/leads/{self.lid}/followup", {"action": "sent", "via": "gmail"})
        self.assertEqual((code, o["followups"]), (200, 1))
        self.assertEqual(self.req("GET", f"/api/leads/{self.lid}")[1]["draft"], "first message")  # first message kept
        self.assertEqual(self.req("GET", "/api/followups")[1], [])
        self.assertEqual(self.req("POST", f"/api/leads/{self.lid}/followup", {"action": "stop"})[1]["stopped"], True)
        self.assertEqual(self.req("POST", f"/api/leads/{self.lid}/followup", {"action": "nope"})[0], 400)
        self.assertEqual(self.req("POST", "/api/leads/999/followup", {"action": "draft"})[0], 404)
        self.assertEqual(self.req("POST", "/api/config", {"follow_up_days": 0})[0], 400)
        self.assertEqual(self.req("POST", "/api/config", {"follow_up_days": 5, "follow_up_max": 0})[1]["follow_up_max"], 0)


if __name__ == "__main__":
    unittest.main()
