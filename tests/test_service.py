"""HTTP service: routing/validation via app.handle, and the real server over loopback."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from conftest import fixture
from youtube_intelligence.analytics.retention import analyse as ret_analyse, load_csv
from youtube_intelligence.core.errors import InputError
from youtube_intelligence.core.transcript import load_cues, load_words
from youtube_intelligence.creative.hookscore import evaluate
from youtube_intelligence.editing import chapters, deadair
from youtube_intelligence.service import app
from youtube_intelligence.service.server import MAX_BODY, make_server
from youtube_intelligence.shorts.candidates import find

SRT = open(fixture("sample.srt")).read()
T = {"format": "srt", "content": SRT}


def ok(path, body):
    status, payload = app.handle("POST", path, body)
    assert status == 200, payload
    return payload


# --- same answers as the library -------------------------------------------------------------------
def test_edl_matches_library():
    assert ok("/v1/edl", {"transcript": T}) == deadair.analyse(load_cues(fixture("sample.srt")))


def test_edl_with_word_timings_and_hold_review():
    content = open("datasets/synthetic-words-v1/essay-whisper.json").read()
    got = ok("/v1/edl", {"transcript": {"format": "json", "content": content}, "hold_review": True})
    p = "datasets/synthetic-words-v1/essay-whisper.json"
    assert got == deadair.analyse(load_cues(p), words=load_words(p), hold_review=True)
    assert got["word_timings"] == "exact"
    assert ok("/v1/edl", {"transcript": {"format": "json", "content": content}, "words": "off"})["word_timings"] == "none"


def test_cues_input_equals_content_input():
    cues = [{"start": c.start, "end": c.end, "text": c.text} for c in load_cues(fixture("sample.srt"))]
    assert ok("/v1/chapters", {"transcript": {"cues": cues}}) == ok("/v1/chapters", {"transcript": T})


def test_chapters_shorts_hooks_titles():
    cues = load_cues(fixture("sample.srt"))
    assert ok("/v1/chapters", {"transcript": T, "target": 7}) == chapters.build(cues, 7)
    assert ok("/v1/shorts", {"transcript": T, "top": 2})["candidates"] == find(cues, 20, 55, 2)
    h = ok("/v1/hooks/score", {"hooks": ["You are losing 40% of viewers in 8 seconds"]})
    assert h["results"][0]["verdict"] == evaluate(["You are losing 40% of viewers in 8 seconds"])[0]["verdict"]
    assert "heuristic" in h["disclaimer"]
    t = ok("/v1/titles/check", {"titles": ["Make $5,000/month overnight", "Why your channel is not growing"]})
    assert [r["title"] for r in t["results"]] == ["Why your channel is not growing", "Make $5,000/month overnight"]


def test_retention_csv_rows_and_transcript():
    csv_text = open(fixture("retention_seconds.csv")).read()
    rows, hint = load_csv(fixture("retention_seconds.csv"))
    a = ok("/v1/retention", {"csv": csv_text, "views": 300})
    assert a == ret_analyse(rows, hint=hint, views=300) and a["warnings"]
    b = ok("/v1/retention", {"rows": [list(r) for r in rows], "axis": "seconds"})
    assert b["cliffs"] == a["cliffs"]
    c = ok("/v1/retention", {"csv": csv_text, "transcript": T})
    assert c["said"]


def test_outliers():
    vids = json.load(open(fixture("collected.json")))
    r = ok("/v1/outliers", {"videos": vids, "min": 2.0})
    assert r["outliers"][0]["multiple"] == 7.88
    assert r["skipped_thin_channels"] == [{"channel": "Gamma Tiny", "videos": 3}]


def test_health():
    s, p = app.handle("GET", "/v1/health")
    assert s == 200 and p["status"] == "ok" and p["writes_to_youtube"] is False


# --- validation --------------------------------------------------------------------------------------
@pytest.mark.parametrize("path,body,msg", [
    ("/v1/edl", [], "must be a JSON object"),
    ("/v1/edl", {}, "'transcript' must be an object"),
    ("/v1/edl", {"transcript": {"format": "doc", "content": ""}}, "must be one of"),
    ("/v1/edl", {"transcript": {"format": "srt", "content": 5}}, "must be a string"),
    ("/v1/edl", {"transcript": {"format": "srt", "content": ""}}, "no cues"),
    ("/v1/edl", {"transcript": {"format": "json", "content": "{bad"}}, "not valid JSON"),
    ("/v1/edl", {"transcript": T, "floor": "1"}, "'floor' must be a number"),
    ("/v1/edl", {"transcript": T, "floor": -1}, "between"),
    ("/v1/edl", {"transcript": T, "hold_review": "yes"}, "true or false"),
    ("/v1/edl", {"transcript": {"cues": [{"start": 0}]}}, "numeric start/end"),
    ("/v1/chapters", {"transcript": T, "target": 2.5}, "whole number"),
    ("/v1/hooks/score", {"hooks": []}, "non-empty list"),
    ("/v1/hooks/score", {"hooks": ["x"] * 501}, "more than 500"),
    ("/v1/titles/check", {"titles": ["a"], "thumb": 3}, "'thumb' must be a string"),
    ("/v1/retention", {}, "send 'csv'"),
    ("/v1/retention", {"rows": [[0, 1]] * 3}, "at least 8"),
    ("/v1/retention", {"rows": [[0, "x"]]}, "row 0"),
    ("/v1/retention", {"rows": [[0, float("nan")]]}, "row 0"),
    ("/v1/outliers", {"videos": "x"}, "'videos' must be a list"),
    ("/v1/shorts", {"transcript": T, "min": 60, "max": 20}, "0 < --min <= --max"),
])
def test_validation_errors(path, body, msg):
    s, p = app.handle("POST", path, body)
    assert s == 400 and p["error"]["code"] == "invalid_input" and msg in p["error"]["message"]


def test_routing_errors():
    assert app.handle("GET", "/v1/nope")[0] == 404
    assert app.handle("GET", "/v1/edl")[0] == 405
    assert app.handle("POST", "/v1/health", {})[0] == 405
    assert app.handle("POST", "/v1/edl/", {"transcript": T})[0] == 200    # trailing slash tolerated


def test_internal_errors_do_not_leak(monkeypatch):
    def boom(body):
        raise RuntimeError("secret internal detail /etc/passwd")
    monkeypatch.setitem(app.POST, "/v1/edl", boom)
    logged = []
    s, p = app.handle("POST", "/v1/edl", {}, log=logged.append)
    assert s == 500 and "secret" not in json.dumps(p) and "secret internal detail" in logged[0]


def test_no_endpoint_accepts_a_file_path():
    s, p = app.handle("POST", "/v1/edl", {"transcript": {"path": "/etc/passwd"}})
    assert s == 400


# --- the real server ---------------------------------------------------------------------------------
NOPROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@pytest.fixture
def server():
    started = []

    def start(token=None):
        srv = make_server("127.0.0.1", 0, token, quiet=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        started.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}"
    yield start
    for s in started:
        s.shutdown()
        s.server_close()


def call(base, path, body=None, method=None, headers=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Content-Type": "application/json"} if data is not None else {}
    h.update(headers or {})
    req = urllib.request.Request(base + path, data=data, headers=h, method=method)
    try:
        with NOPROXY.open(req, timeout=10) as r:
            return r.status, dict(r.headers), json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), json.loads(e.read())


def test_server_roundtrip_and_headers(server):
    base = server()
    s, h, p = call(base, "/v1/titles/check", {"titles": ["Why your channel is not growing"]})
    assert s == 200 and p["results"][0]["score"] == 100
    assert h["Content-Type"].startswith("application/json") and h["Cache-Control"] == "no-store"
    assert h["X-Content-Type-Options"] == "nosniff" and "Access-Control-Allow-Origin" not in h
    assert call(base, "/v1/health")[2]["status"] == "ok"


def test_server_rejects_bad_requests(server):
    base = server()
    assert call(base, "/v1/edl", raw=b"{bad")[0] == 400
    assert call(base, "/v1/edl", raw=b"{}", headers={"Content-Type": "text/plain"})[0] == 415
    assert call(base, "/v1/edl", {"transcript": T}, method="DELETE")[0] == 405
    # declare an oversized body but send a small one: the server must decide from the header alone
    import http.client
    port = int(base.rsplit(":", 1)[1])
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.putrequest("POST", "/v1/edl")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", str(MAX_BODY + 1))
    conn.endheaders()
    conn.send(b"{}")
    r = conn.getresponse()
    assert r.status == 413 and json.loads(r.read())["error"]["code"] == "payload_too_large"
    assert r.getheader("Connection") == "close"
    conn.close()
    # missing Content-Length
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.putrequest("POST", "/v1/edl")
    conn.putheader("Content-Type", "application/json")
    conn.endheaders()
    r = conn.getresponse()
    assert r.status == 411
    conn.close()


def test_server_token(server):
    base = server(token="t" * 32)
    assert call(base, "/v1/titles/check", {"titles": ["a b c"]})[0] == 401
    assert call(base, "/v1/titles/check", {"titles": ["a b c"]}, headers={"Authorization": "Bearer wrong"})[0] == 401
    assert call(base, "/v1/titles/check", {"titles": ["a b c"]}, headers={"Authorization": "Bearer " + "t" * 32})[0] == 200
    assert call(base, "/v1/health")[0] == 200            # health stays open: it carries no data


def test_refuses_public_bind_without_token():
    with pytest.raises(InputError, match="without YIE_API_TOKEN"):
        make_server("0.0.0.0", 0)


def test_short_token_refused(monkeypatch, capsys):
    from youtube_intelligence.service.server import main
    monkeypatch.setenv("YIE_API_TOKEN", "short")
    assert main(["--port", "0"]) == 1 and "at least 16" in capsys.readouterr().err
