"""ToolService facade (ARCHITECTURE §services: register/execute/snapshot).

Pull-only snapshot; no bus events, no bootstrap wiring this cycle (M5 C1).
Stability: Experimental.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from zygos.errors import ToolNotFound
from zygos.runtime.context import ExecutionContext
from zygos.tools.executor import execute_tool
from zygos.tools.registry import ToolRegistry
from zygos.tools.types import Tool, ToolCall, ToolMeta, ToolResult


class ToolServiceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    registered: list[ToolMeta]


class ToolService:
    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._registry = registry if registry is not None else ToolRegistry()

    def register(self, tool: Tool) -> None:
        self._registry.register(tool)

    async def execute(self, call: ToolCall, ctx: ExecutionContext) -> ToolResult:
        tool = self._registry.get(call.tool)
        if tool is None:
            raise ToolNotFound(f"unknown tool: {call.tool!r}")
        return await execute_tool(tool, call, ctx)

    def snapshot(self) -> ToolServiceSnapshot:
        return ToolServiceSnapshot(registered=self._registry.list())
