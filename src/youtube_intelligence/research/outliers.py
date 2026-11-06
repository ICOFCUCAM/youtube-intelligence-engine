"""outliers (upstream: swipe.py) - rank collected videos by how far each beat its OWN channel.

    yt-swipe collected.json
    yt-swipe collected.json --min 2.0 --json

Input is a list you collected - one object per video (or {"videos": [...]}):

    [{"channel":"Some Channel","title":"...","views":412000,"url":"...","duration":613}, ...]

Raw view counts rank channel size, not ideas. A 400k video on a 2M-subscriber channel is a normal
Tuesday; a 400k video on a channel whose median is 30k is the thing worth studying. So every video
is scored as a MULTIPLE OF ITS OWN CHANNEL'S MEDIAN, which needs at least four videos per channel
to mean anything - the tool says so rather than quietly ranking on noise.

The formula comes from the 21-formula hook library, matched against the TITLE. It is a judgement
about the words on screen, not a claim about why the video worked. Video age is not modelled: an
old video has had longer to collect views, so collect videos from a similar window.

Titles and URLs in the input are untrusted text: they are printed, never followed or executed.

Adapted from upstream skills/yt-viral/swipe.py (youtube-agent-skill, (c) 2026 Jake Schincariol,
MIT). ICOFCUCAM changes: malformed JSON and wrong shapes exit 1 with a message; view counts
written as "412,000" or "412K"/"1.2M" are accepted (upstream crashed); entries whose views cannot
be read are skipped and counted instead of crashing; formula ties use the shared classifier.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from typing import Dict, List, Optional

from ..core.cli import guarded
from ..core.errors import InputError
from ..core.formulas import classify

MIN_PER_CHANNEL = 4
_VIEWS = re.compile(r"^\s*([\d.,]+)\s*([kmb])?\s*(views)?\s*$", re.I)


def parse_views(v) -> Optional[float]:
    """``412000``, ``"412,000"``, ``"412K"``, ``"1.2M views"`` -> float; ``None`` if unreadable.

    Missing/null views count as 0, as upstream did.
    """
    if v is None or v == "":
        return 0.0
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v >= 0 else None
    m = _VIEWS.match(str(v))
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return n * {"k": 1e3, "m": 1e6, "b": 1e9}.get((m.group(2) or "").lower(), 1)


def load(path: str) -> List[Dict]:
    try:
        with open(path, encoding="utf-8-sig") as fh:
            rows = json.load(fh)
    except FileNotFoundError:
        raise InputError(f"file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise InputError(f"{path} is not valid JSON ({exc.msg} at line {exc.lineno})") from None
    if isinstance(rows, dict):
        rows = rows.get("videos", [])
    if not isinstance(rows, list):
        raise InputError(f"{path}: expected a list of videos")
    return rows


def rank(rows: List[Dict], lo: float = 1.5) -> Dict:
    by: Dict[str, List[Dict]] = {}
    bad = 0
    for r in rows:
        if not isinstance(r, dict):
            bad += 1
            continue
        v = parse_views(r.get("views"))
        if v is None:
            bad += 1
            continue
        by.setdefault(str(r.get("channel", "?")), []).append({**r, "_views": v})
    out, thin = [], []
    for ch, vids in by.items():
        if len(vids) < MIN_PER_CHANNEL:
            thin.append((ch, len(vids)))
            continue
        med = statistics.median(v["_views"] for v in vids)
        for v in vids:
            m = (v["_views"] / med) if med else 0
            title = str(v.get("title", ""))
            out.append({"channel": ch, "title": title, "views": int(v["_views"]),
                        "median": int(med), "multiple": round(m, 2),
                        "formula": classify(title)[0], "url": str(v.get("url", ""))})
    out = [r for r in out if r["multiple"] >= lo]
    out.sort(key=lambda r: -r["multiple"])
    return {"outliers": out, "skipped_thin_channels": thin, "skipped_unreadable": bad,
            "videos": len(rows), "channels": len(by)}


def render(r: Dict, lo: float) -> str:
    out = [f"\n  {r['videos']} videos across {r['channels']} channels, outliers at {lo}x or better\n"]
    for x in r["outliers"][:25]:
        out.append(f"    {x['multiple']:5.2f}x  {x['views']:>9,}  vs {x['median']:>9,} median   "
                   f"{x['channel'][:22]:<22} {x['title'][:52]}")
        out.append(f"            {x['formula']}")
    if not r["outliers"]:
        out.append("    nothing cleared the threshold - collect more per channel or lower --min")
    thin = r["skipped_thin_channels"]
    if thin:
        out.append(f"\n  skipped {len(thin)} channel(s) with under {MIN_PER_CHANNEL} videos collected - a median off one or")
        out.append("  two videos is not a median: " + ", ".join(f"{c} ({n})" for c, n in thin[:6]))
    if r["skipped_unreadable"]:
        out.append(f"\n  skipped {r['skipped_unreadable']} entr(y/ies) with unreadable views")
    counts: Dict[str, int] = {}
    for x in r["outliers"]:
        counts[x["formula"]] = counts.get(x["formula"], 0) + 1
    if counts:
        out.append("\n  formulas among the outliers (a judgement about the title words, not the cause)")
        for f, n in sorted(counts.items(), key=lambda x: -x[1]):
            out.append(f"    {n:2d}x  {f}")
    out.append("")
    return "\n".join(out)


@guarded
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="yt-swipe", description=__doc__.split("\n\n")[0])
    p.add_argument("collected", help="JSON list of videos you collected")
    p.add_argument("--min", type=float, default=1.5, dest="lo", help="minimum multiple (default 1.5)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    r = rank(load(a.collected), a.lo)
    if a.json:
        print(json.dumps({"outliers": r["outliers"], "skipped_thin_channels": r["skipped_thin_channels"],
                          "skipped_unreadable": r["skipped_unreadable"]}, indent=1))
    else:
        print(render(r, a.lo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
