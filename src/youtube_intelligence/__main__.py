"""``python -m youtube_intelligence <tool> [args]`` - dispatch to one of the CLIs."""
from __future__ import annotations

import sys
from importlib import import_module

TOOLS = {
    "hookscore": "youtube_intelligence.creative.hookscore",
    "title": "youtube_intelligence.packaging.title",
    "deadair": "youtube_intelligence.editing.deadair",
    "chapters": "youtube_intelligence.editing.chapters",
    "retention": "youtube_intelligence.analytics.retention",
    "swipe": "youtube_intelligence.research.outliers",
    "shorts": "youtube_intelligence.shorts.candidates",
    "eval": "youtube_intelligence.evaluation.runner",
    "youtube": "youtube_intelligence.integrations.youtube.cli",
    "serve": "youtube_intelligence.service.server",
    "handoff": "youtube_intelligence.handoff.cli",
    "report": "youtube_intelligence.reports.channel",
    "check": "youtube_intelligence.preflight.check",
    "moments": "youtube_intelligence.analytics.moments",
}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in TOOLS:
        print("usage: python -m youtube_intelligence {" + ",".join(TOOLS) + "} [args]", file=sys.stderr)
        return 1
    return import_module(TOOLS[argv[0]]).main(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
