import json
import os
import subprocess
import sys

import pytest

from conftest import ROOT, run_cli
from youtube_intelligence.core.errors import InputError
from youtube_intelligence.evaluation import dataset, metrics as m
from youtube_intelligence.evaluation.runner import run

DS = os.path.join(ROOT, "datasets", "synthetic-v1")
DATASETS = {
    "synthetic-v1": ("dataset.json", "tutorial-clean.srt", "tutorial-auto.vtt", "essay-clean.json", "essay-auto.vtt"),
    "synthetic-words-v1": ("dataset.json", "tutorial-whisper.json", "tutorial-youtube.vtt",
                           "essay-whisper.json", "essay-youtube.vtt"),
}


# --- metrics, hand-computed ------------------------------------------------------------------
def test_prf_edge_cases():
    assert m.prf(0, 0, 0) == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert m.prf(0, 2, 0)["precision"] == 0.0
    assert m.prf(0, 0, 3)["recall"] == 0.0
    assert m.prf(1, 2, 4) == {"precision": 0.5, "recall": 0.25, "f1": 0.3333}


def test_intersection_and_length_merge_overlaps_first():
    pred = [(0, 4), (2, 6), (10, 12)]
    gold = [(3, 11)]
    assert m.length(pred) == 8
    assert m.intersection_length(pred, gold) == 4      # 3-6 and 10-11
    assert m.time_counts(pred, gold) == {"tp": 4, "pred": 8, "gold": 8}


def test_iou_and_event_matching_is_one_to_one():
    assert m.iou((0, 2), (1, 3)) == pytest.approx(1 / 3)
    assert m.iou((0, 1), (2, 3)) == 0
    # two predictions over one gold: only one may match
    assert m.event_counts([(0, 2), (0.1, 2)], [(0, 2)], 0.5) == {"tp": 1, "pred": 2, "gold": 1}


def test_boundaries_ignore_zero_and_respect_tolerance():
    c = m.boundary_counts([0, 30, 61, 100], [0, 31, 64.5], tolerance=3)
    assert c == {"tp": 1, "pred": 3, "gold": 2}   # 30~31 matches, 61 vs 64.5 is outside 3 s


def test_spans():
    c = m.span_counts([(0, 30), (40, 60), (100, 120)], [(2, 28), (45, 60)], 0.5)
    assert c == {"tp": 2, "gold_hit": 2, "pred": 3, "gold": 2}
    assert m.span_prf(c) == {"precision": 0.6667, "recall": 1.0, "f1": 0.8}


# --- dataset validation ----------------------------------------------------------------------
def _ds(tmp_path, body, transcript=True):
    if transcript:
        (tmp_path / "t.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhello there friend\n")
    p = tmp_path / "d.json"
    p.write_text(json.dumps(body) if not isinstance(body, str) else body)
    return str(p)


@pytest.mark.parametrize("body,msg", [
    ("{bad", "not valid JSON"),
    ({"cases": []}, "non-empty 'cases'"),
    ({"cases": [{"id": "a", "transcript": "t.srt"}]}, "'synthetic' must be"),
    ({"synthetic": True, "cases": [{"id": "a"}]}, "needs 'id' and 'transcript'"),
    ({"synthetic": True, "cases": [{"id": "a", "transcript": "t.srt"}, {"id": "a", "transcript": "t.srt"}]}, "duplicate id"),
    ({"synthetic": True, "cases": [{"id": "a", "transcript": "../t.srt"}]}, "inside the dataset folder"),
    ({"synthetic": True, "cases": [{"id": "a", "transcript": "/etc/passwd"}]}, "inside the dataset folder"),
    ({"synthetic": True, "cases": [{"id": "a", "transcript": "t.srt", "labels": {"cuts": [{"start": 2, "end": 1}]}}]}, "ends before"),
    ({"synthetic": True, "cases": [{"id": "a", "transcript": "t.srt", "labels": {"cuts": [{"start": 0, "end": 1, "kind": "X"}]}}]}, "unknown kind"),
    ({"synthetic": True, "cases": [{"id": "a", "transcript": "t.srt", "labels": {"chapters": ["x"]}}]}, "list of seconds"),
])
def test_dataset_validation(tmp_path, body, msg):
    with pytest.raises(InputError, match=msg):
        dataset.load(_ds(tmp_path, body))


def test_tasks_without_labels_are_skipped(tmp_path):
    r = run(_ds(tmp_path, {"synthetic": False, "cases": [{"id": "a", "transcript": "t.srt"}]}))
    assert r["summary"] == {} and set(r["cases"][0]) == {"id", "cues"}


# --- the synthetic set -----------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(DATASETS))
def test_generator_is_deterministic(tmp_path, name):
    d = os.path.join(ROOT, "datasets", name)
    subprocess.run([sys.executable, "-I", os.path.join(d, "generate.py"), str(tmp_path)], check=True)
    for f in DATASETS[name]:
        assert (tmp_path / f).read_bytes() == open(os.path.join(d, f), "rb").read(), f


@pytest.mark.parametrize("name", sorted(DATASETS))
def test_labels_are_not_derived_from_tools(name):
    src = open(os.path.join(ROOT, "datasets", name, "generate.py")).read()
    assert "youtube_intelligence" not in src


def test_word_dataset_uses_the_same_labels():
    a = {c["id"].split("-")[0]: c["labels"] for c in json.load(open(os.path.join(DS, "dataset.json")))["cases"]}
    b = json.load(open(os.path.join(ROOT, "datasets", "synthetic-words-v1", "dataset.json")))["cases"]
    assert all(c["labels"] == a[c["id"].split("-")[0]] for c in b)


@pytest.mark.parametrize("name", sorted(DATASETS))
def test_results_match_pinned_baseline(name):
    """Any change in tool behaviour moves these numbers; update baseline + docs deliberately."""
    d = os.path.join(ROOT, "datasets", name)
    base = json.load(open(os.path.join(d, "baseline.json")))
    r = run(os.path.join(d, "dataset.json"))
    assert r["summary"] == base["summary"]
    assert r["cases"] == base["cases"]


def test_known_blind_spots_are_visible():
    s = run(os.path.join(DS, "dataset.json"))["summary"]
    assert s["cuts_recall_by_kind"]["DEAD"] == 1.0
    assert s["cuts_recall_by_kind"]["FILLER"] < 0.5     # inline + auto-caption fillers are missed
    assert s["keep_seconds_cut"] > 0                    # emphasis pauses get cut


def test_cli():
    p = run_cli("youtube_intelligence.evaluation.runner", os.path.join(DS, "dataset.json"))
    assert p.returncode == 0 and "SYNTHETIC" in p.stdout and "OVERALL" in p.stdout
    p = run_cli("youtube_intelligence.evaluation.runner", os.path.join(DS, "dataset.json"), "--json", "--chapters-target", "3")
    assert json.loads(p.stdout)["summary"]["chapters"]["f1"] == 1.0
    assert run_cli("youtube_intelligence.evaluation.runner", "missing.json").returncode == 1
