"""shorts - candidate Shorts spans inside a long video's transcript.

    yt-shorts transcript.srt
    yt-shorts transcript.srt --min 20 --max 55 --top 5 --json

ICOFCUCAM addition (not in upstream). It mechanises the timing half of the upstream /yt-shorts
skill, which asks for spans of 20-55 seconds that (1) open on a complete thought, (2) contain a
turn, and (3) end on a line rather than a trail-off. Those are judgements about meaning; this
tool can only approximate them from surface signals:

  opening   a pause or sentence end before the span, and a first word that is not a connective
            ("and", "but", "so", "because", ...) that leans on the previous minute
  turn      a contrast word inside the span ("but", "however", "turns out", "except", ...)
  ending    terminal punctuation on the last cue, and a pause after it

Auto-generated captions usually have no punctuation, so on those only the pause signals work.
The output is a shortlist for a human (or the /yt-shorts skill) to judge and re-hook; it does
not cut media and does not decide anything.
"""
from __future__ import annotations

import argparse
import json
import re
from typing import Dict, List, Optional, Sequence

from ..core.cli import guarded
from ..core.errors import InputError
from ..core.transcript import Cue, load_cues
from ..editing.deadair import is_filler

CONNECTIVES = {"and", "but", "or", "so", "because", "which", "then", "also", "plus", "anyway",
               "though", "as", "whereas", "nor"}
REFERENTIAL = {"it", "this", "that", "they", "these", "those", "he", "she", "there"}
TURN = re.compile(r"\b(but|however|except|instead|until|turns out|the problem|the catch|actually|"
                  r"the reason|unless|yet)\b", re.I)
TERMINAL = re.compile(r"[.?!…][\"')\]]*\s*$")


def _first_word(t: str) -> str:
    m = re.search(r"[a-z']+", t.lower())
    return m.group(0) if m else ""


def find(cues: Sequence[Cue], min_len: float = 20.0, max_len: float = 55.0, top: int = 5) -> List[Dict]:
    if min_len <= 0 or max_len < min_len:
        raise InputError("need 0 < --min <= --max")
    if top < 1:
        raise InputError("--top must be at least 1")
    n = len(cues)
    ends_before = []
    latest = None
    for c in cues:
        ends_before.append(latest)
        latest = c.end if latest is None else max(latest, c.end)
    scored = []
    for i in range(n):
        s0, _, t0 = cues[i]
        if is_filler(t0) or not t0.strip():
            continue
        gap_before = (s0 - ends_before[i]) if ends_before[i] is not None else 2.0
        prev_terminal = i == 0 or bool(TERMINAL.search(cues[i - 1].text))
        fw = _first_word(t0)
        for j in range(i, n):
            e = cues[j].end
            length = e - s0
            if length > max_len:
                break
            if length < min_len or is_filler(cues[j].text):
                continue
            gap_after = (cues[j + 1].start - e) if j + 1 < n else 2.0
            body = " ".join(c.text for c in cues[i:j + 1])
            later = " ".join(c.text for c in cues[i + 1:j + 1])
            score, why = 0.0, []
            score += min(max(gap_before, 0.0), 2.0)
            score += min(max(gap_after, 0.0), 2.0)
            if prev_terminal:
                score += 1.0
            if fw in CONNECTIVES:
                score -= 3.0
                why.append(f'opens on "{fw}" - needs the previous context')
            elif fw in REFERENTIAL:
                score -= 1.0
                why.append(f'opens on "{fw}" - check what it refers to')
            else:
                why.append("opens on its own words")
            if TURN.search(later):
                score += 1.5
                why.append(f'has a turn ("{TURN.search(later).group(0).lower()}")')
            else:
                why.append("no turn word found")
            if TERMINAL.search(cues[j].text):
                score += 1.5
                why.append("ends on a full stop")
            scored.append({"start": round(s0, 2), "end": round(e, 2), "seconds": round(length, 2),
                           "score": round(score, 2), "first_line": t0, "last_line": cues[j].text,
                           "words": len(body.split()), "notes": why})
    scored.sort(key=lambda c: (-c["score"], c["start"], c["end"]))
    picked: List[Dict] = []
    for c in scored:
        if all(c["end"] <= p["start"] or c["start"] >= p["end"] for p in picked):
            picked.append(c)
            if len(picked) >= top:
                break
    return picked


def render(cands: List[Dict]) -> str:
    if not cands:
        return "\n  no span fits the length window - lower --min or raise --max\n"
    out = [""]
    for k, c in enumerate(cands, 1):
        out.append(f"  {k}. {c['start']:8.2f} -> {c['end']:8.2f}  ({c['seconds']:.1f}s, score {c['score']})")
        out.append(f"     first: {c['first_line'][:90]}")
        out.append(f"     last:  {c['last_line'][:90]}")
        out.append("     " + "; ".join(c["notes"]))
    out.append("\n  A shortlist, not a decision. Every Short still needs a NEW first line (run it through yt-hookscore).\n")
    return "\n".join(out)


@guarded
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="yt-shorts", description=__doc__.split("\n\n")[0])
    p.add_argument("transcript")
    p.add_argument("--min", type=float, default=20.0, dest="min_len")
    p.add_argument("--max", type=float, default=55.0, dest="max_len")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    cues = load_cues(a.transcript)
    if not cues:
        raise InputError("no cues found - is this an srt, vtt or whisper json?")
    c = find(cues, a.min_len, a.max_len, a.top)
    print(json.dumps({"candidates": c}, indent=1) if a.json else render(c))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
