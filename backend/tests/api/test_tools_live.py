"""End-to-end live tool-calling round-trip (M8 Cycle 3, Task 10).

Proves the whole wired stack — WS turn loop -> RFC-0008 agentic loop -> ToolService
permission gate -> WebSocketPromptResolver -> `tools:*` framing — works together, using
an in-process ASGI TestClient + a scripted FakeProvider (no real network, no real model).
Despite the historical filename, this is fully deterministic and in-process (no real
network, no real model), so it runs in the default suite alongside the other API tests —
unlike its sibling `tests/live/test_ollama_live.py`, which genuinely hits a live server
and stays `@pytest.mark.live`.

Scenarios:
  1. permission "allow" round-trip: tools:permission -> permission_response(allow) ->
     tools:call / tools:result(ok) -> chat:turn.end.
  2. permission "deny" round-trip: tools:result carries tool_permission_denied, and the
     turn still completes normally.
  3. disconnect while a permission prompt is outstanding resolves the pending future to
     "deny" and clears `Session.pending_permissions` (pins the WS disconnect cleanup path
     added in an earlier M8-C3 task).

Stability: Experimental (test-only).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from pydantic import BaseModel

from zygos.agent.config import ToolLoopConfig
from zygos.api.app import create_app
from zygos.api.session import SessionRegistry
from zygos.api.websocket import session_ws
from zygos.providers.fake import FakeProvider
from zygos.providers.types import GenerationResult, ToolInvocation
from zygos.runtime.bootstrap import build_runtime
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.services.model import DefaultModelService
from zygos.services.router import ProviderRouter, RouteChoice
from zygos.tools.registry import ToolRegistry
from zygos.tools.service import ToolService
from zygos.tools.types import BaseTool, ToolContext, ToolMeta


# ---------------------------------------------------------------------------
# A minimal `ask`-permission tool, registered directly (no config/from_config needed).
# ---------------------------------------------------------------------------

class _AskArgs(BaseModel):
    note: str = ""


class AskTool(BaseTool):
    meta = ToolMeta(
        name="ask_tool",
        description="A tool that requires human permission for this test.",
        input_model=_AskArgs,
        permission="ask",
    )

    async def execute(self, input: _AskArgs, ctx: ToolContext) -> dict:
        return {"done": True, "note": input.note}


def _fake_runtime_with_ask_tool(script):
    """Build a RuntimeAssembly whose model is a scripted FakeProvider and whose only
    registered/exposed tool is AskTool (deterministic; no starter-tool side effects)."""
    provider = FakeProvider(script=script)
    model = DefaultModelService(ProviderRouter([RouteChoice("fake", "m")], {"fake": provider}))
    tool = AskTool()
    registry = ToolRegistry()
    registry.register(tool)
    tool_service = ToolService(registry)   # default PermissionPolicy: no rule matches
    return dataclasses.replace(
        build_runtime(),
        model_service=model,
        memory_service=None,
        tool_service=tool_service,
        tools=(tool,),
        tool_loop_config=ToolLoopConfig(),
    )


def _tool_call_then_answer(final_text: str):
    """Script: first turn iteration requests ask_tool, second iteration answers."""
    call = GenerationResult(
        text="", model="m", provider="fake",
        tool_calls=(ToolInvocation(id="call-1", name="ask_tool", arguments={"note": "hi"}),),
        finish_reason="tool_calls",
    )
    return [call, final_text]


def _um(text: str) -> str:
    return json.dumps({"channel": "chat", "type": "user_message", "payload": {"text": text}})


def _perm_response(call_id: str, decision: str) -> str:
    return json.dumps({"channel": "tools", "type": "permission_response",
                        "payload": {"call_id": call_id, "decision": decision}})


def _drive_until(ws, frames, predicate):
    while True:
        f = json.loads(ws.receive_text())
        frames.append(f)
        if predicate(f):
            return f


def _is_permission(f):
    return f["channel"] == "tools" and f["type"] == "permission"


def _is_turn_end(f):
    return f["channel"] == "chat" and f["type"] == "turn.end"


def _frame(frames, channel, type_):
    return next(f for f in frames if f["channel"] == channel and f["type"] == type_)


# ---------------------------------------------------------------------------
# Scenario 1: permission allow
# ---------------------------------------------------------------------------

def test_permission_allow_round_trip():
    runtime = _fake_runtime_with_ask_tool(_tool_call_then_answer("final answer"))
    app = create_app(runtime)
    with TestClient(app) as client:
        sid = client.post("/sessions").json()["id"]
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            ws.send_text(_um("please use the tool"))
            frames: list[dict] = []
            perm = _drive_until(ws, frames, _is_permission)

            # Payload is exactly the human-prompt shape — no secret-y extras.
            assert set(perm["payload"].keys()) == {"call_id", "tool", "args_summary"}
            assert perm["payload"]["call_id"] == "call-1"
            assert perm["payload"]["tool"] == "ask_tool"
            assert perm["payload"]["args_summary"] == {"note": "hi"}

            ws.send_text(_perm_response(perm["payload"]["call_id"], "allow"))
            _drive_until(ws, frames, _is_turn_end)

    call_frame = _frame(frames, "tools", "call")
    assert call_frame["payload"]["call_id"] == "call-1"
    assert call_frame["payload"]["tool"] == "ask_tool"

    result_frame = _frame(frames, "tools", "result")
    assert result_frame["payload"]["ok"] is True
    assert result_frame["payload"]["output"] == {"done": True, "note": "hi"}

    assert frames[-1]["channel"] == "chat" and frames[-1]["type"] == "turn.end"
    assert frames[-1]["payload"]["text"] == "final answer"


# ---------------------------------------------------------------------------
# Scenario 2: permission deny
# ---------------------------------------------------------------------------

def test_permission_deny_round_trip():
    runtime = _fake_runtime_with_ask_tool(_tool_call_then_answer("final answer after deny"))
    app = create_app(runtime)
    with TestClient(app) as client:
        sid = client.post("/sessions").json()["id"]
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            ws.send_text(_um("please use the tool"))
            frames: list[dict] = []
            perm = _drive_until(ws, frames, _is_permission)

            ws.send_text(_perm_response(perm["payload"]["call_id"], "deny"))
            _drive_until(ws, frames, _is_turn_end)

    result_frame = _frame(frames, "tools", "result")
    assert result_frame["payload"]["ok"] is False
    assert result_frame["payload"]["error_code"] == "tool_permission_denied"

    # The turn still completes — a denied tool call is not a turn failure.
    assert frames[-1]["channel"] == "chat" and frames[-1]["type"] == "turn.end"
    assert frames[-1]["payload"]["text"] == "final answer after deny"


# ---------------------------------------------------------------------------
# Scenario 3: disconnect while a permission prompt is outstanding -> deny
# ---------------------------------------------------------------------------

class _ImmediateDisconnectWebSocket:
    """Stand-in for FastAPI's WebSocket: accepts, then the first receive raises
    WebSocketDisconnect — simulating a client that vanished mid-prompt."""

    def __init__(self, app) -> None:
        self.app = app

    async def accept(self) -> None:
        return None

    async def receive_text(self) -> str:
        raise WebSocketDisconnect(code=1000)

    async def send_text(self, data: str) -> None:
        return None


class _State:
    pass


class _App:
    pass


@pytest.mark.asyncio
async def test_disconnect_resolves_pending_permission_to_deny():
    bus = InProcessEventBus()
    registry = SessionRegistry(
        new_context=lambda sid: root_context(bus, session_id=sid),
        clock=lambda: 0.0, new_id=lambda: "s1",
    )
    session = registry.create()

    # Seed a pending permission future, as the resolver would have while awaiting a
    # human response, then drive the real WS handler's disconnect path directly.
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    session.pending_permissions["call-x"] = fut

    app = _App()
    app.state = _State()
    app.state.registry = registry
    app.state.turn_deps = None  # unused: disconnect happens before any frame dispatch

    await session_ws(_ImmediateDisconnectWebSocket(app), session.id)
    await asyncio.sleep(0)  # let the handler's writer.cancel() land cleanly

    assert fut.done()
    assert fut.result() == "deny"
    assert session.pending_permissions == {}
    assert session.connected is False
