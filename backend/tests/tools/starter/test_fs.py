"""M5 C3 Task 2 — read_file / write_file confinement + behavior."""

import pytest

from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.tools.starter.fs import ReadFileTool, WriteFileTool
from zygos.tools.types import ToolCall
from zygos.tools.executor import execute_tool


def _ctx():
    return root_context(InProcessEventBus())


@pytest.mark.asyncio
async def test_read_file_happy(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    tool = ReadFileTool(root=tmp_path)
    res = await execute_tool(tool, ToolCall(tool="read_file", args={"path": "a.txt"}), _ctx())
    assert res.ok is True
    assert res.output == {"content": "hello", "size": 5, "truncated": False}


@pytest.mark.asyncio
async def test_read_file_truncates(tmp_path):
    (tmp_path / "big.txt").write_text("abcdefghij")
    tool = ReadFileTool(root=tmp_path, max_bytes=4)
    res = await execute_tool(tool, ToolCall(tool="read_file", args={"path": "big.txt"}), _ctx())
    assert res.ok is True
    assert res.output == {"content": "abcd", "size": 10, "truncated": True}


@pytest.mark.asyncio
async def test_read_file_traversal_rejected(tmp_path):
    tool = ReadFileTool(root=tmp_path)
    res = await execute_tool(tool, ToolCall(tool="read_file", args={"path": "../secret"}), _ctx())
    assert res.ok is False
    assert res.error_code == "tool_error"
    assert "escapes root" in res.error_message


@pytest.mark.asyncio
async def test_read_file_absolute_rejected(tmp_path):
    tool = ReadFileTool(root=tmp_path)
    res = await execute_tool(tool, ToolCall(tool="read_file", args={"path": "/etc/passwd"}), _ctx())
    assert res.ok is False
    assert res.error_code == "tool_error"


@pytest.mark.asyncio
async def test_read_file_symlink_escape_rejected(tmp_path):
    outside = tmp_path.parent / "outside_target.txt"
    outside.write_text("secret")
    (tmp_path / "link").symlink_to(outside)
    tool = ReadFileTool(root=tmp_path)
    res = await execute_tool(tool, ToolCall(tool="read_file", args={"path": "link"}), _ctx())
    assert res.ok is False
    assert "escapes root" in res.error_message


@pytest.mark.asyncio
async def test_write_file_create(tmp_path):
    tool = WriteFileTool(root=tmp_path)
    res = await execute_tool(
        tool, ToolCall(tool="write_file", args={"path": "out.txt", "content": "hi"}), _ctx()
    )
    assert res.ok is True
    assert res.output["bytes_written"] == 2
    assert (tmp_path / "out.txt").read_text() == "hi"


@pytest.mark.asyncio
async def test_write_file_create_conflict(tmp_path):
    (tmp_path / "out.txt").write_text("old")
    tool = WriteFileTool(root=tmp_path)
    res = await execute_tool(
        tool, ToolCall(tool="write_file", args={"path": "out.txt", "content": "new"}), _ctx()
    )
    assert res.ok is False
    assert "exists" in res.error_message


@pytest.mark.asyncio
async def test_write_file_append(tmp_path):
    (tmp_path / "out.txt").write_text("a")
    tool = WriteFileTool(root=tmp_path)
    res = await execute_tool(
        tool,
        ToolCall(tool="write_file", args={"path": "out.txt", "content": "b", "mode": "append"}),
        _ctx(),
    )
    assert res.ok is True
    assert (tmp_path / "out.txt").read_text() == "ab"


@pytest.mark.asyncio
async def test_write_file_traversal_rejected(tmp_path):
    tool = WriteFileTool(root=tmp_path)
    res = await execute_tool(
        tool, ToolCall(tool="write_file", args={"path": "../evil.txt", "content": "x"}), _ctx()
    )
    assert res.ok is False
    assert "escapes root" in res.error_message


@pytest.mark.asyncio
async def test_write_file_symlink_escape_rejected(tmp_path):
    outside = tmp_path.parent / "outside_write_target.txt"
    outside.write_text("original")
    (tmp_path / "link").symlink_to(outside)
    tool = WriteFileTool(root=tmp_path)
    for mode in ("overwrite", "append"):
        res = await execute_tool(
            tool,
            ToolCall(tool="write_file", args={"path": "link", "content": "HACKED", "mode": mode}),
            _ctx(),
        )
        assert res.ok is False
        assert "symlink" in res.error_message or "escapes root" in res.error_message
    assert outside.read_text() == "original"   # never written through the symlink


@pytest.mark.asyncio
async def test_write_file_oversize_rejected(tmp_path):
    tool = WriteFileTool(root=tmp_path, max_bytes=3)
    res = await execute_tool(
        tool, ToolCall(tool="write_file", args={"path": "out.txt", "content": "toolong"}), _ctx()
    )
    assert res.ok is False
    assert "max_bytes" in res.error_message
