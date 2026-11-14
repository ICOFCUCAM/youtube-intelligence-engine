"""Credentials from the environment. Never from files in the repository, never logged.

Public data (channel and video metadata) needs only an API key:

    YOUTUBE_API_KEY

The Analytics API (retention) needs OAuth for the channel owner. Supply either a short-lived
access token, or a refresh token plus the OAuth client it was issued to:

    YT_OAUTH_ACCESS_TOKEN
    YT_OAUTH_REFRESH_TOKEN + YT_OAUTH_CLIENT_ID + YT_OAUTH_CLIENT_SECRET

The refresh token must have been granted ONLY the read-only scopes below. Obtaining one (the
browser consent step) is not implemented here yet; use a secrets manager to inject these values
rather than an .env file committed anywhere.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
from dataclasses import dataclass
from typing import Callable, Dict, Mapping, Optional

from ...core.errors import InputError
from .transport import Transport, default_transport

READ_ONLY_SCOPES = (
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
)
TOKEN_URL = "https://oauth2.googleapis.com/token"


class AuthError(InputError):
    """Credentials missing, rejected, or granted more than read-only scopes."""


def redact(text: str, secrets) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "<redacted>")
    return text


@dataclass
class Credentials:
    api_key: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Credentials":
        g = lambda k: (env.get(k) or "").strip() or None  # noqa: E731
        return cls(api_key=g("YOUTUBE_API_KEY"), access_token=g("YT_OAUTH_ACCESS_TOKEN"),
                   refresh_token=g("YT_OAUTH_REFRESH_TOKEN"), client_id=g("YT_OAUTH_CLIENT_ID"),
                   client_secret=g("YT_OAUTH_CLIENT_SECRET"))

    def secrets(self):
        return [self.api_key, self.access_token, self.refresh_token, self.client_secret]

    @property
    def has_oauth(self) -> bool:
        return bool(self.access_token or (self.refresh_token and self.client_id and self.client_secret))

    def __repr__(self) -> str:  # never print secret values
        flags = {k: bool(getattr(self, k)) for k in ("api_key", "access_token", "refresh_token", "client_id", "client_secret")}
        shown = ", ".join(k + "=" + ("set" if v else "unset") for k, v in flags.items())
        return f"Credentials({shown})"


class TokenProvider:
    """Returns a valid OAuth access token, refreshing it when needed. Read-only scopes only."""

    def __init__(self, creds: Credentials, transport: Optional[Transport] = None,
                 clock: Callable[[], float] = time.time):
        if not creds.has_oauth:
            raise AuthError("OAuth is required for this request: set YT_OAUTH_ACCESS_TOKEN, or "
                            "YT_OAUTH_REFRESH_TOKEN with YT_OAUTH_CLIENT_ID and YT_OAUTH_CLIENT_SECRET")
        self.creds = creds
        self.transport = transport or default_transport
        self.clock = clock
        self._token = creds.access_token if not creds.refresh_token else None
        self._expires = float("inf") if self._token else 0.0

    def __call__(self) -> str:
        if self._token and self.clock() < self._expires - 60:
            return self._token
        c = self.creds
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": c.refresh_token,
                                       "client_id": c.client_id, "client_secret": c.client_secret}).encode()
        status, raw = self.transport("POST", TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, body)
        try:
            d: Dict = json.loads(raw.decode("utf-8", "replace") or "{}")
        except json.JSONDecodeError:
            d = {}
        if status != 200 or "access_token" not in d:
            reason = d.get("error_description") or d.get("error") or f"HTTP {status}"
            raise AuthError(redact(f"token refresh failed: {reason}", c.secrets()))
        granted = set(str(d.get("scope", "")).split())
        extra = granted - set(READ_ONLY_SCOPES)
        if extra:
            raise AuthError("the refresh token grants more than read-only access "
                            f"({', '.join(sorted(extra))}); issue one with only the read-only scopes")
        self._token = d["access_token"]
        self._expires = self.clock() + float(d.get("expires_in", 3600))
        return self._token
