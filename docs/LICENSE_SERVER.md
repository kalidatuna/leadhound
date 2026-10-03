# The license server

You host this one small program. Users never run it. It makes the free trial fair and runs the paid AI.

| Job | What it does |
|---|---|
| `POST /v1/trial` | Gives a signed 7-day trial. **One per email and per device**, 3 new trials per network per day. Asking again returns the same trial, so deleting files or reinstalling never starts a new one. Gmail dots and `+tags` count as one inbox. |
| `POST /v1/ai` | Writes a message with **your** Anthropic key for anyone holding a valid Pro key or trial (40 a day each by default). This is the one paid feature that cannot be patched out of the app, because the app does not contain it. |

The app checks trial tokens and license keys by itself, offline. The server is only needed for sign-up and for AI.

## What users go through

1. The first 7 uses (a search, a sent message, an AI draft) are a free taste with no sign-up.
2. Then the app asks for an email and starts a 7-day trial from that moment.
3. After the trial: Free, or Pro with a key you send them.

## Run it

```bash
leadhound license keygen --out ~/leadhound-private.key        # once; prints the public key
LICENSE_PRIVATE_KEY=$(cat ~/leadhound-private.key) \
ANTHROPIC_API_KEY=sk-ant-... \
LICENSE_DB=/data/licenses.db PORT=8080 \
python -m leadhound.licenseserver
```

Put it behind HTTPS (Render, Fly.io, Railway or any small server with Caddy). Behind a proxy set `TRUST_PROXY=1` so the
rate limit sees the real address. Keep `licenses.db` on a persistent disk and back it up: it is what stops repeat trials.

Optional: `AI_DAILY_CAP` (default 40), `AI_MODEL` (default `claude-haiku-4-5-20251001`, the cheapest).

Then build the app with your settings (environment variables, or edit the constants in `leadhound/licensing.py`):

| Setting | Meaning |
|---|---|
| `PUBLIC_KEY_HEX` / `LEADHOUND_PUBLIC_KEY` | public key from `keygen` |
| `LEADHOUND_LICENSE_SERVER` | `https://your-server` (without it there is no sign-up step and the trial is a local 7-day clock) |
| `LEADHOUND_BUY_URL` | your PayPal link |
| `LEADHOUND_PRICE_MONTH`, `LEADHOUND_PRICE_YEAR` | shown prices (default $12.99 and $89.99) |

## What this does and does not stop

- Stops: deleting `license.json`, reinstalling, a second trial on a new email from the same computer, sharing a trial token, forging a key, using AI without paying.
- Does not stop: a developer who edits the open-source code to skip the local checks for searching and sending, or someone who uses a new email *and* a new computer. Disposable emails are not checked. If that becomes a real problem, add email confirmation (send a code before issuing the trial).
- Privacy: the server stores the email as typed, a hash-based device code, the network address, and start times. Hosted AI sends the lead's text to your server, then to Anthropic. Say so on your site and in your privacy policy.
- Cost: every hosted AI message costs you a little. The daily cap bounds it. Watch your Anthropic bill.
