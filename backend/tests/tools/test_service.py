"""M5 C1 Task 5 — ToolService facade."""

import pytest
from pydantic import BaseModel

from zygos.errors import ToolNotFound
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.tools import (
    BaseTool,
    ToolCall,
    ToolContext,
    ToolMeta,
    ToolService,
    ToolServiceSnapshot,
)


class _In(BaseModel):
    x: int


class _Out(BaseModel):
    y: int


class EchoTool(BaseTool):
    meta = ToolMeta(name="echo", description="d", input_model=_In, output_model=_Out)

    async def execute(self, input: _In, ctx: ToolContext) -> _Out:
        return _Out(y=input.x)


def _ctx():
    return root_context(InProcessEventBus())


@pytest.mark.asyncio
async def test_execute_delegates_and_returns_result():
    svc = ToolService()
    svc.register(EchoTool())
    res = await svc.execute(ToolCall(tool="echo", args={"x": 7}), _ctx())
    assert res.ok is True and res.output == _Out(y=7)


@pytest.mark.asyncio
async def test_unknown_tool_raises_tool_not_found():
    svc = ToolService()
    with pytest.raises(ToolNotFound):
        await svc.execute(ToolCall(tool="ghost"), _ctx())


def test_snapshot_lists_registered_metas():
    svc = ToolService()
    svc.register(EchoTool())
    snap = svc.snapshot()
    assert isinstance(snap, ToolServiceSnapshot)
    assert [m.name for m in snap.registered] == ["echo"]


def test_snapshot_is_pure():
    svc = ToolService()
    svc.register(EchoTool())
    svc.snapshot()
    svc.snapshot()
    assert [m.name for m in svc.snapshot().registered] == ["echo"]
