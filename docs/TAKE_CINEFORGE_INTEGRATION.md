# TAKE and CineForge integration

> **Status: design, plus a callable service.** This repository has no code that calls TAKE or
> CineForge and does not depend on either. What exists today: a stable, versioned EDL JSON
> (`youtube-intelligence/edl@1`), and a stateless HTTP API (`yt-serve`) that TAKE can call for
> every analysis.

## Responsibilities

| System | Owns | Does not own |
| --- | --- | --- |
| **YouTube Intelligence Engine** (this repo) | Analysis and decisions: hooks, scripts, packaging, EDLs, chapters, retention, Shorts candidates, plans, reply drafts | Media files, rendering, the creator UI, channel credentials (until the YouTube connector exists) |
| **CineForge** | Media processing: decoding, cutting, rendering, transcoding, reframing (16:9 to 9:16), audio | Deciding *what* to cut or *why* |
| **TAKE** | Creator-facing studio: channels, teams, review and approval UI, calendar | Analysis logic |

## Flow (target)

```
transcript ---> Engine: EDL / Shorts candidates / chapters (draft)
                     |
                     v
             TAKE: human reviews, edits, approves   (approval record: who, when, artefact version)
                     |
                     v
       Engine: production instruction (approved artefact + media reference)
                     |
                     v
             CineForge: renders, returns output reference + render report
                     |
                     v
             TAKE: human reviews the render -> (later) publish via approved action
```

The engine never sends an unapproved decision to CineForge.

## Contract 1: edit decision list (exists)

`yt-deadair --json` emits `youtube-intelligence/edl@1` (see [API_DESIGN.md](API_DESIGN.md)).
For a renderer:
- apply `removed_intervals`, not `cuts`. Cuts can overlap; the intervals are their union;
- times are transcript-timeline seconds. If the media has an offset from the transcript (an intro
  added after captioning), CineForge must apply it, so the instruction carries the offset;
- DEAD cuts already keep half the floor on each side of a gap, so no extra padding is needed;
- the EDL is speech-only. Silent demos and B-roll may need a human to exclude intervals before
  approval.

## Contract 2: production instruction (proposed)

```json
{
  "schema": "youtube-intelligence/production-instruction@1",
  "instruction_id": "uuid",
  "project": {"workspace": "ws_...", "channel": "ch_...", "project": "pr_..."},
  "media": {"ref": "cineforge://asset/...", "transcript_offset_seconds": 0.0},
  "operations": [
    {"op": "remove_intervals", "intervals": [[6.9, 7.4], [15.125, 16.175]], "source_artifact": "edl@1:v3"},
    {"op": "extract_clip", "start": 0.0, "end": 28.6, "aspect": "9:16", "label": "short-1"},
    {"op": "attach_chapters", "chapters": [{"start": 0, "title": "..."}]}
  ],
  "approval": {"approved_by": "user_...", "approved_at": "2026-11-14T12:00:00Z", "artifact_versions": ["edl@1:v3"]}
}
```

Rules: an instruction without `approval` is rejected; CineForge echoes `instruction_id` in its
result; operations are declarative, never code; unknown ops are rejected, not ignored.

## Contract 3: TAKE (proposed)

TAKE calls the stateless HTTP endpoints for analysis and owns the review screens. Approval
happens in TAKE. The engine records it against the artefact version. TAKE shows the action log.

## What to build first

1. Done: the existing functions are behind stateless HTTP endpoints (`yt-serve`, see
   [API_DESIGN.md](API_DESIGN.md)). TAKE can call it today; nothing is stored.
2. Agree `production-instruction@1` with the CineForge team, starting with the
   `remove_intervals` op only.
3. Add the approval record and refuse unapproved instructions, before any second op.
