"""M5 C3 Task 4 — run_command: sandbox, exit codes, streaming, timeout-kill."""

import asyncio
import sys

import pytest

from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.tools.executor import execute_tool, execute_tool_stream
from zygos.tools.starter.shell import RunCommandTool
from zygos.tools.types import ToolCall


def _ctx():
    return root_context(InProcessEventBus())


@pytest.mark.asyncio
async def test_run_echo(tmp_path):
    tool = RunCommandTool(root=tmp_path)
    res = await execute_tool(
        tool, ToolCall(tool="run_command", args={"argv": ["echo", "hello"]}), _ctx()
    )
    assert res.ok is True
    assert res.output["exit_code"] == 0
    assert res.output["stdout"].strip() == "hello"


@pytest.mark.asyncio
async def test_run_nonzero_exit(tmp_path):
    tool = RunCommandTool(root=tmp_path)
    res = await execute_tool(
        tool, ToolCall(tool="run_command", args={"argv": ["false"]}), _ctx()
    )
    assert res.ok is True          # a nonzero exit is a successful *tool* run
    assert res.output["exit_code"] == 1


@pytest.mark.asyncio
async def test_argv_is_not_a_shell(tmp_path):
    """A shell metacharacter is a literal argument, never interpreted."""
    tool = RunCommandTool(root=tmp_path)
    res = await execute_tool(
        tool, ToolCall(tool="run_command", args={"argv": ["echo", "a; rm -rf b"]}), _ctx()
    )
    assert res.output["stdout"].strip() == "a; rm -rf b"


@pytest.mark.asyncio
async def test_empty_argv_rejected(tmp_path):
    tool = RunCommandTool(root=tmp_path)
    res = await execute_tool(tool, ToolCall(tool="run_command", args={"argv": []}), _ctx())
    assert res.ok is False
    assert "argv" in res.error_message


@pytest.mark.asyncio
async def test_scrubbed_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "leak-me")
    tool = RunCommandTool(root=tmp_path)
    res = await execute_tool(
        tool,
        ToolCall(tool="run_command", args={"argv": [sys.executable, "-c",
                 "import os; print(os.environ.get('SECRET_TOKEN', 'ABSENT'))"]}),
        _ctx(),
    )
    assert res.output["stdout"].strip() == "ABSENT"


@pytest.mark.asyncio
async def test_stream_yields_stdout_then_terminal(tmp_path):
    tool = RunCommandTool(root=tmp_path)
    code = "import time\nfor i in range(3):\n print(i, flush=True)\n time.sleep(0.02)"
    call = ToolCall(tool="run_command", args={"argv": [sys.executable, "-u", "-c", code]})
    chunks = [c async for c in execute_tool_stream(tool, call, _ctx())]
    content = [c.content for c in chunks if c.kind == "content" and isinstance(c.content, str)]
    terminal = [c for c in chunks if c.kind == "result"]
    assert "".join(content).split() == ["0", "1", "2"]
    assert len(terminal) == 1
    assert terminal[0].result.ok is True
    assert terminal[0].result.output["exit_code"] == 0


@pytest.mark.asyncio
async def test_timeout_kills_child(tmp_path):
    """meta.timeout_s expires -> tool_timeout AND the child is killed (never writes marker)."""
    marker = tmp_path / "done.txt"
    tool = RunCommandTool(root=tmp_path, timeout_s=0.3)
    code = f"import time; time.sleep(5); open({str(marker)!r}, 'w').close()"
    call = ToolCall(tool="run_command", args={"argv": [sys.executable, "-c", code]})
    res = await execute_tool(tool, call, _ctx())
    assert res.ok is False
    assert res.error_code == "tool_timeout"
    await asyncio.sleep(0.4)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_stream_timeout_kills_child(tmp_path):
    """Streaming deadline (via Task 1 aclose fix) runs the finally -> child killed."""
    marker = tmp_path / "done.txt"
    tool = RunCommandTool(root=tmp_path, timeout_s=0.3)
    code = (
        "import time; print('go', flush=True); time.sleep(5); "
        f"open({str(marker)!r}, 'w').close()"
    )
    call = ToolCall(tool="run_command", args={"argv": [sys.executable, "-u", "-c", code]})
    chunks = [c async for c in execute_tool_stream(tool, call, _ctx())]
    assert any(c.kind == "content" for c in chunks)
    assert chunks[-1].kind == "result" and chunks[-1].result.error_code == "tool_timeout"
    await asyncio.sleep(0.4)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_cwd_escape_rejected(tmp_path):
    tool = RunCommandTool(root=tmp_path)
    res = await execute_tool(
        tool, ToolCall(tool="run_command", args={"argv": ["echo", "x"], "cwd": ".."}), _ctx()
    )
    assert res.ok is False
    assert "escapes root" in res.error_message
