"""The trial: free taste, email sign-up, one trial per person, expiry, and the paid AI on the seller's server."""
import json
import os
import tempfile
import threading
import unittest

from helpers import cfg  # noqa: F401

from leadhound import licensing, licenseserver
from leadhound.dashboard.server import make_server
from leadhound.models import Lead
from leadhound.store import Store

SECRET = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
PUBLIC = licensing.public_hex(SECRET)
T0 = 1_790_000_000.0
DAY = 86400


class Clock:
    now = T0

    def __call__(self):
        return self.now


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.ai_calls = []
        self.gumroad = {"GOOD-KEY-1234": {"success": True, "purchase": {"email": "buyer@example.com", "recurrence": "monthly"}},
                        "REFUNDED-1234": {"success": True, "purchase": {"email": "r@example.com", "refunded": True}},
                        "ENDED-KEY-1234": {"success": True, "purchase": {"email": "e@example.com", "subscription_ended_at": "2026-01-01"}}}
        self.service = licenseserver.Service(":memory:", SECRET, clock=self.clock, anthropic=self.fake_ai,
                                             gumroad=lambda k: self.gumroad.get(k, {"success": False}))
        self.httpd = licenseserver.make_server(self.service, 0, "127.0.0.1")
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.old = (licensing.PUBLIC_KEY_HEX, licensing.SERVER)
        licensing.PUBLIC_KEY_HEX = PUBLIC
        licensing.SERVER = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.lic = licensing.License(os.path.join(self.tmp.name, "license.json"), clock=self.clock)

    def fake_ai(self, system, prompt, max_tokens):
        self.ai_calls.append((system, prompt, max_tokens))
        return "Hi there, a short message."

    def tearDown(self):
        licensing.PUBLIC_KEY_HEX, licensing.SERVER = self.old
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def other_copy(self):
        return licensing.License(os.path.join(self.tmp.name, "other", "license.json"), clock=self.clock)


class TasteAndSignupTests(Base):
    def test_taste_counts_uses_then_asks_for_an_email(self):
        st = self.lic.status()
        self.assertEqual((st["plan"], st["uses_left"]), ("taste", 7))
        for _ in range(7):
            self.lic.count_use()
        st = self.lic.status()
        self.assertEqual((st["plan"], st["need_signup"], st["trial_used"]), ("free", True, False))
        with self.assertRaises(licensing.ProRequired):
            self.lic.require("send")

    def test_taste_also_ends_after_seven_days(self):
        self.lic.status()
        self.clock.now = T0 + 7 * DAY + 5
        self.assertTrue(self.lic.status()["need_signup"])

    def test_signup_gives_a_seven_day_trial_that_then_ends_for_good(self):
        for _ in range(7):
            self.lic.count_use()
        st = self.lic.signup("Ann@Example.com")
        self.assertEqual((st["plan"], st["trial_left"], st["email"]), ("trial", 7, "ann@example.com"))
        self.lic.require("ai")
        self.clock.now = T0 + 7 * DAY + 5
        st = self.lic.status()
        self.assertEqual((st["plan"], st["trial_used"], st["need_signup"]), ("free", True, False))
        with self.assertRaises(ValueError):  # asking again returns the same, ended, trial
            self.lic.signup("ann@example.com")
        self.assertEqual(self.lic.status()["plan"], "free")

    def test_deleting_the_license_file_or_reinstalling_does_not_restart_the_trial(self):
        self.lic.signup("ann@example.com")
        self.clock.now = T0 + 8 * DAY
        fresh = self.other_copy()  # same computer (same device code), no local file
        self.assertEqual(fresh.status()["plan"], "taste")  # the free taste is local, but the trial cannot be renewed:
        with self.assertRaises(ValueError):
            fresh.signup("brand-new@example.com")  # new email, same computer
        with self.assertRaises(ValueError):
            fresh.signup("ann+again@example.com")  # same inbox written differently

    def test_gmail_dots_and_tags_count_as_one_person(self):
        self.assertEqual(licenseserver.canonical_email("A.N.n+x@Gmail.com"), "ann@gmail.com")
        self.assertEqual(licenseserver.canonical_email("ann+x@example.com"), "ann@example.com")

    def test_bad_email_bad_device_and_ip_limit(self):
        with self.assertRaises(ValueError):
            self.lic.signup("not an email")
        with self.assertRaises(licenseserver.ServiceError):
            self.service.trial("1.1.1.1", "ok@example.com", "short")
        for i in range(3):
            self.service.trial("9.9.9.9", f"u{i}@example.com", f"{i:064x}")
        with self.assertRaises(licenseserver.ServiceError) as cm:
            self.service.trial("9.9.9.9", "u9@example.com", f"{9:064x}")
        self.assertEqual(cm.exception.code, 429)

    def test_a_trial_token_cannot_be_used_as_a_pro_key_and_forgeries_fail(self):
        self.lic.signup("ann@example.com")
        with open(self.lic.path) as f:
            token = json.load(f)["trial_token"]
        with self.assertRaises(ValueError):
            self.lic.activate(token)
        forged = licensing.make_key(bytes(range(32)), "me@example.com", 365, plan="trial", now=T0)
        with open(self.lic.path) as f:
            d = json.load(f)
        d["trial_token"] = forged
        with open(self.lic.path, "w") as f:
            json.dump(d, f)
        self.assertNotEqual(self.lic.status()["plan"], "trial")

    def test_server_unreachable_gives_a_friendly_error(self):
        licensing.SERVER = "http://127.0.0.1:1"
        with self.assertRaisesRegex(ValueError, "Could not reach"):
            self.lic.signup("ann@example.com")

    def test_without_a_server_the_trial_is_a_plain_clock(self):
        licensing.SERVER = ""
        st = self.lic.status()
        self.assertEqual((st["plan"], st["trial_left"]), ("trial", 7))
        self.clock.now = T0 + 8 * DAY
        self.assertEqual(self.lic.status()["plan"], "free")


class GumroadTests(Base):
    def test_a_good_license_key_becomes_a_pro_token_the_app_accepts(self):
        for _ in range(7):
            self.lic.count_use()
        st = self.lic.activate("GOOD-KEY-1234")  # not an LH1 key, so it is redeemed with the server
        self.assertEqual((st["plan"], st["email"], st["key_state"]), ("pro", "buyer@example.com", "ok"))
        self.lic.require("send")
        self.assertIn("gumroad_key", json.load(open(self.lic.path)))

    def test_refunded_ended_unknown_and_junk_keys_are_refused(self):
        for key, code in (("REFUNDED-1234", 403), ("ENDED-KEY-1234", 403), ("NO-SUCH-KEY-99", 404), ("x", 400)):
            with self.assertRaises(licenseserver.ServiceError) as cm:
                self.service.redeem("1.1.1.1", key)
            self.assertEqual(cm.exception.code, code, key)
        with self.assertRaises(ValueError):
            self.lic.activate("REFUNDED-1234")
        self.assertNotEqual(self.lic.status()["plan"], "pro")

    def test_the_app_renews_quietly_and_stops_after_a_refund(self):
        self.lic.activate("GOOD-KEY-1234")
        self.clock.now = T0 + 31 * DAY  # close to the end of the 35-day token
        self.lic.renew()
        self.assertGreater(self.lic.status()["expires"], T0 + 60 * DAY)
        self.gumroad["GOOD-KEY-1234"] = {"success": True, "purchase": {"email": "buyer@example.com", "refunded": True}}
        self.clock.now = T0 + 63 * DAY
        self.lic.renew()
        self.assertNotIn("gumroad_key", json.load(open(self.lic.path)))
        self.clock.now = T0 + 100 * DAY
        self.assertEqual(self.lic.status()["plan"], "free")

    def test_redeem_is_rate_limited(self):
        for _ in range(20):
            with self.assertRaises(licenseserver.ServiceError):
                self.service.redeem("5.5.5.5", "NO-SUCH-KEY-99")
        with self.assertRaises(licenseserver.ServiceError) as cm:
            self.service.redeem("5.5.5.5", "GOOD-KEY-1234")
        self.assertEqual(cm.exception.code, 429)


class HostedAiTests(Base):
    def test_ai_needs_a_valid_key_or_trial_and_is_capped(self):
        tok = self.service.trial("1.1.1.1", "ann@example.com", "a" * 64)["token"]
        out = self.service.ai("1.1.1.1", tok, "sys", "write something", 300)
        self.assertEqual(out["text"], "Hi there, a short message.")
        self.assertEqual(self.ai_calls[0][2], 300)
        for bad in ("", "LH1.x.y", licensing.make_key(bytes(range(32)), "x@y.zz", 7, plan="trial", now=T0)):
            with self.assertRaises(licenseserver.ServiceError) as cm:
                self.service.ai("1.1.1.1", bad, "s", "p", 100)
            self.assertEqual(cm.exception.code, 402)
        self.clock.now = T0 + 8 * DAY
        with self.assertRaises(licenseserver.ServiceError):
            self.service.ai("1.1.1.1", tok, "s", "p", 100)  # trial ended: no AI
        pro = licensing.make_key(SECRET, "pay@example.com", 31, now=self.clock.now)
        old = licenseserver.AI_PER_DAY
        licenseserver.AI_PER_DAY = 2
        try:
            self.service.ai("2.2.2.2", pro, "s", "p", 100)
            self.service.ai("2.2.2.2", pro, "s", "p", 100)
            with self.assertRaises(licenseserver.ServiceError) as cm:
                self.service.ai("2.2.2.2", pro, "s", "p", 100)
            self.assertEqual(cm.exception.code, 429)
        finally:
            licenseserver.AI_PER_DAY = old

    def test_ai_refuses_oversized_requests_and_caps_output(self):
        pro = licensing.make_key(SECRET, "pay@example.com", 31, now=T0)
        with self.assertRaises(licenseserver.ServiceError):
            self.service.ai("3.3.3.3", pro, "s", "x" * 9000, 100)
        self.service.ai("3.3.3.3", pro, "s", "ok", 99999)
        self.assertEqual(self.ai_calls[-1][2], 600)

    def test_the_app_writes_drafts_through_the_server(self):
        db, conf = os.path.join(self.tmp.name, "d.db"), os.path.join(self.tmp.name, "config.ini")
        s = Store(db)
        lid, _ = s.upsert(Lead(source="reddit", external_id="1", kind="post", title="Need a translator", url="https://x/1", body="please"))
        s.close()
        from leadhound import config
        config.save(config.Config(name="Ann", llm_provider="leadhound"), conf)
        httpd, token = make_server(db, conf, 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            import http.client
            httpd.ctx.license.clock = self.clock

            def post(path, body):
                c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=20)
                c.request("POST", path, json.dumps(body), {"Host": f"127.0.0.1:{httpd.server_address[1]}", "Content-Type": "application/json", "X-Leadhound-Token": token})
                r = c.getresponse()
                out = (r.status, json.loads(r.read()))
                c.close()
                return out
            code, res = post(f"/api/leads/{lid}/draft", {"llm": True})
            self.assertEqual(code, 402 if httpd.ctx.license.status()["need_signup"] else 200)
            httpd.ctx.license.signup("ann@example.com")
            code, res = post(f"/api/leads/{lid}/draft", {"llm": True})
            self.assertEqual((code, res["draft"], res["engine"]), (200, "Hi there, a short message.", "leadhound"))
            self.assertEqual(post("/api/plan", {"action": "signup", "email": "bad"})[0], 400)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
