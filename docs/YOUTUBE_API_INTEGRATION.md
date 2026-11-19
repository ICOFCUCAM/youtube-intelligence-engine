# YouTube API integration strategy

> **Status: phase 1 (read-only) implemented and tested offline. The success path has not been
> verified against the live API.** `yt-youtube` fetches channel uploads (Data API v3, API key) and
> retention curves (Analytics API v2, OAuth) into the files `yt-swipe` and `yt-retention` already
> read. It was tested with a fake transport shaped like Google's documented responses. Against the
> real API, only the transport and error path were exercised, using a deliberately invalid key:
> Google's `400 API key not valid` came back as a clean one-line error with the key redacted.
> No valid credentials were available. The first run with real credentials is the remaining test.
> Phases 2-4 below are still plans.

## Why later, and in what order

The offline tools already cover the analysis. The API removes manual exports. Order by value
and risk:

| Phase | Capability | API | OAuth scope | Writes? |
| --- | --- | --- | --- | --- |
| 1 (built) | Channel and video metadata (titles, durations, publish dates, stats) for audit, packaging and outlier research | YouTube Data API v3: `channels.list`, `playlistItems.list` (uploads playlist), `videos.list` | `youtube.readonly` (own channel); an API key for public data | No |
| 1 (built: retention curve only) | Retention and performance (replaces the manual CSV for `yt-retention`) | YouTube Analytics API: `reports.query` (`audienceWatchRatio` by `elapsedVideoTimeRatio`, views, average view duration) | `yt-analytics.readonly` | No |
| 2 | Comment ingestion for `/yt-comment` triage | Data API `commentThreads.list` | `youtube.readonly` (`youtube.force-ssl` is needed only for writes) | No |
| 2 | Captions for owned videos (transcripts for deadair, chapters, shorts) | Data API `captions.list` / `captions.download` | `youtube.force-ssl` | No (read), but the scope is broad; consider asking creators for a file instead |
| 3 | Playlist management | `playlists.*`, `playlistItems.*` | `youtube` / `youtube.force-ssl` | Yes, behind approval |
| 3 | Metadata updates (title, description, chapters) | `videos.update` | `youtube.force-ssl` | Yes, behind approval |
| 3 | Comment replies | `comments.insert` | `youtube.force-ssl` | Yes, behind approval |
| 4 | Publishing | `videos.insert` (resumable upload), `thumbnails.set` | `youtube.upload` | Yes, behind approval, and only once CineForge hands over a rendered file |

## OAuth 2.0

- Authorization Code flow with PKCE for installed or desktop use. A server-side web flow for TAKE.
- Client ID and secret from environment variables (for example `YT_OAUTH_CLIENT_ID`,
  `YT_OAUTH_CLIENT_SECRET`) or a secrets manager, never a committed `client_secret.json`.
- Refresh tokens stored encrypted, per channel, with a visible "disconnect" that revokes them.
- Incremental authorization: request a write scope only when the creator enables the feature
  that needs it.
- Unverified apps face user caps and warning screens, and sensitive or restricted scopes need
  Google verification. Plan the verification before shipping write scopes.

## Quota and reliability

The Data API uses a daily unit quota per project, and method costs differ a lot (searches and
uploads are expensive; `list` calls by ID are cheap). Check the current quota table in Google's
documentation rather than hard-coding costs. Design rules:
- Prefer the uploads playlist plus `videos.list` (batched IDs) over `search.list`.
- Cache metadata with ETags. Back off on `quotaExceeded` and `rateLimitExceeded`.
- Analytics data lags by up to a few days. Show the "as of" date.

## What exists (phase 1)

```
youtube_intelligence/integrations/youtube/
    transport.py   the only network code: HTTPS only, 30 s timeout, 20 MB response cap; injectable
    auth.py        credentials from environment variables; refresh-token exchange; refuses tokens
                   that carry any scope beyond youtube.readonly / yt-analytics.readonly;
                   secrets redacted from errors and logs, never in repr()
    client.py      GET-only to two allowlisted API bases; channels.list (id / forHandle / mine),
                   playlistItems.list (paged, capped), videos.list (batches of 50),
                   reports.query (audienceWatchRatio x elapsedVideoTimeRatio); retries 429/5xx
                   with backoff, never retries quotaExceeded
    mappers.py     API JSON -> yt-swipe rows and a yt-retention CSV (percent axis)
    login.py       browser consent (PKCE + loopback) for a read-only refresh token, saved 0600
    cli.py         yt-youtube channel-videos | retention | login
```

```bash
export YOUTUBE_API_KEY=...        # from a secrets manager
```

```bash
yt-youtube channel-videos --handle @ChannelA --handle @ChannelB --limit 30 --out collected.json
```

```bash
yt-swipe collected.json --min 2.0
```

```bash
yt-youtube retention VIDEO_ID --start 2026-01-01 --end 2026-11-01 --out retention.csv
```

```bash
yt-retention retention.csv --duration 600 --views 4200
```

Variable names are listed in [`.env.example`](../.env.example).

### Getting a read-only token: `yt-youtube login`

```bash
yt-youtube login --save ~/.config/youtube-intelligence/token.json
```

```bash
export YT_OAUTH_TOKEN_FILE=~/.config/youtube-intelligence/token.json
```

It needs `YT_OAUTH_CLIENT_ID` and `YT_OAUTH_CLIENT_SECRET` from a **Desktop app** OAuth client
in Google Cloud. It opens Google's consent page asking only for `youtube.readonly` and
`yt-analytics.readonly`, receives the redirect on a one-time 127.0.0.1 listener, checks a random
`state`, uses PKCE (S256), and refuses the result if Google grants any other scope. The refresh
token goes to the named file with mode 600, never to the screen. The save path is checked before
the browser opens: paths inside a git working tree and existing files (without `--force`) are
refused. Tools read the file through `YT_OAUTH_TOKEN_FILE` and refuse it if other users can read
it. **Status:** tested with a simulated browser and token endpoint (real loopback HTTP); not yet
run against Google's consent screen.

Guarantees enforced by tests (`tests/test_youtube_integration.py`): the client's public methods
are an exact read-only allowlist; every API request is a GET to an allowlisted host; tokens with
write scopes are refused; keys never appear in errors, logs or `repr`; quota errors are not
retried.

The mappers are the point. `retention.analyse` and `outliers.rank` already take plain rows, so
the API is just another input source and the analysis code does not change. Write methods live
in a separate executor that accepts only an **approved action** (see [API_DESIGN.md](API_DESIGN.md)).

## Policy

Follow the YouTube API Services Terms and Developer Policies: data retention limits, no
scraping substitute, clear disclosure to creators of what is accessed and why.
