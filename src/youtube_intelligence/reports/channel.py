"""yt-report - a channel report: recent uploads, packaging, retention, and ONE thing to fix.

    yt-youtube channel-videos --handle @YourChannel --out videos.json        # or any collected list
    yt-youtube retention VIDEO_ID --start ... --end ... --out retention.csv   # optional, per video
    yt-report videos.json --retention VIDEO_ID=retention.csv --out report.html
    yt-report videos.json --format md

This is the core of the planned "Creator" weekly report, built only from the existing tools:
outliers (multiple of the channel's own median), the title lint, the hook-formula classifier and
the retention reader. It follows the upstream /yt-audit rule: end in ONE fix, not twenty.

The "one fix" is chosen by fixed rules, in this order, and the report says which rule fired:
  1. the worst opening, if any video loses 25 points or more in its first 30 seconds
     (the retention reader's "leaking" line);
  2. otherwise the weakest title flagged for hype, claims, vagueness or shouting;
  3. otherwise the steepest single retention cliff;
  4. otherwise: nothing urgent.
Scores are heuristics (see docs/TOOL_REVIEW.md); the report repeats that. Titles and channel names
are third-party text and are HTML-escaped. The HTML is self-contained: no scripts, no external
resources.
"""
from __future__ import annotations

import argparse
import html
import json
import statistics
import sys
from typing import Dict, List, Optional, Tuple

from ..analytics import retention as ret
from ..core.cli import guarded
from ..core.errors import InputError
from ..core.formulas import classify
from ..packaging.title import check
from ..research.outliers import load as load_videos, parse_views

HOOK_LEAKING = 25.0
PACKAGING_KINDS = ("claim", "vague", "shouting", "numbers", "front-load", "length")
CAVEATS = [
    "Scores are word-pattern heuristics. They point at what to look at; they do not predict views.",
    "Multiples compare each video with this channel's own median, so they need at least 4 videos "
    "and do not adjust for video age.",
    "Retention depends on sample size, video age, format and audience. A curve from a few hundred "
    "views is mostly noise.",
]


def _fmt_time(sec: Optional[float]) -> str:
    if sec is None:
        return "?"
    s = int(round(sec))
    return f"{s // 60}:{s % 60:02d}"


def build(videos: List[Dict], retention_files: Optional[Dict[str, str]] = None,
          channel: Optional[str] = None, generated_for: str = "") -> Dict:
    rows = [v for v in videos if isinstance(v, dict)]
    names = sorted({str(v.get("channel", "?")) for v in rows})
    if channel is None:
        if len(names) != 1:
            raise InputError(f"the list has {len(names)} channels ({', '.join(names[:5])}); pick one with --channel")
        channel = names[0]
    rows = [v for v in rows if str(v.get("channel", "?")) == channel]
    if not rows:
        raise InputError(f"no videos for channel {channel!r}")
    for v in rows:
        v["_views"] = parse_views(v.get("views"))
    counted = [v["_views"] for v in rows if v["_views"] is not None]
    median = statistics.median(counted) if len(counted) >= 4 else None

    retention_files = retention_files or {}
    by_id = {str(v.get("video_id") or ""): v for v in rows}
    unknown = [k for k in retention_files if k not in by_id]
    if unknown:
        raise InputError(f"retention given for video(s) not in the list: {', '.join(unknown)}")

    items = []
    for v in rows:
        title = str(v.get("title", ""))
        t = check(title)
        item = {
            "video_id": v.get("video_id"), "title": title, "url": str(v.get("url", "")),
            "published": v.get("published"), "views": None if v["_views"] is None else int(v["_views"]),
            "multiple": round(v["_views"] / median, 2) if (median and v["_views"] is not None) else None,
            "formula": classify(title)[0], "title_score": t["score"],
            "title_issues": [{"kind": k, "message": m} for k, m in t["issues"]], "retention": None,
        }
        vid = str(v.get("video_id") or "")
        if vid in retention_files:
            rows_, hint = ret.load_csv(retention_files[vid])
            dur = v.get("duration")
            dur = float(dur) if isinstance(dur, (int, float)) and dur > 0 else None
            r = ret.analyse(rows_, dur, "auto", hint)
            top = r["cliffs"][0] if r["cliffs"] else None
            item["retention"] = {"hook_leak": r["hook_leak"], "axis": r["axis"], "duration": dur,
                                 "top_cliff": None if top is None else {"lost": top["lost"], "at_seconds": top["at_seconds"],
                                                                         "from": top["from"]},
                                 "slide_per_unit": r["slide_per_unit"]}
        items.append(item)
    items.sort(key=lambda i: i["published"] or "", reverse=True)

    return {"schema": "youtube-intelligence/channel-report@1", "channel": channel,
            "generated_for": generated_for, "videos": items, "median_views": None if median is None else int(median),
            "focus": _focus(items), "working": _working(items), "caveats": CAVEATS}


def _focus(items: List[Dict]) -> Dict:
    with_ret = [i for i in items if i["retention"]]
    leaks = sorted(with_ret, key=lambda i: -i["retention"]["hook_leak"])
    if leaks and leaks[0]["retention"]["hook_leak"] >= HOOK_LEAKING:
        i = leaks[0]
        return {"rule": "opening", "video_id": i["video_id"], "title": i["title"],
                "headline": "Fix the first 15 seconds",
                "detail": f"{i['retention']['hook_leak']:.0f} points of viewers are lost in the first 30 seconds of "
                          f"this video. Confirm the title's promise in the first sentence and cut any intro before it.",
                "why": f"rule 1: an opening loses {HOOK_LEAKING:.0f}+ points"}
    flagged = [i for i in items if any(x["kind"] in PACKAGING_KINDS for x in i["title_issues"])]
    if flagged:
        i = min(flagged, key=lambda i: (i["title_score"], i["published"] or ""))
        first = next(x for x in i["title_issues"] if x["kind"] in PACKAGING_KINDS)
        n = len(flagged)
        return {"rule": "packaging", "video_id": i["video_id"], "title": i["title"],
                "headline": "Fix the packaging",
                "detail": f"{n} of {len(items)} titles have a packaging issue. Start with this one: {first['message']}.",
                "why": "rule 2: no opening is leaking, and titles are flagged"}
    cliffs = [i for i in with_ret if i["retention"]["top_cliff"]]
    if cliffs:
        i = max(cliffs, key=lambda i: i["retention"]["top_cliff"]["lost"])
        c = i["retention"]["top_cliff"]
        return {"rule": "cliff", "video_id": i["video_id"], "title": i["title"], "headline": "Fix one moment",
                "detail": f"{c['lost']:.1f} points leave at {_fmt_time(c['at_seconds'])}. Watch that moment: "
                          "signpost the change, or cut it.", "why": "rule 3: steepest single drop"}
    return {"rule": "none", "video_id": None, "title": None, "headline": "Nothing urgent",
            "detail": "No leaking opening, no flagged title, no sharp drop in the data given.", "why": "rule 4"}


def _working(items: List[Dict]) -> Optional[Dict]:
    ranked = [i for i in items if i["multiple"] is not None]
    if not ranked:
        return None
    best = max(ranked, key=lambda i: i["multiple"])
    if best["multiple"] < 1.5:
        return None
    return {"video_id": best["video_id"], "title": best["title"], "multiple": best["multiple"], "formula": best["formula"]}


# --- rendering ---------------------------------------------------------------------------------------
def render_markdown(r: Dict) -> str:
    e = lambda s: str(s).replace("|", "\\|")  # noqa: E731
    f = r["focus"]
    out = [f"# Channel report: {r['channel']}", ""]
    if r["generated_for"]:
        out += [f"_{r['generated_for']}_", ""]
    out += [f"## This week's one fix: {f['headline']}", ""]
    if f["title"]:
        out.append(f"**{e(f['title'])}**")
    out += [f["detail"], "", f"_Why this one: {f['why']}._", ""]
    if r["working"]:
        w = r["working"]
        out += ["## What's working", "", f"**{e(w['title'])}**: {w['multiple']}x the channel median. "
                f"Title formula: {w['formula']} (a judgement about the words, not the cause).", ""]
    out += ["## Uploads", "", "| Title | Views | vs median | Title score | Opening lost |", "| --- | ---: | ---: | ---: | ---: |"]
    for i in r["videos"]:
        hl = f"{i['retention']['hook_leak']:.0f} pts" if i["retention"] else "-"
        mult = f"{i['multiple']}x" if i["multiple"] is not None else "-"
        views = f"{i['views']:,}" if i["views"] is not None else "-"
        out.append(f"| {e(i['title'])} | {views} | {mult} | {i['title_score']} | {hl} |")
    out += ["", "## Read this before acting", ""] + [f"- {c}" for c in r["caveats"]] + [""]
    return "\n".join(out)


CSS = """
:root{--bg:#f7f6f2;--surface:#fff;--text:#1b1d1f;--muted:#5b6066;--line:#dcd9cf;--accent:#1f6f5c;--soft:#dcefe8;--warn:#9a5b00}
@media (prefers-color-scheme: dark){:root{--bg:#111315;--surface:#181b1e;--text:#e8eaec;--muted:#a3a9b0;--line:#2c3136;--accent:#4cc3a2;--soft:#183a31;--warn:#e2b25c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
main{max-width:960px;margin:0 auto;padding:36px 16px 64px}a{color:var(--accent)}
h1{font-size:clamp(26px,4.5vw,36px);letter-spacing:-.02em;margin:6px 0 4px}h2{font-size:20px;margin:34px 0 10px}
.meta{color:var(--muted);margin:0 0 22px}
.sample{background:#fdf1dc;color:#7a4700;border-radius:10px;padding:10px 14px;font-size:15px;margin:0 0 20px}
@media (prefers-color-scheme: dark){.sample{background:#3a2c12;color:#f0c77a}}
.fix{background:var(--soft);border-radius:14px;padding:22px}
.fix .k{font-size:13px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--accent);margin:0}
.fix h2{margin:4px 0 8px;font-size:26px}.fix .t{font-weight:600;margin:0 0 6px}.fix .why{color:var(--muted);font-size:14px;margin:10px 0 0}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:18px}
.tbl{width:100%;border-collapse:collapse;font-size:15px}
.wrap-tbl{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:14px}
.tbl th,.tbl td{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
.tbl th{font-size:13px;color:var(--muted);font-weight:600}.tbl td.n{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.tbl tr:last-child td{border-bottom:0}.iss{color:var(--warn);font-size:13px;display:block}
.hi{color:var(--accent);font-weight:600}.warnv{color:var(--warn);font-weight:600}
ul.cav{color:var(--muted);padding-left:20px}
"""


def render_html(r: Dict) -> str:
    e = html.escape
    f = r["focus"]
    parts = ["<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
             "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
             f"<title>Channel report: {e(r['channel'])}</title><meta name=\"color-scheme\" content=\"light dark\">",
             "<meta name=\"robots\" content=\"noindex\">", f"<style>{CSS}</style></head><body><main>",
             "<p><a href=\"/\">&larr; YouTube Intelligence Engine</a></p>",
             f"<h1>Channel report: {e(r['channel'])}</h1>"]
    if r["generated_for"]:
        parts.append(f"<p class=\"sample\">{e(r['generated_for'])}</p>")
    med = f"{r['median_views']:,}" if r["median_views"] is not None else "not enough videos"
    parts.append(f"<p class=\"meta\">{len(r['videos'])} uploads &middot; channel median {e(med)} views</p>")
    parts += ["<section class=\"fix\" aria-labelledby=\"fix-h\">", "<p class=\"k\">This week's one fix</p>",
              f"<h2 id=\"fix-h\">{e(f['headline'])}</h2>"]
    if f["title"]:
        parts.append(f"<p class=\"t\">{e(f['title'])}</p>")
    parts += [f"<p>{e(f['detail'])}</p>", f"<p class=\"why\">Why this one: {e(f['why'])}.</p>", "</section>"]
    if r["working"]:
        w = r["working"]
        parts += ["<h2>What's working</h2>", "<div class=\"card\">",
                  f"<p><strong>{e(w['title'])}</strong> got <span class=\"hi\">{w['multiple']}x</span> the channel's median views.</p>",
                  f"<p class=\"meta\" style=\"margin:0\">Title formula: {e(w['formula'])}. That describes the words, "
                  "not why it worked.</p></div>"]
    parts += ["<h2>Uploads</h2>", "<div class=\"wrap-tbl\"><table class=\"tbl\"><thead><tr><th>Title</th><th>Views</th>"
              "<th>vs median</th><th>Title score</th><th>Opening lost</th></tr></thead><tbody>"]
    for i in r["videos"]:
        iss = "".join(f"<span class=\"iss\">{e(x['kind'])}: {e(x['message'])}</span>" for x in i["title_issues"][:2])
        if i["retention"]:
            hl = i["retention"]["hook_leak"]
            cls = "warnv" if hl >= HOOK_LEAKING else ""
            hook = f"<span class=\"{cls}\">{hl:.0f} pts</span>"
        else:
            hook = "<span class=\"meta\">no export</span>"
        mult = f"{i['multiple']}x" if i["multiple"] is not None else "-"
        views = f"{i['views']:,}" if i["views"] is not None else "-"
        parts.append(f"<tr><td>{e(i['title'])}{iss}</td><td class=\"n\">{views}</td><td class=\"n\">{mult}</td>"
                     f"<td class=\"n\">{i['title_score']}</td><td class=\"n\">{hook}</td></tr>")
    parts += ["</tbody></table></div>", "<h2>Read this before acting</h2>", "<ul class=\"cav\">"]
    parts += [f"<li>{e(c)}</li>" for c in r["caveats"]]
    parts += ["</ul>", "<p class=\"meta\">Made with the open-source YouTube Intelligence Engine. "
              "It reads data; it never changes anything on your channel.</p>", "</main></body></html>"]
    return "\n".join(parts) + "\n"


def _retention_args(pairs: List[str]) -> Dict[str, str]:
    out = {}
    for p in pairs or []:
        vid, sep, path = p.partition("=")
        if not sep or not vid or not path:
            raise InputError(f"--retention takes VIDEO_ID=path.csv, got {p!r}")
        out[vid] = path
    return out


@guarded
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="yt-report", description=__doc__.split("\n\n")[0])
    p.add_argument("videos", help="JSON list of uploads (yt-youtube channel-videos output, or yt-swipe input)")
    p.add_argument("--retention", action="append", metavar="VIDEO_ID=CSV", help="retention export for a video (repeatable)")
    p.add_argument("--channel", help="which channel, if the list has several")
    p.add_argument("--format", choices=["html", "md", "json"], default="html")
    p.add_argument("--note", default="", help="a line shown under the title, e.g. the week covered")
    p.add_argument("--out")
    a = p.parse_args(argv)
    r = build(load_videos(a.videos), _retention_args(a.retention), a.channel, a.note)
    text = {"html": render_html, "md": render_markdown, "json": lambda x: json.dumps(x, indent=1) + "\n"}[a.format](r)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {a.format} report for {r['channel']} ({len(r['videos'])} uploads) to {a.out}", file=sys.stderr)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
