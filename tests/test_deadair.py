import json
import time

import pytest

from conftest import fixture, golden, run_cli, run_skill
from youtube_intelligence.core.transcript import Cue, load_cues
from youtube_intelligence.editing.deadair import analyse, find_cuts, is_filler, is_restart

M = "youtube_intelligence.editing.deadair"


def _core(r):
    return {k: r[k] for k in ("duration", "cuts", "removed", "out")}


# --- equivalence with upstream on inputs the fixes do not touch -----------------------------
@pytest.mark.parametrize("src,gold,floor", [
    ("sample.srt", "deadair_sample_srt.json", 0.45),
    ("sample.vtt", "deadair_sample_vtt.json", 0.45),
    ("sample_whisper.json", "deadair_sample_whisper_json.json", 0.45),
    ("sample.srt", "deadair_sample_srt_floor1.json", 1.0),
])
def test_matches_upstream_output(src, gold, floor):
    assert _core(analyse(load_cues(fixture(src)), floor)) == _core(golden(gold))


def test_json_array_produces_same_edl_as_object():
    a = analyse(load_cues(fixture("sample_array.json")))
    assert _core(a) == _core(golden("deadair_sample_whisper_json.json"))


# --- regression: overlapping cuts were double-counted ----------------------------------------
OVERLAP = [Cue(0.0, 3.0, "so the main thing is"), Cue(2.5, 3.5, "um"),
           Cue(3.2, 6.0, "so the main thing is this")]


def test_overlapping_cuts_counted_once():
    r = analyse(OVERLAP)
    assert [c["kind"] for c in r["cuts"]] == ["REPEAT", "FILLER"]
    assert r["removed"] == 3.5          # upstream reported 4.0
    assert r["out"] == 2.5              # upstream reported 2.0
    assert r["removed_intervals"] == [[0.0, 3.5]]
    assert r["overlap_counted_once"] == 0.5


def test_removed_never_exceeds_duration():
    cues = [Cue(0, 5, "um"), Cue(0, 5, "uh"), Cue(1, 4, "okay")]
    r = analyse(cues)
    assert r["removed"] == 5.0 and r["out"] == 0.0


# --- regression: dead gap measured from the latest end, not the previous cue -----------------
def test_dead_gap_does_not_cut_through_nested_speech():
    cues = [Cue(0, 10, "a long sentence that keeps going"), Cue(1, 2, "short overlay"),
            Cue(10.2, 12, "next line here")]
    # upstream measured 8.2s of "dead air" from 2.0 to 10.2 - straight through cue 0's speech
    assert [c for c in find_cuts(cues) if c["kind"] == "DEAD"] == []


def test_dead_air_trimmed_from_the_middle():
    cuts = find_cuts([Cue(0, 1, "first line here"), Cue(3, 4, "second line here")], floor=0.4)
    assert cuts == [{"kind": "DEAD", "start": 1.2, "end": 2.8, "why": "2.00s gap"}]


def test_gap_at_floor_is_kept():
    assert find_cuts([Cue(0, 1, "first words here"), Cue(1.45, 2, "more words here")], 0.45) == []


def test_negative_floor_rejected():
    from youtube_intelligence.core.errors import InputError
    with pytest.raises(InputError):
        find_cuts([], -1)


# --- filler handling ---------------------------------------------------------------------------
@pytest.mark.parametrize("t", ["um", "Um?", "Okay!", "uh, uh...", "so yeah", "you know", "Hmm.",
                               "erm", "…um…", '"basically"', "I mean, right"])
def test_filler_detected(t):
    assert is_filler(t)


@pytest.mark.parametrize("t", ["", "umbrella", "so the thing", "like this one", "umso",
                               "yeah I agree", "right now"])
def test_not_filler(t):
    assert not is_filler(t)


def test_filler_regex_is_linear_on_adversarial_input():
    start = time.perf_counter()
    for s in ("u" + "m" * 5000 + "!x", "uh" * 3000 + "x", "um " * 3000 + "zzz"):
        is_filler(s)
    assert time.perf_counter() - start < 1.0


# --- repeat detection ------------------------------------------------------------------------
def test_restart_found_like_upstream():
    assert is_restart("Read the hook out loud and stop", "Read the hook out loud and breathe")


def test_short_abandoned_take_now_found():
    # upstream compared earlier[:5] == later[:5] and missed this
    assert is_restart("so the thing", "so the thing about hooks is timing")
    cues = load_cues(fixture("regress_short_retake.srt"))
    kinds = [c["kind"] for c in find_cuts(cues)]
    assert "REPEAT" in kinds and "FILLER" in kinds


def test_leading_disfluency_ignored_for_restart():
    assert is_restart("um so the main point", "so the main point is this")


@pytest.mark.parametrize("a,b", [("so the", "so the thing"), ("the cat sat", "the dog sat"),
                                 ("", "anything at all"), ("one two three", "one two")])
def test_not_a_restart(a, b):
    assert not is_restart(a, b)


# --- CLI -----------------------------------------------------------------------------------------
def test_cli_json_array_regression():
    p = run_cli(M, fixture("sample_array.json"), "--json")
    assert p.returncode == 0, p.stderr
    d = json.loads(p.stdout)
    assert d["schema"] == "youtube-intelligence/edl@1" and d["removed"] == 14.55


@pytest.mark.parametrize("args,msg", [
    (["missing.srt"], "file not found"),
    (["tests/fixtures/regress_malformed.json"], "not valid JSON"),
    (["tests/fixtures/regress_empty.srt"], "no cues found"),
])
def test_cli_bad_input_exits_1(args, msg):
    p = run_cli(M, *args)
    assert p.returncode == 1 and msg in p.stderr and "Traceback" not in p.stderr


def test_skill_entry_point_text_output():
    p = run_skill("yt-edit/deadair.py", fixture("sample.srt"), "--floor", "0.45")
    assert p.returncode == 0, p.stderr
    assert "10 cuts, 14.55s removed, 75.45s out (16.2% shorter)" in p.stdout


def test_skill_entry_point_keeps_upstream_import_names():
    import os, subprocess, sys
    from conftest import ROOT
    code = ("import sys; sys.path.insert(0, 'skills/yt-edit'); from deadair import load, parse_ts; "
            "print(parse_ts('00:00:01,500'))")
    p = subprocess.run([sys.executable, "-I", "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert p.stdout.strip() == "1.5", p.stderr
