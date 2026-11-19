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

Word timings (ICOFCUCAM addition, :func:`load_words`): read from Whisper JSON ``words`` arrays
(exact start and end) and from YouTube auto-caption WebVTT inline tags
(``word<00:00:01.120><c> next</c>``, start times only). YouTube's "rolling" auto-caption files
repeat every line in a second cue and add 10 ms transition cues; when a file carries inline word
tags, :func:`parse_subtitles` drops those repeated lines so each line of speech appears once.

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
WORD_TAG = re.compile(r"<(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})>")
MAX_BYTES = 50 * 1024 * 1024  # a transcript larger than this is not a transcript


class Cue(NamedTuple):
    """One timed caption. A ``tuple`` subclass, so ``start, end, text = cue`` still works."""

    start: float
    end: float
    text: str


class Word(NamedTuple):
    """One timed word. ``end`` is exact for Whisper; for YouTube VTT it is the next word's start."""

    start: float
    end: float
    text: str


class WordTrack(NamedTuple):
    words: List[Word]
    exact_ends: bool   # True when the source gives real word ends (Whisper), so gaps are real

    @property
    def available(self) -> bool:
        return bool(self.words)


NO_WORDS = WordTrack([], False)


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


def _cue_blocks(raw: str):
    """Yield ``(start, end, [raw text lines])`` for every cue block."""
    cur = None
    for line in raw.splitlines():
        m = TIMING.match(line)
        if m:
            if cur is not None:
                yield cur
            cur = (parse_ts(m.group(1)), parse_ts(m.group(2)), [])
        elif line.rstrip("\r") == "":
            # Only a truly EMPTY line ends a cue (WebVTT/SRT rule). YouTube auto-captions put a
            # single-space line INSIDE cues; treating it as an end dropped the next line's words.
            if cur is not None:
                yield cur
            cur = None
        elif cur is not None and line.strip() and not line.strip().isdigit():
            cur[2].append(line)
    if cur is not None:
        yield cur


def parse_subtitles(raw: str) -> List[Cue]:
    """SRT or WebVTT text into cues. Cues with no text are dropped (as upstream).

    YouTube rolling auto-captions (detected by inline word tags) are de-duplicated: a line equal
    to the previously emitted line is a repeat, not new speech.
    """
    rolling = bool(WORD_TAG.search(raw))
    cues, last = [], None
    for a, b, lines in _cue_blocks(raw):
        texts = []
        for ln in lines:
            t = VTT_TAG.sub("", ln).strip()
            if not t:
                continue
            if rolling:
                if t == last:
                    continue
                last = t
            texts.append(t)
        if texts:
            cues.append(Cue(a, b, " ".join(texts)))
    return cues


def _youtube_words(raw: str) -> List[Word]:
    """Words from lines carrying inline timestamps. A word ends where the next one starts."""
    starts: List[Word] = []
    for a, b, lines in _cue_blocks(raw):
        for ln in lines:
            if not WORD_TAG.search(ln):
                continue
            parts = WORD_TAG.split(ln)          # [text0, ts1, text1, ts2, text2, ...]
            seq = [(a, parts[0])] + [(parse_ts(parts[i]), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
            for t0, txt in seq:
                w = VTT_TAG.sub("", txt).strip()
                if w:
                    starts.append(Word(t0, b, w))
    starts.sort(key=lambda w: w.start)
    out: List[Word] = []
    for i, w in enumerate(starts):
        nxt = starts[i + 1].start if i + 1 < len(starts) else w.end
        out.append(Word(w.start, max(w.start, min(w.end, nxt)), w.text))
    return out


def _json_words(raw: str, source: str) -> List[Word]:
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        return []
    segs = d if isinstance(d, list) else d.get("segments", []) if isinstance(d, dict) else []
    out: List[Word] = []
    for s in segs if isinstance(segs, list) else []:
        for w in (s.get("words") or []) if isinstance(s, dict) else []:
            if not isinstance(w, dict):
                continue
            try:
                a, b = float(w["start"]), float(w["end"])
            except (KeyError, TypeError, ValueError):
                continue        # WhisperX leaves some tokens (numerals) untimed; skip them
            text = str(w.get("word", w.get("text", ""))).strip()
            if text and b >= a:
                out.append(Word(a, b, text))
    out.sort(key=lambda w: w.start)
    return out


def load_words(path: str) -> WordTrack:
    """Word timings for ``path`` if the format carries them, else an empty track."""
    raw = _read(path)
    if path.lower().endswith(".json"):
        return WordTrack(_json_words(raw, path), True)
    if WORD_TAG.search(raw):
        return WordTrack(_youtube_words(raw), False)
    return NO_WORDS


FORMATS = ("srt", "vtt", "json")


def parse_transcript(content: str, fmt: str, source: str = "<transcript>"):
    """Parse transcript TEXT (not a path) -> ``(cues, WordTrack)``. ``fmt`` is srt, vtt or json.

    Used by the HTTP service, which accepts content only, so callers can never make it read a file.
    """
    if fmt not in FORMATS:
        raise InputError(f"transcript format must be one of {', '.join(FORMATS)}")
    if not isinstance(content, str):
        raise InputError("transcript content must be a string")
    if len(content.encode("utf-8", "replace")) > MAX_BYTES:
        raise InputError(f"transcript is larger than {MAX_BYTES // (1024 * 1024)} MB")
    if fmt == "json":
        return parse_json_segments(content, source), WordTrack(_json_words(content, source), True)
    words = WordTrack(_youtube_words(content), False) if WORD_TAG.search(content) else NO_WORDS
    return parse_subtitles(content), words


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
