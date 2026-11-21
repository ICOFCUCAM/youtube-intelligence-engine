# Waitlist (demand test)

The landing page has a **Plans** section (planned prices, clearly not on sale) and a waitlist
form. Its purpose is to learn which offer people want before building one.

**Status: built and switched off.** Until the steps below are done, the form tells visitors
"the waitlist isn't open yet - nothing was saved", and the server function answers `503` and
stores nothing.

## How it works

```
1. form ──GET /api/waitlist──────────────> signed challenge (expires in 10 min)
2. browser solves it (about a second of SHA-256 work, bound to the email)
3. form ──POST /api/waitlist {email, ..., challenge, nonce}
          │  same-origin check, per-visitor limit, honeypot, validation, proof of work,
          │  per-email limit
          └──> email via Resend: "confirm at https://<site>/confirm#t=<signed sign-up>"
               (nothing is stored)
4. /confirm page ──POST /api/waitlist {confirm: token}
          │  signature + 48 h expiry checked
          └──> Supabase REST with the ANON key -> public.yie_waitlist_signups
               (row level security: anon may INSERT only; no read, update or delete;
                flood brake: over 300 sign-ups in 10 minutes -> HTTP 429)
5. nightly (pg_cron): sign-ups older than 12 months are deleted
```

Stored per **confirmed** sign-up: email (lower-cased), offer (`reports`, `shorts`, `agency`,
`api`, `not_sure`), optional channel size, optional other platforms (`tiktok`, `instagram`,
`facebook`, `linkedin`, `x`, `podcasts`, or `none`), consent version (`2026-11-v3`, matching the
privacy notice), when it was saved and when it was confirmed. No IP address, user agent or
cookies. Emails are never logged. A duplicate email gets the same answer as a new one, so the form
can't be used to check who signed up.

**Unconfirmed sign-ups are never stored by us.** The confirmation link carries the sign-up itself,
signed with `WAITLIST_SECRET` (HMAC-SHA256), so there is no "pending" table to clean up. The email
provider does see the address, to deliver the email.

## Abuse protection

No third-party CAPTCHA: nothing is loaded from another site, so the page's no-third-party promise
and its strict Content-Security-Policy hold.

| Layer | Where | Stops |
| --- | --- | --- |
| Same-origin check | function | other websites submitting through their visitors (403) |
| 8 attempts per address per 10 min | function, memory only | one machine hammering the form (429) |
| Honeypot field | function | simple form-filling bots (fake success) |
| Proof of work, 17 bits | browser + function | cheap mass submissions: each costs ~130,000 hashes on average, bound to one email, expires in 10 min |
| 2 confirmation emails per address per 10 min | function, memory only | using the form to flood someone's inbox (same answer, no email) |
| Double opt-in | email + `/confirm` | junk and other people's addresses ever reaching the list |
| 300 sign-ups per 10 min, site-wide | database trigger | everything above failing at once (429) |

Honest limits: the in-memory limits are per warm Vercel instance; proof of work raises a bot's
cost but a determined attacker with fast hardware can pay it; a bot can still make you send
confirmation emails to addresses it doesn't own (bounded by the limits above, and those emails
say "ignore this if it wasn't you"). If that happens at scale, add Cloudflare Turnstile or Vercel
firewall rules.

Measured in Chromium in this environment (the work is random, so times vary):

| Difficulty | Desktop | Phone (Pixel 7 emulation, CPU slowed 4x) |
| --- | --- | --- |
| 16 bits | 0.08 to 0.26 s | not measured |
| **17 bits (default)** | 0.24 to 2.5 s, median about 0.75 s | 1.7 to 6.5 s, median about 3.6 s |
| 18 bits | 0.08 to 4.9 s, median about 1.3 s | 4.2 to 20 s: too slow for people |

While it runs the form says "Checking you're not a bot...". To change it, set
`WAITLIST_POW_BITS` (each +1 doubles the average time).

## Verified (tests and checks run while building)

- `tests/waitlist.test.js` (21 Node tests): closed by default and when any setting is missing;
  validation; honeypot; duplicates; method, type and size limits; generic errors with no email in
  logs; same-origin check; per-visitor and per-email limits; the database's 429; proof of work
  (missing, wrong, bound to the email, forged, expired, tampered, difficulty can't be lowered);
  double opt-in (only an email is sent, the link lands on `/confirm`, confirming stores a
  confirmed row, forged/tampered/expired links and challenge-as-token store nothing).
- `supabase/waitlist.sql` on a real PostgreSQL 16 with Supabase's `anon` and `authenticated`
  roles, applied on top of the previous version's table (with a row) and re-applied: the row was
  kept (`confirmed_at` null); anon could insert a confirmed row, but not one confirmed in the
  future; anon could not read, delete, or call the purge, forget or flood-brake functions; the
  flood brake accepted the 300th recent sign-up and refused the 301st; `yie_waitlist_purge()`
  removed only rows older than 12 months; `yie_waitlist_forget()` matched regardless of case and
  spaces. The `pg_cron` schedule itself was not run (no pg_cron locally).
- Real browser with the production security headers, the real function, and the email and
  database simulated: the form solved the challenge and showed "Almost there: we've emailed a
  link..."; nothing was stored; the emailed link opened `/confirm`, which removed the token from
  the address bar; "Confirm my place" stored one confirmed row; a link with no token hides the
  button; a tampered link is refused; no console errors or CSP violations.

## Going live (do these in order)

1. **Choose the Supabase project** for the list (or create one) and run `supabase/waitlist.sql`
   in its SQL editor.
2. **Turn on automatic deletion:** in Supabase, Database, Extensions, enable `pg_cron`, then run
   the `cron.schedule(...)` line from the end of `supabase/waitlist.sql`.
3. **Set up the email provider** (Resend): create an account, verify your sending domain, and
   create an API key with "sending access" only.
4. **Fill in the privacy notice** (`public/privacy.html`): organisation legal name and address,
   contact email, the Supabase region and the email provider. Then delete the "not open yet"
   paragraph (`id="not-open"`).
5. **In Vercel**, project settings, Environment Variables (Production):
   - `SUPABASE_URL` = `https://<project-ref>.supabase.co`
   - `SUPABASE_ANON_KEY` = the project's anon (public) key. Never the service role key.
   - `WAITLIST_SECRET` = 32+ random characters, e.g. the output of `openssl rand -base64 48`.
     Changing it invalidates links already sent.
   - `RESEND_API_KEY` = the sending-only key from step 3
   - `WAITLIST_FROM_EMAIL` = e.g. `Waitlist <waitlist@your-domain>` (a verified domain)
   - `WAITLIST_ENABLED` = `1`
   - Optional: `WAITLIST_POW_BITS` (default 17), `WAITLIST_ALLOWED_ORIGINS` (extra domains,
     comma-separated, e.g. `https://www.example.com`), `WAITLIST_SINGLE_OPT_IN=1` (skip the
     confirmation email; not recommended, and rows are then stored unconfirmed).
6. **Redeploy**, sign up with your own address, open the email, confirm, and check the row in the
   Supabase table editor (`confirmed_at` filled in).
7. **Reading the list:** Supabase dashboard, table `yie_waitlist_signups`. To count demand:
   `select offer, count(*) from public.yie_waitlist_signups where confirmed_at is not null group by offer order by 2 desc;`
   Demand by platform:
   `select p, count(*) from public.yie_waitlist_signups, unnest(other_platforms) p group by p order by 2 desc;`
8. **Removal requests:** `select public.yie_waitlist_forget('their@address');` (returns how many
   rows were deleted).

To pause the waitlist at any time, set `WAITLIST_ENABLED` to `0` and redeploy.

## Still open

- **Unsubscribe link in later emails.** Removal is by emailing the contact address (handled with
  `yie_waitlist_forget`). When you start emailing the list, use a tool that adds an unsubscribe
  link.
- **The product name.** YouTube's brand policies restrict "YouTube" in a commercial product's
  name; choose a commercial name before taking payments.
