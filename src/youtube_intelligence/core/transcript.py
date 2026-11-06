"""Timestamped-transcript loading: SRT, WebVTT and Whisper-style JSON.

Adapted from ``load`` / ``parse_ts`` in upstream ``skills/yt-edit/deadair.py``
(youtube-agent-skill, (c) 2026 Jake Schincariol, MIT). Changes, all covered by tests:

* A top-level JSON **array** of segments is accepted. Upstream evaluated ``d.get(...)`` before
  checking ``isinstance(d, list)`` and crashed with ``AttributeError`` (it also broke
  ``chapters.py`` and ``retention.py --transcript``, which import the same loader).
* Malformed JSON, missing ``start``/``end`` keys, non-numeric times and unreadable files raise
  :class:`InputError` instead of a traceback.
* A blank line ends a cue, so WebVTT ``NOTE``/``STYLE`` blocks between cues are no longer glued
  onto the previous cue's text.
* WebVTT inline tags (``<c>``, ``<00:00:01.200>``, ``<v Speaker>``) are stripped from cue text.
* Timestamps with more than three ``:`` parts are rejected instead of being mis-parsed.

Input is treated as untrusted data: it is parsed, never evaluated.
"""
from __future__ import annotations

import json
import os
import re
from typing import List, NamedTuple

from .errors import InputError

TIMING = re.compile(r"\s*(\d[\d:.,]+)\s*-->\s*(\d[\d:.,]+)")
VTT_TAG = re.compile(r"<[^>]*>")
MAX_BYTES = 50 * 1024 * 1024  # a transcript larger than this is not a transcript


class Cue(NamedTuple):
    """One timed caption. A ``tuple`` subclass, so ``start, end, text = cue`` still works."""

    start: float
    end: float
    text: str


def parse_ts(s: str) -> float:
    """Parse ``HH:MM:SS,mmm``, ``HH:MM:SS.mmm`` or ``MM:SS.mmm`` into seconds."""
    p = s.strip().replace(",", ".").split(":")
    try:
        if len(p) == 3:
            return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])
        if len(p) == 2:
            return int(p[0]) * 60 + float(p[1])
    except ValueError:
        pass
    raise InputError(f"unreadable timestamp {s.strip()!r}")


def _read(path: str) -> str:
    if not os.path.isfile(path):
        raise InputError(f"file not found: {path}")
    if os.path.getsize(path) > MAX_BYTES:
        raise InputError(f"{path} is larger than {MAX_BYTES // (1024 * 1024)} MB")
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        return fh.read()


def parse_json_segments(raw: str, source: str = "<json>") -> List[Cue]:
    """Whisper-style JSON: ``{"segments": [...]}`` or a bare ``[...]`` of segments."""
    try:
        d = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputError(f"{source} is not valid JSON ({exc.msg} at line {exc.lineno})") from None
    if isinstance(d, list):
        segs = d
    elif isinstance(d, dict):
        segs = d.get("segments", [])
    else:
        raise InputError(f"{source}: expected a JSON object or array, got {type(d).__name__}")
    if not isinstance(segs, list):
        raise InputError(f"{source}: 'segments' must be a list")
    cues: List[Cue] = []
    for i, s in enumerate(segs):
        if not isinstance(s, dict):
            raise InputError(f"{source}: segment {i} is not an object")
        try:
            start, end = float(s["start"]), float(s["end"])
        except KeyError as exc:
            raise InputError(f"{source}: segment {i} has no {exc.args[0]!r}") from None
        except (TypeError, ValueError):
            raise InputError(f"{source}: segment {i} has a non-numeric start/end") from None
        cues.append(Cue(start, end, str(s.get("text") or "").strip()))
    return cues


def parse_subtitles(raw: str) -> List[Cue]:
    """SRT or WebVTT text into cues. Cues with no text are dropped (as upstream)."""
    cues, cur = [], None
    for line in raw.splitlines():
        m = TIMING.match(line)
        if m:
            cur = [parse_ts(m.group(1)), parse_ts(m.group(2)), []]
            cues.append(cur)
        elif not line.strip():
            cur = None
        elif cur is not None and not line.strip().isdigit():
            text = VTT_TAG.sub("", line).strip()
            if text:
                cur[2].append(text)
    return [Cue(a, b, " ".join(t)) for a, b, t in cues if t]


def load_cues(path: str) -> List[Cue]:
    """Load ``path`` (``.json`` -> Whisper JSON, anything else -> SRT/WebVTT)."""
    raw = _read(path)
    if path.lower().endswith(".json"):
        return parse_json_segments(raw, path)
    return parse_subtitles(raw)


def duration(cues: List[Cue]) -> float:
    """Latest cue end. Upstream used the LAST cue's end, which is wrong when cues overlap."""
    return max((c.end for c in cues), default=0.0)


# Upstream name, kept so ``from deadair import load`` style callers keep working.
load = load_cues
