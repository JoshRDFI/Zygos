"""``${ENV_VAR}`` placeholder resolution, ported from v1 loader semantics. Stability: Experimental."""

import os
import re

_PLACEHOLDER = re.compile(r"^\$\{([A-Za-z0-9_]+)\}$")


def resolve_env_placeholders(value: object) -> object:
    if isinstance(value, str):
        match = _PLACEHOLDER.match(value)
        if match is None:
            return value
        return os.environ.get(match.group(1))
    if isinstance(value, list):
        return [resolve_env_placeholders(item) for item in value]
    if isinstance(value, dict):
        return {key: resolve_env_placeholders(item) for key, item in value.items()}
    return value
