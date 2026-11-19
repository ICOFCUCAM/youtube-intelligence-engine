"""production-instruction@1: a declarative job for a video engine, built only from approved artefacts.

Operations (closed set; anything else is rejected, never ignored):
  remove_intervals   the EDL's merged ``removed_intervals`` (already excludes held-back cuts)
  extract_clip       one per PICKED Short: start, end, aspect, label
  attach_chapters    validated chapters: start + title

Times are seconds on the transcript's timeline. ``media.transcript_offset_seconds`` tells the
engine how far the media's timeline is shifted from the transcript's; the engine applies it.
The JSON Schema is docs/schemas/production-instruction-1.schema.json; :func:`validate` enforces
it plus the cross-checks a schema cannot express (ordering, overlaps, references to approved
artefacts).
"""
from __future__ import annotations

import math
import re
import uuid
from typing import Any, Dict, List, Optional

from ..core.errors import InputError
from .approval import ApprovalError, entry_for, fingerprint, verify

SCHEMA = "youtube-intelligence/production-instruction@1"
ASPECTS = ("9:16", "16:9", "1:1")
_CONTROL = re.compile(r"[\x00-\x20\x7f]")
_OP_KEYS = {
    "remove_intervals": {"op", "intervals", "source_artifact"},
    "extract_clip": {"op", "start", "end", "aspect", "label", "source_artifact"},
    "attach_chapters": {"op", "chapters", "source_artifact"},
}
_TOP_KEYS = {"schema", "instruction_id", "project", "media", "operations", "approval"}


def _ref(kind: str, sha: str) -> str:
    return f"{kind}:{sha[:16]}"


def _media_ref(ref: Any) -> str:
    if not isinstance(ref, str) or not ref or len(ref) > 500 or _CONTROL.search(ref):
        raise InputError("media ref must be a non-empty string of at most 500 characters, without spaces or control characters")
    return ref


def _num(v: Any, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise InputError(f"{what} must be a finite number")
    return float(v)


def build(approval: Dict, media_ref: str, *, edl: Optional[Dict] = None, chapters: Optional[Dict] = None,
          shorts: Optional[Dict] = None, transcript_offset: float = 0.0, project: Optional[Dict] = None,
          key: Optional[bytes] = None, instruction_id: Optional[str] = None, aspect: str = "9:16") -> Dict:
    """Build an instruction. Every artefact passed must match its approved hash exactly."""
    verify(approval, key)
    provided = {k: v for k, v in (("edl", edl), ("chapters", chapters), ("shorts", shorts)) if v is not None}
    if not provided:
        raise InputError("give at least one approved artefact (edl, chapters or shorts)")
    ops: List[Dict] = []
    for kind, art in provided.items():
        entry = entry_for(approval, kind)
        if entry is None:
            raise ApprovalError(f"the {kind} was not part of this approval")
        if fingerprint(art) != entry["sha256"]:
            raise ApprovalError(f"the {kind} has changed since it was approved - approve it again")
        src = _ref(kind, entry["sha256"])
        if kind == "edl":
            iv = [[float(a), float(b)] for a, b in art["removed_intervals"]]
            if iv:
                ops.append({"op": "remove_intervals", "intervals": iv, "source_artifact": src})
        elif kind == "shorts":
            if aspect not in ASPECTS:
                raise InputError(f"aspect must be one of {', '.join(ASPECTS)}")
            for i in entry["picked"]:
                c = art["candidates"][i - 1]
                ops.append({"op": "extract_clip", "start": float(c["start"]), "end": float(c["end"]),
                            "aspect": aspect, "label": f"short-{i}", "source_artifact": src})
        elif kind == "chapters":
            ch = [{"start": float(c["start"]), "title": str(c.get("title") or c.get("draft_title") or "").strip()}
                  for c in art["chapters"]]
            ops.append({"op": "attach_chapters", "chapters": ch, "source_artifact": src})
    if not ops:
        raise InputError("the approved artefacts produce no operations (nothing to cut, clip or attach)")
    # The executing engine gets the full approval, signature included, so it can verify it itself.
    approval_block = {k: approval[k] for k in ("approved_by", "approved_at", "artifacts", "signature") if k in approval}
    approval_block["acknowledged_review"] = bool(approval.get("acknowledged_review", False))
    instr = {"schema": SCHEMA, "instruction_id": instruction_id or str(uuid.uuid4()),
             "media": {"ref": _media_ref(media_ref), "transcript_offset_seconds": _num(transcript_offset, "transcript offset")},
             "operations": ops, "approval": approval_block}
    if project is not None:
        instr["project"] = project
    validate(instr)
    return instr


def validate(instr: Any) -> None:
    """Structural and semantic checks. Raises InputError naming the first problem."""
    if not isinstance(instr, dict):
        raise InputError("instruction must be a JSON object")
    extra = set(instr) - _TOP_KEYS
    if extra:
        raise InputError(f"unknown top-level field(s): {', '.join(sorted(extra))}")
    if instr.get("schema") != SCHEMA:
        raise InputError(f"schema must be {SCHEMA}")
    try:
        uuid.UUID(str(instr.get("instruction_id")))
    except ValueError:
        raise InputError("instruction_id must be a UUID") from None
    media = instr.get("media")
    if not isinstance(media, dict) or set(media) != {"ref", "transcript_offset_seconds"}:
        raise InputError("media must be {ref, transcript_offset_seconds}")
    _media_ref(media["ref"])
    _num(media["transcript_offset_seconds"], "media.transcript_offset_seconds")
    if "project" in instr and (not isinstance(instr["project"], dict)
                               or not all(isinstance(k, str) and isinstance(v, str) for k, v in instr["project"].items())):
        raise InputError("project must be an object of string ids")
    ap = instr.get("approval")
    if not isinstance(ap, dict) or not ap.get("approved_by") or not ap.get("approved_at") or not ap.get("artifacts"):
        raise InputError("approval is required: approved_by, approved_at, artifacts")
    extra = set(ap) - {"approved_by", "approved_at", "artifacts", "acknowledged_review", "signature"}
    if extra or not isinstance(ap.get("acknowledged_review"), bool):
        raise InputError("approval fields must be approved_by, approved_at, artifacts, acknowledged_review"
                         " and optionally signature")
    approved_refs = {_ref(a.get("kind", ""), str(a.get("sha256", ""))) for a in ap["artifacts"] if isinstance(a, dict)}
    ops = instr.get("operations")
    if not isinstance(ops, list) or not ops:
        raise InputError("operations must be a non-empty list")
    for n, op in enumerate(ops):
        where = f"operations[{n}]"
        if not isinstance(op, dict) or op.get("op") not in _OP_KEYS:
            raise InputError(f"{where}: unknown op {op.get('op') if isinstance(op, dict) else op!r} (allowed: {', '.join(_OP_KEYS)})")
        if set(op) != _OP_KEYS[op["op"]]:
            raise InputError(f"{where}: fields must be exactly {', '.join(sorted(_OP_KEYS[op['op']]))}")
        if op["source_artifact"] not in approved_refs:
            raise InputError(f"{where}: source_artifact {op['source_artifact']!r} is not an approved artefact")
        if op["op"] == "remove_intervals":
            iv = op["intervals"]
            if not isinstance(iv, list) or not iv:
                raise InputError(f"{where}: intervals must be a non-empty list")
            prev = -1.0
            for a in iv:
                if not isinstance(a, list) or len(a) != 2:
                    raise InputError(f"{where}: each interval is [start, end]")
                s, e = _num(a[0], where), _num(a[1], where)
                if s < 0 or e <= s or s < prev:
                    raise InputError(f"{where}: intervals must be non-negative, non-empty, sorted and non-overlapping")
                prev = e
        elif op["op"] == "extract_clip":
            s, e = _num(op["start"], where), _num(op["end"], where)
            if s < 0 or e <= s:
                raise InputError(f"{where}: clip must have 0 <= start < end")
            if op["aspect"] not in ASPECTS:
                raise InputError(f"{where}: aspect must be one of {', '.join(ASPECTS)}")
            if not isinstance(op["label"], str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", op["label"]):
                raise InputError(f"{where}: label must be 1-64 characters of letters, digits, . _ -")
        else:
            ch = op["chapters"]
            if not isinstance(ch, list) or len(ch) < 3:
                raise InputError(f"{where}: YouTube needs at least 3 chapters")
            starts = []
            for c in ch:
                if not isinstance(c, dict) or set(c) != {"start", "title"} or not isinstance(c["title"], str):
                    raise InputError(f"{where}: each chapter is {{start, title}}")
                starts.append(_num(c["start"], where))
            if starts[0] != 0 or any(b - a < 10 for a, b in zip(starts, starts[1:])):
                raise InputError(f"{where}: chapters must start at 0 and be at least 10 s apart")
