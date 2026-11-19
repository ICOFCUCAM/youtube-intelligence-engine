# Roadmap

"Implemented" means it runs and is tested in this repository. Everything else is planned.

## Implemented

0.1.0: eleven upstream skills with guardrails; seven deterministic tools (hookscore, title,
deadair, chapters, retention, swipe/outliers, shorts); stable EDL JSON (`edl@1`).

Since then (Unreleased, see CHANGELOG): a twelfth skill (`/yt-localize`); seventeen commands in
total; the evaluation harness; the read-only YouTube connector and `login`; the HTTP service with
OpenAPI; approval records and production instructions; the channel report, pre-upload check,
moments, localisation, fact guard and comment triage; the landing page, waitlist and sample
report. 499 Python tests and 10 Node tests, CI on Python 3.10-3.14. What has and hasn't been
verified against real systems: [AUDIT.md](AUDIT.md).

## Phase 1: harden and measure

- Done: evaluation harness `yt-eval`, the synthetic-v1 set and its pinned baseline
  ([EVALUATION.md](EVALUATION.md)); `yt-retention --views`.
- Done: word timings (Whisper, YouTube inline tags), the `[review]` flag and `--hold-review`,
  length-based chapter count, `synthetic-words-v1`.
- Next: a **real** labelled set (consented transcripts, labelled by an editor), so that
  accuracy claims rest on real recordings and the 1.5 s review threshold and 90 s chapter spacing
  can be tuned on data their author did not write. Check the YouTube auto-caption model against a
  real downloaded caption file.
- Improve the hook-formula patterns, which misclassify 8 of 21 of their own examples, as a
  documented, tested change to the data with a version bump.
- Comment triage helper (questions, corrections, praise, possible bait) for `/yt-comment`, if a
  labelled sample shows a heuristic beats letting the model do it.

## Phase 2: service layer (when TAKE needs it)

- Done: stateless HTTP API wrapping the library, `yt-serve` ([API_DESIGN.md](API_DESIGN.md)).
- Done: OpenAPI 3.1 document at `/v1/openapi.json`, tested to match the served routes.
- Next for production use: run behind a TLS reverse proxy with rate limits; per-workspace tokens
  when TAKE has workspaces.
- Voice profiles as structured data per creator, not just `voice.md`.
- Provider-independent AI adapter interface for the drafting steps outside Claude Code.

## Phase 3: YouTube read-only

- Done (offline-tested, live success path unverified): `yt-youtube` read-only connector:
  uploads and metadata via API key, retention curve via OAuth, mapped into the existing tools.
- Done: `yt-youtube login` (loopback + PKCE consent, token file mode 600).
- Next: verify both against the live API with real read-only credentials; performance metrics
  beyond retention;
  comment ingestion for `/yt-comment` ([YOUTUBE_API_INTEGRATION.md](YOUTUBE_API_INTEGRATION.md)).
- Multiple channels, workspaces and teams, research workspaces, and editorial calendar storage.

## Phase 4: approved actions

- Done: approval records (signed with `YIE_APPROVAL_KEY`) and `production-instruction@1` with a
  JSON Schema, `yt-handoff`, and `/v1/handoff/*` ([TAKE_CINEFORGE_INTEGRATION.md](TAKE_CINEFORGE_INTEGRATION.md)).
- Next: a first real instruction through CineForge; storage and versioning of approvals; the
  action executor and action log for YouTube writes ([SECURITY.md](SECURITY.md)).
- Write scopes, one feature at a time: metadata updates, comment replies, then publishing.

Not planned: unattended posting, scraping logged-in pages, tag generators.
