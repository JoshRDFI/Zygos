"""ToolService routes MCP tools (meta.server set) through the MCP gate; built-ins unchanged."""

from __future__ import annotations

import time

from pydantic import BaseModel

from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.tools import BaseTool, PermissionPolicy, Rule, ToolCall, ToolContext, ToolMeta, ToolService
from zygos.tools.permissions import PermissionResolver


class _In(BaseModel):
    x: int = 0


class Builtin(BaseTool):
    meta = ToolMeta(name="builtin", description="d", input_model=_In, permission="ask")

    async def execute(self, input, ctx: ToolContext):
        return "ran"


class FakeMcp(BaseTool):
    def __init__(self) -> None:
        self.meta = ToolMeta(
            name="archon__find_tasks", description="[archon] Find tasks.",
            input_schema={"type": "object"}, server="archon", server_tool="find_tasks",
            permission="ask",
        )
        self.calls = 0

    async def execute(self, input, ctx: ToolContext):
        self.calls += 1
        return {"got": input}


class SlowResolver:
    """Would hang a turn for 120 s if an MCP tool ever reached it."""

    def __init__(self) -> None:
        self.asked = 0

    async def resolve(self, req, ctx):
        self.asked += 1
        import asyncio

        await asyncio.sleep(120)
        return "deny"


class Allow:
    async def resolve(self, req, ctx):
        return "allow"


def _ctx():
    return root_context(InProcessEventBus())


async def test_untrusted_mcp_tool_denied_immediately_with_message():
    resolver = SlowResolver()
    assert isinstance(resolver, PermissionResolver)
    tool = FakeMcp()
    for svc in (
        ToolService(resolver=resolver),  # no gate -> not trusted
        ToolService(resolver=resolver, mcp_gate=lambda meta: "not_trusted"),
    ):
        svc.register(tool)
        t0 = time.monotonic()
        res = await svc.execute(ToolCall(tool="archon__find_tasks", args={"q": 1}), _ctx())
        assert time.monotonic() - t0 < 1.0
        assert res.ok is False
        assert res.error_code == "tool_permission_denied"
        assert res.error_message == "not trusted yet — run: zygos mcp trust archon/find_tasks"
    assert resolver.asked == 0 and tool.calls == 0


async def test_mcp_gate_allow_and_deny():
    tool = FakeMcp()
    seen = []

    def gate(meta):
        seen.append(meta.name)
        return "allow"

    svc = ToolService(mcp_gate=gate)
    svc.register(tool)
    res = await svc.execute(ToolCall(tool="archon__find_tasks", args={"q": 1}), _ctx())
    assert res.ok and res.output == {"got": {"q": 1}} and seen == ["archon__find_tasks"]

    svc.bind_mcp_gate(lambda meta: "deny")
    res = await svc.execute(ToolCall(tool="archon__find_tasks"), _ctx())
    assert res.error_code == "tool_permission_denied" and res.error_message == "permission denied"


async def test_mcp_gate_also_guards_streams():
    svc = ToolService(mcp_gate=lambda meta: "not_trusted")
    svc.register(FakeMcp())
    chunks = [c async for c in svc.execute_stream(ToolCall(tool="archon__find_tasks"), _ctx())]
    assert len(chunks) == 1
    assert chunks[0].result.error_message == "not trusted yet — run: zygos mcp trust archon/find_tasks"


async def test_builtin_permission_unchanged():
    def gate(meta):
        raise AssertionError("built-ins never reach the MCP gate")

    svc = ToolService(resolver=Allow(), mcp_gate=gate)
    svc.register(Builtin())
    res = await svc.execute(ToolCall(tool="builtin"), _ctx())
    assert res.ok and res.output == "ran"

    denied = ToolService(policy=PermissionPolicy(rules=[Rule(pattern="builtin", decision="deny")]), mcp_gate=gate)
    denied.register(Builtin())
    res = await denied.execute(ToolCall(tool="builtin"), _ctx())
    assert res.error_code == "tool_permission_denied" and res.error_message == "permission denied"


class FailsWithMcpFallback(BaseTool):
    meta = ToolMeta(name="primary", description="d", input_model=_In, fallback="archon__find_tasks")

    async def execute(self, input, ctx: ToolContext):
        raise RuntimeError("primary broke")


async def test_mcp_fallback_goes_through_the_mcp_gate():
    for gate, allowed in ((lambda meta: "not_trusted", False), (lambda meta: "allow", True)):
        mcp = FakeMcp()
        svc = ToolService(mcp_gate=gate)
        svc.register(FailsWithMcpFallback())
        svc.register(mcp)
        res = await svc.execute(ToolCall(tool="primary", args={"x": 1}), _ctx())
        chunks = [c async for c in svc.execute_stream(ToolCall(tool="primary", args={"x": 1}), _ctx())]
        if allowed:
            assert res.ok and mcp.calls == 2
            assert chunks[-1].result.ok
        else:
            assert mcp.calls == 0
            assert res.error_message == "not trusted yet — run: zygos mcp trust archon/find_tasks"
            assert chunks[-1].result.error_message == res.error_message
