"""Approval records: who approved exactly which artefacts.

An approval pins each artefact by the SHA-256 of its canonical JSON. A production instruction can
only be built from artefacts whose current hash matches, so an EDL edited after approval is
refused instead of silently rendered.

A hash proves INTEGRITY, not IDENTITY: anyone can compute one. When a signing key is configured
(``YIE_APPROVAL_KEY``, 32+ characters, shared with the system that executes instructions) every
approval is HMAC-SHA256 signed and instructions require a valid signature. ``approved_by`` is
whatever the approving system (e.g. TAKE, after authenticating the person) asserts.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional

from ..core.errors import InputError

SCHEMA = "youtube-intelligence/approval@1"
EDL_SCHEMA = "youtube-intelligence/edl@1"
KINDS = ("edl", "chapters", "shorts")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_SIG = re.compile(r"^hmac-sha256:[0-9a-f]{64}$")


class ApprovalError(InputError):
    """The approval is missing, malformed, unsigned when it must be signed, or does not match."""


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def fingerprint(obj: Any) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def signing_key(env: Mapping[str, str] = os.environ) -> Optional[bytes]:
    k = (env.get("YIE_APPROVAL_KEY") or "").strip()
    if not k:
        return None
    if len(k) < 32:
        raise ApprovalError("YIE_APPROVAL_KEY must be at least 32 characters")
    return k.encode("utf-8")


def _sign(record: Dict, key: bytes) -> str:
    body = {k: v for k, v in record.items() if k != "signature"}
    return "hmac-sha256:" + hmac.new(key, canonical(body), hashlib.sha256).hexdigest()


def unheld_review_cuts(edl: Dict) -> List[Dict]:
    """Cuts flagged for review that WILL be applied (the EDL was not built with hold_review)."""
    if edl.get("hold_review"):
        return []
    return [c for c in edl.get("cuts", []) if isinstance(c, dict) and c.get("review")]


def _check_person(approved_by: Any) -> str:
    if not isinstance(approved_by, str) or not approved_by.strip() or len(approved_by) > 200 or _CONTROL.search(approved_by):
        raise ApprovalError("'approved_by' must be a non-empty name or id of at most 200 characters")
    return approved_by.strip()


def approve(artifacts: Mapping[str, Any], approved_by: str, *, acknowledge_review: bool = False,
            picked_shorts: Optional[Iterable[int]] = None, key: Optional[bytes] = None,
            now: Optional[float] = None) -> Dict:
    """Create an approval record for ``artifacts`` ({"edl": ..., "chapters": ..., "shorts": ...})."""
    if not isinstance(artifacts, Mapping) or not artifacts:
        raise ApprovalError("nothing to approve")
    unknown = set(artifacts) - set(KINDS)
    if unknown:
        raise ApprovalError(f"unknown artefact kind(s): {', '.join(sorted(unknown))}")
    who = _check_person(approved_by)
    entries = []
    for kind in KINDS:
        if kind not in artifacts:
            continue
        art = artifacts[kind]
        if not isinstance(art, dict):
            raise ApprovalError(f"{kind} must be a JSON object")
        entry: Dict[str, Any] = {"kind": kind, "sha256": fingerprint(art)}
        if kind == "edl":
            if art.get("schema") != EDL_SCHEMA or not isinstance(art.get("removed_intervals"), list):
                raise ApprovalError(f"the edl is not a {EDL_SCHEMA} document (run yt-deadair --json)")
            flagged = unheld_review_cuts(art)
            if flagged and not acknowledge_review:
                raise ApprovalError(f"the edl applies {len(flagged)} pause cut(s) marked [review]; listen to them and "
                                    "approve with acknowledge_review, or rebuild the edl with --hold-review")
        if kind == "chapters" and art.get("valid") is not True:
            raise ApprovalError("these chapters break YouTube's rules (valid is not true); fix them before approving")
        if kind == "shorts":
            cands = art.get("candidates")
            picks = sorted(set(picked_shorts or []))
            if not isinstance(cands, list) or not picks:
                raise ApprovalError("approving shorts needs the candidates and the numbers of the ones picked")
            if any(not isinstance(i, int) or not 1 <= i <= len(cands) for i in picks):
                raise ApprovalError(f"picked shorts must be between 1 and {len(cands)}")
            entry["picked"] = picks
        entries.append(entry)
    t = time.gmtime(time.time() if now is None else now)
    record = {"schema": SCHEMA, "approved_by": who, "approved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", t),
              "artifacts": entries, "acknowledged_review": bool(acknowledge_review)}
    if key:
        record["signature"] = _sign(record, key)
    return record


def verify(record: Any, key: Optional[bytes] = None) -> Dict:
    """Validate an approval record. With a key, a valid signature is REQUIRED."""
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        raise ApprovalError(f"not a {SCHEMA} record")
    _check_person(record.get("approved_by"))
    if not isinstance(record.get("approved_at"), str) or not _ISO_Z.match(record["approved_at"]):
        raise ApprovalError("'approved_at' must be a UTC timestamp like 2026-11-19T12:00:00Z")
    arts = record.get("artifacts")
    if not isinstance(arts, list) or not arts:
        raise ApprovalError("the approval covers no artefacts")
    seen = set()
    for a in arts:
        if (not isinstance(a, dict) or a.get("kind") not in KINDS or a["kind"] in seen
                or not re.fullmatch(r"[0-9a-f]{64}", str(a.get("sha256", "")))):
            raise ApprovalError("malformed artefact entry in the approval")
        seen.add(a["kind"])
    sig = record.get("signature")
    if sig is not None and not (isinstance(sig, str) and _SIG.match(sig)):
        raise ApprovalError("malformed signature")
    if key:
        if sig is None:
            raise ApprovalError("this approval is unsigned, but a signing key is configured - unsigned approvals are refused")
        if not hmac.compare_digest(sig, _sign(record, key)):
            raise ApprovalError("approval signature does not verify - the record was altered or signed with another key")
    return {"signed": sig is not None, "verified": bool(key)}


def entry_for(record: Dict, kind: str) -> Optional[Dict]:
    return next((a for a in record["artifacts"] if a["kind"] == kind), None)
