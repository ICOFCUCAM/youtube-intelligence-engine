"""The only code that touches the network. Replaceable for tests.

A transport is ``(method, url, headers, body) -> (status, body_bytes)``. HTTPS only; responses
larger than MAX_RESPONSE bytes are refused.
"""
from __future__ import annotations

import urllib.error
import urllib.request
from typing import Callable, Dict, Optional, Tuple

from ...core.errors import InputError

Transport = Callable[[str, str, Dict[str, str], Optional[bytes]], Tuple[int, bytes]]
MAX_RESPONSE = 20 * 1024 * 1024
TIMEOUT = 30


def default_transport(method: str, url: str, headers: Dict[str, str], body: Optional[bytes] = None) -> Tuple[int, bytes]:
    if not url.startswith("https://"):
        raise InputError("refusing a non-HTTPS request")
    req = urllib.request.Request(url, data=body, headers=dict(headers, **{"User-Agent": "youtube-intelligence-engine"}),
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 - https enforced above
            data = resp.read(MAX_RESPONSE + 1)
            status = resp.status
    except urllib.error.HTTPError as exc:
        data, status = exc.read(MAX_RESPONSE + 1), exc.code
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise InputError(f"network error: {getattr(exc, 'reason', exc)}") from None
    if len(data) > MAX_RESPONSE:
        raise InputError("response too large")
    return status, data
