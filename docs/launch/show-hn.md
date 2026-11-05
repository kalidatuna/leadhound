# Show HN draft

**Title** (80 characters max, no hype words, no emoji):

> Show HN: Leadhound – find freelance clients by live intent, with explainable scores

**URL**: https://github.com/kalidatuna/leadhound

**First comment** (post it right after submitting):

---

Hi HN, I'm Datuna. I freelance, and every lead tool I tried sold me a database of names to cold-email. People on those
lists never asked for anything, so the reply rates were awful and it felt like spam, because it was.

leadhound does the opposite: it only looks for people who are asking for help right now. It reads Freelancer.com
project feeds, [Hiring] posts on Reddit, Hacker News "Seeking freelancer" threads, GitHub issues with cash bounties,
remote contract roles on Himalayas, and job-board RSS. It can also find local businesses on OpenStreetMap and check
their websites (no HTTPS, not mobile-friendly, no online booking, copyright from 2019...).

A few things I cared about:

- **Explainable scores.** Every lead gets 0–100 with a line per point: "+12 skills: wordpress", "+15 posted in the
  last 24h", "−30 says 'unpaid'". No model, no black box, and you can disagree with each line.
- **It never pitches what it can't verify.** The website check only flags what it can prove from the page; if a site
  blocks automated checks, the result is "inconclusive", not "your site is broken". A false claim in a cold message costs
  you your credibility.
- **Messages in the client's language.** A dental clinic in Tbilisi gets the draft in Georgian, a hotel in Valencia in
  Spanish. The app is in 11 languages too.
- **You send every message.** It drafts and opens Gmail/WhatsApp/etc. with the text ready, or sends through your own
  account with daily caps. It never sends on its own.
- **Local-first, standard library only.** Python 3.10+, zero dependencies, SQLite in ~/.leadhound. It ships as a pip
  package, single-file apps for Windows/macOS/Linux, and a Docker image if you want it on a server.

Since the first version I added follow-up reminders (most deals need a second message), reply rates per source so you
can see what actually works, and a small browser extension.

It's MIT licensed and everything you do yourself is free with no limits. There's an optional paid Pro (hosted AI
drafts, automatic search with email alerts, reply detection) that funds the work.

Try it without setting anything up: `pipx run leadhound demo` opens it with made-up sample leads.

I'd love feedback on the scoring rules and on sources I'm missing. Which places do clients in your field post requests?

---

**Answers to have ready** (people will ask):

- *Isn't this a spam tool?* It only shows people who publicly asked for help, it caps sends per day, it never sends
  without a click, and the README has a "Responsible use" section (CAN-SPAM, GDPR). Explain the difference between
  answering a request and cold-emailing a list.
- *Does it scrape behind logins / break ToS?* No: public feeds and APIs only; it identifies itself and rate-limits.
- *Why not an LLM for scoring?* Explainability and cost; the LLM is optional for drafting only.
- *How do you make money?* Pro, as above. The open-source part is not crippled.
