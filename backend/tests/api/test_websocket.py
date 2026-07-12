# backend/tests/api/test_websocket.py
import dataclasses
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from zygos.api.session import SessionRegistry
from zygos.api.turn import TurnDeps
from zygos.api.websocket import router as ws_router
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
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/session/does-not-exist") as ws:
            ws.receive_text()


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


def test_connected_flag_true_during_session():
    app = _app()
    client = TestClient(app)
    sid = client.post("/sessions").json()["id"]
    with client.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_text(json.dumps({"channel": "control", "type": "ping", "payload": {}}))
        json.loads(ws.receive_text())
        assert app.state.registry.get(sid).connected is True
    # after close, connection flips off (best-effort; give the server loop a beat)
