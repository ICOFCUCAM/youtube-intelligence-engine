# Changelog

All notable changes are recorded here. Upstream baseline: youtube-agent-skill
`a2feb2104981a375ffd4f87ee04f4f5344ac43c6` by Jake Schincariol (MIT).

## 0.1.0 - 2026-11

First ICOFCUCAM release. Every fix below was reproduced against the unmodified upstream tool
before it was changed, and has a regression test (test names in brackets).

### Fixed

**Transcript loader** (`core/transcript.py`, used by deadair, chapters, retention, shorts)
- A Whisper JSON file that is a top-level **array** crashed with
  `AttributeError: 'list' object has no attribute 'get'`: upstream evaluated `d.get(...)` before
  checking `isinstance(d, list)`. `chapters.py` and `retention.py --transcript` imported the same
  loader and crashed the same way. [`test_json_array_is_accepted`, `test_cli_json_array_regression`,
  `test_json_array_regression` (chapters), `test_transcript_json_array_at_cliffs`]
- Malformed JSON, missing `start`/`end`, non-numeric times, missing files and directories gave
  tracebacks. They now give `error: ...` and exit status 1. [`test_malformed_json_raises_input_error`,
  `test_cli_bad_input_exits_1`]
- WebVTT `NOTE` blocks were appended to the previous cue's text, and inline tags (`<c>`,
  `<00:00:01.500>`) were kept as text. [`test_vtt_tags_and_note_blocks`]
- A 4-part timestamp (`1:2:3:4`) was silently mis-parsed. It is now rejected. [`test_parse_ts_rejects_garbage`]

**deadair** (edit decision list)
- Removed time was the plain **sum** of cut lengths, so overlapping cuts were double-counted. With
  overlapping caption cues, upstream reported 4.0 s removed where the true union is 3.5 s, and the
  output runtime could go negative. Removed time is now the union of the cuts. The JSON adds
  `removed_intervals` and `overlap_counted_once`. [`test_overlapping_cuts_counted_once`,
  `test_removed_never_exceeds_duration`]
- A dead-air gap was measured from the previous cue only. When a short cue sits inside a longer
  one, upstream cut "dead air" straight through speech. Gaps are now measured from the latest end
  of any earlier cue. [`test_dead_gap_does_not_cut_through_nested_speech`]
- Filler cues with `?`, `!`, `;`, `:`, an ellipsis or quotes ("Um?", "Okay!") were not
  recognised, and "erm", "hmm" and "mm" were not fillers. The pattern now needs a word boundary
  after each filler, so it cannot backtrack exponentially. [`test_filler_detected`, `test_not_filler`,
  `test_filler_regex_is_linear_on_adversarial_input`]
- A retake whose abandoned first attempt was only 3-4 words ("so the thing" / "so the thing about
  hooks...") was missed, because upstream required the first five words to match exactly. A
  leading disfluency ("um so the...") also broke matching. Every restart upstream found is still
  found. [`test_short_abandoned_take_now_found`, `test_leading_disfluency_ignored_for_restart`]
- Duration is the latest cue end rather than the last cue's end, and zero duration no longer
  divides by zero.
- The docstring said cuts print "newest problem first". They print in timeline order, as the code
  always did.

**chapters**
- Draft titles were **nondeterministic**: keywords with equal counts were ordered by Python
  `set` iteration, which is hash-randomised per process, so the same file gave different titles
  on each run. Ties are now broken by first appearance. Boundaries are unchanged and match
  upstream exactly. [`test_titles_are_deterministic_across_hash_seeds`, `test_boundaries_match_upstream_output`]

**retention**
- `retention.py --duration 600 retention.csv` took `600` as the CSV path and printed usage.
  Arguments are now parsed properly. [`test_duration_before_csv_regression`]
- The axis was guessed as "percent" whenever every position was at most 100.5, which misread a
  seconds-axis export of any video up to 100 s long, and lost every cliff's timing. The header
  ("%" or "seconds") now decides, `--axis` overrides, and the old guess is the fallback.
  [`test_seconds_header_on_short_video_regression`, `test_axis_override_and_headerless_auto`]

**hookscore**
- A missing input file printed usage and exited **0**. It now exits 1. [`test_missing_file_exits_nonzero`]

**swipe** (now `research/outliers.py`)
- Views written as `"412K"`, `"1.2M views"` or other non-numeric strings crashed with
  `ValueError`. K, M and B suffixes are now parsed, and unreadable rows are skipped and counted.
  Malformed JSON gives a clean error. [`test_parse_views`, `test_unreadable_rows_skipped_and_counted`, `test_bad_json`]

### Changed (behaviour, deliberately)

- **title**: a title is no longer penalised for having no digit (upstream issue `no-number`), and
  a digit no longer adds a "concrete figure" strength. Both now appear only as an unscored `note`.
  New scored issues: `claim` (guarantees, absolute promises, "overnight", income claims,
  "they don't want you to know") and `numbers` (three or more figures). JSON rows gain a `notes`
  list. Example: upstream scored "Why your channel is not growing" 90 and
  "1 trick 2 make 10000 in 24 hours" 100; they now score 100 and 76. All other checks and the
  formula `100 - 14 x issues + 4 x strengths` are unchanged. [`test_title.py`]
- **retention**: JSON adds `axis` and `limitations`. The text report adds a LIMITS block and labels
  hook leak in percentage points. Analysis values are identical to upstream on the same axis.
- **hookscore**: text output ends with a heuristic disclaimer. Scores and JSON are byte-identical
  to upstream. [`test_scores_identical_to_upstream_*`]
- **swipe**: formula ties now use the hookscore rule (first in library order) instead of reverse
  alphabetical order. This only matters when two formulas match a title equally.
- **deadair** JSON adds `schema: "youtube-intelligence/edl@1"`, `floor`, `removed_intervals` and
  `overlap_counted_once`. Existing keys are unchanged.
- Skill-folder scripts are thin entry points into the `youtube_intelligence` package.

### Added

- `youtube_intelligence` Python package, `pyproject.toml`, console scripts `yt-*`, and
  `python -m youtube_intelligence <tool>`.
- `yt-shorts`: Shorts candidate finder (new).
- 183-test pytest suite, including golden outputs from the unmodified upstream tools.
- Untrusted-input and approval sections appended to every SKILL.md.
- Documentation: architecture, security model, API design, YouTube API plan, TAKE/CineForge
  integration, roadmap, tool review.
- CI on Python 3.10-3.14. Python 3.9 (end of life since October 2025) is not supported:
  GitHub's `ubuntu-latest` runners no longer provide it, so support could not be checked.
