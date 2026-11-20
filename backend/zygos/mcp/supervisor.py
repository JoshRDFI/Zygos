"""The MCP supervisor: which servers run, which of their tools a turn is offered, trust.

Per turn (``before_turn``, synchronous): one cheap ``version()`` read of the store; when
the record changed (``zygos mcp`` edits, or this process's own state writes) servers,
on/off and trust are re-read, so they apply to that turn. Servers removed, switched off
or replaced are stopped; new local servers are started and stale tool lists refreshed
**in the background** — a turn never awaits a start or a listing and uses the tools last
seen. A failing server only loses its own tools.

Offered: tools of a running local server listed by this run, or of a remote server whose
last listing succeeded; per tool see ``offered`` (schema usable, on, no name clash).
Trust (``gate``) is read from the store, pinned per tool to its fingerprint and server;
config rules can only tighten (``permission.mcp_decision``).

Reads on the event loop use a strict reader with a short busy timeout: a failed or busy
read keeps the previous view (logged once) and is retried next turn — it is never taken
for "no servers".

Every lifecycle change is logged (``zygos.mcp``), written to the server's stored state
and published as ``mcp.server`` without a session. Store writes block (~0.3 s) and run
in a worker thread, one at a time, never on the event loop. No secret value (env/header
values) and nothing from ``ServerSpec.extra`` ever reaches a log, event or stored state.

Stability: Experimental.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from zygos.mcp.config import address
from zygos.mcp.manage import trust_all, trust_one
from zygos.mcp.permission import (
    McpDecision, claims, mcp_decision, rule_forces_ask, seen_fingerprint, trust_state,
)
from zygos.mcp.results import McpToolError, McpUnavailable
from zygos.mcp.offered import build_offered, checked, with_clashes
from zygos.mcp.store import McpStoreUnavailable, ServerState, SqliteMcpStore, TrustEntry
from zygos.mcp.tool import McpTool
from zygos.mcp.types import ServerSpec
from zygos.mcp.wire import ListResult
from zygos.runtime.context import ExecutionContext
from zygos.runtime.events import McpServerEvent
from zygos.secrets.types import SecretStoreError
from zygos.tools.permissions import Rule
from zygos.tools.service import ToolService
from zygos.tools.types import Tool, ToolMeta

__all__ = [
    "Connectors", "McpSupervisor", "NO_MCP", "SECRET_FAILURE", "SECRET_SLOW", "SWITCHED_OFF", "TOOL_COUNT_WARNING",
]

logger = logging.getLogger("zygos.mcp")

SECRET_FAILURE = "secret store: "  # starts the detail of a server failed for secret reasons (doctor hints on it)
SECRET_SLOW = "secret store didn't answer in time"  # not a SECRET_FAILURE: it is tried again by itself
SWITCHED_OFF = "switched off"  # the detail of a server stopped because it was switched off
NO_MCP = "MCP support isn't installed: pip install -e '.[mcp]'"
TOOL_COUNT_WARNING = "small local models choose tools less reliably beyond about 20 — consider switching some off"
_DEFAULT_TTL_S = 300.0
_RETRY_S = 30.0  # a failed listing is tried again after this
_TOOL_WARN_OVER = 20
_READ_BUSY_S = 0.2  # a turn waits at most this long for a store writer
_SECRET_READ_S = 5.0  # a secret-store read (a locked keychain may never answer) waits at most this long


class LocalLike(Protocol):
    """What the supervisor needs from a local server (``LocalServer``; fakes in tests)."""

    @property
    def status(self) -> str: ...
    @property
    def exit_code(self) -> int | None: ...
    @property
    def stderr_tail(self) -> str: ...
    @property
    def era(self) -> str | None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def list_tools(self) -> ListResult: ...
    async def call(self, tool: str, args: dict[str, Any], timeout_s: float) -> Any: ...


@dataclass(frozen=True)
class Connectors:
    """How servers are reached: ``LocalServer`` and the remote functions by default."""

    local: Callable[..., LocalLike]
    list_remote: Callable[..., Awaitable[ListResult]]
    call_remote: Callable[..., Awaitable[Any]]


def _default_connectors() -> Connectors:
    from zygos.mcp.local import LocalServer  # neither module imports the SDK at import
    from zygos.mcp.remote import call_remote, list_remote

    return Connectors(local=LocalServer, list_remote=list_remote, call_remote=call_remote)


def _mcp_installed() -> bool:
    try:
        return importlib.util.find_spec("mcp") is not None
    except (ImportError, ValueError):
        return False


@dataclass(eq=False)
class _Server:
    spec: ServerSpec
    state: ServerState
    local: LocalLike | None = None
    attempted: bool = False  # local: started once for this spec; reconcile never starts it again
    start_after: float = 0.0  # local: not (re)started before this (a slow secret store)
    current: bool = False  # local: tools listed from the process now running
    failed: bool = False  # could not be used at all (secrets, no SDK) until replaced or off/on
    next_check: float = 0.0  # when the tool list is due again
    start_task: asyncio.Task[None] | None = None
    list_task: asyncio.Task[None] | None = None
    relist: bool = False  # a new listing was asked for while one was in flight
    dirty: bool = False  # state changed since last written

    @property
    def is_local(self) -> bool:
        return self.spec.transport == "stdio"


class McpSupervisor:
    def __init__(
        self,
        store: SqliteMcpStore,
        secrets: Any,  # SecretsHandle: get(handle) -> str | None
        tool_service: ToolService,
        *,
        rules: Sequence[Rule],
        new_context: Callable[[], ExecutionContext],
        clock: Callable[[], float] = time.time,
        connectors: Connectors | None = None,
    ) -> None:
        self._store = store  # writes (in a thread)
        self._reader = store.strict_reader(busy_timeout_s=_READ_BUSY_S)  # reads on the loop
        self._read_failing = False
        self._secrets = secrets
        self._tool_service = tool_service
        self._rules = list(rules)
        self._new_context = new_context
        self._clock = clock
        self._connectors = connectors
        self._servers: dict[str, _Server] = {}
        self._off: set[str] = set()
        self._trust: dict[str, TrustEntry] = {}
        self._version: int | None = None
        self._mcp_ok: bool | None = None
        self._offered: dict[str, McpTool] = {}
        self._warned_count = False
        self._work: set[asyncio.Task[Any]] = set()  # starts and listings: cancelled on close
        self._chores: set[asyncio.Task[Any]] = set()  # writes, events, stops: finished on close
        self._write_lock = asyncio.Lock()
        self._secret_reads: dict[tuple[str, str, tuple[str, ...]], asyncio.Future[dict[str, str]]] = {}
        self._closed = False

    @property
    def store(self) -> SqliteMcpStore:
        """The record (for read-only views such as the manifest)."""
        return self._store

    @property
    def connectors(self) -> Connectors:
        if self._connectors is None:
            self._connectors = _default_connectors()
        return self._connectors

    # ---- public --------------------------------------------------------------

    async def start(self) -> None:
        """Start local servers that are on and list every remote one, all in the background."""
        if self._closed:
            return
        self._sync(force_remote=True)

    def before_turn(self) -> tuple[Tool, ...]:
        """The MCP tools for this turn. Synchronous; reads the store, never awaits a server."""
        if self._closed:
            return ()
        self._sync()
        tools: list[McpTool] = []
        if self._servers and self._mcp_ok:
            offerable = [(e.spec, e.state.tools) for e in self._servers.values() if self._offerable(e)]
            tools = build_offered(offerable, self._off, self._offered, self.call)
            if len(tools) > _TOOL_WARN_OVER and not self._warned_count:
                logger.warning("%d MCP tools on: %s", len(tools), TOOL_COUNT_WARNING)
            self._warned_count = len(tools) > _TOOL_WARN_OVER
        if tools or self._offered:
            self._offered = {t.meta.name: t for t in tools}
            self._tool_service.set_dynamic_tools(tools)
        return tuple(tools)

    def gate(self, meta: ToolMeta) -> McpDecision:
        tool = self._offered.get(meta.name)
        entry = self._trust.get(meta.name)
        trusted = (
            tool is not None
            and entry is not None
            and tool.meta.server == meta.server
            and entry.server == meta.server
            and trust_state(meta.name, tool.seen, self._trust) == "trusted"
        )
        return mcp_decision(meta.name, self._rules, trusted)

    def describe(self, meta: ToolMeta) -> dict[str, Any]:
        """What a permission prompt shows about an offered tool; ``{}`` if not offered.
        Never includes header or env values."""
        tool = self._offered.get(meta.name)
        if tool is None:
            return {}
        spec, seen = tool.spec, tool.seen
        forced = rule_forces_ask(meta.name, self._rules)
        out: dict[str, Any] = {
            "server": spec.name,
            "server_tool": seen.name,
            "where": "local" if spec.transport == "stdio" else "remote",
            "address": address(spec),
            "description": seen.description,
            "claims": claims(seen.annotations),
            "can_trust": not forced,
            # What trust from this prompt is pinned to: a hash of what the card shows.
            "fingerprint": seen_fingerprint(seen),
        }
        if forced:
            out["rule_note"] = "a config rule asks every time for this tool"
        entry = self._trust.get(meta.name)
        if (
            entry is not None
            and entry.server == spec.name
            and trust_state(meta.name, seen, self._trust) == "changed"
        ):
            out["changed"] = {
                "old_description": entry.description,
                "new_description": seen.description,
                "old_schema": entry.input_schema,
                "new_schema": seen.input_schema,
            }
        return out

    async def trust_from_prompt(self, tool: str, scope: Literal["tool", "server"], shown: str | None) -> bool:
        """Trust one offered tool, or every tool its server currently shows. Takes effect
        at once (no reload), so the same turn can go on. ``shown`` is the fingerprint the
        prompt showed; nothing is trusted unless the tool is still exactly that. False if
        nothing was recorded."""
        offered = self._offered.get(tool)
        if offered is None or not shown or seen_fingerprint(offered.seen) != shown:
            return False
        server = offered.spec.name
        if scope == "tool":
            seen = [offered.seen]
        else:
            running = self._servers.get(server)
            if running is None:
                return False
            seen = list(running.state.tools)
            current = next((t for t in seen if t.name == offered.seen.name), None)
            if current is None or seen_fingerprint(current) != shown:
                return False
        try:
            async with self._write_lock:
                if scope == "tool":
                    entries = [await asyncio.to_thread(trust_one, self._store, server, seen[0])]
                else:
                    entries = await asyncio.to_thread(trust_all, self._store, server, seen)
        except Exception as exc:  # noqa: BLE001 - the prompt falls back to "not trusted"
            logger.warning("mcp server %s: could not record trust (%s)", server, type(exc).__name__)
            return False
        self._trust.update({e.tool: e for e in entries})
        return True

    async def call(self, server: str, tool: str, args: dict[str, Any]) -> Any:
        entry = self._servers.get(server)
        if entry is None or entry.failed:
            raise McpUnavailable(f"{server} is not available")
        spec = entry.spec
        if entry.is_local:
            if entry.local is None:
                raise McpUnavailable(f"{server} is not running")
            return await entry.local.call(tool, args, spec.timeout_s)
        try:
            headers = await self._secret_values(spec, "header", spec.header_names)
        except SecretStoreError as exc:
            raise McpUnavailable(str(exc)) from None

        def on_era(era: str, discover: dict[str, Any] | None) -> None:
            if self._servers.get(server) is entry:
                self._update(entry, era=era, discover=discover)

        try:
            return await self.connectors.call_remote(
                spec, headers, tool, args, era=entry.state.era, discover=entry.state.discover, on_era=on_era
            )
        except McpUnavailable:
            self._list_again(entry, now=False)  # list it again (in the background) to see whether it's down
            raise

    def sync_now(self) -> None:
        """Apply a record change now rather than on the next turn (a new local server
        starts in the background). Synchronous, like ``before_turn``."""
        if self._closed:
            return
        self._sync()

    def restart(self, name: str) -> None:
        """Stop the server's running copy and start it again from the record, so a local
        server reads its env from the secret store afresh. Nothing happens for a server
        that isn't running here (unknown or switched off)."""
        if self._closed:
            return
        entry = self._servers.get(name)
        if entry is not None:
            self._drop(entry, switched_off=False)
            # A fresh entry from the state held here (the store may not have it yet): a local
            # server is started again, a remote one listed again (``next_check`` is 0).
            fresh = _Server(spec=entry.spec, state=entry.state)
            self._servers[name] = fresh
            if not self._mcp_ok:
                self._fail(fresh, NO_MCP)
            elif fresh.is_local:
                self._update(fresh, status="not_started", detail=None, exit_code=None, stderr_tail=None)
        self._sync()  # starts or lists it; a spec changed in the record meanwhile replaces it

    async def refresh(self, limit_s: float = 5.0) -> None:
        """List every server that is on again now and wait at most ``limit_s`` for those
        listings together. Never raises on the limit: a listing still running carries on
        in the background and lands in the record when it finishes.

        A server that is on but failed (its secrets couldn't be read, say) is restarted,
        so it is tried again rather than left failed until it is switched off and on."""
        if self._closed:
            return
        self._sync()
        for name in [name for name, entry in self._servers.items() if entry.failed]:
            self.restart(name)
        for entry in self._servers.values():
            if not entry.failed:
                self._list_again(entry, now=True)
        pending = {
            entry.list_task for entry in self._servers.values()
            if entry.list_task is not None and not entry.list_task.done()
        }
        if pending:
            await asyncio.wait(pending, timeout=limit_s)

    async def aclose(self) -> None:
        """Cancel background starts/listings, stop local servers, finish pending writes."""
        if self._closed:
            return
        self._closed = True
        work = list(self._work)
        for task in work:
            task.cancel()
        await asyncio.gather(*work, return_exceptions=True)
        locals_ = [entry.local for entry in self._servers.values() if entry.local is not None]
        stopping = [
            entry for entry in self._servers.values()
            if entry.local is not None and entry.local.status in ("starting", "running")
        ]
        await asyncio.gather(*(local.stop() for local in locals_), return_exceptions=True)
        for entry in stopping:  # stopped by this shutdown, not by a fault: zygos serve starts it again
            self._update(entry, status="not_started", detail=None, exit_code=None, stderr_tail=None)
        while self._chores:  # a finished chore may have queued another (a write after an event)
            batch = set(self._chores)
            await asyncio.gather(*batch, return_exceptions=True)
            self._chores -= batch  # done callbacks may not have run yet: never spin on them
        if self._offered:
            self._offered = {}
            self._tool_service.set_dynamic_tools([])

    # ---- reconcile -------------------------------------------------------------

    def _sync(self, *, force_remote: bool = False) -> None:
        try:
            version = self._reader.version()
            if version != self._version:
                self._reload()
                self._version = version  # only once the whole record was read
        except McpStoreUnavailable as exc:
            if not self._read_failing:
                logger.warning("%s; keeping the last view, retrying next turn", exc)
            self._read_failing = True
        else:
            self._read_failing = False
        if force_remote:
            for entry in self._servers.values():
                if not entry.is_local:
                    entry.next_check = 0.0
        if self._mcp_ok:
            self._reconcile()

    def _reload(self) -> None:
        """Re-read the record; every read happens before anything changes (a read that
        fails raises ``McpStoreUnavailable`` and leaves the previous view whole)."""
        specs = self._reader.servers()
        off = self._reader.off()
        trust = self._reader.trust_entries()
        active = {name: spec for name, spec in specs.items() if f"server:{name}" not in off}
        new_states = {
            name: self._reader.state(name)
            for name, spec in active.items()
            if name not in self._servers or self._servers[name].spec != spec
        }
        self._off, self._trust = off, trust
        for name, entry in list(self._servers.items()):
            if active.get(name) != entry.spec:
                self._drop(entry, switched_off=name in specs and name not in active)
        for name, spec in active.items():
            if name in self._servers:
                continue
            state = new_states[name]
            entry = _Server(spec=spec, state=state.model_copy(update={"tools": checked(state.tools)}))
            entry.next_check = state.expires_at or 0.0
            self._servers[name] = entry
            if state.status == "stopped" and state.detail == SWITCHED_OFF:  # it is on again
                self._update(entry, status="not_started", detail=None)
            if self._mcp_ok is None:
                self._mcp_ok = _mcp_installed()
            if not self._mcp_ok:
                self._fail(entry, NO_MCP)
        self._apply_clashes()

    def _drop(self, entry: _Server, *, switched_off: bool) -> None:
        name = entry.spec.name
        del self._servers[name]
        for task in (entry.start_task, entry.list_task):
            if task is not None:
                task.cancel()
        if entry.local is not None:
            self._spawn(entry.local.stop(), chore=True)
        if switched_off:
            entry.state = entry.state.model_copy(
                update={"status": "stopped", "detail": SWITCHED_OFF, "status_at": self._clock()}
            )
            self._save(entry, retired_ok=True)
            self._publish(name, "stopped", SWITCHED_OFF)

    def _reconcile(self) -> None:
        now = self._clock()
        for entry in self._servers.values():
            if entry.failed:
                continue
            if entry.is_local:
                if not entry.attempted:
                    if now < entry.start_after:
                        continue
                    entry.attempted = True
                    entry.start_task = self._spawn(self._start_local(entry))
                elif (
                    entry.local is not None
                    and entry.local.status == "running"
                    and (not entry.current or now >= entry.next_check)
                ):
                    self._schedule_list(entry)
            elif now >= entry.next_check:
                self._schedule_list(entry)

    def _schedule_list(self, entry: _Server) -> None:
        if entry.list_task is None or entry.list_task.done():
            entry.list_task = self._spawn(self._list(entry))
            if entry.list_task is not None:
                entry.list_task.add_done_callback(lambda _task: self._after_list(entry))

    def _list_again(self, entry: _Server, *, now: bool) -> None:
        """A fresh listing is wanted (the tools changed, or a call found the server down):
        right away with ``now``, else on the next turn — and if a listing is already in
        flight (it may have started before the change), once more after it."""
        entry.next_check = 0.0
        if entry.list_task is not None and not entry.list_task.done():
            entry.relist = True
        elif now and not self._closed and (not entry.is_local or self._running(entry)):
            self._schedule_list(entry)

    def _after_list(self, entry: _Server) -> None:
        if not entry.relist:
            return
        entry.relist = False
        if self._closed or entry.failed or self._servers.get(entry.spec.name) is not entry:
            return
        self._list_again(entry, now=True)

    @staticmethod
    def _running(entry: _Server) -> bool:
        return entry.local is not None and entry.local.status == "running"

    # ---- background work -----------------------------------------------------------

    async def _start_local(self, entry: _Server) -> None:
        spec = entry.spec
        try:
            env = await self._secret_values(spec, "env", spec.env_names)
        except SecretStoreError as exc:
            self._fail(entry, SECRET_FAILURE + str(exc))
            return
        except McpUnavailable as exc:  # the secret store didn't answer in time: start it later
            entry.attempted = False
            entry.start_after = self._clock() + _RETRY_S
            self._update(entry, status="failed", detail=str(exc))
            self._publish(spec.name, "failed", str(exc))
            return
        try:
            local = self.connectors.local(spec, env, on_event=lambda kind, detail: self._on_local(entry, kind, detail))
        except Exception as exc:  # noqa: BLE001 - a server that can't be set up fails alone
            self._fail(entry, f"could not start: {type(exc).__name__}")
            return
        entry.local = local
        entry.state = entry.state.model_copy(update={"detail": None, "exit_code": None, "stderr_tail": None})
        await local.start()

    def _on_local(self, entry: _Server, kind: str, detail: str | None) -> None:
        """``LocalServer`` events (already logged there); ``detail`` is free of secrets."""
        name = entry.spec.name
        local = entry.local
        if self._servers.get(name) is not entry or local is None:
            return  # a server already dropped (removed, off, replaced)
        if kind == "tools_changed":
            self._list_again(entry, now=True)
            return
        entry.current = False
        ended = {"exit_code": local.exit_code, "stderr_tail": local.stderr_tail or None}
        if kind == "started":
            self._update(entry, status="running", era=local.era)
            self._schedule_list(entry)
        elif kind == "restarted":
            self._update(entry, detail=f"restarted after: {detail}", **ended)
        elif kind == "stopped":
            self._update(entry, status="stopped", detail=detail, **ended)
        elif kind == "failed":
            self._update(entry, status="failed", detail=detail, **ended)
        else:
            return
        self._publish(name, kind, detail, log=False)

    async def _list(self, entry: _Server) -> None:
        spec = entry.spec
        try:
            if entry.is_local:
                if entry.local is None:
                    return
                result = await entry.local.list_tools()
            else:
                headers = await self._secret_values(spec, "header", spec.header_names)
                result = await self.connectors.list_remote(
                    spec, headers, era=entry.state.era, discover=entry.state.discover
                )
        except SecretStoreError as exc:
            self._fail(entry, SECRET_FAILURE + str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - a listing failure only affects this server
            # McpUnavailable/McpToolError reasons are scrubbed; anything else: its type only.
            reason = str(exc) if isinstance(exc, (McpUnavailable, McpToolError)) else type(exc).__name__
            entry.next_check = self._clock() + _RETRY_S
            if entry.is_local:
                self._update(entry, detail=f"listing tools failed: {reason}")
                self._publish(spec.name, "failed", f"listing tools failed: {reason}")
            else:
                self._update(entry, status="unreachable", detail=reason)
                self._publish(spec.name, "unreachable", reason)
            return
        now = self._clock()
        ttl = result.ttl_s or _DEFAULT_TTL_S
        entry.next_check = now + ttl
        changes: dict[str, Any] = {
            "era": result.era, "discover": result.discover, "tools": checked(result.tools),
            "listed_at": now, "expires_at": now + ttl,
        }
        if entry.is_local:
            entry.current = entry.local is not None and entry.local.status == "running"
        else:
            changes.update(status="reachable", detail=None)
        entry.state = entry.state.model_copy(update=changes)
        self._apply_clashes()
        self._update(entry)
        self._publish(spec.name, "listed", tools=len(result.tools))

    async def _secret_values(self, spec: ServerSpec, kind: str, names: list[str]) -> dict[str, str]:
        """Values for a server's env or header names, read in a thread (the store may block).

        Waits at most ``min(timeout_s, 5 s)``, then raises ``McpUnavailable(SECRET_SLOW)``
        (a locked keychain may never answer). A read still hanging is waited on again by
        the next attempt rather than started anew, so stuck threads don't pile up."""
        if not names:
            return {}

        def read() -> dict[str, str]:
            values: dict[str, str] = {}
            for item in names:
                value = self._secrets.get(f"mcp:{spec.name}:{kind}:{item}")
                if value is None:
                    logger.warning("mcp server %s: %s %s has no stored value", spec.name, kind, item)
                else:
                    values[item] = value
            return values

        key = (spec.name, kind, tuple(names))
        pending = self._secret_reads.get(key)
        if pending is None or pending.done():
            pending = asyncio.ensure_future(asyncio.to_thread(read))
            pending.add_done_callback(_retrieve)
            pending.add_done_callback(lambda done: self._forget_read(key, done))  # values aren't kept
            self._secret_reads[key] = pending
        try:
            return await asyncio.wait_for(asyncio.shield(pending), min(spec.timeout_s, _SECRET_READ_S))
        except TimeoutError:
            raise McpUnavailable(SECRET_SLOW) from None

    def _forget_read(self, key: tuple[str, str, tuple[str, ...]], done: asyncio.Future[Any]) -> None:
        if self._secret_reads.get(key) is done:
            del self._secret_reads[key]

    # ---- offered tools ------------------------------------------------------------

    def _offerable(self, entry: _Server) -> bool:
        if entry.failed:
            return False
        if entry.is_local:
            return entry.local is not None and entry.local.status == "running" and entry.current
        return entry.state.listed_at is not None and entry.state.status not in ("unreachable", "failed")

    def _apply_clashes(self) -> None:
        changed = with_clashes({name: entry.state.tools for name, entry in self._servers.items()})
        for name, tools in changed.items():
            self._update(self._servers[name], tools=tools)

    # ---- state, events -------------------------------------------------------------

    def _fail(self, entry: _Server, reason: str) -> None:
        entry.failed = True
        self._update(entry, status="failed", detail=reason)
        self._publish(entry.spec.name, "failed", reason)

    def _update(self, entry: _Server, **changes: Any) -> None:
        if "status" in changes:
            changes["status_at"] = self._clock()
        entry.state = entry.state.model_copy(update=changes)
        self._save(entry)

    def _save(self, entry: _Server, *, retired_ok: bool = False) -> None:
        entry.dirty = True
        self._spawn(self._write_state(entry, retired_ok), chore=True)

    async def _write_state(self, entry: _Server, retired_ok: bool) -> None:
        """One write at a time, latest state wins; a dropped server's state isn't written
        back (that would re-create a removed server's row)."""
        async with self._write_lock:
            name = entry.spec.name
            if not entry.dirty or (not retired_ok and self._servers.get(name) is not entry):
                return
            entry.dirty = False
            try:
                # Given the spec, the store skips the write if the server was replaced
                # meanwhile (a late write for the old spec must not land on the new row).
                await asyncio.to_thread(self._store.put_state, name, entry.state, spec=entry.spec)
            except Exception as exc:  # noqa: BLE001 - a lost status line must not stop the server
                logger.warning("mcp server %s: could not record its state (%s)", name, type(exc).__name__)

    def _publish(
        self, server: str, kind: str, detail: str | None = None, *, tools: int | None = None, log: bool = True
    ) -> None:
        if log:
            level = logging.WARNING if kind in ("failed", "unreachable") else logging.INFO
            logger.log(level, "mcp server %s: %s%s", server, kind, f" ({detail})" if detail else "")
        payload = McpServerEvent(server=server, kind=kind, detail=detail, tools=tools)  # type: ignore[arg-type]
        self._spawn(self._emit(payload), chore=True)

    async def _emit(self, payload: McpServerEvent) -> None:
        try:
            await self._new_context().emit(payload, source="mcp")
        except Exception:  # noqa: BLE001 - events are observational
            logger.exception("mcp event could not be published")

    def _spawn(self, coro: Coroutine[Any, Any, Any], *, chore: bool = False) -> asyncio.Task[Any] | None:
        if self._closed and not chore:
            coro.close()
            return None
        task = asyncio.get_running_loop().create_task(coro)
        bucket = self._chores if chore else self._work
        bucket.add(task)
        task.add_done_callback(bucket.discard)
        task.add_done_callback(_report_crash)
        return task


def _retrieve(future: asyncio.Future[Any]) -> None:
    """Mark a shared secret read's outcome as seen (its waiters may have timed out)."""
    if not future.cancelled():
        future.exception()


def _report_crash(task: asyncio.Task[Any]) -> None:
    if not task.cancelled() and (exc := task.exception()) is not None:
        logger.error("mcp background task failed: %s", type(exc).__name__)
