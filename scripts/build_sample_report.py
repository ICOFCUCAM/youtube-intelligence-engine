"""Regenerate public/sample-report.html from the invented data in examples/report/.

    python scripts/build_sample_report.py

tests/test_report.py fails if the committed page differs from what this produces.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from youtube_intelligence.reports.channel import build, render_html  # noqa: E402
from youtube_intelligence.research.outliers import load  # noqa: E402

EX = os.path.join(ROOT, "examples", "report")
NOTE = ("Sample report. The channel, its videos and its numbers are invented to show what a report "
        "looks like. Your report would use your own channel's data.")


def sample_html() -> str:
    r = build(load(os.path.join(EX, "videos.json")),
              {vid: os.path.join(EX, f"retention-{vid}.csv") for vid in ("smpl0000002", "smpl0000003")},
              generated_for=NOTE)
    return render_html(r)


if __name__ == "__main__":
    with open(os.path.join(ROOT, "public", "sample-report.html"), "w", encoding="utf-8") as fh:
        fh.write(sample_html())
    print("wrote public/sample-report.html")
