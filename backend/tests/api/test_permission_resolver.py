import asyncio

import pytest

from zygos.api.frames import TOOLS
from zygos.api.permission import WebSocketPromptResolver
from zygos.api.session import SessionRegistry
from zygos.runtime.events import InProcessEventBus
from zygos.tools.permissions import PermissionRequest
from zygos.tools.types import ToolContext


def _registry():
    bus = InProcessEventBus()
    return SessionRegistry(
        new_context=lambda sid: __import__("zygos.runtime.context", fromlist=["root_context"]).root_context(bus, session_id=sid),
        clock=lambda: 0.0,
        new_id=lambda: "s1",
    )


def _req(call_id="c1"):
    return PermissionRequest(tool="run_command", args_summary={"argv": ["git", "status"]},
                             run_id="r", call_id=call_id)


def _tctx(session):
    return ToolContext(exec=session.root, tool="run_command", call_id="c1")


@pytest.mark.asyncio
async def test_allow_when_client_responds_allow():
    reg = _registry()
    session = reg.create()
    session.connected = True
    resolver = WebSocketPromptResolver(reg, timeout_s=1.0)
    task = asyncio.create_task(resolver.resolve(_req(), _tctx(session)))
    await asyncio.sleep(0)   # let it enqueue + register the future
    frame = session.outbound.get_nowait()
    assert frame.channel == TOOLS and frame.type == "permission"
    assert frame.payload["call_id"] == "c1"
    assert "argv" in frame.payload["args_summary"]
    session.pending_permissions["c1"].set_result("allow")
    assert await task == "allow"
    assert "c1" not in session.pending_permissions


@pytest.mark.asyncio
async def test_timeout_denies():
    reg = _registry()
    session = reg.create()
    session.connected = True
    resolver = WebSocketPromptResolver(reg, timeout_s=0.01)
    assert await resolver.resolve(_req(), _tctx(session)) == "deny"
    assert "c1" not in session.pending_permissions


@pytest.mark.asyncio
async def test_not_connected_denies():
    reg = _registry()
    session = reg.create()
    session.connected = False
    resolver = WebSocketPromptResolver(reg, timeout_s=1.0)
    assert await resolver.resolve(_req(), _tctx(session)) == "deny"


@pytest.mark.asyncio
async def test_unknown_session_denies():
    reg = _registry()
    session = reg.create()
    session.connected = True
    # ctx with a session_id the registry does not know
    from zygos.runtime.context import root_context
    from zygos.runtime.events import InProcessEventBus
    stray = root_context(InProcessEventBus(), session_id="ghost")
    ctx = ToolContext(exec=stray, tool="run_command", call_id="c1")
    resolver = WebSocketPromptResolver(reg, timeout_s=1.0)
    assert await resolver.resolve(_req(), ctx) == "deny"


@pytest.mark.asyncio
async def test_cancelled_wait_denies_and_cleans_up_pending():
    reg = _registry()
    session = reg.create()
    session.connected = True
    resolver = WebSocketPromptResolver(reg, timeout_s=1.0)
    task = asyncio.create_task(resolver.resolve(_req(), _tctx(session)))
    await asyncio.sleep(0)  # let it register the future and enter wait_for
    task.cancel()
    result = await task
    assert result == "deny"
    assert "c1" not in session.pending_permissions


@pytest.mark.asyncio
async def test_absent_session_id_denies():
    from zygos.runtime.context import root_context
    from zygos.runtime.events import InProcessEventBus
    reg = _registry()
    stray = root_context(InProcessEventBus(), session_id=None)
    ctx = ToolContext(exec=stray, tool="run_command", call_id="c1")
    resolver = WebSocketPromptResolver(reg, timeout_s=1.0)
    assert await resolver.resolve(_req(), ctx) == "deny"
