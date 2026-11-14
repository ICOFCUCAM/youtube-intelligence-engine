import json

import pytest

from conftest import fixture, golden, run_cli, run_skill
from youtube_intelligence.analytics.retention import LIMITATIONS, analyse, attach_transcript, load_csv
from youtube_intelligence.core.errors import InputError

M = "youtube_intelligence.analytics.retention"
SAME = ("points", "start", "hook_leak", "end", "cliffs", "slide_per_unit", "said")


def _core(r):
    return {k: r[k] for k in SAME}


def test_matches_upstream_percent_axis():
    rows, hint = load_csv(fixture("retention_percent.csv"))
    assert hint == "percent"
    assert _core(analyse(rows, hint=hint)) == golden("retention_percent.json")


def test_matches_upstream_with_duration_and_transcript():
    rows, hint = load_csv(fixture("retention_percent.csv"))
    r = analyse(rows, 600, hint=hint)
    attach_transcript(r, fixture("sample.srt"))
    assert _core(r) == golden("retention_percent_dur_tr.json")


def test_duration_before_csv_regression():
    # upstream took "600" as the csv path and printed usage
    p = run_skill("yt-retention/retention.py", "--duration", "600", fixture("retention_percent.csv"), "--json")
    assert p.returncode == 0, p.stderr
    d = json.loads(p.stdout)
    assert [c["at_seconds"] for c in d["cliffs"]] == [0.0, 12.0, 240.0]


def test_seconds_header_on_short_video_regression():
    rows, hint = load_csv(fixture("retention_seconds.csv"))
    assert hint == "seconds" and max(r[0] for r in rows) <= 100
    r = analyse(rows, hint=hint)
    up = golden("retention_seconds_UPSTREAM_MISREAD.json")
    assert all(c["at_seconds"] is None for c in up["cliffs"])        # upstream lost the timing
    assert r["axis"] == "seconds" and r["cliffs"][0]["at_seconds"] == 4.0
    # hook window is now the first 30 SECONDS (upstream used the first 10 "percent" = 10 s)
    assert r["hook_leak"] == pytest.approx(24.0)


def test_axis_override_and_headerless_auto(write):
    p = write("r.csv", "\n".join(f"{x},{100 - x * 0.5}" for x in range(0, 50, 5)))
    rows, hint = load_csv(p)
    assert hint is None
    assert analyse(rows)["axis"] == "percent"                       # upstream heuristic retained
    assert analyse(rows, axis="seconds")["axis"] == "seconds"


def test_transcript_json_array_at_cliffs():
    rows, hint = load_csv(fixture("retention_seconds.csv"))
    r = analyse(rows, hint=hint)
    attach_transcript(r, fixture("sample_array.json"))
    assert "fifteen seconds" in r["said"]["4.0"] or "Most hooks" in r["said"]["4.0"]


def test_limitations_reported():
    p = run_cli(M, fixture("retention_percent.csv"))
    assert p.returncode == 0 and "LIMITS" in p.stdout and "Shorts" in p.stdout
    d = json.loads(run_cli(M, fixture("retention_percent.csv"), "--json").stdout)
    assert d["limitations"] == LIMITATIONS


@pytest.mark.parametrize("body", ["", "a,b\n1,2\n", "pos,ret\n" + "\n".join(f"{i},{i}" for i in range(7))])
def test_too_few_points(write, body):
    rows, hint = load_csv(write("few.csv", body))
    with pytest.raises(InputError, match="at least 8"):
        analyse(rows, hint=hint)


def test_bad_inputs_exit_1(tmp_path):
    assert run_cli(M, "missing.csv").returncode == 1
    assert run_cli(M, str(tmp_path)).returncode == 1
    p = run_cli(M, fixture("retention_percent.csv"), "--duration", "0")
    assert p.returncode == 1 and "positive" in p.stderr
    p = run_cli(M, fixture("retention_percent.csv"), "--duration", "600", "--transcript", "missing.srt")
    assert p.returncode == 1 and "file not found" in p.stderr


def test_upward_spikes_are_not_cliffs(write):
    p = write("s.csv", "\n".join(f"{x},{110 if x == 50 else 100 - x * 0.1}" for x in range(0, 100, 5)))
    r = analyse(load_csv(p)[0])
    assert all(c["lost"] > 0 for c in r["cliffs"])
