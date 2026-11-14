import json

import pytest

from conftest import fixture, golden, run_cli, run_skill
from youtube_intelligence.research.outliers import load, parse_views, rank

M = "youtube_intelligence.research.outliers"


def test_matches_upstream():
    r = rank(load(fixture("collected.json")))
    up = golden("swipe.json")
    assert r["outliers"] == up["outliers"]
    assert [list(t) for t in r["skipped_thin_channels"]] == up["skipped_thin_channels"]


def test_multiple_is_against_own_channel_median():
    rows = [{"channel": "A", "title": f"t{i}", "views": v} for i, v in enumerate([10, 10, 10, 10, 50])]
    out = rank(rows, lo=0)["outliers"]
    assert out[0]["views"] == 50 and out[0]["median"] == 10 and out[0]["multiple"] == 5.0


@pytest.mark.parametrize("v,n", [(412000, 412000), ("412,000", 412000), ("412K", 412000),
                                 ("1.2M views", 1_200_000), (None, 0), ("", 0), (0, 0)])
def test_parse_views(v, n):
    assert parse_views(v) == n


@pytest.mark.parametrize("v", ["lots", "-5", -5, True, "12 apples"])
def test_unreadable_views(v):
    assert parse_views(v) is None


def test_unreadable_rows_skipped_and_counted():
    rows = [{"channel": "A", "views": 10}] * 4 + [{"channel": "A", "views": "many"}, "not a dict"]
    r = rank(rows, lo=0)
    assert r["skipped_unreadable"] == 2 and len(r["outliers"]) == 4


def test_thin_channel_skipped():
    r = rank([{"channel": "B", "views": 1}] * 3)
    assert r["outliers"] == [] and r["skipped_thin_channels"] == [("B", 3)]


@pytest.mark.parametrize("body,msg", [("{bad", "not valid JSON"), ('"x"', "expected a list")])
def test_bad_json(write, body, msg):
    p = run_cli(M, write("c.json", body))
    assert p.returncode == 1 and msg in p.stderr


def test_dict_with_videos_key(write):
    p = write("c.json", json.dumps({"videos": [{"channel": "A", "views": 1}] * 4}))
    assert len(rank(load(p), 0)["outliers"]) == 4


def test_skill_entry_point():
    p = run_skill("yt-viral/swipe.py", fixture("collected.json"), "--min", "2.0")
    assert p.returncode == 0 and "7.88x" in p.stdout and "Gamma Tiny (3)" in p.stdout
