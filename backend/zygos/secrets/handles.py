"""Secret handle grammar.

Forms: ``provider:<name>``, ``mcp:<server>:env:<NAME>``, ``mcp:<server>:header:<Name>``.
Segments are non-empty with no ``:``, whitespace or control characters; the whole
handle is at most 256 characters. A handle names a secret, it is not a secret.

Stability: Experimental.
"""

from __future__ import annotations

import re

from zygos.secrets.types import InvalidHandle

_SEG = r"[^:\s\x00-\x1f\x7f]+"
_PATTERNS = (
    re.compile(rf"provider:{_SEG}"),
    re.compile(rf"mcp:{_SEG}:(?:env|header):{_SEG}"),
)
_MAX_LEN = 256
_RULE = (
    "expected provider:<name>, mcp:<server>:env:<NAME> or mcp:<server>:header:<Name>; "
    "segments non-empty without ':', whitespace or control characters; max 256 chars"
)


def validate_handle(handle: str) -> str:
    if len(handle) <= _MAX_LEN and any(p.fullmatch(handle) for p in _PATTERNS):
        return handle
    shown = handle if len(handle) <= 80 else handle[:77] + "..."
    raise InvalidHandle(f"invalid secret handle {shown!r}: {_RULE}")
