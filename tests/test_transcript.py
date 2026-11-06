import json

import pytest

from conftest import fixture
from youtube_intelligence.core.errors import InputError
from youtube_intelligence.core.transcript import duration, load, load_cues, parse_ts


# --- regression: upstream deadair.load crashed on a top-level JSON array --------------------
def test_json_array_is_accepted(write):
    p = write("a.json", json.dumps([{"start": 0, "end": 1.5, "text": " hi there "},
                                    {"start": 2, "end": 3, "text": None}]))
    assert load_cues(p) == [(0.0, 1.5, "hi there"), (2.0, 3.0, "")]


def test_json_array_fixture_matches_object_fixture():
    assert load_cues(fixture("sample_array.json")) == load_cues(fixture("sample_whisper.json"))


def test_json_object_without_segments_is_empty(write):
    assert load_cues(write("o.json", '{"text": "no segments"}')) == []


@pytest.mark.parametrize("body,msg", [
    ("{bad json", "not valid JSON"),
    ('"a string"', "expected a JSON object or array"),
    ('{"segments": {"start": 0}}', "'segments' must be a list"),
    ('[{"end": 1, "text": "x"}]', "has no 'start'"),
    ('[{"start": "zero", "end": 1}]', "non-numeric"),
    ('[1, 2]', "is not an object"),
])
def test_malformed_json_raises_input_error(write, body, msg):
    with pytest.raises(InputError, match=msg):
        load_cues(write("bad.json", body))


def test_missing_and_directory_inputs(tmp_path):
    with pytest.raises(InputError, match="file not found"):
        load_cues(str(tmp_path / "nope.srt"))
    with pytest.raises(InputError, match="file not found"):
        load_cues(str(tmp_path))


def test_empty_transcript(write):
    assert load_cues(write("e.srt", "")) == []
    assert load_cues(write("e.vtt", "WEBVTT\n\n")) == []
    assert duration([]) == 0.0


# --- timestamps -------------------------------------------------------------------------------
@pytest.mark.parametrize("s,v", [
    ("00:00:00,000", 0.0), ("00:00:01,500", 1.5), ("00:00:59.999", 59.999),
    ("00:59:59,999", 3599.999), ("01:00:00,000", 3600.0), ("10:00:00.000", 36000.0),
    ("00:01.000", 1.0), ("59:59.500", 3599.5), (" 00:00:02,250 ", 2.25),
])
def test_parse_ts_boundaries(s, v):
    assert parse_ts(s) == pytest.approx(v)


@pytest.mark.parametrize("s", ["1:2:3:4", "12", "aa:bb"])
def test_parse_ts_rejects_garbage(s):
    with pytest.raises(InputError):
        parse_ts(s)


def test_srt_and_vtt_fixtures_agree():
    srt, vtt = load_cues(fixture("sample.srt")), load_cues(fixture("sample.vtt"))
    assert len(srt) == 24 and srt == vtt
    assert srt[0] == (0.0, 3.2, "Your first fifteen seconds decide whether anyone stays.")
    assert duration(srt) == 90.0


def test_vtt_tags_and_note_blocks(write):
    p = write("t.vtt", "WEBVTT\n\nNOTE this is a comment\nthat spans lines\n\n"
                       "00:00:01.000 --> 00:00:02.000 align:start\n<v Sam><c>hello</c> <00:00:01.500>world\n\n"
                       "NOTE another note\n\n"
                       "00:00:02.000 --> 00:00:03.000\nsecond\n")
    assert load_cues(p) == [(1.0, 2.0, "hello world"), (2.0, 3.0, "second")]


def test_multiline_srt_cue_and_bom(write):
    p = write("m.srt", "﻿1\n00:00:00,000 --> 00:00:02,000\nline one\nline two\n\n2\n00:00:02,000 --> 00:00:03,000\n42\n")
    # a cue whose only text is a number is dropped (upstream skips digit-only lines as indices)
    assert load_cues(p) == [(0.0, 2.0, "line one line two")]


def test_duration_uses_latest_end_not_last_cue():
    from youtube_intelligence.core.transcript import Cue
    assert duration([Cue(0, 10, "a"), Cue(2, 4, "b")]) == 10


def test_upstream_alias():
    assert load is load_cues
