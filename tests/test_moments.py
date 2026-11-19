"""yt-moments: tagging, alignment, honesty rules, and recovery of scripted effects on invented data."""
import json
import os
import subprocess
import sys

import pytest

from conftest import ROOT, run_cli
from youtube_intelligence.analytics import moments as M
from youtube_intelligence.core.errors import InputError
from youtube_intelligence.core.transcript import Cue

EX = os.path.join(ROOT, "examples", "moments")
MAN = os.path.join(EX, "manifest.json")
CLI = "youtube_intelligence.analytics.moments"


@pytest.mark.parametrize("text,expected", [
    ("This video is sponsored by Acme, use code X", ["sponsor"]),
    ("Thanks to Ledgerly for sponsoring this video", ["sponsor"]),
    ("Subscribe and turn on notifications", ["self_promo"]),
    ("Before we go on, a quick reminder to like the video", ["self_promo", "housekeeping"]),
    ("Quick story, I forgot to press record", ["tangent"]),
    ("As I said earlier, confirm the title", ["recap"]),
    ("Step two: open a gap", ["signpost"]),
    ("Next, the three words that kill a hook", ["signpost"]),
    ("Contrast beats colour at small sizes", []),
])
def test_tags(text, expected):
    assert sorted(M.tags(text)) == sorted(expected)


def test_curve_mapping_and_interpolation():
    curve = M.curve_seconds([(0, 100), (50, 80), (100, 60)], "percent", 200)
    assert curve == [(0, 100), (100, 80), (200, 60)]
    assert M.y_at(curve, 50) == 90 and M.y_at(curve, -5) == 100 and M.y_at(curve, 999) == 60
    assert M.baseline_rate(curve, 0, 200) == pytest.approx(0.2)


def test_opening_and_ending_are_skipped():
    curve = [(t, 100 - 0.1 * t) for t in range(0, 301, 3)]
    cues = [Cue(0, 20, "sponsored by x"), Cue(100, 120, "sponsored by y"), Cue(280, 299, "subscribe now")]
    v = M.analyse_video("v", "t", cues, curve, 300)
    assert [m["start"] for m in v["moments"]] == [100]                # 0-30 s and last 10% left out
    assert v["moments"][0]["extra"] == pytest.approx(0, abs=1e-6)     # no extra loss on a steady curve


def test_pattern_needs_three_occurrences_across_two_videos():
    def video(vid, n):
        curve = [(t, 100 - 0.05 * t - (2 if t >= 100 else 0)) for t in range(0, 401, 2)]
        cues = [Cue(90 + 15 * i, 104 + 15 * i, "sponsored by x") for i in range(n)]
        return M.analyse_video(vid, vid, cues, curve, 400)
    one_video = M.aggregate([video("a", 3)])
    assert one_video["patterns"][0]["finding"] == "too few to tell"
    two_videos = M.aggregate([video("a", 2), video("b", 1)])
    assert two_videos["patterns"][0]["finding"] in ("costs viewers", "no clear effect", "holds viewers")


def test_recovers_scripted_effects_on_invented_demo():
    """The demo script makes sponsor reads, tangents and asks cost viewers. The tool must recover
    those amounts closely - and must NOT find the scripted signpost benefit, the documented blind
    spot (the commonest kind of sentence sets the baseline)."""
    r = M.run(MAN)
    p = {x["type"]: x for x in r["patterns"]}
    assert p["sponsor"]["finding"] == "costs viewers" and p["sponsor"]["mean_extra"] == pytest.approx(3.27, abs=0.1)
    assert p["tangent"]["finding"] == "costs viewers" and p["tangent"]["mean_extra"] == pytest.approx(1.93, abs=0.1)
    assert p["self_promo"]["finding"] == "costs viewers" and p["self_promo"]["mean_extra"] == pytest.approx(1.37, abs=0.1)
    assert p["recap"]["finding"] == "too few to tell"                  # 2 occurrences
    assert p["signpost"]["finding"] == "no clear effect"               # the documented blind spot
    assert all("sponsor" in m["tags"] for m in r["worst_moments"][:3])
    assert "can't stand out" in r["caveat"]


@pytest.mark.parametrize("manifest,msg", [
    ({"videos": []}, "non-empty"),
    ({"videos": [{"id": "a"}]}, "needs id, transcript and retention"),
    ({"videos": [{"id": "a", "transcript": "../x.srt", "retention": "r.csv"}]}, "inside the manifest"),
    ({"videos": [{"id": "a", "transcript": "/etc/passwd", "retention": "r.csv"}]}, "inside the manifest"),
    ({"videos": [{"id": "a", "transcript": "t.srt", "retention": "r.csv"},
                 {"id": "a", "transcript": "t.srt", "retention": "r.csv"}]}, "duplicate"),
    ({"videos": [{"id": "a", "transcript": "t.srt", "retention": "r.csv", "duration": -1}]}, "positive"),
])
def test_manifest_validation(tmp_path, manifest, msg):
    p = tmp_path / "m.json"
    p.write_text(json.dumps(manifest))
    with pytest.raises(InputError, match=msg):
        M.load_manifest(str(p))


def test_cli():
    p = run_cli(CLI, MAN)
    assert p.returncode == 0 and "THE FIVE COSTLIEST SENTENCES" in p.stdout and "(1 time, 1 video)" in p.stdout
    j = json.loads(run_cli(CLI, MAN, "--json").stdout)
    assert j["schema"] == "youtube-intelligence/moments@1" and len(j["per_video"]) == 3
    assert run_cli(CLI, "missing.json").returncode == 1


def test_demo_generator_is_deterministic_and_independent(tmp_path):
    subprocess.run([sys.executable, "-I", os.path.join(EX, "generate.py"), str(tmp_path)], check=True)
    for f in os.listdir(tmp_path):
        assert (tmp_path / f).read_bytes() == open(os.path.join(EX, f), "rb").read(), f
    assert "youtube_intelligence" not in open(os.path.join(EX, "generate.py")).read()
