"""chapters - YouTube chapters from a timestamped transcript.

    yt-chapters transcript.srt            # or .vtt / whisper .json (object or array)
    yt-chapters transcript.srt --target 8 --json

Prints a description block you can paste straight under a video. YouTube's own rules, enforced here
rather than assumed: the list must start at 00:00, needs at least three entries, and each chapter
must be at least 10 seconds long. A block that breaks any of those silently does not become
chapters, which is why this checks instead of trusting.

Boundaries come from the gaps - the pauses you actually took between sections - scored by how long
the pause was and how much the vocabulary changes across it. It is a first draft you retitle, not a
summariser.

Adapted from upstream skills/yt-chapters/chapters.py (youtube-agent-skill, (c) 2026 Jake
Schincariol, MIT). Boundary selection is unchanged. ICOFCUCAM changes: it inherited the
JSON-array crash from the shared transcript loader (fixed in youtube_intelligence.core.transcript);
draft titles are now deterministic (upstream ordered tied keywords by hash-randomised set order,
so titles changed between runs); duration is the latest cue end; bad input exits 1 with a message.
"""
from __future__ import annotations

import argparse
import json
import re
from typing import Dict, List, Optional, Sequence

from ..core.cli import guarded
from ..core.errors import InputError
from ..core.transcript import Cue, duration, load_cues

MIN_SECONDS = 10.0
MIN_CHAPTERS = 3
STOP = set("the a an of for to in on and or is are was were be been with this that it as at by from "
           "you your i my we our they them he she but so if then than there here what which who how "
           "when where why not no yes do does did just really very like about into over out up down "
           "can could will would should have has had get got make made go going went one two".split())


def keywords(text: str) -> set:
    return {w for w in re.findall(r"[a-z']{4,}", text.lower()) if w not in STOP}


def mmss(t: float) -> str:
    t = int(t)
    h, m, s = t // 3600, (t % 3600) // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def is_valid(chapters: List[Dict]) -> bool:
    return (len(chapters) >= MIN_CHAPTERS and chapters[0]["start"] == 0
            and all(c["seconds"] >= MIN_SECONDS for c in chapters))


def build(cues: Sequence[Cue], target: int = 7) -> Dict:
    if target < 1:
        raise InputError("--target must be at least 1")
    if len(cues) < 6:
        raise InputError("too few cues to chapter (need at least 6)")
    dur = duration(list(cues))
    cand = []
    for i in range(1, len(cues)):
        gap = cues[i][0] - cues[i - 1][1]
        before = " ".join(c[2] for c in cues[max(0, i - 12):i])
        after = " ".join(c[2] for c in cues[i:i + 12])
        kb, ka = keywords(before), keywords(after)
        shift = 1 - (len(kb & ka) / len(kb | ka)) if (kb | ka) else 0
        cand.append((gap * 1.6 + shift * 3.2, cues[i][0], i))
    cand.sort(reverse=True)
    picked = [0.0]
    for _, t, _i in cand:
        if len(picked) >= target:
            break
        if all(abs(t - p) >= MIN_SECONDS for p in picked) and dur - t >= MIN_SECONDS:
            picked.append(t)
    picked.sort()
    chapters = []
    for n, t in enumerate(picked):
        end = picked[n + 1] if n + 1 < len(picked) else dur
        text = " ".join(c[2] for c in cues if c[0] >= t and c[1] <= end)
        low = text.lower()
        # Ties broken by first appearance. Upstream left ties in set-iteration order, which Python
        # randomises per process, so the same transcript produced different titles on every run.
        kw = sorted(keywords(text), key=lambda w: (-low.count(w), low.find(w)))
        title = " ".join(w.capitalize() for w in kw[:3]) or "Section"
        chapters.append({"start": round(t, 2), "label": mmss(t), "draft_title": title,
                         "seconds": round(end - t, 2)})
    return {"valid": is_valid(chapters), "chapters": chapters}


def render(r: Dict) -> str:
    out = [""] + [f"  {c['label']} {c['draft_title']}" for c in r["chapters"]]
    bad = "" if r["valid"] else "  -- INVALID: YouTube needs 3+, a 00:00 first entry and 10s minimum each"
    out.append(f"\n  {len(r['chapters'])} chapters{bad}")
    out.append("  Retitle every line before pasting. These are the topic words, not your words.\n")
    return "\n".join(out)


@guarded
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="yt-chapters", description=__doc__.split("\n\n")[0])
    p.add_argument("transcript")
    p.add_argument("--target", type=int, default=7, help="maximum number of chapters (default 7)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    r = build(load_cues(a.transcript), a.target)
    print(json.dumps(r, indent=1) if a.json else render(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
