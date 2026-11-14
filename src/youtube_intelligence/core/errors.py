"""Error types shared by every tool.

ICOFCUCAM addition. Upstream tools let parser exceptions escape as tracebacks; every tool now
raises :class:`InputError` for bad input and the CLIs turn it into a one-line message and exit 1.
"""


class InputError(ValueError):
    """The input file or value cannot be used. The message is safe to show to a user."""
