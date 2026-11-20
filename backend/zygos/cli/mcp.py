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
import os
import sqlite3
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from zygos.config.schema import ZygosConfig
from zygos.mcp import manage
from zygos.mcp.config import status_word
from zygos.mcp.store import McpStoreUnavailable, ServerState, SqliteMcpStore
from zygos.mcp.supervisor import NO_MCP, TOOL_COUNT_WARNING
from zygos.mcp.types import ParsedServer, ServerSpec
from zygos.secrets import build_secret_store

__all__ = ["add_parser", "run_mcp"]

_ADD_LIST_CAP_S = manage.ADD_LIST_CAP_S
_READ_BUSY_S = 30.0  # how long a read waits for another writer (then a readable error)
_TOOL_WARN_OVER = manage.TOOL_WARN_OVER
_LOCAL_HINT = manage.LOCAL_HINT


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


_mcp_installed = manage.mcp_installed


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
            plan = manage.plan_add(self.store, text)
        except manage.ManageError as exc:
            return self.error(exc.reason)
        if plan.problems:
            for problem in plan.problems:
                self.say(f"zygos mcp: {problem}")
            return 1
        for planned in plan.servers:
            self._show_planned(planned)
        if not yes and not self._confirm("Add these servers? [y/N] ", tty):
            self.say("Nothing added.")
            return 1
        existing = self.store.servers()
        code = 0
        for item in plan.items:
            if not self._save(item, existing.get(item.spec.name)):
                code = 1
        if self._tools_on() > _TOOL_WARN_OVER:
            self.say(TOOL_COUNT_WARNING)
        return code

    def _show_planned(self, planned: manage.PlannedServer) -> None:
        self.say(f"{planned.name}:")
        self.say(f"  {planned.runs}")
        if planned.secret_names:
            self.say(f"  secrets: {', '.join(planned.secret_names)} (stored in the secret store)")
        if planned.unused:
            self.say(f"  not used by Zygos: {', '.join(planned.unused)}")
        if planned.replaces:
            self.say(f"  replaces the existing server {planned.name} (its trust is cleared)")

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
        try:
            notes = manage.save_server(self.store, self.secrets, item, old)
        except manage.ManageError as exc:
            self.say(f"{spec.name}: not added — {exc.reason}")
            for note in exc.notes:
                self.say(note)
            return False
        for note in notes:
            self.say(note)
        if spec.transport == "stdio":
            self.say(f"{spec.name}: added{_LOCAL_HINT}")
            return True
        self.say(asyncio.run(manage.list_after_add(
            self.store, spec, item, list_remote=self.list_remote, mcp_installed=self.mcp_installed,
            clock=self.clock, cap_s=_ADD_LIST_CAP_S,
        )))
        return True

    # ---- list ---------------------------------------------------------------------

    def list(self) -> int:
        view = manage.list_view(self.store, self.secrets, mcp_installed=self.mcp_installed)
        if not view.servers:
            self.say("No MCP servers added. Add one with: zygos mcp add servers.json")
            return 0
        for i, server in enumerate(view.servers):
            if i:
                self.say()
            self.say(f"{server.name} ({'on' if server.on else 'off'})")
            self.say(f"  {server.runs}")
            self.say(f"  protocol {server.era or 'not known yet'}")
            self.say(f"  status: {_status(server, server)}")
            for kind, names in (("env", server.env_names), ("header", server.header_names)):
                for item in names:
                    self.say(f"  {kind} {item} = {_presence_text(server, item)}")
            if not server.tools:
                hint = _LOCAL_HINT if server.local else ""
                self.say(f"  tools: none seen yet{hint}")
                continue
            self.say("  tools:")
            for tool in server.tools:
                if tool.problem is not None:
                    self.say(f"    {tool.server_tool} — left out: {tool.problem}")
                    continue
                self.say(f"    {tool.server_tool} — {'on' if tool.on else 'off'}, {_trust_text(tool)}")
        on_count = view.tools_on
        self.say(f"{on_count} tool{'s' if on_count != 1 else ''} on")
        if view.warning is not None:
            self.say(view.warning)
        if not view.installed:
            self.say(NO_MCP)
        return 0

    def _tools_on(self) -> int:
        return manage.tools_on(self.store)

    # ---- remove, on/off, trust ------------------------------------------------------------

    def remove(self, name: str) -> int:
        try:
            notes = manage.remove_server(self.store, self.secrets, name)
        except manage.ManageError as exc:
            return self.error(exc.reason)
        for note in notes:
            self.say(note)
        self.say(f"Removed {name}.")
        return 0

    def switch(self, target: str, on: bool) -> int:
        word = "on" if on else "off"
        try:
            spec, tool = manage.resolve_target(self.store, target)
            if tool is None:
                manage.switch_server(self.store, spec.name, on, clock=self.clock)
                self.say(f"{spec.name} is {word}.")
                return 0
            manage.switch_tool(self.store, spec.name, tool, on)
        except manage.ManageError as exc:
            return self.error(exc.reason)
        self.say(f"{spec.name}/{tool} is {word}.")
        return 0

    def trust(self, target: str) -> int:
        try:
            spec, tool = manage.resolve_target(self.store, target)
            if tool is not None:
                manage.trust_tool(self.store, spec.name, tool)
                self.say(f"Trusted {spec.name}/{tool}.")
                return 0
            entries = manage.trust_server(self.store, spec.name)
        except manage.ManageError as exc:
            return self.error(exc.reason)
        self.say(f"Trusted the {len(entries)} tool{'s' if len(entries) != 1 else ''} {spec.name} has now.")
        self.say("Tools it adds later need trusting on their own.")
        return 0

    def untrust(self, target: str) -> int:
        try:
            spec, tool = manage.resolve_target(self.store, target)
            if tool is not None:
                if manage.untrust_tool(self.store, spec.name, tool):
                    self.say(f"{spec.name}/{tool} is no longer trusted.")
                else:
                    self.say(f"{spec.name}/{tool} wasn't trusted.")
                return 0
            kept = manage.untrust_server(self.store, spec.name)
        except manage.ManageError as exc:
            return self.error(exc.reason)
        self.say(f"{spec.name} is no longer trusted as a server.")
        if kept:
            self.say(f"Tools trusted one by one stay trusted ({len(kept)}): zygos mcp untrust {spec.name}/TOOL")
        return 0


def _presence_text(server: manage.ServerView, name: str) -> str:
    found = server.secrets[name]
    return f"unknown ({server.secret_reasons[name]})" if found == "unknown" else found


def _trust_text(tool: manage.ToolView) -> str:
    if tool.trust == "asks":
        return "not trusted"
    if tool.trust == "trusted":
        return "trusted"
    lines = ["changed since you trusted it"]
    if tool.was != tool.now:
        lines += [f"      was: {tool.was}", f"      now: {tool.now}"]
    if tool.schema_changed:
        lines.append("      its input schema changed too" if len(lines) > 1 else "      its input schema changed")
    return "\n".join(lines)


def _status(spec: ServerSpec | manage.ServerView, state: ServerState | manage.ServerView) -> str:
    """The status line; a ``ServerView`` carries both the transport and the recorded state."""
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
