"""Connected accounts and sending: secrets handling, channels, SMTP, token-based platforms, API, daily limits."""
import base64
import http.client
import json
import os
import socketserver
import stat
import tempfile
import threading
import unittest

from helpers import cfg  # noqa: F401

from leadhound import accounts as acc
from leadhound import send as send_pkg
from leadhound import sending
from leadhound.dashboard.server import make_server
from leadhound.models import Lead
from leadhound.net import Response
from leadhound.send import SendError, github, mail, mastodon, reddit
from leadhound.store import Store


class FakeSMTP(socketserver.ThreadingTCPServer):
    """Just enough SMTP to log in and accept messages. Advertises no STARTTLS."""
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), self.Handler)
        self.inbox, self.password = [], "app-password-1234"
        threading.Thread(target=self.serve_forever, daemon=True).start()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            w = lambda s: self.wfile.write(s.encode() + b"\r\n")  # noqa: E731
            w("220 fake ESMTP")
            data, lines, frm, rcpt = False, [], "", ""
            for raw in self.rfile:
                line = raw.decode().rstrip("\r\n")
                if data:
                    if line == ".":
                        data = False
                        self.server.inbox.append({"from": frm, "to": rcpt, "data": "\n".join(lines)})
                        w("250 queued")
                        lines = []
                    else:
                        lines.append(line[1:] if line.startswith("..") else line)
                    continue
                cmd = line.split(" ", 1)[0].upper()
                if cmd == "EHLO":
                    self.wfile.write(b"250-fake\r\n250 AUTH PLAIN\r\n")
                elif cmd == "AUTH":
                    pw = base64.b64decode(line.split()[-1]).split(b"\0")[-1].decode()
                    w("235 ok" if pw == self.server.password else "535 bad credentials")
                elif cmd == "MAIL":
                    frm = line.split(":", 1)[1].strip(" <>")
                    w("250 ok")
                elif cmd == "RCPT":
                    rcpt = line.split(":", 1)[1].strip(" <>")
                    w("250 ok")
                elif cmd == "DATA":
                    data = True
                    w("354 go")
                elif cmd == "QUIT":
                    w("221 bye")
                    return
                else:
                    w("250 ok")


class FakeHTTP:
    """Replaces send.fetcher: records every call, answers from a queue of (status, payload)."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self):
        return self

    def request(self, url, method="GET", data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "method": method, "data": (data or b"").decode(), "headers": headers or {}})
        status, payload = self.answers.pop(0) if self.answers else (200, {})
        return Response(status, url, {}, json.dumps(payload).encode(), 0.0)


def lead(**kw):
    d = dict(source="osm", external_id="1", kind="business", title="Dental Clinic Vake", url="https://www.openstreetmap.org/node/1",
             contact="hello@dental.example, +995 322 25 01 16, Telegram: @dentalvake", id=1)
    d.update(kw)
    return Lead(**d)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.acc = acc.Accounts(os.path.join(self.tmp.name, "accounts.json"))
        acc._last.clear()
        self._gap = (sending.MIN_GAP, sending.SAME_LEAD_GAP, acc.PLATFORMS["email"]["cap"])
        sending.MIN_GAP = sending.SAME_LEAD_GAP = 0
        self._fetcher = send_pkg.fetcher

    def tearDown(self):
        sending.MIN_GAP, sending.SAME_LEAD_GAP, acc.PLATFORMS["email"]["cap"] = self._gap
        send_pkg.fetcher = self._fetcher
        self.tmp.cleanup()


class AccountFileTests(Base):
    def test_secrets_stay_out_of_public_view_and_file_is_owner_only(self):
        self.acc.connect("github", {"token": "ghp_SECRETSECRETSECRETSECRET", "as": "nino"})
        pub = json.dumps(self.acc.public())
        self.assertNotIn("SECRET", pub)
        self.assertEqual(self.acc.public()["github"]["as"], "nino")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(self.acc.path).st_mode), 0o600)
        self.assertEqual(self.acc.get("github")["token"], "ghp_SECRETSECRETSECRETSECRET")

    def test_link_apps_are_on_until_turned_off_and_usage_counts(self):
        self.assertTrue(self.acc.public()["whatsapp"]["on"])
        self.acc.set_link("whatsapp", False)
        self.assertFalse(self.acc.public()["whatsapp"]["ready"])
        self.assertEqual(self.acc.bump("email"), 1)
        self.assertEqual(self.acc.bump("email"), 2)
        self.assertEqual(self.acc.public()["email"]["used"], 2)
        self.assertTrue(self.acc.disconnect("email") is False)


class ChannelTests(Base):
    def test_channels_from_contact_info(self):
        ch = sending.channels_for(lead(), self.acc.public())
        ids = [(c["id"], c["to"]) for c in ch]
        self.assertIn(("email", "hello@dental.example"), ids)
        self.assertIn(("gmail", "hello@dental.example"), ids)
        self.assertIn(("outlook", "hello@dental.example"), ids)
        g = next(c for c in ch if c["id"] == "gmail")
        self.assertEqual((g["mode"], g["ready"]), ("link", True))  # works with no setup
        self.assertTrue(g["link"].startswith("https://mail.google.com/mail/?view=cm&fs=1&to=hello@dental.example"))
        self.assertIn(("whatsapp", "+995 322 25 01 16"), ids)
        self.assertIn(("telegram", "@dentalvake"), ids)
        wa = next(c for c in ch if c["id"] == "whatsapp")
        self.assertEqual(wa["link"], "https://wa.me/995322250116")
        self.assertEqual(next(c for c in ch if c["id"] == "email")["mode"], "send")
        self.assertFalse(next(c for c in ch if c["id"] == "email")["ready"])

    def test_reddit_mastodon_github_freelancer_and_fallback(self):
        r = sending.channels_for(lead(source="reddit", contact="reddit DM: u/cocina_clips", url="https://reddit.com/r/x/1"), {})
        self.assertEqual((r[0]["id"], r[0]["to"]), ("reddit", "u/cocina_clips"))
        m = sending.channels_for(lead(source="mastodon", contact="Mastodon: @lena@mastodon.social", url="https://mastodon.social/@lena/1"), {})
        self.assertEqual(m[0]["to"], "@lena@mastodon.social")
        g = sending.channels_for(lead(source="github", contact="issue thread on acme/docs", url="https://github.com/acme/docs/issues/412"), {})
        self.assertEqual(g[0]["id"], "github")
        f = sending.channels_for(lead(source="freelancer", contact="bid on Freelancer.com", url="https://www.freelancer.com/projects/x"), self.acc.public())
        self.assertEqual((f[0]["id"], f[0]["mode"], f[0]["ready"]), ("freelancer", "link", True))
        page = sending.channels_for(lead(source="rss", contact="", url="https://jobs.example/p/1"), {})
        self.assertEqual(page[0]["id"], "page")

    def test_unsafe_urls_never_become_links(self):
        ch = sending.channels_for(lead(source="rss", contact="", url="javascript:alert(1)"), {})
        self.assertEqual(ch, [])


class EmailTests(Base):
    @classmethod
    def setUpClass(cls):
        cls.smtp = FakeSMTP()

    @classmethod
    def tearDownClass(cls):
        cls.smtp.shutdown()
        cls.smtp.server_close()

    def form(self, **kw):
        port = self.smtp.server_address[1]
        return {"provider": "other", "address": "nino@mail.example", "password": "app-password-1234", "host": "127.0.0.1", "port": port, **kw}

    def test_connect_sends_a_test_email_to_yourself(self):
        before = len(self.smtp.inbox)
        who = sending.connect(self.acc, "email", self.form(), cloud=False)
        self.assertEqual(who, "nino@mail.example")
        msg = self.smtp.inbox[before]
        self.assertEqual(msg["to"], "nino@mail.example")
        self.assertIn("leadhound is connected", msg["data"])
        self.assertTrue(self.acc.public()["email"]["connected"])

    def test_wrong_password_and_bad_input_are_refused_and_nothing_is_saved(self):
        with self.assertRaisesRegex(SendError, "app password"):
            sending.connect(self.acc, "email", self.form(password="wrong-password-1"), cloud=False)
        with self.assertRaisesRegex(SendError, "valid email"):
            sending.connect(self.acc, "email", self.form(address="not an email"), cloud=False)
        with self.assertRaisesRegex(SendError, "at least 8"):
            sending.connect(self.acc, "email", self.form(password="short"), cloud=False)
        self.assertFalse(self.acc.public()["email"]["connected"])

    def test_cloud_mode_refuses_private_mail_hosts(self):
        with self.assertRaises(SendError):
            sending.connect(self.acc, "email", self.form(), cloud=True)

    def test_never_logs_in_over_a_connection_without_encryption(self):
        s = mail.settings(self.form(), False)
        old = mail.LOOPBACK
        mail.LOOPBACK = ()
        try:
            with self.assertRaisesRegex(SendError, "encrypted"):
                mail._connect(s)
        finally:
            mail.LOOPBACK = old

    def test_send_to_the_lead_marks_counters_and_cannot_pick_another_recipient(self):
        sending.connect(self.acc, "email", self.form(), cloud=False)
        before = len(self.smtp.inbox)
        res = sending.send_lead(self.acc, lead(), "email", "hello@dental.example", "A website for Dental Clinic", "Hello,\n\nBody line")
        self.assertEqual((res["via"], res["used"], res["cap"]), ("email", 1, 10))
        got = self.smtp.inbox[before]
        self.assertEqual((got["from"], got["to"]), ("nino@mail.example", "hello@dental.example"))
        self.assertIn("Subject: A website for Dental Clinic", got["data"])
        with self.assertRaisesRegex(SendError, "not available"):
            sending.send_lead(self.acc, lead(), "email", "victim@else.example", "x", "y")

    def test_a_subject_cannot_inject_headers(self):
        sending.connect(self.acc, "email", self.form(), cloud=False)
        before = len(self.smtp.inbox)
        sending.send_lead(self.acc, lead(), "email", "hello@dental.example", "Hi\r\nBcc: spy@evil.example", "Body")
        data = self.smtp.inbox[before]["data"]
        head = data.split("\n\n")[0]
        self.assertNotIn("\nBcc:", head)

    def test_daily_limit_and_duplicate_guard(self):
        acc.PLATFORMS["email"]["cap"] = 2
        sending.connect(self.acc, "email", self.form(), cloud=False)
        for i in range(2):
            sending.send_lead(self.acc, lead(id=10 + i), "email", "hello@dental.example", "s", "body")
        with self.assertRaises(SendError) as cm:
            sending.send_lead(self.acc, lead(id=99), "email", "hello@dental.example", "s", "body")
        self.assertEqual(cm.exception.code, 429)
        self.assertIn("Daily limit", str(cm.exception))

    def test_same_lead_twice_in_a_row_is_blocked(self):
        sending.SAME_LEAD_GAP = 60
        try:
            sending.connect(self.acc, "email", self.form(), cloud=False)
            sending.send_lead(self.acc, lead(), "email", "hello@dental.example", "s", "body")
            with self.assertRaisesRegex(SendError, "just sent"):
                sending.send_lead(self.acc, lead(), "email", "hello@dental.example", "s", "body")
        finally:
            sending.SAME_LEAD_GAP = 0

    def test_empty_or_huge_messages_are_refused(self):
        sending.connect(self.acc, "email", self.form(), cloud=False)
        for body in ("", "  ", "x" * 10001):
            with self.assertRaises(SendError):
                sending.send_lead(self.acc, lead(), "email", "hello@dental.example", "s", body)


class TokenPlatformTests(Base):
    def test_mastodon_connect_and_direct_message(self):
        fake = FakeHTTP((200, {"acct": "nino"}), (200, {"id": "1"}))
        send_pkg.fetcher = fake
        who = sending.connect(self.acc, "mastodon", {"instance": "https://Fosstodon.org/", "token": "tok-1234567890"}, cloud=False)
        self.assertEqual(who, "@nino@fosstodon.org")
        self.assertEqual(fake.calls[0]["url"], "https://fosstodon.org/api/v1/accounts/verify_credentials")
        self.assertEqual(fake.calls[0]["headers"]["Authorization"], "Bearer tok-1234567890")
        ld = lead(source="mastodon", contact="Mastodon: @lena@mastodon.social", url="https://mastodon.social/@lena/1")
        sending.send_lead(self.acc, ld, "mastodon", "@lena@mastodon.social", "", "Hi Lena")
        post = fake.calls[1]
        self.assertTrue(post["url"].endswith("/api/v1/statuses"))
        self.assertIn("visibility=direct", post["data"])
        self.assertIn("%40lena%40mastodon.social+Hi+Lena", post["data"])

    def test_mastodon_length_limit_and_bad_token(self):
        send_pkg.fetcher = FakeHTTP((401, {}))
        with self.assertRaisesRegex(SendError, "refused"):
            sending.connect(self.acc, "mastodon", {"instance": "mastodon.social", "token": "tok-1234567890"}, False)
        with self.assertRaisesRegex(SendError, "500"):
            mastodon.send({"instance": "mastodon.social", "token": "t"}, "@lena", "x" * 600)
        with self.assertRaises(SendError):
            sending.connect(self.acc, "mastodon", {"instance": "not a host", "token": "tok-1234567890"}, False)

    def test_github_comment(self):
        fake = FakeHTTP((200, {"login": "nino-dev"}), (201, {}))
        send_pkg.fetcher = fake
        self.assertEqual(sending.connect(self.acc, "github", {"token": "ghp_" + "a" * 30}, False), "nino-dev")
        ld = lead(id=7, source="github", contact="issue thread on acme/docs", url="https://github.com/acme/docs/issues/412")
        sending.send_lead(self.acc, ld, "github", "acme/docs/issues/412", "", "I can help with this")
        c = fake.calls[1]
        self.assertEqual(c["url"], "https://api.github.com/repos/acme/docs/issues/412/comments")
        self.assertEqual(json.loads(c["data"]), {"body": "I can help with this"})

    def test_github_errors_are_readable(self):
        send_pkg.fetcher = FakeHTTP((404, {}))
        with self.assertRaisesRegex(SendError, "cannot find"):
            github.send({"token": "t"}, "https://github.com/acme/docs/issues/1", "hi")
        with self.assertRaisesRegex(SendError, "not a GitHub issue"):
            github.send({"token": "t"}, "https://example.com/x", "hi")

    def test_reddit_private_message(self):
        fake = FakeHTTP((200, {"access_token": "abc"}), (200, {"access_token": "abc"}), (200, {"json": {"errors": []}}))
        send_pkg.fetcher = fake
        form = {"client_id": "id1", "client_secret": "sec1", "username": "u/nino_t", "password": "pw-1234"}
        self.assertEqual(sending.connect(self.acc, "reddit", form, False), "u/nino_t")
        ld = lead(id=3, source="reddit", contact="reddit DM: u/cocina_clips", url="https://reddit.com/r/x/1")
        sending.send_lead(self.acc, ld, "reddit", "u/cocina_clips", "Subtitles", "Hi there")
        self.assertIn("to=cocina_clips", fake.calls[2]["data"])
        self.assertTrue(fake.calls[2]["url"].startswith("https://oauth.reddit.com/"))
        self.assertTrue(fake.calls[0]["headers"]["Authorization"].startswith("Basic "))

    def test_reddit_rate_limit_and_bad_login(self):
        send_pkg.fetcher = FakeHTTP((200, {"error": "invalid_grant"}))
        with self.assertRaisesRegex(SendError, "refused"):
            sending.connect(self.acc, "reddit", {"client_id": "a", "client_secret": "b", "username": "c", "password": "d"}, False)
        send_pkg.fetcher = FakeHTTP((200, {"access_token": "t"}), (200, {"json": {"errors": [["RATELIMIT", "slow", "x"]]}}))
        with self.assertRaisesRegex(SendError, "slow down"):
            reddit.send({"client_id": "a", "client_secret": "b", "username": "c", "password": "d"}, "u/someone", "s", "b")

    def test_link_platforms_cannot_be_connected(self):
        with self.assertRaises(SendError):
            sending.connect(self.acc, "whatsapp", {}, False)


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        self.smtp = FakeSMTP()
        db, conf = os.path.join(self.tmp.name, "d.db"), os.path.join(self.tmp.name, "config.ini")
        s = Store(db)
        self.lid, _ = s.upsert(lead(id=None))
        s.close()
        self.httpd, self.token = make_server(db, conf, 0)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.smtp.shutdown()
        self.smtp.server_close()
        super().tearDown()

    def req(self, method, path, body=None, token=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        h = {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
        if token:
            h["X-Leadhound-Token"] = self.token
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, json.loads(raw)

    def test_needs_the_page_token(self):
        self.assertEqual(self.req("GET", "/api/accounts", token=False)[0], 403)
        self.assertEqual(self.req("POST", f"/api/leads/{self.lid}/send", {}, token=False)[0], 403)

    def test_connect_send_stats_and_disconnect_end_to_end(self):
        port = self.smtp.server_address[1]
        form = {"provider": "other", "address": "nino@mail.example", "password": "app-password-1234", "host": "127.0.0.1", "port": port}
        code, body = self.req("POST", "/api/accounts/email", {"action": "connect", "fields": form})
        self.assertEqual((code, body["as"], body["connected"]), (200, "nino@mail.example", True))
        code, listing = self.req("GET", "/api/accounts")
        self.assertNotIn("app-password", json.dumps(listing))
        self.assertTrue(listing["email"]["connected"])
        code, chans = self.req("GET", f"/api/leads/{self.lid}/channels")
        self.assertTrue(next(c for c in chans if c["id"] == "email")["ready"])
        before = len(self.smtp.inbox)
        code, res = self.req("POST", f"/api/leads/{self.lid}/send",
                             {"channel": "email", "to": "hello@dental.example", "subject": "Hi", "body": "Hello there"})
        self.assertEqual((code, res["used"]), (200, 1))
        self.assertEqual(len(self.smtp.inbox), before + 1)
        code, lead_now = self.req("GET", f"/api/leads/{self.lid}")
        self.assertEqual((lead_now["status"], lead_now["draft"]), ("contacted", "Hello there"))
        code, stats = self.req("GET", "/api/stats")
        self.assertEqual((stats["sent_today"], len(stats["sent_week"]), stats["sent_week"][-1]), (1, 7, 1))
        code, off = self.req("POST", "/api/accounts/email", {"action": "disconnect"})
        self.assertFalse(off["connected"])
        # nothing secret was written to the config or the lead database
        for name in os.listdir(self.tmp.name):
            if name != "accounts.json" and not name.endswith(("-wal", "-shm")):
                with open(os.path.join(self.tmp.name, name), "rb") as f:
                    self.assertNotIn(b"app-password-1234", f.read())

    def test_errors_use_proper_status_codes(self):
        self.assertEqual(self.req("POST", f"/api/leads/{self.lid}/send", {"channel": "email", "to": "hello@dental.example", "body": "x"})[0], 400)
        self.assertEqual(self.req("POST", "/api/accounts/nope", {"action": "connect"})[0], 404)
        self.assertEqual(self.req("POST", "/api/accounts/whatsapp", {"action": "connect"})[0], 400)
        self.assertEqual(self.req("GET", "/api/leads/9999/channels")[0], 404)
        code, body = self.req("POST", "/api/accounts/email", {"action": "connect", "fields": {"address": "x"}})
        self.assertEqual(code, 400)
        self.assertIn("valid email", body["error"])

    def test_link_apps_toggle(self):
        code, r = self.req("POST", "/api/accounts/whatsapp", {"action": "toggle", "on": False})
        self.assertEqual((code, r["on"]), (200, False))
        code, r = self.req("POST", "/api/accounts/whatsapp", {"action": "toggle", "on": True})
        self.assertTrue(r["on"])

    def test_manual_sent_counts_too_and_only_once(self):
        self.req("POST", f"/api/leads/{self.lid}", {"status": "contacted"})
        self.req("POST", f"/api/leads/{self.lid}", {"status": "contacted"})
        self.assertEqual(self.req("GET", "/api/stats")[1]["sent_today"], 1)

    def test_fonts_are_served_with_a_matching_content_security_policy(self):
        def raw(path):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            c.request("GET", path, headers={"Host": f"127.0.0.1:{self.port}"})
            r = c.getresponse()
            body = r.read()
            c.close()
            return r.status, r.getheader("Content-Type"), r.getheader("Content-Security-Policy"), body

        status, ctype, csp, body = raw("/static/fonts/fraunces.woff2")
        self.assertEqual((status, ctype), (200, "font/woff2"))
        self.assertTrue(body.startswith(b"wOF2"))
        self.assertIn("font-src 'self'", csp)
        self.assertEqual(raw("/static/fonts/nope.woff2")[0], 404)
        self.assertEqual(raw("/static/fonts/../app.js")[0], 404)

    def test_every_view_script_the_page_loads_is_served(self):
        for name in ("icons.js", "today.js", "compose.js", "accounts.js", "plan.js"):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            c.request("GET", "/static/" + name, headers={"Host": f"127.0.0.1:{self.port}"})
            r = c.getresponse()
            r.read()
            c.close()
            self.assertEqual(r.status, 200, name)

    def test_daily_goal_setting(self):
        code, c = self.req("POST", "/api/config", {"daily_goal": 8})
        self.assertEqual((code, c["daily_goal"]), (200, 8))
        self.assertEqual(self.req("POST", "/api/config", {"daily_goal": 0})[0], 400)


if __name__ == "__main__":
    unittest.main()
