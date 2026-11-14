"""Generate the synthetic-v1 evaluation set. Deterministic: same script, same files.

    python datasets/synthetic-v1/generate.py [out_dir]

Each talk is written as a SCRIPT of events (speech, pauses, fillers, aborted takes, section and
Short markers). Transcripts and labels are both rendered from the script, so the labels are
ground truth by construction and never derived from any tool's output.

Deliberately included, because real recordings have them and the tools are expected to struggle:
  * pauses for emphasis that an editor would KEEP (labelled "keep");
  * a filler inside a sentence ("so the, um, real problem") - a cue-level tool cannot cut it;
  * rhetorical repetition of an opening ("Every single time we...") that is NOT a retake;
  * an auto-caption rendering: lower case, no punctuation, ~7-word chunks that linger 0.35 s and
    overlap, which hides short pauses and merges fillers into speech.

Timing model: 0.38 s per word (about 158 words per minute) plus 0.2 s per utterance, 0.15 s
between utterances unless a pause is scripted. An editor's dead-air cut keeps 0.2 s each side.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
WORD, TAIL, GAP, BREATH = 0.38, 0.2, 0.15, 0.2

TUTORIAL = [
    ("say", "Your first fifteen seconds decide whether anyone stays to the end."),
    ("short_begin",),
    ("say", "Most openings fail because they summarise the video instead of asking a question."),
    ("say", "The viewer already knows the topic from the title they clicked."),
    ("say", "What they do not know is why this video is different from the last ten."),
    ("pause", 1.1, "keep"),
    ("say", "So answer that, and only that, before anything else."),
    ("say", "Confirm the title, open a gap, then prove the payoff exists."),
    ("short_end",),
    ("pause", 2.4, "cut"),
    ("section",),
    ("say", "Now the thumbnail, which most people design last and in a hurry."),
    ("filler", "um"),
    ("say", "Shrink it to the size of a postage stamp before you choose it."),
    ("abort", "Three words is the"),
    ("filler", "uh"),
    ("say", "Three words is the most a thumbnail can carry at feed size."),
    ("say", "And it should never repeat the words already sitting in the title."),
    ("pause", 1.6, "cut"),
    ("say", "Contrast matters more than colour when the image is that small."),
    ("pause", 2.9, "cut"),
    ("section",),
    ("short_begin",),
    ("say", "Retention is where the honest feedback lives, and almost nobody exports it."),
    ("say", "Open the audience retention chart in studio and download the file."),
    ("filler", "so yeah"),
    ("say", "Steep cliffs are moments where people left, usually a topic change with no signpost."),
    ("say", "A slow slide is pacing, and the fix is cutting rather than rewriting."),
    ("say", "Fix the single biggest cliff first and ignore everything else this week."),
    ("short_end",),
    ("pause", 1.0, "keep"),
    ("say", "That is the whole system, and it fits on one page."),
]

ESSAY = [
    ("say", "Every single time we changed the format, the numbers dipped for a week."),
    ("say", "Every single time we held our nerve, they came back higher than before."),
    ("pause", 1.3, "keep"),
    ("say", "That pattern took us two years to notice."),
    ("pause", 2.2, "cut"),
    ("section",),
    ("short_begin",),
    ("say", "Here is the uncomfortable part about growth on this platform."),
    ("say", "So the, {um}, real problem was never the algorithm or the thumbnails."),
    ("say", "It was that we kept abandoning ideas before they had time to work."),
    ("say", "But the audience does not see your analytics, they see a channel that wanders."),
    ("say", "Consistency is not posting often, it is being recognisable every time."),
    ("short_end",),
    ("pause", 3.1, "cut"),
    ("section",),
    ("say", "So what would we do differently with a brand new channel today?"),
    ("abort", "We would pick one format and"),
    ("filler", "hmm"),
    ("say", "We would pick one format and make thirty of them before judging anything."),
    ("say", "We would write the title and thumbnail together before recording a single frame."),
    ("pause", 1.8, "cut"),
    ("say", "And we would read every retention graph like a letter from the viewer."),
    ("filler", "you know"),
    ("say", "Because that is exactly what it is."),
]


def words(text):
    return text.replace("{um}", "um").split()


def build(script):
    """Lay the script on a timeline -> utterances, word timings and labels."""
    t, utts, labels = 0.0, [], {"cuts": [], "keep": [], "chapters": [], "shorts": []}
    pending_gap = None          # explicit pause before the next utterance
    want_chapter = want_short = False
    short_start = None
    for ev in script:
        kind = ev[0]
        if kind == "pause":
            pending_gap = (ev[1], ev[2])
            continue
        if kind == "section":
            want_chapter = True
            continue
        if kind == "short_begin":
            want_short = True
            continue
        if kind == "short_end":
            labels["shorts"].append({"start": round(short_start, 3), "end": round(utts[-1]["end"], 3)})
            continue
        text = ev[1]
        if utts:
            if pending_gap:
                g, what = pending_gap
                if what == "cut":
                    labels["cuts"].append({"start": round(t + BREATH, 3), "end": round(t + g - BREATH, 3), "kind": "DEAD"})
                else:
                    labels["keep"].append({"start": round(t, 3), "end": round(t + g, 3), "why": "pause for emphasis"})
                t += g
            else:
                t += GAP
        pending_gap = None
        w = words(text)
        dur = len(w) * WORD + TAIL
        start, end = t, t + dur
        wt = []
        for i, word in enumerate(text.split()):
            ws = start + i * WORD
            wt.append((ws, ws + WORD, word))
            if "{um}" in word:
                labels["cuts"].append({"start": round(ws, 3), "end": round(ws + WORD, 3), "kind": "FILLER",
                                       "note": "inside a sentence"})
        if kind == "filler":
            labels["cuts"].append({"start": round(start, 3), "end": round(end, 3), "kind": "FILLER"})
        if kind == "abort":
            labels["cuts"].append({"start": round(start, 3), "end": round(end, 3), "kind": "REPEAT"})
        if want_chapter:
            labels["chapters"].append(round(start, 3))
            want_chapter = False
        if want_short:
            short_start, want_short = start, False
        utts.append({"start": start, "end": end, "text": text.replace("{um}", "um"), "words": wt})
        t = end
    return utts, labels


def ts(x, sep):
    h, r = divmod(x, 3600)
    mi, s = divmod(r, 60)
    return f"{int(h):02d}:{int(mi):02d}:{s:06.3f}".replace(".", sep)


def clean_cues(utts):
    return [(u["start"], u["end"], u["text"]) for u in utts]


def auto_cues(utts):
    """Auto-caption style: lower case, no punctuation, 7-word chunks, 0.35 s linger (overlaps)."""
    stream = []
    for u in utts:
        for ws, we, w in u["words"]:
            w = re.sub(r"[^a-z' ]", "", w.replace("{um}", "um").lower())
            if w:
                stream.append((ws, we, w))
    cues, chunk = [], []
    for i, wd in enumerate(stream):
        if chunk and (len(chunk) == 7 or wd[0] - chunk[-1][1] > 1.0):
            cues.append(chunk)
            chunk = []
        chunk.append(wd)
    if chunk:
        cues.append(chunk)
    return [(c[0][0], c[-1][1] + 0.35, " ".join(w for _, _, w in c)) for c in cues]


def write_srt(path, cues):
    with open(path, "w") as f:
        for n, (a, b, t) in enumerate(cues, 1):
            f.write(f"{n}\n{ts(a, ',')} --> {ts(b, ',')}\n{t}\n\n")


def write_vtt(path, cues):
    with open(path, "w") as f:
        f.write("WEBVTT\nKind: captions\nLanguage: en\n\n")
        for a, b, t in cues:
            f.write(f"{ts(a, '.')} --> {ts(b, '.')} align:start position:0%\n{t}\n\n")


def main(out=HERE):
    cases = []
    tu, tl = build(TUTORIAL)
    es, el = build(ESSAY)
    write_srt(os.path.join(out, "tutorial-clean.srt"), clean_cues(tu))
    write_vtt(os.path.join(out, "tutorial-auto.vtt"), auto_cues(tu))
    json.dump([{"start": round(a, 3), "end": round(b, 3), "text": t} for a, b, t in clean_cues(es)],
              open(os.path.join(out, "essay-clean.json"), "w"), indent=1)
    write_vtt(os.path.join(out, "essay-auto.vtt"), auto_cues(es))
    for cid, fn, lab, note in [
        ("tutorial-clean", "tutorial-clean.srt", tl, "one cue per utterance, punctuated"),
        ("tutorial-auto", "tutorial-auto.vtt", tl, "same talk, auto-caption style"),
        ("essay-clean", "essay-clean.json", el, "Whisper-style JSON array; rhetorical repetition, inline filler"),
        ("essay-auto", "essay-auto.vtt", el, "same talk, auto-caption style"),
    ]:
        cases.append({"id": cid, "transcript": fn, "notes": note, "labels": lab})
    d = {"name": "synthetic-v1", "synthetic": True,
         "label_source": "Rendered from scripted talks by generate.py; labels are ground truth by "
                         "construction, never derived from tool output.",
         "cases": cases}
    with open(os.path.join(out, "dataset.json"), "w") as f:
        json.dump(d, f, indent=1)
        f.write("\n")


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else HERE)
