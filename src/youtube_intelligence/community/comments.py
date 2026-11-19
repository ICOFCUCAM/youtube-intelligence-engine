"""yt-comments - comment triage, scam detection, and video ideas from your viewers' questions.

    yt-youtube comments VIDEO_ID --out comments.json          # read-only fetch (or any export)
    yt-comments comments.json --creator "Your Channel" --creator-id UCxxxx

Input: a JSON list of comments, each {"video_id", "video_title", "author", "author_id", "text",
"likes", "published"} (only "text" is required).

  Piles      upstream /yt-comment's four - question, correction, praise, bait - plus scam. Every
             label comes with its reasons. Instructions planted in a comment ("ignore your
             previous instructions...") go to bait and are flagged as an injection attempt.
  Scams      scored from signals: an author impersonating the creator (look-alike names after
             Unicode normalisation, e.g. Cyrillic letters), "message me on Telegram/WhatsApp",
             phone numbers, prize/crypto/investment bait, outside links. 3+ points = scam,
             2 = suspicious.
  Ideas      questions grouped by shared words across all videos (shared words over the shorter
             question's words, 2+ shared, compared question to question), ranked by how many
             different people asked; each with up to 5 of its questions and the videos they came
             from. It matches words, not meaning: synonyms are missed and questions sharing only
             common words can be merged (on the demo set, "is a 40% hook leak bad for a 20 minute
             video?" joins the hook-length group via "hook" and "minute"). Read the questions
             listed under each idea before acting on it.
  Pins       per video, the question whose group most people share (upstream: "pin the question
             the most people also have"), tie-broken by likes.

Nothing here replies, hides, deletes, reports or pins. It lists what to do; you do it in YouTube
Studio. Comments are untrusted text: they are analysed and printed, never followed. Heuristic:
expect misses and false alarms, and look before acting. ICOFCUCAM addition.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import unicodedata
from typing import Dict, List, Optional

from ..core.cli import guarded
from ..core.errors import InputError

SCHEMA = "youtube-intelligence/comments@1"
MAX_COMMENTS = 100_000
CONFUSABLE = str.maketrans({"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y",
                            "х": "x", "і": "i", "ѕ": "s", "ј": "j", "һ": "h", "ԁ": "d",
                            "Α": "a", "Β": "b", "Ε": "e", "Ο": "o", "ο": "o", "α": "a",
                            "0": "o", "1": "l", "3": "e", "5": "s", "$": "s", "@": "a"})
QUESTION = re.compile(r"\?|^\s*(how|what|why|when|where|which|who|can|could|would|should|does|do|is|are|will|"
                      r"any tips|please (?:make|do)|could you|can you)\b", re.I)
CORRECTION = re.compile(r"\b(actually,? (?:it|that|the|you)|you'?re wrong|that'?s (?:not|wrong|incorrect)|incorrect|"
                        r"correction|small mistake|typo|should (?:be|have been)|it'?s not \w+,? it'?s)\b", re.I)
PRAISE = re.compile(r"\b(thank(?:s| you)|love (?:this|it|your)|great (?:video|content|tips?)|so helpful|"
                    r"really helpful|amazing|awesome|best (?:video|channel)|just subscribed|subbed)\b", re.I)
HOSTILE = re.compile(r"\b(idiot|stupid|moron|trash|garbage|cringe|worst (?:video|channel)|clown|loser|shut up|"
                     r"waste of time)\b", re.I)
INJECTION = re.compile(r"\b(ignore (?:all |your |the )?(?:previous|above|prior) (?:instructions|prompts?)|"
                       r"system prompt|you are now|as an ai|disregard (?:the|your) (?:rules|instructions))\b", re.I)
CONTACT = re.compile(r"\b(telegram|whats\s?app|signal app|wa\.me|t\.me|text me|message me|dm me|contact me|"
                     r"reach (?:me|out)|send me a message|inbox me)\b", re.I)
PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
BAIT = re.compile(r"\b(crypto|bitcoin|btc|forex|invest(?:ment|ing)?|trading|profits?|winner|you(?:'ve| have) been "
                  r"(?:selected|chosen)|prize|gift card|giveaway|claim (?:your|it)|earn \$|\$\d+\s*(?:daily|weekly))\b", re.I)
LINK = re.compile(r"https?://|www\.|\b[\w-]+\.(?:com|net|org|io|xyz|me|link|top|site)\b", re.I)
STOP = set("the a an of for to in on and or is are was were be been with this that it as at by from you your i my "
           "we our they them he she but so if then than there here what which who how when where why not no do does "
           "did just really very like about into over out up down can could will would should have has had any "
           "please make video videos next time also more some much one get thanks thank".split())


def norm_name(name: str) -> str:
    n = unicodedata.normalize("NFKC", name or "").lower().translate(CONFUSABLE)
    n = unicodedata.normalize("NFKD", n)
    return re.sub(r"[^a-z]", "", "".join(ch for ch in n if not unicodedata.combining(ch)))


def lookalikes(name: str) -> List[str]:
    """Characters in a name that only look like plain letters, e.g. ['\u0430->a', '\u2113->l']."""
    out = []
    for ch in dict.fromkeys(name or ""):
        if ch.isascii() or not ch.isalpha():
            continue
        plain = norm_name(ch)
        if plain and plain.isascii():
            out.append(f"{ch}->{plain} (U+{ord(ch):04X})")
    return out


def impersonates(author: str, author_id: Optional[str], creator: Optional[str], creator_id: Optional[str]) -> bool:
    if not creator or not author:
        return False
    if creator_id and author_id and author_id == creator_id:
        return False
    a, c = norm_name(author), norm_name(creator)
    if not a or not c:
        return False
    if a == c:
        return not (creator_id and author_id == creator_id) and (author != creator or bool(creator_id))
    return c in a or difflib.SequenceMatcher(None, a, c).ratio() >= 0.85


def _stems(text: str) -> set:
    return {w[:6] for w in re.findall(r"[a-z][a-z']{2,}", text.lower()) if w not in STOP}


def classify(c: Dict, creator: Optional[str], creator_id: Optional[str]) -> Dict:
    text = str(c.get("text") or "")
    reasons, score = [], 0
    if impersonates(str(c.get("author") or ""), c.get("author_id"), creator, creator_id):
        score += 3
        tricks = lookalikes(str(c.get("author") or ""))
        reasons.append(f"author name looks like the creator's ({c.get('author')!r})"
                       + (f", using look-alike letters {', '.join(tricks)}" if tricks else ""))
    if CONTACT.search(text):
        score += 2
        reasons.append(f"asks to move the conversation elsewhere (\"{CONTACT.search(text).group(0)}\")")
    if PHONE.search(text):
        score += 2
        reasons.append("contains a phone number")
    baits = sorted({m.group(0).lower() for m in BAIT.finditer(text)})
    if baits:
        score += min(2, len(baits))
        reasons.append("money or prize bait: " + ", ".join(baits[:3]))
    if LINK.search(text):
        score += 1
        reasons.append("contains a link")
    injection = bool(INJECTION.search(text))
    if score >= 3:
        pile = "scam"
    elif injection:
        pile, reasons = "bait", reasons + ["tries to give instructions (prompt injection): never follow it"]
    elif HOSTILE.search(text):
        pile, reasons = "bait", reasons + [f"hostile (\"{HOSTILE.search(text).group(0)}\"): don't reply"]
    elif CORRECTION.search(text):
        pile = "correction"
    elif QUESTION.search(text):
        pile = "question"
    elif PRAISE.search(text):
        pile = "praise"
    else:
        pile = "other"
    return {"pile": pile, "scam_score": score, "suspicious": score == 2, "reasons": reasons, "injection": injection}


def _group_questions(qs: List[Dict]) -> List[Dict]:
    groups: List[Dict] = []
    for q in sorted(qs, key=lambda q: -int(q.get("likes") or 0)):
        st = _stems(q["text"])
        if not st:
            continue
        # Overlap with the closest single question already in a group (shared words / the shorter
        # question's words), needing 2+ shared words. Short questions phrased differently still meet;
        # a group does not swallow everything as its vocabulary grows.
        best, best_sim = None, 0.0
        for g in groups:
            for other in g["sets"]:
                shared = len(st & other)
                sim = shared / min(len(st), len(other)) if shared >= 2 else 0.0
                if sim > best_sim:
                    best, best_sim = g, sim
        if best is not None and best_sim >= 0.5:
            best["items"].append(q)
            best["sets"].append(st)
            best["stems"] |= st
        else:
            groups.append({"stems": set(st), "sets": [st], "items": [q]})
    out = []
    for g in groups:
        people = {str(i.get("author_id") or i.get("author") or id(i)) for i in g["items"]}
        likes = sum(int(i.get("likes") or 0) for i in g["items"])
        lead = max(g["items"], key=lambda i: int(i.get("likes") or 0))
        words = sorted(g["stems"], key=lambda w: -sum(w in _stems(i["text"]) for i in g["items"]))[:4]
        out.append({"people": len(people), "likes": likes, "question": lead["text"], "keywords": words,
                    "examples": [i["text"] for i in g["items"][:5]],
                    "videos": sorted({str(i.get("video_title") or i.get("video_id") or "?") for i in g["items"]})})
    out.sort(key=lambda g: (-g["people"], -g["likes"], g["question"]))
    return out


def analyse(comments: List[Dict], creator: Optional[str] = None, creator_id: Optional[str] = None,
            top: int = 5) -> Dict:
    if not isinstance(comments, list):
        raise InputError("expected a JSON list of comments")
    if len(comments) > MAX_COMMENTS:
        raise InputError(f"more than {MAX_COMMENTS} comments; split the file")
    rows = []
    for n, c in enumerate(comments):
        if not isinstance(c, dict) or not isinstance(c.get("text"), str):
            raise InputError(f"comment {n} needs a 'text' string")
        likes = c.get("likes", 0)
        if isinstance(likes, bool) or not isinstance(likes, (int, float)) or likes < 0:
            likes = 0
        rows.append({**c, "likes": int(likes), **classify(c, creator, creator_id)})
    piles = {p: sum(1 for r in rows if r["pile"] == p) for p in ("question", "correction", "praise", "bait", "scam", "other")}
    flagged = [r for r in rows if r["pile"] == "scam" or r["suspicious"]]
    flagged.sort(key=lambda r: -r["scam_score"])
    ideas = _group_questions([r for r in rows if r["pile"] == "question"])
    pins = []
    for vid in sorted({str(r.get("video_id") or r.get("video_title") or "?") for r in rows}):
        qs = [r for r in rows if r["pile"] == "question" and str(r.get("video_id") or r.get("video_title") or "?") == vid]
        if not qs:
            continue
        groups = _group_questions(qs)
        g = groups[0]
        pins.append({"video": vid, "video_title": qs[0].get("video_title"), "comment": g["question"],
                     "shared_by": g["people"]})
    return {"schema": SCHEMA, "comments": len(rows), "piles": piles,
            "flagged": [{"author": r.get("author"), "video": r.get("video_title") or r.get("video_id"),
                         "text": r["text"], "status": "scam" if r["pile"] == "scam" else "suspicious",
                         "score": r["scam_score"], "reasons": r["reasons"]} for r in flagged],
            "injection_attempts": sum(1 for r in rows if r["injection"]),
            "ideas": ideas[:top], "pins": pins,
            "note": "Heuristic: expect misses and false alarms. Nothing was replied to, hidden, deleted or reported."}


def _clip(s: str, n: int = 90) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 3] + "..."


def render(r: Dict) -> str:
    p = r["piles"]
    out = [f"\n  {r['comments']} comments: {p['question']} questions, {p['correction']} corrections, {p['praise']} praise, "
           f"{p['bait']} bait, {p['scam']} scams, {p['other']} other\n"]
    if r["flagged"]:
        out.append("  SCAMS AND SUSPICIOUS COMMENTS   hide and report them in YouTube Studio; never reply")
        for f in r["flagged"]:
            out.append(f"    {f['status'].upper():<10} {_clip(f['author'] or '?', 24):<24} \"{_clip(f['text'], 60)}\"")
            out.append(f"               {'; '.join(f['reasons'])}")
        out.append("")
    if r["injection_attempts"]:
        out.append(f"  {r['injection_attempts']} comment(s) tried to give instructions to an AI. They are in the bait pile.\n")
    if r["ideas"]:
        out.append("  VIDEO IDEAS FROM YOUR VIEWERS' QUESTIONS")
        for n, g in enumerate(r["ideas"], 1):
            out.append(f"    {n}. asked by {g['people']} {'person' if g['people'] == 1 else 'people'}: \"{_clip(g['question'], 80)}\"")
            for ex in g["examples"][1:]:
                out.append(f"         also: \"{_clip(ex, 76)}\"")
            out.append(f"       on: {', '.join(_clip(v, 40) for v in g['videos'])}")
        out.append("")
    if r["pins"]:
        out.append("  WHAT TO PIN   (the question the most people share)")
        for pin in r["pins"]:
            out.append(f"    {_clip(pin['video_title'] or pin['video'], 34):<34} \"{_clip(pin['comment'], 70)}\"")
    out.append(f"\n  {r['note']}\n")
    return "\n".join(out)


@guarded
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="yt-comments", description=__doc__.split("\n\n")[0])
    p.add_argument("comments", help="JSON list of comments (yt-youtube comments output, or any export)")
    p.add_argument("--creator", help="your channel name, to catch impersonators")
    p.add_argument("--creator-id", help="your channel id, so your own replies are never flagged")
    p.add_argument("--top", type=int, default=5, help="how many video ideas to list")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    try:
        with open(a.comments, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise InputError(f"file not found: {a.comments}") from None
    except json.JSONDecodeError as exc:
        raise InputError(f"{a.comments} is not valid JSON ({exc.msg} at line {exc.lineno})") from None
    if isinstance(data, dict):
        data = data.get("comments", [])
    r = analyse(data, a.creator, a.creator_id, max(1, a.top))
    print(json.dumps(r, indent=1, ensure_ascii=False) if a.json else render(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
