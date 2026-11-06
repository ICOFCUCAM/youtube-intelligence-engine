"""deadair - an edit decision list from a timestamped transcript.

    yt-deadair transcript.srt            # or .vtt, or whisper .json (object or array)
    yt-deadair transcript.srt --floor 0.35 --json

Finds three things and prints the cuts in timeline order:
  DEAD    gaps between spoken cues longer than the floor
  FILLER  cues that are only filler ("um", "so yeah", "basically")
  REPEAT  a sentence restarted - the earlier take of the same opening

WHAT IT DOES NOT DO. It does not cut the file. It prints an EDL, the total it would remove, and the
runtime you would land on, and you apply it in whatever editor you use. Nothing here touches media.

Adapted from upstream skills/yt-edit/deadair.py (youtube-agent-skill, (c) 2026 Jake Schincariol,
MIT). ICOFCUCAM changes - see CHANGELOG.md, each has a regression test:
  * removed time is the UNION of the cuts, so overlapping cuts are no longer double-counted
    (upstream could report more removed than the video's length);
  * a dead gap is measured from the latest end of ANY earlier cue, not just the previous one, so
    a gap can never be cut through speech when cues overlap or nest;
  * filler cues may carry ? ! ; : ... or quotes ("Um?", "Okay!"), and "erm", "hmm", "mm" count;
  * a restart is also found when the abandoned take was only 3-4 words, and when either take
    opens with a disfluency ("um so the thing" / "so the thing is");
  * duration is the latest cue end, not the last cue's end; a zero-length input cannot divide
    by zero.
"""
from __future__ import annotations

import argparse
import json
import re
from typing import Dict, List, Optional, Sequence

from ..core.cli import guarded
from ..core.errors import InputError
from ..core.intervals import merge_intervals
from ..core.transcript import Cue, duration, load_cues

SCHEMA = "youtube-intelligence/edl@1"
DEFAULT_FLOOR = 0.45

_WORDS = (r"um+|uhm+|uh+|erm+|er+|ah+|hm+|mm+|so|okay|ok|right|yeah|like|anyway|basically|"
          r"actually|you know|i mean|let me see|hold on")
_SEP = r"[\s,.!?;:…\"'()\[\]-]"
# Each filler word must end on a word boundary. Besides being correct ("umso" is not two fillers)
# that makes the split of a run like "ummmmm" unique, so the nested repeat cannot backtrack
# exponentially on adversarial input.
FILLER_ONLY = re.compile(rf"^{_SEP}*(?:(?:{_WORDS})\b{_SEP}*)+$", re.I)
DISFLUENCY = {"um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "hm", "hmm", "mm", "mmm"}


def is_filler(text: str) -> bool:
    return bool(FILLER_ONLY.match(text))


def norm(t: str) -> List[str]:
    """Lower-case words with punctuation removed (upstream behaviour)."""
    return re.sub(r"[^a-z ]", "", t.lower()).split()


def _opening(t: str) -> List[str]:
    w = norm(t)
    while w and w[0] in DISFLUENCY:
        w.pop(0)
    return w


def is_restart(earlier: str, later: str) -> bool:
    """True when ``later`` re-opens with the first words of ``earlier``.

    Up to five opening words of the earlier take are compared; at least three are required.
    Upstream compared ``earlier[:5] == later[:5]``, which missed an abandoned 3-4 word take
    followed by the full sentence. Every restart upstream found is still found.
    """
    a1 = _opening(earlier)[:5]
    b1 = _opening(later)[: len(a1)]
    return len(a1) >= 3 and a1 == b1


def find_cuts(cues: Sequence[Cue], floor: float = DEFAULT_FLOOR) -> List[Dict]:
    if floor < 0:
        raise InputError("--floor must be zero or more")
    cuts: List[Dict] = []
    prev_end: Optional[float] = None
    for i, (s, e, t) in enumerate(cues):
        if is_filler(t):
            cuts.append({"kind": "FILLER", "start": s, "end": e, "why": t.strip()[:48]})
        if prev_end is not None:
            gap = s - prev_end
            if gap > floor:
                keep = floor / 2
                cuts.append({"kind": "DEAD", "start": round(prev_end + keep, 3),
                             "end": round(s - keep, 3), "why": f"{gap:.2f}s gap"})
        prev_end = e if prev_end is None else max(prev_end, e)
        # A restart is compared against the last cue that was actually SPEECH. Comparing against
        # the literal previous cue misses every retake with an "um" between the two attempts.
        if t.strip() and not is_filler(t):
            j = i - 1
            while j >= 0 and (is_filler(cues[j][2]) or not cues[j][2].strip()):
                j -= 1
            if j >= 0 and is_restart(cues[j][2], t):
                cuts.append({"kind": "REPEAT", "start": cues[j][0], "end": cues[j][1],
                             "why": f'restart of "{" ".join(_opening(cues[j][2])[:5])}"'})
    cuts = [c for c in cuts if c["end"] > c["start"]]
    cuts.sort(key=lambda c: c["start"])
    return cuts


def analyse(cues: Sequence[Cue], floor: float = DEFAULT_FLOOR, source: str = "") -> Dict:
    """The full report. ``removed`` counts overlapping cut time once."""
    dur = duration(list(cues))
    cuts = find_cuts(cues, floor)
    merged = merge_intervals((c["start"], c["end"]) for c in cuts)
    removed = sum(e - s for s, e in merged)
    raw = sum(c["end"] - c["start"] for c in cuts)
    return {"schema": SCHEMA, "source": source, "duration": dur, "floor": floor, "cuts": cuts,
            "removed": round(removed, 3), "out": round(max(0.0, dur - removed), 3),
            "removed_intervals": [[round(s, 3), round(e, 3)] for s, e in merged],
            "overlap_counted_once": round(raw - removed, 3)}


def render(r: Dict, n_cues: int) -> str:
    dur, removed = r["duration"], r["removed"]
    lines = [f"\n  {r['source']}   {dur:.2f}s in, {n_cues} cues, dead-air floor {r['floor']}s\n"]
    for c in r["cuts"]:
        lines.append(f"    {c['kind']:<7} {c['start']:8.2f} -> {c['end']:8.2f}   "
                     f"{c['end'] - c['start']:5.2f}s   {c['why']}")
    pct = removed / dur * 100 if dur > 0 else 0.0
    lines.append(f"\n  {len(r['cuts'])} cuts, {removed:.2f}s removed, {r['out']:.2f}s out "
                 f"({pct:.1f}% shorter)")
    if r["overlap_counted_once"] > 0:
        lines.append(f"  ({r['overlap_counted_once']:.2f}s of the cuts overlap and is counted once)")
    lines.append("  Speech-only estimate: check it against the footage before trusting the runtime.\n")
    return "\n".join(lines)


@guarded
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="yt-deadair", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("transcript", help=".srt, .vtt or whisper .json")
    p.add_argument("--floor", type=float, default=DEFAULT_FLOOR, help="dead-air floor in seconds")
    p.add_argument("--json", action="store_true", help="machine-readable EDL")
    a = p.parse_args(argv)
    cues = load_cues(a.transcript)
    if not cues:
        raise InputError("no cues found - is this an srt, vtt or whisper json?")
    r = analyse(cues, a.floor, a.transcript)
    print(json.dumps(r, indent=1) if a.json else render(r, len(cues)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
