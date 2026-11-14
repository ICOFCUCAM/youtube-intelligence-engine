# Contributing

## Ground rules

1. **Preserve provenance.** Never edit upstream SKILL.md text above the ICOFCUCAM marker line,
   or `hooks.json` / `templates/voice.md`, except when syncing from upstream (see
   [UPSTREAM.md](UPSTREAM.md)). Add guidance below the marker.
2. **No silent behaviour changes.** If a tool's output changes for an existing input, record it
   in [CHANGELOG.md](CHANGELOG.md) and update or add a test that pins the new behaviour. The
   golden files in `tests/fixtures/upstream_golden/` are upstream outputs. Never regenerate them
   from this code.
3. **Every bug fix gets a regression test** that fails on the old code.
4. **No placeholders.** Don't add a module, flag or doc that claims something works unless it
   runs and is tested. Planned work goes in [docs/ROADMAP.md](docs/ROADMAP.md).
5. **Standard library only** at runtime. A new runtime dependency needs a reason in the PR.
6. **Nothing acts on a channel without a human.** See [docs/SECURITY.md](docs/SECURITY.md).

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

```bash
.venv/bin/pytest
```

```bash
.venv/bin/python -m compileall -q src skills tests
```

## Adding a tool

- Put the logic in the right package under `src/youtube_intelligence/`, as pure functions plus a
  `main(argv) -> int` wrapped in `core.cli.guarded`.
- Raise `core.errors.InputError` for bad input. Never let a parser exception reach the user.
- Add a console script in `pyproject.toml`, an entry in `__main__.TOOLS`, and, if a skill uses
  it, a thin entry point in the skill folder.
- Tests: happy path, empty input, malformed input, missing file, boundaries, and the CLI exit code.

## Commits

Conventional prefixes (`feat:`, `fix:`, `docs:`, `test:`, `chore:`). Do not commit `.env` files,
OAuth client secrets, tokens or channel exports containing personal data.
