# Contributing

Thanks for helping. leadhound has one hard rule: **standard library only**. No runtime dependencies, so it installs anywhere Python 3.10+ runs and builds into small standalone apps.

## Run the tests

```bash
python -m unittest discover -s tests -t tests -v
```

Tests never touch the internet. Sources are tested with canned API responses (`tests/helpers.py` has a `FakeFetcher`), and the website audit runs against a local HTTP server.

## Add a lead source

1. Create `leadhound/sources/<name>.py` with:

   ```python
   def collect(fetcher, cfg, now: float) -> list[Lead]:
       ...
   ```

   Use `fetcher.get_json` or `fetcher.get_text`. They handle the User-Agent, rate limits and retries.
   If you make several requests (one per feed or subreddit), wrap them in `collect_each` so one failure does not lose the rest.
2. Register it in `SOURCES` in `leadhound/sources/__init__.py`.
3. Add a parser test with a small canned response.

Good sources show **live intent**: someone asking for help right now. Do not add sources that need scraping behind a login, or that break a site's terms of service.

## Add an audit check

Add it to `analyze_html` (HTML checks) or `audit` (HTTP checks) in `leadhound/audit.py`. Every finding needs:

- `severity`: 1 minor, 2 costs customers, 3 critical
- `pitch`: one sentence a non-technical business owner understands

Only flag what you can verify from the page. A false finding in a cold message costs the user their credibility.

## Scoring

`leadhound/score.py` must stay explainable: every point added or removed comes with a reason string shown to the user.

## Improve a translation

- App text: `leadhound/dashboard/locales/<lang>.json`
- Messages, website findings and score reasons: `leadhound/i18n/<lang>.py`

Keep every `{placeholder}` exactly as in English. The tests check that every language has every key and the same placeholders.

To add a language, copy `en.json` and `en.py`, translate them, and add the code to `LANGUAGES` in `leadhound/langs.py`.

## Add a profession

Add a `Profession` to `leadhound/profiles.py`. Check that its Freelancer.com categories return projects: `https://www.freelancer.com/rss/job_<Category>.xml`. Then add `prof.<id>` to every locale file and `o.<id>` (the one-line offer) to every `i18n/<lang>.py`.
