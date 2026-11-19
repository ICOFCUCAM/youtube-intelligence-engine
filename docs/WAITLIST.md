# Waitlist (demand test)

The landing page has a **Plans** section (planned prices, clearly not on sale) and a waitlist
form. Its purpose is to learn which offer people want before building one.

**Status: built and switched off.** Until the steps below are done, the form tells visitors
"the waitlist isn't open yet - nothing was saved", and the server function answers `503` and
stores nothing.

## How it works

```
browser form --fetch POST /api/waitlist--> api/waitlist.js (Vercel function)
                                                  | validates, drops bot submissions (honeypot)
                                                  v
                       Supabase REST with the project's ANON key -> public.yie_waitlist_signups
                       (row level security: anon may INSERT only; no read, update or delete)
```

Stored per sign-up: email (lower-cased), offer (`reports`, `shorts`, `agency`, `api`,
`not_sure`), optional channel size, optional other platforms they post on (`tiktok`,
`instagram`, `facebook`, `linkedin`, `x`, `podcasts`, or `none`), consent version (`2026-11-v2`,
matching the privacy notice), and a timestamp. No IP address, user agent or cookies. Emails are never logged. A duplicate email
gets the same "you're on the list" answer, so the form can't be used to check who signed up.

Verified (tests and checks run while building):
- `tests/waitlist.test.js` (10 Node tests, including the platform rules): closed by default, validation, honeypot, duplicates,
  method, type and size limits, generic errors, no email in logs.
- `supabase/waitlist.sql` applied twice to a real PostgreSQL 16 database with Supabase's `anon`
  and `authenticated` roles. Anon could insert one valid row, and every other action was refused:
  duplicates, invalid offer, unnormalised email, setting `created_at`, SELECT, UPDATE, DELETE, and
  inserting as `authenticated`. With Supabase-style blanket grants given to anon first,
  re-applying the script still left anon unable to read or delete.
- Upgrade path: the current script applied twice on top of the first version's table (with a
  row in it) added `other_platforms` (existing row: empty list) and its rules: unknown platforms
  and "none" combined with a platform are refused.
- Real browser with the production security headers: form validation, the closed message, a
  successful sign-up (with the endpoint simulated), the exact JSON sent, and no CSP violations.

## Going live (do these in order)

1. **Choose the Supabase project** for the list (or create one) and run `supabase/waitlist.sql`
   in its SQL editor.
2. **Fill in the privacy notice** (`public/privacy.html`): organisation legal name and address,
   contact email, and the Supabase region. Then delete the "not open yet" paragraph
   (`id="not-open"`).
3. **In Vercel**, project settings, Environment Variables (Production):
   - `SUPABASE_URL` = `https://<project-ref>.supabase.co`
   - `SUPABASE_ANON_KEY` = the project's anon (public) key. Never the service role key.
   - `WAITLIST_ENABLED` = `1`
4. **Redeploy**, then submit a real test sign-up and check it in the Supabase table editor.
5. **Reading the list:** Supabase dashboard, table `yie_waitlist_signups`. To count demand:
   `select offer, count(*) from public.yie_waitlist_signups group by offer order by 2 desc;`
   Demand by platform (does multi-platform matter?):
   `select p, count(*) from public.yie_waitlist_signups, unnest(other_platforms) p group by p order by 2 desc;`

To pause the waitlist at any time, set `WAITLIST_ENABLED` to `0` and redeploy.

## Not built (decide before relying on it)

- **No rate limiting or CAPTCHA.** A determined bot can add junk rows. The honeypot stops simple
  bots. If spam appears, add Cloudflare Turnstile or Vercel's firewall rules.
- **No confirmation email (double opt-in).** Recommended before emailing the list in the EU.
- **No automatic deletion.** The notice promises deletion within 12 months of the waitlist
  closing: put a reminder in the calendar, or schedule a `delete` in Supabase.
- **The product name.** YouTube's brand policies restrict "YouTube" in a commercial product's
  name; choose a commercial name before taking payments.
