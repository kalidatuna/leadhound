# Reddit drafts

Read each subreddit's rules and recent top posts first. Use the flair they ask for. Reply to comments for the first
few hours. Never cross-post the same text everywhere on the same day.

## r/selfhosted

**Title:** leadhound: a self-hosted tool that finds freelance clients from public hiring posts (Docker, SQLite, no deps)

Hi all. I built leadhound to stop paying for lead databases. It runs on your machine or your server and watches public
places where people ask for freelance help: Freelancer.com feeds, [Hiring] posts on Reddit, HN "Seeking freelancer"
threads, GitHub bounties, remote contract roles, any job-board RSS, plus local businesses from OpenStreetMap with a
website check.

Self-hosting details:
- `docker run -d -p 8787:8787 -e LEADHOUND_PASSWORD=... -v leadhound:/data ghcr.io/kalidatuna/leadhound`
- SQLite in a volume, password login with lockout, strict CSP, refuses to check private network addresses
- Set `LEADHOUND_TRUST_PROXY=1` behind Caddy/Traefik/Cloudflare Tunnel
- Python standard library only, MIT, no telemetry

Every lead gets a 0–100 score with the reasons listed, and a first message in the client's language. You press send.

Repo and screenshots: https://github.com/kalidatuna/leadhound. Try it with sample data: `pipx run leadhound demo`.

Happy to hear what you'd want from it on a home server.

## r/Python

**Title:** I built a desktop app with only the standard library: HTTP server, SQLite, Ed25519, IMAP, and 11 languages

leadhound (MIT) finds freelance clients from public hiring posts. The part r/Python might like is the constraint: no
runtime dependencies at all, so it installs anywhere 3.10+ runs and PyInstaller builds stay small.

Some things that turned out fine without packages:
- `http.server.ThreadingHTTPServer` + a few hundred lines of JSON API with a per-run token, Host-header checks against DNS rebinding,
  and a strict CSP
- `sqlite3` with WAL for a UI and background jobs sharing one file
- Ed25519 license signatures in ~100 lines of pure Python (checked against the RFC 8032 vectors)
- `imaplib` read-only reply detection, `smtplib` sending, `xml.etree` for RSS/Atom, `html.parser` for website audits
- 150+ unittest tests that never touch the network (a fake fetcher and a local HTTP server)

Code: https://github.com/kalidatuna/leadhound. Try it: `pipx run leadhound demo`. Questions about any of it welcome.

## r/SideProject and r/webdev (Showoff Saturday)

**Title:** leadhound: finds people asking for freelance help right now, scores them with reasons, drafts the first message

Short version: instead of cold-emailing lists, it watches public hiring posts (Freelancer.com, Reddit, HN, GitHub
bounties, contract boards) and local businesses with broken websites, explains every score, and writes the first message
in the client's language. Follow-up reminders, reply rates per source, dark mode, 11 languages. Free and open source.

GIF and code: https://github.com/kalidatuna/leadhound. Feedback on the UI especially welcome.
