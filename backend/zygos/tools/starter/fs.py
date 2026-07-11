"""File tools: read_file, write_file. Confined to a constructor-injected root.

Confinement is symlink-safe: the resolved real path must stay under the resolved root.
Stability: Experimental.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from zygos.errors import ToolError
from zygos.tools.types import BaseTool, ToolContext, ToolMeta


def _under_root(root: Path, candidate: Path, rel: str) -> Path:
    root_r = root.resolve()
    if candidate != root_r and root_r not in candidate.parents:
        raise ToolError(f"path escapes root: {rel!r}")
    return candidate


def _resolve_existing(root: Path, rel: str) -> Path:
    root_r = root.resolve()
    return _under_root(root, (root_r / rel).resolve(), rel)


def _resolve_target(root: Path, rel: str) -> Path:
    """Resolve a possibly-nonexistent target: its parent must exist and stay under root."""
    root_r = root.resolve()
    target = root_r / rel
    parent = target.parent.resolve()
    _under_root(root, parent, rel)
    if not target.name:
        raise ToolError(f"not a file path: {rel!r}")
    return parent / target.name


class ReadFileInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    path: str


class ReadFileOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    content: str
    size: int
    truncated: bool


class ReadFileTool(BaseTool):
    def __init__(self, root: Path, *, max_bytes: int = 1_048_576) -> None:
        self._root = Path(root)
        self._max_bytes = max_bytes
        self.meta = ToolMeta(
            name="read_file",
            description="Read a UTF-8 text file confined to the tool's root directory.",
            input_model=ReadFileInput,
            output_model=ReadFileOutput,
            permission="allow",
        )

    async def execute(self, input: ReadFileInput, ctx: ToolContext) -> dict:
        target = _resolve_existing(self._root, input.path)
        if not target.is_file():
            raise ToolError(f"not a file: {input.path!r}")
        with target.open("rb") as fh:
            data = fh.read(self._max_bytes + 1)
        truncated = len(data) > self._max_bytes
        if truncated:
            size = target.stat().st_size
            data = data[: self._max_bytes]
        else:
            size = len(data)
        return {
            "content": data.decode("utf-8", errors="replace"),
            "size": size,
            "truncated": truncated,
        }


class WriteFileInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    path: str
    content: str
    mode: Literal["create", "overwrite", "append"] = "create"


class WriteFileOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    path: str
    bytes_written: int


class WriteFileTool(BaseTool):
    def __init__(self, root: Path, *, max_bytes: int = 1_048_576) -> None:
        self._root = Path(root)
        self._max_bytes = max_bytes
        self.meta = ToolMeta(
            name="write_file",
            description="Write a UTF-8 text file confined to the tool's root directory.",
            input_model=WriteFileInput,
            output_model=WriteFileOutput,
            permission="ask",
        )

    async def execute(self, input: WriteFileInput, ctx: ToolContext) -> dict:
        target = _resolve_target(self._root, input.path)
        payload = input.content.encode("utf-8")
        if len(payload) > self._max_bytes:
            raise ToolError(f"content exceeds max_bytes ({self._max_bytes})")
        if input.mode == "create" and target.exists():
            raise ToolError(f"file exists: {input.path!r}")
        open_mode = {"create": "xb", "overwrite": "wb", "append": "ab"}[input.mode]
        with target.open(open_mode) as fh:
            fh.write(payload)
        return {"path": str(target), "bytes_written": len(payload)}
