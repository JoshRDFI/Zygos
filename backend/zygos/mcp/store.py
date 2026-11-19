"""SQLite persistence for MCP servers, learned state, trust and on/off.

Same database file as preferences, own tables, one row per item. A short-lived
connection is opened per call (the CLI and `zygos serve` are separate processes).
Every write is one IMMEDIATE transaction that touches only its rows and bumps
``mcp_meta.version``; a busy timeout makes concurrent writers wait, not fail.
Reading never creates the database file. Only names are stored, never secret values.

Stability: Experimental.
"""

from __future__ import annotations

import hashlib
import json
import logging
import copy
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field, ValidationError

from zygos.mcp.config import clean_part
from zygos.mcp.types import SeenTool, ServerSpec

_log = logging.getLogger("zygos.mcp")

_BUSY_TIMEOUT_S = 30.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mcp_servers (name TEXT PRIMARY KEY, spec TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mcp_state (name TEXT PRIMARY KEY, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mcp_trust (tool TEXT PRIMARY KEY, entry TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mcp_trust_servers (name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS mcp_off (key TEXT PRIMARY KEY, server TEXT);
CREATE TABLE IF NOT EXISTS mcp_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);
INSERT OR IGNORE INTO mcp_meta(id, version) VALUES (1, 0);
"""

_T = TypeVar("_T")


class McpStoreUnavailable(Exception):
    """A strict reader could not read the record (busy, corrupt, I/O). Never carries values."""


class ServerState(BaseModel):
    era: str | None = None
    discover: dict[str, Any] | None = None
    tools: list[SeenTool] = Field(default_factory=list)
    listed_at: float | None = None
    expires_at: float | None = None
    status: Literal[
        "not_started", "running", "stopped", "reachable", "unreachable", "failed"
    ] = "not_started"
    detail: str | None = None
    exit_code: int | None = None
    stderr_tail: str | None = None
    status_at: float | None = None


class TrustEntry(BaseModel):
    server: str  # server key the tool belongs to
    tool: str  # zygos tool name
    fingerprint: str
    description: str
    input_schema: dict[str, Any]
    via: Literal["tool", "server"]


def fingerprint(name: str, description: str, input_schema: dict[str, Any]) -> str:
    blob = json.dumps([name, description, input_schema], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class SqliteMcpStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._busy_timeout_s = _BUSY_TIMEOUT_S
        self._strict = False

    def strict_reader(self, *, busy_timeout_s: float) -> "SqliteMcpStore":
        """A copy for reading on the event loop: waits at most ``busy_timeout_s`` for a
        writer and raises ``McpStoreUnavailable`` instead of reading empty on failure (so
        a failed read is never mistaken for "no servers"). A missing file still reads empty."""
        reader = copy.copy(self)
        reader._busy_timeout_s = busy_timeout_s
        reader._strict = True
        return reader

    # -- reads ---------------------------------------------------------------

    def _read(self, fn: Callable[[sqlite3.Connection], _T], default: _T) -> _T:
        if not self._path.exists():
            return default
        try:
            with closing(sqlite3.connect(self._path, timeout=self._busy_timeout_s)) as con:
                has = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mcp_meta'"
                ).fetchone()
                if has is None:
                    return default
                return fn(con)
        except sqlite3.Error as exc:
            if self._strict:
                raise McpStoreUnavailable(f"mcp store unreadable ({type(exc).__name__}: {exc})") from None
            _log.warning("mcp store unreadable (%s); using empty", exc)
            return default

    def _parse(self, model: type[BaseModel], raw: str, table: str, key: str) -> Any:
        try:
            return model.model_validate_json(raw)
        except ValidationError as exc:
            # Never log exc text: pydantic errors echo the stored values.
            _log.warning("mcp row invalid (%s, key %r: %s); skipped", table, key, type(exc).__name__)
            return None

    def servers(self) -> dict[str, ServerSpec]:
        rows = self._read(lambda c: c.execute("SELECT name, spec FROM mcp_servers").fetchall(), [])
        out: dict[str, ServerSpec] = {}
        for name, raw in rows:
            spec = self._parse(ServerSpec, raw, "mcp_servers", name)
            if spec is not None:
                out[name] = spec
        return out

    def state(self, name: str) -> ServerState:
        row = self._read(
            lambda c: c.execute("SELECT state FROM mcp_state WHERE name=?", (name,)).fetchone(),
            None,
        )
        if row is None:
            return ServerState()
        return self._parse(ServerState, row[0], "mcp_state", name) or ServerState()

    def trust_entries(self) -> dict[str, TrustEntry]:
        rows = self._read(lambda c: c.execute("SELECT tool, entry FROM mcp_trust").fetchall(), [])
        out: dict[str, TrustEntry] = {}
        for tool, raw in rows:
            entry = self._parse(TrustEntry, raw, "mcp_trust", tool)
            if entry is not None:
                out[tool] = entry
        return out

    def trusted_servers(self) -> set[str]:
        rows = self._read(lambda c: c.execute("SELECT name FROM mcp_trust_servers").fetchall(), [])
        return {r[0] for r in rows}

    def off(self) -> set[str]:
        rows = self._read(lambda c: c.execute("SELECT key FROM mcp_off").fetchall(), [])
        return {r[0] for r in rows}

    def version(self) -> int:
        row = self._read(
            lambda c: c.execute("SELECT version FROM mcp_meta WHERE id=1").fetchone(), None
        )
        return int(row[0]) if row else 0

    # -- writes --------------------------------------------------------------

    def _write(self, fn: Callable[[sqlite3.Connection], None]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(
            sqlite3.connect(self._path, timeout=_BUSY_TIMEOUT_S, isolation_level=None)
        ) as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                for stmt in _SCHEMA.split(";"):
                    if stmt.strip():
                        con.execute(stmt)
                fn(con)
                con.execute("UPDATE mcp_meta SET version = version + 1 WHERE id = 1")
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise

    def put_server(self, spec: ServerSpec) -> None:
        if "__" in clean_part(spec.name):
            raise ValueError(
                f"server name {spec.name!r}: '__' is reserved as the server/tool separator"
            )
        self._write(
            lambda c: c.execute(
                "INSERT INTO mcp_servers(name, spec) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET spec = excluded.spec",
                (spec.name, spec.model_dump_json()),
            )
        )

    @staticmethod
    def _clear_server(c: sqlite3.Connection, name: str) -> None:
        c.execute("DELETE FROM mcp_servers WHERE name=?", (name,))
        c.execute("DELETE FROM mcp_state WHERE name=?", (name,))
        c.execute("DELETE FROM mcp_trust_servers WHERE name=?", (name,))
        c.execute("DELETE FROM mcp_off WHERE key=?", (f"server:{name}",))
        c.execute("DELETE FROM mcp_trust WHERE json_extract(entry, '$.server') = ?", (name,))
        c.execute("DELETE FROM mcp_off WHERE server = ?", (name,))

    def remove_server(self, name: str) -> None:
        self._write(lambda c: self._clear_server(c, name))

    def replace_server(self, spec: ServerSpec) -> None:
        """Put ``spec`` in place of the server of the same name, clearing that server's
        state, trust and on/off, in one transaction (a reader never sees it missing)."""
        if "__" in clean_part(spec.name):
            raise ValueError(
                f"server name {spec.name!r}: '__' is reserved as the server/tool separator"
            )

        def go(c: sqlite3.Connection) -> None:
            self._clear_server(c, spec.name)
            c.execute(
                "INSERT INTO mcp_servers(name, spec) VALUES (?, ?)", (spec.name, spec.model_dump_json())
            )

        self._write(go)

    def put_state(self, name: str, state: ServerState, *, spec: ServerSpec | None = None) -> None:
        """Record a server's state; a no-op once the server is gone (a late write must not
        leave a row a re-added server of the same name would adopt) and, given ``spec``,
        a no-op when the stored server is no longer that spec (replaced meanwhile)."""

        def go(c: sqlite3.Connection) -> None:
            row = c.execute("SELECT spec FROM mcp_servers WHERE name=?", (name,)).fetchone()
            if row is None:
                return
            if spec is not None:
                try:
                    stored = ServerSpec.model_validate_json(row[0])
                except ValidationError:
                    return
                if stored != spec:
                    return
            self._put_state_row(c, name, state)

        self._write(go)

    @staticmethod
    def _put_state_row(c: sqlite3.Connection, name: str, state: ServerState) -> None:
        c.execute(
            "INSERT INTO mcp_state(name, state) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET state = excluded.state",
            (name, state.model_dump_json()),
        )

    @staticmethod
    def _put_trust(c: sqlite3.Connection, entry: TrustEntry) -> None:
        c.execute(
            "INSERT INTO mcp_trust(tool, entry) VALUES (?, ?) "
            "ON CONFLICT(tool) DO UPDATE SET entry = excluded.entry",
            (entry.tool, entry.model_dump_json()),
        )

    def trust_tool(self, entry: TrustEntry) -> None:
        self._write(lambda c: self._put_trust(c, entry))

    def trust_server(self, name: str, entries: list[TrustEntry]) -> None:
        def go(c: sqlite3.Connection) -> None:
            c.execute("INSERT OR IGNORE INTO mcp_trust_servers(name) VALUES (?)", (name,))
            for e in entries:
                self._put_trust(c, e)

        self._write(go)

    def untrust_tool(self, tool: str) -> None:
        self._write(lambda c: c.execute("DELETE FROM mcp_trust WHERE tool=?", (tool,)))

    def untrust_server(self, name: str) -> None:
        def go(c: sqlite3.Connection) -> None:
            c.execute("DELETE FROM mcp_trust_servers WHERE name=?", (name,))
            c.execute(
                "DELETE FROM mcp_trust WHERE json_extract(entry, '$.server') = ? "
                "AND json_extract(entry, '$.via') = 'server'",
                (name,),
            )

        self._write(go)

    def set_off(
        self, kind: Literal["server", "tool"], name: str, off: bool, *, server: str | None = None
    ) -> None:
        if kind == "tool" and server is None:
            raise ValueError("set_off for a tool needs its server")
        key = f"{kind}:{name}"
        owner = server if kind == "tool" else None
        if off:
            self._write(
                lambda c: c.execute(
                    "INSERT INTO mcp_off(key, server) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET server = excluded.server",
                    (key, owner),
                )
            )
        else:
            self._write(lambda c: c.execute("DELETE FROM mcp_off WHERE key=?", (key,)))

    def set_server_on(self, name: str, on: bool, *, now: float) -> None:
        """Switch a server on or off in one transaction; switching on also clears the
        "switched off" stop state that ``zygos serve`` recorded."""

        from zygos.mcp.supervisor import SWITCHED_OFF  # supervisor imports this module

        def go(c: sqlite3.Connection) -> None:
            key = f"server:{name}"
            if not on:
                c.execute(
                    "INSERT INTO mcp_off(key, server) VALUES (?, NULL) "
                    "ON CONFLICT(key) DO UPDATE SET server = excluded.server",
                    (key,),
                )
                return
            c.execute("DELETE FROM mcp_off WHERE key=?", (key,))
            row = c.execute("SELECT state FROM mcp_state WHERE name=?", (name,)).fetchone()
            if row is None:
                return
            state = self._parse(ServerState, row[0], "mcp_state", name)
            if state is not None and state.status == "stopped" and state.detail == SWITCHED_OFF:
                self._put_state_row(c, name, state.model_copy(
                    update={"status": "not_started", "detail": None, "status_at": now}))

        self._write(go)
