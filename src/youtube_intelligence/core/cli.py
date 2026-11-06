"""Small helpers so every CLI handles bad input the same way."""
from __future__ import annotations

import functools
import sys
from typing import Callable, List, Optional

from .errors import InputError


def guarded(main: Callable[[Optional[List[str]]], int]) -> Callable[[Optional[List[str]]], int]:
    """Turn :class:`InputError` into ``error: ...`` on stderr and exit status 1."""

    @functools.wraps(main)
    def run(argv: Optional[List[str]] = None) -> int:
        try:
            return main(argv)
        except InputError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    return run


def read_lines(path: str) -> List[str]:
    """Non-empty lines of a UTF-8 text file, or :class:`InputError`."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            return [ln for ln in fh.read().splitlines() if ln.strip()]
    except FileNotFoundError:
        raise InputError(f"file not found: {path}") from None
    except IsADirectoryError:
        raise InputError(f"{path} is a directory") from None
