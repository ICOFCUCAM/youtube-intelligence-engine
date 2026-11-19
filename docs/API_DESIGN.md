# API design

> **Status:** the Python library API, the CLIs and the stateless HTTP API (`yt-serve`, section 2)
> exist and are tested. The persistence and approval endpoints (section 3) are still a design.

## 1. Python library (implemented)

| Function | Input | Output |
| --- | --- | --- |
| `core.transcript.load_cues(path)` | .srt / .vtt / .json path | `list[Cue(start, end, text)]` |
| `editing.deadair.analyse(cues, floor=0.45, source="")` | cues | EDL dict, schema `youtube-intelligence/edl@1` |
| `editing.chapters.build(cues, target=7)` | cues | `{"valid": bool, "chapters": [...]}` |
| `creative.hookscore.evaluate(lines)` | hook strings | ranked score panels |
| `packaging.title.check(title, thumb=None)` | strings | `{"score", "issues", "good", "notes", ...}` |
| `analytics.retention.analyse(rows, duration=None, axis="auto", hint=None)` | `[(position, pct)]` | hook leak, cliffs, slide, limitations |
| `research.outliers.rank(rows, lo=1.5)` | video dicts | outliers, thin channels, skipped count |
| `shorts.candidates.find(cues, min_len, max_len, top)` | cues | non-overlapping candidate spans |

All raise `core.errors.InputError` on unusable input. All are deterministic and side-effect free.

### EDL schema `youtube-intelligence/edl@1` (implemented, `yt-deadair --json`)

```json
{
  "schema": "youtube-intelligence/edl@1",
  "source": "talk.srt",
  "duration": 90.0,
  "floor": 0.45,
  "cuts": [{"kind": "DEAD|FILLER|REPEAT", "start": 15.12, "end": 16.18, "why": "1.50s gap"}],
  "removed": 14.55,
  "out": 75.45,
  "removed_intervals": [[6.9, 7.4], [15.125, 16.175]],
  "overlap_counted_once": 0.0
}
```

Times are seconds from the start of the transcript's timeline. `removed_intervals` is the
merged, sorted, non-overlapping union, which is what a video engine should apply.
`schema` changes only on a breaking change. Additive fields keep `@1`.

## 2. HTTP API (implemented: `yt-serve`)

Stateless: each endpoint wraps one library function, JSON in and JSON out, no storage, no
outbound calls. Responses are exactly what the library returns for the same input (tested).

```bash
yt-serve                                   # http://127.0.0.1:8765
```

```bash
curl -s -X POST localhost:8765/v1/titles/check -H 'Content-Type: application/json' -d '{"titles": ["Why your channel is not growing"]}'
```

| Endpoint | Body | Returns |
| --- | --- | --- |
| `GET /v1/health` | - | `{"status": "ok", "version", "writes_to_youtube": false}` |
| `POST /v1/edl` | `transcript`, optional `floor`, `words` (`auto`/`off`), `review_below`, `hold_review` | EDL `edl@1` |
| `POST /v1/chapters` | `transcript`, optional `target` | `{valid, chapters, target}` |
| `POST /v1/hooks/score` | `hooks: [str]` (max 500) | `{results, disclaimer}` |
| `POST /v1/titles/check` | `titles: [str]` (max 500), optional `thumb` | `{results}` ranked |
| `POST /v1/retention` | `csv` (Studio export text) or `rows: [[position, percent]]`; optional `duration`, `axis`, `views`, `transcript` | retention report |
| `POST /v1/outliers` | `videos: [...]` (max 20,000), optional `min` | `{outliers, skipped_thin_channels, ...}` |
| `POST /v1/shorts` | `transcript`, optional `min`, `max`, `top` | `{candidates}` |
| `POST /v1/handoff/approve` | `approved_by`, any of `edl`, `chapters`, `shorts` (+ `picked_shorts`), `acknowledge_review` | `approval@1` record (signed if the server has `YIE_APPROVAL_KEY`) |
| `POST /v1/handoff/instruction` | `approval`, `media`, the approved artefacts, optional `transcript_offset`, `aspect`, `project` | `production-instruction@1` |
| `POST /v1/handoff/validate` | `instruction` | `{"valid": true}` or `400` |
| `GET /v1/openapi.json` | - | OpenAPI 3.1 document for all of the above |

`transcript` is `{"format": "srt" | "vtt" | "json", "content": "<text>"}` or
`{"cues": [{"start", "end", "text"}]}`. **Content only - no endpoint accepts a file path**, so a
caller cannot make the server read local files.

Errors: `{"error": {"code", "message"}}` with `400 invalid_input` (validation, or the library's
own message), `400 invalid_json`, `401 unauthorised`, `404 not_found`, `405 method_not_allowed`,
`411 length_required`, `413 payload_too_large` (8 MB), `415 unsupported_media_type`, and
`500 internal_error` (generic message; details only in the server log).

Security: binds to 127.0.0.1 by default and refuses any other address unless `YIE_API_TOKEN`
(at least 16 characters) is set; with a token, every POST needs `Authorization: Bearer <token>`
(constant-time compare); `/v1/health` stays open. 30 s socket timeout; `Cache-Control: no-store`;
`X-Content-Type-Options: nosniff`; no CORS headers; the access log records method, path and
status only. A connection whose body was not read (401/411/413/415) is closed, never reused. It
is Python's `ThreadingHTTPServer`: put it behind a TLS-terminating reverse proxy, with rate
limiting, before exposing it beyond a trusted network.

## 3. Persistence (design only)

Approval records and production instructions exist (section 2, and
[TAKE_CINEFORGE_INTEGRATION.md](TAKE_CINEFORGE_INTEGRATION.md)); storing them, versioning
artefacts and executing actions do not.

Only when TAKE needs persistence:

```
/v1/workspaces/{ws}/channels/{ch}/projects/{p}/artifacts/{kind}/{version}
POST .../artifacts/{kind}/{version}:approve   {approved_by}       -> approval record
POST /v1/actions                              {approval_id}       -> executes exactly the approved payload
GET  /v1/actions?channel=...                                        -> action log
```

Conventions: request size limits; all user content treated as untrusted; errors as
`{"error": {"code": "invalid_input", "message": "..."}}` mirroring `InputError`; idempotency keys
on `POST /v1/actions`; auth per workspace; no endpoint ever executes an unapproved action.
