import json

import pytest

from conftest import fixture, golden, run_cli, run_skill
from youtube_intelligence.core.errors import InputError
from youtube_intelligence.core.transcript import Cue, load_cues
from youtube_intelligence.editing.chapters import build, is_valid, mmss

M = "youtube_intelligence.editing.chapters"


@pytest.mark.parametrize("src,gold,target", [
    ("sample.srt", "chapters_sample_srt.json", 7),
    ("sample.vtt", "chapters_sample_vtt.json", 7),
    ("sample_whisper.json", "chapters_sample_whisper_json.json", 7),
    ("sample.srt", "chapters_sample_srt_target3.json", 3),
])
def test_boundaries_match_upstream_output(src, gold, target):
    # draft titles are excluded: upstream's were nondeterministic (see test_titles_are_deterministic)
    assert _bounds(build(load_cues(fixture(src)), target)) == _bounds(golden(gold))


def _bounds(r):
    return r["valid"], [(c["start"], c["label"], c["seconds"]) for c in r["chapters"]]


def test_titles_are_deterministic_across_hash_seeds():
    import os, subprocess, sys
    from conftest import ROOT
    outs = set()
    for seed in ("0", "1", "2", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=os.path.join(ROOT, "src"))
        p = subprocess.run([sys.executable, "-m", M, fixture("sample.srt"), "--json"], env=env,
                           capture_output=True, text=True, cwd=ROOT)
        outs.add(p.stdout)
    assert len(outs) == 1
    titles = [c["draft_title"] for c in json.loads(outs.pop())["chapters"]]
    assert titles[0] == "Open Opening First"
    # each upstream title word set is drawn from the same keyword pool; only tie order changed
    up = golden("chapters_sample_srt.json")["chapters"]
    assert titles[0].split()[:2] == up[0]["draft_title"].split()[:2]


def test_json_array_regression():
    # upstream chapters.py imported deadair.load and crashed on this file
    assert build(load_cues(fixture("sample_array.json"))) == build(load_cues(fixture("sample_whisper.json")))
    p = run_skill("yt-chapters/chapters.py", fixture("sample_array.json"), "--json")
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["valid"] is True


def test_youtube_rules_hold_on_output():
    r = build(load_cues(fixture("sample.srt")), 8)
    ch = r["chapters"]
    assert ch[0]["start"] == 0 and ch[0]["label"] == "0:00"
    assert len(ch) >= 3 and all(c["seconds"] >= 10 for c in ch)
    assert [c["start"] for c in ch] == sorted(c["start"] for c in ch)
    assert abs(sum(c["seconds"] for c in ch) - 90.0) < 0.05


def test_short_video_is_flagged_invalid():
    cues = [Cue(i * 2.0, i * 2.0 + 1.8, f"line number {i} words") for i in range(8)]  # 15.8 s total
    r = build(cues)
    assert r["valid"] is False and len(r["chapters"]) < 3


def test_is_valid_rules():
    ok = [{"start": 0, "seconds": 10}, {"start": 10, "seconds": 10}, {"start": 20, "seconds": 10}]
    assert is_valid(ok)
    assert not is_valid(ok[:2])
    assert not is_valid([{"start": 1, "seconds": 10}] + ok[1:])
    assert not is_valid(ok[:2] + [{"start": 20, "seconds": 9.99}])


def test_too_few_cues_and_bad_target():
    with pytest.raises(InputError, match="too few cues"):
        build([Cue(0, 1, "a")] * 5)
    with pytest.raises(InputError):
        build(load_cues(fixture("sample.srt")), 0)


@pytest.mark.parametrize("t,s", [(0, "0:00"), (9.99, "0:09"), (59, "0:59"), (60, "1:00"),
                                 (3599, "59:59"), (3600, "1:00:00"), (3725, "1:02:05")])
def test_mmss_boundaries(t, s):
    assert mmss(t) == s


def test_cli_errors():
    assert run_cli(M, "nope.srt").returncode == 1
    p = run_cli(M, fixture("regress_short_retake.srt"))
    assert p.returncode == 1 and "too few cues" in p.stderr
