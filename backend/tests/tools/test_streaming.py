"""M5 C2 Task 6 — streaming executor: chunks + terminal result, started-flag retry cutoff."""

import asyncio

import pytest
from pydantic import BaseModel

from zygos.errors import ToolError
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.tools.executor import execute_tool_stream
from zygos.tools.types import BaseTool, RetryPolicy, ToolCall, ToolContext, ToolMeta


class _In(BaseModel):
    x: int


class _Out(BaseModel):
    y: int


def _ctx():
    return root_context(InProcessEventBus())


async def _collect(agen):
    return [c async for c in agen]


class _Retry(ToolError):
    code = "x_retry"
    retryable = True


class StreamTool(BaseTool):
    meta = ToolMeta(name="stream", description="d", input_model=_In, output_model=_Out)

    def __init__(self):
        self.cleanup_calls = 0

    async def execute_stream(self, input: _In, ctx: ToolContext):
        for i in range(1, input.x + 1):
            yield _Out(y=i)

    def cleanup(self, ctx: ToolContext) -> None:
        self.cleanup_calls += 1


class EchoTool(BaseTool):
    """No execute_stream override -> exercises the BaseTool auto-wrap."""

    meta = ToolMeta(name="echo", description="d", input_model=_In, output_model=_Out)

    async def execute(self, input: _In, ctx: ToolContext) -> _Out:
        return _Out(y=input.x)


class FlakyStreamTool(BaseTool):
    """Fails (retryable) before yielding on the first N attempts, then streams one value."""

    def __init__(self, *, fail_times: int, attempts: int):
        self.meta = ToolMeta(name="flakystream", description="d", input_model=_In,
                             output_model=_Out,
                             retry=RetryPolicy(attempts=attempts, backoff_ms=250, multiplier=2.0))
        self._fail_times = fail_times
        self.attempts_started = 0

    async def execute_stream(self, input: _In, ctx: ToolContext):
        self.attempts_started += 1
        if self.attempts_started <= self._fail_times:
            raise _Retry("transient before first chunk")
        yield _Out(y=input.x)


class PostChunkFailTool(BaseTool):
    """Yields one chunk, THEN raises retryable — must NOT retry (cannot un-yield)."""

    def __init__(self, attempts: int):
        self.meta = ToolMeta(name="postfail", description="d", input_model=_In, output_model=_Out,
                             retry=RetryPolicy(attempts=attempts))
        self.attempts_started = 0

    async def execute_stream(self, input: _In, ctx: ToolContext):
        self.attempts_started += 1
        yield _Out(y=1)
        raise _Retry("after first chunk")


class StalledStreamTool(BaseTool):
    meta = ToolMeta(name="stalled", description="d", input_model=_In, output_model=_Out,
                    timeout_s=0.01)

    def __init__(self):
        self.cleanup_calls = 0

    async def execute_stream(self, input: _In, ctx: ToolContext):
        await asyncio.sleep(1.0)
        yield _Out(y=1)

    def cleanup(self, ctx: ToolContext) -> None:
        self.cleanup_calls += 1


def _fake_sleep():
    calls: list[float] = []

    async def sleep(s: float) -> None:
        calls.append(s)

    return sleep, calls


@pytest.mark.asyncio
async def test_stream_yields_content_then_terminal_result():
    tool = StreamTool()
    chunks = await _collect(execute_tool_stream(tool, ToolCall(tool="stream", args={"x": 3}), _ctx()))
    assert [c.kind for c in chunks] == ["content", "content", "content", "result"]
    assert [c.content for c in chunks[:3]] == [_Out(y=1), _Out(y=2), _Out(y=3)]
    assert chunks[-1].result.ok is True and chunks[-1].result.output == _Out(y=3)
    assert tool.cleanup_calls == 1


@pytest.mark.asyncio
async def test_non_streaming_tool_auto_wraps_to_one_content_chunk():
    chunks = await _collect(execute_tool_stream(EchoTool(), ToolCall(tool="echo", args={"x": 5}), _ctx()))
    assert [c.kind for c in chunks] == ["content", "result"]
    assert chunks[0].content == _Out(y=5)
    assert chunks[-1].result.ok is True


@pytest.mark.asyncio
async def test_retry_before_first_chunk():
    tool = FlakyStreamTool(fail_times=1, attempts=2)
    sleep, slept = _fake_sleep()
    chunks = await _collect(
        execute_tool_stream(tool, ToolCall(tool="flakystream", args={"x": 7}), _ctx(), sleep=sleep)
    )
    assert chunks[-1].result.ok is True
    assert tool.attempts_started == 2 and slept == [0.25]
    assert sum(1 for c in chunks if c.kind == "content") == 1  # content began exactly once


@pytest.mark.asyncio
async def test_no_retry_after_first_chunk():
    tool = PostChunkFailTool(attempts=3)
    sleep, slept = _fake_sleep()
    chunks = await _collect(
        execute_tool_stream(tool, ToolCall(tool="postfail", args={"x": 1}), _ctx(), sleep=sleep)
    )
    assert tool.attempts_started == 1 and slept == []       # started -> no retry
    assert chunks[0].kind == "content"
    assert chunks[-1].kind == "result" and chunks[-1].result.ok is False


@pytest.mark.asyncio
async def test_stream_timeout_terminal_and_cleanup_ran():
    tool = StalledStreamTool()
    chunks = await _collect(execute_tool_stream(tool, ToolCall(tool="stalled", args={"x": 1}), _ctx()))
    assert chunks[-1].kind == "result" and chunks[-1].result.error_code == "tool_timeout"
    assert tool.cleanup_calls == 1
