"""title - lint a YouTube title and thumbnail pairing before you publish it.

    yt-title --title "..." --thumb "AI RAN IT"
    yt-title titles.txt            # one per line, ranked
    yt-title --title "..." --json

The pairing is the unit, not the title. A title that repeats the thumbnail text wastes half the
click surface, and that is the single most common mistake this checks for.

Length: YouTube truncates around 60 characters on desktop search and around 40 on a mobile home
feed. Both limits are reported because they are different failures - a desktop truncation loses the
tail, a mobile one can lose the subject. (These are observed display widths, not API limits; only
the 100-character maximum is a hard YouTube rule.)

Adapted from upstream skills/yt-package/title.py (youtube-agent-skill, (c) 2026 Jake Schincariol,
MIT). ICOFCUCAM scoring changes, documented in CHANGELOG.md and docs/TOOL_REVIEW.md:
  * a title is no longer penalised for having no digit, and a digit no longer earns credit.
    Upstream scored "Why your channel is not growing" 90 and "1 trick 2 make 10000 in 24 hours"
    100, which taught users to add numbers. The absence of a number is now an unscored NOTE
    reminding you that a figure helps only if it is true and you can show it;
  * hype and unverifiable-claim language (guarantees, "overnight", income claims, "they don't want
    you to know") is a scored "claim" issue;
  * three or more separate figures in one title is a scored "numbers" issue.
Every other check and the scoring formula (100 - 14 per issue + 4 per strength) are unchanged.
"""
from __future__ import annotations

import argparse
import json
import re
from typing import Dict, List, Optional

from ..core.cli import guarded, read_lines

DESKTOP, MOBILE, HARD = 60, 40, 100
VAGUE = {"amazing", "incredible", "insane", "crazy", "huge", "massive", "ultimate", "best", "powerful",
         "secret", "revolutionary", "mindblowing", "epic", "perfect", "complete", "everything"}
STOP = {"the", "a", "an", "of", "for", "to", "in", "on", "and", "or", "is", "are", "with", "your", "you",
        "my", "i", "this", "that", "it", "how", "what", "why"}
FIGURE = re.compile(r"\d[\d,.]*%?")
CLAIMS = [
    (re.compile(r"\bguarantee[ds]?\b|\b100\s?%\s+(guaranteed|proven|works|success|legit)\b", re.I),
     "a guarantee"),
    (re.compile(r"\b(always works|never fails|works every time|can'?t fail|cannot fail|"
                r"zero risk|risk[- ]free|no risk)\b", re.I), "an absolute promise"),
    (re.compile(r"\b(overnight|instantly|instant results|get rich)\b", re.I), "an instant-result promise"),
    (re.compile(r"\b(make|made|earn|earned|earning|making)\s+(over\s+)?\$?\d", re.I), "an income claim"),
    (re.compile(r"\$\s?\d[\d,.]*\s?k?\s*(/|per|a|an|every)\s*(day|week|month|mo|hour|hr|year)\b", re.I),
     "an income claim"),
    (re.compile(r"\b((they )?(don'?t|doesn'?t) want you to know|doctors hate|nobody will tell you|banned)\b", re.I),
     "a conspiracy hook"),
]


def words(t: str) -> List[str]:
    return re.findall(r"[a-z0-9']+", t.lower())


def check(title: str, thumb: Optional[str] = None) -> Dict:
    t = title.strip()
    n = len(t)
    issues, good, notes = [], [], []
    if n > HARD:
        issues.append(("length", f"{n} characters - YouTube's hard limit is {HARD}"))
    elif n > DESKTOP:
        issues.append(("length", f"{n} characters - desktop search cuts near {DESKTOP}"))
    else:
        good.append(f"{n} characters, inside the {DESKTOP}-character desktop cut")
    if n > MOBILE:
        head = t[:MOBILE].rsplit(" ", 1)[0]
        issues.append(("mobile", f'a mobile feed shows about "{head}..." - check the subject survives'))
    caps = [w for w in t.split() if len(w) > 2 and w.isupper()]
    if len(caps) > 2:
        issues.append(("shouting", f"{len(caps)} all-caps words - two is the ceiling before it reads as spam"))
    elif caps:
        good.append(f"{len(caps)} all-caps word for emphasis")
    v = [w for w in words(t) if w in VAGUE]
    if v:
        issues.append(("vague", f"{', '.join(sorted(set(v)))} - swap for something specific and true"))
    nums = FIGURE.findall(t)
    if len(nums) >= 3:
        issues.append(("numbers", f"{len(nums)} separate figures - one real number lands, three read as bait"))
    if nums:
        notes.append(f"carries a figure ({', '.join(nums[:3])}) - only publish it if the video shows it")
    else:
        notes.append("no number, date or name - a specific detail usually helps, but only a true one")
    claims = sorted({label for rx, label in CLAIMS if rx.search(t)})
    if claims:
        issues.append(("claim", f"reads as {', '.join(claims)} - only publish it if the video proves it on screen"))
    if t.endswith("?"):
        good.append("open question in the title")
    front = [w for w in words(t)[:3] if w not in STOP]
    if not front:
        issues.append(("front-load", "the first three words are all filler - move the subject forward"))
    if thumb:
        tw, hw = set(words(t)) - STOP, set(words(thumb)) - STOP
        shared = tw & hw
        if shared:
            issues.append(("duplicate", f"thumbnail repeats the title on {', '.join(sorted(shared))} - "
                                        "the thumbnail should say what the title does not"))
        else:
            good.append("thumbnail and title carry different words")
        if len(words(thumb)) > 4:
            issues.append(("thumb-length", f"{len(words(thumb))} words on the thumbnail - three is the ceiling at feed size"))
    score = max(0, min(100, 100 - 14 * len(issues) + 4 * len(good)))
    return {"title": t, "chars": n, "score": score, "issues": issues, "good": good, "notes": notes}


def show(r: Dict) -> str:
    lines = [f'\n  "{r["title"]}"', f"  {r['chars']} chars   score {r['score']}/100"]
    lines += [f"    x  {k:<12} {m}" for k, m in r["issues"]]
    lines += [f"    ok              {m}" for m in r["good"]]
    lines += [f"    note            {m}" for m in r["notes"]]
    return "\n".join(lines)


@guarded
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="yt-title", description=__doc__.split("\n\n")[0])
    p.add_argument("file", nargs="?", help="one title per line")
    p.add_argument("--title")
    p.add_argument("--thumb", help="the thumbnail text")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    if a.title is not None:
        rows = [check(a.title, a.thumb)]
    elif a.file:
        rows = [check(ln, a.thumb) for ln in read_lines(a.file)]
    else:
        p.print_usage()
        return 1
    rows.sort(key=lambda r: -r["score"])
    if a.json:
        print(json.dumps(rows, indent=1))
        return 0
    for r in rows:
        print(show(r))
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
