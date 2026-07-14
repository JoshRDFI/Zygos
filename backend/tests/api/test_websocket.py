# backend/tests/api/test_websocket.py
import asyncio
import dataclasses
import json

import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient

from zygos.api.frames import CHAT, TOOLS, Frame
from zygos.api.session import Session, SessionRegistry
from zygos.api.turn import TurnDeps
from zygos.api.websocket import _dispatch, _writer, router as ws_router
from zygos.api.routes_sessions import router as sessions_router
from zygos.config.schema import ReasoningConfig
from zygos.providers.fake import FakeProvider
from zygos.reasoning.service import DefaultReasoningService
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.services.model import DefaultModelService
from zygos.services.router import ProviderRouter, RouteChoice


def _app(script=None, text="hi there"):
    app = FastAPI()
    bus = InProcessEventBus()
    n = {"i": 0}

    def new_id():
        n["i"] += 1
        return f"x-{n['i']}"

    registry = SessionRegistry(new_context=lambda sid: root_context(bus, session_id=sid),
                               clock=lambda: 0.0, new_id=new_id)
    provider = FakeProvider(script=script, text=text)
    model = DefaultModelService(ProviderRouter([RouteChoice("fake", "m")], {"fake": provider}))
    app.state.registry = registry
    app.state.turn_deps = TurnDeps(
        model_service=model,
        reasoning_factory=lambda: DefaultReasoningService(model, ReasoningConfig(enabled=True)),
        reasoning_enabled=False, memory_service=None, new_id=lambda: "turn",
    )
    app.include_router(sessions_router)
    app.include_router(ws_router)
    return app


def _um(text):
    return json.dumps({"channel": "chat", "type": "user_message", "payload": {"text": text}})


def _collect_until_turn_end(ws):
    frames = []
    while True:
        f = json.loads(ws.receive_text())
        frames.append(f)
        if f["channel"] == "chat" and f["type"] == "turn.end":
            return frames


def test_full_turn_round_trip():
    app = _app(script=["alpha beta"])
    client = TestClient(app)
    sid = client.post("/sessions").json()["id"]
    with client.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_text(_um("hello"))
        frames = _collect_until_turn_end(ws)
    kinds = [(f["channel"], f["type"]) for f in frames]
    assert kinds[0] == ("chat", "turn.start")
    assert ("chat", "token") in kinds
    assert kinds[-1] == ("chat", "turn.end")


def test_unknown_session_id_is_closed():
    app = _app()
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/session/does-not-exist") as ws:
            ws.receive_text()
    assert exc_info.value.code == 4404


def test_ping_pong():
    app = _app()
    client = TestClient(app)
    sid = client.post("/sessions").json()["id"]
    with client.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_text(json.dumps({"channel": "control", "type": "ping", "payload": {}}))
        reply = json.loads(ws.receive_text())
    assert reply["channel"] == "control" and reply["type"] == "pong"


def test_malformed_frame_returns_control_error():
    app = _app()
    client = TestClient(app)
    sid = client.post("/sessions").json()["id"]
    with client.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_text("this is not json")
        reply = json.loads(ws.receive_text())
    assert reply["channel"] == "control" and reply["type"] == "error"


class _FailingWebSocket:
    """Fake websocket whose send_text always fails, simulating a mid-turn drop."""

    def __init__(self, exc):
        self._exc = exc
        self.calls = 0

    async def send_text(self, data):
        self.calls += 1
        raise self._exc


def _session():
    bus = InProcessEventBus()
    return Session("s", root_context(bus, session_id="s"), created_at=0.0)


def test_writer_returns_cleanly_on_websocket_disconnect():
    session = _session()
    session.enqueue(Frame(channel=CHAT, type="token", payload={"text": "hi"}))
    fake_ws = _FailingWebSocket(WebSocketDisconnect(code=1000))
    asyncio.run(_writer(fake_ws, session))  # must return, not raise
    assert fake_ws.calls == 1


def test_writer_returns_cleanly_on_generic_send_error():
    session = _session()
    session.enqueue(Frame(channel=CHAT, type="token", payload={"text": "hi"}))
    fake_ws = _FailingWebSocket(RuntimeError("connection reset"))
    asyncio.run(_writer(fake_ws, session))  # must return, not raise
    assert fake_ws.calls == 1


def test_writer_propagates_cancellation():
    async def run():
        session = _session()
        fake_ws = _FailingWebSocket(RuntimeError("unused"))
        task = asyncio.create_task(_writer(fake_ws, session))
        await asyncio.sleep(0)  # let it start waiting on the empty queue
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())


def test_connected_flag_true_during_session():
    app = _app()
    client = TestClient(app)
    sid = client.post("/sessions").json()["id"]
    with client.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_text(json.dumps({"channel": "control", "type": "ping", "payload": {}}))
        json.loads(ws.receive_text())
        assert app.state.registry.get(sid).connected is True
    # after close, connection flips off (best-effort; give the server loop a beat)


def _bare_session():
    return Session("s1", root_context(InProcessEventBus(), session_id="s1"), created_at=0.0)


@pytest.mark.asyncio
async def test_permission_response_resolves_future():
    session = _bare_session()
    fut = asyncio.get_running_loop().create_future()
    session.pending_permissions["c1"] = fut
    await _dispatch(session, None, Frame(channel=TOOLS, type="permission_response",
                                         payload={"call_id": "c1", "decision": "allow"}))
    assert fut.result() == "allow"


@pytest.mark.asyncio
async def test_permission_response_ignores_unknown_and_bad_decision():
    session = _bare_session()
    fut = asyncio.get_running_loop().create_future()
    session.pending_permissions["c1"] = fut
    # unknown call_id -> ignored
    await _dispatch(session, None, Frame(channel=TOOLS, type="permission_response",
                                         payload={"call_id": "zzz", "decision": "allow"}))
    # bad decision -> ignored
    await _dispatch(session, None, Frame(channel=TOOLS, type="permission_response",
                                         payload={"call_id": "c1", "decision": "maybe"}))
    assert not fut.done()
