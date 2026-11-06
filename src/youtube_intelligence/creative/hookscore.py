"""hookscore - score a YouTube hook before you waste a take on it.

Five properties, 0-100 each, and a verdict that is 60% the mean and 40% the weakest one. The
weakest-link weighting is deliberate: a hook with four strong properties and one dead one is a hook
that leaks at the dead one, and averaging hides that.

    yt-hookscore hooks.txt            # one hook per line, ranked
    yt-hookscore --hook "one line"    # score a single hook
    yt-hookscore --json hooks.txt     # machine-readable

WHAT THIS CAN AND CANNOT TELL YOU. The score is a HEURISTIC built from word lists and regular
expressions. It is not a model of viewer behaviour and it does not predict views, retention or
virality. Upstream measured it against 74 real short-form hooks (first 15 seconds of
auto-captions, top-8 and bottom-8 by views across five channels): it separates deliberately bad
hooks from real ones well, and it separates a creator's own hits from their own misses barely at
all. Treat a low score as a reason to look again, never a high score as a promise.

Known ways to game it (documented, deliberately NOT re-weighted, because changing weights would
silently invalidate the upstream calibration): every number adds to SPECIFICITY, so stuffing a
hook with figures raises the score; every "you" adds to ADDRESS; STAKES rewards fear words. A
number that is not true is worse than no number - the skill instructions forbid inventing one.

Adapted from upstream skills/yt-script/hookscore.py (youtube-agent-skill, (c) 2026 Jake
Schincariol, MIT). Scores are byte-for-byte identical to upstream (golden test). ICOFCUCAM
changes: a missing input file now exits 1 (upstream exited 0), files are read as UTF-8, and the
text report ends with the heuristic disclaimer.
"""
from __future__ import annotations

import argparse
import json
import sys
import re
from typing import Dict, List, Optional, Tuple

from ..core.cli import guarded, read_lines
from ..core.formulas import classify

DISCLAIMER = "heuristic word-pattern score - not a prediction of views or retention"

FILLER = {"basically", "actually", "literally", "just", "really", "very", "so", "kind", "sort", "like",
          "guys", "hey", "welcome", "today", "video", "subscribe", "channel"}
VAGUE = {"amazing", "incredible", "insane", "crazy", "huge", "massive", "game", "changer", "secret",
         "powerful", "ultimate", "best", "revolutionary", "mind", "blowing", "unbelievable"}
CONCRETE = re.compile(r"\b(\d[\d,.]*\s?(%|k|m|x|s|m|h)?|\$\d|\d+\s?(second|minute|hour|day|week|month|year)s?)\b", re.I)
YOU = re.compile(r"\b(you|your|you're|youre|yourself)\b", re.I)
STAKE = re.compile(r"\b(lose|lost|wasting|waste|quit|fail|broke|cost|risk|before|stop|never|die|dying|dead)\b", re.I)
CURIOSITY = re.compile(r"\b(why|how|what|which|until|before|but|nobody|almost|except|reason|actually)\b", re.I)


def words(t: str) -> List[str]:
    return re.findall(r"[a-z0-9'%$.]+", t.lower())


def specificity(t: str) -> int:
    w = words(t)
    if not w:
        return 0
    nums = len(CONCRETE.findall(t))
    vague = sum(1 for x in w if x in VAGUE)
    filler = sum(1 for x in w if x in FILLER)
    s = 34 + nums * 22 - vague * 16 - filler * 5
    # proper nouns that are not sentence-initial read as named things
    s += min(18, 6 * sum(1 for x in t.split()[1:] if x[:1].isupper()))
    return max(0, min(100, s))


def address(t: str) -> int:
    n = len(YOU.findall(t))
    first = 30 if YOU.search(" ".join(t.split()[:6])) else 0
    return max(0, min(100, 26 + n * 20 + first))


def stakes(t: str) -> int:
    n = len(STAKE.findall(t))
    return max(0, min(100, 22 + n * 26 + (14 if CONCRETE.search(t) else 0)))


def curiosity(t: str) -> int:
    n = len(CURIOSITY.findall(t))
    q = 18 if t.strip().endswith("?") else 0
    # a hook that resolves itself has no gap left
    closed = -18 if re.search(r"\b(because|so that|which means)\b", t, re.I) else 0
    return max(0, min(100, 24 + n * 17 + q + closed))


def brevity(t: str) -> int:
    n = len(words(t))
    if n == 0:
        return 0
    # 9-24 words is the band a spoken hook lands in at ~150wpm inside 10 seconds
    if 9 <= n <= 24:
        return 100
    if n < 9:
        return max(30, 100 - (9 - n) * 11)
    return max(10, 100 - (n - 24) * 7)


PROPS = [("SPECIFICITY", specificity), ("ADDRESS", address), ("STAKES", stakes),
         ("CURIOSITY", curiosity), ("BREVITY", brevity)]

FIX = {
    "SPECIFICITY": "swap one adjective for a number, a name or a date (a true one)",
    "ADDRESS": "say 'you' in the first six words",
    "STAKES": "name what it costs them to keep doing it the current way",
    "CURIOSITY": "cut the half of the sentence that answers itself",
    "BREVITY": "9 to 24 words. Read it out loud and stop where you run out of breath",
}


def score(t: str) -> Tuple[Dict[str, int], int, str, int]:
    parts = {n: fn(t) for n, fn in PROPS}
    vals = list(parts.values())
    verdict = round(0.6 * (sum(vals) / len(vals)) + 0.4 * min(vals))
    name, hits = classify(t)
    return parts, verdict, name, hits


def band(v: int) -> str:
    return "STRONG" if v >= 72 else "WORKABLE" if v >= 55 else "WEAK"


def evaluate(lines: List[str]) -> List[Dict]:
    out = []
    for t in lines:
        parts, verdict, name, hits = score(t)
        out.append({"hook": t.strip(), "properties": parts, "verdict": verdict,
                    "band": band(verdict), "formula": name, "matched": hits})
    out.sort(key=lambda r: -r["verdict"])
    return out


def report(r: Dict) -> str:
    t, parts = r["hook"], r["properties"]
    lines = [f"\n  {t}", f"  {'-' * min(72, max(20, len(t)))}"]
    for k, v in parts.items():
        lines.append(f"    {k:<12} {v:3d}  {'#' * (v // 5)}")
    lines.append(f"    {'VERDICT':<12} {r['verdict']:3d}  {r['band']}")
    hits = r["matched"]
    lines.append(f"    formula      {r['formula']}" + (
        f"  ({hits} pattern{'s' if hits != 1 else ''} matched)" if hits
        else "  (no formula matched - that is usually a summary, not a hook)"))
    low = min(parts, key=parts.get)
    lines.append(f"    weakest      {low} - {FIX[low]}")
    return "\n".join(lines)


@guarded
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="yt-hookscore", description=__doc__.split("\n\n")[0])
    p.add_argument("file", nargs="?", help="one hook per line")
    p.add_argument("--hook", help="score a single hook")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    if a.hook is not None:
        lines = [a.hook]
    elif a.file:
        lines = read_lines(a.file)
    else:
        p.print_usage()
        return 1
    out = evaluate(lines)
    if not out:
        print("error: no hooks to score", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps([{k: v for k, v in r.items() if k != "matched"} for r in out], indent=1))
        return 0
    for r in out:
        print(report(r))
    if len(out) > 1:
        print(f"\n  winner: {out[0]['hook']}  ({out[0]['verdict']}, {out[0]['band']})")
    print(f"\n  {DISCLAIMER}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
