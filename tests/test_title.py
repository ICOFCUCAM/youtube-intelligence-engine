import json

import pytest

from conftest import fixture, golden, run_cli
from youtube_intelligence.packaging.title import check

M = "youtube_intelligence.packaging.title"


def kinds(r):
    return [k for k, _ in r["issues"]]


def test_no_number_is_not_penalised_any_more():
    r = check("Why your channel is not growing")
    assert "no-number" not in kinds(r) and r["score"] == 100  # upstream: 90
    assert any("only a true one" in n for n in r["notes"])


def test_a_number_earns_no_credit():
    a = check("I posted once a week for a year")
    b = check("I posted once a week for 1 year")
    assert a["score"] == b["score"]


def test_number_stuffed_income_claim_is_penalised():
    r = check("1 trick 2 make 10000 in 24 hours")
    assert {"claim", "numbers"} <= set(kinds(r))
    assert r["score"] < check("Why your channel is not growing")["score"]   # upstream scored it 100


@pytest.mark.parametrize("t", ["Guaranteed views with this setting", "Make $5,000/month from Shorts",
                               "Grow overnight with one trick", "The setting YouTube doesn't want you to know",
                               "This method never fails", "I made $40k in a week"])
def test_claim_language_flagged(t):
    assert "claim" in kinds(check(t))


@pytest.mark.parametrize("t", ["How I edit a video in 2 hours", "Why I quit posting daily",
                               "My 2025 channel review"])
def test_honest_titles_not_flagged_as_claims(t):
    assert "claim" not in kinds(check(t))


def test_unchanged_checks_still_fire():
    long = "x" * 101
    assert kinds(check(long))[0] == "length"
    assert "shouting" in kinds(check("THIS IS WAY TOO LOUD"))
    assert "vague" in kinds(check("The ultimate guide"))
    assert "front-load" in kinds(check("What is the best camera"))
    r = check("Posting less grew my channel", thumb="POSTING LESS")
    assert "duplicate" in kinds(r)
    assert "thumb-length" in kinds(check("Short title", thumb="one two three four five"))
    assert "thumbnail and title carry different words" in check("Posting less", thumb="3X VIEWS")["good"]


@pytest.mark.parametrize("n,expect", [(40, None), (41, "mobile"), (60, "mobile"), (61, "length")])
def test_length_boundaries(n, expect):
    t = ("Subject " * 20)[:n].rstrip() + "x" * (n - len(("Subject " * 20)[:n].rstrip()))
    assert len(t) == n
    ks = kinds(check(t))
    if expect is None:
        assert "mobile" not in ks and "length" not in ks
    else:
        assert expect in ks


def test_differences_from_upstream_are_only_the_documented_ones():
    up = {r["title"]: r for r in golden("title_titles.json")}
    for t in up:
        new = check(t, "POSTING LESS")
        old_kinds = [k for k, _ in up[t]["issues"] if k not in ("no-number",)]
        assert [k for k in kinds(new) if k not in ("claim", "numbers")] == old_kinds
        assert [g for g in up[t]["good"] if not g.startswith("carries a concrete figure")] == new["good"]


def test_cli_file_mode_and_errors():
    p = run_cli(M, fixture("titles.txt"), "--json")
    assert p.returncode == 0
    rows = json.loads(p.stdout)
    assert [r["score"] for r in rows] == sorted((r["score"] for r in rows), reverse=True)
    assert run_cli(M, "missing.txt").returncode == 1
    assert run_cli(M).returncode == 1
