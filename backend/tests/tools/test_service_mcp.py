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


class Allow:
    async def resolve(self, req, ctx):
        return "allow"


def _ctx():
    return root_context(InProcessEventBus())


REFUSAL = "not trusted — answer the prompt in the web page, or run: zygos mcp trust archon/find_tasks"


class Recording:
    """Records each request; answers with a fixed decision."""

    def __init__(self, decision: str = "deny") -> None:
        self.decision = decision
        self.requests = []

    async def resolve(self, req, ctx):
        self.requests.append(req)
        return self.decision


async def test_untrusted_mcp_tool_denied_immediately_with_message():
    # With nobody to answer (the headless resolver denies), the refusal is immediate.
    resolver = Recording("deny")
    assert isinstance(resolver, PermissionResolver)
    tool = FakeMcp()
    for svc in (
        ToolService(),  # no gate -> not trusted; default resolver denies
        ToolService(resolver=resolver, mcp_gate=lambda meta: "not_trusted"),
    ):
        svc.register(tool)
        t0 = time.monotonic()
        res = await svc.execute(ToolCall(tool="archon__find_tasks", args={"q": 1}), _ctx())
        assert time.monotonic() - t0 < 1.0
        assert res.ok is False
        assert res.error_code == "tool_permission_denied"
        assert res.error_message == REFUSAL
    assert len(resolver.requests) == 1 and tool.calls == 0


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
    assert chunks[0].result.error_message == REFUSAL


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
            assert res.error_message == REFUSAL
            assert chunks[-1].result.error_message == res.error_message


async def test_untrusted_mcp_tool_asks_resolver():
    resolver = Recording("allow")
    tool = FakeMcp()
    svc = ToolService(resolver=resolver, mcp_gate=lambda meta: "not_trusted")
    svc.bind_mcp_describe(lambda meta: {"server": "archon", "server_tool": "find_tasks", "can_trust": True})
    svc.register(tool)
    res = await svc.execute(ToolCall(tool="archon__find_tasks", args={"q": 1}), _ctx())
    assert res.ok and res.output == {"got": {"q": 1}} and tool.calls == 1
    [req] = resolver.requests
    assert req.tool == "archon__find_tasks" and req.args_summary == {"q": 1}
    assert req.details == {"server": "archon", "server_tool": "find_tasks", "can_trust": True}
    assert req.call_id == res.call_id


async def test_untrusted_mcp_tool_refused_with_hint_on_deny():
    tool = FakeMcp()
    svc = ToolService(resolver=Recording("deny"), mcp_gate=lambda meta: "not_trusted")
    svc.register(tool)
    res = await svc.execute(ToolCall(tool="archon__find_tasks"), _ctx())
    assert res.ok is False and res.error_code == "tool_permission_denied"
    assert res.error_message == REFUSAL
    assert tool.calls == 0


async def test_config_deny_never_asks():
    resolver = Recording("allow")
    tool = FakeMcp()
    svc = ToolService(resolver=resolver, mcp_gate=lambda meta: "deny")
    svc.register(tool)
    res = await svc.execute(ToolCall(tool="archon__find_tasks"), _ctx())
    chunks = [c async for c in svc.execute_stream(ToolCall(tool="archon__find_tasks"), _ctx())]
    assert res.error_message == "permission denied"
    assert chunks[-1].result.error_message == "permission denied"
    assert resolver.requests == [] and tool.calls == 0


async def test_broken_gate_never_asks():
    def gate(meta):
        raise RuntimeError("boom")

    resolver = Recording("allow")
    tool = FakeMcp()
    svc = ToolService(resolver=resolver, mcp_gate=gate)
    svc.register(tool)
    res = await svc.execute(ToolCall(tool="archon__find_tasks"), _ctx())
    assert res.ok is False and res.error_code == "tool_permission_denied"
    assert resolver.requests == [] and tool.calls == 0


async def test_mcp_fallback_asks_too():
    for decision, allowed in (("deny", False), ("allow", True)):
        resolver = Recording(decision)
        mcp = FakeMcp()
        svc = ToolService(resolver=resolver, mcp_gate=lambda meta: "not_trusted")
        svc.register(FailsWithMcpFallback())
        svc.register(mcp)
        res = await svc.execute(ToolCall(tool="primary", args={"x": 1}), _ctx())
        chunks = [c async for c in svc.execute_stream(ToolCall(tool="primary", args={"x": 1}), _ctx())]
        # The built-in primary is not gated by the resolver here (default policy allows);
        # only the MCP fallback asks, once per path.
        assert [r.tool for r in resolver.requests] == ["archon__find_tasks", "archon__find_tasks"]
        if allowed:
            assert res.ok and chunks[-1].result.ok and mcp.calls == 2
        else:
            assert mcp.calls == 0
            assert res.error_message == REFUSAL
            assert chunks[-1].result.error_message == REFUSAL


async def test_describe_failure_still_asks_with_empty_details():
    def describe(meta):
        raise RuntimeError("describe broke")

    resolver = Recording("allow")
    tool = FakeMcp()
    svc = ToolService(resolver=resolver, mcp_gate=lambda meta: "not_trusted")
    svc.bind_mcp_describe(describe)
    svc.register(tool)
    res = await svc.execute(ToolCall(tool="archon__find_tasks"), _ctx())
    assert res.ok and tool.calls == 1
    assert resolver.requests[0].details == {}

    # No describe bound at all: also empty details.
    resolver2 = Recording("deny")
    svc2 = ToolService(resolver=resolver2, mcp_gate=lambda meta: "not_trusted")
    svc2.register(FakeMcp())
    await svc2.execute(ToolCall(tool="archon__find_tasks"), _ctx())
    assert resolver2.requests[0].details == {}


async def test_fallback_prompt_has_its_own_id():
    resolver = Recording("allow")
    mcp = FakeMcp()
    svc = ToolService(resolver=resolver, mcp_gate=lambda meta: "not_trusted")
    svc.register(FailsWithMcpFallback())
    svc.register(mcp)
    res = await svc.execute(ToolCall(tool="primary", args={"x": 1}, call_id="c1"), _ctx())
    chunks = [c async for c in svc.execute_stream(ToolCall(tool="primary", call_id="c2"), _ctx())]
    assert [r.call_id for r in resolver.requests] == ["c1:fb", "c2:fb"]
    assert res.ok and res.call_id == "c1"
    assert chunks[-1].result.call_id == "c2"

    # An MCP tool asked directly keeps the call's own id.
    resolver.requests.clear()
    await svc.execute(ToolCall(tool="archon__find_tasks", call_id="c3"), _ctx())
    assert [r.call_id for r in resolver.requests] == ["c3"]
