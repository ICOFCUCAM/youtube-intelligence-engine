# Audit: what has actually been built (2026-11-19)

An honest inventory of this repository: what exists, how it was checked, and what has **not**
been verified. Measured on `main`. Where this document and any other disagree, this one was
written last; tell us so it can be fixed.

## Verdict

The engine is real, tested working software: 17 commands, 12 Claude skills, a local HTTP API
and a landing page. Everything is checked offline: 499 Python tests and 10 Node tests pass (501 and 21 after the 2026-11-21 waitlist protections), and CI
is green on Python 3.10 to 3.14.

The main gap is evidence. **Apart from the upstream tools' reference outputs, no tool has been
run on a real creator's data, and only one live check has touched the YouTube API.** Accuracy
numbers come from synthetic or invented data built by the same author as the tools. The
integrations with YouTube, Supabase and CineForge are built to documented formats and tested
against simulations, not the real services.

## What exists

| Area | Built | Size |
| --- | --- | --- |
| Engine code (Python, standard library only at runtime) | 16 packages | ~5,300 lines |
| Tests | 499 Python (pytest) + 10 Node | ~3,100 lines |
| Commands (`yt-*`) | 17 | all start and print help |
| Claude skills | 12 (11 upstream + `/yt-localize`) | 10 with tool scripts in their folder |
| Local HTTP API (`yt-serve`) | 15 endpoints + OpenAPI 3.1 | loopback by default |
| Landing page (`public/`) | page, privacy notice, sample report | no external resources |
| Waitlist | Vercel function + Supabase SQL | switched off |
| Datasets / demo data | 2 synthetic evaluation sets, 5 invented demo sets | all labelled |
| Docs | 13 documents | this audit fixed drift in 6 |

## Verification status, component by component

"Offline" means tests in this repository on fixtures, synthetic or invented data. "Real" means
the component has met the real system or real data.

| Component | Offline | Real | Notes |
| --- | --- | --- | --- |
| Upstream tools: hookscore, title, deadair, chapters, retention, swipe | Yes; outputs equal the unmodified upstream tools on fixtures (golden tests) | **No** | 10 upstream defects reproduced and fixed, each with a regression test |
| Word timings (Whisper JSON) | Yes | **No** | Format as documented by Whisper |
| Word timings (YouTube auto-caption VTT) | Yes | **No** | Format **modelled**; downloading a real file was blocked in this environment |
| Shorts candidates | Yes, synthetic evaluation | **No** | Shortlist only |
| Evaluation harness (`yt-eval`) | Yes | n/a | Both datasets are synthetic; thresholds were chosen by the same author as the data |
| YouTube connector (`yt-youtube`) | Yes, fake transport | **Partly**: one live call with an invalid key returned Google's real error, cleanly, key redacted | The success path (real channel, retention, comments) has never run |
| `yt-youtube login` (OAuth) | Yes, simulated browser over real loopback HTTP | **No** | Never run against Google's consent screen |
| HTTP API (`yt-serve`) | Yes, a real server on loopback | Not deployed | Development server; needs TLS and rate limits in front of it |
| Approval records + production instructions | Yes; JSON Schema checked with `jsonschema` | **No** | Never sent to CineForge; no CineForge side exists here |
| Channel report (`yt-report`) | Yes, invented data | **No** | |
| Pre-upload check (`yt-check`) | Yes | **No** | FAIL rules use YouTube's documented limits |
| Moments (`yt-moments`) | Yes, scripted demo: recovers scripted effects within 0.1 points | **No** | Has a documented blind spot (the commonest kind of sentence sets the baseline) |
| Localisation (`yt-localize`) | Yes | **No** | Demo Spanish is an unreviewed AI translation |
| Fact guard (`yt-claims`) | Yes | **No** | Checks numbers match evidence, not that evidence is true |
| Comment triage (`yt-comments`) | Yes, invented comments | **No** | One documented false merge in question grouping |
| Landing page | Yes, Chromium at phone and desktop, light and dark, with the production headers replayed | **Partly**: the owner's screenshot showed the first version live on Vercel | Later versions (plans, waitlist, sample report) not confirmed live; this environment cannot reach `*.vercel.app` |
| Waitlist function (`api/waitlist.js`) | Yes, 10 Node tests | **No**; switched off | Never run on Vercel. It may not deploy if the Vercel project still uses the "Python" preset |
| Waitlist SQL | Yes, real PostgreSQL 16 with Supabase's roles, incl. the upgrade path | **No** | Never applied to a Supabase project |
| Security headers (CSP etc.) | Yes, replayed locally in Chromium | **No** | Live headers not inspected |
| CI | Green on 3.10-3.14 for every recent commit | Yes (GitHub Actions) | |

## Measurements taken for this audit

- **Tests:** 499 Python + 10 Node, all passing (including the upstream-equivalence golden tests
  and the provenance tests that hash-check the original author's files).
- **Coverage:** 80% of statements. This is understated for the commands, because many tests run
  them as separate processes, which coverage doesn't follow (`__main__.py` shows 0% while a test
  exercises it). The real weak spot is the network transport at 39%: it has met Google once.
- **Static analysis (pyflakes):** 2 unused imports in the engine (fixed). 18 warnings in the
  skill-folder scripts are deliberate re-exports kept for backward compatibility.
- **Dangerous constructs:** none: no `eval`, `exec`, `subprocess`, `shell=True`, pickle or YAML
  loading in engine code, scripts or the waitlist function.
- **Network:** outbound calls only in `integrations/youtube/transport.py`. Listening sockets
  only in `service/server.py` (loopback unless a token is set) and the one-time OAuth loopback
  listener in `integrations/youtube/login.py`.
- **Links:** 35 Markdown/HTML files checked. Two broken links, both in
  `docs/upstream/README.md`, the original author's README kept byte-for-byte: its links are
  relative to his repository. Accepted, because changing the file would break provenance.
- **Secrets:** a test scans every tracked file for key-shaped strings and credential file names;
  none found. `.env.example` holds names only.

## Problems this audit found and fixed

1. Two unused imports (`service/server.py`, `reports/channel.py`).
2. The landing page still said "Seven of the steps are backed by tools".
3. `docs/ROADMAP.md` still listed 11 skills, 7 tools and 183 tests as the current state.
4. `docs/ARCHITECTURE.md` omitted 7 of the newer packages.
5. `docs/API_DESIGN.md` was missing `/v1/check`, `/v1/claims`, `/v1/comments` and six library
   functions.
6. `UPSTREAM.md` (the provenance record) did not list most ICOFCUCAM additions.

## Open issues (not fixed here)

| Issue | Why it matters | Who |
| --- | --- | --- |
| Version is still 0.1.0, with a very large "Unreleased" section | Users can't tell what they have | Owner decides; tag 0.2.0 |
| The product name contains "YouTube" | YouTube's brand rules restrict it in a commercial product | Owner |
| Vercel project created with the "Python" preset | May stop the waitlist function deploying | Owner: set the preset to "Other" |
| Personal cloud environment `youtube-intelligence-engine` lists the wrong Vercel hosts | It was created with guessed addresses before the project name was known | Owner: fix to `youtube-intelligence-engine-site.vercel.app` or delete |
| Waitlist protections built but never run live: rate limits (2026-11-20), proof-of-work anti-spam, double opt-in by email and scheduled deletion (2026-11-21) | Untested with real Resend, Supabase and pg_cron | When opening it |
| `yt-serve` has no TLS or rate limiting of its own | Not safe to expose directly | Before deploying it |
| Heuristic tools are uncalibrated on real data | Thresholds (1.5 s review, 90 s chapters, 25-point hook leak) are assumptions | Needs real labelled data |

## Known limitations (by design, documented where they apply)

- Hook and title scores are word-pattern heuristics, not predictions (`docs/TOOL_REVIEW.md`).
- 13 of the 21 hook-library examples classify as their own formula.
- Retention readings are descriptive; sample size, video age, format and audience change them.
- `yt-moments` measures correlation, and can't see the most common kind of sentence.
- `yt-comments` matches words, not meaning (misses synonyms, can merge unrelated questions).
- `yt-claims` checks that numbers match the evidence file, not that the evidence is true.
- `yt-localize` checks structure, not translation quality.
- Everything drafts or analyses. Nothing publishes, replies, deletes or changes a channel.

## What would most improve confidence

1. **Run the tools on one real channel**: a few videos' transcripts, retention exports and
   comments, or read-only credentials. This turns every "No" in the Real column above into
   evidence.
2. **A small human-labelled set** of real transcripts, to measure (and then tune) the edit,
   chapter and Shorts thresholds.
3. **Confirm the live site**: the waitlist reply ("isn't open yet") and the security headers.
