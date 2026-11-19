"""yt-serve - the engine as a local HTTP/JSON service.

    yt-serve                                  # http://127.0.0.1:8765, loopback only
    YIE_API_TOKEN=... yt-serve --host 0.0.0.0 --port 8765

    curl -s localhost:8765/v1/health
    curl -s -X POST localhost:8765/v1/titles/check -H 'Content-Type: application/json' \\
         -d '{"titles": ["Why your channel is not growing"]}'

Endpoints (all JSON): GET /v1/health; POST /v1/edl, /v1/chapters, /v1/hooks/score,
/v1/titles/check, /v1/retention, /v1/outliers, /v1/shorts. See docs/API_DESIGN.md.

Safety: binds to 127.0.0.1 unless told otherwise, and refuses a non-loopback address without
YIE_API_TOKEN; when a token is set every POST needs ``Authorization: Bearer <token>`` (constant-
time compare). POST bodies must be JSON with a Content-Length of at most 8 MB; sockets time out
after 30 s; responses are ``no-store``; request bodies are never logged; no CORS headers are sent.
It is stateless and makes no outbound calls. It is a development/integration server (Python's
ThreadingHTTPServer): put it behind a TLS-terminating reverse proxy before exposing it.
"""
from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List, Optional

from .. import __version__
from ..core.cli import guarded
from ..core.errors import InputError
from . import app

MAX_BODY = 8 * 1024 * 1024
SOCKET_TIMEOUT = 30


def _is_loopback(host: str) -> bool:
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class Handler(BaseHTTPRequestHandler):
    server_version = f"youtube-intelligence-engine/{__version__}"
    sys_version = ""
    timeout = SOCKET_TIMEOUT
    token: Optional[str] = None
    quiet = False

    # -- plumbing -------------------------------------------------------------------------------------
    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _fail(self, status: int, code: str, message: str, unread_body: bool = False) -> None:
        if unread_body:
            # The request body was not consumed; never reuse this connection, or its leftover
            # bytes would be parsed as the next request.
            self.close_connection = True
        self._send(*app.error(status, code, message))

    def log_message(self, fmt, *args):  # method, path and status only - never bodies or headers
        if not self.quiet:
            sys.stderr.write(f"{self.address_string()} {fmt % args}\n")

    def _authorised(self) -> bool:
        if not self.token:
            return True
        got = self.headers.get("Authorization", "")
        return hmac.compare_digest(got.encode(), f"Bearer {self.token}".encode())

    # -- methods --------------------------------------------------------------------------------------
    def do_GET(self):  # noqa: N802
        self._send(*app.handle("GET", self.path))

    def do_POST(self):  # noqa: N802
        if not self._authorised():
            return self._fail(401, "unauthorised", "missing or wrong bearer token", unread_body=True)
        ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return self._fail(415, "unsupported_media_type", "send Content-Type: application/json", unread_body=True)
        length = self.headers.get("Content-Length")
        if length is None or not length.isdigit():
            return self._fail(411, "length_required", "Content-Length is required", unread_body=True)
        n = int(length)
        if n > MAX_BODY:
            return self._fail(413, "payload_too_large", f"request body is larger than {MAX_BODY // (1024 * 1024)} MB",
                              unread_body=True)
        try:
            raw = self.rfile.read(n)
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._fail(400, "invalid_json", "request body is not valid UTF-8 JSON")
        except OSError:
            return
        self._send(*app.handle("POST", self.path, body, log=lambda m: sys.stderr.write(m + "\n")))

    def _not_allowed(self):
        self._fail(405, "method_not_allowed", f"{self.command} is not supported")

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _not_allowed  # noqa: N815


def make_server(host: str = "127.0.0.1", port: int = 8765, token: Optional[str] = None,
                quiet: bool = False) -> ThreadingHTTPServer:
    if not _is_loopback(host) and not token:
        raise InputError(f"refusing to listen on {host} without YIE_API_TOKEN - set a token, or use 127.0.0.1")
    handler = type("BoundHandler", (Handler,), {"token": token, "quiet": quiet})
    srv = ThreadingHTTPServer((host, port), handler)
    srv.daemon_threads = True
    return srv


@guarded
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="yt-serve", description=__doc__.split("\n\n")[0])
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--quiet", action="store_true", help="no access log")
    a = p.parse_args(argv)
    token = (os.environ.get("YIE_API_TOKEN") or "").strip() or None
    if token is not None and len(token) < 16:
        raise InputError("YIE_API_TOKEN must be at least 16 characters")
    srv = make_server(a.host, a.port, token, a.quiet)
    host, port = srv.server_address[:2]
    print(f"youtube-intelligence-engine {__version__} on http://{host}:{port}  "
          f"(auth: {'bearer token' if token else 'none - loopback only'})", file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
