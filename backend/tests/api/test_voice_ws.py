"""Voice sidecar lifespan integration (Voice Cycle 1, Task 10).

Proves the FastAPI lifespan actually spawns the STT sidecar at startup and
kills it at shutdown when voice is enabled — mirroring the memory_service
resume/close pattern in `_lifespan`. Uses the real `fake` STT engine (a real
subprocess) so `snapshot().stt.alive` reflects genuine OS-level state, not a
mock.

Stability: Experimental (test-only).
"""

from __future__ import annotations

import asyncio
import dataclasses

import yaml
from fastapi.testclient import TestClient

from zygos.api.app import create_app
from zygos.runtime.bootstrap import build_runtime


def _voice_runtime(tmp_path, script=None):
    p = tmp_path / "zygos.yaml"
    p.write_text(yaml.safe_dump({"voice": {"enabled": True, "stt": {"engine": "fake"}}}))
    rt = build_runtime(p)
    # swap in a FakeProvider-backed model so turns are deterministic
    from zygos.providers.fake import FakeProvider
    from zygos.services.model import DefaultModelService
    from zygos.services.router import ProviderRouter, RouteChoice

    provider = FakeProvider(script=script or ["heard you"])
    model = DefaultModelService(ProviderRouter([RouteChoice("fake", "m")], {"fake": provider}))
    return dataclasses.replace(rt, model_service=model, memory_service=None)


def test_lifespan_starts_and_stops_sidecar(tmp_path):
    rt = _voice_runtime(tmp_path)
    app = create_app(rt)
    with TestClient(app):  # enters lifespan
        assert rt.voice_service.snapshot().stt.alive is True
    # after lifespan exit, sidecar is killed
    assert rt.voice_service.snapshot().stt.alive is False


from zygos.api.frames import AUDIO_TAG_IN


def _drive_until(ws, predicate, frames):
    while True:
        f = __import__("json").loads(ws.receive_text())
        frames.append(f)
        if predicate(f):
            return f


def test_voice_drives_a_turn(tmp_path):
    rt = _voice_runtime(tmp_path, script=["you said it"])
    app = create_app(rt)
    with TestClient(app) as client:
        sid = client.post("/sessions").json()["id"]
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            ws.send_text(__import__("json").dumps(
                {"channel": "control", "type": "audio.start", "payload": {}}))
            # stream tagged PCM
            for _ in range(4):
                ws.send_bytes(bytes([AUDIO_TAG_IN]) + b"\x00" * 640)
            ws.send_text(__import__("json").dumps(
                {"channel": "control", "type": "audio.endpoint", "payload": {}}))

            frames: list[dict] = []
            partial = _drive_until(ws, lambda f: f["channel"] == "chat" and f["type"] == "partial", frames)
            assert partial["payload"]["text"]
            final = _drive_until(ws, lambda f: f["channel"] == "chat" and f["type"] == "final", frames)
            assert final["payload"]["text"]  # committed transcript
            end = _drive_until(ws, lambda f: f["channel"] == "chat" and f["type"] == "turn.end", frames)
            assert "text" in end["payload"]  # the assistant's answer to the spoken turn


import json


def test_default_off_rejects_audio_and_chat_still_works(tmp_path):
    # voice NOT enabled → audio.start is inert, typed chat turn unchanged
    import dataclasses
    from zygos.providers.fake import FakeProvider
    from zygos.services.model import DefaultModelService
    from zygos.services.router import ProviderRouter, RouteChoice
    rt = dataclasses.replace(
        build_runtime(),
        model_service=DefaultModelService(
            ProviderRouter([RouteChoice("fake", "m")], {"fake": FakeProvider(script=["hi"])})),
        memory_service=None,
    )
    assert rt.voice_service is None
    app = create_app(rt)
    with TestClient(app) as client:
        sid = client.post("/sessions").json()["id"]
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            ws.send_text(json.dumps({"channel": "control", "type": "audio.start", "payload": {}}))
            # a typed turn still works
            ws.send_text(json.dumps({"channel": "chat", "type": "user_message", "payload": {"text": "yo"}}))
            frames = []
            _drive_until(ws, lambda f: f["channel"] == "chat" and f["type"] == "turn.end", frames)


def test_cancel_mid_utterance_is_clean(tmp_path):
    # grey-box: this must fail if cancel_audio_turn stops clearing session.audio
    # (the old version of this test passed either way, since the fake sidecar
    # always emits exactly one `final` regardless of whether cancel did anything).
    rt = _voice_runtime(tmp_path)
    app = create_app(rt)
    with TestClient(app) as client:
        sid = client.post("/sessions").json()["id"]
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            frames: list[dict] = []

            def _sync():
                # ping/pong is dispatched inline and the WS receive loop awaits each
                # frame's dispatch before reading the next, so observing `pong` proves
                # every frame sent before it has fully finished processing.
                ws.send_text(json.dumps({"channel": "control", "type": "ping", "payload": {}}))
                _drive_until(ws, lambda f: f["channel"] == "control" and f["type"] == "pong", frames)

            ws.send_text(json.dumps({"channel": "control", "type": "audio.start", "payload": {}}))
            ws.send_bytes(bytes([AUDIO_TAG_IN]) + b"\x00" * 320)
            _sync()

            session = app.state.registry.get(sid)
            assert session.audio is not None
            first_consumer = session.audio.consumer

            ws.send_text(json.dumps({"channel": "control", "type": "cancel", "payload": {}}))
            _sync()

            # cancel_audio_turn must have cleared the slot and torn down the consumer.
            assert session.audio is None
            assert first_consumer.cancelled() or first_consumer.done()

            # a fresh utterance still works afterward, via a brand-new AudioTurn (not
            # a no-op start() blocked by a stale non-None session.audio).
            ws.send_text(json.dumps({"channel": "control", "type": "audio.start", "payload": {}}))
            _sync()
            assert session.audio is not None
            assert session.audio.consumer is not first_consumer

            ws.send_bytes(bytes([AUDIO_TAG_IN]) + b"\x00" * 640)
            ws.send_text(json.dumps({"channel": "control", "type": "audio.endpoint", "payload": {}}))
            _drive_until(ws, lambda f: f["channel"] == "chat" and f["type"] == "final", frames)


import threading
import time as _time

from zygos.providers.types import GenerationChunk
from zygos.services.router import RouteChoice


def _wait_until(predicate, timeout=5.0):
    """Bounded busy-wait for the app's background event-loop thread to reach a
    condition (e.g. session.audio going None once a transcription naturally
    finishes) — a synchronous test thread can't `await` it directly."""
    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        if predicate():
            return
        _time.sleep(0.005)
    raise AssertionError("timed out waiting for condition")


class _BlockingModel:
    """A ModelService whose FIRST stream() call blocks mid-generation until the
    test releases it (a threading.Event, since TestClient's ASGI app runs its
    event loop on a different thread than the test). It polls ctx.cancelled
    while blocked — mirroring run_turn's reasoning-off path, which polls
    ctx.cancelled between stream chunks — so a real barge-in trip actually
    unwinds it instead of the release event being the only way out."""

    def __init__(self, release: threading.Event, texts: tuple[str, ...]) -> None:
        self._release = release
        self._texts = texts
        self._calls = 0

    def classify_task(self, prompt: str) -> str:
        return "simple"

    def select_model(self, classification=None) -> RouteChoice:
        return RouteChoice("fake", "m")

    async def generate(self, ctx, request):
        raise NotImplementedError

    async def stream(self, ctx, request):
        call = self._calls
        self._calls += 1
        words = self._texts[call].split()
        yield GenerationChunk(text=words[0])
        if call == 0:
            while not self._release.is_set():
                if ctx.cancelled:
                    return
                await asyncio.sleep(0.01)
            if ctx.cancelled:
                return
        for word in words[1:]:
            yield GenerationChunk(text=word)
        yield GenerationChunk(text="", done=True)


def test_back_to_back_utterances_barge_in_cleanly(tmp_path):
    # controller-directed fix: the audio-final path must barge in on a still-
    # running prior turn the same way the typed user_message path does,
    # otherwise back-to-back utterances clobber session.active_task.
    #
    # Turn 1 is made to block mid-stream so it is DEMONSTRABLY still running when
    # utterance 2's `final` reaches consume() — otherwise the barge-in branch
    # (`if session.active_task is not None and not session.active_task.done()`)
    # never actually fires and this test is vacuous (see original Finding 1).
    rt = _voice_runtime(tmp_path)
    release = threading.Event()
    # tools are ON by default (M8-C3); force the plain reasoning-off streaming path
    # so this test exercises run_turn's cooperative-cancellation polling loop the
    # same way it's mirrored in _BlockingModel.stream() below — the agentic-loop
    # path only checks ctx.cancelled between iterations, not mid model_service.generate().
    rt = dataclasses.replace(
        rt, model_service=_BlockingModel(release, ("first answer", "second answer")), tools=())
    app = create_app(rt)
    with TestClient(app) as client:
        sid = client.post("/sessions").json()["id"]
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            frames: list[dict] = []

            # utterance 1: starts turn 1, which blocks mid-stream (never released yet).
            ws.send_text(json.dumps({"channel": "control", "type": "audio.start", "payload": {}}))
            ws.send_bytes(bytes([AUDIO_TAG_IN]) + b"\x00" * 640)
            ws.send_text(json.dumps({"channel": "control", "type": "audio.endpoint", "payload": {}}))
            final1 = _drive_until(ws, lambda f: f["channel"] == "chat" and f["type"] == "final", frames)
            assert final1["payload"]["text"]
            # do NOT drain turn 1's turn.end here — it must still be running below.

            # The AUDIO/transcription pipeline for utterance 1 is independent of the
            # (still-blocked) CHAT turn it kicked off, and finishes quickly on its own
            # (session.audio -> None). Wait for that so utterance 2's audio.start
            # isn't a silent no-op against a stale non-None session.audio.
            session = app.state.registry.get(sid)
            _wait_until(lambda: session.audio is None, timeout=3.0)

            # utterance 2: its `final` must barge in on the still-running turn 1.
            ws.send_text(json.dumps({"channel": "control", "type": "audio.start", "payload": {}}))
            ws.send_bytes(bytes([AUDIO_TAG_IN]) + b"\x00" * 640)
            ws.send_text(json.dumps({"channel": "control", "type": "audio.endpoint", "payload": {}}))
            final2 = _drive_until(ws, lambda f: f["channel"] == "chat" and f["type"] == "final", frames)
            assert final2["payload"]["text"]

            # Safety valve, not the mechanism under test: if barge-in is broken, turn 1
            # would otherwise block forever and hang this test. A correct
            # implementation has already cancelled turn 1 (via the barge-in await)
            # well before this point.
            release.set()

            ends: list[dict] = []
            while len(ends) < 2:
                ends.append(_drive_until(
                    ws, lambda f: f["channel"] == "chat" and f["type"] == "turn.end", frames))

            cancelled = [e for e in ends if e["payload"].get("cancelled")]
            normal = [e for e in ends if not e["payload"].get("cancelled")]
            assert len(cancelled) == 1, "turn 1 must have been barged-in on (turn.end cancelled=True)"
            assert len(normal) == 1 and "text" in normal[0]["payload"]  # turn 2 completed normally


def test_second_session_voice_is_refused(tmp_path):
    rt = _voice_runtime(tmp_path)
    app = create_app(rt)
    with TestClient(app) as client:
        a = client.post("/sessions").json()["id"]
        b = client.post("/sessions").json()["id"]
        with client.websocket_connect(f"/ws/session/{a}") as ws_a, \
             client.websocket_connect(f"/ws/session/{b}") as ws_b:
            # A claims voice
            ws_a.send_text(json.dumps({"channel": "control", "type": "audio.start", "payload": {}}))
            ws_a.send_text(json.dumps({"channel": "control", "type": "ping", "payload": {}}))
            _drive_until(ws_a, lambda f: f["channel"] == "control" and f["type"] == "pong", [])

            # B is refused with a degraded-service warning, and never begins a transcription
            ws_b.send_text(json.dumps({"channel": "control", "type": "audio.start", "payload": {}}))
            warn = _drive_until(
                ws_b, lambda f: f["channel"] == "control" and f["type"] == "audio.unavailable", [])
            assert warn["payload"]["reason"] == "voice_in_use"
            assert app.state.registry.get(b).audio is None

            # B's typed chat still works (text is never gated)
            ws_b.send_text(json.dumps(
                {"channel": "chat", "type": "user_message", "payload": {"text": "yo"}}))
            _drive_until(ws_b, lambda f: f["channel"] == "chat" and f["type"] == "turn.end", [])
