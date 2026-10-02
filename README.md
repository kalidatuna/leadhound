# leadhound

**Find freelance clients by live intent, not stale contact lists.**

Most lead tools sell you a database of names and emails, then you cold-email strangers who never asked for anything. leadhound does the opposite. It looks for people and businesses that show a need **right now**, tells you why each one is a fit, and drafts a first message based on that evidence. You review it and send it yourself.

It is for freelance developers, small agencies, and anyone who builds websites or software for clients.

- **Live intent.** Hiring posts on Reddit and Hacker News, paid GitHub bounties, and job-board feeds.
- **Local businesses.** Finds shops, clinics, cafes and trades near any city with OpenStreetMap, then audits their websites.
- **Evidence-based pitch.** The audit finds concrete problems an owner understands, such as "Chrome marks your site Not secure" or "customers can't book online". The draft cites only those.
- **Explainable scores.** Every lead gets a 0–100 score with a line-by-line breakdown (`+15 budget stated: $1,500`, `-30 contains 'equity only'`). No black box.
- **Local-first and free.** Data stays in a SQLite file on your machine. No account, no tracking, no API key needed.
- **Zero dependencies.** Python 3.10+ standard library only.

## Install

```bash
pipx install git+https://github.com/kalidatuna/leadhound
```

Or without installing:

```bash
git clone https://github.com/kalidatuna/leadhound && cd leadhound
python -m leadhound --help
```

## Quick start

```bash
leadhound init                 # writes leadhound.ini: set your skills, pitch, min budget
leadhound scan                 # hiring posts + paid issues from all sources
leadhound local "Tbilisi, Georgia" --category dentist,restaurant
leadhound serve                # open the dashboard in your browser
```

Or stay in the terminal:

```bash
leadhound list --min-score 50
leadhound show 12              # full post, contact, score breakdown, audit
leadhound draft 12             # first message from the lead's evidence
leadhound status 12 contacted --note "DM sent"
leadhound export --format csv --out leads.csv
leadhound audit https://example.com --booking   # audit any single site
```

## Where leads come from

| Source | What it finds | Notes |
|---|---|---|
| `reddit` | `[Hiring]` and "need a developer" posts in r/forhire, r/jobbit, and the other subreddits you list | Public Atom feed. `[For Hire]` posts (competitors) are dropped. Reddit rate-limits anonymous feeds, so leadhound waits 7 s between subreddits. |
| `hn` | The monthly "Freelancer? Seeking freelancer?" thread (`SEEKING FREELANCER` posts only) plus contract/part-time posts from "Who is hiring?" | Algolia HN API. |
| `github` | Open, unassigned issues labelled `bounty` / `help wanted`, optionally filtered by language | Only issues with a cash amount or an Algora 💎 label count as **paid bounty**. A bare "bounty" label is often points, not money. Max 3 issues per owner, so one org can't flood your list. Set `GITHUB_TOKEN` for higher limits. |
| `rss` | Any RSS or Atom feed, such as job boards or saved searches | Add feeds in `rss_feeds`. |
| `local` | Businesses near a place, by category (`dentist`, `cafe`, `plumber`, `shop=bicycle`, ...) | OpenStreetMap Nominatim + Overpass. Free, no key. |

If one source fails (rate limit, outage), the others still run, and partial results are kept.

## Website audit

`leadhound local` audits each business website. `leadhound audit <url>` audits any single site. The audit fetches the homepage and up to 8 internal links. It checks for:

| Severity | Check |
|---|---|
| critical | Site down, HTTP errors, broken HTTPS certificate, no HTTPS, not mobile-friendly, WordPress < 6, Flash |
| costs customers | Slow load (> 3 s), footer copyright 2+ years old, no contact path, no online booking (for booking businesses), broken links, mixed content, missing title |
| minor | Missing meta description, no structured data (hurts maps ranking), old jQuery, images without alt text |

Some checks are built to avoid false claims, because a wrong claim in a cold email ruins your credibility:

- If a site blocks automated checks (HTTP 401/403/429/503, usually bot protection), the audit is marked **inconclusive** and nothing is pitched.
- Only 404/410/5xx responses count as broken links.
- The copyright year is read from visible text only, so a library license in a script does not count.

## Scoring

Posts and issues (0–100):

| Part | Points |
|---|---|
| Your skills mentioned (title counts more) | up to 35 |
| Hiring intent: `[Hiring]`, "looking to hire", "paid", budget, contract, urgency | up to 25 |
| Budget stated and above your minimum | +15, or −15 below your `min_budget` / `min_rate` |
| Fresh: < 24 h / < 3 d / < 7 d | 15 / 10 / 5 |
| Public email, or another contact path | 10 / 5 |
| No replies yet / crowded (> 20 replies) | +5 / −5 |
| Each phrase from your `avoid` list ("unpaid", "equity only", ...) | −30 |

Leads with no skill match are capped at 45, so relevant work always ranks first.

For local businesses, the score is based on: no website listed (+60), or audit severity (up to 60, plus 10 if any finding is critical), plus public contact info.

## Message drafts

`leadhound draft <id>` writes a first message from templates. No AI is needed. A post draft quotes the post, names your matching skills, and asks one scoping question. A business draft lists the top three audit findings in plain language and offers a free report.

To have an LLM write drafts, set this in `leadhound.ini`:

```ini
[llm]
provider = anthropic     # needs ANTHROPIC_API_KEY
# or any OpenAI-compatible API, including local Ollama:
# provider = openai
# base_url = http://localhost:11434/v1
# model = llama3.1
```

Then run `leadhound draft 12 --llm`, or click **Draft with LLM** in the dashboard. The model is told to use only the lead's evidence and never invent results. If the LLM call fails, the template draft is used instead.

leadhound **never sends anything**. You copy the draft, edit it, and send it yourself.

## Dashboard

`leadhound serve` opens a local web UI with a ranked lead list, filters, score breakdown, audit findings, a draft editor with copy, status buttons (new, shortlisted, contacted, replied, won, lost, ignored) and autosaved notes.

The dashboard binds to `127.0.0.1` only. It also rejects foreign `Host` headers (blocks DNS rebinding) and requires a per-run token on every API call. Other websites open in your browser cannot read or change your leads.

## Configuration

`leadhound init` writes a commented `leadhound.ini`. The settings that matter most:

```ini
[profile]
pitch = I build fast, reliable websites and web apps for small businesses
skills = Python, Django, React, WordPress, Shopify
avoid = unpaid, equity only, rev share, for exposure
min_budget = 300
min_rate = 25
```

API keys (`GITHUB_TOKEN`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) are read from environment variables only. They are never stored in the config file.

## Responsible use

- **You send every message.** Personalize it, and never mass-send.
- **Follow outreach law where you and the recipient are.** Examples: CAN-SPAM (US), GDPR and ePrivacy (EU/UK). Identify yourself, and stop when asked.
- **Verify before pitching.** OpenStreetMap can be incomplete, so a business may have a website that isn't listed. Open the site yourself before you send audit findings.
- **Be a polite client of public APIs.** leadhound identifies itself in its User-Agent, rate-limits per host, and only reads public posts and public business listings. Don't remove those limits.
- **Reply in the channel the person chose.** Contact info is only what the lead published themselves (an email in their post, a phone number in OpenStreetMap).

## Contributing

New sources and audit checks are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). Run the tests with:

```bash
python -m unittest discover -s tests -t tests
```

## License

MIT
