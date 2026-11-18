"""An MCP server's tool as a Zygos tool: JSON-Schema input, calls go to the supervisor.

A failure (server unreachable, or the tool's own error) is re-raised for the executor to
turn into a tool error, and published with the turn's context so it reaches the trace.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from zygos.mcp.config import zygos_tool_name
from zygos.mcp.results import McpToolError, McpUnavailable
from zygos.mcp.types import SeenTool, ServerSpec
from zygos.runtime.events import McpServerEvent
from zygos.tools.types import BaseTool, RetryPolicy, ToolContext, ToolMeta

Call = Callable[[str, str, dict[str, Any]], Awaitable[Any]]


class McpTool(BaseTool):
    def __init__(self, spec: ServerSpec, seen: SeenTool, call: Call) -> None:
        self.spec = spec
        self.seen = seen
        self._call = call
        self.meta = ToolMeta(
            name=zygos_tool_name(spec.name, seen.name),
            description=f"[{spec.name}] {seen.description}",
            input_schema=seen.input_schema,
            server=spec.name,
            server_tool=seen.name,
            timeout_s=spec.timeout_s,
            retry=RetryPolicy(attempts=1),
            permission="ask",
        )

    async def execute(self, input: dict[str, Any], ctx: ToolContext) -> Any:
        server, tool = self.meta.server or "", self.meta.server_tool or ""
        try:
            return await self._call(server, tool, dict(input))
        except (McpUnavailable, McpToolError) as exc:
            await ctx.emit(McpServerEvent(server=server, kind="failed", detail=str(exc)), source="mcp")
            raise
