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
_SHOW_MAX = 40
_RULE = (
    "expected provider:<name>, mcp:<server>:env:<NAME> or mcp:<server>:header:<Name>; "
    "segments non-empty without ':', whitespace or control characters; max 256 chars"
)


def validate_handle(handle: str) -> str:
    if isinstance(handle, str) and len(handle) <= _MAX_LEN and any(p.fullmatch(handle) for p in _PATTERNS):
        return handle
    raise InvalidHandle(f"invalid secret handle {_shown(handle)}: {_RULE}")


def _shown(handle: str) -> str:
    # Swapped arguments put a secret where the handle goes: only echo input that
    # starts like a handle, and only its start.
    if not isinstance(handle, str) or not handle.startswith(("provider:", "mcp:")):
        return "(not shown)"
    return repr(handle if len(handle) <= _SHOW_MAX else handle[: _SHOW_MAX - 3] + "...")
