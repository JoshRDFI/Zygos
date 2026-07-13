import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from zygos.api.app import create_app
from zygos.providers.fake import FakeProvider
from zygos.runtime.bootstrap import build_runtime
from zygos.services.model import DefaultModelService
from zygos.services.router import ProviderRouter, RouteChoice


def _fake_runtime(script=None, text="hello world"):
    provider = FakeProvider(script=script, text=text)
    model = DefaultModelService(ProviderRouter([RouteChoice("fake", "m")], {"fake": provider}))
    return dataclasses.replace(build_runtime(), model_service=model, memory_service=None)


def test_end_to_end_turn_over_real_app():
    runtime = _fake_runtime(script=["alpha beta gamma"])
    app = create_app(runtime)
    with TestClient(app) as client:  # runs lifespan → accept_requests
        assert app.state.runtime.lifecycle_stage == "accept_requests"
        sid = client.post("/sessions").json()["id"]
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            ws.send_text(json.dumps({"channel": "chat", "type": "user_message",
                                     "payload": {"text": "hi"}}))
            frames = []
            while True:
                f = json.loads(ws.receive_text())
                frames.append(f)
                if f["channel"] == "chat" and f["type"] == "turn.end":
                    break
    kinds = [(f["channel"], f["type"]) for f in frames]
    assert kinds[0] == ("chat", "turn.start")
    assert kinds[-1] == ("chat", "turn.end")
    assert frames[-1]["payload"]["text"] == "alphabetagamma"


def test_health_session_count_reflects_registry():
    runtime = _fake_runtime()
    app = create_app(runtime)
    with TestClient(app) as client:
        assert client.get("/runtime/health").json()["active_sessions"] == 0
        client.post("/sessions")
        client.post("/sessions")
        assert client.get("/runtime/health").json()["active_sessions"] == 2


def test_session_count_override_still_honored():
    runtime = _fake_runtime()
    app = create_app(runtime, session_count=lambda: 42)
    try:
        assert app.state.session_count() == 42
    finally:
        import asyncio
        asyncio.run(runtime.aclose())


def test_runtime_endpoint_still_pure():
    runtime = _fake_runtime()
    app = create_app(runtime)
    with TestClient(app) as client:
        assert client.get("/runtime").status_code == 200
