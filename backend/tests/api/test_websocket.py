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
        ws.receive_text()  # connect-time control:think.state
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
        ws.receive_text()  # connect-time control:think.state
        ws.send_text(json.dumps({"channel": "control", "type": "ping", "payload": {}}))
        reply = json.loads(ws.receive_text())
    assert reply["channel"] == "control" and reply["type"] == "pong"


def test_malformed_frame_returns_control_error():
    app = _app()
    client = TestClient(app)
    sid = client.post("/sessions").json()["id"]
    with client.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.receive_text()  # connect-time control:think.state
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
    from zygos.api.permission import PromptAnswer
    assert fut.result() == PromptAnswer("allow", None)


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


@pytest.mark.asyncio
async def test_permission_response_passes_trust():
    from zygos.api.permission import PromptAnswer
    for decision, trust in (("allow", "tool"), ("allow", "server"), ("deny", "server")):
        session = _bare_session()
        fut = asyncio.get_running_loop().create_future()
        session.pending_permissions["c1"] = fut
        await _dispatch(session, None, Frame(channel=TOOLS, type="permission_response", payload={
            "call_id": "c1", "decision": decision, "trust": trust}))
        assert fut.result() == PromptAnswer(decision, trust)


@pytest.mark.asyncio
async def test_bad_trust_value_dropped():
    from zygos.api.permission import PromptAnswer
    for trust in ("everything", 1, None, ["tool"]):
        session = _bare_session()
        fut = asyncio.get_running_loop().create_future()
        session.pending_permissions["c1"] = fut
        await _dispatch(session, None, Frame(channel=TOOLS, type="permission_response", payload={
            "call_id": "c1", "decision": "allow", "trust": trust}))
        assert fut.result() == PromptAnswer("allow", None)


@pytest.mark.asyncio
async def test_trust_ignored_for_unknown_call_id():
    # A stale card, another tab or a forged id: nothing resolves and no trust is written.
    from zygos.api.permission import WebSocketPromptResolver
    from zygos.tools.permissions import PermissionRequest
    from zygos.tools.types import ToolContext

    bus = InProcessEventBus()
    registry = SessionRegistry(new_context=lambda sid: root_context(bus, session_id=sid),
                               clock=lambda: 0.0, new_id=lambda: "s1")
    session = registry.create()
    session.connected = True
    trusted = []

    async def trust(tool, scope):
        trusted.append((tool, scope))
        return True

    resolver = WebSocketPromptResolver(registry, timeout_s=5.0, trust=trust)
    req = PermissionRequest(tool="archon__find_tasks", run_id="r", call_id="c1",
                            details={"can_trust": True})
    task = asyncio.create_task(resolver.resolve(
        req, ToolContext(exec=session.root, tool="archon__find_tasks", call_id="c1")))
    await asyncio.sleep(0)
    await _dispatch(session, None, Frame(channel=TOOLS, type="permission_response", payload={
        "call_id": "zzz", "decision": "allow", "trust": "server"}))
    await asyncio.sleep(0)
    assert not task.done() and not session.pending_permissions["c1"].done()
    assert trusted == []

    # Answered once: a second answer for the same card does nothing.
    await _dispatch(session, None, Frame(channel=TOOLS, type="permission_response", payload={
        "call_id": "c1", "decision": "deny"}))
    assert await task == "deny"
    await _dispatch(session, None, Frame(channel=TOOLS, type="permission_response", payload={
        "call_id": "c1", "decision": "allow", "trust": "server"}))
    await asyncio.sleep(0)
    assert trusted == [] and session.pending_permissions == {}


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


from zygos.api.permission import WebSocketPromptResolver
from zygos.tools.permissions import PermissionRequest
from zygos.tools.types import ToolContext


async def test_barge_in_does_not_hang_when_turn_parked_on_permission():
    # End-to-end guard for 9774f63d. A chat:user_message barge-in trips the active
    # turn's CancelToken then awaits that turn before starting a new one. When the
    # interrupted turn is parked inside the permission resolver, the parked
    # resolve() must observe the trip and return promptly — otherwise this await
    # (running on the WS reader loop) freezes until the permission timeout.
    bus = InProcessEventBus()
    registry = SessionRegistry(new_context=lambda sid: root_context(bus, session_id=sid),
                               clock=lambda: 0.0, new_id=lambda: "s1")
    session = registry.create()
    session.connected = True
    provider = FakeProvider(text="ok")
    model = DefaultModelService(ProviderRouter([RouteChoice("fake", "m")], {"fake": provider}))
    deps = TurnDeps(model_service=model,
                    reasoning_factory=lambda: DefaultReasoningService(model, ReasoningConfig(enabled=True)),
                    reasoning_enabled=False, memory_service=None, new_id=lambda: "turn")

    # A prior turn is parked inside the permission resolver, tied to the session token.
    token = CancelToken()
    session.active_cancel = token
    resolver = WebSocketPromptResolver(registry, timeout_s=30.0)
    ctx = ToolContext(exec=session.root.child("prior", cancel=token),
                      tool="run_command", call_id="c1")
    req = PermissionRequest(tool="run_command", args_summary={}, run_id="r", call_id="c1")
    parked = asyncio.create_task(resolver.resolve(req, ctx))
    session.active_task = parked
    await asyncio.sleep(0)  # park it awaiting the permission response
    assert "c1" in session.pending_permissions

    # Barge in. Poll for _dispatch to finish ON ITS OWN — do NOT wrap it in
    # wait_for, whose timeout would cancel the chain and let the buggy resolve's
    # `except CancelledError` mask the hang (a false pass).
    frame = Frame(channel=CHAT, type="user_message", payload={"text": "stop, do this instead"})
    disp = asyncio.create_task(_dispatch(session, deps, frame))
    for _ in range(40):
        await asyncio.sleep(0.005)
        if disp.done():
            break
    finished = disp.done()
    new_task = session.active_task
    if not finished:  # buggy: reader hung on the parked turn — clean up and fail
        disp.cancel()
        parked.cancel()
    assert finished, "barge-in await hung: the parked resolve ignored the cancel-token trip"
    assert parked.done() and parked.result() == "deny"
    assert new_task is not parked  # a fresh turn was started
    if new_task is not None:
        await asyncio.wait_for(new_task, timeout=1.0)  # let it finish, no leak


import time


def test_session_reaped_from_registry_on_disconnect():
    app = _app()
    client = TestClient(app)
    sid = client.post("/sessions").json()["id"]
    with client.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_text(json.dumps({"channel": "control", "type": "ping", "payload": {}}))
        json.loads(ws.receive_text())
        assert app.state.registry.get(sid) is not None  # alive while connected
    # after the socket closes, the WS teardown reaps the session (poll the loop)
    for _ in range(100):
        if app.state.registry.get(sid) is None:
            break
        time.sleep(0.01)
    assert app.state.registry.get(sid) is None


async def test_typed_user_message_starts_a_turn_marked_as_typed(monkeypatch):
    # RFC-0010 §3a / AC8: the typed caller states the modality explicitly.
    calls = []

    async def fake_run_turn(session, deps, text, cancel, **kw):
        calls.append((text, kw))

    monkeypatch.setattr("zygos.api.websocket.run_turn", fake_run_turn)
    session = Session("s1", root_context(InProcessEventBus(), session_id="s1"), created_at=0.0)
    frame = Frame(channel=CHAT, type="user_message", payload={"text": "typed words"})
    await _dispatch(session, None, frame)
    await session.active_task
    assert calls == [("typed words", {"spoken_input": False, "think": None, "rethink_of": None})]


@pytest.mark.parametrize("payload, expected", [
    ({"text": "q", "think": True, "rethink_of": "t1"},
     {"spoken_input": False, "think": True, "rethink_of": "t1"}),
    ({"text": "q", "think": False}, {"spoken_input": False, "think": False, "rethink_of": None}),
    ({"text": "q", "think": "yes", "rethink_of": 7},
     {"spoken_input": False, "think": None, "rethink_of": None}),
    ({"text": "q", "think": 1}, {"spoken_input": False, "think": None, "rethink_of": None}),
])
async def test_user_message_think_and_rethink_forwarded(monkeypatch, payload, expected):
    calls = []

    async def fake_run_turn(session, deps, text, cancel, **kw):
        calls.append((text, kw))

    monkeypatch.setattr("zygos.api.websocket.run_turn", fake_run_turn)
    session = Session("s1", root_context(InProcessEventBus(), session_id="s1"), created_at=0.0)
    await _dispatch(session, None, Frame(channel=CHAT, type="user_message", payload=payload))
    await session.active_task
    assert calls == [("q", expected)]


# --- RFC-0012 §2: session Think toggle -------------------------------------

def _ctl(type_, payload=None):
    return json.dumps({"channel": "control", "type": type_, "payload": payload or {}})


def _next_think_state(ws):
    while True:
        f = json.loads(ws.receive_text())
        if f["channel"] == "control" and f["type"] == "think.state":
            return f["payload"]


class _FixedChecker:
    def __init__(self, supported, reason=None):
        from zygos.thinking.support import ThinkingSupport
        self._s = ThinkingSupport(supported=supported, reason=reason)

    async def check(self, route):
        return self._s


def test_think_state_sent_on_connect():
    app = _app()
    client = TestClient(app)
    sid = client.post("/sessions").json()["id"]
    with client.websocket_connect(f"/ws/session/{sid}") as ws:
        first = json.loads(ws.receive_text())
    assert (first["channel"], first["type"]) == ("control", "think.state")
    assert first["payload"] == {"enabled": False, "supported": True, "reason": None}


def test_think_toggle_on_then_off():
    app = _app(script=["alpha", "beta"])
    seen = []
    fake = next(iter(app.state.turn_deps.model_service._router._providers.values()))
    orig_stream = fake.stream

    def spy(request):
        seen.append(request.think)
        return orig_stream(request)

    fake.stream = spy
    client = TestClient(app)
    sid = client.post("/sessions").json()["id"]
    session = app.state.registry.get(sid)
    with client.websocket_connect(f"/ws/session/{sid}") as ws:
        _next_think_state(ws)
        ws.send_text(_ctl("think", {"enabled": True}))
        assert _next_think_state(ws)["enabled"] is True
        assert session.think is True
        ws.send_text(_um("hi"))
        _collect_until_turn_end(ws)
        ws.send_text(_ctl("think", {"enabled": False}))
        assert _next_think_state(ws)["enabled"] is False
        assert session.think is False
        ws.send_text(_um("again"))
        _collect_until_turn_end(ws)
    assert seen[0] is True and seen[-1] is False


def test_think_toggle_applies_to_next_turn(monkeypatch):
    calls = []

    async def fake_run_turn(session, deps, text, cancel, **kw):
        calls.append(kw["think"])

    monkeypatch.setattr("zygos.api.websocket.run_turn", fake_run_turn)
    session = Session("s1", root_context(InProcessEventBus(), session_id="s1"), created_at=0.0)
    deps = SimpleNamespace(think_default=False, thinking_support=None, model_service=None)

    async def run():
        await _dispatch(session, deps, Frame(channel=CONTROL, type="think", payload={"enabled": True}))
        assert session.think is True
        await session.think_state_task  # sent off the reader path (M5)
        frames = _drain_ws(session)
        assert frames[-1].type == "think.state" and frames[-1].payload["enabled"] is True
        await _dispatch(session, deps, Frame(channel=CHAT, type="user_message", payload={"text": "q"}))
        await session.active_task
        await _dispatch(session, deps, Frame(channel=CONTROL, type="think", payload={"enabled": 0}))
        assert session.think is False

    asyncio.run(run())
    # run_turn receives the request-level value (None); resolve_think applies session.think.
    assert calls == [None]


def test_think_state_reports_unsupported():
    app = _app()
    app.state.turn_deps = dataclasses.replace(
        app.state.turn_deps, thinking_support=_FixedChecker(False, "m can't think"))
    client = TestClient(app)
    sid = client.post("/sessions").json()["id"]
    with client.websocket_connect(f"/ws/session/{sid}") as ws:
        first = json.loads(ws.receive_text())
    assert first["payload"]["supported"] is False
    assert first["payload"]["reason"] == "m can't think"


def test_hello_also_sends_think_state():
    app = _app()
    client = TestClient(app)
    sid = client.post("/sessions").json()["id"]
    with client.websocket_connect(f"/ws/session/{sid}") as ws:
        json.loads(ws.receive_text())  # connect-time think.state
        ws.send_text(_ctl("hello"))
        types = [json.loads(ws.receive_text())["type"] for _ in range(2)]
    assert types == ["hello", "think.state"]


def test_connect_survives_unroutable_model():
    from zygos.errors import ProviderUnavailable

    app = _app()

    def boom(*a, **k):
        raise ProviderUnavailable("No eligible provider routes", provider="router")

    app.state.turn_deps.model_service.select_model = boom
    app.state.turn_deps = dataclasses.replace(
        app.state.turn_deps, thinking_support=_FixedChecker(True))
    client = TestClient(app)
    sid = client.post("/sessions").json()["id"]
    with client.websocket_connect(f"/ws/session/{sid}") as ws:
        first = json.loads(ws.receive_text())
        assert first["type"] == "think.state"
        assert first["payload"]["supported"] is False
        assert first["payload"]["reason"] == "couldn't check the model"
        ws.send_text(_ctl("ping"))
        assert json.loads(ws.receive_text())["type"] == "pong"


# --- RFC-0012 §2 (final-review I1, M5): re-announce support changes; never block the reader

class _SequenceChecker:
    """Returns each queued support in turn, then repeats the last."""

    def __init__(self, *supports):
        self._supports = list(supports)
        self.calls = 0

    async def check(self, route):
        self.calls += 1
        if len(self._supports) > 1:
            return self._supports.pop(0)
        return self._supports[0]


def test_support_change_reannounced_after_turn():
    from zygos.thinking.support import ThinkingSupport

    app = _app(script=["one", "two"])
    app.state.turn_deps = dataclasses.replace(
        app.state.turn_deps, thinking_support=_SequenceChecker(
            ThinkingSupport(supported=False, reason="couldn't check the model"),
            ThinkingSupport(supported=True)))
    client = TestClient(app)
    sid = client.post("/sessions").json()["id"]
    with client.websocket_connect(f"/ws/session/{sid}") as ws:
        first = _next_think_state(ws)
        assert first["supported"] is False and first["reason"] == "couldn't check the model"
        ws.send_text(_um("hi"))
        _collect_until_turn_end(ws)
        after_first = _frames_until_pong(ws)
        assert [f["payload"] for f in after_first if f["type"] == "think.state"] == [
            {"enabled": False, "supported": True, "reason": None}]
        ws.send_text(_um("again"))
        _collect_until_turn_end(ws)
        after_second = _frames_until_pong(ws)
        assert [f for f in after_second if f["type"] == "think.state"] == []  # unchanged


def _frames_until_pong(ws):
    """Send a ping and collect every frame up to its pong (a no-hang 'nothing else')."""
    ws.send_text(_ctl("ping"))
    frames = []
    while True:
        f = json.loads(ws.receive_text())
        if f["type"] == "pong":
            return frames
        frames.append(f)


def _support(supported, reason=None):
    from zygos.thinking.support import ThinkingSupport
    return ThinkingSupport(supported=supported, reason=reason)


def _announce_deps(checker):
    model = SimpleNamespace(select_model=lambda: RouteChoice("fake", "m"))
    return SimpleNamespace(think_default=False, thinking_support=checker, model_service=model)


async def test_announce_if_changed_sends_nothing_when_unchanged():
    from zygos.api.thinking import announce_if_changed, send_think_state

    session = Session("s1", root_context(InProcessEventBus(), session_id="s1"), created_at=0.0)
    deps = _announce_deps(_SequenceChecker(_support(True)))
    await send_think_state(session, deps)
    assert len(_drain_ws(session)) == 1
    await announce_if_changed(session, deps)
    assert _drain_ws(session) == []


async def test_announce_if_changed_sends_on_change():
    from zygos.api.thinking import announce_if_changed, send_think_state

    session = Session("s1", root_context(InProcessEventBus(), session_id="s1"), created_at=0.0)
    deps = _announce_deps(_SequenceChecker(_support(False, "couldn't check the model"),
                                           _support(True)))
    await send_think_state(session, deps)
    _drain_ws(session)
    await announce_if_changed(session, deps)
    frames = _drain_ws(session)
    assert [f.type for f in frames] == ["think.state"]
    assert frames[0].payload == {"enabled": False, "supported": True, "reason": None}


async def test_control_think_always_reprobes():
    """control:think is an explicit request: it re-checks and always answers."""
    checker = _SequenceChecker(_support(True))
    session = Session("s1", root_context(InProcessEventBus(), session_id="s1"), created_at=0.0)
    deps = _announce_deps(checker)
    for enabled in (True, True):
        await _dispatch(session, deps, Frame(channel=CONTROL, type="think",
                                             payload={"enabled": enabled}))
        await session.think_state_task
    assert checker.calls == 2
    assert [f.type for f in _drain_ws(session)] == ["think.state", "think.state"]


class _SlowChecker:
    async def check(self, route):
        await asyncio.sleep(0.5)
        return _support(True)


def test_slow_probe_does_not_block_reader():
    app = _app()
    app.state.turn_deps = dataclasses.replace(app.state.turn_deps, thinking_support=_SlowChecker())
    client = TestClient(app)
    sid = client.post("/sessions").json()["id"]
    with client.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_text(_ctl("ping"))
        first = json.loads(ws.receive_text())
        assert (first["channel"], first["type"]) == ("control", "pong")
        ws.send_text(_ctl("think", {"enabled": True}))
        ws.send_text(_ctl("ping"))
        nxt = json.loads(ws.receive_text())
        assert nxt["type"] == "pong"
