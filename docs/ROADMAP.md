# Roadmap

"Implemented" means it runs and is tested in this repository. Everything else is planned.

## Implemented (0.1.0)

- Eleven Claude skills (upstream workflows plus guardrails).
- Seven deterministic tools: hookscore, title, deadair, chapters, retention, swipe/outliers,
  shorts (new). Stdlib only, CLI and library, 183 tests, CI.
- Stable EDL JSON (`edl@1`).

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
- Next for production use: run behind a TLS reverse proxy with rate limits; an OpenAPI document
  generated from the endpoint table; per-workspace tokens when TAKE has workspaces.
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

- Approval records, action executor and action log ([SECURITY.md](SECURITY.md)).
- CineForge `production-instruction@1` ([TAKE_CINEFORGE_INTEGRATION.md](TAKE_CINEFORGE_INTEGRATION.md)).
- Write scopes, one feature at a time: metadata updates, comment replies, then publishing.

Not planned: unattended posting, scraping logged-in pages, tag generators.
