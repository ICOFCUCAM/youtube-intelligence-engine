# YouTube Intelligence Engine

An independent, AI-assisted YouTube intelligence and creator-workflow engine from **ICOFCUCAM**:
research, scripting, content packaging, editing intelligence, retention analysis, Shorts
repurposing, SEO, channel planning and creator operations.

It is built from **[youtube-agent-skill](https://github.com/Jakeschincariol/youtube-agent-skill)
by Jake Schincariol** (MIT), at upstream commit `a2feb2104981a375ffd4f87ee04f4f5344ac43c6`. The
original eleven Claude skills and six tools are preserved. The tools are now one tested Python
package, with known defects fixed and documented. See [UPSTREAM.md](UPSTREAM.md) for exactly what
came from where.

**Landing page:** a static page in [`public/`](public/), deployed on Vercel
(configuration in [`vercel.json`](vercel.json): no build step, strict security headers). It
includes a demand test: planned plans (not on sale) and a waitlist that is **switched off** until
storage is chosen. See [docs/WAITLIST.md](docs/WAITLIST.md).

**Nothing here publishes, uploads, replies or deletes.** Every skill and tool drafts or analyses.
The creator decides and acts. See [SECURITY.md](SECURITY.md).

## What it is, today

| Area | Skill | Tool (CLI) | What it does |
| --- | --- | --- | --- |
| Creative | `/yt-script` | `yt-hookscore` | Five hooks off [21 formulas](skills/yt-script/hooks.json), scored by a **heuristic** five-property panel, then the spoken script with retention beats. |
| Packaging | `/yt-package` | `yt-title` | Title and thumbnail text linted as one pairing: truncation, duplication, vagueness, shouting, unverifiable claims. |
| Editing | `/yt-edit` | `yt-deadair` | Transcript to edit decision list: dead air, filler cues and retakes, with timecodes and a merged runtime estimate. Uses word timings when present (fillers inside sentences); marks short, possibly deliberate pauses `[review]`. |
| Editing | `/yt-chapters` | `yt-chapters` | Chapters from a transcript, checked against YouTube's rules (0:00 first, 3+ entries, 10 s minimum). |
| Analytics | `/yt-retention` | `yt-retention` | A Studio retention export read as hook leak, cliffs and slide, optionally quoting what was said at each cliff. |
| Research | `/yt-viral` | `yt-swipe` | Collected videos ranked by multiple over their own channel's median, with the title's formula named. |
| Shorts | `/yt-shorts` | `yt-shorts` *(new)* | Candidate 20-55 s spans inside a long video, scored on opening, turn and ending signals. |
| YouTube data | - | `yt-youtube` *(new, read-only)* | Fetches channel uploads (API key) and retention curves (OAuth) into the files `yt-swipe` and `yt-retention` read. Tested offline; not yet verified against the live API with real credentials. |
| Service | - | `yt-serve` *(new)* | The same tools as a local, stateless HTTP/JSON API (for TAKE or any app). Loopback by default; a token is required to listen beyond it. See [docs/API_DESIGN.md](docs/API_DESIGN.md). |
| Handoff | - | `yt-handoff` *(new)* | Approval records (SHA-256 pinned, HMAC-signed with a key) and `production-instruction@1` for a video engine such as CineForge. Only approved, unchanged artefacts become instructions. JSON Schema in [docs/schemas](docs/schemas/). |
| Report | `/yt-audit` | `yt-report` *(new)* | One channel report: recent uploads vs the channel median, title checks, retention where exported, and ONE fix chosen by stated rules. HTML (self-contained), Markdown or JSON. [Sample](public/sample-report.html) (invented data). |
| Moments | `/yt-retention` | `yt-moments` *(new)* | Across all your videos: what you were saying when viewers left. Each sentence's extra loss against the video's typical rate, grouped by type (sponsor reads, subscribe asks, tangents, recaps, signposts). Skips the first 30 s and last 10%; a pattern needs 3+ times across 2+ videos; correlation, not cause. |
| Comments | `/yt-comment` | `yt-comments` *(new)* | Triage into questions, corrections, praise and bait; scams and creator impersonators (incl. look-alike letters) with reasons; injection attempts flagged; video ideas from questions ranked by how many people asked; what to pin. `yt-youtube comments` fetches them read-only. Never acts on a comment. |
| Fact guard | `/yt-script`, `/yt-comment` | `yt-claims` *(new)* | Every figure, citation and result claim in a draft that your evidence file doesn't back, plus your own `voice.md` rules (words you never use, claims you won't make). Exit code 1 until it's clean. |
| Pre-upload | - | `yt-check` *(new)* | One command before upload: opening (hook, title echo, no early subscribe pitch), title + thumbnail, edit, description limits, chapter rules, search words, Shorts ready. FAIL only for objective YouTube rule breaks; WARN for judgement. Exit code 1 when not ready. |
| Evaluation | - | `yt-eval` *(new)* | Scores the edit, chapter and Shorts tools against labelled transcripts. See [docs/EVALUATION.md](docs/EVALUATION.md). |
| SEO | `/yt-seo` | - | Description, tags worth having, and the three queries the video should win. |
| Planning | `/yt-plan` | - | A week sized to real capacity: one anchor, one cheap one, Shorts from the anchor. |
| Community | `/yt-comment` | - | Comments triaged into four piles, replies drafted in the creator's voice. |
| Channel | `/yt-audit` | - | A channel audit that ends in ONE fix. |
| Languages | `/yt-localize` *(new)* | `yt-localize` *(new)* | Translation packs for title, description and captions: links, @handles, #hashtags and promo codes kept exactly, chapter timestamps kept, caption timing kept and wrapped to two lines, per-language checks, files built only when nothing fails. The tool doesn't translate; Claude or a translator does, and a fluent speaker should review. |

Skills are prompt workflows for Claude. Tools are deterministic Python on the standard library
only. The analysis tools never touch the network. Only the optional `yt-youtube` connector
does, read-only, with credentials from environment variables (see [`.env.example`](.env.example)).

## Install

### As a Claude Code plugin

```
/plugin marketplace add ICOFCUCAM/youtube-intelligence-engine
/plugin install youtube-intelligence
```

### As Python tools

```bash
pip install git+https://github.com/ICOFCUCAM/youtube-intelligence-engine
```

```bash
yt-deadair transcript.srt --json
```

### As copied skills

```bash
git clone https://github.com/ICOFCUCAM/youtube-intelligence-engine.git
```

```bash
cp -r youtube-intelligence-engine/skills/yt-* ~/.claude/skills/
```

Skill folders copied on their own need the package installed (`pip install` above) for their
scripts to run. Each script says so if it is missing.

Then fill in [`templates/voice.md`](templates/voice.md) and copy it to
`~/.claude/youtube/voice.md`. Every skill reads it.

## The tools

```bash
yt-hookscore --hook "one line"                 # heuristic 5-property hook panel
yt-title --title "..." --thumb "..."           # title + thumbnail linter
yt-deadair transcript.srt                      # edit decision list (.srt / .vtt / whisper .json)
yt-chapters transcript.srt --target 8          # validated chapters
yt-retention retention.csv --duration 600      # hook leak, cliffs, slide
yt-swipe collected.json --min 2.0              # outliers by own-channel multiple
yt-shorts transcript.srt --top 5               # Shorts candidates
yt-eval datasets/synthetic-v1/dataset.json     # measure the tools against labels
yt-youtube channel-videos --handle @Chan --out collected.json   # read-only fetch (YOUTUBE_API_KEY)
yt-serve                                       # HTTP/JSON API on http://127.0.0.1:8765
yt-report videos.json --retention ID=ret.csv   # channel report with one fix
yt-check --title "..." --transcript t.srt --description d.txt   # pre-upload verdict
yt-moments manifest.json                       # what you said when viewers left, across videos
yt-localize export --title "..." --transcript t.srt --lang es,fr --out pack.json   # then check, build
```

Every tool takes `--json`. Every tool exits `1` with a one-line `error:` message on unusable
input; none prints a traceback for bad input. The upstream commands still work from inside a
skill folder (`python3 deadair.py transcript.srt`). See [examples/](examples/).

## What the numbers mean, and do not

- **`yt-hookscore` is a heuristic.** It is word lists and regular expressions, not a model of
  viewers. It does not predict views or virality, and it can be gamed (every number raises
  SPECIFICITY). Upstream's calibration found it separates bad hooks from real ones, but barely
  separates a creator's hits from their misses.
- **`yt-title` does not reward numbers.** A figure helps a title only if it is true and the video
  shows it. Guarantee, income and "overnight" language is flagged.
- **`yt-retention` is descriptive.** Small samples, video age, format (Shorts vs long-form) and
  traffic mix all change the curve. Its thresholds are long-form rules of thumb.
- **`yt-deadair` measures speech.** Its runtime estimate ignores silent demos and B-roll. On
  the synthetic evaluation set it finds all dead air but also cuts pauses kept for emphasis, and
  misses most fillers in auto-generated captions. A Whisper transcript with word timestamps
  fixes the inline-filler blind spot. Review its cuts, especially those marked `[review]`; do not
  apply them blind.
- **Formula names are about the words**, not about why a video worked.

Details: [docs/TOOL_REVIEW.md](docs/TOOL_REVIEW.md). What has and hasn't been verified against
real systems: [docs/AUDIT.md](docs/AUDIT.md).

## Repository layout

```
skills/            the eleven Claude skills (upstream instructions + ICOFCUCAM additions)
src/youtube_intelligence/
  core/            transcript parsing, interval maths, hook-formula library, CLI helpers
  creative/        hookscore
  packaging/       title
  editing/         deadair (EDL), chapters
  analytics/       retention
  research/        outliers (upstream swipe.py)
  shorts/          Shorts candidates (new)
  evaluation/      metrics, dataset loader, yt-eval (new)
  integrations/    youtube/: read-only Data + Analytics API connector, yt-youtube (new)
  service/         stateless HTTP/JSON API, yt-serve, OpenAPI (new)
  handoff/         approval records + production instructions, yt-handoff (new)
  data/hooks.json  the 21-formula library (upstream, unmodified)
templates/         voice.md (upstream, unmodified)
datasets/          labelled evaluation sets (synthetic-v1, synthetic-words-v1: generated, pinned baselines)
tests/             pytest suite, fixtures, upstream golden outputs
docs/              architecture, security, API design, integrations, roadmap, reviews
api/               waitlist.js: the landing page's sign-up function (Vercel), off by default
supabase/          waitlist.sql: insert-only waitlist table
public/            the landing page (static HTML, no external requests), deployed on Vercel via vercel.json
examples/          runnable examples
```

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

```bash
.venv/bin/pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Roadmap and integrations

Not implemented yet, and designed for later: multiple channels and teams, voice profiles as
data, research workspaces, an OAuth login command and any YouTube write action (behind human
approval), provider-independent AI adapters, and stable interfaces to **CineForge** (media processing) and **TAKE** (creator studio).
This repository depends on neither. See [docs/ROADMAP.md](docs/ROADMAP.md),
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
[docs/YOUTUBE_API_INTEGRATION.md](docs/YOUTUBE_API_INTEGRATION.md) and
[docs/TAKE_CINEFORGE_INTEGRATION.md](docs/TAKE_CINEFORGE_INTEGRATION.md).

## Licence and credit

MIT. See [LICENSE](LICENSE). The original work, including the skill instructions, the 21-formula
hook library, the voice template and the six tools' designs, is by **Jake Schincariol**:
https://github.com/Jakeschincariol/youtube-agent-skill. ICOFCUCAM's modifications and additions
are also MIT. The original README is kept at [docs/upstream/README.md](docs/upstream/README.md).
