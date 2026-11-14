"""Interval arithmetic for edit decisions.

ICOFCUCAM addition, written to fix an upstream defect: ``deadair.py`` summed the length of every
cut, so two cuts covering the same seconds (common with overlapping auto-caption cues) were
counted twice and the reported runtime could even go negative.
"""
from __future__ import annotations

from typing import Iterable, List, Tuple

Interval = Tuple[float, float]


def merge_intervals(intervals: Iterable[Interval]) -> List[Interval]:
    """Return the union of ``intervals`` as sorted, non-overlapping ``(start, end)`` pairs.

    Empty or inverted intervals (``end <= start``) contribute nothing. Touching intervals
    (``a.end == b.start``) are merged.
    """
    spans = sorted((float(s), float(e)) for s, e in intervals if e > s)
    merged: List[Interval] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            if e > merged[-1][1]:
                merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


def total_length(intervals: Iterable[Interval]) -> float:
    """Total seconds covered by ``intervals``, counting overlapping time once."""
    return sum(e - s for s, e in merge_intervals(intervals))
