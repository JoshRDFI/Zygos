"""Parse a pasted ``mcpServers`` JSON and name tools. Pure: no I/O, no SDK import."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shlex
from typing import Any

from pydantic import ValidationError

from zygos.mcp.types import ParsedServer, ServerSpec
from zygos.secrets.handles import validate_handle
from zygos.secrets.types import InvalidHandle

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
_MAX_NAME = 64
_KNOWN = {"command", "args", "cwd", "url", "type", "env", "headers", "timeout_s"}
_MAX_TIMEOUT_S = 600.0


class McpConfigError(ValueError):
    """The pasted configuration cannot be used. Never carries secret values."""


def clean_part(text: str) -> str:
    return _UNSAFE.sub("_", text)


def zygos_tool_name(server: str, tool: str) -> str:
    name = f"{clean_part(server)}__{clean_part(tool)}"
    if len(name) <= _MAX_NAME:
        return name
    digest = hashlib.sha256(f"{server}/{tool}".encode()).hexdigest()[:8]
    return f"{name[:55]}_{digest}"


def check_server_names(new: list[str], existing: list[str]) -> list[str]:
    problems: list[str] = []
    seen: dict[str, str] = {}
    for raw in new:
        if raw in seen.values():
            continue
        cleaned = clean_part(raw)
        if cleaned in seen:
            problems.append(f"server names {seen[cleaned]!r} and {raw!r} both become {cleaned!r}; rename one")
        else:
            seen[cleaned] = raw
    for raw in new:
        cleaned = clean_part(raw)
        for other in existing:
            if other != raw and clean_part(other) == cleaned:
                problems.append(f"server name {raw!r} collides with existing {other!r} (both become {cleaned!r})")
    return problems


def address(spec: ServerSpec) -> str:
    """Where a server is: its URL, or for a local one its command line (args included;
    never its env values)."""
    if spec.transport == "stdio":
        return " ".join(shlex.quote(p) for p in [spec.command or "", *spec.args])
    return spec.url or ""


def status_word(transport: str, status: str) -> str:
    """A recorded server status in words — the same in ``zygos mcp list``, doctor and inspect."""
    if status == "not_started":
        return "not started — zygos serve starts it" if transport == "stdio" else "not contacted yet"
    return status.replace("_", " ")


def describe(spec: ServerSpec) -> str:
    if spec.transport == "stdio":
        return f"This runs `{address(spec)}` on this machine as you"
    suffix = " (deprecated transport)" if spec.transport == "sse" else ""
    return f"This connects to {spec.url}{suffix}"


def parse_servers(text: str) -> list[ParsedServer]:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise McpConfigError(f"not valid JSON: {exc}") from None
    if isinstance(data, dict) and "mcpServers" in data:
        data = data["mcpServers"]
    if not isinstance(data, dict) or not data:
        raise McpConfigError("expected a mapping of server name to server settings")
    return [_parse_one(str(name), cfg) for name, cfg in data.items()]


def _strings(server: str, field: str, value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise McpConfigError(f"server {server!r}: {field} must be a mapping")
    for key, val in value.items():
        if not isinstance(val, str):
            raise McpConfigError(f"server {server!r}: {field} {key!r} must be a string")
    return value


def _handle(server: str, kind: str, name: str) -> str:
    handle = f"mcp:{server}:{kind}:{name}"
    try:
        return validate_handle(handle)
    except InvalidHandle:
        raise McpConfigError(
            f"server {server!r}: {kind} name {name!r} (or the server name) cannot form a secret handle; "
            "names must not contain ':' or whitespace"
        ) from None


def _parse_one(name: str, cfg: Any) -> ParsedServer:
    if "__" in clean_part(name):
        raise McpConfigError(
            f"server {name!r}: '__' is reserved as the server/tool separator; rename the server"
        )
    if not isinstance(cfg, dict):
        raise McpConfigError(f"server {name!r}: settings must be a mapping")
    command, url, kind = cfg.get("command"), cfg.get("url"), cfg.get("type")
    if command is not None and not isinstance(command, str):
        raise McpConfigError(f"server {name!r}: command must be a string")
    if url is not None and not isinstance(url, str):
        raise McpConfigError(f"server {name!r}: url must be a string")
    args = cfg.get("args", [])
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise McpConfigError(f"server {name!r}: args must be a list of strings")
    cwd = cfg.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise McpConfigError(f"server {name!r}: cwd must be a string")
    env = _strings(name, "env", cfg.get("env", {}))
    headers = _strings(name, "headers", cfg.get("headers", {}))
    if command:
        transport = "stdio"
    elif url:
        if kind == "sse":
            transport = "sse"
        elif kind in (None, "http", "streamable-http"):
            transport = "http"
        else:
            raise McpConfigError(f"server {name!r}: unsupported type {kind!r}")
    else:
        raise McpConfigError(f"server {name!r}: needs a 'command' (local) or a 'url' (remote)")
    secrets = {_handle(name, "env", k): v for k, v in env.items()}
    secrets.update({_handle(name, "header", k): v for k, v in headers.items()})
    extra = {k: v for k, v in cfg.items() if k not in _KNOWN}
    kwargs: dict[str, Any] = {}
    if "timeout_s" in cfg:
        kwargs["timeout_s"] = check_timeout(name, cfg["timeout_s"])
    try:
        spec = ServerSpec(
            name=name, transport=transport, command=command or None, args=args, cwd=cwd,
            url=url or None, env_names=list(env), header_names=list(headers), extra=extra, **kwargs,
        )
    except ValidationError as exc:
        raise McpConfigError(f"server {name!r}: {validation_reason(exc)}") from None
    return ParsedServer(spec=spec, secrets=secrets)


def check_timeout(server: str, value: Any) -> float:
    """A per-call timeout: a finite number of seconds, above 0 and at most 600."""
    ok = (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value) and 0 < value <= _MAX_TIMEOUT_S
    )
    if not ok:
        raise McpConfigError(
            f"server {server!r}: timeout_s must be a number of seconds above 0 and at most {_MAX_TIMEOUT_S:g}"
        )
    return float(value)


def validation_reason(exc: ValidationError) -> str:
    """The first problem as ``field: message`` — never the rejected value (it may be a secret)."""
    first = exc.errors()[0]
    field = ".".join(str(part) for part in first["loc"]) or "value"
    return f"{field}: {first['msg']}"
