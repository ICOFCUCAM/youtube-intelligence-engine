"""yt-moments - what you were saying when viewers left, across all your videos.

    yt-moments manifest.json
    yt-moments manifest.json --json

The manifest lists videos, each with a transcript and its YouTube Studio retention export (paths
relative to the manifest, which must stay inside its folder):

    {"videos": [{"id": "abc", "title": "...", "transcript": "abc.srt",
                 "retention": "abc-retention.csv", "duration": 612.0}]}

For every sentence (transcript cue) it measures how many percentage points of the audience were
lost while it was said, minus what the video normally loses in that time (the median loss rate
across the video's middle). The difference is the sentence's EXTRA loss. Sentences are tagged by
type (sponsor read, subscribe/like ask, housekeeping, tangent, recap, signpost), and the types are
compared across videos.

Honesty rules, built in:
  * the first 30 seconds and the last 10% are left out: viewers leave there anyway (hook leak,
    outro), so blaming whatever was said would be wrong;
  * a type is called a pattern only with at least 3 occurrences across at least 2 videos;
  * this is correlation, not cause: a sponsor read placed at a natural exit point will look worse
    than it is. Use it to choose what to test, not as proof;
  * EXTRA loss is relative to the video's typical rate, so a type of sentence that makes up most
    of a video becomes the typical rate and cannot stand out. On the invented demo set, signposts
    were scripted to hold viewers but measure as "no clear effect" for exactly this reason.
ICOFCUCAM addition.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
from typing import Dict, List, Optional, Sequence, Tuple

from ..core.cli import guarded
from ..core.errors import InputError
from ..core.transcript import Cue, duration as transcript_duration, load_cues
from . import retention as ret

OPENING_SKIP = 30.0
ENDING_SKIP = 0.10
MIN_OCCURRENCES = 3
MIN_VIDEOS = 2
COSTS_ABOVE = 0.5      # extra points per occurrence
HOLDS_BELOW = -0.2

CATEGORIES: List[Tuple[str, str, "re.Pattern[str]"]] = [
    ("sponsor", "Sponsor reads", re.compile(
        r"\b(sponsor(?:ed|ing|s)?|brought to you by|use (?:my )?code|promo code|percent off|thanks to \w+ for)\b", re.I)),
    ("self_promo", "Subscribe / like asks", re.compile(
        r"\b(subscribe|like (?:the|this) video|hit (?:the|that) like|notifications?|the bell|comment below|patreon)\b", re.I)),
    ("housekeeping", "Housekeeping", re.compile(
        r"\b(before we (?:get into|go on|start|begin|dive in)|quick reminder|as always|first things first)\b", re.I)),
    ("tangent", "Tangents and side stories", re.compile(
        r"\b(quick story|funny story|by the way|side note|fun fact|off topic|random(?:ly)?)\b", re.I)),
    ("recap", "Recaps and repeats", re.compile(
        r"\b(as i (?:said|mentioned)|like i (?:said|mentioned)|to recap|to sum up|in summary)\b", re.I)),
    ("signpost", "Signposts (next, step two...)", re.compile(
        r"\b(step (?:one|two|three|four|five|\d+)|number (?:one|two|three|four|five|\d+)|"
        r"(?:first|second|third|fourth)(?:ly)?,|next,|moving on|now let's|let's move on)", re.I)),
]
LABEL = {k: label for k, label, _ in CATEGORIES}


def tags(text: str) -> List[str]:
    return [k for k, _, rx in CATEGORIES if rx.search(text)]


def curve_seconds(rows: List[Tuple[float, float]], hint: Optional[str], seconds: float) -> List[Tuple[float, float]]:
    """Retention as (second, percent) pairs, sorted. A percent axis is mapped with the video length."""
    axis = hint or ("percent" if max(x for x, _ in rows) <= 100.5 else "seconds")
    pts = [((x / 100.0 * seconds) if axis == "percent" else x, y) for x, y in rows]
    return sorted(pts)


def y_at(curve: List[Tuple[float, float]], t: float) -> float:
    if t <= curve[0][0]:
        return curve[0][1]
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if x0 <= t <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (t - x0) / (x1 - x0)
    return curve[-1][1]


def baseline_rate(curve: List[Tuple[float, float]], start: float, end: float) -> float:
    rates = [(y0 - y1) / (x1 - x0) for (x0, y0), (x1, y1) in zip(curve, curve[1:])
             if x1 > x0 and x0 >= start and x1 <= end]
    if not rates:
        raise InputError("the retention export has too few points inside the analysed window")
    return statistics.median(rates)


def analyse_video(vid: str, title: str, cues: Sequence[Cue], curve: List[Tuple[float, float]],
                  seconds: float) -> Dict:
    start, end = OPENING_SKIP, seconds * (1 - ENDING_SKIP)
    if end - start < 30:
        raise InputError(f"{vid}: too short to analyse (needs more than 30 s between the opening and the ending)")
    rate = baseline_rate(curve, start, end)
    moments = []
    for c in cues:
        if c.start < start or c.end > end or c.end <= c.start or not c.text.strip():
            continue
        lost = y_at(curve, c.start) - y_at(curve, c.end)
        extra = lost - rate * (c.end - c.start)
        moments.append({"video": vid, "title": title, "start": round(c.start, 2), "end": round(c.end, 2),
                        "text": c.text, "lost": round(lost, 3), "extra": round(extra, 3), "tags": tags(c.text)})
    return {"id": vid, "title": title, "duration": seconds, "baseline_per_minute": round(rate * 60, 3),
            "analysed": [start, round(end, 2)], "moments": moments}


def aggregate(videos: List[Dict]) -> Dict:
    allm = [m for v in videos for m in v["moments"]]
    if not allm:
        raise InputError("no sentences inside the analysed windows")
    plain = [m["extra"] for m in allm if not m["tags"]]
    patterns = []
    for key, label, _ in CATEGORIES:
        ms = [m for m in allm if key in m["tags"]]
        vids = sorted({m["video"] for m in ms})
        entry = {"type": key, "label": label, "occurrences": len(ms), "videos": len(vids)}
        if ms:
            entry["mean_extra"] = round(statistics.mean(m["extra"] for m in ms), 2)
        if len(ms) >= MIN_OCCURRENCES and len(vids) >= MIN_VIDEOS:
            me = entry["mean_extra"]
            entry["finding"] = ("costs viewers" if me > COSTS_ABOVE else
                                "holds viewers" if me < HOLDS_BELOW else "no clear effect")
        elif ms:
            entry["finding"] = "too few to tell"
        else:
            continue
        patterns.append(entry)
    order = {"costs viewers": 0, "holds viewers": 1, "no clear effect": 2, "too few to tell": 3}
    patterns.sort(key=lambda p: (order[p["finding"]], -p.get("mean_extra", 0)))
    worst = sorted(allm, key=lambda m: -m["extra"])[:5]
    return {"schema": "youtube-intelligence/moments@1", "videos": len(videos),
            "sentences": len(allm), "untagged_mean_extra": round(statistics.mean(plain), 2) if plain else None,
            "patterns": patterns, "worst_moments": worst,
            "rules": {"skipped": f"first {OPENING_SKIP:.0f} s and last {ENDING_SKIP:.0%} of each video",
                      "pattern_needs": f"{MIN_OCCURRENCES}+ occurrences across {MIN_VIDEOS}+ videos",
                      "costs_viewers": f"more than {COSTS_ABOVE} extra points per occurrence",
                      "holds_viewers": f"less than {HOLDS_BELOW} extra points per occurrence"},
            "caveat": "Correlation, not cause. Use it to choose what to test next. Losses are compared with "
                      "each video's typical rate, so the kind of sentence that fills most of a video can't stand out."}


def load_manifest(path: str) -> List[Dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except FileNotFoundError:
        raise InputError(f"file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise InputError(f"{path} is not valid JSON ({exc.msg} at line {exc.lineno})") from None
    vids = d.get("videos") if isinstance(d, dict) else d
    if not isinstance(vids, list) or not vids:
        raise InputError("the manifest needs a non-empty 'videos' list")
    base = os.path.dirname(os.path.abspath(path))
    out, seen = [], set()
    for n, v in enumerate(vids):
        if not isinstance(v, dict) or not all(isinstance(v.get(k), str) for k in ("id", "transcript", "retention")):
            raise InputError(f"videos[{n}] needs id, transcript and retention")
        if v["id"] in seen:
            raise InputError(f"duplicate video id {v['id']!r}")
        seen.add(v["id"])
        paths = {}
        for k in ("transcript", "retention"):
            full = os.path.normpath(os.path.join(base, v[k]))
            if os.path.isabs(v[k]) or not full.startswith(base + os.sep):
                raise InputError(f"videos[{n}].{k} must be a relative path inside the manifest's folder")
            paths[k] = full
        d_ = v.get("duration")
        if d_ is not None and (isinstance(d_, bool) or not isinstance(d_, (int, float)) or d_ <= 0):
            raise InputError(f"videos[{n}].duration must be a positive number of seconds")
        out.append({"id": v["id"], "title": str(v.get("title", v["id"])), "duration": d_, **paths})
    return out


def run(manifest_path: str) -> Dict:
    videos = []
    for v in load_manifest(manifest_path):
        cues = load_cues(v["transcript"])
        if not cues:
            raise InputError(f"{v['id']}: no cues in the transcript")
        seconds = float(v["duration"] or transcript_duration(cues))
        rows, hint = ret.load_csv(v["retention"])
        if len(rows) < ret.MIN_POINTS:
            raise InputError(f"{v['id']}: could not read at least {ret.MIN_POINTS} points from the retention export")
        videos.append(analyse_video(v["id"], v["title"], cues, curve_seconds(rows, hint, seconds), seconds))
    r = aggregate(videos)
    r["per_video"] = [{k: v[k] for k in ("id", "title", "duration", "baseline_per_minute", "analysed")} for v in videos]
    return r


def _t(s: float) -> str:
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def render(r: Dict) -> str:
    out = [f"\n  {r['videos']} videos, {r['sentences']} sentences analysed ({r['rules']['skipped']} skipped)\n",
           "  WHAT YOU SAY, AND WHAT IT COSTS            extra points lost per time said"]
    for p in r["patterns"]:
        me = f"{p['mean_extra']:+.2f}" if "mean_extra" in p else "   -"
        times = f"{p['occurrences']} time{'s' if p['occurrences'] != 1 else ''}"
        vids = f"{p['videos']} video{'s' if p['videos'] != 1 else ''}"
        out.append(f"    {p['label']:<32} {me:>7}   {p['finding']:<16} ({times}, {vids})")
    if r["untagged_mean_extra"] is not None:
        out.append(f"    {'everything else':<32} {r['untagged_mean_extra']:+7.2f}")
    out.append("\n  THE FIVE COSTLIEST SENTENCES")
    for m in r["worst_moments"]:
        out.append(f"    {m['extra']:+5.1f}  {m['video']} at {_t(m['start'])}  \"{m['text'][:70]}\"")
    out.append(f"\n  {r['caveat']} A pattern needs {r['rules']['pattern_needs']}.\n")
    return "\n".join(out)


@guarded
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="yt-moments", description=__doc__.split("\n\n")[0])
    p.add_argument("manifest")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    r = run(a.manifest)
    print(json.dumps(r, indent=1) if a.json else render(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
