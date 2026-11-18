"""Remote MCP servers (Streamable HTTP, SSE): one short connection per list or call.

Every ``list_remote`` / ``call_remote`` opens a connection, does its one job and closes,
all bounded by the server's ``timeout_s``; a restarted server never leaves a stale
session behind. The protocol era learned on first contact is handed back so the caller
can store it: a known modern era (with its discover result) is adopted directly next time
(``mode=<era>``); anything else probes with ``mode="auto"`` (discover, falling back to the
initialize handshake).

Nothing is declared to servers: no roots, sampling, elicitation or logging callbacks.
Header values travel only in the HTTP client; every reason raised is scrubbed of them.

The MCP SDK is imported inside the functions, so importing this module never imports it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, TypeVar

from zygos.agent.schema import check_input_schema
from zygos.mcp.results import McpToolError, McpUnavailable, map_result
from zygos.mcp.types import SeenTool, ServerSpec

__all__ = ["ListResult", "McpToolError", "McpUnavailable", "call_remote", "list_remote"]

_T = TypeVar("_T")
_PAGE_CAP = 100
_ROOT_MARK = "x-zygos-original-input-schema"
_NOT_OBJECT = "input schema root must be an object schema"


@dataclass(frozen=True)
class ListResult:
    era: str
    discover: dict[str, Any] | None
    tools: list[SeenTool]
    ttl_s: float | None


async def list_remote(
    spec: ServerSpec,
    headers: dict[str, str],
    *,
    era: str | None,
    discover: dict[str, Any] | None,
) -> ListResult:
    """List a remote server's tools over one short connection; each tool's schema is checked."""
    (tools, ttl_ms), negotiated, found = await _with_client(spec, headers, era, discover, list_pages, phase="list")
    return ListResult(era=negotiated, discover=found, tools=tools, ttl_s=ttl_seconds(negotiated, ttl_ms))


async def list_pages(client: Any) -> tuple[list[SeenTool], int]:
    """Every page of a connected client's ``tools/list`` (each schema checked) and the
    first page's ``ttlMs``. Shared with local servers; the client's streams must be
    wrapped with ``_guard`` so one bad schema can't sink the listing."""
    tools: list[SeenTool] = []
    ttl_ms = 0
    cursor: str | None = None
    for page_no in range(_PAGE_CAP):
        page = await client.list_tools(cursor=cursor, cache_mode="bypass")
        if page_no == 0:
            ttl_ms = getattr(page, "ttl_ms", 0) or 0
        tools.extend(_seen(tool) for tool in page.tools)
        cursor = page.next_cursor
        if cursor is None:
            break
    return tools, ttl_ms


def ttl_seconds(era: str, ttl_ms: int) -> float | None:
    """A modern server's caching hint in seconds; ``None`` when it gave none (or is handshake-era)."""
    return ttl_ms / 1000 if _is_modern(era) and ttl_ms > 0 else None


def dump_discover(client: Any) -> dict[str, Any] | None:
    """A connected client's discover result as stored JSON (``None`` for handshake-era servers)."""
    found = client.session.discover_result
    return None if found is None else found.model_dump(mode="json", by_alias=True, exclude_none=True)


async def call_remote(
    spec: ServerSpec,
    headers: dict[str, str],
    tool: str,
    args: dict[str, Any],
    *,
    era: str | None,
    discover: dict[str, Any] | None,
    on_era: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> Any:
    """Call one tool over one short connection; returns ``map_result`` of the reply.

    A known handshake era connects with ``mode="legacy"`` (no discover probe per call).
    If the server's era turned out different from ``era`` (e.g. a pinned modern era fell
    back after a downgrade), ``on_era(new_era, new_discover)`` is called before the result
    is mapped, so the caller can store it.
    """

    async def work(client: Any) -> Any:
        return await client.call_tool(tool, args)

    result, negotiated, found = await _with_client(spec, headers, era, discover, work, phase="call")
    if on_era is not None and negotiated != era:
        on_era(negotiated, found)
    return map_result(result)


# ---- connection --------------------------------------------------------------


@dataclass
class _HttpStatus:
    """Error statuses the HTTP client saw, so a failure can say "HTTP 401" (never headers)."""

    codes: list[int] = field(default_factory=list)

    async def hook(self, response: Any) -> None:
        if response.status_code >= 400:
            self.codes.append(response.status_code)

    @property
    def refused(self) -> int | None:
        return next((c for c in self.codes if c in (401, 403, 407)), None)


def _is_modern(version: str | None) -> bool:
    from mcp_types.version import MODERN_PROTOCOL_VERSIONS

    return version in MODERN_PROTOCOL_VERSIONS


def _http_client(headers: dict[str, str], status: _HttpStatus, timeout_s: float) -> Any:
    import httpx2
    from mcp.shared._httpx_utils import create_mcp_http_client

    connect = min(timeout_s, 30.0)
    timeout = httpx2.Timeout(connect, read=max(timeout_s, connect))
    client = create_mcp_http_client(headers=dict(headers), timeout=timeout)
    client.event_hooks = {"request": [], "response": [status.hook]}
    return client


@asynccontextmanager
async def _transport(spec: ServerSpec, headers: dict[str, str], status: _HttpStatus) -> AsyncIterator[Any]:
    if spec.transport == "http":
        from mcp.client.streamable_http import streamable_http_client

        async with _http_client(headers, status, spec.timeout_s) as http:
            async with streamable_http_client(spec.url or "", http_client=http) as streams:
                yield _guard(streams)
    else:  # sse
        from mcp.client.sse import sse_client

        def factory(headers: Any = None, timeout: Any = None, auth: Any = None) -> Any:
            return _http_client(headers or {}, status, spec.timeout_s)

        async with sse_client(
            spec.url or "",
            headers=dict(headers),
            timeout=min(spec.timeout_s, 30.0),
            sse_read_timeout=spec.timeout_s,
            httpx_client_factory=factory,
        ) as streams:
            yield _guard(streams)


async def _with_client(
    spec: ServerSpec,
    headers: dict[str, str],
    era: str | None,
    discover: dict[str, Any] | None,
    work: Callable[[Any], Awaitable[_T]],
    *,
    phase: str,
) -> tuple[_T, str, dict[str, Any] | None]:
    """Run ``work`` on a connected client; returns (its value, negotiated era, discover dict).

    A pinned era (modern, or legacy for a known handshake-era call) that fails with a
    protocol mismatch is retried once in ``mode="auto"`` within the same time budget, so a
    server that changed era never shows up as a refused tool.
    """
    if spec.transport not in ("http", "sse") or not spec.url:
        raise McpUnavailable(f"{spec.name} is not a remote server (no url)")
    import anyio
    from mcp import Client
    from mcp_types import DiscoverResult
    from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS
    from pydantic import ValidationError

    mode, prior = "auto", None
    if _is_modern(era):
        try:
            prior = DiscoverResult.model_validate(discover) if discover is not None else None
            mode = era  # type: ignore[assignment]
        except ValidationError:
            mode, prior = "auto", None  # a stored discover we can't read: learn it again
    elif phase == "call" and era in HANDSHAKE_PROTOCOL_VERSIONS:
        mode = "legacy"

    status = _HttpStatus()
    connected = False

    async def attempt(mode: str, prior: Any) -> tuple[_T, str, dict[str, Any] | None]:
        nonlocal connected
        connected = False
        status.codes.clear()
        client = Client(
            _transport(spec, headers, status),
            mode=mode,
            prior_discover=prior,
            read_timeout_seconds=spec.timeout_s,
            cache=None,
        )
        async with client:
            connected = True
            value = await work(client)
            return value, client.protocol_version, dump_discover(client)

    try:
        with anyio.fail_after(spec.timeout_s):
            try:
                return await attempt(mode, prior)
            except Exception as exc:
                if mode == "auto" or not _mismatch(exc, status, phase=phase):
                    raise
                return await attempt("auto", None)
    except TimeoutError:
        raise McpUnavailable(f"no answer within {spec.timeout_s:g} s") from None
    except (McpUnavailable, McpToolError):
        raise
    except Exception as exc:  # noqa: BLE001 - every failure becomes a readable reason
        raise _translate(exc, status, headers, during_call=connected and phase == "call") from None


# ---- tool listing ------------------------------------------------------------


def _seen(tool: Any) -> SeenTool:
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


def _guard(streams: Any) -> tuple[Any, Any]:
    """Wrap the transport streams so one tool's non-object input schema can't sink a listing.

    The SDK validates ``tools/list`` replies per protocol version and rejects the whole
    reply when any tool's ``inputSchema`` root isn't ``{"type": "object"}``. The reply is
    patched on the way in: such a tool gets a placeholder object schema carrying the
    original, and ``_seen`` restores it and records the problem — the tool is left out,
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


def _leaf(exc: BaseException) -> BaseException:
    """The first real error inside (possibly nested) exception groups."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        real = [e for e in exc.exceptions if isinstance(e, Exception) and "Cancel" not in type(e).__name__]
        exc = real[0] if real else exc.exceptions[0]
    return exc


def _mismatch(exc: BaseException, status: _HttpStatus, *, phase: str) -> bool:
    """Did a pinned-era attempt fail because the server speaks another era?"""
    from mcp.shared.exceptions import MCPError
    from mcp_types import INVALID_REQUEST, METHOD_NOT_FOUND, UNSUPPORTED_PROTOCOL_VERSION
    from pydantic import ValidationError

    if status.refused is not None:
        return False
    leaf = _leaf(exc)
    if isinstance(leaf, MCPError):
        return leaf.code in (METHOD_NOT_FOUND, INVALID_REQUEST, UNSUPPORTED_PROTOCOL_VERSION)
    # A call's reply that fails validation may come from a tool that already ran: no retry.
    return isinstance(leaf, ValidationError) and phase == "list"


def _scrub(text: str, headers: dict[str, str]) -> str:
    """Hide header values: the whole value always, and its space-separated parts of 4+ chars."""
    secrets: set[str] = set()
    for value in headers.values():
        if value:
            secrets.add(value)
        secrets.update(part for part in value.split() if len(part) >= 4)
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "***")
    return text


def _translate(exc: Exception, status: _HttpStatus, headers: dict[str, str], *, during_call: bool) -> Exception:
    import httpx2
    from mcp import InputRequiredRoundsExceededError
    from mcp.shared.exceptions import MCPError
    from mcp_types import CONNECTION_CLOSED, REQUEST_TIMEOUT
    from pydantic import ValidationError

    leaf = _leaf(exc)
    if isinstance(leaf, (McpUnavailable, McpToolError)):
        return leaf
    if (code := status.refused) is not None:
        return McpUnavailable(f"the server refused the request (HTTP {code}) — check its headers")
    if isinstance(leaf, TimeoutError):
        return McpUnavailable("no answer in time")
    if isinstance(leaf, InputRequiredRoundsExceededError):
        return McpToolError("the server asked for input during the call, which Zygos doesn't support")
    if isinstance(leaf, MCPError):
        message = _scrub(leaf.message, headers)
        if during_call and leaf.code not in (CONNECTION_CLOSED, REQUEST_TIMEOUT):
            return McpToolError(f"the server refused the call: {message}")
        http = f" (HTTP {status.codes[-1]})" if status.codes else ""
        return McpUnavailable(f"the server answered with an error: {message}{http}")
    if isinstance(leaf, ValidationError):
        reason = "the server's reply didn't follow the MCP protocol"
        return McpToolError(reason) if during_call else McpUnavailable(reason)
    if isinstance(leaf, httpx2.HTTPStatusError):
        return McpUnavailable(f"the server answered HTTP {leaf.response.status_code}")
    if isinstance(leaf, httpx2.ConnectError):
        return McpUnavailable(f"could not connect: {_scrub(str(leaf) or 'connection failed', headers)}")
    if isinstance(leaf, httpx2.TimeoutException):
        return McpUnavailable("timed out talking to the server")
    if isinstance(leaf, (httpx2.TransportError, OSError)):
        return McpUnavailable(f"connection failed: {_scrub(str(leaf) or type(leaf).__name__, headers)}")
    detail = _scrub(str(leaf), headers)
    return McpUnavailable(f"{type(leaf).__name__}: {detail}" if detail else type(leaf).__name__)
