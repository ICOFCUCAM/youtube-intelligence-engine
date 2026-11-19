# TAKE and CineForge integration

> **Status: contracts implemented, no calls to either system.** This repository does not call
> or depend on TAKE or CineForge. It now produces everything they need: the EDL
> (`youtube-intelligence/edl@1`), approval records (`approval@1`), production instructions
> (`production-instruction@1`, with a published JSON Schema), and a stateless HTTP API
> (`yt-serve`) with an OpenAPI document. The CineForge side (accepting and executing an
> instruction) is not built here and has not been tested against CineForge.

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

## Contract 2: approval and production instruction (implemented)

```bash
yt-deadair talk.srt --hold-review --json > edl.json
```

```bash
yt-handoff approve --edl edl.json --chapters chapters.json --by editor@example.org --out approval.json
```

```bash
yt-handoff instruction --approval approval.json --edl edl.json --chapters chapters.json --media cineforge://asset/123 --out instruction.json
```

The same steps are `POST /v1/handoff/approve`, `/v1/handoff/instruction` and
`/v1/handoff/validate` on `yt-serve`.

**Approval record (`youtube-intelligence/approval@1`)** pins each approved artefact by the
SHA-256 of its canonical JSON (sorted keys, no whitespace), records `approved_by` and a UTC
`approved_at`, and lists the Shorts actually picked. Rules:
- an EDL that still applies `[review]` pause cuts can be approved only with an explicit
  acknowledgement (`--acknowledge-review`), or after rebuilding it with `--hold-review`;
- chapters that break YouTube's rules cannot be approved;
- with `YIE_APPROVAL_KEY` (32+ characters, shared with the executor) the record is signed
  (`hmac-sha256:<hex>` over the canonical record), and unsigned approvals are refused.

A hash proves the artefact is unchanged; it does not prove who approved it. Identity comes from
the system that authenticated the approver (TAKE) and from the signature key.

**Instruction (`youtube-intelligence/production-instruction@1`)**, schema:
[`docs/schemas/production-instruction-1.schema.json`](schemas/production-instruction-1.schema.json).

```json
{
  "schema": "youtube-intelligence/production-instruction@1",
  "instruction_id": "68759453-b88a-4281-b32c-3fd143e66095",
  "media": {"ref": "cineforge://asset/demo-123", "transcript_offset_seconds": 0.0},
  "operations": [
    {"op": "remove_intervals", "intervals": [[6.9, 7.4], [19.9, 20.3]], "source_artifact": "edl:646cef3c67d15a13"},
    {"op": "extract_clip", "start": 0.0, "end": 28.6, "aspect": "9:16", "label": "short-1", "source_artifact": "shorts:..."},
    {"op": "attach_chapters", "chapters": [{"start": 0.0, "title": "..."}], "source_artifact": "chapters:ba2e192dd908187c"}
  ],
  "approval": {"approved_by": "editor@example.org", "approved_at": "2026-11-19T12:00:00Z",
               "artifacts": [{"kind": "edl", "sha256": "..."}], "acknowledged_review": false,
               "signature": "hmac-sha256:..."}
}
```

Guarantees, enforced by `handoff.instruction.validate` and tested against the JSON Schema:
- instructions are built only from artefacts whose hash matches the approval, so an edit list
  changed after approval is refused;
- `source_artifact` must name an approved artefact (`<kind>:<first 16 hex of its sha256>`);
- the operation set is closed (`remove_intervals`, `extract_clip`, `attach_chapters`): unknown
  operations and unknown fields are rejected, never ignored;
- intervals are non-negative, sorted and non-overlapping, and pauses held back for review are
  not in them;
- chapters start at 0, number three or more, and are 10 s apart;
- the full approval, including its signature, travels with the instruction, so the executor
  can verify it with the shared key (`yt-handoff validate` does exactly that).

**What CineForge must do (not built here):** reject anything that fails the schema or the
checks above; verify the signature with the shared key; apply
`media.transcript_offset_seconds`; echo `instruction_id` in its result; and never execute an
instruction twice (treat `instruction_id` as an idempotency key).

## Contract 3: TAKE (proposed)

TAKE calls the stateless HTTP endpoints for analysis and owns the review screens. Approval
happens in TAKE. The engine records it against the artefact version. TAKE shows the action log.

## What to build first

1. Done: the existing functions are behind stateless HTTP endpoints (`yt-serve`, see
   [API_DESIGN.md](API_DESIGN.md)). TAKE can call it today; nothing is stored.
2. Done on this side: `production-instruction@1`, approval records with optional HMAC
   signatures, a JSON Schema and `yt-handoff`. Next: review the schema with the CineForge team
   and run one real instruction through CineForge, starting with `remove_intervals`.
3. TAKE: authenticate the approver, then call `/v1/handoff/approve` with the shared key
   configured on the engine, so every approval it records is signed.
