"""yt-check: FAIL only for objective YouTube rule breaks; WARN for judgement; honest verdicts."""
import json
import os

import pytest

from conftest import ROOT, fixture, run_cli
from youtube_intelligence.core.errors import InputError
from youtube_intelligence.core.transcript import Cue, load_cues
from youtube_intelligence.preflight.check import check_chapters, parse_description_chapters, run

CUES = load_cues(fixture("sample.srt"))       # 90 s
DESC = open(os.path.join(ROOT, "examples", "check", "description.txt")).read()
M = "youtube_intelligence.preflight.check"


def statuses(r, area=None):
    return [(c["status"], c["title"]) for c in r["checks"] if area is None or c["area"] == area]


def fails(r):
    return [c["title"] for c in r["checks"] if c["status"] == "fail"]


def test_sample_is_ready_with_fixes_and_sorted():
    r = run("Why your first 15 seconds lose viewers", "FIX THIS", DESC, ["youtube hook"], CUES)
    assert r["verdict"] == "ready_with_fixes" and r["counts"]["fail"] == 0
    order = [c["status"] for c in r["checks"]]
    rank = {"fail": 0, "warn": 1, "pass": 2, "info": 3}
    assert order == sorted(order, key=rank.get)


def test_clean_upload_is_ready():
    cues = [Cue(0, 4, "Your thumbnails fail at feed size, and here is the fix you can check in one second."),
            Cue(4.1, 9, "Shrink the thumbnail to a postage stamp before you choose it."),
            Cue(9.1, 14, "If the words vanish, the thumbnail fails, whatever the title says.")]
    desc = "Your thumbnails fail at feed size: the one-second fix.\nShrink before you choose.\n"
    r = run("Your thumbnails fail at feed size", "SHRINK IT", desc, ["thumbnail feed size"], cues)
    assert fails(r) == [] and r["verdict"] in ("ready", "ready_with_fixes")
    assert ("pass", "The opening echoes the title") in statuses(r, "opening")


@pytest.mark.parametrize("title,desc,expect", [
    ("x" * 101, "ok", "Title is 101 characters"),
    ("Fix <this> now", "ok", "Title contains < or >"),
    ("Fine title here", "a" * 5001, "Description is 5001 bytes"),
    ("Fine title here", "\U0001F600" * 1251, "Description is 5004 bytes"),        # 1,251 characters, 5,004 bytes
    ("Fine title here", "Use <b>bold</b>", "Description contains < or >"),
])
def test_objective_fails(title, desc, expect):
    r = run(title, None, desc)
    assert expect in fails(r) and r["verdict"] == "not_yet"


def test_long_title_not_double_reported_as_warn():
    r = run("x" * 101, None, "ok")
    assert not any("desktop search cuts" in c["detail"] for c in r["checks"] if c["status"] == "warn")


@pytest.mark.parametrize("lines,seconds,problem", [
    (["0:00 a", "0:20 b"], None, "at least 3"),
    (["0:05 a", "0:30 b", "1:00 c"], None, "must be 0:00"),
    (["0:00 a", "0:40 b", "0:30 c"], None, "increasing order"),
    (["0:00 a", "0:05 b", "0:40 c"], None, "shorter than 10 seconds"),
    (["0:00 a", "0:30 b", "1:20 c"], 85.0, "shorter than 10 seconds"),
    (["0:00 a", "0:30 b", "2:00 c"], 90.0, "after the end of the video"),
])
def test_chapter_rules(lines, seconds, problem):
    ch = parse_description_chapters("\n".join(lines))
    assert any(problem in p for p in check_chapters(ch, seconds))


def test_chapter_parsing_formats():
    ch = parse_description_chapters("Intro text\n00:00 - Start\n(1:05) Middle\n1:02:03 | Late\nnot 9:99x")
    assert [(c["start"], c["title"]) for c in ch] == [(0, "Start"), (65, "Middle"), (3723, "Late")]
    assert check_chapters(ch, 4000) == []


def test_broken_chapters_fail_the_upload():
    r = run("Fine title here", None, "0:00 a\n0:05 b\n", cues=CUES)
    assert "Chapters won't show on YouTube" in fails(r)


def test_pitch_in_first_30_seconds_warns():
    cues = [Cue(0, 5, "Hey guys, welcome back to the channel."), Cue(5.2, 9, "Today, hooks.")]
    r = run("Hooks that work", None, "Hooks that work.", cues=cues)
    assert ("warn", '"welcome back" in the first 30 seconds') in statuses(r, "opening")


def test_opening_that_ignores_the_title_warns():
    cues = [Cue(0, 5, "So I bought a new camera last week and it is great.")]
    r = run("Retention graphs explained", None, "Retention graphs explained.", cues=cues)
    assert ("warn", "The first 15 seconds don't echo the title") in statuses(r, "opening")


def test_search_queries_and_missing_description():
    r = run("How to read retention", None, "Read your retention graph.\nSecond line.", ["retention graph", "watch time"])
    s = statuses(r, "search")
    assert ("pass", '"retention graph" is covered by the title and first two lines') in s
    assert ('warn', '"watch time": not in the title or first two lines') in s
    r = run("How to read retention")
    assert ("warn", "No description given") in statuses(r, "description")
    assert ("info", "No transcript given") in statuses(r, "opening")


def test_suggests_chapters_when_none_given():
    r = run("Hooks, thumbnails and retention", None, "A video about hooks.", cues=CUES)
    assert r["suggested_chapters"] and r["suggested_chapters"][0]["label"] == "0:00"


def test_title_required():
    with pytest.raises(InputError):
        run("   ")


def test_cli_exit_codes(tmp_path):
    ok = run_cli(M, "--title", "Why your first 15 seconds lose viewers", "--transcript", fixture("sample.srt"),
                 "--description", os.path.join(ROOT, "examples", "check", "description.txt"))
    assert ok.returncode == 0 and "READY" in ok.stdout
    bad = tmp_path / "d.txt"
    bad.write_text("0:00 a\n0:05 b\n")
    no = run_cli(M, "--title", "Fine title", "--description", str(bad))
    assert no.returncode == 1 and "NOT YET" in no.stdout          # can block an automated pipeline
    j = json.loads(run_cli(M, "--title", "Fine title", "--json").stdout)
    assert j["schema"] == "youtube-intelligence/preflight@1"
    assert run_cli(M, "--title", "x", "--description", "missing.txt").returncode == 1


def test_http_endpoint_and_openapi():
    from youtube_intelligence.service import app
    srt = open(fixture("sample.srt")).read()
    s, r = app.handle("POST", "/v1/check", {"title": "Why your first 15 seconds lose viewers",
                                            "transcript": {"format": "srt", "content": srt},
                                            "description": DESC, "queries": ["youtube hook"]})
    assert s == 200 and r["verdict"] == "ready_with_fixes"
    assert run("Why your first 15 seconds lose viewers", None, DESC, ["youtube hook"], CUES) == r
    assert app.handle("POST", "/v1/check", {"title": 5})[0] == 400
    assert app.handle("POST", "/v1/check", {"title": "x", "queries": ["a"] * 21})[0] == 400
    assert "/v1/check" in app.handle("GET", "/v1/openapi.json")[1]["paths"]
