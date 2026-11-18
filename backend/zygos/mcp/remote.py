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

from zygos.mcp.results import McpToolError, McpUnavailable, map_result
from zygos.mcp.types import ServerSpec
from zygos.mcp.wire import (
    ListResult,
    dump_discover,
    guard_streams,
    is_modern,
    leaf,
    list_pages,
    scrub,
    translate,
    ttl_seconds,
)

__all__ = ["ListResult", "McpToolError", "McpUnavailable", "call_remote", "list_remote"]

_T = TypeVar("_T")


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
                yield guard_streams(streams)
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
            yield guard_streams(streams)


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
    if is_modern(era):
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


# ---- failures ----------------------------------------------------------------


def _mismatch(exc: BaseException, status: _HttpStatus, *, phase: str) -> bool:
    """Did a pinned-era attempt fail because the server speaks another era?"""
    from mcp.shared.exceptions import MCPError
    from mcp_types import INVALID_REQUEST, METHOD_NOT_FOUND, UNSUPPORTED_PROTOCOL_VERSION
    from pydantic import ValidationError

    if status.refused is not None:
        return False
    found = leaf(exc)
    if isinstance(found, MCPError):
        return found.code in (METHOD_NOT_FOUND, INVALID_REQUEST, UNSUPPORTED_PROTOCOL_VERSION)
    # A call's reply that fails validation may come from a tool that already ran: no retry.
    return isinstance(found, ValidationError) and phase == "list"


def _translate(exc: Exception, status: _HttpStatus, headers: dict[str, str], *, during_call: bool) -> Exception:
    """HTTP-aware reasons first (refused, HTTP errors), then the shared ``translate``."""
    import httpx2

    found = leaf(exc)
    if isinstance(found, (McpUnavailable, McpToolError)):
        return found
    if (code := status.refused) is not None:
        return McpUnavailable(f"the server refused the request (HTTP {code}) — check its headers")
    if isinstance(found, httpx2.HTTPStatusError):
        return McpUnavailable(f"the server answered HTTP {found.response.status_code}")
    if isinstance(found, httpx2.ConnectError):
        return McpUnavailable(f"could not connect: {scrub(str(found) or 'connection failed', headers)}")
    if isinstance(found, httpx2.TimeoutException):
        return McpUnavailable("timed out talking to the server")
    if isinstance(found, httpx2.TransportError):
        return McpUnavailable(f"connection failed: {scrub(str(found) or type(found).__name__, headers)}")
    http_note = f" (HTTP {status.codes[-1]})" if status.codes else ""
    return translate(exc, headers, during_call=during_call, http_note=http_note)
