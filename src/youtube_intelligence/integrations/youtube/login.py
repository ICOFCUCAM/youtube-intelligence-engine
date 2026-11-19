"""Browser consent for a READ-ONLY refresh token (OAuth 2.0 for installed apps, PKCE + loopback).

    export YT_OAUTH_CLIENT_ID=... YT_OAUTH_CLIENT_SECRET=...   # a "Desktop app" OAuth client
    yt-youtube login --save ~/.config/youtube-intelligence/token.json
    export YT_OAUTH_TOKEN_FILE=~/.config/youtube-intelligence/token.json

Flow: a one-time HTTP listener on 127.0.0.1 (random port) receives Google's redirect; a random
``state`` guards against forged redirects; PKCE (S256) binds the code to this process. The token
response is refused unless it grants ONLY youtube.readonly / yt-analytics.readonly.

The refresh token is written to the file you name with owner-only permissions (0600), never
printed. Paths inside a git working tree are refused so the token cannot be committed by
accident. Status: tested with a simulated browser and token endpoint; not yet run against Google.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.parse
from typing import Callable, Dict, Optional

from .auth import READ_ONLY_SCOPES, TOKEN_URL, AuthError, Credentials, redact
from .transport import Transport, default_transport

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_UNRESERVED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def pkce_pair() -> Dict[str, str]:
    """RFC 7636: 43-128 unreserved characters, challenge = BASE64URL(SHA256(verifier)) unpadded."""
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    return {"verifier": verifier, "challenge": challenge}


def auth_url(client_id: str, redirect_uri: str, challenge: str, state: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": " ".join(READ_ONLY_SCOPES), "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "false", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})


class _Receiver(http.server.HTTPServer):
    result: Optional[Dict[str, str]] = None
    expected_state: str = ""


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server API
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        srv: _Receiver = self.server  # type: ignore[assignment]
        if q.get("state") != srv.expected_state:
            res, msg = {"error": "state mismatch - possible forged redirect"}, "Sign-in failed: state mismatch."
        elif "error" in q:
            res, msg = {"error": q["error"]}, f"Sign-in was not completed ({q['error']})."
        elif "code" in q:
            res, msg = {"code": q["code"]}, "Signed in. You can close this tab and return to the terminal."
        else:
            res, msg = {"error": "no code in redirect"}, "Sign-in failed."
        if srv.result is None:
            srv.result = res
        body = f"<!doctype html><meta charset=utf-8><title>yt-youtube</title><p>{msg}</p>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the code out of terminal logs
        pass


def exchange_code(code: str, verifier: str, redirect_uri: str, creds: Credentials,
                  transport: Transport) -> Dict:
    body = urllib.parse.urlencode({"grant_type": "authorization_code", "code": code,
                                   "code_verifier": verifier, "redirect_uri": redirect_uri,
                                   "client_id": creds.client_id, "client_secret": creds.client_secret}).encode()
    status, raw = transport("POST", TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, body)
    try:
        d = json.loads(raw.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError:
        d = {}
    if status != 200 or "refresh_token" not in d:
        reason = d.get("error_description") or d.get("error") or f"HTTP {status}"
        if status == 200:
            reason = "no refresh token returned (revoke the app's access and sign in again)"
        raise AuthError(redact(f"code exchange failed: {reason}", [creds.client_secret, code, verifier]))
    granted = set(str(d.get("scope", "")).split())
    if granted - set(READ_ONLY_SCOPES):
        raise AuthError("Google granted more than read-only access "
                        f"({', '.join(sorted(granted - set(READ_ONLY_SCOPES)))}); token discarded")
    return d


def login(creds: Credentials, open_url: Optional[Callable[[str], object]] = None,
          transport: Optional[Transport] = None, timeout: float = 300.0,
          announce: Callable[[str], None] = print) -> Dict:
    """Run the consent flow and return the token response (refresh_token, scope, ...)."""
    if not (creds.client_id and creds.client_secret):
        raise AuthError("set YT_OAUTH_CLIENT_ID and YT_OAUTH_CLIENT_SECRET (a Desktop app OAuth client)")
    srv = _Receiver(("127.0.0.1", 0), _Handler)
    srv.expected_state = secrets.token_urlsafe(24)
    redirect_uri = f"http://127.0.0.1:{srv.server_address[1]}/"
    pk = pkce_pair()
    url = auth_url(creds.client_id, redirect_uri, pk["challenge"], srv.expected_state)
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    thread.start()
    try:
        announce("Open this URL to grant READ-ONLY access (youtube.readonly, yt-analytics.readonly):\n" + url)
        if open_url:
            try:
                open_url(url)
            except Exception:  # noqa: BLE001 - a browser failing to open is not fatal
                pass
        deadline = time.monotonic() + timeout
        while srv.result is None and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        srv.shutdown()
        srv.server_close()
    if srv.result is None:
        raise AuthError(f"no response from the browser within {int(timeout)} s")
    if "error" in srv.result:
        raise AuthError(f"sign-in failed: {srv.result['error']}")
    return exchange_code(srv.result["code"], pk["verifier"], redirect_uri, creds, transport or default_transport)


def inside_git_worktree(path: str) -> bool:
    d = os.path.dirname(os.path.abspath(os.path.expanduser(path)))
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return True
        parent = os.path.dirname(d)
        if parent == d:
            return False
        d = parent


def check_save_path(path: str, force: bool = False) -> str:
    """Validate the token destination. Called BEFORE the consent flow, so a bad path fails fast
    instead of after the user has already signed in."""
    path = os.path.abspath(os.path.expanduser(path))
    if inside_git_worktree(path):
        raise AuthError(f"refusing to write a token inside a git working tree ({path}); choose a path "
                        "outside any repository, e.g. ~/.config/youtube-intelligence/token.json")
    if os.path.exists(path) and not force:
        raise AuthError(f"{path} exists; pass --force to replace it")
    return path


def save_token(token: Dict, path: str, force: bool = False) -> str:
    path = check_save_path(path, force)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    data = json.dumps({"refresh_token": token["refresh_token"], "scope": token.get("scope", ""),
                       "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=1)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(data + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def read_token_file(path: str) -> str:
    """Refresh token from a file written by save_token. Refused if group/world can read it."""
    path = os.path.abspath(os.path.expanduser(path))
    try:
        st = os.stat(path)
    except FileNotFoundError:
        raise AuthError(f"YT_OAUTH_TOKEN_FILE not found: {path}") from None
    if os.name == "posix" and st.st_mode & 0o077:
        raise AuthError(f"{path} is readable by other users; run: chmod 600 {path}")
    try:
        with open(path, encoding="utf-8") as fh:
            tok = json.load(fh).get("refresh_token")
    except (OSError, json.JSONDecodeError, AttributeError):
        tok = None
    if not tok:
        raise AuthError(f"{path} does not contain a refresh_token")
    return tok
