---
title: "Shipping a desktop app with nothing but the Python standard library"
tags: python, opensource, desktop, sqlite
---

# Shipping a desktop app with nothing but the Python standard library

leadhound has one hard rule in its contributing guide: **standard library only.** No requests, no Flask, no SQLAlchemy,
no cryptography package. The app finds freelance clients, serves a full web UI in 11 languages, sends email, reads an
inbox, checks websites, and verifies signed license keys, and `pip install leadhound` downloads exactly one package.

Here's what that looks like and what it cost.

## Why bother

- **It installs anywhere.** Python 3.10+ on Windows, macOS, Linux, a Raspberry Pi, a $5 server. No compiler, no wheels
  that don't exist for your platform.
- **Small standalone apps.** PyInstaller builds stay small and boring, which matters for people who will never open a
  terminal.
- **Fewer supply-chain worries.** For a tool that stores your email app password, fewer packages means fewer things to trust.

## The pieces

**HTTP server.** `http.server.ThreadingHTTPServer` with a small router: a list of `(method, regex, handler)` tuples. Local
mode binds to 127.0.0.1, checks the `Host` header (DNS rebinding), and requires a per-run token on every API call that the
page gets from a `<meta>` tag. Every response has a strict Content-Security-Policy with no inline scripts.

**Frontend.** Plain ES modules, a 20-line `el()` helper that builds DOM nodes and never parses HTML, and CSS with
`oklch()` colours and a dark theme. No build step: CI runs `node --check` on each file and that's it.

**Storage.** `sqlite3` in WAL mode, so the UI and background search threads can share one file. Re-scans update content
and scores but never touch what you wrote (status, notes, drafts).

**Network.** One `Fetcher` class on top of `urllib.request` with a User-Agent, per-host rate limits and retries. Sources
get it injected, so tests swap in a fake that returns canned responses. No test touches the internet.

**Email.** `smtplib` with STARTTLS (and a refusal to send a password over a plain connection), and `imaplib` opened
read-only to notice replies by sender and date.

**Signatures.** Pro license keys are Ed25519-signed. That's about 100 lines of pure Python, checked against the RFC
8032 test vectors. It's slow by C standards, and it doesn't need to be fast: it verifies one key at startup.

**Website audits.** `html.parser.HTMLParser` subclasses collect titles, meta tags, links, scripts and images.

## What it cost

- Writing a router and a tiny DOM helper by hand: an afternoon each.
- Ed25519: a day, mostly careful testing.
- No ORM means SQL strings, which are honestly fine at this size.

What I didn't miss: dependency upgrades, broken wheels, and "works on my machine".

The code is at https://github.com/kalidatuna/leadhound (MIT). `pipx run leadhound demo` shows the result in ten seconds.
