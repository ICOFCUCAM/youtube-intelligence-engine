"""Read-only YouTube Data API v3 and YouTube Analytics API v2 connector. ICOFCUCAM addition.

Status: built against Google's documented request and response formats and tested with a fake
transport. It has NOT yet been exercised against the live API (no credentials were available
when it was written). Treat the first live run as a test.

Read-only by construction: the client has no method that writes, it refuses every HTTP method
except GET against the API hosts, and it only accepts the read-only OAuth scopes. Writing
(publishing, replying, editing) is deliberately absent - see docs/SECURITY.md.
"""
