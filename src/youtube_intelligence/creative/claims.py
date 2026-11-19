"""yt-claims - the fact guard: find every claim in a draft that you can't back up.

    yt-claims script.md
    yt-claims script.md --voice ~/.claude/youtube/voice.md --evidence evidence.md
    yt-claims --text "I grew to 200k subscribers in 30 days" --json

Upstream's skills all say "Never invent a number, a result or a source". This checks a draft
(script, title, description, reply) for exactly that, sentence by sentence:

  BLOCKED       your own rules from voice.md: a word under "Words I never use", or a sentence that
                matches an item under "What I will not claim"
  NEEDS SOURCE  a figure (percent, money, 10x, "200,000 subscribers", "in 30 days", "#1") that is
                not in your evidence file; an unsourced citation ("studies show", "experts say");
                a result claim ("I made", "we tripled", "went from ... to ...") with nothing backing
                it
  CHECK         absolutes: guaranteed, always works, never fails, everyone, nobody

The evidence file is plain text: one verified fact per line, with where it came from, e.g.
"412,000 views on the March video (YouTube Studio, 2026-03-01)". A figure counts as backed when the
same number appears in a fact, however it is written (200k = 200,000; 40 % = 40%). The guard
checks numbers match, not that the fact is true: keep the evidence file honest.
Exit code 1 while anything is BLOCKED or NEEDS SOURCE. ICOFCUCAM addition.
"""
from __future__ import annotations

import argparse
import json
import re

from typing import Dict, List, Optional, Set

from ..core.cli import guarded
from ..core.errors import InputError

SCHEMA = "youtube-intelligence/claims@1"
UNITS = (r"subscribers?|subs|views?|followers?|videos?|uploads?|days?|weeks?|months?|years?|hours?|minutes?|"
         r"people|creators?|channels?|dollars?|euros?|pounds?|clients?|customers?|sales|downloads?|members?|students?")
FIGURE = re.compile(
    r"[$€£]\s?\d[\d,.]*\s?[kKmMbB]?(?:\s?(?:/|per|a)\s?(?:day|week|month|year|hour))?"   # money
    r"|\b\d[\d,.]*\s?(?:%|percent\b)"                                                       # percentages
    r"|\b\d+(?:\.\d+)?\s?x\b"                                                               # multipliers
    rf"|\b\d[\d,.]*\s?[kKmM]?\s+(?:{UNITS})\b"                                             # counts with units
    r"|#\s?\d+\b|\bnumber one\b|\btop \d+\b",                                               # rankings
    re.I)
RANGE = re.compile(r"\bfrom\s+([$\u20ac\u00a3]?\d[\d,.]*\s?[kKmM]?)\s+to\s+([$\u20ac\u00a3]?\d[\d,.]*\s?[kKmM]?)", re.I)
WORD_MULT = re.compile(r"\b(doubled|tripled|quadrupled|tenfold)\b", re.I)
CITATION = re.compile(r"\b(studies (?:show|prove|say)|research (?:shows|proves|says)|science (?:says|shows)|"
                      r"experts (?:say|agree)|data (?:shows|proves)|scientifically proven|it'?s (?:a )?proven)\b", re.I)
RESULT = re.compile(r"\b(?:i|we)\s+(?:made|earned|grew|gained|got|hit|reached|tripled|doubled|sold|went from)\b"
                    r"|\bwent from\b.+?\bto\b", re.I)
ABSOLUTE = re.compile(r"\b(guaranteed?|always works|never fails|works every time|100% (?:of|guaranteed|proven)|"
                      r"everyone|nobody|every single (?:time|creator|one))\b", re.I)
SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")
STOP = set("the a an of for to in on and or is are was were be been with this that it as at by from you your i my "
           "we our they them he she but so if then than there here what which who how when where why not no do does "
           "did just really very like about into over out up down can could will would should have has had".split())


def normalise(fig: str) -> Optional[str]:
    """'200k' -> '200000', '$5,000' -> '5000', '40 %' -> '40', '3x' -> '3', '#1' -> '1'."""
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s?([kKmMbB](?![a-z]))?", fig)
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    n *= {"k": 1e3, "m": 1e6, "b": 1e9}.get((m.group(2) or "").lower(), 1)
    return f"{n:g}" if n != int(n) else str(int(n))


def evidence_numbers(lines: List[str]) -> Set[str]:
    """Numbers stated in the facts. The source in brackets and any dates are ignored, so a date
    like 2026-04-15 can never 'back' a claim of 15 or 2026."""
    out = set()
    for ln in lines:
        ln = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", ln)
        ln = re.sub(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b", " ", ln)
        for m in re.finditer(r"[$€£#]?\d[\d,]*(?:\.\d+)?\s?[kKmMbB]?(?![a-z])", ln):
            v = normalise(m.group(0))
            if v:
                out.add(v)
    return out


def parse_voice(text: str) -> Dict[str, List[str]]:
    """The two voice.md sections the guard enforces. Items are bullet lines and quoted phrases."""
    sections = {"never": [], "will_not_claim": []}
    current = None
    for line in text.splitlines():
        h = re.match(r"^#{1,6}\s+(.*)$", line)
        if h:
            title = h.group(1).strip().lower()
            current = "never" if title.startswith("words i never use") else \
                "will_not_claim" if title.startswith("what i will not claim") else None
            continue
        if current is None:
            continue
        b = re.match(r"^\s*[-*]\s+(.+?)\s*$", line)
        if b:
            sections[current].append(b.group(1).strip().strip('"“”'))
        sections[current] += [q.strip() for q in re.findall(r"[\"“]([^\"”]{2,80})[\"”]", line)
                              if not b or q.strip() != b.group(1).strip().strip('"“”')]
    for k in sections:
        seen, uniq = set(), []
        for item in sections[k]:
            if item and item.lower() not in seen:
                seen.add(item.lower())
                uniq.append(item)
        sections[k] = uniq
    return sections


def _content(s: str) -> Set[str]:
    return {w for w in re.findall(r"[a-z0-9']{3,}", s.lower()) if w not in STOP}


def check(text: str, voice: Optional[str] = None, evidence: Optional[List[str]] = None) -> Dict:
    if not isinstance(text, str) or not text.strip():
        raise InputError("nothing to check: the draft is empty")
    rules = parse_voice(voice) if voice else {"never": [], "will_not_claim": []}
    backed = evidence_numbers(evidence or [])
    findings: List[Dict] = []
    for ln_no, line in enumerate(text.splitlines(), 1):
        for sm in SENTENCE.finditer(line):
            s = sm.group(0).strip()
            if not s:
                continue

            def add(kind, status, excerpt, message):
                findings.append({"line": ln_no, "sentence": s, "kind": kind, "status": status,
                                 "excerpt": excerpt, "message": message})

            low = s.lower()
            for w in rules["never"]:
                if re.search(r"(?<![a-z0-9])" + re.escape(w.lower()) + r"(?![a-z0-9])", low):
                    add("banned_word", "blocked", w, "on your 'Words I never use' list")
            for item in rules["will_not_claim"]:
                need = _content(item)
                if need and need <= _content(s):
                    add("will_not_claim", "blocked", item, "matches 'What I will not claim'")
            ranges = list(RANGE.finditer(s))
            covered = []
            for m in ranges:
                a, b = normalise(m.group(1)), normalise(m.group(2))
                ok = a in backed and b in backed
                add("figure", "backed" if ok else "needs_source", m.group(0).strip(),
                    "both numbers found in your evidence file" if ok else
                    "a before-and-after claim needs both numbers in your evidence file")
                covered.append(m.span())
            figs = [m.group(0).strip() for m in FIGURE.finditer(s)
                    if not any(a <= m.start() < b for a, b in covered)]
            for f in figs:
                v = normalise(f)
                if v and v in backed:
                    add("figure", "backed", f, "found in your evidence file")
                else:
                    add("figure", "needs_source", f, "not in your evidence file: add the source, or cut the number")
            for m in WORD_MULT.finditer(s):
                add("figure", "needs_source", m.group(0), "a multiple needs the before and after numbers, with a source")
            for m in CITATION.finditer(s):
                add("citation", "needs_source", m.group(0), "name the study or source, or cut it")
            if RESULT.search(s) and not figs and not ranges and not WORD_MULT.search(s):
                add("result", "needs_source", RESULT.search(s).group(0), "a result claim with nothing backing it")
            for m in ABSOLUTE.finditer(s):
                add("absolute", "check", m.group(0), "absolute wording: is it literally true?")
    counts = {k: sum(1 for f in findings if f["status"] == k) for k in ("blocked", "needs_source", "check", "backed")}
    clean = counts["blocked"] == 0 and counts["needs_source"] == 0
    return {"schema": SCHEMA, "clean": clean, "counts": counts, "findings": findings,
            "rules_loaded": {"never": len(rules["never"]), "will_not_claim": len(rules["will_not_claim"]),
                             "evidence_figures": len(backed)},
            "note": "The guard checks that figures match your evidence file, not that the evidence is true."}


LABEL = {"blocked": "BLOCKED", "needs_source": "NEEDS SOURCE", "check": "CHECK", "backed": "backed"}


def render(r: Dict) -> str:
    c, rl = r["counts"], r["rules_loaded"]
    out = [f"\n  {'CLEAN' if r['clean'] else 'NOT CLEAN'}: {c['blocked']} blocked, {c['needs_source']} need a source, "
           f"{c['check']} to check, {c['backed']} backed",
           f"  rules: {rl['never']} banned words, {rl['will_not_claim']} won't-claim items, "
           f"{rl['evidence_figures']} figures in evidence\n"]
    order = {"blocked": 0, "needs_source": 1, "check": 2, "backed": 3}
    for f in sorted(r["findings"], key=lambda f: (order[f["status"]], f["line"])):
        out.append(f"  {LABEL[f['status']]:<13} line {f['line']:<4} \"{f['excerpt']}\"  {f['message']}")
    if not r["findings"]:
        out.append("  no claims found")
    out.append(f"\n  {r['note']}\n")
    return "\n".join(out)


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return fh.read()
    except FileNotFoundError:
        raise InputError(f"file not found: {path}") from None


@guarded
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="yt-claims", description=__doc__.split("\n\n")[0])
    p.add_argument("draft", nargs="?", help="script, description or any text file")
    p.add_argument("--text", help="check this text instead of a file")
    p.add_argument("--voice", help="voice.md with 'Words I never use' and 'What I will not claim'")
    p.add_argument("--evidence", help="one verified fact per line, with its source")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    if a.text is None and not a.draft:
        p.print_usage()
        return 1
    text = a.text if a.text is not None else _read(a.draft)
    voice = _read(a.voice) if a.voice else None
    evidence = [ln for ln in _read(a.evidence).splitlines() if ln.strip()] if a.evidence else None
    r = check(text, voice, evidence)
    print(json.dumps(r, indent=1, ensure_ascii=False) if a.json else render(r))
    return 0 if r["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
