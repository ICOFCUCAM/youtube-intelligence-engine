"""yt-localize: export, per-language checks, build, and the demo pack."""
import copy
import json
import os

import pytest

from conftest import ROOT, fixture, run_cli, run_skill
from youtube_intelligence.core.errors import InputError
from youtube_intelligence.core.transcript import Cue, load_cues, parse_subtitles
from youtube_intelligence.localize.pack import _protected, build, check, export, wrap

EX = os.path.join(ROOT, "examples", "localize")
DEMO = json.load(open(os.path.join(EX, "pack.json"), encoding="utf-8"))
DESC = open(os.path.join(EX, "description.txt")).read()
M = "youtube_intelligence.localize.pack"


def units(pack, kind):
    return [u for u in pack["units"] if u["kind"] == kind]


def test_export_structure():
    p = export("Title here", DESC, load_cues(fixture("sample.srt")), ["es", "pt-BR"])
    assert p["targets"] == ["es", "pt-BR"] and units(p, "title")[0]["translations"] == {"es": "", "pt-BR": ""}
    ch = units(p, "chapter")
    assert [(c["timestamp"], c["source"]) for c in ch] == [("0:00", "The first fifteen seconds"),
                                                          ("0:31", "Thumbnails at feed size"), ("1:00", "Reading retention")]
    caps = units(p, "caption")
    assert len(caps) == 24 and (caps[0]["start"], caps[0]["end"]) == (0.0, 3.2)
    link = next(u for u in p["units"] if "https://" in u["source"])
    assert link["keep"] == ["HOOKS20", "https://example.org/hook-template"]
    assert units(p, "blank")


@pytest.mark.parametrize("text,keep", [
    ("AMAZING INSANE TRICKS", []), ("use code HOOKS for 20% off", ["HOOKS"]), ("SAVE10 today", ["SAVE10"]),
    ("see www.example.org.", ["www.example.org"]), ("mail a.b@example.org", ["a.b@example.org"]),
    ("follow @me #tag", ["#tag", "@me"]), ("2026 review", []),
])
def test_protected_tokens(text, keep):
    assert _protected(text) == keep


@pytest.mark.parametrize("langs,src,msg", [
    ([], "en", "at least one"), (["spanish"], "en", "not a language code"), (["es", "es"], "en", "distinct"),
    (["en"], "en", "differ from the source"),
])
def test_export_language_validation(langs, src, msg):
    with pytest.raises(InputError, match=msg):
        export("t", None, None, langs, src)


def test_wrap():
    assert wrap("short line") == "short line"
    w = wrap("Casi todos los ganchos fallan: resumen en vez de abrir una pregunta.")
    assert w.count("\n") == 1 and all(len(x) <= 42 for x in w.splitlines())
    assert wrap("already\ntwo lines") == "already\ntwo lines"


def test_demo_spanish_pack_is_ready_with_two_reading_speed_warnings():
    r = check(DEMO)["languages"]["es"]
    assert r["ready"] and r["fails"] == 0
    assert [p["unit"] for p in r["problems"]] == ["cue-0007", "cue-0012"]
    assert all("characters per second" in p["message"] for p in r["problems"])
    assert "Not reviewed by a fluent speaker" in DEMO["translator_note"]


def _broken(mut):
    p = copy.deepcopy(DEMO)
    mut(p)
    return check(p)["languages"]["es"]


def _unit(p, uid):
    return next(u for u in p["units"] if u["id"] == uid)


@pytest.mark.parametrize("name,mut,msg", [
    ("untranslated", lambda p: _unit(p, "cue-0003").__setitem__("translations", {"es": ""}), "not translated"),
    ("link changed", lambda p: _unit(p, "desc-002")["translations"].__setitem__(
        "es", "Plantilla gratis: https://example.org/plantilla - código HOOKS20."), "must stay exactly"),
    ("code translated", lambda p: _unit(p, "desc-002")["translations"].__setitem__(
        "es", "Plantilla: https://example.org/hook-template - código GANCHOS20."), "must stay exactly"),
    ("title too long", lambda p: _unit(p, "title")["translations"].__setitem__("es", "x" * 101), "limit is 100"),
    ("angle brackets", lambda p: _unit(p, "desc-001")["translations"].__setitem__("es", "<b>hola</b>"), "rejects < and >"),
    ("line break in title", lambda p: _unit(p, "title")["translations"].__setitem__("es", "uno\ndos"), "line break"),
])
def test_failures(name, mut, msg):
    r = _broken(mut)
    assert not r["ready"] and any(msg in x["message"] for x in r["problems"] if x["status"] == "fail")


def test_description_size_counts_bytes():
    def mut(p):
        _unit(p, "desc-001")["translations"]["es"] = "é" * 2600        # 2,600 characters, 5,200 bytes
    r = _broken(mut)
    assert any("bytes" in x["message"] for x in r["problems"])


def test_build_keeps_timings_and_wraps(tmp_path):
    files = build(DEMO, "es")
    assert files["title.txt"] == "Por qué tus primeros 15 segundos pierden espectadores\n"
    d = files["description.txt"]
    assert "0:00 Los primeros quince segundos" in d and "https://example.org/hook-template" in d and "HOOKS20" in d
    cues = parse_subtitles(files["srt"])
    src = units(DEMO, "caption")
    assert [(c.start, c.end) for c in cues] == [(u["start"], u["end"]) for u in src]
    assert all(len(line) <= 42 for c in files["srt"].split("\n\n") for line in c.splitlines()[2:])


def test_build_refuses_a_failing_language():
    p = copy.deepcopy(DEMO)
    _unit(p, "cue-0001")["translations"]["es"] = ""
    with pytest.raises(InputError, match="failing check"):
        build(p, "es")
    with pytest.raises(InputError, match="not a target"):
        build(DEMO, "fr")


def test_cli_and_skill_entry_point(tmp_path):
    out = tmp_path / "pack.json"
    p = run_cli(M, "export", "--title", "A title", "--description", os.path.join(EX, "description.txt"),
                "--transcript", fixture("sample.srt"), "--lang", "es,fr", "--out", str(out))
    assert p.returncode == 0 and "units for es, fr" in p.stderr
    ck = run_cli(M, "check", str(out))
    assert ck.returncode == 1 and "NOT READY" in ck.stdout              # nothing translated yet
    ok = run_skill("yt-localize/localize.py", "build", os.path.join(EX, "pack.json"), "--lang", "es", "--out-dir", str(tmp_path / "dist"))
    assert ok.returncode == 0, ok.stderr
    assert sorted(os.listdir(tmp_path / "dist")) == ["es.description.txt", "es.srt", "es.title.txt"]
    assert run_cli(M, "check", "missing.json").returncode == 1
