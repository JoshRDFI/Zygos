"""Parsing of host names as they appear in a Host header or in configuration.

Stability: Experimental.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


def parse_host_header(value: str) -> str | None:
    """The lower-cased hostname of a Host header value (port and trailing dot
    dropped), or None when the value is malformed."""
    value = value.strip()
    if not value or any(c.isspace() for c in value):
        return None
    if value.startswith("["):
        end = value.find("]")
        if end < 0:
            return None
        name, rest = value[1:end], value[end + 1:]
        if not name or (rest and not (rest.startswith(":") and rest[1:].isdigit())):
            return None
    else:
        name, sep, port = value.partition(":")
        if sep and not port.isdigit():
            return None
        if not name or ":" in port:
            return None
    return name.lower().rstrip(".") or None


def normalize_host_entry(entry: str) -> str | None:
    """The hostname a configured entry names, or None when it cannot be parsed.

    Accepts what a person naturally writes: a bare name or address, ``name:port``,
    a bracketed or bare IPv6 address, or a URL such as ``http://zygos.lan:8443``.
    """
    value = entry.strip()
    if "://" in value:
        try:
            value = urlsplit(value).netloc
        except ValueError:
            return None
        if "@" in value:
            return None
    if "/" in value:
        return None
    try:
        ipaddress.IPv6Address(value)
    except ValueError:
        return parse_host_header(value)
    return value.lower()
