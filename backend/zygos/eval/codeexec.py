"""Sandboxed execution scoring for code tasks. Stability: Experimental."""

import re

_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\n(.*?)```", re.DOTALL)


def extract_code(text: str) -> str:
    """Return the last fenced code block's body, else the stripped whole text."""
    blocks = _FENCE.findall(text)
    if blocks:
        return blocks[-1].strip()
    return text.strip()
