"""Metrics for comparing tool output with labels. Pure functions, no I/O.

Three families, matching what the tools emit:

* **Cuts (EDL)** - time-weighted precision/recall (seconds of predicted cut that are also labelled
  cut, and the reverse) plus event-level precision/recall, where a predicted cut matches a
  labelled cut when their intersection-over-union is at least ``min_iou`` (one-to-one, greedy by
  IoU).
* **Boundaries (chapters)** - a predicted boundary matches a labelled one within ``tolerance``
  seconds (one-to-one, nearest first). The mandatory 0:00 entry is excluded from both sides,
  because counting it would inflate every score.
* **Spans (Shorts)** - a predicted span hits a labelled span when IoU >= ``min_iou``. Precision is
  the share of predictions that hit; recall the share of labelled spans hit.
"""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from ..core.intervals import Interval, merge_intervals


def prf(tp: float, n_pred: float, n_gold: float) -> Dict[str, float]:
    """Precision, recall and F1. An empty side scores 1.0 when the other is empty too, else 0."""
    p = tp / n_pred if n_pred else (1.0 if not n_gold else 0.0)
    r = tp / n_gold if n_gold else (1.0 if not n_pred else 0.0)
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4)}


def intersection_length(a: Sequence[Interval], b: Sequence[Interval]) -> float:
    """Seconds covered by both interval sets (each merged first)."""
    ma, mb = merge_intervals(a), merge_intervals(b)
    i = j = 0
    total = 0.0
    while i < len(ma) and j < len(mb):
        lo, hi = max(ma[i][0], mb[j][0]), min(ma[i][1], mb[j][1])
        if hi > lo:
            total += hi - lo
        if ma[i][1] < mb[j][1]:
            i += 1
        else:
            j += 1
    return total


def length(x: Sequence[Interval]) -> float:
    return sum(e - s for s, e in merge_intervals(x))


def iou(a: Interval, b: Interval) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union > 0 else 0.0


def match_by_iou(pred: Sequence[Interval], gold: Sequence[Interval], min_iou: float) -> List[Tuple[int, int]]:
    pairs = sorted(((iou(p, g), i, j) for i, p in enumerate(pred) for j, g in enumerate(gold)), reverse=True)
    used_p, used_g, out = set(), set(), []
    for v, i, j in pairs:
        if v < min_iou:
            break
        if i not in used_p and j not in used_g:
            used_p.add(i)
            used_g.add(j)
            out.append((i, j))
    return out


def time_counts(pred: Sequence[Interval], gold: Sequence[Interval]) -> Dict[str, float]:
    """Raw seconds, so several cases can be summed before computing ratios (micro-average)."""
    return {"tp": intersection_length(pred, gold), "pred": length(pred), "gold": length(gold)}


def event_counts(pred: Sequence[Interval], gold: Sequence[Interval], min_iou: float = 0.5) -> Dict[str, float]:
    return {"tp": len(match_by_iou(pred, gold, min_iou)), "pred": len(pred), "gold": len(gold)}


def boundary_counts(pred: Sequence[float], gold: Sequence[float], tolerance: float = 3.0) -> Dict[str, float]:
    p = sorted(t for t in pred if t > 0)
    g = sorted(t for t in gold if t > 0)
    pairs = sorted((abs(a - b), i, j) for i, a in enumerate(p) for j, b in enumerate(g))
    used_p, used_g, tp = set(), set(), 0
    for d, i, j in pairs:
        if d > tolerance:
            break
        if i not in used_p and j not in used_g:
            used_p.add(i)
            used_g.add(j)
            tp += 1
    return {"tp": tp, "pred": len(p), "gold": len(g)}


def span_counts(pred: Sequence[Interval], gold: Sequence[Interval], min_iou: float = 0.5) -> Dict[str, float]:
    """``tp`` = predictions that hit any gold span; ``gold_hit`` = gold spans hit by any prediction."""
    hit_p = sum(1 for p in pred if any(iou(p, g) >= min_iou for g in gold))
    hit_g = sum(1 for g in gold if any(iou(p, g) >= min_iou for p in pred))
    return {"tp": hit_p, "gold_hit": hit_g, "pred": len(pred), "gold": len(gold)}


def span_prf(c: Dict[str, float]) -> Dict[str, float]:
    p = c["tp"] / c["pred"] if c["pred"] else (1.0 if not c["gold"] else 0.0)
    r = c["gold_hit"] / c["gold"] if c["gold"] else (1.0 if not c["pred"] else 0.0)
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4)}


def add_counts(a: Dict[str, float], b: Dict[str, float]) -> Dict[str, float]:
    return {k: a.get(k, 0) + b.get(k, 0) for k in set(a) | set(b)}
