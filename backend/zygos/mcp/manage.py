"""Trust operations shared by the CLI and the chat permission prompt."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from zygos.mcp.config import zygos_tool_name
from zygos.mcp.permission import seen_fingerprint
from zygos.mcp.store import SqliteMcpStore, TrustEntry
from zygos.mcp.types import SeenTool

__all__ = ["trust_all", "trust_entry", "trust_one"]


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
