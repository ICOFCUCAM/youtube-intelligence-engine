import json

from conftest import fixture, golden, run_cli, run_skill
from youtube_intelligence.core.formulas import classify, formulas
from youtube_intelligence.creative import hookscore

M = "youtube_intelligence.creative.hookscore"


def _strip(rows):
    return [{k: v for k, v in r.items() if k != "matched"} for r in rows]


def test_scores_identical_to_upstream_on_formula_examples():
    lines = [f["example"] for f in formulas()]
    assert _strip(hookscore.evaluate(lines)) == golden("hookscore_formula_examples.json")


def test_scores_identical_to_upstream_on_fixture():
    p = run_cli(M, "--json", fixture("hooks.txt"))
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout) == golden("hookscore_hooks.json")


def test_library_has_21_formulas_with_required_fields():
    fs = formulas()
    assert len(fs) == 21
    for f in fs:
        assert {"id", "name", "shape", "example", "fails_when", "match"} <= set(f)


def test_classify_unclassified_and_known():
    assert classify("") == ("Unclassified", 0)
    assert classify("97% of people quit")[0] == "The Statistic"


def test_missing_file_exits_nonzero():
    # upstream printed the usage text and exited 0 when the file did not exist
    p = run_skill("yt-script/hookscore.py", "definitely-missing.txt")
    assert p.returncode == 1 and "file not found" in p.stderr


def test_no_arguments_exits_1():
    assert run_cli(M).returncode == 1


def test_text_output_carries_heuristic_disclaimer():
    p = run_cli(M, "--hook", "You are losing 40% of viewers in the first 8 seconds")
    assert p.returncode == 0
    assert hookscore.DISCLAIMER in p.stdout
    assert "heuristic" in hookscore.__doc__.lower() and "does not predict" in hookscore.__doc__


def test_documented_gaming_behaviour_is_real():
    # Documented limitation, pinned so a future change to it is deliberate: numbers inflate SPECIFICITY.
    plain = hookscore.specificity("Your thumbnails are too busy to read")
    stuffed = hookscore.specificity("Your 3 thumbnails are 47% too busy to read in 2 seconds")
    assert stuffed > plain


def test_empty_hook_scores_zero_without_crash():
    parts, verdict, name, hits = hookscore.score("")
    assert verdict >= 0 and name == "Unclassified"
