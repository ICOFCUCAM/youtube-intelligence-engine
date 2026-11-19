# Changelog

All notable changes are recorded here. Upstream baseline: youtube-agent-skill
`a2feb2104981a375ffd4f87ee04f4f5344ac43c6` by Jake Schincariol (MIT).

## Unreleased

### Added
- **Evaluation harness** (`youtube_intelligence.evaluation`, `yt-eval`): seconds-weighted and
  event-level precision/recall for edit cuts, recall by cut kind, a "keep regions cut" harm metric,
  chapter-boundary and Shorts-span scoring. Dataset format with validation (paths confined to the
  dataset folder, a mandatory `synthetic` flag).
- **`datasets/synthetic-v1`**: four scripted transcripts (clean and auto-caption renderings of two
  talks) with labels generated from the script, a deterministic generator, and a pinned baseline.
  Results and their limits: [docs/EVALUATION.md](docs/EVALUATION.md).
- `yt-retention --views N`: small-sample warning below 1,000 views (rule of thumb). Output is
  unchanged when `--views` is not given.
- **Read-only YouTube connector** (`youtube_intelligence.integrations.youtube`, `yt-youtube`):
  channel uploads with metadata and views (Data API v3, API key, or OAuth for `--mine`) and
  retention curves (Analytics API v2, OAuth), written as `yt-swipe` / `yt-retention` input. GET-only
  to allowlisted hosts, read-only scopes enforced, secrets from the environment and redacted,
  bounded retries, quota errors surfaced. Tested with a fake transport; against the live API only
  the error path has been exercised (invalid key). `.env.example` lists the variable names.
- `core.cli.guarded` forwards keyword arguments (lets tests inject a client).
- **Word timings** (`core.transcript.load_words`): Whisper JSON `words` (exact start and end) and
  YouTube auto-caption inline tags (starts only). `yt-deadair --words auto|off` (default auto):
  disfluencies inside a sentence (um, uh, er, erm, ah, hmm, mm; never "like" or "so") are cut
  using the word's own time, and with exact word ends dead air is measured between words. Plain
  SRT/VTT/JSON without word timings gives the same cuts as before.
- **Review flag**: every cut carries `review`; DEAD cuts shorter than `--review-below` (default
  1.5 s, an assumption) are `true` and shown as `[review]`. `--hold-review` keeps them out of
  `removed`, `out` and `removed_intervals`. EDL JSON adds `word_timings`, `review_below`,
  `hold_review`, `held_for_review` (additive; schema stays `edl@1`).
- **`datasets/synthetic-words-v1`**: the synthetic-v1 talks rendered as Whisper JSON with word
  timings and as modelled YouTube rolling auto-captions, with a pinned baseline.
- `yt-eval --words auto|off --hold-review`.
- **`yt-youtube login`**: browser consent for a read-only refresh token (PKCE S256, random state,
  one-time 127.0.0.1 listener). Refuses any grant beyond the two read-only scopes; saves the token
  with mode 600, never prints it, and refuses paths inside a git working tree; the path is checked
  before sign-in starts (a screenshot taken during the build showed it was checked only after,
  which would have wasted a completed sign-in). `YT_OAUTH_TOKEN_FILE` lets the tools read it and
  is refused if group/world-readable. Tested with a simulated browser; not yet run against Google.

- **`yt-serve`** (`youtube_intelligence.service`): stateless HTTP/JSON API over the library:
  `GET /v1/health`; `POST /v1/edl`, `/v1/chapters`, `/v1/hooks/score`, `/v1/titles/check`,
  `/v1/retention`, `/v1/outliers`, `/v1/shorts`. Responses equal the library's output (tested).
  Content-only inputs (no file paths); loopback by default, bearer token required beyond it;
  8 MB cap, item caps, range checks, 30 s socket timeout, no CORS, generic 500s. Built while the
  build was screenshotted; a test exposed that rejected-but-unread requests must close the
  connection, which they now do.
- `core.transcript.parse_transcript(content, format)`, `analytics.retention.parse_csv_text` and
  `attach_cues`: content-based entry points (the file-based functions now call them).

- **Handoff** (`youtube_intelligence.handoff`, `yt-handoff`, `/v1/handoff/*`): `approval@1`
  records pin approved artefacts by SHA-256 of canonical JSON; `[review]` cuts need an explicit
  acknowledgement; invalid chapters cannot be approved; optional HMAC-SHA256 signatures with
  `YIE_APPROVAL_KEY` (unsigned or altered approvals refused when a key is set).
  `production-instruction@1` is built only from artefacts that match their approval; closed
  operation set (`remove_intervals`, `extract_clip`, `attach_chapters`); JSON Schema at
  `docs/schemas/production-instruction-1.schema.json`, tested to agree with the validator.
  No call to CineForge is made or tested.
- **`yt-claims`**, the fact guard (`creative/claims.py`, `POST /v1/claims`, and `claims.py` in
  the yt-script skill folder): BLOCKED for `voice.md` "Words I never use" (whole words) and "What
  I will not claim"; NEEDS SOURCE for figures (percent, money, multipliers, counts with units,
  rankings, "from X to Y" needing both numbers) not in the evidence file, unsourced citations
  ("studies show") and unbacked result claims; CHECK for absolutes. Evidence numbers ignore
  bracketed sources and dates, so a date can't back a claim. Exit 1 until clean. The yt-script and
  yt-comment skills now run it before handing over a draft.
- **`yt-localize`** and a new **`/yt-localize` skill** (the twelfth): export a translation pack
  (title, each description line, each caption; chapter names only, timestamps kept; links,
  emails, @handles, #hashtags and promo codes marked "keep exactly"), check it per language
  (FAIL: untranslated, a protected token changed, title over 100, description over 5,000 bytes,
  `<` or `>`, chapters broken; WARN: captions over 20 characters per second or too long for two
  lines of about 42) and build title, description and SRT with the original timings, wrapped to
  two balanced lines, only when nothing fails. The engine does not translate. Demo:
  `examples/localize/pack.json`, Spanish by an AI assistant, labelled as not reviewed.
- **`yt-moments`** (`youtube_intelligence.analytics.moments`): aligns each video's retention
  curve with its transcript, measures every sentence's extra loss against the video's typical
  (median) loss rate, tags sentences (sponsor, subscribe/like ask, housekeeping, tangent, recap,
  signpost) and compares the types across videos. Skips the first 30 s and last 10%; calls
  something a pattern only with 3+ occurrences across 2+ videos; says correlation, not cause. On an
  invented, scripted demo set (`examples/moments/`) it recovers the scripted costs within 0.1
  points, and shows its blind spot: the commonest kind of sentence sets the baseline, so it cannot
  stand out (the scripted signpost benefit is not found).
- Waitlist: optional "Where else do you post?" (TikTok, Instagram, Facebook, LinkedIn, X,
  podcasts, or nowhere else) to measure multi-platform demand before building it. Validated by
  the function, the form and a database constraint; the SQL upgrades a table from the earlier
  script in place. Privacy notice and consent version bumped to `2026-11-v2` (nothing collected
  yet: the waitlist is still closed).
- **`yt-check`** (`youtube_intelligence.preflight`, `POST /v1/check`): the pre-upload check.
  FAIL is reserved for objective YouTube rule breaks (title over 100 characters, description over
  5,000 bytes, `<` or `>` in either, description chapters that will not render, checked against
  the real video length); WARN for judgement (weak opening, opening that doesn't echo the title,
  a subscribe pitch or channel intro in the first 30 s, flagged title, over 10% removable, target
  search words missing from the title and first two description lines). Verdict: ready / ready
  with fixes / not yet; the CLI exits 1 when not ready. Drafts chapters when none are given.
- **`yt-report`** (`youtube_intelligence.reports.channel`): a channel report built from the
  existing tools (multiple of the channel median, title lint, formula, retention) that ends in one
  fix chosen by four stated rules (leaking opening, then flagged packaging, then the steepest
  cliff, then nothing urgent). HTML (self-contained, all third-party text escaped), Markdown or
  JSON (`channel-report@1`). Reads `yt-youtube` output directly. A sample built from invented
  data is published at `/sample-report` and linked from the Creator plan; a test keeps it
  identical to the generator's output.
- **Demand test on the landing page**: a Plans section (planned prices, clearly not on sale) and
  a waitlist form with consent and a privacy notice (`public/privacy.html`, with placeholders to
  be completed before opening). `api/waitlist.js` (Vercel function, no dependencies) validates
  and stores the minimum through Supabase's anon key, is off unless `WAITLIST_ENABLED=1`, never
  logs emails, and answers duplicates like new sign-ups. `supabase/waitlist.sql` makes the table
  insert-only for the website (verified on PostgreSQL 16 with Supabase's roles). CSP adds
  `connect-src 'self'`. `scripts/update_csp_hash.py` refreshes the script hash. Go-live steps:
  `docs/WAITLIST.md`.
- `GET /v1/openapi.json`: OpenAPI 3.1 description of `yt-serve`, tested to list exactly the
  served routes.
- Dev dependency: `jsonschema` (tests only; runtime stays standard-library only).
- **Landing page** (`public/index.html`): a single static page for creators with a developer
  section; no external scripts, fonts or trackers; light/dark; checked at phone and desktop
  widths. Its example outputs are tested against the tools' real output, and its links and
  install commands against the project. Deployed on **Vercel** (`vercel.json`): the page lives
  in `public/` (the folder Vercel serves for a static site with no configuration) and there is no
  install or build step; two earlier deploys failed on folder handling, and sends a strict Content Security Policy (no external sources; the one
  inline script pinned by SHA-256, tested to match), plus `nosniff`, `DENY` framing, HSTS, and a
  locked-down Permissions-Policy. The GitHub Pages workflow was removed in favour of Vercel.

### Changed
- **chapters**: the default `--target` is derived from the video's length (about one per 90 s,
  plus one, between 3 and 10; equals the old 7 for a 9-minute video). An explicit `--target`
  behaves exactly as before. JSON adds `target`. On synthetic-v1, chapter precision went from
  0.42 to 1.00 (see the circularity caution in docs/EVALUATION.md).

### Fixed
- WebVTT: only a truly empty line ends a cue. YouTube auto-captions put a single-space line inside
  cues, and treating it as the end dropped the following line's words (found while building
  synthetic-words-v1). YouTube "rolling" duplicates are now dropped when a file carries inline
  word tags, so each spoken line appears once. Plain files are unaffected.
- yt-eval scored held-back cuts as predictions under `--hold-review`; only applied cuts count now.

### Found by the evaluation (documented, not yet changed)
- deadair cuts deliberate emphasis pauses (3.65 s of 6.8 s labelled "keep").
- On auto-caption transcripts, filler and retake detection mostly fails (chunked, overlapping cues).
- Fillers inside a sentence are never cut.
- chapters at the default `--target 7` over-proposes boundaries on short talks (precision 0.42).

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
