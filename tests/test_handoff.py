"""Approval records and production-instruction@1."""
import copy
import json
import os

import jsonschema
import pytest

from conftest import ROOT, fixture, run_cli
from youtube_intelligence.core.errors import InputError
from youtube_intelligence.core.transcript import load_cues
from youtube_intelligence.editing import chapters, deadair
from youtube_intelligence.handoff import approval as A
from youtube_intelligence.handoff import instruction as I
from youtube_intelligence.service import app
from youtube_intelligence.shorts.candidates import find

SCHEMA = json.load(open(os.path.join(ROOT, "docs", "schemas", "production-instruction-1.schema.json")))
KEY = b"k" * 40
CUES = load_cues(fixture("sample.srt"))
UID = "00000000-0000-4000-8000-000000000000"


def arts(hold=True):
    return {"edl": deadair.analyse(CUES, hold_review=hold), "chapters": chapters.build(CUES),
            "shorts": {"candidates": find(CUES, 20, 55, 3)}}


def full(key=None, **kw):
    a = arts()
    ap = A.approve(a, "editor@example.org", picked_shorts=[1, 2], key=key, now=0)
    return a, ap, I.build(ap, "cineforge://asset/1", instruction_id=UID, key=key, **a, **kw)


# --- approval ----------------------------------------------------------------------------------------
def test_approval_pins_hashes_and_time():
    a = arts()
    ap = A.approve(a, "  editor@example.org ", picked_shorts=[2], now=0)
    assert ap["approved_by"] == "editor@example.org" and ap["approved_at"] == "1970-01-01T00:00:00Z"
    assert [x["kind"] for x in ap["artifacts"]] == ["edl", "chapters", "shorts"]
    assert ap["artifacts"][0]["sha256"] == A.fingerprint(a["edl"]) and ap["artifacts"][2]["picked"] == [2]
    assert "signature" not in ap
    assert A.verify(ap) == {"signed": False, "verified": False}


def test_fingerprint_is_order_independent():
    assert A.fingerprint({"a": 1, "b": [1, 2]}) == A.fingerprint({"b": [1, 2], "a": 1})


def test_review_cuts_need_acknowledgement():
    edl = deadair.analyse(load_cues("datasets/synthetic-v1/tutorial-clean.srt"))   # has [review] cuts, not held
    assert A.unheld_review_cuts(edl)
    with pytest.raises(A.ApprovalError, match="marked \\[review\\]"):
        A.approve({"edl": edl}, "ed")
    assert A.approve({"edl": edl}, "ed", acknowledge_review=True)["acknowledged_review"] is True
    held = deadair.analyse(load_cues("datasets/synthetic-v1/tutorial-clean.srt"), hold_review=True)
    assert A.approve({"edl": held}, "ed")["acknowledged_review"] is False


@pytest.mark.parametrize("artifacts,kw,msg", [
    ({}, {}, "nothing to approve"),
    ({"video": {}}, {}, "unknown artefact"),
    ({"edl": {"cuts": []}}, {}, "not a youtube-intelligence/edl@1"),
    ({"chapters": {"valid": False, "chapters": []}}, {}, "break YouTube's rules"),
    ({"shorts": {"candidates": [{}]}}, {}, "numbers of the ones picked"),
    ({"shorts": {"candidates": [{}]}}, {"picked_shorts": [2]}, "between 1 and 1"),
])
def test_approval_rejections(artifacts, kw, msg):
    with pytest.raises(A.ApprovalError, match=msg):
        A.approve(artifacts, "ed", **kw)


@pytest.mark.parametrize("who", ["", "   ", "a\nb", "x" * 201, None])
def test_approver_must_be_named(who):
    with pytest.raises(A.ApprovalError, match="approved_by"):
        A.approve({"chapters": chapters.build(CUES)}, who)


# --- signatures --------------------------------------------------------------------------------------
def test_signed_approval_verifies_and_detects_tampering():
    ap = A.approve({"chapters": chapters.build(CUES)}, "ed", key=KEY, now=0)
    assert ap["signature"].startswith("hmac-sha256:") and A.verify(ap, KEY) == {"signed": True, "verified": True}
    forged = dict(ap, approved_by="someone-else")
    with pytest.raises(A.ApprovalError, match="does not verify"):
        A.verify(forged, KEY)
    with pytest.raises(A.ApprovalError, match="does not verify"):
        A.verify(ap, b"z" * 40)
    with pytest.raises(A.ApprovalError, match="unsigned"):
        A.verify(A.approve({"chapters": chapters.build(CUES)}, "ed"), KEY)


def test_signing_key_from_env():
    assert A.signing_key({}) is None
    with pytest.raises(A.ApprovalError, match="32"):
        A.signing_key({"YIE_APPROVAL_KEY": "short"})
    assert A.signing_key({"YIE_APPROVAL_KEY": "x" * 32}) == b"x" * 32


# --- instructions -----------------------------------------------------------------------------------
def test_instruction_contents():
    a, ap, ins = full()
    ops = {o["op"]: o for o in ins["operations"]}
    assert ops["remove_intervals"]["intervals"] == a["edl"]["removed_intervals"]
    clips = [o for o in ins["operations"] if o["op"] == "extract_clip"]
    assert [c["label"] for c in clips] == ["short-1", "short-2"] and clips[0]["aspect"] == "9:16"
    assert ops["attach_chapters"]["chapters"][0] == {"start": 0.0, "title": a["chapters"]["chapters"][0]["draft_title"]}
    assert ins["approval"]["approved_by"] == "editor@example.org" and ins["instruction_id"] == UID


def test_held_review_cuts_are_not_in_the_instruction():
    a, _, ins = full()
    held = [c for c in a["edl"]["cuts"] if c["review"]]
    assert held, "fixture should contain a review-flagged pause"
    iv = next(o for o in ins["operations"] if o["op"] == "remove_intervals")["intervals"]
    for c in held:
        assert not any(s <= c["start"] and c["end"] <= e for s, e in iv)


def test_artifact_changed_after_approval_is_refused():
    a = arts()
    ap = A.approve(a, "ed", picked_shorts=[1])
    changed = copy.deepcopy(a["edl"])
    changed["removed_intervals"].append([85.0, 86.0])
    with pytest.raises(A.ApprovalError, match="changed since it was approved"):
        I.build(ap, "cineforge://asset/1", edl=changed)
    with pytest.raises(A.ApprovalError, match="not part of this approval"):
        I.build(A.approve({"chapters": a["chapters"]}, "ed"), "cineforge://asset/1", edl=a["edl"])


def test_signed_flow_and_unsigned_refused_when_key_set():
    _, ap, ins = full(key=KEY)
    assert ins["approval"]["signature"] == ap["signature"]
    a = arts()
    unsigned = A.approve(a, "ed", picked_shorts=[1])
    with pytest.raises(A.ApprovalError, match="unsigned"):
        I.build(unsigned, "cineforge://asset/1", key=KEY, **a)


@pytest.mark.parametrize("ref", ["", "has space", "x" * 501, "a\nb"])
def test_bad_media_ref(ref):
    a = arts()
    ap = A.approve(a, "ed", picked_shorts=[1])
    with pytest.raises(InputError, match="media ref"):
        I.build(ap, ref, **a)


# --- schema and validator agree -------------------------------------------------------------------
def test_generated_instructions_match_published_schema():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    for key in (None, KEY):
        _, _, ins = full(key=key)
        jsonschema.validate(ins, SCHEMA)
        I.validate(ins)


def _mutations():
    _, _, base = full()
    def m(f):
        x = copy.deepcopy(base)
        f(x)
        return x
    return [
        ("unknown op", m(lambda x: x["operations"].append({"op": "run_script", "source_artifact": "edl:0"}))),
        ("extra field", m(lambda x: x["operations"][0].update(cmd="rm -rf /"))),
        ("extra top", m(lambda x: x.update(callback="https://example.invalid"))),
        ("no approval", m(lambda x: x.pop("approval"))),
        ("bad schema", m(lambda x: x.update(schema="other@1"))),
        ("negative", m(lambda x: x["operations"][0]["intervals"].insert(0, [-1.0, 0.5]))),
        ("aspect", m(lambda x: next(o for o in x["operations"] if o["op"] == "extract_clip").update(aspect="4:3"))),
        ("chapters", m(lambda x: next(o for o in x["operations"] if o["op"] == "attach_chapters")["chapters"].pop())),
        ("approval extra", m(lambda x: x["approval"].update(role="admin"))),
    ]


@pytest.mark.parametrize("name,bad", _mutations(), ids=[n for n, _ in _mutations()])
def test_malformed_instructions_rejected_by_both(name, bad):
    with pytest.raises(InputError):
        I.validate(bad)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, SCHEMA)


@pytest.mark.parametrize("name,mut", [
    ("overlapping intervals", lambda x: x["operations"][0]["intervals"].insert(1, [0.0, 100.0])),
    ("source not approved", lambda x: x["operations"][0].update(source_artifact="edl:" + "0" * 16)),
    ("chapters too close", lambda x: next(o for o in x["operations"] if o["op"] == "attach_chapters")["chapters"][1].update(start=5.0)),
])
def test_semantic_checks_beyond_the_schema(name, mut):
    _, _, ins = full()
    mut(ins)
    with pytest.raises(InputError):
        I.validate(ins)


# --- CLI and HTTP -----------------------------------------------------------------------------------
def test_cli_flow(tmp_path):
    edl = tmp_path / "edl.json"
    ch = tmp_path / "chapters.json"
    edl.write_text(json.dumps(deadair.analyse(CUES, hold_review=True)))
    ch.write_text(json.dumps(chapters.build(CUES)))
    M = "youtube_intelligence.handoff.cli"
    p = run_cli(M, "approve", "--edl", str(edl), "--chapters", str(ch), "--by", "ed", "--out", str(tmp_path / "ap.json"))
    assert p.returncode == 0 and "UNSIGNED" in p.stderr
    p = run_cli(M, "instruction", "--approval", str(tmp_path / "ap.json"), "--edl", str(edl), "--chapters", str(ch),
                "--media", "cineforge://asset/9", "--out", str(tmp_path / "ins.json"))
    assert p.returncode == 0, p.stderr
    p = run_cli(M, "validate", str(tmp_path / "ins.json"))
    assert p.returncode == 0 and "valid:" in p.stdout and "NOT checked" in p.stdout
    edl.write_text(json.dumps(deadair.analyse(CUES)))           # edit after approval
    p = run_cli(M, "instruction", "--approval", str(tmp_path / "ap.json"), "--edl", str(edl), "--media", "cineforge://a")
    assert p.returncode == 1 and "changed since it was approved" in p.stderr


def test_cli_signed_validate(tmp_path, monkeypatch):
    from youtube_intelligence.handoff.cli import main
    monkeypatch.setenv("YIE_APPROVAL_KEY", "s" * 40)
    ch = tmp_path / "c.json"
    ch.write_text(json.dumps(chapters.build(CUES)))
    assert main(["approve", "--chapters", str(ch), "--by", "ed", "--out", str(tmp_path / "ap.json")]) == 0
    assert main(["instruction", "--approval", str(tmp_path / "ap.json"), "--chapters", str(ch),
                 "--media", "cineforge://x", "--out", str(tmp_path / "i.json")]) == 0
    assert main(["validate", str(tmp_path / "i.json")]) == 0
    ins = json.loads((tmp_path / "i.json").read_text())
    ins["approval"]["approved_by"] = "mallory"
    (tmp_path / "i.json").write_text(json.dumps(ins))
    assert main(["validate", str(tmp_path / "i.json")]) == 1


def test_http_handoff_endpoints():
    a = arts()
    s, ap = app.handle("POST", "/v1/handoff/approve", {"approved_by": "ed", "edl": a["edl"], "shorts": a["shorts"],
                                                       "picked_shorts": [1]})
    assert s == 200 and ap["schema"] == A.SCHEMA
    s, ins = app.handle("POST", "/v1/handoff/instruction", {"approval": ap, "media": "cineforge://asset/2",
                                                            "edl": a["edl"], "shorts": a["shorts"]})
    assert s == 200 and ins["schema"] == I.SCHEMA
    assert app.handle("POST", "/v1/handoff/validate", {"instruction": ins}) == (200, {"valid": True})
    bad = dict(ins, operations=[{"op": "shell"}])
    assert app.handle("POST", "/v1/handoff/validate", {"instruction": bad})[0] == 400
    s, p = app.handle("POST", "/v1/handoff/approve", {"approved_by": "ed", "edl": "x"})
    assert s == 400 and "must be a JSON object" in p["error"]["message"]


def test_openapi_lists_exactly_the_routes():
    s, spec = app.handle("GET", "/v1/openapi.json")
    assert s == 200 and spec["openapi"].startswith("3.1")
    documented = {(m.upper(), p) for p, ops in spec["paths"].items() for m in ops}
    served = {("POST", p) for p in app.POST} | {("GET", p) for p in app.GET}
    assert documented == served
    for p, ops in spec["paths"].items():
        for op in ops.values():
            assert op["summary"] and "200" in op["responses"]
