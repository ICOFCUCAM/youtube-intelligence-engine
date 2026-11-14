# API design

> **Status:** the Python library API and CLI exist and are tested. The HTTP API below is a
> design, not an implementation.

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

## 2. HTTP API (design only)

Stateless first: each endpoint wraps one library function, with JSON in and JSON out and no
storage.

```
POST /v1/edl            {transcript: {format, content} | {cues: [...]}, floor}      -> edl@1
POST /v1/chapters       {transcript, target}                                         -> chapters
POST /v1/hooks/score    {hooks: [...]}                                               -> panels
POST /v1/titles/check   {titles: [...], thumb}                                       -> results
POST /v1/retention      {rows | csv, duration, axis}                                 -> report
POST /v1/outliers       {videos: [...], min}                                         -> outliers
POST /v1/shorts         {transcript, min, max, top}                                  -> candidates
```

Then, only when TAKE needs persistence:

```
/v1/workspaces/{ws}/channels/{ch}/projects/{p}/artifacts/{kind}/{version}
POST .../artifacts/{kind}/{version}:approve   {approved_by}       -> approval record
POST /v1/actions                              {approval_id}       -> executes exactly the approved payload
GET  /v1/actions?channel=...                                        -> action log
```

Conventions: request size limits; all user content treated as untrusted; errors as
`{"error": {"code": "invalid_input", "message": "..."}}` mirroring `InputError`; idempotency keys
on `POST /v1/actions`; auth per workspace; no endpoint ever executes an unapproved action.
