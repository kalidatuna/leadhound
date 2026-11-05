"""Follow-ups, proof of work, reply detection, insights, alerts, manual leads and demo data."""
import http.client
import json
import os
import tempfile
import threading
import time
import unittest

from helpers import cfg

import imaplib

from leadhound import accounts, alerts, config, draft, i18n, licensing, replies
from leadhound.jobs import AutoScanner, Job
from leadhound.send import SendError
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


class ProofTest(unittest.TestCase):
    PROOF = ["wordpress, booking: Rebuilt a dental clinic site with online booking: https://x.dev/clinic",
             "logo, brand: Designed logos for 30 cafes", "no separator here", "empty:  "]

    def test_the_best_matching_line_goes_into_english_drafts_only(self):
        c = cfg(proof=self.PROOF)
        wp = lead(title="[Hiring] WordPress booking plugin fix")
        self.assertEqual(draft.pick_proof(wp, c), "Rebuilt a dental clinic site with online booking: https://x.dev/clinic")
        self.assertIn("https://x.dev/clinic\n", draft.make_draft(wp, c)[0])
        self.assertEqual(draft.pick_proof(lead(title="Need a brand refresh and logo"), c), "Designed logos for 30 cafes.")
        self.assertEqual(draft.pick_proof(lead(title="Translate a menu"), c), "")  # unrelated proof reads like spam
        es = draft.make_draft(wp, cfg(proof=self.PROOF, draft_language="es"))[0]
        self.assertNotIn("Rebuilt", es)
        self.assertIn("Rebuilt a dental clinic", draft.llm_prompt(wp, c, "es"))

    def test_settings_round_trip(self):
        c = config.from_dict(config.Config(), {"proof": "a, b: one\n\nc: two"})
        self.assertEqual(c.proof, ["a, b: one", "c: two"])
        with tempfile.TemporaryDirectory() as d:
            config.save(c, os.path.join(d, "c.ini"))
            self.assertEqual(config.load(os.path.join(d, "c.ini")).proof, ["a, b: one", "c: two"])


class InsightTest(unittest.TestCase):
    def test_reply_rates_and_tips_state_their_numbers(self):
        s = Store(":memory:")
        for i in range(10):  # reddit: 10 messages, no reply
            lid, _ = s.upsert(lead(f"r{i}", score=40))
            s.update(lid, status="contacted")
        for i in range(4):  # freelancer: 4 messages, 2 replies (one won), all high scores
            lid, _ = s.upsert(lead(f"f{i}", source="freelancer", score=80))
            s.update(lid, status="contacted")
            if i == 0:
                s.update(lid, status="won")
            if i == 1:
                s.log(lid, "replied", "email")
        s.upsert(lead("never"))  # not contacted: not counted
        ins = s.insights()
        self.assertEqual(ins["contacted"], 14)
        self.assertEqual([(x["source"], x["contacted"], x["replied"], x["won"], x["rate"]) for x in ins["sources"]],
                         [("freelancer", 4, 2, 1, 50), ("reddit", 10, 0, 0, 0)])
        self.assertEqual(ins["tips"], [["best", {"src": "freelancer", "rate": 50, "n": 4}],
                                       ["weak", {"src": "reddit", "n": 10}]])  # high band has only 4: no score tip yet
        self.assertEqual(Store(":memory:").insights(), {"contacted": 0, "sources": [], "tips": []})


class FakeImap:
    """Answers SEARCH FROM "x" SINCE d from a fixed set of senders. Records what it was asked."""

    def __init__(self, senders=(), password="app-password-1"):
        self.senders, self.password, self.calls, self.readonly = set(senders), password, [], None

    def __call__(self, host):
        self.host = host
        return self

    def login(self, user, pw):
        if pw != self.password:
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    def select(self, box, readonly=False):
        self.readonly = readonly
        return "OK", [b"3"]

    def search(self, charset, *crit):
        self.calls.append(crit)
        return "OK", [b"7 9" if crit[1].strip('"') in self.senders else b""]

    def logout(self):
        pass


class ReplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.acc = accounts.Accounts(os.path.join(self.tmp.name, "accounts.json"))
        self.s = Store(":memory:")
        self.a, _ = self.s.upsert(lead("a", contact="ann@example.com"))
        self.b, _ = self.s.upsert(lead("b", contact="bob@example.com, +995 555 12 34 56"))
        self.c, _ = self.s.upsert(lead("c", contact="reddit DM: u/cat"))  # no email: nothing to look for
        for lid in (self.a, self.b, self.c):
            self.s.update(lid, status="contacted")
        self.lock = threading.Lock()

    def tearDown(self):
        self.tmp.cleanup()

    def connect(self, host="smtp.gmail.com"):
        self.acc.connect("email", {"provider": "gmail", "address": "me@gmail.com", "password": "app-password-1", "host": host, "port": 587})

    def test_moves_leads_that_answered_and_only_reads(self):
        self.connect()
        imap = FakeImap({"bob@example.com"})
        res = replies.check(self.acc, self.s, self.lock, imap_factory=imap)
        self.assertEqual(res, {"checked": 2, "replied": 1})
        self.assertEqual((self.s.get(self.b).status, self.s.get(self.a).status), ("replied", "contacted"))
        self.assertTrue(imap.readonly)
        self.assertEqual(imap.host, "imap.gmail.com")
        self.assertEqual(imap.calls[0][:2], ("FROM", '"ann@example.com"'))
        self.assertRegex(imap.calls[0][3], r"^\d\d-[A-Z][a-z]{2}-\d{4}$")
        self.assertEqual(replies.check(self.acc, self.s, self.lock, imap_factory=FakeImap({"bob@example.com"}))["replied"], 0)

    def test_errors_are_clear(self):
        with self.assertRaises(SendError):  # nothing connected
            replies.check(self.acc, self.s, self.lock, imap_factory=FakeImap())
        self.connect()
        with self.assertRaisesRegex(SendError, "refused the login"):
            replies.check(self.acc, self.s, self.lock, imap_factory=FakeImap(password="other"))

    def test_imap_host(self):
        self.assertEqual(replies.imap_host({"host": "smtp-mail.outlook.com"}), "outlook.office365.com")
        self.assertEqual(replies.imap_host({"host": "smtp.fastmail.com"}), "imap.fastmail.com")
        self.assertEqual(replies.imap_host({"host": "mail.example.org"}), "imap.example.org")
        self.assertEqual(replies.imap_host({"host": "localhost"}), "localhost")  # a local test server
        for bad, cloud in (("bad host", False), ("localhost", True)):
            with self.assertRaises(SendError):
                replies.imap_host({"host": bad}, cloud=cloud)

    def test_old_and_answered_leads_are_skipped(self):
        backdate(self.s, self.a, 90)
        self.s.update(self.b, status="won")
        self.assertEqual(replies.candidates(self.s), [])


class AlertTest(unittest.TestCase):
    """After an automatic search: replies are checked, then the best new matches are emailed to yourself."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conf = os.path.join(self.tmp.name, "config.ini")
        config.save(config.Config(alert_email=True, alert_min_score=60), self.conf)
        self.acc = accounts.Accounts(os.path.join(self.tmp.name, "accounts.json"))
        self.acc.connect("email", {"provider": "gmail", "address": "me@gmail.com", "password": "app-password-1",
                                   "host": "smtp.gmail.com", "port": 587})
        self.store = Store(":memory:")
        self.job = Job("scan", {}, auto=True)
        self.job.status = "done"
        self.job.started = time.time() - 5
        self.store.upsert(lead("hot", score=82, title="[Hiring] Shopify fix", budget="$300"))
        self.store.upsert(lead("weak", score=30))
        old, _ = self.store.upsert(lead("old", score=90))
        self.store.db.execute("UPDATE leads SET first_seen = first_seen - 999 WHERE id = ?", (old,))  # found by an earlier search
        self.sent = []
        self.lic = licensing.License(os.path.join(self.tmp.name, "license.json"))

        class Ctx:
            pass
        self.ctx = Ctx()
        self.ctx.license, self.ctx.accounts, self.ctx.store = self.lic, self.acc, self.store
        self.ctx.lock, self.ctx.auth, self.ctx.config_path = threading.Lock(), None, self.conf

    def tearDown(self):
        self.tmp.cleanup()

    def run_alert(self):
        return alerts.after_auto_search(self.ctx, self.job, send=lambda *a: self.sent.append(a), imap_factory=FakeImap())

    def test_emails_only_new_strong_matches_to_yourself(self):
        out = self.run_alert()
        self.assertEqual(out, {"replied": 0, "emailed": 1})
        (acct, to, subject, body), = self.sent
        self.assertEqual((to, subject), ("me@gmail.com", "leadhound: 1 new matches for you"))
        self.assertIn("[82] [Hiring] Shopify fix", body)
        self.assertIn("$300", body)
        self.assertNotIn("Lead weak", body)
        self.assertNotIn("Lead old", body)

    def test_nothing_for_clicks_quiet_searches_or_free_plans(self):
        self.job.auto = False
        self.assertEqual(self.run_alert()["emailed"], 0)
        self.job.auto = True
        config.save(config.Config(alert_email=False), self.conf)
        self.assertEqual(self.run_alert()["emailed"], 0)
        config.save(config.Config(alert_email=True, alert_min_score=95), self.conf)
        self.assertEqual(self.run_alert()["emailed"], 0)
        old = licensing.PUBLIC_KEY_HEX, licensing.SERVER
        licensing.PUBLIC_KEY_HEX, licensing.SERVER = "b8" * 32, ""
        try:
            with open(self.lic.path, "w") as f:
                json.dump({"first_use": time.time() - 30 * DAY}, f)  # the local trial ended long ago
            self.assertEqual(self.lic.status()["plan"], "free")
            config.save(config.Config(alert_email=True), self.conf)
            self.assertEqual(self.run_alert()["emailed"], 0)
        finally:
            licensing.PUBLIC_KEY_HEX, licensing.SERVER = old
        self.assertEqual(self.sent, [])

    def test_the_scheduler_marks_its_jobs_and_runs_the_hooks(self):
        from leadhound.jobs import JobManager
        from helpers import FakeFetcher
        db = os.path.join(self.tmp.name, "d.db")
        jm = JobManager(db, self.conf, fetcher_factory=lambda: FakeFetcher([]))
        seen = []
        jm.on_done.append(lambda j: seen.append((j.auto, j.status)))
        jm.on_done.append(lambda j: 1 / 0)  # a broken hook is logged, never fatal
        config.save(config.Config(auto_scan_hours=6, freelancer=False, hn=False, github=False, reddit_subreddits=[]), self.conf)
        auto = AutoScanner(jm, os.path.join(self.tmp.name, "state.json"))
        self.assertTrue(auto.tick())
        jm.wait()
        self.assertEqual(seen, [(True, "done")])
        self.assertTrue(any("after search" in line for line in jm.current.log))
        self.assertTrue(jm.current.to_dict()["auto"])


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

    def test_reply_check_needs_an_email_account(self):
        code, body = self.req("POST", "/api/replies", {})
        self.assertEqual(code, 400)  # licensing is off in tests: allowed, but nothing connected
        self.assertIn("Connect your email", body["error"])


if __name__ == "__main__":
    unittest.main()
