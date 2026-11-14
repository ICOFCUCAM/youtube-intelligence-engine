# Roadmap

"Implemented" means it runs and is tested in this repository. Everything else is planned.

## Implemented (0.1.0)

- Eleven Claude skills (upstream workflows plus guardrails).
- Seven deterministic tools: hookscore, title, deadair, chapters, retention, swipe/outliers,
  shorts (new). Stdlib only, CLI and library, 183 tests, CI.
- Stable EDL JSON (`edl@1`).

## Phase 1: harden and measure

- Evaluation sets: real (consented or public) transcripts and retention exports with human
  labels, to measure deadair precision and recall, chapter boundary accuracy, and Shorts
  shortlist quality. Today the only evidence is upstream's 74-hook study and our unit tests.
- Improve the hook-formula patterns, which misclassify 8 of 21 of their own examples, as a
  documented, tested change to the data with a version bump.
- Optional `--views` on retention to warn about low-sample curves.
- Comment triage helper (questions, corrections, praise, possible bait) for `/yt-comment`, if a
  labelled sample shows a heuristic beats letting the model do it.

## Phase 2: service layer (when TAKE needs it)

- Stateless HTTP API wrapping the library ([API_DESIGN.md](API_DESIGN.md)).
- Voice profiles as structured data per creator, not just `voice.md`.
- Provider-independent AI adapter interface for the drafting steps outside Claude Code.

## Phase 3: YouTube read-only

- OAuth with `youtube.readonly` and `yt-analytics.readonly`, metadata, analytics reports and
  comment ingestion ([YOUTUBE_API_INTEGRATION.md](YOUTUBE_API_INTEGRATION.md)).
- Multiple channels, workspaces and teams, research workspaces, and editorial calendar storage.

## Phase 4: approved actions

- Approval records, action executor and action log ([SECURITY.md](SECURITY.md)).
- CineForge `production-instruction@1` ([TAKE_CINEFORGE_INTEGRATION.md](TAKE_CINEFORGE_INTEGRATION.md)).
- Write scopes, one feature at a time: metadata updates, comment replies, then publishing.

Not planned: unattended posting, scraping logged-in pages, tag generators.
