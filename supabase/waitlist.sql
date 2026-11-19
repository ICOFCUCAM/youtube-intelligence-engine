-- YouTube Intelligence Engine: waitlist table (demand test).
-- Apply once to the Supabase project chosen for the waitlist (SQL editor, or a migration).
-- Data minimisation: email, the offer they want, optional channel size, the consent-text version
-- they agreed to, and when. No IP address, no user agent, no tracking.
--
-- Security model: the website's server function uses the project's ANON key. Row level security
-- lets anon INSERT only. Anon cannot SELECT, UPDATE or DELETE, so a leaked anon key cannot be
-- used to read or wipe the list. Read the list from the Supabase dashboard (service role).

create table if not exists public.yie_waitlist_signups (
  id               bigint generated always as identity primary key,
  email            text        not null
                   check (char_length(email) between 6 and 254
                          and email = lower(email)
                          and email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'),
  offer            text        not null
                   check (offer in ('shorts', 'reports', 'agency', 'api', 'not_sure')),
  channel_size     text
                   check (channel_size is null
                          or channel_size in ('starting', 'under_1k', '1k_10k', '10k_100k', 'over_100k')),
  consent_version  text        not null check (char_length(consent_version) between 1 and 20),
  created_at       timestamptz not null default now()
);

create unique index if not exists yie_waitlist_signups_email_key
  on public.yie_waitlist_signups (email);

alter table public.yie_waitlist_signups enable row level security;

revoke all on public.yie_waitlist_signups from anon, authenticated;
grant insert (email, offer, channel_size, consent_version) on public.yie_waitlist_signups to anon;

drop policy if exists "website can add signups" on public.yie_waitlist_signups;
create policy "website can add signups"
  on public.yie_waitlist_signups
  for insert
  to anon
  with check (true);

comment on table public.yie_waitlist_signups is
  'YouTube Intelligence Engine waitlist. Insert-only for anon. Delete rows 12 months after the '
  'waitlist closes, or on request (see public/privacy.html).';
