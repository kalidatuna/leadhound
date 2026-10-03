# Selling leadhound Pro

leadhound is free to use and MIT licensed. Pro is a paid license key that unlocks sending from connected accounts,
unlimited searches and matches, AI-written messages, the local business finder with website checks, and automatic search.
Everyone gets a free taste (7 uses), then a 7-day trial after an email sign-up. Keys and trials are checked offline; you host one small [license server](LICENSE_SERVER.md) for sign-ups and the paid AI.

**Honest limit:** the code is open, so a developer can remove the local checks. The license server stops the ordinary routes (resetting the trial, reinstalling, sharing) and holds the AI behind payment, which cannot be patched out. Do not promise more than that.

## One-time setup

1. Make your signing key (keep the file private and back it up; never commit it, `*.key` is git-ignored):
   ```bash
   leadhound license keygen --out ~/leadhound-private.key
   ```
2. Deploy the license server ([LICENSE_SERVER.md](LICENSE_SERVER.md)), then paste the printed public key into `PUBLIC_KEY_HEX` in `leadhound/licensing.py` (or set `LEADHOUND_PUBLIC_KEY`), commit, release.
   Until you do, licensing is off and everything stays unlocked.
3. Create a PayPal payment link for your price (PayPal.me or a PayPal button) and set it as `LEADHOUND_BUY_URL`
   (or edit `BUY_URL` in `licensing.py`). Prices shown in the app come from `LEADHOUND_PRICE_MONTH` / `LEADHOUND_PRICE_YEAR`.
   The app only opens `https://` links.

## Each sale (manual, takes a minute)

1. PayPal emails you the payment and the buyer's email address.
2. Make their key (31 days for a monthly plan, 366 for a yearly one):
   ```bash
   leadhound license issue --key ~/leadhound-private.key --email buyer@example.com --days 31
   ```
3. Email them the key. They paste it in **Pro** (the pill in the header) and click Activate.
4. Renewals: send a new key before the old one ends. An expired key falls back to Free; nothing is lost.

Check a key: `leadhound license check LH1... --public <public key>`.

## Before you sell

- Check PayPal's rules for your age and country, and whether a parent or guardian needs to be on the account.
  Selling can also have tax and consumer-law duties where you and your buyers live. This file is not legal advice.
- Say clearly on the sales page that keys are sent by email by hand, and what the refund policy is.
- Pro never touches customer data: licensing sends nothing over the network.
