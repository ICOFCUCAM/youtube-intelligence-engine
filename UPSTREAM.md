# Upstream provenance

| | |
| --- | --- |
| Upstream project | youtube-agent-skill |
| Upstream URL | https://github.com/Jakeschincariol/youtube-agent-skill |
| Upstream author | Jake Schincariol |
| Upstream licence | MIT, "Copyright (c) 2026 Jake Schincariol" (kept in [LICENSE](LICENSE)) |
| Extraction commit | `a2feb2104981a375ffd4f87ee04f4f5344ac43c6` (2026-09-16, "The YouTube agent skill: eleven skills, six tools") |
| Files at that commit | 24 |
| Upstream repository modified? | No. It was cloned read-only. |

The first commit of this repository (`chore: import upstream youtube-agent-skill verbatim`) is
the upstream tree, byte for byte. Every ICOFCUCAM change after it is visible with `git diff` against
that commit.

A machine-readable record of every upstream file, with its SHA-256 at the extraction commit, its
destinations here and its status, is in [docs/upstream-manifest.json](docs/upstream-manifest.json).
`tests/test_provenance.py` checks it on every test run.

## Status of each upstream file

**Imported verbatim (3)**: byte-identical to upstream, verified by hash.

| Upstream file | Here |
| --- | --- |
| `skills/yt-script/hooks.json` | same path, plus `src/youtube_intelligence/data/hooks.json` (package data) |
| `templates/voice.md` | same path |
| `README.md` | `docs/upstream/README.md` (the root README is new) |

**Adapted, append-only (11)**: `skills/*/SKILL.md`. The upstream instructions are byte-identical
above the line

```
<!-- ICOFCUCAM additions below. Everything above this line is upstream text by Jake Schincariol (MIT), unmodified. -->
```

and ICOFCUCAM additions are appended below it: untrusted-input rules, tool install notes, and
per-skill guardrails. Verified by hashing the part above the marker.

**Adapted (10)**

| Upstream file | Here | What changed |
| --- | --- | --- |
| `skills/yt-edit/deadair.py` | `src/youtube_intelligence/editing/deadair.py`, `core/transcript.py`; skill-folder entry point | Defect fixes (see CHANGELOG). Loader moved to `core`. |
| `skills/yt-chapters/chapters.py` | `src/youtube_intelligence/editing/chapters.py`; entry point | Inherited loader fix; deterministic titles. Boundary algorithm unchanged. |
| `skills/yt-script/hookscore.py` | `src/youtube_intelligence/creative/hookscore.py`, `core/formulas.py`; entry point | Scoring unchanged (golden test); exit code fix; disclaimer. |
| `skills/yt-package/title.py` | `src/youtube_intelligence/packaging/title.py`; entry point | Number and claim scoring changed (documented); other checks unchanged. |
| `skills/yt-retention/retention.py` | `src/youtube_intelligence/analytics/retention.py`; entry point | Argument and axis fixes, limitations output. Analysis unchanged. |
| `skills/yt-viral/swipe.py` | `src/youtube_intelligence/research/outliers.py`; entry point | Input robustness; shared classifier. Ranking unchanged. |
| `LICENSE` | `LICENSE` | Upstream text and copyright line kept; ICOFCUCAM copyright line added. |
| `.gitignore` | `.gitignore` | Upstream lines kept; venv, build and credential patterns added. |
| `.claude-plugin/plugin.json` | same | Renamed to `youtube-intelligence`, ICOFCUCAM author, upstream credited in the description. |
| `.claude-plugin/marketplace.json` | same | As above. |

The six skill-folder `.py` files keep their upstream names and commands but are now thin entry
points into the package, so there is one implementation to test.

## ICOFCUCAM additions (not from upstream)

- `src/youtube_intelligence/` package structure, `core/errors.py`, `core/intervals.py`,
  `core/cli.py`, `__main__.py`
- `src/youtube_intelligence/shorts/candidates.py` and `skills/yt-shorts/shorts.py` (new tool)
- `tests/` (all), including `tests/fixtures/upstream_golden/`: outputs of the **unmodified
  upstream tools**, recorded at the extraction commit and used to prove equivalence
- `pyproject.toml`, `.github/workflows/ci.yml`
- `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`, everything in `docs/` except
  `docs/upstream/README.md`, and `examples/`

## Syncing with upstream later

1. Clone upstream and note its new commit SHA.
2. `git diff a2feb2104981a375ffd4f87ee04f4f5344ac43c6..<new>` upstream.
3. Apply SKILL.md changes above the marker, `hooks.json` and `voice.md` changes verbatim, and port
   tool changes into the package with tests.
4. Regenerate `docs/upstream-manifest.json` hashes, update this file and the golden outputs.
