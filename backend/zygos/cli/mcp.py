"""``zygos mcp add | list | remove | on | off | trust | untrust`` (RFC-0015 phase 1a).

Edits the MCP record (``SqliteMcpStore`` in preferences.db) and the secret store; a
running ``zygos serve`` picks the changes up on its next turn. Nothing is started or
contacted before the user confirms an add (``--yes`` skips the prompt); after it, a
remote server is listed once so its tools can be trusted right away.

No secret value (env/header values) and nothing from ``ServerSpec.extra`` is ever
printed: secrets show as ``NAME = set`` / ``NAME = not set``.

Exit codes: 0 done, 1 a user-facing error (bad input, unknown server or tool,
collision, refused, declined).

Stability: Experimental.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import sqlite3
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from pydantic import ValidationError

from zygos.config.schema import ZygosConfig
from zygos.mcp.config import (
    McpConfigError, check_server_names, describe, parse_servers, status_word, validation_reason,
    zygos_tool_name,
)
from zygos.mcp.offered import checked, noted
from zygos.mcp.permission import seen_fingerprint, trust_state
from zygos.mcp.results import McpToolError, McpUnavailable
from zygos.mcp.store import McpStoreUnavailable, ServerState, SqliteMcpStore, TrustEntry
from zygos.mcp.supervisor import NO_MCP, SWITCHED_OFF, TOOL_COUNT_WARNING
from zygos.mcp.types import ParsedServer, SeenTool, ServerSpec
from zygos.secrets import SecretStoreError, build_secret_store

__all__ = ["add_parser", "run_mcp"]

_DEFAULT_TTL_S = 300.0
_ADD_LIST_CAP_S = 20.0  # the listing right after an add waits at most this long
_READ_BUSY_S = 30.0  # how long a read waits for another writer (then a readable error)
_TOOL_WARN_OVER = 20
_LOCAL_HINT = " — its tools are listed when zygos serve starts it"


def add_parser(subcommands: Any) -> None:
    """Register ``zygos mcp …`` on the top-level subcommands."""
    mcp = subcommands.add_parser("mcp", help="Add and manage MCP servers")
    cmds = mcp.add_subparsers(dest="mcp_command", required=True)
    add = cmds.add_parser("add", help="Add servers from an mcpServers JSON (file or stdin)")
    add.add_argument("file", nargs="?", default=None, help="JSON file (default: read stdin)")
    add.add_argument("--yes", action="store_true", help="Don't ask for confirmation")
    cmds.add_parser("list", help="Show servers, their tools and trust")
    remove = cmds.add_parser("remove", help="Remove a server and its stored secrets")
    remove.add_argument("name")
    for verb, text in (
        ("on", "Switch a server or SERVER/TOOL on"),
        ("off", "Switch a server or SERVER/TOOL off"),
        ("trust", "Trust a tool (SERVER/TOOL) or the tools a server has now (SERVER)"),
        ("untrust", "Withdraw trust from SERVER/TOOL or SERVER"),
    ):
        cmd = cmds.add_parser(verb, help=text)
        cmd.add_argument("target", metavar="NAME[/TOOL]")


def _mcp_installed() -> bool:
    try:
        return importlib.util.find_spec("mcp") is not None
    except (ImportError, ValueError):
        return False


def _open_tty() -> TextIO | None:
    """The terminal, for confirming when the JSON came on stdin; None without one."""
    try:
        return open("CONIN$" if os.name == "nt" else "/dev/tty", encoding="utf-8")
    except OSError:
        return None


async def _default_list_remote(*args: Any, **kwargs: Any) -> Any:
    from zygos.mcp.remote import list_remote  # imports the SDK only when called

    return await list_remote(*args, **kwargs)


class _Cli:
    def __init__(
        self,
        config: ZygosConfig,
        *,
        input_fn: Callable[[str], str],
        out: TextIO,
        secrets: Any,
        list_remote: Callable[..., Any],
        mcp_installed: Callable[[], bool],
        clock: Callable[[], float],
        stdin: TextIO,
        tty_opener: Callable[[], TextIO | None],
    ) -> None:
        # Strict: an unreadable record is an error, never "no servers".
        self.store = SqliteMcpStore(Path(config.personalization.db_path)).strict_reader(
            busy_timeout_s=_READ_BUSY_S
        )
        self.stdin = stdin
        self.tty_opener = tty_opener
        self.config = config
        self.input_fn = input_fn
        self.out = out
        self._secrets = secrets
        self.list_remote = list_remote
        self.mcp_installed = mcp_installed
        self.clock = clock

    @property
    def secrets(self) -> Any:
        if self._secrets is None:
            self._secrets = build_secret_store(self.config)
        return self._secrets

    def say(self, text: str = "") -> None:
        print(text, file=self.out)

    def error(self, text: str) -> int:
        self.say(f"zygos mcp: {text}")
        return 1

    # ---- add ---------------------------------------------------------------------

    def add(self, file: str | None, yes: bool) -> int:
        tty = None
        if not file and not yes:
            # stdin carries the JSON, so the answer has to come from the terminal.
            tty = self.tty_opener()
            if tty is None:
                return self.error("stdin was used for the JSON — pass --yes or give a FILE")
        try:
            return self._add(file, yes, tty)
        finally:
            if tty is not None:
                tty.close()

    def _add(self, file: str | None, yes: bool, tty: TextIO | None) -> int:
        try:
            text = Path(file).read_text(encoding="utf-8") if file else self.stdin.read()
        except OSError as exc:
            return self.error(f"can't read {file}: {exc.strerror or type(exc).__name__}")
        try:
            parsed = parse_servers(text)
        except McpConfigError as exc:
            return self.error(str(exc))
        except ValidationError as exc:  # parse_servers turns these into McpConfigError; belt and braces
            return self.error(f"invalid server settings: {validation_reason(exc)}")
        existing = self.store.servers()
        problems = check_server_names([p.spec.name for p in parsed], list(existing))
        if problems:
            for problem in problems:
                self.say(f"zygos mcp: {problem}")
            return 1
        for item in parsed:
            self._show_planned(item, existing.get(item.spec.name))
        if not yes and not self._confirm("Add these servers? [y/N] ", tty):
            self.say("Nothing added.")
            return 1
        code = 0
        for item in parsed:
            if not self._save(item, existing.get(item.spec.name)):
                code = 1
        if self._tools_on() > _TOOL_WARN_OVER:
            self.say(TOOL_COUNT_WARNING)
        return code

    def _show_planned(self, item: ParsedServer, old: ServerSpec | None) -> None:
        spec = item.spec
        self.say(f"{spec.name}:")
        self.say(f"  {describe(spec)}")
        names = [*spec.env_names, *spec.header_names]
        if names:
            self.say(f"  secrets: {', '.join(names)} (stored in the secret store)")
        if spec.extra:
            self.say(f"  not used by Zygos: {', '.join(sorted(spec.extra))}")
        if old is not None:
            self.say(f"  replaces the existing server {spec.name} (its trust is cleared)")

    def _confirm(self, prompt: str, tty: TextIO | None) -> bool:
        if tty is not None:
            self.out.write(prompt)
            self.out.flush()
            answer = tty.readline()
            if not answer:
                self.say()
                return False
        else:
            try:
                answer = self.input_fn(prompt)
            except EOFError:
                self.say()
                return False
        return answer.strip().lower() in ("y", "yes")

    def _save(self, item: ParsedServer, old: ServerSpec | None) -> bool:
        spec = item.spec
        if item.secrets and not self._save_secrets(item):
            return False
        if old is not None:
            self.store.replace_server(spec)  # one transaction; clears its state, trust and on/off
            self._delete_secrets(spec.name, sorted(_handles(old) - set(item.secrets)))
        else:
            self.store.put_server(spec)
        if spec.transport == "stdio":
            self.say(f"{spec.name}: added{_LOCAL_HINT}")
            return True
        self._list_once(item)
        return True

    def _save_secrets(self, item: ParsedServer) -> bool:
        """Store a server's secret values; on a failure put back what was there before."""
        name = item.spec.name
        status = self.secrets.status()
        if not status.available:
            self.say(f"{name}: not added — its secrets can't be stored: {status.why_unavailable}")
            return False
        written: list[str] = []
        previous: dict[str, str | None] = {}
        try:
            previous = {handle: self.secrets.get(handle) for handle in item.secrets}
            for handle, value in item.secrets.items():
                self.secrets.set(handle, value)
                written.append(handle)
        except SecretStoreError as exc:
            self.say(f"{name}: not added — its secrets can't be stored: {exc}")
            self._undo_secrets(name, previous, written)
            return False
        return True

    def _undo_secrets(self, server: str, previous: dict[str, str | None], written: list[str]) -> None:
        stuck: list[str] = []
        for handle in written:
            try:
                if previous[handle] is None:
                    self.secrets.delete(handle)
                else:
                    self.secrets.set(handle, previous[handle])  # type: ignore[arg-type]
            except SecretStoreError:
                stuck.append(handle)
        for handle in stuck:
            what = "overwritten" if previous[handle] is not None else "saved"
            undo = "restored" if previous[handle] is not None else "removed"
            self.say(f"{server}: the secret {_secret_name(handle)} was {what} and couldn't be {undo}")
        if written and not stuck:
            self.say(f"{server}: the secrets saved before the failure were restored")

    def _list_once(self, item: ParsedServer) -> None:
        spec = item.spec
        if not self.mcp_installed():
            self.say(f"{spec.name}: added, but its tools couldn't be listed: {NO_MCP}")
            return
        prefix = f"mcp:{spec.name}:header:"
        headers = {h[len(prefix):]: v for h, v in item.secrets.items() if h.startswith(prefix)}
        limit = min(spec.timeout_s, _ADD_LIST_CAP_S)

        async def bounded() -> Any:
            return await asyncio.wait_for(self.list_remote(spec, headers, era=None, discover=None), limit)

        try:
            result = asyncio.run(bounded())
        except Exception as exc:  # noqa: BLE001 - a failed listing never undoes the add
            # McpUnavailable/McpToolError reasons are scrubbed of header values; others: type only.
            if isinstance(exc, TimeoutError):
                reason = f"no answer within {limit:g} s"
            elif isinstance(exc, (McpUnavailable, McpToolError)):
                reason = str(exc)
            else:
                reason = type(exc).__name__
            now = self.clock()
            self.store.put_state(
                spec.name, ServerState(status="unreachable", detail=reason, status_at=now)
            )
            self.say(f"{spec.name}: added, but its tools couldn't be listed: {reason} — zygos serve tries again")
            return
        now = self.clock()
        ttl = result.ttl_s or _DEFAULT_TTL_S
        tools = checked(result.tools)
        self.store.put_state(spec.name, ServerState(
            era=result.era, discover=result.discover, tools=tools,
            listed_at=now, expires_at=now + ttl, status="reachable", status_at=now,
        ))
        count = len(tools)
        self.say(f"{spec.name}: added — {count} tool{'s' if count != 1 else ''} listed (protocol {result.era})")
        if tools:
            self.say(
                f"  trust the ones you want: zygos mcp trust {spec.name}/TOOL "
                f"(or {spec.name} for all {count}) — see zygos mcp list"
            )

    def _delete_secrets(self, server: str, handles: list[str]) -> None:
        for handle in handles:
            try:
                self.secrets.delete(handle)
            except SecretStoreError as exc:
                self.say(f"{server}: could not delete the secret {_secret_name(handle)}: {exc}")

    # ---- list ---------------------------------------------------------------------

    def list(self) -> int:
        servers = self.store.servers()
        if not servers:
            self.say("No MCP servers added. Add one with: zygos mcp add servers.json")
            return 0
        off = self.store.off()
        trust = self.store.trust_entries()
        states = {name: self.store.state(name) for name in servers}
        tools_by = _tools_by(servers, states, off)
        for name in sorted(servers):
            spec, state = servers[name], states[name]
            server_on = f"server:{name}" not in off
            if name != min(servers):
                self.say()
            self.say(f"{name} ({'on' if server_on else 'off'})")
            self.say(f"  {describe(spec)}")
            self.say(f"  protocol {state.era or 'not known yet'}")
            self.say(f"  status: {_status(spec, state)}")
            for kind, names in (("env", spec.env_names), ("header", spec.header_names)):
                for item in names:
                    self.say(f"  {kind} {item} = {self._presence(f'mcp:{name}:{kind}:{item}')}")
            tools = tools_by[name]
            if not tools:
                hint = _LOCAL_HINT if spec.transport == "stdio" else ""
                self.say(f"  tools: none seen yet{hint}")
                continue
            self.say("  tools:")
            for seen in tools:
                zname = zygos_tool_name(name, seen.name)
                if seen.problem is not None:
                    self.say(f"    {seen.name} — left out: {seen.problem}")
                    continue
                tool_on = f"tool:{zname}" not in off
                self.say(f"    {seen.name} — {'on' if tool_on else 'off'}, {self._trust_text(name, zname, seen, trust)}")
        on_count = _count_on(servers, off, tools_by)
        self.say(f"{on_count} tool{'s' if on_count != 1 else ''} on")
        if on_count > _TOOL_WARN_OVER:
            self.say(TOOL_COUNT_WARNING)
        if not self.mcp_installed():
            self.say(NO_MCP)
        return 0

    def _tools_on(self) -> int:
        servers = self.store.servers()
        off = self.store.off()
        return _count_on(servers, off, _tools_by(servers, {n: self.store.state(n) for n in servers}, off))

    def _presence(self, handle: str) -> str:
        try:
            presence = self.secrets.presence(handle)
        except SecretStoreError as exc:
            return f"unknown ({exc})"
        if presence.state == "set":
            return "set"
        if presence.state == "not_set":
            return "not set"
        return f"unknown ({presence.reason})"

    def _trust_text(self, server: str, zname: str, seen: SeenTool, trust: dict[str, TrustEntry]) -> str:
        entry = trust.get(zname)
        if entry is None or entry.server != server:
            return "not trusted"
        if trust_state(zname, seen, trust) == "trusted":
            return "trusted"
        lines = ["changed since you trusted it"]
        if entry.description != seen.description:
            lines += [f"      was: {entry.description}", f"      now: {seen.description}"]
        if entry.input_schema != seen.input_schema:
            lines.append("      its input schema changed too" if len(lines) > 1 else "      its input schema changed")
        return "\n".join(lines)

    # ---- remove, on/off, trust ------------------------------------------------------------

    def remove(self, name: str) -> int:
        spec = self.store.servers().get(name)
        if spec is None:
            return self.error(f"no server {name}")
        self.store.remove_server(name)
        self._delete_secrets(name, sorted(_handles(spec)))
        self.say(f"Removed {name}.")
        return 0

    def _target(self, target: str) -> tuple[ServerSpec, str | None] | None:
        servers = self.store.servers()
        if target in servers:
            return servers[target], None
        # Server names may contain "/": the longest matching server name wins.
        for i in range(len(target) - 1, 0, -1):
            if target[i] == "/" and target[:i] in servers:
                return servers[target[:i]], target[i + 1:]
        return None

    def _seen(self, spec: ServerSpec, tool: str | None) -> list[SeenTool] | None:
        """The tools seen now (one, or all for ``tool=None``); None after printing the error."""
        tools = self.store.state(spec.name).tools
        if tool is not None:
            tools = [t for t in tools if t.name == tool]
        if tools:
            return tools
        hint = _LOCAL_HINT if spec.transport == "stdio" else ""
        what = f"no tool {tool}" if tool is not None else "no tools"
        self.error(f"{what} seen on {spec.name} yet{hint}")
        return None

    def switch(self, target: str, on: bool) -> int:
        found = self._target(target)
        if found is None:
            return self.error(f"no server {target.split('/', 1)[0]}")
        spec, tool = found
        word = "on" if on else "off"
        if tool is None:
            self.store.set_off("server", spec.name, not on)
            state = self.store.state(spec.name)
            if on and state.status == "stopped" and state.detail == SWITCHED_OFF:
                # zygos serve stopped it for being off; it isn't any more
                self.store.put_state(spec.name, state.model_copy(
                    update={"status": "not_started", "detail": None, "status_at": self.clock()}))
            self.say(f"{spec.name} is {word}.")
            return 0
        zname = zygos_tool_name(spec.name, tool)
        already_off = f"tool:{zname}" in self.store.off()
        if not (on and already_off) and self._seen(spec, tool) is None:
            return 1
        self.store.set_off("tool", zname, not on, server=spec.name)
        self.say(f"{spec.name}/{tool} is {word}.")
        return 0

    def trust(self, target: str) -> int:
        found = self._target(target)
        if found is None:
            return self.error(f"no server {target.split('/', 1)[0]}")
        spec, tool = found
        tools = self._seen(spec, tool)
        if tools is None:
            return 1
        via = "tool" if tool is not None else "server"
        entries = [_entry(spec.name, seen, via) for seen in tools]
        if tool is not None:
            self.store.trust_tool(entries[0])
            self.say(f"Trusted {spec.name}/{tool}.")
        else:
            self.store.trust_server(spec.name, entries)
            self.say(f"Trusted the {len(entries)} tool{'s' if len(entries) != 1 else ''} {spec.name} has now.")
            self.say("Tools it adds later need trusting on their own.")
        return 0

    def untrust(self, target: str) -> int:
        found = self._target(target)
        if found is None:
            return self.error(f"no server {target.split('/', 1)[0]}")
        spec, tool = found
        if tool is not None:
            zname = zygos_tool_name(spec.name, tool)
            entry = self.store.trust_entries().get(zname)
            if entry is None or entry.server != spec.name:
                self.say(f"{spec.name}/{tool} wasn't trusted.")
                return 0
            self.store.untrust_tool(zname)
            self.say(f"{spec.name}/{tool} is no longer trusted.")
            return 0
        self.store.untrust_server(spec.name)
        kept = sorted(
            e.tool for e in self.store.trust_entries().values() if e.server == spec.name and e.via == "tool"
        )
        self.say(f"{spec.name} is no longer trusted as a server.")
        if kept:
            self.say(f"Tools trusted one by one stay trusted ({len(kept)}): zygos mcp untrust {spec.name}/TOOL")
        return 0


def _secret_name(handle: str) -> str:
    return handle.rsplit(":", 1)[-1]


def _tools_by(
    servers: dict[str, ServerSpec], states: dict[str, ServerState], off: set[str]
) -> dict[str, list[SeenTool]]:
    """Each server's tools with schema problems and name clashes (among servers on) noted."""
    on = {name for name in servers if f"server:{name}" not in off}
    return noted({name: checked(state.tools) for name, state in states.items()}, on)


def _count_on(servers: dict[str, ServerSpec], off: set[str], tools_by: dict[str, list[SeenTool]]) -> int:
    return sum(
        1
        for name in servers
        if f"server:{name}" not in off
        for seen in tools_by.get(name, [])
        if seen.problem is None and f"tool:{zygos_tool_name(name, seen.name)}" not in off
    )


def _handles(spec: ServerSpec) -> set[str]:
    return {f"mcp:{spec.name}:env:{n}" for n in spec.env_names} | {
        f"mcp:{spec.name}:header:{n}" for n in spec.header_names
    }


def _entry(server: str, seen: SeenTool, via: str) -> TrustEntry:
    """Pinned the way the supervisor's gate checks it: the server's own tool name."""
    return TrustEntry(
        server=server, tool=zygos_tool_name(server, seen.name), fingerprint=seen_fingerprint(seen),
        description=seen.description, input_schema=seen.input_schema, via=via,  # type: ignore[arg-type]
    )


def _status(spec: ServerSpec, state: ServerState) -> str:
    text = status_word(spec.transport, state.status)
    if state.status == "not_started":
        return text
    if state.status_at is not None:
        text += f" (as of {datetime.fromtimestamp(state.status_at).strftime('%Y-%m-%d %H:%M')})"
    if state.status == "stopped" and state.exit_code is not None:
        text += f" — exit {state.exit_code}"
        last = (state.stderr_tail or "").strip().splitlines()
        if last:
            text += f": {last[-1]}"
    elif state.detail:
        text += f" — {state.detail}"
    return text


def run_mcp(
    args: argparse.Namespace,
    config: ZygosConfig,
    *,
    input_fn: Callable[[str], str] = input,
    out: TextIO | None = None,
    secrets: Any = None,
    list_remote: Callable[..., Any] | None = None,
    mcp_installed: Callable[[], bool] = _mcp_installed,
    clock: Callable[[], float] = time.time,
    stdin: TextIO | None = None,
    tty_opener: Callable[[], TextIO | None] = _open_tty,
) -> int:
    """Run one ``zygos mcp`` subcommand; returns the exit code."""
    cli = _Cli(
        config, input_fn=input_fn, out=out if out is not None else sys.stdout, secrets=secrets,
        list_remote=list_remote or _default_list_remote, mcp_installed=mcp_installed, clock=clock,
        stdin=stdin if stdin is not None else sys.stdin, tty_opener=tty_opener,
    )
    try:
        return _dispatch(cli, args)
    except McpStoreUnavailable as exc:  # already a readable reason, never values
        return cli.error(str(exc))
    except sqlite3.Error as exc:
        return cli.error(f"couldn't update the MCP record ({exc}); try again")


def _dispatch(cli: _Cli, args: argparse.Namespace) -> int:
    command = args.mcp_command
    if command == "add":
        return cli.add(args.file, args.yes)
    if command == "list":
        return cli.list()
    if command == "remove":
        return cli.remove(args.name)
    if command in ("on", "off"):
        return cli.switch(args.target, command == "on")
    if command == "trust":
        return cli.trust(args.target)
    if command == "untrust":
        return cli.untrust(args.target)
    return 2
