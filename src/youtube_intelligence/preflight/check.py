"""yt-check - the pre-upload check. One command before you upload, ending in a verdict.

    yt-check --title "Why your first 30 seconds lose viewers" --thumb "STOP DOING THIS" \\
             --transcript talk.srt --description description.txt --query "youtube retention"

Status rules, chosen so the verdict is honest:
  FAIL  only for objective YouTube rule breaks that will cause a problem: a title over 100
        characters, a description over 5,000 bytes, "<" or ">" in either (YouTube rejects them),
        or chapters in the description that will not render.
  WARN  judgement calls and heuristics: a weak or slow opening, a title flagged by the lint, a lot
        of removable dead air, target search words missing from the top of the description.
  PASS / INFO  everything else.
Verdict: "not yet" if anything FAILs, "ready, with fixes worth making" if anything WARNs,
otherwise "ready to upload". Nothing here uploads; it only reads what you give it.

Built from the existing tools (hookscore, title, deadair, chapters, shorts) plus upstream skill
rules: confirm the title in the first sentence, no channel intro or subscribe pitch before the
payoff (yt-script), the first two description lines are the search snippet (yt-seo), and
YouTube's chapter rules (yt-chapters).
"""
from __future__ import annotations

import argparse
import json
import re

from typing import Dict, List, Optional, Sequence

from ..core.cli import guarded
from ..core.errors import InputError
from ..core.transcript import NO_WORDS, Cue, WordTrack, duration, load_cues, load_words, parse_ts
from ..creative import hookscore
from ..editing import chapters as chapters_mod
from ..editing import deadair
from ..packaging.title import check as title_check
from ..shorts import candidates

SCHEMA = "youtube-intelligence/preflight@1"
TITLE_MAX = 100
DESCRIPTION_MAX_BYTES = 5000
HOOK_SECONDS = 15.0
PITCH_SECONDS = 30.0
DEAD_AIR_WARN = 0.10
PITCH = re.compile(r"\b(welcome back|subscribe|smash (?:that|the) like|hit (?:that|the) bell|my name is|"
                   r"before we (?:get started|begin|dive in)|don'?t forget to like)\b", re.I)
CHAPTER_LINE = re.compile(r"^\s*(\(?)((?:\d{1,2}:)?\d{1,2}:\d{2})\)?\s*[-–:|]?\s*(.+?)\s*$")
STOP = chapters_mod.STOP | {"youtube", "video", "videos"}


def _check(area: str, status: str, title: str, detail: str = "") -> Dict:
    return {"area": area, "status": status, "title": title, "detail": detail}


def _stems(text: str) -> set:
    return {w[:5] for w in re.findall(r"[a-z0-9']{3,}", text.lower()) if w not in STOP}


def _opening(cues: Sequence[Cue], words: WordTrack, seconds: float) -> str:
    if words.available:
        return " ".join(w.text for w in words.words if w.start < seconds)
    return " ".join(c.text for c in cues if c.start < seconds)


def parse_description_chapters(description: str) -> List[Dict]:
    out = []
    for line in description.splitlines():
        m = CHAPTER_LINE.match(line)
        if m:
            try:
                t = parse_ts(m.group(2))
            except InputError:
                continue
            out.append({"start": t, "label": m.group(2), "title": m.group(3)})
    return out


def check_chapters(ch: List[Dict], video_seconds: Optional[float]) -> List[str]:
    """YouTube's chapter rules. Returns the list of broken rules (empty = will render)."""
    problems = []
    if len(ch) < 3:
        problems.append(f"only {len(ch)} timestamp(s); YouTube needs at least 3")
    if ch and ch[0]["start"] != 0:
        problems.append(f"the first timestamp is {ch[0]['label']}; it must be 0:00")
    starts = [c["start"] for c in ch]
    if any(b <= a for a, b in zip(starts, starts[1:])):
        problems.append("timestamps are not in increasing order")
    short = [c["label"] for c, nxt in zip(ch, ch[1:]) if nxt["start"] - c["start"] < 10]
    if video_seconds is not None and ch:
        if ch[-1]["start"] >= video_seconds:
            problems.append(f"{ch[-1]['label']} is after the end of the video")
        elif video_seconds - ch[-1]["start"] < 10:
            short.append(ch[-1]["label"])
    if short:
        problems.append(f"chapter(s) at {', '.join(short)} are shorter than 10 seconds")
    return problems


def run(title: str, thumb: Optional[str] = None, description: Optional[str] = None,
        queries: Optional[List[str]] = None, cues: Optional[Sequence[Cue]] = None,
        words: WordTrack = NO_WORDS) -> Dict:
    if not isinstance(title, str) or not title.strip():
        raise InputError("a title is required")
    title = title.strip()
    queries = [q.strip() for q in (queries or []) if q and q.strip()]
    checks: List[Dict] = []
    suggested: List[Dict] = []
    video_seconds = duration(list(cues)) if cues else None

    # --- packaging -------------------------------------------------------------------------------
    if len(title) > TITLE_MAX:
        checks.append(_check("packaging", "fail", f"Title is {len(title)} characters",
                             f"YouTube's limit is {TITLE_MAX}. It will be rejected."))
    if "<" in title or ">" in title:
        checks.append(_check("packaging", "fail", "Title contains < or >", "YouTube rejects these characters in titles."))
    t = title_check(title, thumb)
    flagged = [m for k, m in t["issues"] if k not in ("length",)] if len(title) > TITLE_MAX else [m for _, m in t["issues"]]
    if flagged:
        checks.append(_check("packaging", "warn", f"Title and thumbnail: {len(flagged)} thing(s) to fix (score {t['score']})",
                             "; ".join(flagged)))
    else:
        checks.append(_check("packaging", "pass", f"Title and thumbnail look clean (score {t['score']})",
                             "; ".join(t["good"])))

    # --- opening ---------------------------------------------------------------------------------
    if cues:
        opening = _opening(cues, words, HOOK_SECONDS)
        early = _opening(cues, words, PITCH_SECONDS)
        if not opening.strip():
            checks.append(_check("opening", "warn", "Nothing is said in the first 15 seconds",
                                 "A silent or music-only opening needs the title's promise on screen."))
        else:
            parts, verdict, name, _hits = hookscore.score(opening)
            band = hookscore.band(verdict)
            weakest = min(parts, key=parts.get)
            status = "warn" if band == "WEAK" else "pass"
            checks.append(_check("opening", status, f"Opening hook: {verdict} ({band})",
                                 f"Weakest: {weakest.lower()} - {hookscore.FIX[weakest]}. Formula: {name}. "
                                 "A heuristic, not a prediction."))
            stems = _stems(opening)
            shared = sorted({w for w in re.findall(r"[a-z0-9']{3,}", title.lower()) if w not in STOP and w[:5] in stems})
            if not shared:
                checks.append(_check("opening", "warn", "The first 15 seconds don't echo the title",
                                     "Confirm the click: say what the title promised in the first sentence."))
            else:
                checks.append(_check("opening", "pass", "The opening echoes the title",
                                     "Shared words: " + ", ".join(shared[:5])))
        m = PITCH.search(early)
        if m:
            checks.append(_check("opening", "warn", f"\"{m.group(0)}\" in the first 30 seconds",
                                 "A channel intro or subscribe pitch before the payoff is the most common cause of "
                                 "the early drop. Move it after the payoff."))

    # --- edit -------------------------------------------------------------------------------------
    if cues:
        edl = deadair.analyse(cues, words=words)
        share = edl["removed"] / edl["duration"] if edl["duration"] else 0.0
        n_review = sum(1 for c in edl["cuts"] if c["review"])
        kinds = {k: sum(1 for c in edl["cuts"] if c["kind"] == k) for k in ("DEAD", "FILLER", "REPEAT")}
        n = lambda k, one, many: f"{kinds[k]} {one if kinds[k] == 1 else many}"  # noqa: E731
        detail = (f"{n('DEAD', 'pause', 'pauses')}, {n('FILLER', 'filler', 'fillers')}, {n('REPEAT', 'retake', 'retakes')}; "
                  f"{edl['removed']:.1f}s of {edl['duration']:.1f}s."
                  + (f" {n_review} pause(s) may be deliberate: listen before cutting." if n_review else ""))
        if share > DEAD_AIR_WARN:
            checks.append(_check("edit", "warn", f"{share * 100:.0f}% could be cut", detail + " Run yt-deadair for the list."))
        else:
            checks.append(_check("edit", "pass", f"Tight edit: {share * 100:.0f}% removable", detail))

    # --- description ------------------------------------------------------------------------------
    if description is None:
        checks.append(_check("description", "warn", "No description given",
                             "The first two lines are the search snippet: say what the video gives, in the words people type."))
    else:
        size = len(description.encode("utf-8"))
        if size > DESCRIPTION_MAX_BYTES:
            checks.append(_check("description", "fail", f"Description is {size} bytes",
                                 f"YouTube's limit is {DESCRIPTION_MAX_BYTES}. It will be rejected."))
        if "<" in description or ">" in description:
            checks.append(_check("description", "fail", "Description contains < or >",
                                 "YouTube rejects these characters in descriptions."))
        ch = parse_description_chapters(description)
        if ch:
            broken = check_chapters(ch, video_seconds)
            if broken:
                checks.append(_check("description", "fail", "Chapters won't show on YouTube", "; ".join(broken) + "."))
            else:
                checks.append(_check("description", "pass", f"{len(ch)} chapters follow YouTube's rules",
                                     "" if video_seconds else "Video length unknown: add --transcript to check the last chapter."))
        elif cues and len(cues) >= 6:
            built = chapters_mod.build(cues)
            if built["valid"]:
                suggested = built["chapters"]
                checks.append(_check("description", "info", "No chapters in the description",
                                     f"{len(suggested)} drafted from the transcript below. Retitle them before pasting."))
        top = "\n".join([ln for ln in description.splitlines() if ln.strip()][:2])
        for q in queries:
            need = _stems(q)
            missing = sorted(need - _stems(title + "\n" + top))
            if missing:
                checks.append(_check("search", "warn", f"\"{q}\": not in the title or first two lines",
                                     "Missing: " + ", ".join(missing) + ". If it's not in the title, that's the "
                                     "bigger problem."))
            else:
                checks.append(_check("search", "pass", f"\"{q}\" is covered by the title and first two lines"))

    # --- shorts -----------------------------------------------------------------------------------
    if cues:
        found = candidates.find(cues, 20, 55, 3)
        if found:
            checks.append(_check("shorts", "info", f"{len(found)} Shorts candidate(s) ready",
                                 ", ".join(f"{c['start']:.0f}-{c['end']:.0f}s" for c in found) + ". Run yt-shorts."))
    else:
        checks.append(_check("opening", "info", "No transcript given",
                             "Add --transcript to check the opening, the edit, chapters and Shorts."))

    order = {"fail": 0, "warn": 1, "pass": 2, "info": 3}
    checks.sort(key=lambda c: order[c["status"]])
    statuses = {c["status"] for c in checks}
    verdict = "not_yet" if "fail" in statuses else "ready_with_fixes" if "warn" in statuses else "ready"
    return {"schema": SCHEMA, "verdict": verdict, "title": title,
            "counts": {s: sum(1 for c in checks if c["status"] == s) for s in ("fail", "warn", "pass", "info")},
            "checks": checks, "suggested_chapters": suggested}


VERDICT_TEXT = {"ready": "READY TO UPLOAD", "ready_with_fixes": "READY, WITH FIXES WORTH MAKING",
                "not_yet": "NOT YET: fix the failures first"}
MARK = {"fail": "x", "warn": "!", "pass": "ok", "info": "i"}


def render(r: Dict) -> str:
    c = r["counts"]
    out = [f"\n  {VERDICT_TEXT[r['verdict']]}",
           f"  {c['fail']} fail, {c['warn']} warn, {c['pass']} pass   \"{r['title']}\"\n"]
    for k in r["checks"]:
        out.append(f"  {MARK[k['status']]:>2}  {k['area']:<11} {k['title']}")
        if k["detail"]:
            out.append(f"      {'':<11} {k['detail']}")
    if r["suggested_chapters"]:
        out.append("\n  drafted chapters (retitle before pasting):")
        out += [f"    {ch['label']} {ch['draft_title']}" for ch in r["suggested_chapters"]]
    out.append("\n  Only FAIL means YouTube will reject or ignore something. WARN is judgement.\n")
    return "\n".join(out)


@guarded
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="yt-check", description=__doc__.split("\n\n")[0])
    p.add_argument("--title", required=True)
    p.add_argument("--thumb", help="thumbnail text")
    p.add_argument("--transcript", help=".srt, .vtt or whisper .json")
    p.add_argument("--description", help="text file with the description")
    p.add_argument("--query", action="append", help="a search the video should win (repeatable)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    cues, words = None, NO_WORDS
    if a.transcript:
        cues = load_cues(a.transcript)
        if not cues:
            raise InputError("no cues found in the transcript")
        words = load_words(a.transcript)
    desc = None
    if a.description:
        try:
            with open(a.description, encoding="utf-8-sig") as fh:
                desc = fh.read()
        except FileNotFoundError:
            raise InputError(f"file not found: {a.description}") from None
    r = run(a.title, a.thumb, desc, a.query, cues, words)
    print(json.dumps(r, indent=1) if a.json else render(r))
    return 1 if r["verdict"] == "not_yet" else 0


if __name__ == "__main__":
    raise SystemExit(main())
