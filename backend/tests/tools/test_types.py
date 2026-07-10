"""M5 C1 Task 1 — error taxonomy + data models."""

import dataclasses
import pytest
from pydantic import BaseModel, ValidationError

from zygos.errors import ToolError, ToolNotFound, ZygosError
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.tools.types import ToolCall, ToolContext, ToolMeta, ToolResult, VerifyResult


class _In(BaseModel):
    x: int


class _Out(BaseModel):
    y: int


def test_tool_errors_have_stable_codes():
    assert issubclass(ToolError, ZygosError)
    assert issubclass(ToolNotFound, ToolError)
    assert ToolError.code == "tool_error"
    assert ToolNotFound.code == "tool_not_found"


def test_toolmeta_holds_model_types():
    meta = ToolMeta(name="echo", description="d", input_model=_In, output_model=_Out)
    assert meta.input_model is _In
    assert meta.output_model is _Out
    meta_no_out = ToolMeta(name="e2", description="d", input_model=_In)
    assert meta_no_out.output_model is None


def test_toolcall_defaults():
    call = ToolCall(tool="echo")
    assert call.args == {}
    assert call.call_id is None


def test_toolresult_ok_and_failed_constructors():
    good = ToolResult.succeeded(tool="echo", call_id="c1", output={"y": 1})
    assert good.ok is True and good.output == {"y": 1}
    assert good.error_code is None

    bad = ToolResult.failed(
        tool="echo", call_id="c1", error_code="tool_execution_failed", error_message="boom"
    )
    assert bad.ok is False and bad.output is None
    assert bad.error_code == "tool_execution_failed" and bad.error_message == "boom"


def test_verifyresult():
    assert VerifyResult(passed=True).reason is None
    assert VerifyResult(passed=False, reason="bad").reason == "bad"


def test_toolcontext_derives_from_execution_context():
    parent = root_context(InProcessEventBus())
    child = parent.child(span_id="call-123")
    tctx = ToolContext(exec=child, tool="echo", call_id="call-123")
    assert tctx.call_id == "call-123"
    assert tctx.tool == "echo"
    assert tctx.cancelled is False
    parent._cancel.trip()  # same CancelToken threads through child
    assert tctx.cancelled is True


def test_value_model_is_frozen():
    result = ToolResult.succeeded(tool="echo", call_id="c1", output={"y": 1})
    with pytest.raises(ValidationError):
        result.ok = False


def test_toolcontext_is_frozen():
    parent = root_context(InProcessEventBus())
    tctx = ToolContext(exec=parent.child(span_id="c1"), tool="echo", call_id="c1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        tctx.tool = "changed"


# M5 C2 Task 2 tests below
from typing import Any

from zygos.tools.types import RetryPolicy, ToolChunk, ToolResult


def test_retry_policy_defaults_single_attempt():
    r = RetryPolicy()
    assert (r.attempts, r.backoff_ms, r.multiplier) == (1, 250, 2.0)


def test_tool_meta_resilience_field_defaults():
    from pydantic import BaseModel

    class _In(BaseModel):
        x: int

    from zygos.tools.types import ToolMeta

    m = ToolMeta(name="t", description="d", input_model=_In)
    assert m.retry == RetryPolicy()
    assert m.timeout_s is None
    assert m.permission == "allow"
    assert m.fallback is None


def test_tool_chunk_content_and_result_kinds():
    c = ToolChunk(kind="content", content=42)
    assert c.kind == "content" and c.content == 42 and c.result is None
    res = ToolResult.succeeded(tool="t", call_id="1", output=7)
    term = ToolChunk(kind="result", result=res)
    assert term.kind == "result" and term.result == res


def test_basetool_default_execute_stream_yields_one_value():
    import asyncio

    from pydantic import BaseModel

    from zygos.tools.types import BaseTool, ToolContext, ToolMeta

    class _In(BaseModel):
        x: int

    class _T(BaseTool):
        meta = ToolMeta(name="t", description="d", input_model=_In)

        async def execute(self, input: _In, ctx: ToolContext) -> int:
            return input.x + 1

    async def _run():
        return [v async for v in _T().execute_stream(_In(x=4), ctx=None)]  # ctx unused by default

    assert asyncio.run(_run()) == [5]
