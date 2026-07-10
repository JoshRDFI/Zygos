"""M5 C2 Task 8 — RFC-0002 invariants: tools emit no events and never trip the shared token."""

import pytest
from pydantic import BaseModel

from zygos.runtime.context import root_context
from zygos.runtime.events import Event, InProcessEventBus
from zygos.tools import (
    AllowingResolver,
    DenyingResolver,
    PermissionPolicy,
    RetryPolicy,
    Rule,
    ToolChunk,
    ToolService,
    execute_tool_stream,
)
from zygos.tools.types import BaseTool, ToolCall, ToolContext, ToolMeta


class _In(BaseModel):
    x: int


class _Out(BaseModel):
    y: int


class EchoTool(BaseTool):
    meta = ToolMeta(name="echo", description="d", input_model=_In, output_model=_Out)

    async def execute(self, input: _In, ctx: ToolContext) -> _Out:
        return _Out(y=input.x)


def test_public_exports_present():
    # Import-time surface check: the names above must be importable from zygos.tools.
    assert all(x is not None for x in (
        PermissionPolicy, Rule, DenyingResolver, AllowingResolver, RetryPolicy,
        ToolChunk, ToolService, execute_tool_stream))


@pytest.mark.asyncio
async def test_execute_emits_no_events():
    bus = InProcessEventBus()
    received: list[Event] = []

    async def recorder(event: Event) -> None:
        received.append(event)

    bus.subscribe(recorder)
    ctx = root_context(bus)
    svc = ToolService()
    svc.register(EchoTool())
    await svc.execute(ToolCall(tool="echo", args={"x": 1}), ctx)
    assert received == []   # puller invariant: tools emit nothing


@pytest.mark.asyncio
async def test_tools_never_trip_shared_cancel_token():
    ctx = root_context(InProcessEventBus())
    svc = ToolService()
    svc.register(EchoTool())
    await svc.execute(ToolCall(tool="echo", args={"x": 1}), ctx)
    assert ctx.cancelled is False   # timeout uses wait_for's private scope, not the shared token
