"""Which MCP tools a turn is offered: schema check, name clashes, on/off. Pure: no I/O.

A tool is offered only when its schema is usable (``check_input_schema``; a turn must
never see one ``tool_schema`` would reject), it is not switched off, and no other tool —
of another server or the same one — maps to the same Zygos name. Clashing tools are all
left out, the clash noted as their ``problem`` (so ``zygos mcp list`` can show it); the
note clears itself once the clash is gone.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

from zygos.agent.schema import check_input_schema
from zygos.mcp.config import zygos_tool_name
from zygos.mcp.tool import McpTool
from zygos.mcp.types import SeenTool, ServerSpec

__all__ = ["CLASH", "build_offered", "checked", "noted", "with_clashes"]

CLASH = "name clash: "


def checked(tools: list[SeenTool]) -> list[SeenTool]:
    """Note a schema problem on any tool stored without one."""
    out = []
    for tool in tools:
        if tool.problem is None and (problem := check_input_schema(tool.input_schema)) is not None:
            tool = tool.model_copy(update={"problem": problem})
        out.append(tool)
    return out


def with_clashes(tools_by_server: Mapping[str, list[SeenTool]]) -> dict[str, list[SeenTool]]:
    """The servers whose tools' clash notes change, with their updated tool lists."""
    owners: dict[str, list[str]] = {}
    for name, tools in tools_by_server.items():
        for seen in tools:
            owners.setdefault(zygos_tool_name(name, seen.name), []).append(f"{name}/{seen.name}")
    changed: dict[str, list[SeenTool]] = {}
    for name, tools in tools_by_server.items():
        out, differs = [], False
        for seen in tools:
            zname = zygos_tool_name(name, seen.name)
            problem = seen.problem
            if problem is not None and problem.startswith(CLASH):
                problem = check_input_schema(seen.input_schema)
            clash = owners[zname]
            if problem is None and len(clash) > 1:
                verb = "both become" if len(clash) == 2 else "all become"
                problem = f"{CLASH}{' and '.join(clash)} {verb} {zname}"
            if problem != seen.problem:
                seen, differs = seen.model_copy(update={"problem": problem}), True
            out.append(seen)
        if differs:
            changed[name] = out
    return changed


def noted(tools_by_server: Mapping[str, list[SeenTool]], on: set[str]) -> dict[str, list[SeenTool]]:
    """Every server's tools with clash notes as the supervisor keeps them: clashes count
    only among servers that are on (it runs only those); an off server's tools are
    checked against each other alone."""
    out = dict(tools_by_server)
    out.update(with_clashes({n: t for n, t in tools_by_server.items() if n in on}))
    for name, tools in tools_by_server.items():
        if name not in on:
            out.update(with_clashes({name: tools}))
    return out


def build_offered(
    servers: Iterable[tuple[ServerSpec, list[SeenTool]]],
    off: set[str],
    previous: Mapping[str, McpTool],
    call: Callable[[str, str, dict[str, Any]], Awaitable[Any]],
) -> list[McpTool]:
    """McpTools for the given (offerable) servers; unchanged tools keep their objects."""
    tools: list[McpTool] = []
    for spec, seen_tools in servers:
        for seen in seen_tools:
            zname = zygos_tool_name(spec.name, seen.name)
            if seen.problem is not None or f"tool:{zname}" in off:
                continue
            old = previous.get(zname)
            if old is not None and old.seen == seen and old.spec == spec:
                tools.append(old)
            else:
                tools.append(McpTool(spec, seen, call))
    return tools
