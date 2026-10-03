"""Worldwide features: currencies, languages, professions, new sources, translations, drafts."""
import json
import os
import re
import string
import tempfile
import unittest
from pathlib import Path

from helpers import NOW, FakeFetcher, cfg

from leadhound import config, draft, i18n, profiles, updates
from leadhound.langs import LANGUAGES, is_client_text, is_freelance_client, language_for
from leadhound.models import Lead
from leadhound.money import compare_min, parse_budget
from leadhound.sources import freelancer, mastodon, osm

LOCALES = Path(__file__).parent.parent / "leadhound" / "dashboard" / "locales"


class MoneyTest(unittest.TestCase):
    def test_currencies(self):
        cases = {"(Budget: ₹600 - ₹1500 INR, Jobs: x)": (600, 1500, "INR"), "(Budget: $30 - $250 AUD, Jobs": (30, 250, "AUD"),
                 "R$ 500": (500, 500, "BRL"), "presupuesto 300 EUR": (300, 300, "EUR"), "2 500 ₽": (2500, 2500, "RUB"),
                 "€1.200 total": (1200, 1200, "EUR"), "$100-150k": (100000, 150000, "USD"), "budget: 800": (800, 800, "")}
        for text, (lo, hi, cur) in cases.items():
            b = parse_budget(text)
            self.assertEqual((b.low, b.high, b.currency), (lo, hi, cur), text)
        self.assertIsNone(parse_budget("I have 3 kids aged 5-12"))

    def test_compare_across_currencies(self):
        inr = parse_budget("₹600 - ₹1500 INR")
        self.assertFalse(compare_min(inr, 300, "USD"))  # ~18 USD
        self.assertTrue(compare_min(inr, 1000, "INR"))
        self.assertTrue(compare_min(parse_budget("€500"), 300, "USD"))
        self.assertTrue(compare_min(parse_budget("budget: 800"), 500, "GEL"))  # no currency = yours


class LanguageTest(unittest.TestCase):
    def test_client_vs_seeker(self):
        yes = ["Busco desarrollador freelance para un proyecto web", "Ищу дизайнера для проекта логотипа",
               "Suche Entwickler für ein Projekt", "გვჭირდება დიზაინერი პროექტისთვის", "[Hiring] Need a developer for my booking site"]
        no = ["Ищу работу дизайнером", "I am available for freelance work, DM me", "Need a website? I build them fast",
              "Cloudflare is hiring Senior Software Engineer", "Looking for freelance Python / automation help?"]
        for t in yes:
            self.assertTrue(is_freelance_client(t), t)
        for t in no:
            self.assertFalse(is_freelance_client(t), t)
        self.assertTrue(is_client_text("Je cherche un développeur pour mon site"))

    def test_language_for(self):
        self.assertEqual(language_for("es-ES", "fr"), "es")  # website language wins
        self.assertEqual(language_for("", "ge"), "ka")
        self.assertEqual(language_for("nl", "nl"), "en")  # no templates: English


class ProfessionTest(unittest.TestCase):
    def test_every_profession_is_valid_config(self):
        for p in profiles.PROFESSIONS:
            c = config.from_dict(config.Config(), profiles.defaults(p.id))
            self.assertEqual(c.profession, p.id)
            self.assertTrue(c.freelancer_categories)
            for cat in c.categories:
                osm.category_tag(cat)  # every suggested business type exists
        self.assertEqual({p["id"] for p in profiles.summary()}, set(profiles.BY_ID))

    def test_config_roundtrip_all_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.ini")
            c = config.from_dict(config.Config(), {**profiles.defaults("translator"), "name": "Nino %s ; # weird",
                                                   "currency": "gel", "draft_language": "ka", "auto_scan_hours": 12,
                                                   "rss_feeds": "https://a.example/f?x=1,2\nhttps://b.example/g",
                                                   "mastodon_instances": "https://Mastodon.Social/", "mastodon_tags": "#hiring, freelance"})
            config.save(c, path)
            back = config.load(path)
            for f in ("name", "profession", "currency", "draft_language", "auto_scan_hours", "rss_feeds", "skills",
                      "freelancer_categories", "mastodon_instances", "mastodon_tags", "llm_provider"):
                self.assertEqual(getattr(back, f), getattr(c, f), f)
            self.assertEqual(back.currency, "GEL")
            self.assertEqual(back.mastodon_instances, ["mastodon.social"])
            self.assertEqual(back.mastodon_tags, ["hiring", "freelance"])
            for bad in ({"currency": "XYZ"}, {"draft_language": "xx"}, {"profession": "astronaut"}, {"auto_scan_hours": 5},
                        {"freelancer_categories": "../etc"}, {"mastodon_instances": "localhost"}, {"mastodon_tags": "a b"}):
                with self.assertRaises(ValueError, msg=bad):
                    config.from_dict(c, bad)

    def test_old_config_files_still_load(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "old.ini")
            with open(path, "w") as f:
                f.write("[profile]\nname = Old\nskills = a, b\nmin_budget = abc\n[llm]\nprovider = anthropic\nmodel = m\n")
            c = config.load(path)
            self.assertEqual((c.name, c.skills, c.min_budget, c.llm_provider, c.llm_model), ("Old", ["a", "b"], 0, "anthropic", "m"))


class SourceTest(unittest.TestCase):
    FEED = """<?xml version="1.0"?><rss><channel>
      <item><title><![CDATA[Punjabi to English Subtitling]]></title><link>https://www.freelancer.com/projects/translation/Punjabi-Subs.html</link>
      <description><![CDATA[Translate footage into English... (Budget: ₹600 - ₹1500 INR, Jobs: English (US) Translator, Punjabi Translator, Subtitling)]]></description>
      <pubDate>{d}</pubDate></item></channel></rss>"""

    def test_freelancer(self):
        from email.utils import formatdate
        xml = self.FEED.replace("{d}", formatdate(NOW - 3600))
        f = FakeFetcher([("job_Translation", xml), ("job_Subtitling", xml)])
        leads = freelancer.collect(f, cfg(freelancer=True, freelancer_categories=["Translation", "Subtitling"]), NOW)
        self.assertEqual(len(leads), 1)  # same project in two categories = one lead
        l = leads[0]
        self.assertEqual((l.source, l.external_id, l.budget), ("freelancer", "Punjabi-Subs", "₹600 - ₹1500 INR"))
        self.assertEqual(l.extra["skills"], ["English (US) Translator", "Punjabi Translator", "Subtitling"])
        self.assertTrue(l.body.endswith("…"))

    def test_mastodon(self):
        statuses = [
            {"uri": "u1", "url": "https://m.example/@a/1", "created_at": "2026-09-30T10:00:00Z", "language": "es",
             "content": "<p>Buscamos diseñador freelance para un proyecto de logo</p>", "account": {"acct": "ana@m.example"}, "replies_count": 0},
            {"uri": "u2", "url": "x", "created_at": "2026-09-30T10:00:00Z", "content": "<p>Hire me! I am available</p>", "account": {"acct": "b"}},
            {"uri": "u3", "url": "x", "created_at": "2026-09-30T10:00:00Z", "content": "<p>Acme is hiring Senior Engineer</p>", "account": {"acct": "c"}},
        ]
        f = FakeFetcher([("mastodon.social", statuses)])
        leads = mastodon.collect(f, cfg(mastodon=True, mastodon_instances=["mastodon.social"], mastodon_tags=["a", "b"]), NOW)
        self.assertEqual([l.external_id for l in leads], ["u1"])  # deduped across tags; seekers and job ads dropped
        self.assertEqual(leads[0].extra["language"], "es")
        self.assertIn("Mastodon: @ana@m.example", leads[0].contact)

    def test_whole_city_query(self):
        q = osm.build_query(["dentist"], 41.7, 44.8, 0, [41.6, 41.8, 44.7, 44.9])
        self.assertIn('nwr["amenity"="dentist"]["name"](41.6,44.7,41.8,44.9);', q)
        self.assertIn("out center tags 1500;", q)
        self.assertGreater(len(osm.CATEGORY_TAGS), 60)


class TranslationTest(unittest.TestCase):
    def test_server_catalogs_complete(self):
        en = i18n.catalog("en")
        fields = lambda s: {f for _, f, _, _ in string.Formatter().parse(s) if f}  # noqa: E731
        for lang in LANGUAGES:
            c = i18n.catalog(lang)
            self.assertEqual(set(c), set(en), lang)
            self.assertEqual([k for k in c if fields(c[k]) != fields(en[k])], [], lang)

    def test_ui_locales_complete(self):
        en = json.loads((LOCALES / "en.json").read_text())
        for lang in LANGUAGES:
            d = json.loads((LOCALES / f"{lang}.json").read_text())
            self.assertEqual(set(d), set(en), lang)
            for k, v in d.items():
                self.assertEqual(set(re.findall(r"\{(\w+)\}", v)), set(re.findall(r"\{(\w+)\}", en[k])), f"{lang}:{k}")

    def test_ui_uses_only_known_keys(self):
        en = json.loads((LOCALES / "en.json").read_text())
        server = i18n.catalog("en")
        js = "".join(p.read_text() for p in (LOCALES.parent).glob("*.js"))
        used = set(re.findall(r"\bt\('([a-z_][a-z_.0-9]+)'", js))
        unknown = sorted(k for k in used if not k.endswith(".") and k not in en and k not in server)
        self.assertEqual(unknown, [])

    def test_drafts_in_every_language(self):
        biz = Lead(source="osm", external_id="1", kind="business", title="Café Sol", url="u",
                   extra={"website": "http://cafe.example", "audit": {"findings": [
                       {"code": "stale", "severity": 2, "pitch": "x", "args": {"year": 2019}},
                       {"code": "broken_links", "severity": 2, "pitch": "x", "args": {"n": 2}},
                       {"code": "http_error", "severity": 3, "pitch": "x", "args": {"code": 500}}]}})
        nosite = Lead(source="osm", external_id="2", kind="business", title="Sol", url="u", extra={"website": "", "booking_relevant": True})
        post = Lead(source="mastodon", external_id="3", kind="post", title="Busco diseñador", url="u", author="ana", body="logo",
                    extra={"language": "es"})
        for lang in LANGUAGES:
            c = cfg(profession="designer", draft_language=lang)
            for lead in (biz, nosite, post):
                text, engine = draft.make_draft(lead, c)
                self.assertEqual(engine, "template")
                self.assertNotRegex(text, r"\{\w+\}", f"{lang}: unfilled placeholder")
                self.assertTrue(text.strip().endswith("Dato"), lang)
            self.assertIn("2019", draft.make_draft(biz, c)[0])
        self.assertIn("Hola", draft.make_draft(post, cfg(profession="designer"))[0])  # auto: post language


class UpdateTest(unittest.TestCase):
    def test_versions_and_check(self):
        self.assertGreater(updates.parse_version("0.10.0"), updates.parse_version("0.9.9"))
        self.assertEqual(updates.parse_version("v1.2"), (1, 2, 0))
        with tempfile.TemporaryDirectory() as d:
            cache = os.path.join(d, "u.json")
            f = FakeFetcher([("pypi.org", {"info": {"version": "99.0.0"}})])
            info = updates.check(f, cache)
            self.assertEqual((info["latest"], info["newer"]), ("99.0.0", True))
            info2 = updates.check(FakeFetcher([]), cache)  # cached: no network
            self.assertEqual(info2["latest"], "99.0.0")
            down = updates.check(FakeFetcher([]), os.path.join(d, "none.json"))
            self.assertEqual((down["latest"], down["newer"]), (None, False))


if __name__ == "__main__":
    unittest.main()


class OverpassFallbackTest(unittest.TestCase):
    def test_falls_back_to_next_server(self):
        from leadhound.net import FetchError, Response
        ok = Response(200, "u", {}, b'{"elements": []}', 0.1)
        f = FakeFetcher([("overpass-api.de", FetchError("timed out")), ("private.coffee", ok)])
        self.assertEqual(osm.overpass(f, "q"), {"elements": []})
        dead = FakeFetcher([("overpass", FetchError("timed out"))])
        with self.assertRaises(FetchError) as ctx:
            osm.overpass(dead, "q")
        self.assertIn("map servers busy", str(ctx.exception))
