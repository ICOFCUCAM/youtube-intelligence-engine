# YouTube API integration strategy

> **Status: not implemented.** Nothing in this repository calls a YouTube API today. All inputs
> are files the creator exports or collects. This document is the plan.

## Why later, and in what order

The offline tools already cover the analysis. The API removes manual exports. Order by value
and risk:

| Phase | Capability | API | OAuth scope | Writes? |
| --- | --- | --- | --- | --- |
| 1 | Channel and video metadata (titles, durations, publish dates, stats) for audit, packaging and outlier research | YouTube Data API v3: `channels.list`, `playlistItems.list` (uploads playlist), `videos.list` | `youtube.readonly` (own channel); an API key for public data | No |
| 1 | Retention and performance (replaces the manual CSV for `yt-retention`) | YouTube Analytics API: `reports.query` (`audienceWatchRatio` by `elapsedVideoTimeRatio`, views, average view duration) | `yt-analytics.readonly` | No |
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

## Shape in code (when built)

```
youtube_intelligence/integrations/youtube/
    auth.py        token loading/refresh from a secret store; no token ever logged
    client.py      thin wrapper; read methods only in phase 1
    mappers.py     API responses -> the same dicts the offline tools already accept
```

The mappers are the point. `retention.analyse` and `outliers.rank` already take plain rows, so
the API is just another input source and the analysis code does not change. Write methods live
in a separate executor that accepts only an **approved action** (see [API_DESIGN.md](API_DESIGN.md)).

## Policy

Follow the YouTube API Services Terms and Developer Policies: data retention limits, no
scraping substitute, clear disclosure to creators of what is accessed and why.
