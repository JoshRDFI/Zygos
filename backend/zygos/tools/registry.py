"""Name-keyed tool registry (ARCHITECTURE §Tool Contract). Stability: Experimental."""

from __future__ import annotations

from zygos.errors import ToolError
from zygos.tools.types import Tool, ToolMeta


class ToolRegistry:
    def __init__(self) -> None:
        self._by_name: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        name = tool.meta.name
        if name in self._by_name:
            raise ToolError(f"tool {name!r} is already registered")
        self._by_name[name] = tool

    def get(self, name: str) -> Tool | None:
        return self._by_name.get(name)

    def list(self) -> list[ToolMeta]:
        return [tool.meta for tool in self._by_name.values()]
