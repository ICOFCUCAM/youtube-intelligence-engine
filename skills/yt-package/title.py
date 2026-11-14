#!/usr/bin/env python3
"""title.py - skill entry point for `youtube_intelligence.packaging.title`.

Adapted from upstream skills/yt-package/title.py in youtube-agent-skill by Jake Schincariol (MIT),
https://github.com/Jakeschincariol/youtube-agent-skill. The implementation now lives in the
youtube_intelligence package (one implementation, tested); this file keeps the upstream command
`python3 title.py ...` working from inside the skill folder. Run with --help for usage.
"""
import os
import sys

_SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
if os.path.isdir(os.path.join(_SRC, "youtube_intelligence")):
    sys.path.insert(0, _SRC)  # running from a checkout or a plugin install: use the bundled source
try:
    from youtube_intelligence.packaging.title import main, check  # noqa: E402,F401
except ImportError:  # skill folder copied on its own, package not installed
    sys.exit("youtube_intelligence is not installed. Run:\n"
             "  pip install git+https://github.com/ICOFCUCAM/youtube-intelligence-engine")

if __name__ == "__main__":
    sys.exit(main())
