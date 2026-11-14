#!/usr/bin/env python3
"""shorts.py - skill entry point for `youtube_intelligence.shorts.candidates`.

ICOFCUCAM addition with no upstream counterpart: a companion tool for the upstream yt-shorts skill
by Jake Schincariol (MIT, https://github.com/Jakeschincariol/youtube-agent-skill). Run with
--help for usage.
"""
import os
import sys

_SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
if os.path.isdir(os.path.join(_SRC, "youtube_intelligence")):
    sys.path.insert(0, _SRC)  # running from a checkout or a plugin install: use the bundled source
try:
    from youtube_intelligence.shorts.candidates import main, find  # noqa: E402,F401
except ImportError:  # skill folder copied on its own, package not installed
    sys.exit("youtube_intelligence is not installed. Run:\n"
             "  pip install git+https://github.com/ICOFCUCAM/youtube-intelligence-engine")

if __name__ == "__main__":
    sys.exit(main())
