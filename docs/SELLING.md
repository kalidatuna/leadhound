# Selling leadhound Pro (Gumroad)

leadhound is free to use and MIT licensed. Pro unlocks sending from connected accounts, unlimited searches and matches,
hosted AI messages, the local business finder with website checks, and automatic search. Everyone gets a free taste
(7 uses), then a 7-day trial after an email sign-up. You host one small [license server](LICENSE_SERVER.md).

**Honest limit:** the code is open, so a developer can remove the local checks. The server stops the ordinary routes
(resetting the trial, reinstalling, sharing) and holds the AI behind payment. Do not promise more than that.

## One-time setup

1. **Gumroad product.** Create a *Membership* product with two tiers: Monthly $12.99 and Yearly $89.99.
   In the product's settings turn on **Generate a unique license key per sale**. Gumroad then emails every buyer a license key.
   Note the product's **ID** (Product page, Settings, or the API docs show it).
   Gumroad account owners must meet Gumroad's age rule; use a parent or guardian's account if you are under it.
2. **Give the server the product ID** and redeploy:
   ```bash
   fly secrets set GUMROAD_PRODUCT_ID=<your product id> -a leadhound-license-nino
   fly deploy -c fly.license.toml -a leadhound-license-nino
   ```
3. **Point the app at the product page**: set `BUY_URL` in `leadhound/licensing.py` (or `LEADHOUND_BUY_URL`) to the Gumroad link.
   Put the same link on the landing page (`site/index.html`).

## Each sale: nothing to do

The buyer pays on Gumroad and gets a license key by email. They paste it into the **Pro** dialog. leadhound asks your server,
which asks Gumroad, and returns a signed Pro token valid for 35 days. The app renews it quietly each month while the
subscription is active. A refund, chargeback, failed payment or ended subscription stops the renewal, and Pro ends within 35 days.

## Manual keys (for testers and gifts)

```bash
leadhound license issue --key ~/leadhound-private.key --email tester@example.com --days 31
```

## Before you sell

- Check the age and tax rules for you, your country and your buyers. This file is not legal advice.
- Write your refund policy on the sales page. Gumroad handles refunds; the key stops renewing after one.
- Pro never sends customer data anywhere except the license server (see LICENSE_SERVER.md).
