# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub's **"Report a vulnerability"** (Security
Advisories) on https://github.com/ICOFCUCAM/youtube-intelligence-engine, not in a public issue.
Include the affected tool or skill, an input that reproduces it, and the impact. We aim to
acknowledge within 7 days.

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | yes |

## Scope today

The current release is offline: the tools read local files and print results. They make no
network calls, store no credentials, and cannot publish, reply, delete or change anything on
YouTube. The skills instruct Claude to draft only. The threat model, including prompt injection
through transcripts and comments, and the rules any future YouTube API integration must follow,
are in [docs/SECURITY.md](docs/SECURITY.md).

Never commit API keys, OAuth client secrets or tokens. `.gitignore` blocks the common file names,
and a test fails if a tracked file contains a key-shaped string.
