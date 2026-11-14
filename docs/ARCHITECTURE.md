# Architecture

## Principle

The YouTube Intelligence Engine is the **intelligence layer**. It reads material (transcripts,
analytics exports, collected listings, comments, ideas), and produces **decisions and drafts**:
hooks, scripts, titles, edit decision lists, chapters, retention diagnoses, Shorts candidates,
plans and reply drafts.

It does **not** process media and does **not** act on a channel.

- Media processing, rendering and transcoding belong to **CineForge**.
- The creator-facing studio and channel management belong to **TAKE**.
- Publishing, replying, deleting and changing settings belong to a **human**, who approves an
  explicit action.

Neither TAKE nor CineForge is a dependency. The engine is useful on its own: CLI, Python library
and Claude skills.

## Today (0.1.0)

```
            Claude skills (skills/yt-*/SKILL.md)          humans / scripts
                         |                                       |
                 skill entry points (skills/*/*.py)      yt-* console scripts
                         \_____________________  ______________/
                                               \/
                              youtube_intelligence (stdlib only)
   +--------------------------------------------------------------------------------+
   | creative/hookscore  packaging/title  editing/deadair  editing/chapters          |
   | analytics/retention research/outliers shorts/candidates                         |
   |--------------------------------------------------------------------------------|
   | core/transcript  core/intervals  core/formulas (data/hooks.json)  core/cli+errors |
   +--------------------------------------------------------------------------------+
                  inputs: local files          outputs: stdout text / JSON
   +--------------------------------------------------------------------------------+
   | evaluation/ (yt-eval)            integrations/youtube/ (yt-youtube, read-only) |
   +--------------------------------------------------------------------------------+
     labelled datasets -> metrics        YouTube APIs -> the same files the tools read
```

Properties that hold today and should be kept:

1. **Pure functions plus thin CLIs.** Each module exposes functions that take parsed data and
   return dicts (`deadair.analyse`, `chapters.build`, `retention.analyse`, `outliers.rank`,
   `candidates.find`, `title.check`, `hookscore.evaluate`). `main(argv)` only parses arguments,
   reads files and prints. That makes the future service layer a wrapper, not a rewrite.
2. **One parser per format** (`core/transcript`). Every transcript consumer shares it, so a fix
   lands everywhere. That shared loader is how the upstream JSON-array bug spread to three tools.
3. **Typed failure.** Bad input raises `InputError`, which the CLI maps to exit 1.
4. **Deterministic.** Same input, same output, regardless of hash seed or platform.
5. **No network, no secrets, no side effects** in the analysis packages. Network access exists
   only in `integrations/youtube/transport.py`, read-only.

## Where the skills fit

The skills are the "AI-assisted" half. Claude follows the SKILL.md workflow, calls the
deterministic tools for anything measurable, and drafts the creative parts in the creator's voice
(`~/.claude/youtube/voice.md`). The tools keep the model honest about timings and counts. The
model supplies the language. Every skill ends in a human gate ("ship it, or change it?").

## Target architecture (not built)

Build these only when a real consumer needs them. See [ROADMAP.md](ROADMAP.md).

```
 TAKE (studio UI)  ---- HTTP/JSON ---->  Engine API (thin, stateless first)
                                            |-- workspace / channel / creator scoping
                                            |-- the same pure functions as today
                                            |-- AI adapter interface (provider-independent)
                                            |-- YouTube connector (read-only OAuth first)
                                            |-- approval queue + action log
                                            v
                         approved EDL / production instructions
                                            v
                                     CineForge API (media)
```

Planned domain objects: `Workspace` (team) > `Channel` > `Creator` with `VoiceProfile` >
`Project` (a video) > artefacts (`Script`, `HookSet`, `Packaging`, `EditDecisionList`,
`ChapterList`, `RetentionReport`, `ShortsCandidates`). Each artefact is versioned and carries
`approved_by` / `approved_at` before anything downstream may act on it.

**AI adapters.** A small interface (`complete(prompt, schema) -> result`) with one implementation
per provider. The deterministic tools never depend on it. The skills currently run inside Claude
and need no adapter.

**Storage.** None today. When needed: start with files or SQLite per workspace, and move to a
managed database only for multi-user TAKE deployments.

Detailed contracts: [API_DESIGN.md](API_DESIGN.md), [TAKE_CINEFORGE_INTEGRATION.md](TAKE_CINEFORGE_INTEGRATION.md),
[YOUTUBE_API_INTEGRATION.md](YOUTUBE_API_INTEGRATION.md), [SECURITY.md](SECURITY.md).
