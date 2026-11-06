"""The 21-formula hook library (``data/hooks.json``) and the formula classifier.

``hooks.json`` is upstream data by Jake Schincariol (MIT), shipped unmodified; the copy in
``skills/yt-script/hooks.json`` must stay byte-identical (enforced by a test).

The classifier merges two upstream implementations: ``hookscore.classify`` (first formula with
the most pattern hits, in file order) and ``swipe.classify`` (most hits, ties broken by reverse
alphabetical name). This module uses the hookscore rule for both. The swipe tie-break is the
only behaviour change and only affects titles that match two formulas equally.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources
from typing import Dict, List, Tuple


@lru_cache(maxsize=1)
def library() -> Dict:
    text = resources.files("youtube_intelligence").joinpath("data/hooks.json").read_text("utf-8")
    return json.loads(text)


def formulas() -> List[Dict]:
    return library()["hooks"]


@lru_cache(maxsize=1)
def _compiled() -> List[Tuple[str, List["re.Pattern[str]"]]]:
    return [(f["name"], [re.compile(p, re.I) for p in f["match"]]) for f in formulas()]


def classify(text: str) -> Tuple[str, int]:
    """Return ``(formula name, patterns matched)``, or ``("Unclassified", 0)``.

    A judgement about the WORDS, never a claim about why a video performed.
    """
    best, hits = None, 0
    for name, pats in _compiled():
        n = sum(1 for p in pats if p.search(text))
        if n > hits:
            best, hits = name, n
    return (best or "Unclassified"), hits
