"""yt-eval - score the tools against a labelled dataset.

    yt-eval datasets/synthetic-v1/dataset.json
    yt-eval dataset.json --json --floor 0.45 --chapters-target 7 --shorts-top 5

Runs deadair, chapters and shorts on every case with the given settings (the tools' defaults
unless overridden), compares the output with the labels and prints per-case and overall
(micro-averaged) precision, recall and F1. See youtube_intelligence.evaluation.metrics for the
definitions and docs/EVALUATION.md for how to read them.

A dataset marked "synthetic": true measures behaviour on constructed transcripts. It is useful
for catching regressions and known blind spots. It is NOT evidence of accuracy on real footage.
"""
from __future__ import annotations

import argparse
import json
from typing import Dict, List, Optional

from ..core.cli import guarded
from ..core.transcript import NO_WORDS, load_cues, load_words
from ..editing import chapters as chapters_mod
from ..editing import deadair
from ..shorts import candidates
from . import dataset as ds
from . import metrics as m

DEFAULTS = {"floor": deadair.DEFAULT_FLOOR, "words": "auto", "hold_review": False,
            "review_below": deadair.REVIEW_BELOW, "chapters_target": None, "tolerance": 3.0,
            "min_iou": 0.5, "shorts_min": 20.0, "shorts_max": 55.0, "shorts_top": 5}


def evaluate_case(case: Dict, s: Dict) -> Dict:
    cues = load_cues(case["transcript_path"])
    lab = case["labels"]
    out: Dict = {"id": case["id"], "cues": len(cues)}
    if "cuts" in lab or "keep" in lab:
        words = load_words(case["transcript_path"]) if s["words"] == "auto" else NO_WORDS
        edl = deadair.analyse(cues, s["floor"], words=words, review_below=s["review_below"],
                              hold_review=s["hold_review"])
        # only the cuts that would actually be applied count as predictions
        pred_events = [(c["start"], c["end"]) for c in edl["cuts"] if not (s["hold_review"] and c["review"])]
        pred_union = [tuple(x) for x in edl["removed_intervals"]]
        gold = lab.get("cuts", [])
        gold_iv = [(g["start"], g["end"]) for g in gold]
        r = {"time": m.time_counts(pred_union, gold_iv),
             "events": m.event_counts(pred_events, gold_iv, s["min_iou"]),
             "by_kind": {}}
        for k in sorted({g["kind"] for g in gold}):
            sub = [(g["start"], g["end"]) for g in gold if g["kind"] == k]
            r["by_kind"][k] = m.event_counts(pred_events, sub, s["min_iou"])
        keep_iv = [(k["start"], k["end"]) for k in lab.get("keep", [])]
        r["keep_seconds_cut"] = round(m.intersection_length(pred_union, keep_iv), 3)
        r["keep_seconds"] = round(m.length(keep_iv), 3)
        r["word_timings"] = edl["word_timings"]
        out["cuts"] = r
    if "chapters" in lab:
        built = chapters_mod.build(cues, s["chapters_target"])
        pred = [c["start"] for c in built["chapters"]]
        out["chapters"] = m.boundary_counts(pred, lab["chapters"], s["tolerance"])
        out["chapters"]["valid"] = built["valid"]
    if "shorts" in lab:
        found = candidates.find(cues, s["shorts_min"], s["shorts_max"], s["shorts_top"])
        pred = [(c["start"], c["end"]) for c in found]
        gold = [(g["start"], g["end"]) for g in lab["shorts"]]
        out["shorts"] = m.span_counts(pred, gold, s["min_iou"])
    return out


def _round(c: Dict) -> Dict:
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in c.items()}


def summarise(cases: List[Dict]) -> Dict:
    tot: Dict = {"cuts_time": {}, "cuts_events": {}, "by_kind": {}, "keep": {}, "chapters": {}, "shorts": {}}
    for c in cases:
        if "cuts" in c:
            tot["cuts_time"] = m.add_counts(tot["cuts_time"], c["cuts"]["time"])
            tot["cuts_events"] = m.add_counts(tot["cuts_events"], c["cuts"]["events"])
            for k, v in c["cuts"]["by_kind"].items():
                tot["by_kind"][k] = m.add_counts(tot["by_kind"].get(k, {}), v)
            tot["keep"] = m.add_counts(tot["keep"], {"cut": c["cuts"]["keep_seconds_cut"],
                                                     "total": c["cuts"]["keep_seconds"]})
        if "chapters" in c:
            tot["chapters"] = m.add_counts(tot["chapters"], {k: c["chapters"][k] for k in ("tp", "pred", "gold")})
        if "shorts" in c:
            tot["shorts"] = m.add_counts(tot["shorts"], c["shorts"])
    s: Dict = {}
    if tot["cuts_time"]:
        t, e = tot["cuts_time"], tot["cuts_events"]
        s["cuts_time"] = m.prf(t["tp"], t["pred"], t["gold"])
        s["cuts_events"] = m.prf(e["tp"], e["pred"], e["gold"])
        s["cuts_recall_by_kind"] = {k: round(v["tp"] / v["gold"], 4) if v["gold"] else None
                                    for k, v in sorted(tot["by_kind"].items())}
        s["keep_seconds_cut"] = round(tot["keep"].get("cut", 0.0), 3)
        s["keep_seconds_total"] = round(tot["keep"].get("total", 0.0), 3)
    if tot["chapters"]:
        c = tot["chapters"]
        s["chapters"] = m.prf(c["tp"], c["pred"], c["gold"])
    if tot["shorts"]:
        s["shorts"] = m.span_prf(tot["shorts"])
    return s


def run(path: str, settings: Optional[Dict] = None) -> Dict:
    s = dict(DEFAULTS, **(settings or {}))
    d = ds.load(path)
    cases = [evaluate_case(c, s) for c in d["cases"]]
    for c in cases:
        if "cuts" in c:
            c["cuts"]["time"] = _round(c["cuts"]["time"])
    return {"dataset": d.get("name", path), "synthetic": d["synthetic"], "settings": s,
            "summary": summarise(cases), "cases": cases}


def _fmt(x: Dict) -> str:
    return f"P {x['precision']:.2f}  R {x['recall']:.2f}  F1 {x['f1']:.2f}"


def render(r: Dict) -> str:
    out = [f"\n  {r['dataset']}   {len(r['cases'])} cases" +
           ("   SYNTHETIC - regression signal only, not real-world accuracy" if r["synthetic"] else "")]
    out.append("")
    for c in r["cases"]:
        parts = [f"  {c['id']:<28}"]
        if "cuts" in c:
            t, e = c["cuts"]["time"], c["cuts"]["events"]
            pt = m.prf(t["tp"], t["pred"], t["gold"])
            pe = m.prf(e["tp"], e["pred"], e["gold"])
            parts.append(f"cuts t-F1 {pt['f1']:.2f} ev-F1 {pe['f1']:.2f} keep-cut {c['cuts']['keep_seconds_cut']:.1f}s")
        if "chapters" in c:
            x = c["chapters"]
            parts.append(f"chapters {x['tp']}/{x['gold']} found, {x['pred']} proposed")
        if "shorts" in c:
            x = c["shorts"]
            parts.append(f"shorts {x['gold_hit']}/{x['gold']} found, {x['tp']}/{x['pred']} hits")
        out.append("  ".join(parts))
    s = r["summary"]
    out.append("\n  OVERALL (micro-averaged)")
    if "cuts_time" in s:
        out.append(f"    cuts, by seconds      {_fmt(s['cuts_time'])}")
        out.append(f"    cuts, by event        {_fmt(s['cuts_events'])}")
        out.append("    recall by kind        " + "  ".join(f"{k} {v:.2f}" for k, v in s["cuts_recall_by_kind"].items() if v is not None))
        out.append(f"    keep regions cut      {s['keep_seconds_cut']:.2f}s of {s['keep_seconds_total']:.2f}s")
    if "chapters" in s:
        out.append(f"    chapter boundaries    {_fmt(s['chapters'])}   (+/-{r['settings']['tolerance']}s)")
    if "shorts" in s:
        out.append(f"    shorts candidates     {_fmt(s['shorts'])}   (IoU >= {r['settings']['min_iou']})")
    out.append("")
    return "\n".join(out)


@guarded
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="yt-eval", description=__doc__.split("\n\n")[0])
    p.add_argument("dataset")
    p.add_argument("--floor", type=float, default=DEFAULTS["floor"])
    p.add_argument("--words", choices=["auto", "off"], default="auto")
    p.add_argument("--hold-review", action="store_true", help="score the cut with review-marked pauses held back")
    p.add_argument("--chapters-target", type=int, default=None, help="default: derived from length, as yt-chapters")
    p.add_argument("--tolerance", type=float, default=DEFAULTS["tolerance"], help="chapter match window, seconds")
    p.add_argument("--min-iou", type=float, default=DEFAULTS["min_iou"])
    p.add_argument("--shorts-top", type=int, default=DEFAULTS["shorts_top"])
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    r = run(a.dataset, {"floor": a.floor, "words": a.words, "hold_review": a.hold_review,
                        "chapters_target": a.chapters_target, "tolerance": a.tolerance,
                        "min_iou": a.min_iou, "shorts_top": a.shorts_top})
    print(json.dumps(r, indent=1) if a.json else render(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
