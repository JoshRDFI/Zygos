"""M5 C1 Task 1 — error taxonomy + data models."""

import pytest
from pydantic import BaseModel

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
