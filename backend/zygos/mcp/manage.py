"""Operations on the MCP record shared by the CLI, the web page and the chat permission prompt.

Adding servers is planned first (``plan_add`` reads and checks, writes nothing), then saved
one server at a time (``save_server``), then listed once (``list_after_add``). ``list_view``
is what ``zygos mcp list`` and the Tools page show; the other functions remove, switch,
trust, set a secret or a timeout. A refusal is a ``ManageError`` whose ``reason`` the
caller shows as is. Nothing here prints, and no view, reason or note it returns contains
a secret value: secrets show as ``set``, ``not set`` or ``unknown`` (RFC-0015).
"""

from __future__ import annotations

import asyncio
import importlib.util
from collections.abc import Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from zygos.mcp.config import (
    McpConfigError, check_server_names, check_timeout, describe, parse_servers, status_word,
    validation_reason, zygos_tool_name,
)
from zygos.mcp.offered import checked, noted
from zygos.mcp.permission import claims, seen_fingerprint, trust_state
from zygos.mcp.results import McpToolError, McpUnavailable
from zygos.mcp.store import ServerState, SqliteMcpStore, TrustEntry
from zygos.mcp.types import ParsedServer, SeenTool, ServerSpec
from zygos.secrets import SecretStoreError

__all__ = [
    "ADD_LIST_CAP_S", "LOCAL_HINT", "MAX_PASTE_BYTES", "TOOL_WARN_OVER", "AddPlan", "ManageError", "McpView",
    "PlannedServer", "ServerView", "ToolView", "delete_secrets", "find_server", "find_tool", "handles",
    "list_after_add", "list_view", "mcp_installed", "plan_add", "presence", "remove_server", "resolve_target", "save_server",
    "set_secret", "set_timeout", "switch_server", "switch_tool", "tools_on", "trust_all", "trust_entry",
    "trust_one", "trust_server", "trust_tool", "untrust_server", "untrust_tool",
]

MAX_PASTE_BYTES = 64 * 1024
ADD_LIST_CAP_S = 20.0  # the listing right after an add waits at most this long
TOOL_WARN_OVER = 20  # more tools on than this: show TOOL_COUNT_WARNING
LOCAL_HINT = " — its tools are listed when zygos serve starts it"
_DEFAULT_TTL_S = 300.0


def mcp_installed() -> bool:
    """Whether the MCP SDK (the ``.[mcp]`` extra) is installed; never imports it."""
    try:
        return importlib.util.find_spec("mcp") is not None
    except (ImportError, ValueError):
        return False


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


# ---- the list view ------------------------------------------------------------------

SecretPresence = Literal["set", "not set", "unknown"]


class ToolView(BaseModel):
    """One tool a server showed when last listed."""

    zname: str  # the name the model sees (server__tool)
    server_tool: str  # the server's own name for it
    description: str
    on: bool  # False for a tool switched off or left out (``problem``)
    trust: Literal["trusted", "asks", "changed"]
    was: str | None = None  # the trusted description, when ``trust == "changed"``
    now: str | None = None  # the description now, when ``trust == "changed"``
    schema_changed: bool = False  # the input schema differs from the trusted one
    claims: list[str]  # what the server says about the tool, never verified
    problem: str | None = None  # why it is left out


class ServerView(BaseModel):
    """One server: what it runs or reaches, its last recorded status, secrets and tools."""

    name: str
    transport: Literal["stdio", "http", "sse"]
    local: bool
    runs: str
    on: bool
    status: str  # the recorded status (``ServerState.status``), kept while the server is off
    status_word: str  # ``status`` in words, or "off"
    detail: str | None
    status_at: float | None
    era: str | None
    exit_code: int | None
    stderr_tail: str | None
    timeout_s: float
    trusted_server: bool
    env_names: list[str]
    header_names: list[str]
    secrets: dict[str, SecretPresence]  # by env/header name; never a value
    secret_reasons: dict[str, str]  # why a secret reads "unknown" (the secret store's reason)
    secrets_note: str | None  # the first such reason
    tools: list[ToolView]
    tools_on: int


class McpView(BaseModel):
    installed: bool  # the MCP SDK (the ``.[mcp]`` extra) is installed
    servers: list[ServerView]
    tools_on: int
    warn: bool
    warning: str | None


def presence(secrets: Any, handle: str) -> tuple[SecretPresence, str | None]:
    """Whether a secret is stored, without reading its value out; a reason comes with "unknown"."""
    try:
        found = secrets.presence(handle)
    except SecretStoreError as exc:
        return "unknown", str(exc)
    if found.state == "set":
        return "set", None
    if found.state == "not_set":
        return "not set", None
    return "unknown", found.reason or "the secret store gave no reason"


def _tools_by(
    servers: dict[str, ServerSpec], states: dict[str, ServerState], off: set[str]
) -> dict[str, list[SeenTool]]:
    """Each server's tools with schema problems and name clashes (among servers on) noted."""
    on = {name for name in servers if f"server:{name}" not in off}
    return noted({name: checked(state.tools) for name, state in states.items()}, on)


def _tool_on(server: str, seen: SeenTool, off: set[str]) -> bool:
    return seen.problem is None and f"tool:{zygos_tool_name(server, seen.name)}" not in off


def _count_on(servers: dict[str, ServerSpec], off: set[str], tools_by: dict[str, list[SeenTool]]) -> int:
    return sum(
        1
        for name in servers
        if f"server:{name}" not in off
        for seen in tools_by.get(name, [])
        if _tool_on(name, seen, off)
    )


def tools_on(store: SqliteMcpStore) -> int:
    """How many tools a turn would be offered, as far as the record knows."""
    servers = store.servers()
    off = store.off()
    return _count_on(servers, off, _tools_by(servers, {n: store.state(n) for n in servers}, off))


def _tool_view(server: str, seen: SeenTool, off: set[str], trust: dict[str, TrustEntry]) -> ToolView:
    zname = zygos_tool_name(server, seen.name)
    entry = trust.get(zname)
    state = "not_trusted" if entry is None or entry.server != server else trust_state(zname, seen, trust)
    changed: dict[str, Any] = {}
    if state == "changed" and entry is not None:
        changed = {
            "was": entry.description, "now": seen.description,
            "schema_changed": entry.input_schema != seen.input_schema,
        }
    return ToolView(
        zname=zname, server_tool=seen.name, description=seen.description, on=_tool_on(server, seen, off),
        trust="asks" if state == "not_trusted" else state, claims=claims(seen.annotations), problem=seen.problem,
        **changed,
    )


def list_view(store: SqliteMcpStore, secrets: Any, *, mcp_installed: Callable[[], bool]) -> McpView:
    """Every server with its status, secret presence, tools and trust, sorted by name.

    Reads the record and asks the secret store whether each secret is set (which may block
    on a locked keychain: async callers run this in a thread)."""
    from zygos.mcp.supervisor import TOOL_COUNT_WARNING  # the supervisor imports this module

    servers = store.servers()
    off = store.off()
    trust = store.trust_entries()
    trusted_servers = store.trusted_servers() if servers else set()
    states = {name: store.state(name) for name in servers}
    tools_by = _tools_by(servers, states, off)
    views = []
    for name in sorted(servers):
        spec, state = servers[name], states[name]
        server_on = f"server:{name}" not in off
        found: dict[str, SecretPresence] = {}
        reasons: dict[str, str] = {}
        for kind, names in (("env", spec.env_names), ("header", spec.header_names)):
            for item in names:
                found[item], reason = presence(secrets, f"mcp:{name}:{kind}:{item}")
                if reason is not None:
                    reasons[item] = reason
        tools = [_tool_view(name, seen, off, trust) for seen in tools_by[name]]
        views.append(ServerView(
            name=name, transport=spec.transport, local=spec.transport == "stdio", runs=describe(spec),
            on=server_on, status=state.status,
            status_word=status_word(spec.transport, state.status) if server_on else "off",
            detail=state.detail, status_at=state.status_at, era=state.era, exit_code=state.exit_code,
            stderr_tail=state.stderr_tail, timeout_s=spec.timeout_s, trusted_server=name in trusted_servers,
            env_names=list(spec.env_names), header_names=list(spec.header_names),
            secrets=found, secret_reasons=reasons, secrets_note=next(iter(reasons.values()), None),
            tools=tools, tools_on=sum(1 for t in tools if t.on) if server_on else 0,
        ))
    count = _count_on(servers, off, tools_by)
    warn = count > TOOL_WARN_OVER
    return McpView(
        installed=mcp_installed(), servers=views, tools_on=count, warn=warn,
        warning=TOOL_COUNT_WARNING if warn else None,
    )


# ---- finding servers and tools ---------------------------------------------------------


def find_server(store: SqliteMcpStore, name: str) -> ServerSpec:
    spec = store.servers().get(name)
    if spec is None:
        raise ManageError("not_found", f"no server {name}")
    return spec


def find_tool(store: SqliteMcpStore, zname: str) -> tuple[ServerSpec, SeenTool]:
    """The server and seen tool behind a zygos tool name (``server__tool``).

    Two servers' tools can map to one name (a clash, never offered); the first server by
    name wins."""
    servers = store.servers()
    for name in sorted(servers):
        for seen in store.state(name).tools:
            if zygos_tool_name(name, seen.name) == zname:
                return servers[name], seen
    raise ManageError("not_found", f"no tool {zname}")


def resolve_target(store: SqliteMcpStore, target: str) -> tuple[ServerSpec, str | None]:
    """``SERVER`` or ``SERVER/TOOL``. Server names may contain "/": the longest matching
    server name wins."""
    servers = store.servers()
    if target in servers:
        return servers[target], None
    for i in range(len(target) - 1, 0, -1):
        if target[i] == "/" and target[:i] in servers:
            return servers[target[:i]], target[i + 1:]
    raise ManageError("not_found", f"no server {target.split('/', 1)[0]}")


def _seen(store: SqliteMcpStore, spec: ServerSpec, tool: str | None) -> list[SeenTool]:
    """The tools seen now: the one named, or all of them for ``tool=None``."""
    tools = store.state(spec.name).tools
    if tool is not None:
        tools = [t for t in tools if t.name == tool]
    if tools:
        return tools
    hint = LOCAL_HINT if spec.transport == "stdio" else ""
    what = f"no tool {tool}" if tool is not None else "no tools"
    raise ManageError("not_found", f"{what} seen on {spec.name} yet{hint}")


# ---- remove, switch, trust -------------------------------------------------------------


def remove_server(store: SqliteMcpStore, secrets: Any, name: str) -> list[str]:
    """Remove the server, its state, trust and on/off, then its secrets; returns a note
    for each secret that couldn't be deleted."""
    spec = find_server(store, name)
    store.remove_server(name)
    return delete_secrets(secrets, name, sorted(handles(spec)))


def switch_server(store: SqliteMcpStore, name: str, on: bool, *, clock: Callable[[], float]) -> None:
    find_server(store, name)
    # also clears the "switched off" stop zygos serve recorded, atomically
    store.set_server_on(name, on, now=clock())


def switch_tool(store: SqliteMcpStore, server: str, tool: str, on: bool) -> None:
    """Switch one tool. Switching off needs the tool to have been seen; a tool that is
    off can always be switched back on (it may have gone from the server since)."""
    spec = find_server(store, server)
    zname = zygos_tool_name(spec.name, tool)
    if not (on and f"tool:{zname}" in store.off()):
        _seen(store, spec, tool)
    store.set_off("tool", zname, not on, server=spec.name)


def trust_tool(store: SqliteMcpStore, server: str, tool: str) -> TrustEntry:
    spec = find_server(store, server)
    return trust_one(store, spec.name, _seen(store, spec, tool)[0])


def trust_server(store: SqliteMcpStore, name: str) -> list[TrustEntry]:
    """Trust every tool the server shows now; tools it adds later need trusting on their own."""
    spec = find_server(store, name)
    return trust_all(store, spec.name, _seen(store, spec, None))


def untrust_tool(store: SqliteMcpStore, server: str, tool: str) -> bool:
    """Withdraw trust from one tool; False when it wasn't trusted."""
    spec = find_server(store, server)
    zname = zygos_tool_name(spec.name, tool)
    entry = store.trust_entries().get(zname)
    if entry is None or entry.server != spec.name:
        return False
    store.untrust_tool(zname)
    return True


def untrust_server(store: SqliteMcpStore, name: str) -> list[str]:
    """Withdraw the server-wide trust; returns the tools still trusted one by one."""
    spec = find_server(store, name)
    store.untrust_server(spec.name)
    return sorted(
        e.tool for e in store.trust_entries().values() if e.server == spec.name and e.via == "tool"
    )


# ---- secrets, timeout ------------------------------------------------------------------


def set_secret(store: SqliteMcpStore, secrets: Any, server: str, secret: str, value: str) -> None:
    """Store a new value for one of the server's env or header names.

    A local server reads its env only when it starts, so the caller restarts it."""
    spec = find_server(store, server)
    targets = [
        f"mcp:{spec.name}:{kind}:{secret}"
        for kind, names in (("env", spec.env_names), ("header", spec.header_names))
        if secret in names
    ]
    if not targets:
        raise ManageError("not_found", f"no secret {secret} on {spec.name}")
    try:
        for handle in targets:
            secrets.set(handle, value)
    except SecretStoreError as exc:  # its text never carries the value
        raise ManageError("unavailable", f"the secret {secret} can't be stored: {exc}") from None


def set_timeout(store: SqliteMcpStore, name: str, timeout_s: object) -> ServerSpec:
    """Set the server's per-call timeout; trust, on/off and its last listing are kept."""
    spec = find_server(store, name)
    try:
        value = check_timeout(spec.name, timeout_s)
    except McpConfigError as exc:
        raise ManageError("invalid", str(exc)) from None
    updated = spec.model_copy(update={"timeout_s": value})
    store.put_server(updated)
    return updated
