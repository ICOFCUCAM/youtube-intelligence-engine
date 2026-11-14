"""Use the engine as a library: one transcript through EDL, chapters and Shorts candidates.

    python examples/library_usage.py [transcript]     (defaults to the test fixture)
"""
import json
import os
import sys

from youtube_intelligence.core.transcript import load_cues
from youtube_intelligence.editing import chapters, deadair
from youtube_intelligence.packaging.title import check
from youtube_intelligence.shorts.candidates import find

HERE = os.path.dirname(os.path.abspath(__file__))
path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "tests", "fixtures", "sample.srt")

cues = load_cues(path)
edl = deadair.analyse(cues, source=os.path.basename(path))
ch = chapters.build(cues, target=6)
shorts = find(cues, 20, 55, 3)

print(f"{len(cues)} cues, {edl['duration']:.1f}s -> {edl['out']:.1f}s after {len(edl['cuts'])} cuts")
print("chapters valid:", ch["valid"], [c["label"] for c in ch["chapters"]])
print("shorts:", [(s["start"], s["end"]) for s in shorts])
print("title score:", check("Posting less grew my channel", thumb="3X VIEWS")["score"])
print(json.dumps({"schema": edl["schema"], "removed_intervals": edl["removed_intervals"][:3]}))
