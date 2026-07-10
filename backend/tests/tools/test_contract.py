"""M5 C1 Task 2 — Tool Protocol + BaseTool defaults."""

import pytest
from pydantic import BaseModel

from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.tools.types import BaseTool, Tool, ToolContext, ToolMeta, VerifyResult


class _In(BaseModel):
    x: int


class _Out(BaseModel):
    y: int


def _ctx(tool: str) -> ToolContext:
    root = root_context(InProcessEventBus())
    return ToolContext(exec=root.child(span_id="c1"), tool=tool, call_id="c1")


class EchoTool(BaseTool):
    meta = ToolMeta(name="echo", description="echo x as y", input_model=_In, output_model=_Out)

    async def execute(self, input: _In, ctx: ToolContext) -> _Out:
        return _Out(y=input.x)


class NoOutputTool(BaseTool):
    meta = ToolMeta(name="noout", description="no output model", input_model=_In)

    async def execute(self, input: _In, ctx: ToolContext) -> str:
        return "anything"


@pytest.mark.asyncio
async def test_basetool_execute_runs():
    tool = EchoTool()
    out = await tool.execute(_In(x=3), _ctx("echo"))
    assert out == _Out(y=3)


def test_basetool_prepare_and_cleanup_are_noops():
    tool = EchoTool()
    assert tool.prepare(_ctx("echo")) is None
    assert tool.cleanup(_ctx("echo")) is None


def test_default_verify_passes_valid_output():
    tool = EchoTool()
    vr = tool.verify(_Out(y=1), _ctx("echo"))
    assert isinstance(vr, VerifyResult) and vr.passed is True


def test_default_verify_fails_invalid_output():
    tool = EchoTool()
    vr = tool.verify({"y": "not-an-int-and-wrong-shape", "z": 9}, _ctx("echo"))
    assert vr.passed is False and vr.reason


def test_default_verify_passes_when_no_output_model():
    tool = NoOutputTool()
    vr = tool.verify("anything", _ctx("noout"))
    assert vr.passed is True


def test_basetool_satisfies_tool_protocol():
    assert isinstance(EchoTool(), Tool)
