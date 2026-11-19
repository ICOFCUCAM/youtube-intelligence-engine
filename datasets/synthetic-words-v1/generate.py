"""Generate synthetic-words-v1: the synthetic-v1 talks rendered WITH word timings.

    python datasets/synthetic-words-v1/generate.py [out_dir]

Same scripts and the same labels as synthetic-v1 (imported from its generator by file path; the
engine is never imported, so labels cannot come from tool output). Two renderings per talk:

  *-whisper.json  Whisper-style JSON: one segment per utterance, each with a "words" array
                  carrying exact word start and end times (as openai-whisper / faster-whisper
                  produce with word timestamps on).
  *-youtube.vtt   YouTube auto-caption style: lower case, no punctuation, 7-word lines, inline
                  word start tags (word<00:00:01.120><c> next</c>), "rolling" cues that repeat the
                  previous line, and 10 ms transition cues.

MODELLING ASSUMPTION, NOT VERIFIED HERE: each caption line stays on screen until the next line
starts (contiguous cues), so pauses are invisible at cue level, and YouTube tags give word STARTS
only. Fetching a real auto-caption file to check this was not possible in the environment where
this was written. If a real file shows lines ending before silences, regenerate with that model.
"""
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "synthetic_v1_generate", os.path.join(HERE, "..", "synthetic-v1", "generate.py"))
v1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v1)


def whisper_json(utts):
    segs = []
    for i, u in enumerate(utts):
        words = [{"word": " " + w.replace("{um}", "um"), "start": round(a, 3), "end": round(b, 3)}
                 for a, b, w in u["words"]]
        segs.append({"id": i, "start": round(u["start"], 3), "end": round(u["end"], 3),
                     "text": " " + u["text"], "words": words})
    return {"language": "en", "segments": segs}


def youtube_vtt(utts):
    stream = []
    for u in utts:
        for a, b, w in u["words"]:
            w = re.sub(r"[^a-z' ]", "", w.replace("{um}", "um").lower())
            if w:
                stream.append((a, b, w))
    lines = [stream[i:i + 7] for i in range(0, len(stream), 7)]
    out = ["WEBVTT", "Kind: captions", "Language: en", ""]
    prev_plain = ""
    for n, line in enumerate(lines):
        start = line[0][0]
        end = lines[n + 1][0][0] if n + 1 < len(lines) else line[-1][1] + 0.35
        tagged = line[0][2] + "".join(f"<{v1.ts(a, '.')}><c> {w}</c>" for a, _, w in line[1:])
        out += [f"{v1.ts(start, '.')} --> {v1.ts(max(start, end - 0.01), '.')} align:start position:0%",
                prev_plain if prev_plain else " ", tagged, ""]
        plain = " ".join(w for _, _, w in line)
        out += [f"{v1.ts(max(start, end - 0.01), '.')} --> {v1.ts(end, '.')} align:start position:0%",
                plain, " ", ""]
        prev_plain = plain
    return "\n".join(out)


def main(out=HERE):
    tu, tl = v1.build(v1.TUTORIAL)
    es, el = v1.build(v1.ESSAY)
    cases = []
    for name, utts, lab in (("tutorial", tu, tl), ("essay", es, el)):
        with open(os.path.join(out, f"{name}-whisper.json"), "w") as f:
            json.dump(whisper_json(utts), f, indent=1)
        with open(os.path.join(out, f"{name}-youtube.vtt"), "w") as f:
            f.write(youtube_vtt(utts) + "\n")
        cases.append({"id": f"{name}-whisper", "transcript": f"{name}-whisper.json",
                      "notes": "Whisper JSON with exact word timings", "labels": lab})
        cases.append({"id": f"{name}-youtube", "transcript": f"{name}-youtube.vtt",
                      "notes": "modelled YouTube rolling auto-captions with word start tags", "labels": lab})
    d = {"name": "synthetic-words-v1", "synthetic": True,
         "label_source": "Same scripted talks and labels as synthetic-v1, rendered with word timings; "
                         "labels are ground truth by construction, never derived from tool output.",
         "cases": cases}
    with open(os.path.join(out, "dataset.json"), "w") as f:
        json.dump(d, f, indent=1)
        f.write("\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else HERE)
