"""yt-claims: the fact guard."""
import json
import os

import pytest

from conftest import ROOT, run_cli
from youtube_intelligence.core.errors import InputError
from youtube_intelligence.creative.claims import check, evidence_numbers, normalise, parse_voice

EX = os.path.join(ROOT, "examples", "claims")
VOICE = open(os.path.join(EX, "voice.md")).read()
EVID = [l for l in open(os.path.join(EX, "evidence.md")).read().splitlines() if l.strip()]
M = "youtube_intelligence.creative.claims"


def kinds(r, status):
    return sorted((f["kind"], f["excerpt"]) for f in r["findings"] if f["status"] == status)


@pytest.mark.parametrize("raw,n", [("200k", "200000"), ("200,000", "200000"), ("$5,000", "5000"), ("40 %", "40"),
                                    ("3x", "3"), ("#1", "1"), ("1.5M", "1500000"), ("12.5%", "12.5")])
def test_normalise(raw, n):
    assert normalise(raw) == n


def test_evidence_ignores_sources_and_dates():
    nums = evidence_numbers(["412,000 views on the March video (YouTube Studio, 2026-03-01)",
                             "Up 12% [Studio export 15/04/2026]", "Sold 30 copies on 2026-04-15"])
    assert nums == {"412000", "12", "30"}


def test_parse_voice_sections():
    v = parse_voice(VOICE)
    assert v == {"never": ["dive in", "game-changer", "unlock"], "will_not_claim": ["paid for ads", "overnight results"]}
    tpl = parse_voice(open(os.path.join(ROOT, "templates", "voice.md")).read())
    assert "game-changer" in tpl["never"] and tpl["will_not_claim"] == []       # template prose is not a rule


def test_demo_script():
    r = check(open(os.path.join(EX, "script.md")).read(), VOICE, EVID)
    assert not r["clean"]
    assert kinds(r, "blocked") == [("banned_word", "dive in"), ("will_not_claim", "paid for ads")]
    assert kinds(r, "backed") == [("figure", "12%"), ("figure", "412,000 views")]
    ns = kinds(r, "needs_source")
    assert ("figure", "80%") in ns and ("citation", "Studies show") in ns
    assert ("figure", "from 400 to 200k") in ns and ("figure", "tripled") in ns
    assert kinds(r, "check") == [("absolute", "everyone"), ("absolute", "guaranteed")]
    assert sum(1 for f in r["findings"] if f["line"] == 10) == 1        # "We tripled" reported once


@pytest.mark.parametrize("text,evidence,expect", [
    ("We hit 10,000 subscribers.", ["10,000 subscribers (Studio)"], "backed"),
    ("We hit 10k subscribers.", ["10,000 subscribers (Studio)"], "backed"),
    ("We hit 10,000 subscribers.", [], "needs_source"),
    ("It went from 1,000 to 5,000 views.", ["1,000 views before, 5,000 after (Studio)"], "backed"),
    ("It went from 1,000 to 9,000 views.", ["1,000 views before, 5,000 after (Studio)"], "needs_source"),
    ("We grew in 15 days.", ["412,000 views (Studio, 2026-04-15)"], "needs_source"),
])
def test_figures_and_ranges(text, evidence, expect):
    statuses = {f["status"] for f in check(text, evidence=evidence)["findings"] if f["kind"] == "figure"}
    assert statuses == {expect}


@pytest.mark.parametrize("text,kind", [
    ("Research shows hooks matter.", "citation"), ("Experts agree on this.", "citation"),
    ("I made a fortune last year.", "result"), ("We doubled our reach.", "figure"),
    ("Make $500/month from this.", "figure"), ("We are the #1 channel.", "figure"),
])
def test_claim_kinds(text, kind):
    assert kind in {f["kind"] for f in check(text)["findings"] if f["status"] == "needs_source"}


def test_word_boundaries_and_clean_text():
    v = "## Words I never use\n- unlock\n"
    assert check("Unlocking is not the word.", v)["counts"]["blocked"] == 0       # not a whole-word match
    assert check("Let me unlock this.", v)["counts"]["blocked"] == 1
    r = check("Thumbnails work at feed size or they do not work at all.")
    assert r["clean"] and r["findings"] == []
    with pytest.raises(InputError):
        check("   ")


def test_cli_and_http():
    p = run_cli(M, os.path.join(EX, "script.md"), "--voice", os.path.join(EX, "voice.md"),
                "--evidence", os.path.join(EX, "evidence.md"))
    assert p.returncode == 1 and "NOT CLEAN: 2 blocked" in p.stdout
    ok = run_cli(M, "--text", "Short, honest sentence.", "--json")
    assert ok.returncode == 0 and json.loads(ok.stdout)["clean"] is True
    assert run_cli(M, "missing.md").returncode == 1
    from youtube_intelligence.service import app
    s, r = app.handle("POST", "/v1/claims", {"text": open(os.path.join(EX, "script.md")).read(),
                                             "voice": VOICE, "evidence": EVID})
    assert s == 200 and r["counts"]["blocked"] == 2
    assert app.handle("POST", "/v1/claims", {"text": "x", "evidence": "not a list"})[0] == 400


def test_skill_entry_point():
    from conftest import run_skill
    p = run_skill("yt-script/claims.py", "--text", "Studies show it works.")
    assert p.returncode == 1 and "NEEDS SOURCE" in p.stdout
