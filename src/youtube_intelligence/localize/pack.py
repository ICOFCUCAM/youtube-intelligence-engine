"""yt-localize - translate titles, descriptions and captions without breaking them.

    yt-localize export --title "..." --description d.txt --transcript talk.srt --lang es,fr --out pack.json
    # translate: fill "translations" in pack.json (the /yt-localize skill does this with Claude,
    # or send the file to a translator)
    yt-localize check pack.json
    yt-localize build pack.json --lang es --out-dir dist/

The engine does not translate. It makes translation safe to do and safe to use:

  export  one unit per piece of text: the title, each description line, each caption. Caption
          timings are kept; for chapter lines only the name is translated, never the timestamp.
          Links, @handles, #hashtags, emails and promo codes (HOOKS20, or the word after "code")
          are listed as "keep exactly".
  check   per language. FAIL: a unit not translated, a "keep exactly" token changed or missing, a
          title over 100 characters, a description over 5,000 bytes, "<" or ">", a translation
          with a line break where none is allowed, or chapters that no longer follow YouTube's
          rules. WARN: captions faster than 20 characters per second, or too long for two lines of
          about 42 characters (common subtitle limits), or a translation identical to the source.
  build   writes <lang>.title.txt, <lang>.description.txt and <lang>.srt with the source
          timings, captions wrapped into at most two balanced lines, only for languages with no FAIL.

Machine and AI translation can be wrong in ways these checks cannot see. Have a fluent speaker
review before publishing; nothing here publishes. ICOFCUCAM addition.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Dict, List, Optional

from ..core.cli import guarded
from ..core.errors import InputError
from ..core.transcript import load_cues
from ..preflight.check import CHAPTER_LINE, DESCRIPTION_MAX_BYTES, TITLE_MAX, check_chapters, parse_description_chapters

SCHEMA = "youtube-intelligence/localization-pack@1"
LANG = re.compile(r"^[a-z]{2,3}(?:-(?:[A-Z]{2}|[A-Z][a-z]{3}|\d{3}))?$")
# Links, emails, @handles, #hashtags, and promo codes: a capitalised token with a digit (HOOKS20),
# or whatever follows "code"/"coupon" (code HOOKS). Plain capitals (AMAZING) are words, not codes.
PROTECT = re.compile(r"https?://\S+|www\.\S+|[\w.+-]+@[\w-]+\.[\w.-]+|(?<!\w)[@#][\w.]+|\b[A-Z][A-Z0-9]*\d[A-Z0-9]*\b")
CODE_AFTER = re.compile(r"\b(?:code|coupon)\s+([A-Za-z0-9]{3,})", re.I)
MAX_CPS = 20.0
MAX_LINE = 42


def _protected(text: str) -> List[str]:
    found = {m.group(0).rstrip(".,;:!?)") for m in PROTECT.finditer(text)}
    found |= {m.group(1) for m in CODE_AFTER.finditer(text)}
    return sorted(found)


def wrap(text: str, width: int = MAX_LINE) -> str:
    """Subtitle convention: up to two lines of about `width` characters. A longer single line is
    split at the space that best balances the two halves."""
    t = " ".join(text.split())
    if len(t) <= width or "\n" in text:
        return text.strip() if "\n" in text else t
    spaces = [i for i, ch in enumerate(t) if ch == " "]
    if not spaces:
        return t
    best = min(spaces, key=lambda i: (max(i, len(t) - i - 1) > width, abs(len(t) / 2 - i)))
    return t[:best] + "\n" + t[best + 1:]


def _ts(x: float) -> str:
    h, r = divmod(x, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")


def export(title: str, description: Optional[str], cues, langs: List[str], source_lang: str = "en") -> Dict:
    if not isinstance(title, str) or not title.strip():
        raise InputError("a title is required")
    langs = [l.strip() for l in langs if l.strip()]
    if not langs:
        raise InputError("give at least one target language, e.g. --lang es,fr")
    for l in langs + [source_lang]:
        if not LANG.match(l):
            raise InputError(f"{l!r} is not a language code like es, fr, pt-BR or zh-Hans")
    if source_lang in langs or len(set(langs)) != len(langs):
        raise InputError("target languages must be distinct and differ from the source language")
    empty = {l: "" for l in langs}
    units = [{"id": "title", "kind": "title", "source": title.strip(), "keep": _protected(title), "translations": dict(empty)}]
    if description is not None:
        for n, line in enumerate(description.splitlines(), 1):
            if not line.strip():
                units.append({"id": f"desc-{n:03d}", "kind": "blank", "source": "", "keep": [], "translations": {}})
                continue
            m = CHAPTER_LINE.match(line)
            if m:
                units.append({"id": f"desc-{n:03d}", "kind": "chapter", "timestamp": m.group(2),
                              "source": m.group(3), "keep": _protected(m.group(3)), "translations": dict(empty)})
            else:
                units.append({"id": f"desc-{n:03d}", "kind": "description", "source": line,
                              "keep": _protected(line), "translations": dict(empty)})
    for n, c in enumerate(cues or [], 1):
        units.append({"id": f"cue-{n:04d}", "kind": "caption", "start": round(c.start, 3), "end": round(c.end, 3),
                      "source": c.text, "keep": _protected(c.text), "translations": dict(empty)})
    return {"schema": SCHEMA, "source_lang": source_lang, "targets": langs,
            "instructions": "Fill each unit's translations. Keep every 'keep' item exactly as written. Do not "
                            "translate chapter timestamps (they are stored separately). Keep captions short "
                            "enough to read in their time. Have a fluent speaker review before publishing.",
            "units": units}


def _assemble_description(pack: Dict, lang: str) -> str:
    lines = []
    for u in pack["units"]:
        if u["kind"] == "blank":
            lines.append("")
        elif u["kind"] == "chapter":
            lines.append(f"{u['timestamp']} {u['translations'].get(lang, '')}")
        elif u["kind"] == "description":
            lines.append(u["translations"].get(lang, ""))
    return "\n".join(lines)


def _has_description(pack: Dict) -> bool:
    return any(u["kind"] in ("description", "chapter", "blank") for u in pack["units"])


def validate_pack(pack) -> None:
    if not isinstance(pack, dict) or pack.get("schema") != SCHEMA:
        raise InputError(f"not a {SCHEMA} file (run yt-localize export)")
    if not isinstance(pack.get("targets"), list) or not isinstance(pack.get("units"), list):
        raise InputError("the pack is missing targets or units")
    for u in pack["units"]:
        if not isinstance(u, dict) or "id" not in u or "kind" not in u or not isinstance(u.get("translations", {}), dict):
            raise InputError("the pack has a malformed unit")


def check(pack: Dict) -> Dict:
    validate_pack(pack)
    out = {}
    for lang in pack["targets"]:
        problems: List[Dict] = []

        def add(status, unit, msg):
            problems.append({"status": status, "unit": unit, "message": msg})

        for u in pack["units"]:
            if u["kind"] == "blank":
                continue
            t = u["translations"].get(lang)
            if not isinstance(t, str) or not t.strip():
                add("fail", u["id"], "not translated")
                continue
            for k in u.get("keep", []):
                if k not in t:
                    add("fail", u["id"], f"\"{k}\" must stay exactly as written")
            if "\n" in t and u["kind"] != "caption":
                add("fail", u["id"], "line break inside a single line")
            if u["kind"] in ("title", "description", "chapter") and ("<" in t or ">" in t):
                add("fail", u["id"], "YouTube rejects < and > in titles and descriptions")
            if u["kind"] == "title" and len(t.strip()) > TITLE_MAX:
                add("fail", u["id"], f"title is {len(t.strip())} characters; YouTube's limit is {TITLE_MAX}")
            if u["kind"] == "caption":
                secs = max(u["end"] - u["start"], 0.001)
                cps = len(t.replace("\n", " ")) / secs
                if cps > MAX_CPS:
                    add("warn", u["id"], f"{cps:.0f} characters per second; over {MAX_CPS:.0f} is hard to read in time")
                lines = wrap(t).splitlines()
                long = [ln for ln in lines if len(ln) > MAX_LINE]
                if len(lines) > 2 or long:
                    worst = max(len(ln) for ln in lines)
                    add("warn", u["id"], f"needs {len(lines)} line(s), the longest {worst} characters; "
                                         f"subtitles fit 2 lines of about {MAX_LINE} - shorten it")
            if t.strip() == u["source"].strip() and not u.get("keep") and len(u["source"].split()) > 2:
                add("warn", u["id"], "identical to the source - left untranslated?")
        if _has_description(pack) and not any(p["status"] == "fail" and p["message"] == "not translated" for p in problems):
            desc = _assemble_description(pack, lang)
            size = len(desc.encode("utf-8"))
            if size > DESCRIPTION_MAX_BYTES:
                add("fail", "description", f"description is {size} bytes; YouTube's limit is {DESCRIPTION_MAX_BYTES}")
            ch = parse_description_chapters(desc)
            if ch:
                broken = check_chapters(ch, None)
                if broken:
                    add("fail", "description", "chapters won't show: " + "; ".join(broken))
        fails = sum(1 for p in problems if p["status"] == "fail")
        warns = len(problems) - fails
        out[lang] = {"ready": fails == 0, "fails": fails, "warns": warns, "problems": problems}
    return {"schema": "youtube-intelligence/localization-check@1", "languages": out}


def build(pack: Dict, lang: str) -> Dict[str, str]:
    validate_pack(pack)
    if lang not in pack["targets"]:
        raise InputError(f"{lang!r} is not a target language in this pack")
    result = check(pack)["languages"][lang]
    if not result["ready"]:
        first = result["problems"][0]
        raise InputError(f"{lang} has {result['fails']} failing check(s), e.g. {first['unit']}: {first['message']}. "
                         "Run yt-localize check and fix them first")
    files = {"title.txt": next(u for u in pack["units"] if u["kind"] == "title")["translations"][lang].strip() + "\n"}
    if _has_description(pack):
        files["description.txt"] = _assemble_description(pack, lang) + "\n"
    caps = [u for u in pack["units"] if u["kind"] == "caption"]
    if caps:
        files["srt"] = "".join(f"{n}\n{_ts(u['start'])} --> {_ts(u['end'])}\n{wrap(u['translations'][lang])}\n\n"
                               for n, u in enumerate(caps, 1))
    return files


def render_check(r: Dict) -> str:
    out = [""]
    for lang, v in r["languages"].items():
        state = "READY" if v["ready"] else "NOT READY"
        out.append(f"  {lang:<8} {state:<10} {v['fails']} fail, {v['warns']} warn")
        for p in v["problems"][:12]:
            out.append(f"     {'x' if p['status'] == 'fail' else '!'}  {p['unit']:<11} {p['message']}")
        if len(v["problems"]) > 12:
            out.append(f"     ... and {len(v['problems']) - 12} more (use --json)")
    out.append("\n  Checks catch broken structure, not bad translation. Have a fluent speaker review.\n")
    return "\n".join(out)


def _load(path: str) -> Dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise InputError(f"file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise InputError(f"{path} is not valid JSON ({exc.msg} at line {exc.lineno})") from None


@guarded
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="yt-localize", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="make a translation pack")
    ex.add_argument("--title", required=True)
    ex.add_argument("--description")
    ex.add_argument("--transcript")
    ex.add_argument("--lang", required=True, help="target languages, comma-separated, e.g. es,fr,pt-BR")
    ex.add_argument("--source-lang", default="en")
    ex.add_argument("--out")
    ck = sub.add_parser("check", help="check a filled pack, per language")
    ck.add_argument("pack")
    ck.add_argument("--json", action="store_true")
    bd = sub.add_parser("build", help="write the translated files for one language")
    bd.add_argument("pack")
    bd.add_argument("--lang", required=True)
    bd.add_argument("--out-dir", required=True)
    a = p.parse_args(argv)
    if a.cmd == "export":
        desc = None
        if a.description:
            try:
                with open(a.description, encoding="utf-8-sig") as fh:
                    desc = fh.read()
            except FileNotFoundError:
                raise InputError(f"file not found: {a.description}") from None
        cues = load_cues(a.transcript) if a.transcript else None
        pack = export(a.title, desc, cues, a.lang.split(","), a.source_lang)
        text = json.dumps(pack, indent=1, ensure_ascii=False) + "\n"
        if a.out:
            with open(a.out, "w", encoding="utf-8") as fh:
                fh.write(text)
            print(f"wrote {len(pack['units'])} units for {', '.join(pack['targets'])} to {a.out}", file=sys.stderr)
        else:
            sys.stdout.write(text)
        return 0
    if a.cmd == "check":
        r = check(_load(a.pack))
        print(json.dumps(r, indent=1, ensure_ascii=False) if a.json else render_check(r))
        return 0 if all(v["ready"] for v in r["languages"].values()) else 1
    files = build(_load(a.pack), a.lang)
    os.makedirs(a.out_dir, exist_ok=True)
    for name, content in files.items():
        path = os.path.join(a.out_dir, f"{a.lang}.{name}")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        print(f"wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
