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


from zygos.tools import ToolChunk
from zygos.tools.permissions import AllowingResolver, DenyingResolver, PermissionPolicy, Rule


class SpyExec(BaseTool):
    """Records whether execute ran; result parameterized."""

    def __init__(self, name, *, permission="allow", fallback=None, fail=False, out=1):
        self.meta = ToolMeta(name=name, description="d", input_model=_In, output_model=_Out,
                             permission=permission, fallback=fallback)
        self._fail = fail
        self._out = out
        self.ran = False

    async def execute(self, input: _In, ctx: ToolContext):
        self.ran = True
        if self._fail:
            raise RuntimeError("boom")
        return _Out(y=self._out)


class CountingResolver:
    def __init__(self, decision):
        self.decision = decision
        self.calls = 0

    async def resolve(self, req, ctx):
        self.calls += 1
        return self.decision


async def _collect(agen):
    return [c async for c in agen]


@pytest.mark.asyncio
async def test_meta_deny_blocks_execution():
    tool = SpyExec("t", permission="deny")
    svc = ToolService()
    svc.register(tool)
    res = await svc.execute(ToolCall(tool="t", args={"x": 1}), _ctx())
    assert res.ok is False and res.error_code == "tool_permission_denied"
    assert tool.ran is False


@pytest.mark.asyncio
async def test_policy_rule_deny_blocks_execution():
    tool = SpyExec("t")
    svc = ToolService(policy=PermissionPolicy(rules=[Rule(pattern="t", decision="deny")]))
    svc.register(tool)
    res = await svc.execute(ToolCall(tool="t", args={"x": 1}), _ctx())
    assert res.error_code == "tool_permission_denied" and tool.ran is False


@pytest.mark.asyncio
async def test_ask_with_denying_resolver_blocks_and_allowing_runs():
    denied = SpyExec("a", permission="ask")
    svc_d = ToolService(resolver=DenyingResolver())
    svc_d.register(denied)
    assert (await svc_d.execute(ToolCall(tool="a", args={"x": 1}), _ctx())).error_code == "tool_permission_denied"

    allowed = SpyExec("a2", permission="ask")
    svc_a = ToolService(resolver=AllowingResolver())
    svc_a.register(allowed)
    assert (await svc_a.execute(ToolCall(tool="a2", args={"x": 2}), _ctx())).ok is True


@pytest.mark.asyncio
async def test_resolver_consulted_exactly_once():
    tool = SpyExec("a", permission="ask")
    resolver = CountingResolver("allow")
    svc = ToolService(resolver=resolver)
    svc.register(tool)
    await svc.execute(ToolCall(tool="a", args={"x": 1}), _ctx())
    assert resolver.calls == 1


@pytest.mark.asyncio
async def test_one_level_fallback_runs_on_primary_failure():
    primary = SpyExec("p", fallback="fb", fail=True)
    fb = SpyExec("fb", out=99)
    svc = ToolService()
    svc.register(primary)
    svc.register(fb)
    res = await svc.execute(ToolCall(tool="p", args={"x": 1}), _ctx())
    assert res.ok is True and res.output == _Out(y=99)
    assert primary.ran and fb.ran


@pytest.mark.asyncio
async def test_fallback_failure_returns_fallback_result_no_third_try():
    primary = SpyExec("p", fallback="fb", fail=True)
    fb = SpyExec("fb", fallback="fb2", fail=True)   # fb2 must NOT be followed
    fb2 = SpyExec("fb2", out=7)
    svc = ToolService()
    for t in (primary, fb, fb2):
        svc.register(t)
    res = await svc.execute(ToolCall(tool="p", args={"x": 1}), _ctx())
    assert res.ok is False
    assert fb.ran is True and fb2.ran is False


@pytest.mark.asyncio
async def test_missing_fallback_returns_primary_failure():
    primary = SpyExec("p", fallback="ghost", fail=True)
    svc = ToolService()
    svc.register(primary)
    res = await svc.execute(ToolCall(tool="p", args={"x": 1}), _ctx())
    assert res.ok is False and res.error_code == "tool_execution_failed"


@pytest.mark.asyncio
async def test_successful_primary_never_invokes_fallback():
    primary = SpyExec("p", fallback="fb", out=3)
    fb = SpyExec("fb")
    svc = ToolService()
    svc.register(primary)
    svc.register(fb)
    res = await svc.execute(ToolCall(tool="p", args={"x": 1}), _ctx())
    assert res.output == _Out(y=3) and fb.ran is False


@pytest.mark.asyncio
async def test_execute_stream_denied_yields_single_terminal_chunk():
    tool = SpyExec("t", permission="deny")
    svc = ToolService()
    svc.register(tool)
    chunks = await _collect(svc.execute_stream(ToolCall(tool="t", args={"x": 1}), _ctx()))
    assert len(chunks) == 1
    assert chunks[0].kind == "result" and chunks[0].result.error_code == "tool_permission_denied"


@pytest.mark.asyncio
async def test_execute_stream_happy_passes_chunks_through():
    tool = SpyExec("t", out=5)
    svc = ToolService()
    svc.register(tool)
    chunks = await _collect(svc.execute_stream(ToolCall(tool="t", args={"x": 1}), _ctx()))
    assert [c.kind for c in chunks] == ["content", "result"]
    assert chunks[-1].result.ok is True
