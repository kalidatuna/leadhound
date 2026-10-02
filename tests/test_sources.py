import unittest

from helpers import NOW, FakeFetcher, cfg

from leadhound.sources import github, hn, osm, reddit, rss


def reddit_entry(id, title, age_h=2, body="", author="/u/alice"):
    from datetime import datetime, timezone
    ts = datetime.fromtimestamp(NOW - age_h * 3600, timezone.utc).isoformat()
    content = (f"&lt;!-- SC_OFF --&gt;&lt;div class=&quot;md&quot;&gt;&lt;p&gt;{body}&lt;/p&gt;&lt;/div&gt;"
               f"&lt;!-- SC_ON --&gt; &amp;#32; submitted by &amp;#32; &lt;a href=&quot;x&quot;&gt; {author} &lt;/a&gt;")
    return (f'<entry><author><name>{author}</name></author><content type="html">{content}</content>'
            f'<id>t3_{id}</id><link href="https://www.reddit.com/r/forhire/comments/{id}/x/"/>'
            f'<published>{ts}</published><title>{title}</title></entry>')


class RedditTest(unittest.TestCase):
    def test_keeps_clients_drops_competitors_and_old(self):
        feed = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">' + "".join([
            reddit_entry("a", "[Hiring] Django dev for booking site", body="Budget $800. email me: a@b.co"),
            reddit_entry("b", "[For Hire] Python dev available"),
            reddit_entry("c", "Need a developer to fix my Shopify store"),
            reddit_entry("d", "[Hiring] old one", age_h=24 * 30),
            reddit_entry("e", "Random discussion about rates"),
        ]) + "</feed>"
        f = FakeFetcher([("reddit.com/r/forhire/new/.rss", feed)])
        leads = reddit.collect(f, cfg(), NOW)
        self.assertEqual([l.external_id for l in leads], ["a", "c"])
        a = leads[0]
        self.assertEqual(a.url, "https://www.reddit.com/r/forhire/comments/a/x/")
        self.assertEqual(a.body, "Budget $800. email me: a@b.co")  # footer stripped
        self.assertIn("a@b.co", a.contact)
        self.assertIn("reddit DM: u/alice", a.contact)
        self.assertEqual(a.author, "u/alice")


class HNTest(unittest.TestCase):
    def test_threads_and_filters(self):
        hiring_search = {"hits": [
            {"title": "Ask HN: Who wants to be hired? (October 2026)", "objectID": "300"},
            {"title": "Ask HN: Who is hiring? (October 2026)", "objectID": "100"},
        ]}
        free_search = {"hits": [
            {"title": "Ask HN: Freelancer? Seeking freelancer? (October 2026)", "objectID": "201",
             "created_at_i": NOW - 3600, "num_comments": 2},
            {"title": "Ask HN: Freelancer? Seeking freelancer? (October 2026)", "objectID": "200",
             "created_at_i": NOW - 7200, "num_comments": 13},
            {"title": "Ask HN: Freelancer? Seeking freelancer? (September 2026)", "objectID": "199",
             "created_at_i": NOW - 31 * 86400, "num_comments": 40},
            {"title": "Seeking freelancer advice", "objectID": "9", "created_at_i": NOW},
        ]}
        self.assertEqual(hn.latest_hiring(hiring_search), "100")
        self.assertEqual(hn.latest_freelancer(free_search), "200")  # same-month duplicate: busiest wins
        self.assertIsNone(hn.latest_freelancer({"hits": []}))
        freelancer = {"children": [
            {"id": 1, "author": "acme", "created_at_i": NOW - 3600,
             "text": "SEEKING FREELANCER | Remote | Django<p>Need help with an API. jane [at] acme [dot] com"},
            {"id": 2, "author": "bob", "created_at_i": NOW - 3600, "text": "SEEKING WORK | Python dev"},
            {"id": 3, "author": None, "text": "deleted"},
        ]}
        hiring = {"children": [
            {"id": 4, "author": "co", "created_at_i": NOW, "text": "Acme | Contract | Remote | React"},
            {"id": 5, "author": "co2", "created_at_i": NOW, "text": "BigCo | Full-time | Onsite<p>we also hire contractors"},
            {"id": 6, "author": "me", "created_at_i": NOW, "text": "Location: SF<p>Open to contract work"},
            {"id": 7, "author": "mm", "created_at_i": NOW, "text": "Mainmatter | Rust Consultant | Full-time"},
        ]}
        f = FakeFetcher([("author_whoishiring", hiring_search), ("seeking%20freelancer", free_search),
                         ("items/200", freelancer), ("items/100", hiring)])
        leads = hn.collect(f, cfg(), NOW)
        ids = sorted(l.external_id for l in leads)
        self.assertEqual(ids, ["1", "4"])
        one = next(l for l in leads if l.external_id == "1")
        self.assertEqual(one.title, "SEEKING FREELANCER | Remote | Django")
        self.assertIn("jane@acme.com", one.contact)
        self.assertEqual(one.url, "https://news.ycombinator.com/item?id=1")


class GitHubTest(unittest.TestCase):
    def test_parse_and_dedupe(self):
        item = {"id": 9, "title": "Add CSV export", "body": "details", "html_url": "https://github.com/o/r/issues/1",
                "user": {"login": "maint"}, "created_at": "2026-09-30T10:00:00Z", "comments": 0,
                "labels": [{"name": "💎 Bounty"}, {"name": "$150"}],
                "repository_url": "https://api.github.com/repos/o/r"}
        pr = dict(item, id=10, pull_request={"url": "x"})
        f = FakeFetcher([("api.github.com/search/issues", {"items": [item, pr]})])
        leads = github.collect(f, cfg(github_labels=["bounty", "help wanted"]), NOW)
        self.assertEqual(len(leads), 1)  # PR skipped, duplicate across two label queries removed
        self.assertEqual(len(f.calls), 2)
        l = leads[0]
        self.assertEqual(l.title, "[o/r] Add CSV export")
        self.assertIn("paid bounty", l.signals)
        self.assertEqual(l.budget, "$150")
        self.assertIn("no%3Aassignee", f.calls[0])

    def test_per_owner_cap_and_points_bounty(self):
        def item(i, repo, labels=()):
            return {"id": i, "title": f"t{i}", "html_url": "u", "created_at": "2026-09-30T10:00:00Z",
                    "labels": [{"name": n} for n in labels], "repository_url": f"https://api.github.com/repos/{repo}"}
        items = [item(i, f"spam/repo{i}", ["bounty", "points:50"]) for i in range(10)] + [item(99, "real/repo")]
        f = FakeFetcher([("api.github.com/search/issues", {"items": items})])
        leads = github.collect(f, cfg(github_languages=["python"]), NOW)
        self.assertEqual([l.extra["repo"].split("/")[0] for l in leads], ["spam"] * 3 + ["real"])
        self.assertIn("bounty label (no amount)", leads[0].signals)
        self.assertNotIn("paid bounty", leads[0].signals)
        self.assertEqual(leads[0].extra["language"], "python")

    def test_partial_failure_keeps_good_queries(self):
        from leadhound.sources import PartialFailure
        f = FakeFetcher([("python", {"items": [{"id": 1, "title": "x", "html_url": "u", "labels": [],
                                                  "repository_url": "https://api.github.com/repos/a/b"}]}),
                         ("language%3Ago", RuntimeError("rate limited"))])
        with self.assertRaises(PartialFailure) as ctx:
            github.collect(f, cfg(github_languages=["python", "go"]), NOW)
        self.assertEqual(len(ctx.exception.leads), 1)
        self.assertIn("rate limited", str(ctx.exception))

    def test_queries_with_languages(self):
        qs = github.build_queries(["bounty"], ["python", "go"], "2026-09-01")
        self.assertEqual(len(qs), 2)
        self.assertTrue(qs[1][0].endswith("language:go"))
        self.assertEqual(qs[1][1], "go")


class RSSTest(unittest.TestCase):
    RSS = """<?xml version="1.0"?><rss><channel>
      <item><title>Senior Django Developer (Contract)</title><link>https://jobs.example/1</link>
        <description>&lt;p&gt;Remote. $60/hr. Contact hr@jobs.example&lt;/p&gt;</description>
        <pubDate>Mon, 21 Sep 2026 10:00:00 +0000</pubDate><guid>job-1</guid></item>
      <item><title>Ancient job</title><link>https://jobs.example/2</link>
        <pubDate>Mon, 01 Jan 2024 10:00:00 +0000</pubDate></item>
    </channel></rss>"""
    ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Need React help</title><link href="https://a.example/x"/><id>tag:1</id>
      <updated>2026-09-21T10:00:00Z</updated><summary>Small fix</summary></entry></feed>"""

    def test_rss_and_atom(self):
        leads = rss.parse_feed(self.RSS, "https://jobs.example/feed.rss", NOW - 30 * 86400)
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0].body, "Remote. $60/hr. Contact hr@jobs.example")
        self.assertEqual(leads[0].contact, "hr@jobs.example")
        atom = rss.parse_feed(self.ATOM, "https://a.example/feed", 0)
        self.assertEqual(atom[0].url, "https://a.example/x")
        self.assertGreater(atom[0].created_at, 0)


class OSMTest(unittest.TestCase):
    def test_query_and_parse(self):
        q = osm.build_query(["dentist", "shop=bicycle"], 41.7, 44.8, 2000)
        self.assertIn('nwr["amenity"="dentist"]["name"](around:2000,41.7,44.8);', q)
        self.assertIn('nwr["shop"="bicycle"]', q)
        with self.assertRaises(ValueError):
            osm.category_tag("spaceship")
        data = {"elements": [
            {"type": "node", "id": 1, "lat": 41.7, "lon": 44.8,
             "tags": {"name": "Smile Dental", "amenity": "dentist", "website": "smile.ge", "phone": "+995 555"}},
            {"type": "way", "id": 2, "center": {"lat": 1, "lon": 2},
             "tags": {"name": "Bike Hub", "shop": "bicycle", "addr:street": "Rustaveli", "addr:city": "Tbilisi"}},
            {"type": "node", "id": 3, "tags": {"amenity": "dentist"}},
        ]}
        leads = osm.parse_elements(data, ["dentist", "shop=bicycle"])
        self.assertEqual(len(leads), 2)
        smile, bike = leads
        self.assertEqual(smile.extra["website"], "http://smile.ge")
        self.assertTrue(smile.extra["booking_relevant"])
        self.assertEqual(bike.url, "https://www.openstreetmap.org/way/2")
        self.assertEqual(bike.signals, ["no website listed"])
        self.assertEqual(bike.location, "Rustaveli, Tbilisi")

    def test_geocode_not_found(self):
        f = FakeFetcher([("nominatim", [])])
        with self.assertRaises(ValueError):
            osm.geocode(f, "Nowhere")


if __name__ == "__main__":
    unittest.main()
