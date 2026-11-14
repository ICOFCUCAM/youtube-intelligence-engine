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

The analysis tools read local files and print results; they make no network calls. The optional
`yt-youtube` connector reads from the YouTube Data and Analytics APIs with credentials taken from
environment variables. It is read-only by construction: GET requests only, read-only OAuth scopes
only, no write methods. Nothing in this repository stores credentials or can publish, reply,
delete or change anything on YouTube. The skills instruct Claude to draft only. The threat model,
including prompt injection through transcripts and comments, and the rules for the YouTube
integration, are in [docs/SECURITY.md](docs/SECURITY.md).

Report a vulnerability in the connector (for example a way to make it write, or to leak a key)
with the same private process above.

Never commit API keys, OAuth client secrets or tokens. `.gitignore` blocks the common file names,
and a test fails if a tracked file contains a key-shaped string.
