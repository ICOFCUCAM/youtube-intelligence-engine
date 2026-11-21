-- YouTube Intelligence Engine: waitlist table (demand test).
-- Apply once to the Supabase project chosen for the waitlist (SQL editor, or a migration).
-- Data minimisation: email, the offer they want, optional channel size, optional other platforms
-- they post on, the consent-text version they agreed to, when, and when they confirmed by email.
-- No IP address, no user agent, no tracking. Unconfirmed sign-ups are never stored: the website
-- only inserts a row after the person clicks the link in the confirmation email (double opt-in).
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
  other_platforms  text[]      not null default '{}',
  consent_version  text        not null check (char_length(consent_version) between 1 and 20),
  created_at       timestamptz not null default now()
);

-- Re-runnable on a table created by an earlier version of this script.
alter table public.yie_waitlist_signups add column if not exists other_platforms text[] not null default '{}';
alter table public.yie_waitlist_signups drop constraint if exists yie_waitlist_signups_other_platforms_check;
alter table public.yie_waitlist_signups add constraint yie_waitlist_signups_other_platforms_check check (
  other_platforms <@ array['tiktok', 'instagram', 'facebook', 'linkedin', 'x', 'podcasts', 'none']::text[]
  and cardinality(other_platforms) <= 7
  and not ('none' = any(other_platforms) and cardinality(other_platforms) > 1)
);

-- Double opt-in: when the person clicked the emailed link. Null only for rows added with
-- WAITLIST_SINGLE_OPT_IN=1 (or by an earlier version), which were never confirmed.
alter table public.yie_waitlist_signups add column if not exists confirmed_at timestamptz;
alter table public.yie_waitlist_signups drop constraint if exists yie_waitlist_signups_confirmed_at_check;
alter table public.yie_waitlist_signups add constraint yie_waitlist_signups_confirmed_at_check
  check (confirmed_at is null or confirmed_at <= now() + interval '5 minutes');

create unique index if not exists yie_waitlist_signups_email_key
  on public.yie_waitlist_signups (email);

alter table public.yie_waitlist_signups enable row level security;

revoke all on public.yie_waitlist_signups from anon, authenticated;
grant insert (email, offer, channel_size, other_platforms, consent_version, confirmed_at)
  on public.yie_waitlist_signups to anon;

drop policy if exists "website can add signups" on public.yie_waitlist_signups;
create policy "website can add signups"
  on public.yie_waitlist_signups
  for insert
  to anon
  with check (true);

-- Flood brake: refuse new rows when too many arrived site-wide in the last 10 minutes, whatever
-- the website function's own per-visitor limit missed (several instances, many addresses).
-- PostgREST turns SQLSTATE 'PT429' into HTTP 429, which the website shows as "try again in a few
-- minutes". 300 per 10 minutes is far above a normal launch day; raise it here if you need to.
create index if not exists yie_waitlist_signups_created_at_idx
  on public.yie_waitlist_signups (created_at);

create or replace function public.yie_waitlist_flood_brake()
  returns trigger
  language plpgsql
  security definer
  set search_path = ''
as $$
declare
  recent integer;
begin
  -- one counter at a time, so a burst of parallel inserts can't all slip under the limit
  perform pg_advisory_xact_lock(hashtext('yie_waitlist_flood_brake'));
  select count(*) into recent
    from public.yie_waitlist_signups
   where created_at > now() - interval '10 minutes';
  if recent >= 300 then
    raise sqlstate 'PT429' using message = 'waitlist is busy, try again later';
  end if;
  return new;
end;
$$;

revoke all on function public.yie_waitlist_flood_brake() from public, anon, authenticated;

drop trigger if exists yie_waitlist_flood_brake on public.yie_waitlist_signups;
create trigger yie_waitlist_flood_brake
  before insert on public.yie_waitlist_signups
  for each row execute function public.yie_waitlist_flood_brake();

-- Deletion (owner only; the website cannot call these).
--   select public.yie_waitlist_forget('someone@example.org');   -- a removal request: rows deleted
--   select public.yie_waitlist_purge();                         -- everything older than 12 months
create or replace function public.yie_waitlist_purge(older_than interval default interval '12 months')
  returns integer
  language sql
  set search_path = ''
as $$
  with gone as (
    delete from public.yie_waitlist_signups where created_at < now() - older_than returning 1
  )
  select count(*)::integer from gone;
$$;

create or replace function public.yie_waitlist_forget(address text)
  returns integer
  language sql
  set search_path = ''
as $$
  with gone as (
    delete from public.yie_waitlist_signups where email = lower(trim(address)) returning 1
  )
  select count(*)::integer from gone;
$$;

revoke all on function public.yie_waitlist_purge(interval) from public, anon, authenticated;
revoke all on function public.yie_waitlist_forget(text) from public, anon, authenticated;

-- Automatic deletion (recommended): enable the pg_cron extension in Supabase (Database,
-- Extensions), then run this once. It deletes sign-ups older than 12 months every night at 03:17.
--   select cron.schedule('yie-waitlist-purge', '17 3 * * *',
--                        $job$select public.yie_waitlist_purge(interval '12 months')$job$);
-- Check it:  select * from cron.job;     Stop it:  select cron.unschedule('yie-waitlist-purge');

comment on table public.yie_waitlist_signups is
  'YouTube Intelligence Engine waitlist. Insert-only for anon. Rows are deleted 12 months after '
  'sign-up (yie_waitlist_purge, scheduled with pg_cron) or on request (yie_waitlist_forget). '
  'See public/privacy.html.';
