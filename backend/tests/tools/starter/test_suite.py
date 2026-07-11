"""M5 C3 Task 5 — starter suite exports + real permission gate end-to-end."""

import pytest

from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.tools.permissions import AllowingResolver, DenyingResolver
from zygos.tools.service import ToolService
from zygos.tools.starter import (
    HttpFetchTool,
    ReadFileTool,
    RunCommandTool,
    WriteFileTool,
)
from zygos.tools.types import ToolCall


def _ctx():
    return root_context(InProcessEventBus())


def test_exports():
    assert {t.__name__ for t in (ReadFileTool, WriteFileTool, HttpFetchTool, RunCommandTool)} == {
        "ReadFileTool", "WriteFileTool", "HttpFetchTool", "RunCommandTool",
    }


@pytest.mark.asyncio
async def test_allow_tool_runs_under_denying_resolver(tmp_path):
    """read_file is permission=allow -> never asks -> runs even with a DenyingResolver."""
    (tmp_path / "a.txt").write_text("hi")
    svc = ToolService(resolver=DenyingResolver())
    svc.register(ReadFileTool(root=tmp_path))
    res = await svc.execute(ToolCall(tool="read_file", args={"path": "a.txt"}), _ctx())
    assert res.ok is True
    assert res.output["content"] == "hi"


@pytest.mark.asyncio
async def test_ask_tool_denied_under_denying_resolver(tmp_path):
    svc = ToolService(resolver=DenyingResolver())
    svc.register(WriteFileTool(root=tmp_path))
    res = await svc.execute(
        ToolCall(tool="write_file", args={"path": "o.txt", "content": "x"}), _ctx()
    )
    assert res.ok is False
    assert res.error_code == "tool_permission_denied"
    assert not (tmp_path / "o.txt").exists()


@pytest.mark.asyncio
async def test_ask_tool_allowed_under_allowing_resolver(tmp_path):
    svc = ToolService(resolver=AllowingResolver())
    svc.register(WriteFileTool(root=tmp_path))
    res = await svc.execute(
        ToolCall(tool="write_file", args={"path": "o.txt", "content": "x"}), _ctx()
    )
    assert res.ok is True
    assert (tmp_path / "o.txt").read_text() == "x"


@pytest.mark.asyncio
async def test_run_command_streams_through_service(tmp_path):
    svc = ToolService(resolver=AllowingResolver())
    svc.register(RunCommandTool(root=tmp_path))
    call = ToolCall(tool="run_command", args={"argv": ["echo", "streamed"]})
    chunks = [c async for c in svc.execute_stream(call, _ctx())]
    content = "".join(c.content for c in chunks if c.kind == "content" and isinstance(c.content, str))
    assert "streamed" in content
    assert chunks[-1].kind == "result" and chunks[-1].result.ok is True
