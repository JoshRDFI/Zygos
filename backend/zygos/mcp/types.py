"""Plain data types for MCP servers. Pure: no I/O, no SDK import."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ServerSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    transport: Literal["stdio", "http", "sse"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    url: str | None = None
    env_names: list[str] = Field(default_factory=list)
    header_names: list[str] = Field(default_factory=list)
    timeout_s: float = 120.0
    extra: dict[str, Any] = Field(default_factory=dict)


class ParsedServer(BaseModel):
    """A parsed server plus its secret values (handle -> value). Values never appear in repr."""

    model_config = ConfigDict(frozen=True)

    spec: ServerSpec
    secrets: dict[str, str] = Field(default_factory=dict, repr=False)


class SeenTool(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    input_schema: dict[str, Any]
    annotations: dict[str, Any] = Field(default_factory=dict)
    problem: str | None = None
