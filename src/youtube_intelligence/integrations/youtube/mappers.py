"""API responses -> the exact inputs the offline tools already read.

The point of this module: the analysis code does not change when data comes from the API instead
of a manual export. ``videos_to_rows`` produces yt-swipe's collected.json rows;
``retention_to_rows`` / ``write_retention_csv`` produce a CSV yt-retention reads as a percent axis.
"""
from __future__ import annotations

import csv
import re
from typing import Dict, List, Optional, Tuple

from ...core.errors import InputError

_ISO = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$")


def iso_duration(s: Optional[str]) -> Optional[float]:
    """``PT1H2M3S`` -> 3723.0; ``P0D`` (live/upcoming) -> 0.0; unreadable -> None."""
    m = _ISO.match(s or "")
    if not m or s in ("P", "PT"):
        return None
    d, h, mi, sec = m.groups()
    return int(d or 0) * 86400 + int(h or 0) * 3600 + int(mi or 0) * 60 + float(sec or 0)


def videos_to_rows(videos: List[Dict], channel_title: Optional[str] = None) -> List[Dict]:
    rows = []
    for v in videos:
        sn, st, cd = v.get("snippet") or {}, v.get("statistics") or {}, v.get("contentDetails") or {}
        vid = v.get("id")
        rows.append({
            "channel": channel_title or sn.get("channelTitle") or "?",
            "title": sn.get("title", ""),
            # viewCount can be absent (hidden or live); keep None so yt-swipe treats it as 0 like upstream
            "views": int(st["viewCount"]) if str(st.get("viewCount", "")).isdigit() else None,
            "url": f"https://www.youtube.com/watch?v={vid}" if vid else "",
            "duration": iso_duration(cd.get("duration")),
            "published": sn.get("publishedAt"),
            "video_id": vid,
        })
    return rows


def retention_to_rows(report: Dict) -> List[Tuple[float, float]]:
    """Analytics ``reports.query`` (elapsedVideoTimeRatio x audienceWatchRatio) -> (percent, percent)."""
    headers = [h.get("name") for h in report.get("columnHeaders") or []]
    try:
        xi, yi = headers.index("elapsedVideoTimeRatio"), headers.index("audienceWatchRatio")
    except ValueError:
        raise InputError("report lacks elapsedVideoTimeRatio / audienceWatchRatio columns") from None
    rows = []
    for r in report.get("rows") or []:
        try:
            rows.append((round(float(r[xi]) * 100, 4), round(float(r[yi]) * 100, 4)))
        except (TypeError, ValueError, IndexError):
            raise InputError("report has a malformed row") from None
    rows.sort()
    return rows


def write_retention_csv(rows: List[Tuple[float, float]], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Video position (%)", "Absolute audience retention (%)"])
        w.writerows(rows)


def comments_to_rows(threads: List[Dict], video_title: Optional[str] = None) -> List[Dict]:
    """commentThreads.list items -> yt-comments input rows."""
    rows = []
    for t in threads:
        top = ((t.get("snippet") or {}).get("topLevelComment") or {}).get("snippet") or {}
        if not top:
            continue
        rows.append({
            "video_id": top.get("videoId") or (t.get("snippet") or {}).get("videoId"),
            "video_title": video_title,
            "author": top.get("authorDisplayName", ""),
            "author_id": (top.get("authorChannelId") or {}).get("value"),
            "text": top.get("textOriginal") or top.get("textDisplay") or "",
            "likes": int(top.get("likeCount") or 0),
            "published": top.get("publishedAt"),
            "replies": int((t.get("snippet") or {}).get("totalReplyCount") or 0),
        })
    return rows
