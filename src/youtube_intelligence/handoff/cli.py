"""yt-handoff - approve artefacts and build a production instruction for a video engine.

    yt-deadair talk.srt --hold-review --json > edl.json
    yt-chapters talk.srt --json > chapters.json            # retitle the chapters first
    yt-handoff approve --edl edl.json --chapters chapters.json --by "editor@example.org" --out approval.json
    yt-handoff instruction --approval approval.json --edl edl.json --chapters chapters.json \\
        --media cineforge://asset/123 --out instruction.json
    yt-handoff validate instruction.json

With YIE_APPROVAL_KEY set (32+ characters, shared with the executing engine) approvals are signed
and instructions require a valid signature. Nothing here sends anything anywhere.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from ..core.cli import guarded
from ..core.errors import InputError
from . import approval as A
from . import instruction as I


def _load(path: Optional[str]):
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise InputError(f"file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise InputError(f"{path} is not valid JSON ({exc.msg} at line {exc.lineno})") from None


def _emit(obj, out: Optional[str], what: str) -> None:
    text = json.dumps(obj, indent=1) + "\n"
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {what} to {out}", file=sys.stderr)
    else:
        sys.stdout.write(text)


@guarded
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="yt-handoff", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    ap = sub.add_parser("approve", help="record who approved exactly which artefacts")
    ap.add_argument("--edl")
    ap.add_argument("--chapters")
    ap.add_argument("--shorts", help="yt-shorts --json output")
    ap.add_argument("--pick", help="comma-separated numbers of the Shorts to approve, e.g. 1,3")
    ap.add_argument("--by", required=True, help="who approved (name or user id)")
    ap.add_argument("--acknowledge-review", action="store_true",
                    help="confirm the [review] pause cuts were listened to and should be applied")
    ap.add_argument("--out")
    ins = sub.add_parser("instruction", help="build production-instruction@1 from approved artefacts")
    ins.add_argument("--approval", required=True)
    ins.add_argument("--media", required=True, help="the engine's media reference, e.g. cineforge://asset/123")
    ins.add_argument("--edl")
    ins.add_argument("--chapters")
    ins.add_argument("--shorts")
    ins.add_argument("--offset", type=float, default=0.0, help="media timeline offset from the transcript, seconds")
    ins.add_argument("--aspect", default="9:16", choices=I.ASPECTS)
    ins.add_argument("--out")
    va = sub.add_parser("validate", help="check an instruction (and its signature when YIE_APPROVAL_KEY is set)")
    va.add_argument("instruction")
    a = p.parse_args(argv)
    key = A.signing_key()
    if a.cmd == "approve":
        arts = {k: _load(getattr(a, k)) for k in ("edl", "chapters", "shorts") if getattr(a, k)}
        picks = None
        if a.pick:
            try:
                picks = [int(x) for x in a.pick.split(",") if x.strip()]
            except ValueError:
                raise InputError("--pick takes numbers like 1,3") from None
        rec = A.approve(arts, a.by, acknowledge_review=a.acknowledge_review, picked_shorts=picks, key=key)
        _emit(rec, a.out, "approval" + (" (signed)" if key else " (UNSIGNED - set YIE_APPROVAL_KEY to sign)"))
        return 0
    if a.cmd == "instruction":
        instr = I.build(_load(a.approval), a.media, edl=_load(a.edl), chapters=_load(a.chapters),
                        shorts=_load(a.shorts), transcript_offset=a.offset, key=key, aspect=a.aspect)
        _emit(instr, a.out, f"instruction {instr['instruction_id']} ({len(instr['operations'])} operations)")
        return 0
    instr = _load(a.instruction)
    I.validate(instr)
    if key:
        sig = instr["approval"].get("signature")
        rec = dict(instr["approval"], schema=A.SCHEMA)
        rec.pop("signature", None)
        if sig is None:
            raise A.ApprovalError("instruction approval is unsigned, but a signing key is configured")
        rec["signature"] = sig
        A.verify(rec, key)
    print(f"valid: {instr['instruction_id']}, {len(instr['operations'])} operation(s), "
          f"approved by {instr['approval']['approved_by']}"
          + (", signature verified" if key else ", signature NOT checked (no YIE_APPROVAL_KEY)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
