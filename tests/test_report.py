"""yt-report: rules for the one fix, escaping, inputs, CLI, and the published sample."""
import json
import os
import subprocess
import sys

import pytest

from conftest import ROOT, run_cli
from youtube_intelligence.core.errors import InputError
from youtube_intelligence.reports.channel import build, render_html, render_markdown

EX = os.path.join(ROOT, "examples", "report")
VIDEOS = json.load(open(os.path.join(EX, "videos.json")))
RET = {v: os.path.join(EX, f"retention-{v}.csv") for v in ("smpl0000002", "smpl0000003")}
M = "youtube_intelligence.reports.channel"


def vids(titles, views=None):
    views = views or [1000] * len(titles)
    return [{"channel": "C", "title": t, "views": v, "video_id": f"vid{i:08d}", "duration": 600,
             "published": f"2026-01-{i + 1:02d}T00:00:00Z"} for i, (t, v) in enumerate(zip(titles, views))]


def test_sample_rule1_leaking_opening_wins():
    r = build(VIDEOS, RET)
    assert r["focus"]["rule"] == "opening" and r["focus"]["video_id"] == "smpl0000002"
    assert r["working"]["video_id"] == "smpl0000003" and r["working"]["multiple"] >= 1.5
    assert r["videos"][0]["published"] >= r["videos"][-1]["published"]       # newest first


def test_rule2_packaging_when_no_opening_leaks():
    r = build(VIDEOS, {"smpl0000003": RET["smpl0000003"]})
    assert r["focus"]["rule"] == "packaging"
    assert r["focus"]["title"] == "AMAZING INSANE EDITING TRICKS YOU NEED"   # lowest-scoring flagged title


def test_rule3_cliff_and_rule4_nothing(tmp_path):
    clean = vids(["How I edit a video in 2 hours", "Why I stopped posting daily", "My studio setup in 2026",
                  "What I learned from 100 uploads"])
    csv = tmp_path / "r.csv"
    csv.write_text("Video position (%),Absolute audience retention (%)\n" +
                   "\n".join(f"{i},{100 - 0.2 * i - (3 if i >= 1 else 0) - (12 if i >= 50 else 0)}" for i in range(101)))
    r = build(clean, {"vid00000000": str(csv)})
    # the drop runs from 49% to 50% of a 600 s video; the reader reports where it starts (294 s)
    assert r["focus"]["rule"] == "cliff" and "leave at 4:54" in r["focus"]["detail"]
    assert build(clean)["focus"]["rule"] == "none"


def test_untrusted_titles_are_escaped():
    evil = vids(['<script>alert(1)</script>', '"><img src=x onerror=alert(1)>', "ok title here", "another title"])
    evil[0]["channel"] = evil[1]["channel"] = evil[2]["channel"] = evil[3]["channel"] = "<b>Chan</b>"
    page = render_html(build(evil))
    assert "<script>" not in page and "<img" not in page and "<b>Chan" not in page
    assert "&lt;script&gt;" in page


def test_input_errors(tmp_path):
    two = vids(["a b c", "d e f"])
    two[1]["channel"] = "Other"
    with pytest.raises(InputError, match="pick one with --channel"):
        build(two)
    assert build(two, channel="Other")["channel"] == "Other"
    with pytest.raises(InputError, match="no videos"):
        build(two, channel="Nope")
    with pytest.raises(InputError, match="not in the list"):
        build(VIDEOS, {"zzz": RET["smpl0000002"]})


def test_small_channel_has_no_multiples():
    r = build(vids(["a b c", "d e f", "g h i"], [10, 20, 900]))
    assert r["median_views"] is None and all(v["multiple"] is None for v in r["videos"]) and r["working"] is None


def test_markdown_and_caveats():
    md = render_markdown(build(VIDEOS, RET))
    assert md.startswith("# Channel report: Sample Channel") and "This week's one fix" in md
    assert "do not predict views" in md


def test_cli(tmp_path):
    out = tmp_path / "r.html"
    p = run_cli(M, os.path.join(EX, "videos.json"), "--retention", f"smpl0000002={RET['smpl0000002']}", "--out", str(out))
    assert p.returncode == 0, p.stderr
    assert "Fix the first 15 seconds" in out.read_text()
    j = json.loads(run_cli(M, os.path.join(EX, "videos.json"), "--format", "json").stdout)
    assert j["schema"] == "youtube-intelligence/channel-report@1"
    assert run_cli(M, os.path.join(EX, "videos.json"), "--retention", "nonsense").returncode == 1


def test_published_sample_is_current_and_self_contained():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from build_sample_report import sample_html
    committed = open(os.path.join(ROOT, "public", "sample-report.html"), encoding="utf-8").read()
    assert committed == sample_html(), "run: python scripts/build_sample_report.py"
    assert "<script" not in committed and 'src="http' not in committed
    assert "invented" in committed
