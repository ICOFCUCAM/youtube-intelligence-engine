"""Handoff to a video engine (e.g. CineForge): approval records and production instructions.

ICOFCUCAM addition. Nothing here renders, uploads or calls another system. It turns artefacts a
human has APPROVED (an EDL, chapters, picked Shorts) into a declarative, validated instruction
(`youtube-intelligence/production-instruction@1`) that a video engine can execute.
"""
