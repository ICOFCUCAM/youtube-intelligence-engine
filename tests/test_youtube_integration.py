"""Read-only YouTube connector, tested with a fake transport shaped like Google's documented JSON.

These tests prove request construction, read-only enforcement, error handling and the mapping
into the offline tools' inputs. They do not prove compatibility with the live API.
"""
import inspect
import json
import urllib.parse

import pytest

from youtube_intelligence.analytics.retention import analyse, load_csv
from youtube_intelligence.core.errors import InputError
from youtube_intelligence.integrations.youtube import client as client_mod
from youtube_intelligence.integrations.youtube.auth import (READ_ONLY_SCOPES, AuthError, Credentials,
                                                            TokenProvider)
from youtube_intelligence.integrations.youtube.cli import main
from youtube_intelligence.integrations.youtube.client import YouTubeAPIError, YouTubeClient
from youtube_intelligence.integrations.youtube.mappers import (iso_duration, retention_to_rows,
                                                               videos_to_rows, write_retention_csv)
from youtube_intelligence.research.outliers import rank

KEY = "AIzaFAKEKEYFAKEKEYFAKEKEYFAKEKEY12345"


class Fake:
    """Routes by path; records (method, url, headers)."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, method, url, headers, body=None):
        self.calls.append((method, url, dict(headers), body))
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        for path, fn in self.routes.items():
            if u.path.endswith(path):
                status, payload = fn(q, body) if callable(fn) else fn
                return status, json.dumps(payload).encode()
        return 404, b"{}"


def _video(i, views, dur="PT10M"):
    return {"id": f"vid{i:08d}", "snippet": {"title": f"Video {i}", "channelTitle": "Chan",
                                              "publishedAt": "2026-01-01T00:00:00Z"},
            "contentDetails": {"duration": dur}, "statistics": {"viewCount": str(views)}}


def _channel_routes(n_videos=120, views=lambda i: 1000 + i):
    ids = [f"vid{i:08d}" for i in range(n_videos)]

    def playlist(q, _):
        start = int(q.get("pageToken") or 0)
        page = ids[start:start + 50]
        d = {"items": [{"contentDetails": {"videoId": v}} for v in page]}
        if start + 50 < len(ids):
            d["nextPageToken"] = str(start + 50)
        return 200, d

    def videos(q, _):
        want = q["id"].split(",")
        assert len(want) <= 50
        return 200, {"items": [_video(int(v[3:]), views(int(v[3:]))) for v in want]}

    return {
        "/channels": (200, {"items": [{"id": "UC123", "snippet": {"title": "Chan"},
                                       "contentDetails": {"relatedPlaylists": {"uploads": "UU123"}}}]}),
        "/playlistItems": playlist,
        "/videos": videos,
    }


# --- read-only by construction -------------------------------------------------------------------
def test_client_has_no_write_methods():
    # Exact allowlist: adding ANY public method fails here until it is reviewed as read-only.
    public = {n for n, _ in inspect.getmembers(YouTubeClient, inspect.isfunction) if not n.startswith("_")}
    assert public == {"channel", "playlist_video_ids", "videos", "recent_uploads", "retention_report", "comment_threads"}
    src = inspect.getsource(client_mod)
    assert '"POST"' not in src and '"PUT"' not in src and '"DELETE"' not in src


def test_every_api_request_is_get_to_an_allowlisted_host():
    fake = Fake(_channel_routes(120))
    c = YouTubeClient(Credentials(api_key=KEY), transport=fake)
    c.recent_uploads(limit=120, handle="chan")
    assert fake.calls and all(m == "GET" for m, *_ in fake.calls)
    assert all(u.startswith(client_mod.DATA_API) for _, u, *_ in fake.calls)


def test_refuses_non_allowlisted_base():
    c = YouTubeClient(Credentials(api_key=KEY), transport=Fake({}))
    with pytest.raises(InputError, match="non-allowlisted"):
        c._get("https://evil.example/", "x", {})


def test_only_read_only_scopes_declared():
    assert all(s.endswith(".readonly") for s in READ_ONLY_SCOPES)


# --- requests ---------------------------------------------------------------------------------------
def test_pagination_and_batching():
    fake = Fake(_channel_routes(120))
    got = YouTubeClient(Credentials(api_key=KEY), transport=fake).recent_uploads(limit=120, channel_id="UC123")
    assert len(got["videos"]) == 120
    paths = [urllib.parse.urlparse(u).path.rsplit("/", 1)[1] for _, u, *_ in fake.calls]
    assert paths == ["channels", "playlistItems", "playlistItems", "playlistItems", "videos", "videos", "videos"]


def test_limit_stops_pagination_early():
    fake = Fake(_channel_routes(500))
    got = YouTubeClient(Credentials(api_key=KEY), transport=fake).recent_uploads(limit=30, handle="@chan")
    assert len(got["videos"]) == 30
    assert sum("playlistItems" in u for _, u, *_ in fake.calls) == 1


def test_handle_is_normalised_and_key_sent_as_query():
    fake = Fake(_channel_routes(1))
    YouTubeClient(Credentials(api_key=KEY), transport=fake).channel(handle="chan")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(fake.calls[0][1]).query))
    assert q["forHandle"] == "@chan" and q["key"] == KEY
    assert "Authorization" not in fake.calls[0][2]


def test_channel_argument_rules():
    c = YouTubeClient(Credentials(api_key=KEY), transport=Fake({}))
    with pytest.raises(InputError, match="exactly one"):
        c.channel(channel_id="a", handle="b")
    with pytest.raises(InputError, match="exactly one"):
        c.channel()


def test_channel_not_found():
    c = YouTubeClient(Credentials(api_key=KEY), transport=Fake({"/channels": (200, {"items": []})}))
    with pytest.raises(InputError, match="channel not found"):
        c.channel(handle="nobody")


def test_no_credentials_is_a_clean_error():
    with pytest.raises(InputError, match="no credentials"):
        YouTubeClient(Credentials(), transport=Fake({})).channel(handle="x")


# --- errors and retries -----------------------------------------------------------------------------
def _err(status, reason, message="nope"):
    return status, {"error": {"code": status, "message": message, "errors": [{"reason": reason}]}}


def test_quota_exceeded_is_not_retried():
    fake = Fake({"/channels": _err(403, "quotaExceeded")})
    c = YouTubeClient(Credentials(api_key=KEY), transport=fake, sleep=lambda s: None)
    with pytest.raises(YouTubeAPIError, match="quota") as e:
        c.channel(handle="x")
    assert e.value.status == 403 and len(fake.calls) == 1


def test_transient_errors_retry_then_succeed():
    seq = [_err(503, "backendError"), _err(429, "rateLimitExceeded"),
           (200, {"items": [{"id": "UC1", "snippet": {"title": "T"}}]})]
    slept = []
    fake = Fake({"/channels": lambda q, b: seq.pop(0)})
    c = YouTubeClient(Credentials(api_key=KEY), transport=fake, sleep=slept.append)
    assert c.channel(channel_id="UC1")["id"] == "UC1"
    assert slept == [2, 4] and len(fake.calls) == 3


def test_transient_errors_give_up_after_max_attempts():
    fake = Fake({"/channels": _err(500, "backendError")})
    with pytest.raises(YouTubeAPIError):
        YouTubeClient(Credentials(api_key=KEY), transport=fake, sleep=lambda s: None).channel(channel_id="x")
    assert len(fake.calls) == client_mod.MAX_ATTEMPTS


def test_key_never_appears_in_errors_or_logs():
    logs = []
    fake = Fake({"/channels": _err(400, "keyInvalid", f"API key {KEY} not valid")})
    c = YouTubeClient(Credentials(api_key=KEY), transport=fake, log=logs.append)
    with pytest.raises(YouTubeAPIError) as e:
        c.channel(handle="x")
    assert KEY not in str(e.value) and logs and all(KEY not in m for m in logs)
    assert KEY not in repr(Credentials(api_key=KEY))


# --- OAuth ------------------------------------------------------------------------------------------
def _token_route(scope=" ".join(READ_ONLY_SCOPES), status=200):
    def fn(q, body):
        form = dict(urllib.parse.parse_qsl(body.decode()))
        assert form["grant_type"] == "refresh_token"
        if status != 200:
            return status, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}
        return 200, {"access_token": "ya29.fake-access", "expires_in": 3600, "scope": scope}
    return fn


OAUTH = Credentials(refresh_token="1//fake-refresh", client_id="cid", client_secret="csecret")


def test_refresh_token_flow_and_caching():
    now = [1000.0]
    fake = Fake({"/token": _token_route()})
    tp = TokenProvider(OAUTH, fake, clock=lambda: now[0])
    assert tp() == "ya29.fake-access" and tp() == "ya29.fake-access"
    assert len(fake.calls) == 1 and fake.calls[0][0] == "POST"
    now[0] += 3600
    tp()
    assert len(fake.calls) == 2


def test_refuses_token_with_write_scope():
    fake = Fake({"/token": _token_route(scope=READ_ONLY_SCOPES[0] + " https://www.googleapis.com/auth/youtube.upload")})
    with pytest.raises(AuthError, match="more than read-only"):
        TokenProvider(OAUTH, fake)()


def test_refresh_failure_redacts_secrets():
    fake = Fake({"/token": _token_route(status=400)})
    with pytest.raises(AuthError, match="expired or revoked") as e:
        TokenProvider(OAUTH, fake)()
    assert "csecret" not in str(e.value) and "1//fake-refresh" not in str(e.value)


def test_oauth_required_for_owner_data():
    with pytest.raises(AuthError, match="OAuth is required"):
        YouTubeClient(Credentials(api_key=KEY), transport=Fake({})).retention_report("abcdefghijk", "2026-01-01", "2026-02-01")


def test_credentials_from_env():
    c = Credentials.from_env({"YOUTUBE_API_KEY": " k ", "YT_OAUTH_ACCESS_TOKEN": ""})
    assert c.api_key == "k" and c.access_token is None and not c.has_oauth


# --- mappers -> offline tools -----------------------------------------------------------------------
@pytest.mark.parametrize("s,v", [("PT10M", 600), ("PT1H2M3S", 3723), ("PT45S", 45), ("P1DT1S", 86401),
                                 ("P0D", 0), ("PT0.5S", 0.5), ("", None), ("10:00", None), ("PT", None)])
def test_iso_duration(s, v):
    assert iso_duration(s) == v


def test_videos_feed_yt_swipe_unchanged():
    fake = Fake(_channel_routes(8, views=lambda i: 50_000 if i == 3 else 10_000))
    c = YouTubeClient(Credentials(api_key=KEY), transport=fake)
    got = c.recent_uploads(limit=8, handle="chan")
    rows = videos_to_rows(got["videos"], "Chan")
    assert rows[0]["url"] == "https://www.youtube.com/watch?v=vid00000000" and rows[0]["duration"] == 600
    r = rank(rows, lo=2.0)
    assert [x["title"] for x in r["outliers"]] == ["Video 3"] and r["outliers"][0]["multiple"] == 5.0


def test_hidden_view_count_maps_to_none():
    v = _video(1, 0)
    del v["statistics"]["viewCount"]
    assert videos_to_rows([v])[0]["views"] is None


REPORT = {"kind": "youtubeAnalytics#resultTable",
          "columnHeaders": [{"name": "elapsedVideoTimeRatio", "columnType": "DIMENSION"},
                            {"name": "audienceWatchRatio", "columnType": "METRIC"}],
          "rows": [[round(i / 100, 2), round(1.0 - i * 0.004 - (0.15 if i >= 3 else 0), 4)] for i in range(1, 101)]}


def test_retention_report_feeds_yt_retention(tmp_path):
    fake = Fake({"/reports": (200, REPORT)})
    c = YouTubeClient(Credentials(access_token="ya29.x"), transport=fake)
    rep = c.retention_report("abcdefghijk", "2026-01-01", "2026-02-01")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(fake.calls[0][1]).query))
    assert q["filters"] == "video==abcdefghijk" and q["ids"] == "channel==MINE"
    assert fake.calls[0][2]["Authorization"] == "Bearer ya29.x" and "key" not in q
    rows = retention_to_rows(rep)
    assert rows[0] == (1.0, 99.6) and rows[-1][0] == 100.0
    p = tmp_path / "r.csv"
    write_retention_csv(rows, str(p))
    loaded, hint = load_csv(str(p))
    assert hint == "percent" and len(loaded) == 100
    r = analyse(loaded, 600, hint=hint)
    assert r["cliffs"][0]["at_seconds"] == 12.0          # the 15-point drop between 2% and 3%


def test_retention_report_missing_columns():
    with pytest.raises(InputError, match="lacks"):
        retention_to_rows({"columnHeaders": [{"name": "views"}], "rows": [[1]]})


# --- CLI --------------------------------------------------------------------------------------------
def test_cli_channel_videos_writes_swipe_input(tmp_path, capsys):
    out = tmp_path / "collected.json"
    c = YouTubeClient(Credentials(api_key=KEY), transport=Fake(_channel_routes(5)))
    assert main(["channel-videos", "--handle", "@a", "--limit", "5", "--out", str(out)], client=c) == 0
    assert len(json.loads(out.read_text())) == 5
    assert "wrote 5 videos" in capsys.readouterr().err


@pytest.mark.parametrize("argv,msg", [
    (["channel-videos"], "give --channel-id"),
    (["channel-videos", "--handle", "a", "--limit", "0"], "between 1 and 500"),
    (["retention", "short", "--start", "2026-01-01", "--end", "2026-02-01"], "11-character"),
    (["retention", "abcdefghijk", "--start", "Jan 1", "--end", "2026-02-01"], "YYYY-MM-DD"),
])
def test_cli_validation(argv, msg, capsys):
    c = YouTubeClient(Credentials(api_key=KEY), transport=Fake({}))
    assert main(argv, client=c) == 1
    assert msg in capsys.readouterr().err


def test_cli_retention_empty_report_is_an_error(capsys):
    c = YouTubeClient(Credentials(access_token="t"), transport=Fake({"/reports": (200, dict(REPORT, rows=[]))}))
    assert main(["retention", "abcdefghijk", "--start", "2026-01-01", "--end", "2026-02-01"], client=c) == 1
    assert "no retention rows" in capsys.readouterr().err



def _thread(i, text, author="Viewer", likes=0, author_id=None):
    return {"snippet": {"videoId": "abcdefghijk", "totalReplyCount": 1, "topLevelComment": {"snippet": {
        "videoId": "abcdefghijk", "authorDisplayName": author, "authorChannelId": {"value": author_id or f"UC{i}"},
        "textOriginal": text, "textDisplay": "<b>html</b>", "likeCount": likes, "publishedAt": "2026-11-01T00:00:00Z"}}}}


def test_comment_threads_paginate_and_map(tmp_path, capsys):
    pages = {None: ([_thread(i, f"question {i}?") for i in range(100)], "p2"),
             "p2": ([_thread(100 + i, f"q {i}?") for i in range(30)], None)}

    def threads(q, _):
        items, nxt = pages[q.get("pageToken")]
        assert q["textFormat"] == "plainText" and q["part"] == "snippet"
        d = {"items": items}
        if nxt:
            d["nextPageToken"] = nxt
        return 200, d
    fake = Fake({"/commentThreads": threads, "/videos": (200, {"items": [_video(1, 10)]})})
    c = YouTubeClient(Credentials(api_key=KEY), transport=fake)
    out = tmp_path / "c.json"
    assert main(["comments", "abcdefghijk", "--limit", "120", "--out", str(out)], client=c) == 0
    rows = json.loads(out.read_text())
    assert len(rows) == 120 and rows[0]["text"] == "question 0?" and rows[0]["video_title"] == "Video 1"
    assert rows[0]["author_id"] == "UC0" and rows[0]["replies"] == 1          # plain text, not textDisplay HTML
    assert all(m == "GET" for m, *_ in fake.calls)
    assert main(["comments", "short"], client=c) == 1
