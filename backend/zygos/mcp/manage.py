"""Operations on the MCP record shared by the CLI, the web page and the chat permission prompt.

Adding servers is planned first (``plan_add`` reads and checks, writes nothing), then saved
one server at a time (``save_server``), then listed once (``list_after_add``). Nothing here
prints, and no reason or note it returns contains a secret value (RFC-0015).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from zygos.mcp.config import (
    McpConfigError, check_server_names, describe, parse_servers, validation_reason, zygos_tool_name,
)
from zygos.mcp.offered import checked
from zygos.mcp.permission import seen_fingerprint
from zygos.mcp.results import McpToolError, McpUnavailable
from zygos.mcp.store import ServerState, SqliteMcpStore, TrustEntry
from zygos.mcp.types import ParsedServer, SeenTool, ServerSpec
from zygos.secrets import SecretStoreError

__all__ = [
    "ADD_LIST_CAP_S", "MAX_PASTE_BYTES", "AddPlan", "ManageError", "PlannedServer", "delete_secrets",
    "handles", "list_after_add", "plan_add", "save_server", "trust_all", "trust_entry", "trust_one",
]

MAX_PASTE_BYTES = 64 * 1024
ADD_LIST_CAP_S = 20.0  # the listing right after an add waits at most this long
_DEFAULT_TTL_S = 300.0


class ManageError(Exception):
    """A refused operation; ``reason`` is user-facing and never contains a value."""

    def __init__(
        self,
        kind: Literal["not_found", "invalid", "conflict", "unavailable", "too_large"],
        reason: str,
        notes: Sequence[str] = (),
    ) -> None:
        super().__init__(reason)
        self.kind = kind
        self.reason = reason
        self.notes = list(notes)  # lines to show after the reason (e.g. a rollback outcome)


class PlannedServer(BaseModel):
    """What an add would do to one server, without any secret value."""

    name: str
    transport: Literal["stdio", "http", "sse"]
    runs: str
    secret_names: list[str]
    unused: list[str]
    replaces: bool
    old_runs: str | None


class AddPlan:
    """The parsed servers and their previews. Holds secret values, so never serialise it."""

    def __init__(self, servers: list[PlannedServer], problems: list[str], items: list[ParsedServer]) -> None:
        self.servers = servers
        self.problems = problems  # non-empty: nothing can be saved
        self.items = items

    def __repr__(self) -> str:
        return f"AddPlan(servers={self.servers!r}, problems={self.problems!r})"


def plan_add(store: SqliteMcpStore, text: str) -> AddPlan:
    """Parse pasted ``mcpServers`` JSON and describe what saving it would do; writes nothing."""
    if len(text.encode("utf-8")) > MAX_PASTE_BYTES:
        raise ManageError("too_large", f"the pasted text is over {MAX_PASTE_BYTES // 1024} KiB")
    try:
        parsed = parse_servers(text)
    except McpConfigError as exc:
        raise ManageError("invalid", str(exc)) from None
    except ValidationError as exc:  # parse_servers turns these into McpConfigError; belt and braces
        raise ManageError("invalid", f"invalid server settings: {validation_reason(exc)}") from None
    existing = store.servers()
    problems = check_server_names([p.spec.name for p in parsed], list(existing))
    planned = []
    for item in parsed:
        spec, old = item.spec, existing.get(item.spec.name)
        planned.append(PlannedServer(
            name=spec.name, transport=spec.transport, runs=describe(spec),
            secret_names=[*spec.env_names, *spec.header_names], unused=sorted(spec.extra),
            replaces=old is not None, old_runs=describe(old) if old is not None else None,
        ))
    return AddPlan(planned, problems, parsed)


def _secret_name(handle: str) -> str:
    return handle.rsplit(":", 1)[-1]


def handles(spec: ServerSpec) -> set[str]:
    return {f"mcp:{spec.name}:env:{n}" for n in spec.env_names} | {
        f"mcp:{spec.name}:header:{n}" for n in spec.header_names
    }


def save_server(
    store: SqliteMcpStore, secrets: Any, item: ParsedServer, old: ServerSpec | None
) -> list[str]:
    """Store the server's secrets, then the server; ``old`` is the spec it replaces, if any.

    Returns note lines (secrets that couldn't be deleted). Raises ``ManageError("unavailable")``
    when the secrets can't be stored: the previous secrets are put back and nothing is saved;
    the error's ``notes`` say how the put-back went.
    """
    spec = item.spec
    if item.secrets:
        _save_secrets(secrets, item)
    if old is not None:
        store.replace_server(spec)  # one transaction; clears its state, trust and on/off
        return delete_secrets(secrets, spec.name, sorted(handles(old) - set(item.secrets)))
    store.put_server(spec)
    return []


def _save_secrets(secrets: Any, item: ParsedServer) -> None:
    name = item.spec.name
    status = secrets.status()
    if not status.available:
        raise ManageError("unavailable", f"its secrets can't be stored: {status.why_unavailable}")
    written: list[str] = []
    previous: dict[str, str | None] = {}
    try:
        previous = {handle: secrets.get(handle) for handle in item.secrets}
        for handle, value in item.secrets.items():
            secrets.set(handle, value)
            written.append(handle)
    except SecretStoreError as exc:
        raise ManageError(
            "unavailable", f"its secrets can't be stored: {exc}", _undo_secrets(secrets, name, previous, written)
        ) from None


def _undo_secrets(
    secrets: Any, server: str, previous: dict[str, str | None], written: list[str]
) -> list[str]:
    notes: list[str] = []
    stuck: list[str] = []
    for handle in written:
        try:
            if previous[handle] is None:
                secrets.delete(handle)
            else:
                secrets.set(handle, previous[handle])
        except SecretStoreError:
            stuck.append(handle)
    for handle in stuck:
        what = "overwritten" if previous[handle] is not None else "saved"
        undo = "restored" if previous[handle] is not None else "removed"
        notes.append(f"{server}: the secret {_secret_name(handle)} was {what} and couldn't be {undo}")
    if written and not stuck:
        notes.append(f"{server}: the secrets saved before the failure were restored")
    return notes


def delete_secrets(secrets: Any, server: str, handles: list[str]) -> list[str]:
    """Delete the handles; returns a note for each one that couldn't be deleted."""
    notes: list[str] = []
    for handle in handles:
        try:
            secrets.delete(handle)
        except SecretStoreError as exc:
            notes.append(f"{server}: could not delete the secret {_secret_name(handle)}: {exc}")
    return notes


async def list_after_add(
    store: SqliteMcpStore,
    spec: ServerSpec,
    item: ParsedServer,
    *,
    list_remote: Callable[..., Any],
    mcp_installed: Callable[[], bool],
    clock: Callable[[], float],
    cap_s: float = ADD_LIST_CAP_S,
) -> str:
    """List a just-added remote server once and record the result; returns the outcome text.

    A failed listing never undoes the add: it is recorded as unreachable and reported.
    """
    from zygos.mcp.supervisor import NO_MCP  # the supervisor imports this module

    if not mcp_installed():
        return f"{spec.name}: added, but its tools couldn't be listed: {NO_MCP}"
    prefix = f"mcp:{spec.name}:header:"
    headers = {h[len(prefix):]: v for h, v in item.secrets.items() if h.startswith(prefix)}
    limit = min(spec.timeout_s, cap_s)
    try:
        result = await asyncio.wait_for(list_remote(spec, headers, era=None, discover=None), limit)
    except Exception as exc:  # noqa: BLE001 - a failed listing never undoes the add
        # McpUnavailable/McpToolError reasons are scrubbed of header values; others: type only.
        if isinstance(exc, TimeoutError):
            reason = f"no answer within {limit:g} s"
        elif isinstance(exc, (McpUnavailable, McpToolError)):
            reason = str(exc)
        else:
            reason = type(exc).__name__
        store.put_state(
            spec.name, ServerState(status="unreachable", detail=reason, status_at=clock())
        )
        return f"{spec.name}: added, but its tools couldn't be listed: {reason} — zygos serve tries again"
    now = clock()
    ttl = result.ttl_s or _DEFAULT_TTL_S
    tools = checked(result.tools)
    store.put_state(spec.name, ServerState(
        era=result.era, discover=result.discover, tools=tools,
        listed_at=now, expires_at=now + ttl, status="reachable", status_at=now,
    ))
    count = len(tools)
    lines = [f"{spec.name}: added — {count} tool{'s' if count != 1 else ''} listed (protocol {result.era})"]
    if tools:
        lines.append(
            f"  trust the ones you want: zygos mcp trust {spec.name}/TOOL "
            f"(or {spec.name} for all {count}) — see zygos mcp list"
        )
    return "\n".join(lines)


def trust_entry(server: str, seen: SeenTool, via: Literal["tool", "server"]) -> TrustEntry:
    """Pinned the way the supervisor's gate checks it: the server's own tool name."""
    return TrustEntry(
        server=server, tool=zygos_tool_name(server, seen.name), fingerprint=seen_fingerprint(seen),
        description=seen.description, input_schema=seen.input_schema, via=via,
    )


def trust_one(store: SqliteMcpStore, server: str, seen: SeenTool) -> TrustEntry:
    entry = trust_entry(server, seen, "tool")
    store.trust_tool(entry)
    return entry


def trust_all(store: SqliteMcpStore, server: str, tools: Sequence[SeenTool]) -> list[TrustEntry]:
    entries = [trust_entry(server, seen, "server") for seen in tools]
    store.trust_server(server, entries)
    return entries
