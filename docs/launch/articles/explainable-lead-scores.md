---
title: "Scoring leads you can argue with: no model, every point explained"
tags: freelance, python, opensource, productivity
---

# Scoring leads you can argue with

When I started building leadhound, a tool that finds freelance clients from public hiring posts, the obvious move was
to throw every post at a language model and ask "how good is this lead, 0 to 100?". I didn't, and I'd make the same
call again. Here's why, and how the scoring works instead.

## The problem with a black-box score

A score is only useful if you act on it. If a lead scores 41 and you can't see why, you either ignore the number or
trust it blindly. Neither helps. Worse, freelancers have very specific deal-breakers: "equity only", "for exposure",
a $50 budget for a full website. A model that has never met you will happily rank those highly.

## Every point comes with a sentence

In leadhound, a score is a list of lines, and the number is just their sum:

```
+12 skills: wordpress
+20 client project post (they pay through Freelancer.com)
+12 budget stated: $750 USD
+15 posted in the last 24h
+10 public email given
−30 contains 'unpaid'
```

The rules are deliberately boring:

1. **Your skills** (up to 35): a skill in the title or the project's own skill tags counts more than one buried in the text.
2. **Hiring intent** (up to 25): `[Hiring]`, "looking to hire", "paid", a budget, urgency, in 11 languages.
   It's capped, so a post that says "paid, budget, urgent, ASAP" can't buy its way to the top.
3. **Budget** (−15 to +15): compared with *your* minimum, in *your* currency.
4. **Freshness** (up to 15): under 24 hours, under 3 days, under a week. Early replies win.
5. **Contact** (up to 10): a public email beats "reply on the site".
6. **Your "no thanks" list**: each phrase is −30.

And one safety rule: a lead with no skill match is capped at 45, however enthusiastic the post sounds.

## Why this works better than it sounds

- **You can disagree line by line.** If "+15 posted in the last 24h" matters less to you, you know exactly what to change.
- **It's fast and free.** Hundreds of leads score in milliseconds, on your laptop, with no API key.
- **It translates.** The reasons are stored as keys with arguments (`["budget_ok", {"amount": "$750"}]`), so the app
  shows them in Georgian or Arabic without asking a model.
- **It learns from you, out loud.** The "What works" panel shows your reply rate per source and whether high scores
  really reply more often ("Leads scoring 60+ replied 30% of the time, others 8%"). It suggests, it doesn't silently
  re-weight.

## Where a language model does help

Writing. An optional AI draft (your own key, a local model, or the hosted one) turns the evidence into a friendlier
first message. But it only gets the facts that are already there, and the prompt tells it never to invent past clients
or results.

The code is in [`leadhound/score.py`](https://github.com/kalidatuna/leadhound/blob/main/leadhound/score.py): about 200
lines, standard library only. Try it with sample data: `pipx run leadhound demo`.
