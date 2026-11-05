---
title: "A website check that never pitches what it can't prove"
tags: webdev, freelance, python, seo
---

# A website check that never pitches what it can't prove

"Hi, I noticed your website has 37 SEO errors!" Every small-business owner has had that email, and every one of them
deletes it. When I added a website check to leadhound, the rule was simple: **only say what you can prove, in words the
owner understands.** A false claim in a cold message doesn't just lose that client; it makes you look like the spammers.

## What it checks

leadhound reads the homepage and up to 8 internal links, then sorts findings into three levels:

| Level | Examples |
|---|---|
| Critical | site down or erroring, broken HTTPS certificate, no HTTPS, not mobile-friendly, WordPress older than 6, Flash |
| Costs customers | slower than 3 seconds, copyright 2+ years old, no contact path, no online booking (for clinics, salons, hotels), broken links, mixed content |
| Minor | no meta description, no structured data, old jQuery, images without alt text |

Each finding carries one sentence a non-technical owner understands: not "missing viewport meta" but *"Your site isn't
set up for phones, and most local searches happen on a phone."*

## The places where it's easy to lie by accident

- **Bot protection.** Cloudflare and friends often answer automated requests with 403 or a challenge page. Real visitors
  see the site fine. leadhound marks those results *inconclusive* and tells you to open the site yourself. It never
  pitches "your site is broken" on a 403.
- **Broken links.** Only 404, 410 and 5xx count. 401, 403, 412 and 429 usually mean "I don't talk to bots".
- **"Copyright 2015".** jQuery's own license comment says 2015. The year only comes from visible text, never from scripts
  or comments.
- **"No website".** OpenStreetMap can be incomplete, so a business without a listed site gets a reminder to check
  before pitching.
- **Language.** The finding sentences exist in 11 languages, and the message goes out in the site's own language (its
  `<html lang>`, then the country), so a hotel in Valencia gets Spanish.

## Turning findings into a message

The draft cites at most three findings, then offers to send a short free report with screenshots:

> I was looking at hotelmarazul.example and noticed a few things that are likely costing you customers:
> – Your site isn't set up for phones, and most local searches happen on a phone.
> – Your homepage took 6.2 seconds to load in my test; many visitors leave after 3.

No invented numbers, no "37 errors". If the site is healthy, the message says so and doesn't make up problems.

The checks are in [`leadhound/audit.py`](https://github.com/kalidatuna/leadhound/blob/main/leadhound/audit.py), with tests
that run against a local HTTP server. Run one yourself: `leadhound audit https://your-site.example`.
