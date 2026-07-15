# backend/tests/api/test_websocket.py
import asyncio
import dataclasses
import json

import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient

from zygos.api.frames import AUDIO_TAG_OUT, CHAT, CONTROL, TOOLS, Frame
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


class _RecordingWS:
    """Fake websocket that records send_text/send_bytes calls in FIFO order."""

    def __init__(self):
        self.sent = []

    async def send_text(self, s):
        self.sent.append(("text", s))

    async def send_bytes(self, b):
        self.sent.append(("bytes", b))


async def test_writer_sends_frames_as_text_and_audio_as_bytes():
    session = _session()
    session.enqueue(Frame(channel=CHAT, type="tok", payload={"text": "hi"}))
    session.enqueue_audio(b"\x00\x00")
    ws = _RecordingWS()
    task = asyncio.create_task(_writer(ws, session))
    try:
        while len(ws.sent) < 2:
            await asyncio.sleep(0)
    finally:
        task.cancel()
    kinds = [k for k, _ in ws.sent]
    assert kinds == ["text", "bytes"]  # FIFO order preserved
    assert ws.sent[1][1] == bytes([AUDIO_TAG_OUT]) + b"\x00\x00"


@pytest.mark.asyncio
async def test_audio_output_frame_toggles_speak():
    session = _bare_session()
    assert session.speak is False
    # no voice service configured -> gate is inert; deps just needs the two attrs
    deps = SimpleNamespace(voice_service=None, voice_gate=None)
    await _dispatch(session, deps, Frame(channel=CONTROL, type="audio.output",
                                         payload={"enabled": True}))
    assert session.speak is True
    await _dispatch(session, deps, Frame(channel=CONTROL, type="audio.output",
                                         payload={"enabled": False}))
    assert session.speak is False


from types import SimpleNamespace

from zygos.api.voice_gate import VoiceGate
from zygos.api.websocket import _acquire_voice_or_warn


class _Sess:
    def __init__(self, sid):
        self.id = sid
        self.sent = []
    def enqueue(self, frame):
        self.sent.append(frame)


def _deps(voice_service, gate):
    return SimpleNamespace(voice_service=voice_service, voice_gate=gate)


def test_gate_inert_when_no_voice_service():
    s = _Sess("a")
    assert _acquire_voice_or_warn(s, _deps(None, VoiceGate())) is True
    assert s.sent == []


def test_gate_inert_for_concurrency_safe_engine():
    s = _Sess("a")
    vs = SimpleNamespace(concurrent_sessions_ok=True)
    assert _acquire_voice_or_warn(s, _deps(vs, VoiceGate())) is True
    assert s.sent == []


def test_gate_enforced_first_allows_second_warns():
    gate = VoiceGate()
    vs = SimpleNamespace(concurrent_sessions_ok=False)
    a, b = _Sess("a"), _Sess("b")
    assert _acquire_voice_or_warn(a, _deps(vs, gate)) is True
    assert a.sent == []
    assert _acquire_voice_or_warn(b, _deps(vs, gate)) is False
    assert len(b.sent) == 1
    warn = b.sent[0]
    assert warn.channel == "control" and warn.type == "audio.unavailable"
    assert warn.payload["reason"] == "voice_in_use"


import asyncio
from types import SimpleNamespace

from zygos.api.duck import arm_duck
from zygos.api.frames import AUDIO_OUT, CONTROL, Frame
from zygos.api.session import Session
from zygos.api.websocket import _dispatch
from zygos.runtime.context import CancelToken, root_context
from zygos.runtime.events import InProcessEventBus


def _vad_session() -> Session:
    return Session("s", root_context(InProcessEventBus()), created_at=0.0)


def _vad_deps():
    return SimpleNamespace(duck_gain=0.2, duck_timeout_s=5.0,
                           voice_service=None, voice_gate=None)


def _drain_ws(session):
    out = []
    while not session.outbound.empty():
        out.append(session.outbound.get_nowait())
    return out


async def test_dispatch_vad_onset_ducks_when_speaking():
    s = _vad_session()
    s.speaking = True
    await _dispatch(s, _vad_deps(),
                    Frame(channel=CONTROL, type="audio.vad", payload={"state": "onset"}))
    items = _drain_ws(s)
    assert len(items) == 1 and items[0].channel == AUDIO_OUT and items[0].type == "tts.duck"
    assert s.ducked is True
    s.duck_timeout.cancel()


async def test_dispatch_vad_silence_unducks():
    s = _vad_session()
    s.speaking = True
    arm_duck(s, gain=0.2, timeout_s=5.0)
    _drain_ws(s)
    await _dispatch(s, _vad_deps(),
                    Frame(channel=CONTROL, type="audio.vad", payload={"state": "silence"}))
    items = _drain_ws(s)
    assert len(items) == 1 and items[0].type == "tts.unduck"
    assert s.ducked is False


async def test_dispatch_vad_speech_trips_active_turn():
    s = _vad_session()
    token = CancelToken()
    s.active_cancel = token

    async def _never():
        await asyncio.Event().wait()

    s.active_task = asyncio.create_task(_never())
    await _dispatch(s, _vad_deps(),
                    Frame(channel=CONTROL, type="audio.vad", payload={"state": "speech"}))
    assert token.is_set is True
    s.active_task.cancel()


async def test_dispatch_vad_onset_no_op_when_not_speaking():
    s = _vad_session()  # not speaking
    await _dispatch(s, _vad_deps(),
                    Frame(channel=CONTROL, type="audio.vad", payload={"state": "onset"}))
    assert _drain_ws(s) == [] and s.ducked is False


async def test_dispatch_vad_unknown_state_ignored():
    s = _vad_session()
    s.speaking = True
    await _dispatch(s, _vad_deps(),
                    Frame(channel=CONTROL, type="audio.vad", payload={"state": "bogus"}))
    assert _drain_ws(s) == [] and s.ducked is False
