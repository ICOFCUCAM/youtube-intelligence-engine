"""Word timings (ICOFCUCAM 0.2): loading, and their use in deadair."""
import json

import pytest

from conftest import fixture, golden, run_cli
from youtube_intelligence.core.transcript import NO_WORDS, Cue, Word, WordTrack, load_cues, load_words
from youtube_intelligence.editing.deadair import analyse, find_cuts

M = "youtube_intelligence.editing.deadair"

YT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.990 align:start position:0%
 
so<00:00:00.400><c> the</c><00:00:00.800><c> um</c><00:00:01.200><c> real</c><00:00:01.600><c> problem</c>

00:00:02.990 --> 00:00:03.000 align:start position:0%
so the um real problem
 

00:00:03.000 --> 00:00:05.000 align:start position:0%
so the um real problem
was<00:00:03.400><c> timing</c>

"""


def _whisper(segments):
    return json.dumps({"segments": segments})


# --- loading ---------------------------------------------------------------------------------------
def test_whisper_words_exact(write):
    p = write("w.json", _whisper([{"start": 0, "end": 2, "text": " so the um real",
                                   "words": [{"word": " so", "start": 0, "end": 0.3},
                                             {"word": " the", "start": 0.3, "end": 0.6},
                                             {"word": " um,", "start": 0.7, "end": 1.0},
                                             {"word": " 42", "start": None, "end": None},   # WhisperX untimed
                                             {"word": " real", "start": 1.2, "end": 1.6}]}]))
    t = load_words(p)
    assert t.exact_ends and [w.text for w in t.words] == ["so", "the", "um,", "real"]


def test_plain_transcripts_have_no_words():
    for f in ("sample.srt", "sample.vtt", "sample_whisper.json", "sample_array.json"):
        assert not load_words(fixture(f)).available


def test_youtube_rolling_vtt(write):
    p = write("yt.vtt", YT)
    cues = load_cues(p)
    # each spoken line once, the 10 ms transition cue's repeat dropped, the " " line ignored
    assert [c.text for c in cues] == ["so the um real problem", "was timing"]
    t = load_words(p)
    assert not t.exact_ends
    assert [(w.start, w.text) for w in t.words] == [(0.0, "so"), (0.4, "the"), (0.8, "um"), (1.2, "real"),
                                                    (1.6, "problem"), (3.0, "was"), (3.4, "timing")]
    assert t.words[2].end == 1.2                       # ends where the next word starts


def test_space_only_line_does_not_end_a_cue(write):
    p = write("s.vtt", "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n \nhello there\n")
    assert load_cues(p) == [(0.0, 1.0, "hello there")]


def test_plain_vtt_repeated_lines_are_kept(write):
    # without inline word tags a repeated line is real speech, not a rolling duplicate
    p = write("r.vtt", "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nagain\n\n00:00:01.000 --> 00:00:02.000\nagain\n")
    assert len(load_cues(p)) == 2


# --- deadair with words ----------------------------------------------------------------------------
CUES = [Cue(0, 2, "so the um real problem"), Cue(4, 6, "was timing all along")]


def test_inline_filler_cut_from_words():
    words = WordTrack([Word(0, .3, "so"), Word(.3, .6, "the"), Word(.7, 1.0, "um,"), Word(1.1, 1.5, "real"),
                       Word(1.5, 2, "problem"), Word(4, 4.5, "was"), Word(4.5, 6, "timing")], True)
    cuts = find_cuts(CUES, words=words)
    f = [c for c in cuts if c["kind"] == "FILLER"]
    assert f == [{"kind": "FILLER", "start": .7, "end": 1.0, "why": '"um," inside a sentence', "review": False}]
    assert not [c for c in find_cuts(CUES) if c["kind"] == "FILLER"]   # no words, no inline cut


def test_meaningful_words_are_not_fillers():
    words = WordTrack([Word(0, .3, "like"), Word(.3, .6, "so"), Word(.6, .9, "right")], True)
    assert [c for c in find_cuts([Cue(0, 1, "like so right now")], words=words) if c["kind"] == "FILLER"] == []


def test_exact_words_find_pause_hidden_inside_a_cue():
    cues = [Cue(0, 6, "one long cue with a pause in the middle")]
    words = WordTrack([Word(0, 1, "one"), Word(1, 2, "long"), Word(4.5, 5, "with"), Word(5, 6, "pause")], True)
    dead = [c for c in find_cuts(cues, words=words) if c["kind"] == "DEAD"]
    assert dead == [{"kind": "DEAD", "start": 2.225, "end": 4.275, "why": "2.50s gap", "review": False}]
    assert [c for c in find_cuts(cues) if c["kind"] == "DEAD"] == []


def test_start_only_words_keep_cue_level_gaps():
    words = WordTrack([Word(0, 4, "so"), Word(4, 6, "was")], False)       # YouTube-style: no real ends
    dead = [c for c in find_cuts(CUES, words=words) if c["kind"] == "DEAD"]
    assert len(dead) == 1 and dead[0]["why"] == "2.00s gap"


def test_filler_only_cue_not_double_cut_by_words():
    cues = [Cue(0, 1, "um"), Cue(1.1, 3, "then the point")]
    words = WordTrack([Word(0, 1, "um"), Word(1.1, 3, "then")], True)
    assert [c["kind"] for c in find_cuts(cues, words=words)].count("FILLER") == 1


# --- review flag -----------------------------------------------------------------------------------
def test_review_flag_and_hold():
    cues = [Cue(0, 1, "first line here"), Cue(2.2, 3, "second line here"), Cue(6, 7, "third line here")]
    r = analyse(cues)
    assert [(c["why"], c["review"]) for c in r["cuts"]] == [("1.20s gap", True), ("3.00s gap", False)]
    held = analyse(cues, hold_review=True)
    assert held["cuts"] == r["cuts"] and held["held_for_review"] == 1
    assert held["removed"] == round(3.0 - 0.45, 3) and len(held["removed_intervals"]) == 1
    assert analyse(cues, review_below=0)["cuts"][0]["review"] is False


def test_plain_transcript_edl_unchanged_apart_from_review_field():
    r = analyse(load_cues(fixture("sample.srt")))
    up = golden("deadair_sample_srt.json")
    assert [{k: c[k] for k in ("kind", "start", "end", "why")} for c in r["cuts"]] == up["cuts"]
    assert r["removed"] == up["removed"] and r["word_timings"] == "none"


# --- CLI -------------------------------------------------------------------------------------------
def test_cli_words_auto_and_off(write):
    p = write("yt.vtt", YT)
    on = json.loads(run_cli(M, p, "--json").stdout)
    off = json.loads(run_cli(M, p, "--json", "--words", "off").stdout)
    assert on["word_timings"] == "start-only" and off["word_timings"] == "none"
    assert any("inside a sentence" in c["why"] for c in on["cuts"])
    assert not any("inside a sentence" in c["why"] for c in off["cuts"])
    text = run_cli(M, p).stdout
    assert "word timings: start-only" in text
