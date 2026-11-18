"""Transport-neutral pieces shared by remote and local MCP servers.

Tool listing (each tool's schema checked, a bad schema leaving only that tool out),
the protocol era test, hiding secret values in text, and turning SDK failures into
reasons a user can read. Nothing here knows about HTTP or processes.

The MCP SDK is imported inside the functions, so importing this module never imports it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from zygos.agent.schema import check_input_schema
from zygos.mcp.results import McpToolError, McpUnavailable
from zygos.mcp.types import SeenTool

__all__ = [
    "ListResult",
    "dump_discover",
    "guard_streams",
    "is_modern",
    "leaf",
    "list_pages",
    "scrub",
    "seen_tool",
    "translate",
    "ttl_seconds",
]

_PAGE_CAP = 100
_ROOT_MARK = "x-zygos-original-input-schema"
_NOT_OBJECT = "input schema root must be an object schema"


@dataclass(frozen=True)
class ListResult:
    era: str
    discover: dict[str, Any] | None
    tools: list[SeenTool]
    ttl_s: float | None


async def list_pages(client: Any) -> tuple[list[SeenTool], int]:
    """Every page of a connected client's ``tools/list`` (each schema checked) and the
    first page's ``ttlMs``. The client's streams must be wrapped with ``guard_streams``
    so one bad schema can't sink the listing."""
    tools: list[SeenTool] = []
    ttl_ms = 0
    cursor: str | None = None
    for page_no in range(_PAGE_CAP):
        page = await client.list_tools(cursor=cursor, cache_mode="bypass")
        if page_no == 0:
            ttl_ms = getattr(page, "ttl_ms", 0) or 0
        tools.extend(seen_tool(tool) for tool in page.tools)
        cursor = page.next_cursor
        if cursor is None:
            break
    return tools, ttl_ms


def ttl_seconds(era: str, ttl_ms: int) -> float | None:
    """A modern server's caching hint in seconds; ``None`` when it gave none (or is handshake-era)."""
    return ttl_ms / 1000 if is_modern(era) and ttl_ms > 0 else None


def dump_discover(client: Any) -> dict[str, Any] | None:
    """A connected client's discover result as stored JSON (``None`` for handshake-era servers)."""
    found = client.session.discover_result
    return None if found is None else found.model_dump(mode="json", by_alias=True, exclude_none=True)


def is_modern(version: str | None) -> bool:
    from mcp_types.version import MODERN_PROTOCOL_VERSIONS

    return version in MODERN_PROTOCOL_VERSIONS


# ---- tool listing ------------------------------------------------------------


def seen_tool(tool: Any) -> SeenTool:
    schema = tool.input_schema if isinstance(tool.input_schema, dict) else {}
    if _ROOT_MARK in schema:
        original = schema[_ROOT_MARK]
        schema = original if isinstance(original, dict) else {}
        problem = check_input_schema(schema) or _NOT_OBJECT
    else:
        problem = check_input_schema(schema)
    annotations = tool.annotations
    return SeenTool(
        name=tool.name,
        description=tool.description or "",
        input_schema=schema,
        annotations=(
            {} if annotations is None else annotations.model_dump(mode="json", by_alias=True, exclude_none=True)
        ),
        problem=problem,
    )


def guard_streams(streams: Any) -> tuple[Any, Any]:
    """Wrap the transport streams so one tool's non-object input schema can't sink a listing.

    The SDK validates ``tools/list`` replies per protocol version and rejects the whole
    reply when any tool's ``inputSchema`` root isn't ``{"type": "object"}``. The reply is
    patched on the way in: such a tool gets a placeholder object schema carrying the
    original, and ``seen_tool`` restores it and records the problem — the tool is left out,
    the server's other tools still work.
    """
    read, write = streams
    pending: set[Any] = set()
    return _GuardedRead(read, pending), _GuardedWrite(write, pending)


class _Delegate:
    def __init__(self, inner: Any, pending: set[Any]) -> None:
        self._inner = inner
        self._pending = pending

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def __aenter__(self) -> Any:
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> Any:
        return await self._inner.__aexit__(*exc)


class _GuardedWrite(_Delegate):
    async def send(self, item: Any) -> None:
        message = getattr(item, "message", None)
        if getattr(message, "method", None) == "tools/list" and hasattr(message, "id"):
            self._pending.add(message.id)
        await self._inner.send(item)


class _GuardedRead(_Delegate):
    async def receive(self) -> Any:
        return self._patch(await self._inner.receive())

    def __aiter__(self) -> _GuardedRead:
        return self

    async def __anext__(self) -> Any:
        return self._patch(await self._inner.__anext__())

    def _patch(self, item: Any) -> Any:
        message = getattr(item, "message", None)
        msg_id = getattr(message, "id", None)
        if msg_id is None or msg_id not in self._pending:
            return item
        self._pending.discard(msg_id)
        result = getattr(message, "result", None)
        tools = result.get("tools") if isinstance(result, dict) else None
        if isinstance(tools, list):
            for tool in tools:
                if isinstance(tool, dict) and not _object_root(tool.get("inputSchema")):
                    tool["inputSchema"] = {"type": "object", "properties": {}, _ROOT_MARK: tool.get("inputSchema")}
        return item


def _object_root(schema: Any) -> bool:
    return isinstance(schema, dict) and schema.get("type") == "object"


# ---- failures ----------------------------------------------------------------


def leaf(exc: BaseException) -> BaseException:
    """The first real error inside (possibly nested) exception groups."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        real = [e for e in exc.exceptions if isinstance(e, Exception) and "Cancel" not in type(e).__name__]
        exc = real[0] if real else exc.exceptions[0]
    return exc


def scrub(text: str, secrets: Mapping[str, str]) -> str:
    """Hide secret values (headers, env): the whole value always, and its space-separated
    parts of 4+ chars."""
    hidden: set[str] = set()
    for value in secrets.values():
        if value:
            hidden.add(value)
        hidden.update(part for part in value.split() if len(part) >= 4)
    for secret in sorted(hidden, key=len, reverse=True):
        text = text.replace(secret, "***")
    return text


def translate(exc: BaseException, secrets: Mapping[str, str], *, during_call: bool, http_note: str = "") -> Exception:
    """A failure as ``McpUnavailable`` (couldn't reach / talk to the server) or ``McpToolError``
    (the server answered but the call failed). Secret values never appear in the reason.

    ``http_note`` (e.g. `` (HTTP 500)``) is appended to a server error reply's reason.
    """
    from mcp import InputRequiredRoundsExceededError
    from mcp.shared.exceptions import MCPError
    from mcp_types import CONNECTION_CLOSED, REQUEST_TIMEOUT
    from pydantic import ValidationError

    found = leaf(exc)
    if isinstance(found, (McpUnavailable, McpToolError)):
        return found
    if isinstance(found, TimeoutError):
        return McpUnavailable("no answer in time")
    if isinstance(found, InputRequiredRoundsExceededError):
        return McpToolError("the server asked for input during the call, which Zygos doesn't support")
    if isinstance(found, MCPError):
        message = scrub(found.message, secrets)
        if during_call and found.code not in (CONNECTION_CLOSED, REQUEST_TIMEOUT):
            return McpToolError(f"the server refused the call: {message}")
        return McpUnavailable(f"the server answered with an error: {message}{http_note}")
    if isinstance(found, ValidationError):
        reason = "the server's reply didn't follow the MCP protocol"
        return McpToolError(reason) if during_call else McpUnavailable(reason)
    if isinstance(found, OSError):
        return McpUnavailable(f"connection failed: {scrub(str(found) or type(found).__name__, secrets)}")
    detail = scrub(str(found), secrets)
    return McpUnavailable(f"{type(found).__name__}: {detail}" if detail else type(found).__name__)
