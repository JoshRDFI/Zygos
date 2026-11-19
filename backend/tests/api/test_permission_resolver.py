import asyncio

import pytest

from zygos.api.frames import TOOLS
from zygos.api.permission import PromptAnswer, WebSocketPromptResolver
from zygos.api.session import SessionRegistry
from zygos.runtime.context import CancelToken
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
    session.pending_permissions["c1"].set_result(PromptAnswer("allow", None))
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
async def test_tripped_cancel_token_denies_without_waiting_for_timeout():
    # A barge-in trips the turn's CancelToken while a tool is parked awaiting a
    # permission response. resolve() must observe the trip and deny promptly,
    # never hang for the (long) permission timeout — otherwise the WS reader
    # loop, which is awaiting the parked turn, freezes until timeout (9774f63d).
    reg = _registry()
    session = reg.create()
    session.connected = True
    token = CancelToken()
    ctx = ToolContext(exec=session.root.child("turn1", cancel=token),
                      tool="run_command", call_id="c1")
    resolver = WebSocketPromptResolver(reg, timeout_s=30.0)
    task = asyncio.create_task(resolver.resolve(_req(), ctx))
    await asyncio.sleep(0)  # let it register the future and start waiting
    assert "c1" in session.pending_permissions
    token.trip()  # barge-in / cancel trips the turn's token
    # resolve must finish ON ITS OWN (no external cancellation) after the trip.
    for _ in range(20):
        await asyncio.sleep(0)
        if task.done():
            break
    finished = task.done()
    if not finished:
        task.cancel()  # don't leak a parked task into the next test
    assert finished, "resolve ignored the cancel-token trip and hung for the timeout"
    assert task.result() == "deny"
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


# --- the prompt carries details, reports its outcome, and can record trust ---------------

DETAILS = {"server": "archon", "server_tool": "find_tasks", "where": "remote",
           "address": "http://localhost:8051/mcp", "description": "Find tasks.",
           "claims": ["read-only"], "can_trust": True, "fingerprint": "fp-shown"}


def _mcp_req(call_id="c1", details=None):
    return PermissionRequest(tool="archon__find_tasks", args_summary={"query": "auth"},
                             run_id="r", call_id=call_id,
                             details=DETAILS if details is None else details)


def _frames(session):
    out = []
    while not session.outbound.empty():
        out.append(session.outbound.get_nowait())
    return out


def _results(session):
    return [f for f in _frames(session) if f.type == "permission.result"]


class _Trust:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    async def __call__(self, tool, scope, shown):
        self.calls.append((tool, scope, shown))
        return self.ok


def _connected():
    reg = _registry()
    session = reg.create()
    session.connected = True
    return reg, session


async def _answer(resolver, session, answer, req=None):
    task = asyncio.create_task(resolver.resolve(req or _mcp_req(), _tctx(session)))
    await asyncio.sleep(0)
    prompt = session.outbound.get_nowait()
    fut = session.pending_permissions["c1"]
    if answer == "cancel":
        fut.cancel()
    elif isinstance(answer, BaseException):
        fut.set_exception(answer)
    else:
        fut.set_result(answer)
    return prompt, await task


@pytest.mark.asyncio
async def test_frame_carries_details_and_expiry():
    reg, session = _connected()
    resolver = WebSocketPromptResolver(reg, timeout_s=90.0)
    prompt, decision = await _answer(resolver, session, PromptAnswer("allow", None))
    assert prompt.channel == TOOLS and prompt.type == "permission"
    assert prompt.payload == {"call_id": "c1", "tool": "archon__find_tasks",
                              "args_summary": {"query": "auth"}, "expires_in_s": 90.0, **DETAILS}
    assert decision == "allow"
    [result] = _results(session)
    assert result.channel == TOOLS and result.payload == {"call_id": "c1", "outcome": "allowed"}


@pytest.mark.asyncio
async def test_builtin_frame_cannot_trust():
    reg, session = _connected()
    resolver = WebSocketPromptResolver(reg, timeout_s=1.0)
    prompt, _ = await _answer(resolver, session, PromptAnswer("deny", None), req=_req())
    assert prompt.payload["can_trust"] is False
    assert prompt.payload["expires_in_s"] == 1.0
    assert set(prompt.payload) == {"call_id", "tool", "args_summary", "expires_in_s", "can_trust"}
    assert _results(session)[0].payload["outcome"] == "denied"


@pytest.mark.asyncio
async def test_allow_with_trust_tool_calls_trust_and_reports():
    reg, session = _connected()
    trust = _Trust(True)
    resolver = WebSocketPromptResolver(reg, timeout_s=1.0, trust=trust)
    _, decision = await _answer(resolver, session, PromptAnswer("allow", "tool"))
    assert decision == "allow"
    assert trust.calls == [("archon__find_tasks", "tool", "fp-shown")]
    assert _results(session)[0].payload == {"call_id": "c1", "outcome": "trusted_tool"}


@pytest.mark.asyncio
async def test_allow_with_trust_server():
    reg, session = _connected()
    trust = _Trust(True)
    resolver = WebSocketPromptResolver(reg, timeout_s=1.0, trust=trust)
    _, decision = await _answer(resolver, session, PromptAnswer("allow", "server"))
    assert decision == "allow"
    assert trust.calls == [("archon__find_tasks", "server", "fp-shown")]
    assert _results(session)[0].payload["outcome"] == "trusted_server"


@pytest.mark.asyncio
async def test_trust_without_a_shown_fingerprint_passes_none():
    reg, session = _connected()
    trust = _Trust(False)
    details = {k: v for k, v in DETAILS.items() if k != "fingerprint"}
    resolver = WebSocketPromptResolver(reg, timeout_s=1.0, trust=trust)
    _, decision = await _answer(resolver, session, PromptAnswer("allow", "tool"), req=_mcp_req(details=details))
    assert decision == "allow"
    assert trust.calls == [("archon__find_tasks", "tool", None)]
    assert _results(session)[0].payload["outcome"] == "trust_failed"


@pytest.mark.asyncio
async def test_trust_failure_still_allows():
    for trust in (_Trust(False), None):
        reg, session = _connected()
        if trust is None:
            async def trust(tool, scope, shown):  # a raising callback counts as a failed save
                raise RuntimeError("store busy")
        resolver = WebSocketPromptResolver(reg, timeout_s=1.0, trust=trust)
        _, decision = await _answer(resolver, session, PromptAnswer("allow", "tool"))
        assert decision == "allow"
        assert _results(session)[0].payload["outcome"] == "trust_failed"


@pytest.mark.asyncio
async def test_deny_with_trust_writes_nothing():
    reg, session = _connected()
    trust = _Trust(True)
    resolver = WebSocketPromptResolver(reg, timeout_s=1.0, trust=trust)
    _, decision = await _answer(resolver, session, PromptAnswer("deny", "server"))
    assert decision == "deny"
    assert trust.calls == []
    assert _results(session)[0].payload["outcome"] == "denied"


@pytest.mark.asyncio
async def test_trust_ignored_when_cannot_trust():
    for details in ({}, {**DETAILS, "can_trust": False}):
        reg, session = _connected()
        trust = _Trust(True)
        resolver = WebSocketPromptResolver(reg, timeout_s=1.0, trust=trust)
        _, decision = await _answer(resolver, session, PromptAnswer("allow", "tool"),
                                    req=_mcp_req(details=details))
        assert decision == "allow"
        assert trust.calls == []
        assert _results(session)[0].payload["outcome"] == "allowed"
    # Nothing bound to record trust: allowed, nothing written.
    reg, session = _connected()
    resolver = WebSocketPromptResolver(reg, timeout_s=1.0)
    _, decision = await _answer(resolver, session, PromptAnswer("allow", "tool"))
    assert decision == "allow" and _results(session)[0].payload["outcome"] == "allowed"


@pytest.mark.asyncio
async def test_timeout_outcome_timed_out():
    reg, session = _connected()
    trust = _Trust(True)
    resolver = WebSocketPromptResolver(reg, timeout_s=0.01, trust=trust)
    assert await resolver.resolve(_mcp_req(), _tctx(session)) == "deny"
    assert _results(session)[0].payload == {"call_id": "c1", "outcome": "timed_out"}
    assert trust.calls == [] and "c1" not in session.pending_permissions


@pytest.mark.asyncio
async def test_cancel_outcome_cancelled():
    # A tripped turn token.
    reg, session = _connected()
    token = CancelToken()
    ctx = ToolContext(exec=session.root.child("t", cancel=token), tool="x", call_id="c1")
    resolver = WebSocketPromptResolver(reg, timeout_s=30.0)
    task = asyncio.create_task(resolver.resolve(_mcp_req(), ctx))
    await asyncio.sleep(0)
    token.trip()
    assert await asyncio.wait_for(task, 1.0) == "deny"
    assert _results(session)[0].payload["outcome"] == "cancelled"

    # The awaiting task itself cancelled.
    reg, session = _connected()
    resolver = WebSocketPromptResolver(reg, timeout_s=30.0)
    task = asyncio.create_task(resolver.resolve(_mcp_req(), _tctx(session)))
    await asyncio.sleep(0)
    task.cancel()
    assert await task == "deny"
    assert _results(session)[0].payload == {"call_id": "c1", "outcome": "cancelled"}


@pytest.mark.asyncio
async def test_failed_or_foreign_future_counts_as_cancelled():
    # The socket's teardown, or anything else that settles the future without a
    # PromptAnswer, denies. Includes the disconnect path's plain "deny" and a stray "allow".
    trust = _Trust(True)
    for answer in ("cancel", RuntimeError("socket gone"), "deny", "allow", None):
        reg, session = _connected()
        resolver = WebSocketPromptResolver(reg, timeout_s=1.0, trust=trust)
        _, decision = await _answer(resolver, session, answer)
        assert decision == "deny", answer
        assert _results(session)[0].payload["outcome"] == "cancelled", answer
    assert trust.calls == []


@pytest.mark.asyncio
async def test_result_frame_when_socket_gone_is_harmless():
    reg, session = _connected()
    resolver = WebSocketPromptResolver(reg, timeout_s=1.0)
    task = asyncio.create_task(resolver.resolve(_mcp_req(), _tctx(session)))
    await asyncio.sleep(0)
    session.connected = False
    reg.delete(session.id)
    session.pending_permissions["c1"].set_result("deny")
    assert await task == "deny"


@pytest.mark.asyncio
async def test_announce_once_when_speaking():
    reg, session = _connected()
    session.speak = True
    spoken = []
    resolver = WebSocketPromptResolver(reg, timeout_s=1.0,
                                       announce=lambda s, text: spoken.append((s, text)))
    await _answer(resolver, session, PromptAnswer("allow", None))
    assert spoken == [(session, "I need your OK on screen to use find tasks.")]
    # A built-in uses its own name.
    spoken.clear()
    await _answer(resolver, session, PromptAnswer("deny", None), req=PermissionRequest(
        tool="run_command", args_summary={}, run_id="r", call_id="c1"))
    assert spoken == [(session, "I need your OK on screen to use run command.")]


@pytest.mark.asyncio
async def test_no_announce_when_not_speaking():
    reg, session = _connected()
    session.speak = False
    spoken = []
    resolver = WebSocketPromptResolver(reg, timeout_s=1.0,
                                       announce=lambda s, text: spoken.append(text))
    await _answer(resolver, session, PromptAnswer("allow", None))
    assert spoken == []


@pytest.mark.asyncio
async def test_announce_failure_does_not_break_prompt():
    reg, session = _connected()
    session.speak = True

    def announce(s, text):
        raise RuntimeError("tts broke")

    resolver = WebSocketPromptResolver(reg, timeout_s=1.0, announce=announce)
    _, decision = await _answer(resolver, session, PromptAnswer("allow", None))
    assert decision == "allow"
    assert _results(session)[0].payload["outcome"] == "allowed"


@pytest.mark.asyncio
async def test_trust_write_is_bounded():
    # A wedged trust store must not hold the call: the user said yes, so it runs,
    # and the card says trust was not saved.
    reg, session = _connected()

    async def never(tool, scope, shown):
        await asyncio.Event().wait()

    resolver = WebSocketPromptResolver(reg, timeout_s=0.05, trust=never)
    _, decision = await asyncio.wait_for(
        _answer(resolver, session, PromptAnswer("allow", "tool")), 2.0)
    assert decision == "allow"
    assert _results(session)[0].payload["outcome"] == "trust_failed"
