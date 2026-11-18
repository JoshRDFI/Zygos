"""Derive a provider-facing ToolSchema from a tool's ToolMeta + input_model (RFC-0008 §3).

$defs/$ref are inlined into one flat schema object because many local-model tool
parsers handle $ref poorly. Cyclic input models are rejected (an authoring smell the
conventions already discourage).

Stability: Experimental.
"""

from __future__ import annotations

from typing import Any

from zygos.providers.types import ToolSchema
from zygos.tools.types import Tool, ToolMeta


def _inline(node: Any, defs: dict[str, Any], seen: frozenset[str]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            name = node["$ref"].split("/")[-1]
            if name in seen:
                raise ValueError(f"cyclic $ref in tool input model: {name!r}")
            if name not in defs:
                raise ValueError(f"unresolvable $ref: {node['$ref']!r}")
            resolved = _inline(defs[name], defs, seen | {name})
            siblings = {k: _inline(v, defs, seen) for k, v in node.items() if k != "$ref"}
            if siblings:
                return {**resolved, **siblings}   # sibling keys (e.g. description) win
            return resolved
        return {k: _inline(v, defs, seen) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_inline(v, defs, seen) for v in node]
    return node


def _flatten(raw: dict[str, Any]) -> dict[str, Any]:
    """Inline `$defs` and draft-07 `definitions` ($ref targets) into one flat schema."""
    defs = {**raw.get("definitions", {}), **raw.get("$defs", {})}
    body = {k: v for k, v in raw.items() if k not in ("$defs", "definitions")}
    return _inline(body, defs, frozenset())


def check_input_schema(schema: dict[str, Any]) -> str | None:
    """Reason a server-supplied input schema can't be offered to a model, else None."""
    if schema.get("type") != "object":
        return "input schema root must be an object schema"
    try:
        _flatten(schema)
    except ValueError as exc:
        return str(exc)
    return None


def tool_schema(tool: Tool | ToolMeta) -> ToolSchema:
    meta = tool if isinstance(tool, ToolMeta) else tool.meta
    raw = meta.input_schema if meta.input_schema is not None else meta.input_model.model_json_schema()
    parameters = _flatten(raw)
    return ToolSchema(name=meta.name, description=meta.description, parameters=parameters)
