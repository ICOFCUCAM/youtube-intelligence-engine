"""Routing and validation, independent of HTTP: ``handle(method, path, body) -> (status, payload)``.

Every request body is untrusted. Fields are type- and range-checked here; anything the library
rejects comes back as ``400 invalid_input`` with the library's message. Unexpected failures are
``500 internal_error`` with a generic message (details go to the server log, never the client).
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import __version__
from ..analytics import retention
from ..core.errors import InputError
from ..core.transcript import NO_WORDS, Cue, FORMATS, parse_transcript
from ..creative import hookscore
from ..editing import chapters, deadair
from ..handoff import approval as handoff_approval
from ..handoff import instruction as handoff_instruction
from ..packaging import title
from ..research import outliers
from ..shorts import candidates

MAX_ITEMS = {"hooks": 500, "titles": 500, "videos": 20000, "cues": 100000, "rows": 100000}

Payload = Dict[str, Any]


class BadRequest(InputError):
    pass


# --- field helpers ---------------------------------------------------------------------------------
def _obj(body: Any) -> Dict:
    if not isinstance(body, dict):
        raise BadRequest("request body must be a JSON object")
    return body


def _num(body: Dict, key: str, default=None, lo=None, hi=None, integer=False):
    v = body.get(key, default)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise BadRequest(f"'{key}' must be a number")
    if integer and int(v) != v:
        raise BadRequest(f"'{key}' must be a whole number")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise BadRequest(f"'{key}' must be between {lo} and {hi}")
    return int(v) if integer else float(v)


def _str_list(body: Dict, key: str) -> List[str]:
    v = body.get(key)
    if not isinstance(v, list) or not v or not all(isinstance(x, str) for x in v):
        raise BadRequest(f"'{key}' must be a non-empty list of strings")
    if len(v) > MAX_ITEMS[key]:
        raise BadRequest(f"'{key}' has more than {MAX_ITEMS[key]} items")
    return v


def _choice(body: Dict, key: str, options, default):
    v = body.get(key, default)
    if v not in options:
        raise BadRequest(f"'{key}' must be one of {', '.join(map(str, options))}")
    return v


def _transcript(body: Dict, need_words: bool = False):
    t = body.get("transcript")
    if not isinstance(t, dict):
        raise BadRequest("'transcript' must be an object: {\"format\": \"srt|vtt|json\", \"content\": \"...\"} "
                         "or {\"cues\": [{\"start\", \"end\", \"text\"}]}")
    if "cues" in t:
        raw = t["cues"]
        if not isinstance(raw, list) or len(raw) > MAX_ITEMS["cues"]:
            raise BadRequest(f"'transcript.cues' must be a list of at most {MAX_ITEMS['cues']} cues")
        cues = []
        for i, c in enumerate(raw):
            if not isinstance(c, dict):
                raise BadRequest(f"cue {i} must be an object")
            a, b = _num(c, "start"), _num(c, "end")
            if a is None or b is None or not isinstance(c.get("text", ""), str):
                raise BadRequest(f"cue {i} needs numeric start/end and string text")
            cues.append(Cue(a, b, c.get("text", "").strip()))
        return cues, NO_WORDS
    fmt = t.get("format")
    if fmt not in FORMATS:
        raise BadRequest(f"'transcript.format' must be one of {', '.join(FORMATS)}")
    return parse_transcript(t.get("content"), fmt, "transcript")


# --- endpoints -------------------------------------------------------------------------------------
def edl(body: Dict) -> Payload:
    cues, words = _transcript(body)
    if not cues:
        raise BadRequest("no cues found in transcript")
    if _choice(body, "words", ("auto", "off"), "auto") == "off":
        words = NO_WORDS
    hold = body.get("hold_review", False)
    if not isinstance(hold, bool):
        raise BadRequest("'hold_review' must be true or false")
    return deadair.analyse(cues, _num(body, "floor", deadair.DEFAULT_FLOOR, 0, 30), "",
                           words, _num(body, "review_below", deadair.REVIEW_BELOW, 0, 60), hold)


def chapter_list(body: Dict) -> Payload:
    cues, _ = _transcript(body)
    return chapters.build(cues, _num(body, "target", None, 1, 100, integer=True))


def hooks(body: Dict) -> Payload:
    rows = hookscore.evaluate(_str_list(body, "hooks"))
    return {"results": [{k: v for k, v in r.items() if k != "matched"} for r in rows],
            "disclaimer": hookscore.DISCLAIMER}


def titles(body: Dict) -> Payload:
    thumb = body.get("thumb")
    if thumb is not None and not isinstance(thumb, str):
        raise BadRequest("'thumb' must be a string")
    rows = [title.check(t, thumb) for t in _str_list(body, "titles")]
    rows.sort(key=lambda r: -r["score"])
    return {"results": rows}


def retention_report(body: Dict) -> Payload:
    if "csv" in body:
        if not isinstance(body["csv"], str):
            raise BadRequest("'csv' must be a string")
        rows, hint = retention.parse_csv_text(body["csv"])
    elif "rows" in body:
        raw = body["rows"]
        if not isinstance(raw, list) or len(raw) > MAX_ITEMS["rows"]:
            raise BadRequest(f"'rows' must be a list of at most {MAX_ITEMS['rows']} [position, percent] pairs")
        rows, hint = [], None
        for i, r in enumerate(raw):
            if (not isinstance(r, list) or len(r) != 2
                    or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in r)):
                raise BadRequest(f"row {i} must be [position, percent]")
            rows.append((float(r[0]), float(r[1])))
    else:
        raise BadRequest("send 'csv' (Studio export text) or 'rows' ([[position, percent], ...])")
    views = _num(body, "views", None, 0, None, integer=True)
    r = retention.analyse(rows, _num(body, "duration", None, 0.001, 86400 * 2),
                          _choice(body, "axis", ("auto", "percent", "seconds"), "auto"), hint, views)
    if "transcript" in body:
        cues, _ = _transcript(body)
        retention.attach_cues(r, cues)
    return r


def outlier_rank(body: Dict) -> Payload:
    vids = body.get("videos")
    if not isinstance(vids, list) or len(vids) > MAX_ITEMS["videos"]:
        raise BadRequest(f"'videos' must be a list of at most {MAX_ITEMS['videos']} objects")
    r = outliers.rank(vids, _num(body, "min", 1.5, 0, 1e6))
    r["skipped_thin_channels"] = [{"channel": c, "videos": n} for c, n in r["skipped_thin_channels"]]
    return r


def shorts(body: Dict) -> Payload:
    cues, _ = _transcript(body)
    return {"candidates": candidates.find(cues, _num(body, "min", 20.0, 1, 600), _num(body, "max", 55.0, 1, 600),
                                          _num(body, "top", 5, 1, 50, integer=True))}


def _artifact(body: Dict, kind: str):
    v = body.get(kind)
    if v is not None and not isinstance(v, dict):
        raise BadRequest(f"'{kind}' must be a JSON object")
    return v


def approve(body: Dict) -> Payload:
    """``approved_by`` is asserted by the caller (e.g. TAKE after authenticating the person)."""
    arts = {k: v for k in handoff_approval.KINDS if (v := _artifact(body, k)) is not None}
    picked = body.get("picked_shorts")
    if picked is not None and (not isinstance(picked, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in picked)):
        raise BadRequest("'picked_shorts' must be a list of whole numbers")
    ack = body.get("acknowledge_review", False)
    if not isinstance(ack, bool):
        raise BadRequest("'acknowledge_review' must be true or false")
    return handoff_approval.approve(arts, body.get("approved_by"), acknowledge_review=ack, picked_shorts=picked,
                                    key=handoff_approval.signing_key())


def instruction(body: Dict) -> Payload:
    if not isinstance(body.get("approval"), dict):
        raise BadRequest("'approval' must be the approval record")
    offset = _num(body, "transcript_offset", 0.0, -86400, 86400)
    project = body.get("project")
    if project is not None and (not isinstance(project, dict) or not all(isinstance(v, str) for v in project.values())):
        raise BadRequest("'project' must be an object of string ids")
    return handoff_instruction.build(body["approval"], body.get("media"), edl=_artifact(body, "edl"),
                                     chapters=_artifact(body, "chapters"), shorts=_artifact(body, "shorts"),
                                     transcript_offset=offset, project=project, key=handoff_approval.signing_key(),
                                     aspect=_choice(body, "aspect", handoff_instruction.ASPECTS, "9:16"))


def validate_instruction(body: Dict) -> Payload:
    handoff_instruction.validate(body.get("instruction"))
    return {"valid": True}


def health(_body: Optional[Dict] = None) -> Payload:
    return {"status": "ok", "service": "youtube-intelligence-engine", "version": __version__,
            "writes_to_youtube": False}


POST: Dict[str, Callable[[Dict], Payload]] = {
    "/v1/edl": edl, "/v1/chapters": chapter_list, "/v1/hooks/score": hooks, "/v1/titles/check": titles,
    "/v1/retention": retention_report, "/v1/outliers": outlier_rank, "/v1/shorts": shorts,
    "/v1/handoff/approve": approve, "/v1/handoff/instruction": instruction,
    "/v1/handoff/validate": validate_instruction,
}


def openapi(_body: Optional[Dict] = None) -> Payload:
    from .openapi import spec
    return spec()


GET: Dict[str, Callable] = {"/v1/health": health, "/v1/openapi.json": openapi}


def error(status: int, code: str, message: str) -> Tuple[int, Payload]:
    return status, {"error": {"code": code, "message": message}}


def handle(method: str, path: str, body: Any = None, log: Callable[[str], None] = lambda m: None) -> Tuple[int, Payload]:
    path = path.split("?", 1)[0].rstrip("/") or "/"
    routes = GET if method == "GET" else POST if method == "POST" else {}
    if path not in routes:
        if path in GET or path in POST:
            return error(405, "method_not_allowed", f"{method} is not allowed on {path}")
        return error(404, "not_found", f"no endpoint {path}")
    try:
        return 200, routes[path](_obj(body) if method == "POST" else None)
    except InputError as exc:
        return error(400, "invalid_input", str(exc))
    except Exception as exc:  # noqa: BLE001 - never leak internals to the client
        log(f"internal error on {path}: {type(exc).__name__}: {exc}")
        return error(500, "internal_error", "the request could not be processed")
