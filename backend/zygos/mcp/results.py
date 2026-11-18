"""MCP tool results -> what a Zygos tool returns, and the MCP error types.

Pure: imports nothing from the MCP SDK; content blocks are read by their ``type`` and
attributes, so any object shaped like the SDK's ``CallToolResult`` works. Results are
untrusted server data; they are passed on as data, never acted on.
"""

from __future__ import annotations

from typing import Any


class McpUnavailable(Exception):
    """Couldn't reach the server, it timed out, or the transport failed. The message is a
    reason a user can read and never contains header or env values."""


class McpToolError(Exception):
    """The server answered, but the call failed (``isError``, or an MCP error reply)."""


def _artifact_line(kind: str) -> str:
    return f"[{kind} returned — shown once artifacts arrive]"


def _block_text(block: Any) -> str:
    kind = getattr(block, "type", None)
    if kind == "text":
        return str(getattr(block, "text", ""))
    if kind in ("image", "audio"):
        return _artifact_line(kind)
    if kind == "resource_link":
        return f"[resource: {getattr(block, 'uri', '')}]"
    if kind == "resource":
        resource = getattr(block, "resource", None)
        text = getattr(resource, "text", None)
        if isinstance(text, str):
            return text
        return f"[resource: {getattr(resource, 'uri', '')}]"
    return f"[{kind or 'unknown'} content]"


def map_result(result: Any) -> Any:
    """Text parts joined with newlines; with structured content, ``{"text", "structured"}``.

    Raises ``McpToolError`` (with the result's text) when the server flags ``isError``.
    """
    text = "\n".join(_block_text(block) for block in (getattr(result, "content", None) or []))
    if getattr(result, "is_error", False):
        raise McpToolError(text or "the tool reported an error without saying why")
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return {"text": text, "structured": structured}
    return text
