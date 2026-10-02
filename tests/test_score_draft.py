import unittest

from helpers import NOW, FakeFetcher, cfg

from leadhound import draft, score
from leadhound.models import Lead
from leadhound.net import Response
from leadhound.textutil import find_emails, parse_budget, strip_html, word_hit


def post(title, body="", age_h=2, **kw):
    return Lead(source="reddit", external_id="x", kind="post", title=title, url="u", body=body,
                author="u/alice", created_at=NOW - age_h * 3600, contact="reddit DM: u/alice", **kw)


class TextTest(unittest.TestCase):
    def test_budget(self):
        cases = {
            "Budget is $1,500": (1500, 1500, False),
            "paying $40/hr": (40, 40, True),
            "$2k-$3k for the project": (2000, 3000, False),
            "$100-150k": (100000, 150000, False),
            "$23-$34 USD/h": (23, 34, True),
            "500 USD fixed": (500, 500, False),
            "€1.200 total": (1200, 1200, False),
            "budget: 800": (800, 800, False),
            "rate 30 per hour, budget unknown": (30, 30, True),
            "we need 30 pages and 2 forms": None,
        }
        for text, want in cases.items():
            b = parse_budget(text)
            got = (b.low, b.high, b.hourly) if b else None
            self.assertEqual(got, want, text)
        self.assertIsNone(parse_budget("I have 3 pages and 2 forms"))

    def test_helpers(self):
        self.assertEqual(find_emails("mail a@b.io or c [at] d [dot] com, logo@2x.png"), ["a@b.io", "c@d.com"])
        self.assertEqual(strip_html("<p>Hi &amp; bye</p><p>two</p>"), "Hi & bye\n\ntwo")
        self.assertTrue(word_hit("go", "we use go daily"))
        self.assertFalse(word_hit("go", "google it"))
        self.assertTrue(word_hit("c++", "c++ dev"))


class ScoreTest(unittest.TestCase):
    def test_strong_lead_beats_weak(self):
        strong = score.score(post("[Hiring] Django developer for booking app",
                                  "Budget $1,500. Need it by next week. contact a@b.co", extra={"comments": 0}), cfg(), NOW)
        weak = score.score(post("Looking for a designer", "logo for my band", age_h=24 * 9), cfg(), NOW)
        self.assertGreater(strong.score, 80)
        self.assertLess(weak.score, 45)
        self.assertTrue(any("skills: django" in r for r in strong.reasons))
        self.assertTrue(any(r.startswith("+0 no skill match") for r in weak.reasons))
        self.assertEqual(strong.budget, "$1,500")

    def test_avoid_and_low_budget(self):
        l = score.score(post("[Hiring] Python dev, equity only", "budget $100"), cfg(), NOW)
        self.assertTrue(any("equity only" in r for r in l.reasons))
        self.assertTrue(any("below your min" in r for r in l.reasons))
        self.assertLess(l.score, 30)

    def test_no_skill_cap(self):
        l = score.score(post("[Hiring] need a designer ASAP, paid", "budget $5,000 contact a@b.co"), cfg(), NOW)
        self.assertEqual(l.score, 45)

    def test_github_bounty_vs_help_wanted(self):
        b = Lead(source="github", external_id="1", kind="issue", title="[o/r] python scraping fix", url="u",
                 created_at=NOW, signals=["paid bounty"], extra={"comments": 0})
        h = Lead(source="github", external_id="2", kind="issue", title="[o/r] python scraping fix", url="u",
                 created_at=NOW, signals=[], extra={"comments": 0})
        self.assertGreater(score.score(b, cfg(), NOW).score, score.score(h, cfg(), NOW).score)

    def test_business(self):
        none = score.score(Lead(source="osm", external_id="n", kind="business", title="A", url="u",
                                extra={"website": "", "phone": "1", "booking_relevant": True}), cfg(), NOW)
        self.assertEqual(none.score, 75)
        bad = Lead(source="osm", external_id="b", kind="business", title="B", url="u",
                   extra={"website": "http://b", "email": "x@b", "audit": {"findings": [
                       {"severity": 3, "title": "No HTTPS"}, {"severity": 3, "title": "Not mobile-friendly"},
                       {"severity": 2, "title": "Stale"}]}})
        self.assertEqual(score.score(bad, cfg(), NOW).score, 73)  # 48 + 10 + 15
        ok = Lead(source="osm", external_id="c", kind="business", title="C", url="u",
                  extra={"website": "https://c", "audit": {"findings": []}})
        self.assertEqual(score.score(ok, cfg(), NOW).score, 0)


class DraftTest(unittest.TestCase):
    def test_post_template(self):
        l = post("[Hiring] Django dev for booking app", "need it soon")
        text, engine = draft.make_draft(l, cfg())
        self.assertEqual(engine, "template")
        self.assertIn("Hi alice,", text)
        self.assertIn('"Django dev for booking app"', text)
        self.assertIn("django", text)
        self.assertIn("What budget and timeline", text)
        self.assertTrue(text.endswith("Dato"))

    def test_business_templates(self):
        nosite = Lead(source="osm", external_id="1", kind="business", title="Smile Dental", url="u",
                      extra={"website": "", "category": "dentist", "city": "Tbilisi", "booking_relevant": True})
        t, _ = draft.make_draft(nosite, cfg())
        self.assertIn("Subject: A website for Smile Dental", t)
        self.assertIn("dentist in Tbilisi", t)
        self.assertIn("online booking", t)
        site = Lead(source="osm", external_id="2", kind="business", title="Cafe X", url="u",
                    extra={"website": "http://cafex.ge", "audit": {"findings": [
                        {"severity": 3, "title": "No HTTPS", "pitch": "Chrome marks your site 'Not secure'."}]}})
        t, _ = draft.make_draft(site, cfg())
        self.assertIn("Subject: Quick note about cafex.ge", t)
        self.assertIn("- Chrome marks your site 'Not secure'.", t)
        healthy = Lead(source="osm", external_id="3", kind="business", title="Good Co", url="u",
                       extra={"website": "https://good.ge", "audit": {"findings": [], "blocked": True}})
        t, _ = draft.make_draft(healthy, cfg())
        self.assertNotIn("costing you customers", t)
        self.assertNotIn("quick fixes", t)
        self.assertEqual(score.score(healthy, cfg(), NOW).reasons[0][:10], "+10 site b")

    def test_llm_and_fallback(self):
        import os
        c = cfg(llm_provider="anthropic")
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        try:
            ok = FakeFetcher([("api.anthropic.com", Response(200, "u", {}, b'{"content":[{"type":"text","text":"Hi from LLM"}]}', 0))])
            self.assertEqual(draft.make_draft(post("[Hiring] x"), c, use_llm=True, fetcher=ok), ("Hi from LLM", "anthropic"))
            bad = FakeFetcher([("api.anthropic.com", Response(401, "u", {}, b'{"error":"bad key"}', 0))])
            text, engine = draft.make_draft(post("[Hiring] x"), c, use_llm=True, fetcher=bad)
            self.assertIn("Hi alice", text)
            self.assertTrue(engine.startswith("template (LLM failed"))
        finally:
            del os.environ["ANTHROPIC_API_KEY"]
        self.assertEqual(draft.make_draft(post("x"), cfg(), use_llm=True)[1], "template")  # provider none


if __name__ == "__main__":
    unittest.main()
