"""retention - read a YouTube Studio audience-retention export and find the leaks.

    yt-retention retention.csv
    yt-retention retention.csv --duration 600 --transcript transcript.srt   # names what was said
    yt-retention retention.csv --json

Get the file from Studio: Analytics -> a video -> Engagement -> the audience-retention chart ->
the download icon -> "Audience retention". Two columns, a position (percent or seconds) and a
percentage still watching.

It reports three things, because they are three different problems with three different fixes:
  HOOK LEAK    percentage points lost in the first 30 seconds
  CLIFFS       single steep drops - a specific moment people left at
  SLIDE        the steady bleed rate across the flat middle

With --transcript (and seconds, either from a seconds axis or --duration) it prints what you were
saying at each cliff, which is the only version of this report you can act on without scrubbing
the video yourself.

LIMITATIONS - the numbers are descriptive, not diagnostic:
  * Sample size. A curve from a few hundred views is mostly noise; single "cliffs" on a low-view
    video can be a handful of people.
  * Video age. Early viewers are mostly subscribers; later ones arrive from browse and search and
    behave differently. Compare videos at the same age.
  * Format. The 25% / 40% hook-leak bands are rules of thumb for long-form talking videos. They do
    not transfer to Shorts, music, livestream replays or very short videos.
  * Audience and traffic source. Retention differs by traffic source, device and country; one
    curve averages all of them.
  * Rewatches and skips make absolute retention exceed 100% or jump upward; upward moves are
    ignored as cliffs and averaged into the slide.

Adapted from upstream skills/yt-retention/retention.py (youtube-agent-skill, (c) 2026 Jake
Schincariol, MIT). The analysis is unchanged. ICOFCUCAM changes:
  * arguments are parsed properly - upstream treated the value of --duration as the CSV path when
    --duration came first, and printed usage instead of reading the file;
  * the position axis is read from the CSV header when it says "%" or "second", and can be forced
    with --axis; upstream guessed "percent" whenever every position was <= 100.5, which misreads
    a seconds-axis export of any video up to 100 seconds long;
  * --transcript accepts JSON-array transcripts (inherited loader bug);
  * the limitations above are printed and included in --json output.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from typing import Dict, List, Optional, Tuple

from ..core.cli import guarded
from ..core.errors import InputError
from ..core.transcript import load_cues

MIN_POINTS = 8
LIMITATIONS = [
    "low view counts make the curve noisy - a cliff can be a handful of people",
    "compare videos at the same age - early viewers are mostly subscribers",
    "hook-leak bands (25/40) are long-form rules of thumb, not valid for Shorts or very short videos",
    "one curve averages every traffic source, device and audience",
]


def load_csv(path: str) -> Tuple[List[Tuple[float, float]], Optional[str]]:
    """Return ``(rows, axis_hint)``; ``axis_hint`` is ``percent``/``seconds`` from the header or None."""
    rows, hint = [], None
    try:
        fh = open(path, newline="", encoding="utf-8-sig", errors="replace")
    except FileNotFoundError:
        raise InputError(f"file not found: {path}") from None
    except IsADirectoryError:
        raise InputError(f"{path} is a directory") from None
    with fh:
        for r in csv.reader(fh):
            nums = []
            for c in r:
                c = c.strip().replace("%", "").replace(",", "")
                try:
                    nums.append(float(c))
                except ValueError:
                    nums.append(None)
            vals = [n for n in nums if n is not None]
            if len(vals) >= 2:
                rows.append((vals[0], vals[1]))
            elif not rows and r and hint is None:
                head = r[0].lower()
                if "%" in head or "percent" in head:
                    hint = "percent"
                elif re.search(r"second|\(s\)|time", head):
                    hint = "seconds"
    return rows, hint


def analyse(rows: List[Tuple[float, float]], duration: Optional[float] = None,
            axis: str = "auto", hint: Optional[str] = None) -> Dict:
    if len(rows) < MIN_POINTS:
        raise InputError(f"could not read at least {MIN_POINTS} data points from that csv")
    if duration is not None and duration <= 0:
        raise InputError("--duration must be positive")
    xs = [r[0] for r in rows]
    ys = [r[1] for r in rows]
    if axis == "auto":
        axis = hint or ("percent" if max(xs) <= 100.5 else "seconds")
    pct_axis = axis == "percent"
    dur = duration

    def at(x: float) -> float:
        return (x / 100.0 * dur) if (pct_axis and dur) else x

    start = ys[0] or 100.0
    # HOOK: the first 30 seconds, or the first 10% when the axis is a percentage and we have no duration
    cutoff = 30.0 if not pct_axis else (30.0 / dur * 100 if dur else 10.0)
    hook_end = min((y for x, y in rows if x <= cutoff), default=start)
    hook_leak = start - hook_end
    drops = []
    for i in range(1, len(rows)):
        d = ys[i - 1] - ys[i]
        span = xs[i] - xs[i - 1] or 1
        drops.append((d / span, xs[i - 1], xs[i], d))
    drops.sort(reverse=True)
    cliffs = [{"from": round(a1, 2), "to": round(b1, 2), "lost": round(d, 2),
               "at_seconds": round(at(a1), 1) if (not pct_axis or dur) else None}
              for _, a1, b1, d in drops[:5] if d > 0.8]
    mid = [rate for rate, x0, _, _ in drops if x0 > cutoff]
    slide = sum(mid) / len(mid) if mid else 0
    return {"points": len(rows), "axis": axis, "start": start, "hook_leak": round(hook_leak, 2),
            "end": ys[-1], "cliffs": cliffs, "slide_per_unit": round(slide, 3), "said": {},
            "limitations": LIMITATIONS}


def attach_transcript(report: Dict, transcript: str, window: float = 4.0) -> None:
    cues = load_cues(transcript)
    for c in report["cliffs"]:
        if c["at_seconds"] is None:
            continue
        t = c["at_seconds"]
        near = [q[2] for q in cues if q[0] <= t + window and q[1] >= t - window]
        report["said"][str(c["from"])] = " ".join(near)[:140]


def render(r: Dict, source: str) -> str:
    out = [f"\n  {source}   {r['points']} points   {r['start']:.1f}% -> {r['end']:.1f}%   ({r['axis']} axis)\n"]
    hl = r["hook_leak"]
    verdict = "healthy" if hl < 25 else "leaking" if hl < 40 else "severe"
    out.append(f"  HOOK LEAK   {hl:.1f} points lost in the opening   [{verdict}]")
    out.append("              under 25 is healthy for long-form. Fix the first line before anything else.\n")
    out.append("  CLIFFS      the moments people actually left")
    said = r["said"]
    for c in r["cliffs"]:
        where = f"{c['at_seconds']:.0f}s" if c["at_seconds"] is not None else f"{c['from']}%"
        out.append(f"    -{c['lost']:5.1f}%  at {where:>8}" + (f"   \"{said.get(str(c['from']), '')}\"" if said else ""))
    if not r["cliffs"]:
        out.append("    none steeper than 0.8% - the loss is all slide, not moments")
    unit = "second" if r["axis"] == "seconds" else "1% of the video"
    out.append(f"\n  SLIDE       {r['slide_per_unit']:.3f}% per {unit} across the middle")
    out.append("              a flat slide is pacing, not content. Cut the middle, do not rewrite it.\n")
    out.append("  LIMITS      " + "\n              ".join(r["limitations"]) + "\n")
    return "\n".join(out)


@guarded
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="yt-retention", description=__doc__.split("\n\n")[0])
    p.add_argument("csv")
    p.add_argument("--duration", type=float, help="video length in seconds (maps a percent axis to time)")
    p.add_argument("--transcript", help=".srt/.vtt/.json transcript to quote at each cliff")
    p.add_argument("--axis", choices=["auto", "percent", "seconds"], default="auto")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    rows, hint = load_csv(a.csv)
    r = analyse(rows, a.duration, a.axis, hint)
    if a.transcript:
        attach_transcript(r, a.transcript)
    print(json.dumps(r, indent=1) if a.json else render(r, a.csv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
