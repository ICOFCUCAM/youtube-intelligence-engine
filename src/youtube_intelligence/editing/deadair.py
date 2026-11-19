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

ICOFCUCAM additions (0.2), off when the transcript has no word timings, so plain SRT/VTT output
is unchanged apart from the new "review" field:
  * WORD TIMINGS (--words auto|off). From Whisper JSON "words" or YouTube auto-caption inline tags:
      - a disfluency INSIDE a sentence ("so the, um, real problem") is cut as FILLER using the
        word's own time. Only disfluencies (um, uh, er, erm, ah, hmm, mm), never "like" or "so",
        which are often meaningful mid-sentence;
      - with exact word ends (Whisper), dead air is measured between WORDS, which finds pauses
        hidden inside long or overlapping cues. YouTube tags carry starts only, so there the
        cue-level gaps are kept.
  * REVIEW. Every DEAD cut carries "review": true when the pause is shorter than --review-below
    (default 1.5 s): short pauses are where deliberate pauses for emphasis live, and a transcript
    cannot tell the difference. --hold-review leaves those out of the removed time. The 1.5 s
    default is an assumption, not a measured threshold - see docs/EVALUATION.md.
"""
from __future__ import annotations

import argparse
import json
import re
from typing import Dict, List, Optional, Sequence

from ..core.cli import guarded
from ..core.errors import InputError
from ..core.intervals import merge_intervals
from ..core.transcript import NO_WORDS, Cue, WordTrack, duration, load_cues, load_words

SCHEMA = "youtube-intelligence/edl@1"
DEFAULT_FLOOR = 0.45
REVIEW_BELOW = 1.5

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


def _dead(prev_end: float, start: float, floor: float, review_below: float) -> Dict:
    gap = start - prev_end
    keep = floor / 2
    return {"kind": "DEAD", "start": round(prev_end + keep, 3), "end": round(start - keep, 3),
            "why": f"{gap:.2f}s gap", "review": gap < review_below}


def _word_cuts(cues: Sequence[Cue], words: WordTrack, floor: float, review_below: float) -> List[Dict]:
    out: List[Dict] = []
    filler_cues = [(c.start, c.end) for c in cues if is_filler(c.text)]
    for w in words.words:
        if re.sub(r"[^a-z]", "", w.text.lower()) in DISFLUENCY and w.end > w.start:
            if not any(a <= w.start and w.end <= b for a, b in filler_cues):
                out.append({"kind": "FILLER", "start": w.start, "end": w.end,
                            "why": f'"{w.text.strip()}" inside a sentence', "review": False})
    if words.exact_ends:
        prev = None
        for w in words.words:
            if prev is not None and w.start - prev > floor:
                out.append(_dead(prev, w.start, floor, review_below))
            prev = w.end if prev is None else max(prev, w.end)
    return out


def find_cuts(cues: Sequence[Cue], floor: float = DEFAULT_FLOOR, words: WordTrack = NO_WORDS,
              review_below: float = REVIEW_BELOW) -> List[Dict]:
    if floor < 0:
        raise InputError("--floor must be zero or more")
    word_gaps = words.available and words.exact_ends
    cuts: List[Dict] = []
    prev_end: Optional[float] = None
    for i, (s, e, t) in enumerate(cues):
        if is_filler(t):
            cuts.append({"kind": "FILLER", "start": s, "end": e, "why": t.strip()[:48], "review": False})
        if prev_end is not None and not word_gaps:
            if s - prev_end > floor:
                cuts.append(_dead(prev_end, s, floor, review_below))
        prev_end = e if prev_end is None else max(prev_end, e)
        # A restart is compared against the last cue that was actually SPEECH. Comparing against
        # the literal previous cue misses every retake with an "um" between the two attempts.
        if t.strip() and not is_filler(t):
            j = i - 1
            while j >= 0 and (is_filler(cues[j][2]) or not cues[j][2].strip()):
                j -= 1
            if j >= 0 and is_restart(cues[j][2], t):
                cuts.append({"kind": "REPEAT", "start": cues[j][0], "end": cues[j][1],
                             "why": f'restart of "{" ".join(_opening(cues[j][2])[:5])}"', "review": False})
    if words.available:
        cuts.extend(_word_cuts(cues, words, floor, review_below))
    cuts = [c for c in cuts if c["end"] > c["start"]]
    cuts.sort(key=lambda c: c["start"])
    return cuts


def analyse(cues: Sequence[Cue], floor: float = DEFAULT_FLOOR, source: str = "",
            words: WordTrack = NO_WORDS, review_below: float = REVIEW_BELOW,
            hold_review: bool = False) -> Dict:
    """The full report. ``removed`` counts overlapping cut time once.

    With ``hold_review``, cuts flagged for review stay in ``cuts`` but are left out of
    ``removed``, ``out`` and ``removed_intervals`` (the list a video engine would apply).
    """
    dur = duration(list(cues))
    cuts = find_cuts(cues, floor, words, review_below)
    applied = [c for c in cuts if not (hold_review and c["review"])]
    merged = merge_intervals((c["start"], c["end"]) for c in applied)
    removed = sum(e - s for s, e in merged)
    raw = sum(c["end"] - c["start"] for c in applied)
    timing = "none" if not words.available else ("exact" if words.exact_ends else "start-only")
    return {"schema": SCHEMA, "source": source, "duration": dur, "floor": floor, "cuts": cuts,
            "removed": round(removed, 3), "out": round(max(0.0, dur - removed), 3),
            "removed_intervals": [[round(s, 3), round(e, 3)] for s, e in merged],
            "overlap_counted_once": round(raw - removed, 3),
            "word_timings": timing, "review_below": review_below, "hold_review": hold_review,
            "held_for_review": sum(1 for c in cuts if c["review"]) if hold_review else 0}


def render(r: Dict, n_cues: int) -> str:
    dur, removed = r["duration"], r["removed"]
    lines = [f"\n  {r['source']}   {dur:.2f}s in, {n_cues} cues, dead-air floor {r['floor']}s\n"]
    for c in r["cuts"]:
        flag = "  [review]" if c.get("review") else ""
        lines.append(f"    {c['kind']:<7} {c['start']:8.2f} -> {c['end']:8.2f}   "
                     f"{c['end'] - c['start']:5.2f}s   {c['why']}{flag}")
    pct = removed / dur * 100 if dur > 0 else 0.0
    lines.append(f"\n  {len(r['cuts'])} cuts, {removed:.2f}s removed, {r['out']:.2f}s out "
                 f"({pct:.1f}% shorter)")
    n_review = sum(1 for c in r["cuts"] if c.get("review"))
    if n_review:
        held = " - held back, not counted above" if r["hold_review"] else " - possibly deliberate, listen before cutting"
        lines.append(f"  {n_review} pause(s) marked [review]{held}")
    if r["word_timings"] != "none":
        lines.append(f"  word timings: {r['word_timings']}")
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
    p.add_argument("--words", choices=["auto", "off"], default="auto",
                   help="use word timings when the transcript has them (default auto)")
    p.add_argument("--review-below", type=float, default=REVIEW_BELOW,
                   help="mark pauses shorter than this many seconds for review (default 1.5)")
    p.add_argument("--hold-review", action="store_true", help="leave review-marked pauses out of the cut")
    p.add_argument("--json", action="store_true", help="machine-readable EDL")
    a = p.parse_args(argv)
    cues = load_cues(a.transcript)
    if not cues:
        raise InputError("no cues found - is this an srt, vtt or whisper json?")
    words = load_words(a.transcript) if a.words == "auto" else NO_WORDS
    r = analyse(cues, a.floor, a.transcript, words, a.review_below, a.hold_review)
    print(json.dumps(r, indent=1) if a.json else render(r, len(cues)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
