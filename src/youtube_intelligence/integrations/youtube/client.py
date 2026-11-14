"""Read-only client for the YouTube Data API v3 and YouTube Analytics API v2.

Every request goes through ``_get``: GET only, to one of two allowlisted API bases, with the API
key as a query parameter (public data) or an OAuth bearer token (owner data). There is no code
path that sends POST/PUT/DELETE to an API host.
"""
from __future__ import annotations

import json
import time
import urllib.parse
from typing import Callable, Dict, Iterable, List, Optional

from ...core.errors import InputError
from .auth import Credentials, TokenProvider, redact
from .transport import Transport, default_transport

DATA_API = "https://www.googleapis.com/youtube/v3/"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/"
ALLOWED_BASES = (DATA_API, ANALYTICS_API)
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
MAX_PAGES = 100  # 100 x 50 = 5,000 uploads; a guard against runaway pagination


class YouTubeAPIError(InputError):
    def __init__(self, status: int, reason: str, message: str):
        self.status, self.reason = status, reason
        super().__init__(f"YouTube API {status} {reason}: {message}")


class YouTubeClient:
    def __init__(self, creds: Optional[Credentials] = None, transport: Optional[Transport] = None,
                 sleep: Callable[[float], None] = time.sleep, log: Optional[Callable[[str], None]] = None):
        self.creds = creds or Credentials.from_env()
        self.transport = transport or default_transport
        self.sleep = sleep
        self.log = log
        self._tokens: Optional[TokenProvider] = None
        self.requests = 0

    # -- plumbing -----------------------------------------------------------------------------
    def _bearer(self) -> str:
        if self._tokens is None:
            self._tokens = TokenProvider(self.creds, self.transport)
        return self._tokens()

    def _get(self, base: str, path: str, params: Dict, owner: bool = False) -> Dict:
        if base not in ALLOWED_BASES:
            raise InputError(f"refusing request to non-allowlisted base {base}")
        q = {k: v for k, v in params.items() if v is not None}
        headers = {"Accept": "application/json"}
        if owner:
            headers["Authorization"] = "Bearer " + self._bearer()
        elif self.creds.api_key:
            q["key"] = self.creds.api_key
        elif self.creds.has_oauth:
            headers["Authorization"] = "Bearer " + self._bearer()
        else:
            raise InputError("no credentials: set YOUTUBE_API_KEY for public data "
                             "(or the YT_OAUTH_* variables) - see `yt-youtube --help`")
        url = base + path + "?" + urllib.parse.urlencode(q, doseq=True)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self.requests += 1
            if self.log:
                self.log(redact(f"GET {url}", self.creds.secrets()))
            status, raw = self.transport("GET", url, headers, None)
            try:
                body = json.loads(raw.decode("utf-8", "replace") or "{}")
            except json.JSONDecodeError:
                body = {}
            if status == 200:
                if not isinstance(body, dict):
                    raise InputError("unexpected response shape from YouTube")
                return body
            err = body.get("error", {}) if isinstance(body, dict) else {}
            reasons = [e.get("reason", "") for e in err.get("errors", []) if isinstance(e, dict)]
            reason = reasons[0] if reasons else str(err.get("status", "error"))
            msg = redact(str(err.get("message", "request failed")), self.creds.secrets())
            transient = status in RETRY_STATUS or reason in ("rateLimitExceeded", "userRateLimitExceeded", "backendError")
            if reason in ("quotaExceeded", "dailyLimitExceeded") or not transient or attempt == MAX_ATTEMPTS:
                if reason in ("quotaExceeded", "dailyLimitExceeded"):
                    msg += " - the project's daily quota is used up; it resets at midnight Pacific time"
                raise YouTubeAPIError(status, reason, msg)
            self.sleep(2 ** attempt)
        raise AssertionError("unreachable")

    # -- Data API (public with an API key) ------------------------------------------------------
    def channel(self, channel_id: Optional[str] = None, handle: Optional[str] = None, mine: bool = False) -> Dict:
        if sum(bool(x) for x in (channel_id, handle, mine)) != 1:
            raise InputError("give exactly one of a channel id, a handle, or --mine")
        params = {"part": "snippet,contentDetails,statistics", "id": channel_id,
                  "forHandle": ("@" + handle.lstrip("@")) if handle else None, "mine": "true" if mine else None}
        items = self._get(DATA_API, "channels", params, owner=mine).get("items") or []
        if not items:
            raise InputError(f"channel not found: {channel_id or handle or 'mine'}")
        return items[0]

    def playlist_video_ids(self, playlist_id: str, limit: int = 50) -> List[str]:
        ids: List[str] = []
        token = None
        for _ in range(MAX_PAGES):
            d = self._get(DATA_API, "playlistItems", {"part": "contentDetails", "playlistId": playlist_id,
                                                      "maxResults": 50, "pageToken": token})
            for it in d.get("items") or []:
                vid = (it.get("contentDetails") or {}).get("videoId")
                if vid:
                    ids.append(vid)
                if len(ids) >= limit:
                    return ids
            token = d.get("nextPageToken")
            if not token:
                break
        return ids

    def videos(self, ids: Iterable[str]) -> List[Dict]:
        ids = list(ids)
        out: List[Dict] = []
        for i in range(0, len(ids), 50):
            d = self._get(DATA_API, "videos", {"part": "snippet,contentDetails,statistics",
                                               "id": ",".join(ids[i:i + 50]), "maxResults": 50})
            out.extend(d.get("items") or [])
        return out

    def recent_uploads(self, limit: int = 50, **channel_kw) -> Dict:
        ch = self.channel(**channel_kw)
        uploads = ((ch.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
        if not uploads:
            raise InputError("channel has no uploads playlist")
        return {"channel": ch, "videos": self.videos(self.playlist_video_ids(uploads, limit))}

    # -- Analytics API (owner OAuth) --------------------------------------------------------------
    def retention_report(self, video_id: str, start_date: str, end_date: str) -> Dict:
        return self._get(ANALYTICS_API, "reports", {
            "ids": "channel==MINE", "startDate": start_date, "endDate": end_date,
            "metrics": "audienceWatchRatio", "dimensions": "elapsedVideoTimeRatio",
            "filters": f"video=={video_id}", "sort": "elapsedVideoTimeRatio"}, owner=True)
