import json

import pytest

from conftest import fixture, run_cli, run_skill
from youtube_intelligence.core.errors import InputError
from youtube_intelligence.core.transcript import Cue, load_cues
from youtube_intelligence.shorts.candidates import find


def test_candidates_respect_window_and_do_not_overlap():
    c = find(load_cues(fixture("sample.srt")), 20, 55, 5)
    assert c
    for x in c:
        assert 20 <= x["seconds"] <= 55
    spans = sorted((x["start"], x["end"]) for x in c)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))


def test_connective_opening_is_penalised():
    base = [Cue(0, 5, "Intro words here."), Cue(7, 20, "Hooks decide everything."),
            Cue(20.5, 30, "But the problem is timing."), Cue(32, 40, "Done.")]
    alt = list(base)
    alt[1] = Cue(7, 20, "and hooks decide everything.")
    good, bad = find(base, 20, 40, 1)[0], find(alt, 20, 40, 1)[0]
    assert good["score"] > bad["score"]
    assert any('opens on "and"' in n for n in bad["notes"])


def test_filler_never_starts_or_ends_a_candidate():
    cues = [Cue(0, 1, "um")] + [Cue(1 + i * 5, 5 + i * 5, f"Sentence number {i}.") for i in range(8)] + [Cue(46, 47, "uh")]
    for x in find(cues, 10, 40, 5):
        assert x["first_line"] not in ("um", "uh") and x["last_line"] not in ("um", "uh")


def test_empty_and_too_short():
    assert find([], 20, 55) == []
    assert find([Cue(0, 5, "Too short.")], 20, 55) == []


@pytest.mark.parametrize("args", [(0, 10, 1), (30, 20, 1), (20, 55, 0)])
def test_bad_parameters(args):
    with pytest.raises(InputError):
        find([Cue(0, 1, "x")], *args)


def test_cli_and_skill_entry_point():
    p = run_cli("youtube_intelligence.shorts.candidates", fixture("sample_array.json"), "--json", "--top", "2")
    assert p.returncode == 0 and len(json.loads(p.stdout)["candidates"]) == 2
    assert run_skill("yt-shorts/shorts.py", fixture("regress_empty.srt")).returncode == 1
