"""yt-youtube - fetch data from YouTube, read-only, into files the other tools read.

    yt-youtube channel-videos --handle @SomeChannel --handle @Other --limit 30 --out collected.json
    yt-swipe collected.json --min 2.0

    yt-youtube retention VIDEO_ID --start 2026-01-01 --end 2026-11-01 --out retention.csv
    yt-retention retention.csv --duration 600

    yt-youtube comments VIDEO_ID --out comments.json
    yt-comments comments.json --creator "Your Channel"

    yt-youtube login --save ~/.config/youtube-intelligence/token.json   # read-only consent

Credentials come from the environment only (see youtube_intelligence.integrations.youtube.auth):
YOUTUBE_API_KEY for public channel data; YT_OAUTH_* for --mine and for retention (owner data,
read-only scopes). Nothing here can publish, edit, reply or delete.

Not yet verified against the live API - see the package docstring.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import List, Optional

from ...core.cli import guarded
from ...core.errors import InputError
from .auth import Credentials
from .client import YouTubeClient
from .login import check_save_path, login, save_token
from .mappers import comments_to_rows, retention_to_rows, videos_to_rows, write_retention_csv

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_VIDEO = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _client(a) -> YouTubeClient:
    log = (lambda m: print(m, file=sys.stderr)) if a.verbose else None
    return YouTubeClient(log=log)


def cmd_channel_videos(a, client: YouTubeClient) -> int:
    targets = [("channel_id", c) for c in a.channel_id or []] + [("handle", h) for h in a.handle or []]
    if a.mine:
        targets.append(("mine", True))
    if not targets:
        raise InputError("give --channel-id, --handle or --mine (repeatable)")
    if not 1 <= a.limit <= 500:
        raise InputError("--limit must be between 1 and 500")
    rows = []
    for k, v in targets:
        got = client.recent_uploads(limit=a.limit, **{k: v})
        title = (got["channel"].get("snippet") or {}).get("title")
        rows.extend(videos_to_rows(got["videos"], title))
    text = json.dumps(rows, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {len(rows)} videos from {len(targets)} channel(s) to {a.out} "
              f"({client.requests} API requests)", file=sys.stderr)
    else:
        print(text)
    return 0


def cmd_retention(a, client: YouTubeClient) -> int:
    if not _VIDEO.match(a.video_id):
        raise InputError("that does not look like an 11-character video id")
    for d in (a.start, a.end):
        if not _DATE.match(d):
            raise InputError(f"dates must be YYYY-MM-DD, got {d!r}")
    rows = retention_to_rows(client.retention_report(a.video_id, a.start, a.end))
    if not rows:
        raise InputError("YouTube returned no retention rows for that video and date range")
    if a.out:
        write_retention_csv(rows, a.out)
        print(f"wrote {len(rows)} points to {a.out}", file=sys.stderr)
    else:
        print("Video position (%),Absolute audience retention (%)")
        for x, y in rows:
            print(f"{x},{y}")
    return 0


def cmd_login(a, login_fn=login) -> int:
    import webbrowser
    check_save_path(a.save, a.force)       # fail before the user signs in, not after
    creds = Credentials.from_env()
    tok = login_fn(creds, open_url=None if a.no_browser else webbrowser.open, timeout=a.timeout,
                   announce=lambda m: print(m, file=sys.stderr))
    path = save_token(tok, a.save, force=a.force)
    print(f"saved a read-only refresh token to {path} (mode 600). Use it with:\n"
          f"  export YT_OAUTH_TOKEN_FILE={path}", file=sys.stderr)
    return 0


def cmd_comments(a, client: YouTubeClient) -> int:
    if not _VIDEO.match(a.video_id):
        raise InputError("that does not look like an 11-character video id")
    if not 1 <= a.limit <= 5000:
        raise InputError("--limit must be between 1 and 5000")
    title = None
    vids = client.videos([a.video_id])
    if vids:
        title = (vids[0].get("snippet") or {}).get("title")
    rows = comments_to_rows(client.comment_threads(a.video_id, a.limit), title)
    text = json.dumps(rows, indent=1, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {len(rows)} comments to {a.out} ({client.requests} API requests)", file=sys.stderr)
    else:
        print(text)
    return 0


@guarded
def main(argv: Optional[List[str]] = None, client: Optional[YouTubeClient] = None, login_fn=None) -> int:
    p = argparse.ArgumentParser(prog="yt-youtube", description=__doc__.split("\n\n")[0],
                                epilog="Credentials: YOUTUBE_API_KEY, or YT_OAUTH_ACCESS_TOKEN / "
                                       "YT_OAUTH_REFRESH_TOKEN + YT_OAUTH_CLIENT_ID + YT_OAUTH_CLIENT_SECRET")
    p.add_argument("--verbose", action="store_true", help="log each request to stderr (keys redacted)")
    sub = p.add_subparsers(dest="cmd", required=True)
    cv = sub.add_parser("channel-videos", help="recent uploads with views, as yt-swipe input")
    cv.add_argument("--channel-id", action="append")
    cv.add_argument("--handle", action="append")
    cv.add_argument("--mine", action="store_true", help="your own channel (OAuth)")
    cv.add_argument("--limit", type=int, default=50, help="uploads per channel (default 50)")
    cv.add_argument("--out")
    rt = sub.add_parser("retention", help="audience retention curve (OAuth, channel owner)")
    rt.add_argument("video_id")
    rt.add_argument("--start", required=True, help="YYYY-MM-DD")
    rt.add_argument("--end", required=True, help="YYYY-MM-DD")
    rt.add_argument("--out")
    cm = sub.add_parser("comments", help="public top-level comments on a video, as yt-comments input")
    cm.add_argument("video_id")
    cm.add_argument("--limit", type=int, default=500)
    cm.add_argument("--out")
    lg = sub.add_parser("login", help="browser consent for a read-only refresh token (saved to a file)")
    lg.add_argument("--save", required=True, help="token file, outside any git repository")
    lg.add_argument("--force", action="store_true", help="replace an existing token file")
    lg.add_argument("--no-browser", action="store_true", help="only print the URL")
    lg.add_argument("--timeout", type=float, default=300.0, help="seconds to wait for the browser")
    a = p.parse_args(argv)
    if a.cmd == "login":
        return cmd_login(a, login_fn or login)
    c = client or _client(a)
    if a.cmd == "comments":
        return cmd_comments(a, c)
    return cmd_channel_videos(a, c) if a.cmd == "channel-videos" else cmd_retention(a, c)


if __name__ == "__main__":
    raise SystemExit(main())
