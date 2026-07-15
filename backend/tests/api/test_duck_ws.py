from __future__ import annotations

import asyncio
import dataclasses
import json
import threading
import time as _time

import yaml
from fastapi.testclient import TestClient

from zygos.api.app import create_app
from zygos.providers.types import GenerationChunk
from zygos.runtime.bootstrap import build_runtime
from zygos.services.router import RouteChoice


def test_turn_deps_carry_duck_config_defaults():
    app = create_app(build_runtime())
    assert app.state.turn_deps.duck_gain == 0.2
    assert app.state.turn_deps.duck_timeout_s == 2.0


def test_turn_deps_carry_duck_config_overrides(tmp_path):
    p = tmp_path / "z.yaml"
    p.write_text(yaml.safe_dump(
        {"voice": {"tts": {"duck_gain": 0.5}, "duck_timeout_s": 1.0}}))
    app = create_app(build_runtime(p))
    assert app.state.turn_deps.duck_gain == 0.5
    assert app.state.turn_deps.duck_timeout_s == 1.0


def _drive_until(ws, predicate, frames):
    while True:
        f = json.loads(ws.receive_text())
        frames.append(f)
        if predicate(f):
            return f


def _wait_until(predicate, timeout=5.0):
    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        if predicate():
            return
        _time.sleep(0.005)
    raise AssertionError("timed out")


def _voice_app(tmp_path, model=None):
    p = tmp_path / "zygos.yaml"
    p.write_text(yaml.safe_dump({"voice": {"enabled": True, "stt": {"engine": "fake"}}}))
    rt = build_runtime(p)
    from zygos.providers.fake import FakeProvider
    from zygos.services.model import DefaultModelService
    from zygos.services.router import ProviderRouter, RouteChoice as RC
    if model is None:
        model = DefaultModelService(
            ProviderRouter([RC("fake", "m")], {"fake": FakeProvider(script=["ok"])}))
    rt = dataclasses.replace(rt, model_service=model, memory_service=None, tools=())
    return create_app(rt)


class _BlockingModel:
    """First stream() call blocks mid-generation until released, polling ctx.cancelled."""

    def __init__(self, release, texts):
        self._release = release
        self._texts = texts
        self._calls = 0

    def classify_task(self, prompt):
        return "simple"

    def select_model(self, classification=None):
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
        for w in words[1:]:
            yield GenerationChunk(text=w)
        yield GenerationChunk(text="", done=True)


def test_vad_speech_stops_turn_and_session_recovers(tmp_path):
    # AC3/AC5 over the real WS: audio.vad speech hard-stops an in-flight turn
    # (no prior onset needed), and the session is not wedged afterward (AC4 spirit —
    # the final/new-turn path is unchanged).
    release = threading.Event()
    app = _voice_app(tmp_path, model=_BlockingModel(release, ("first answer", "second answer")))
    with TestClient(app) as client:
        sid = client.post("/sessions").json()["id"]
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            frames = []
            # turn 1: typed, blocks mid-stream
            ws.send_text(json.dumps(
                {"channel": "chat", "type": "user_message", "payload": {"text": "go"}}))
            _drive_until(ws, lambda f: f["channel"] == "chat" and f["type"] == "turn.start", frames)
            _drive_until(ws, lambda f: f["channel"] == "chat" and f["type"] == "token", frames)

            # confirmed speech -> hard stop
            ws.send_text(json.dumps(
                {"channel": "control", "type": "audio.vad", "payload": {"state": "speech"}}))
            end1 = _drive_until(
                ws, lambda f: f["channel"] == "chat" and f["type"] == "turn.end", frames)
            assert end1["payload"].get("cancelled") is True

            release.set()  # safety valve

            # session recovers: a new turn runs to completion
            ws.send_text(json.dumps(
                {"channel": "chat", "type": "user_message", "payload": {"text": "again"}}))
            end2 = _drive_until(
                ws, lambda f: f["channel"] == "chat" and f["type"] == "turn.end"
                and not f["payload"].get("cancelled"), frames)
            assert "text" in end2["payload"]


def test_vad_onset_then_silence_ducks_and_restores(tmp_path):
    # AC1/AC2 wiring over the real WS. Grey-box: set session.speaking to represent an
    # active TTS synthesis (the speaking flag itself is unit-tested in test_speech.py),
    # so we deterministically prove ws -> _dispatch -> arm_duck/release_duck + config
    # plumbing without racing the fake synth's chunk timing.
    app = _voice_app(tmp_path)
    with TestClient(app) as client:
        sid = client.post("/sessions").json()["id"]
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            frames = []
            # sync: ping/pong proves the session exists on the app loop
            ws.send_text(json.dumps({"channel": "control", "type": "ping", "payload": {}}))
            _drive_until(ws, lambda f: f["type"] == "pong", frames)

            session = app.state.registry.get(sid)
            session.speaking = True  # grey-box: assistant is "speaking"

            ws.send_text(json.dumps(
                {"channel": "control", "type": "audio.vad", "payload": {"state": "onset"}}))
            duck = _drive_until(
                ws, lambda f: f["channel"] == "audio.out" and f["type"] == "tts.duck", frames)
            assert duck["payload"]["gain"] == 0.2

            ws.send_text(json.dumps(
                {"channel": "control", "type": "audio.vad", "payload": {"state": "silence"}}))
            unduck = _drive_until(
                ws, lambda f: f["channel"] == "audio.out" and f["type"] == "tts.unduck", frames)
            assert unduck["payload"]["gain"] == 1.0
            session.speaking = False


def test_vad_frames_are_no_ops_when_not_speaking(tmp_path):
    # AC7/AC8: with nothing speaking, onset/silence/speech emit no tts.* and a typed
    # turn still completes normally (default-off invariance for the duck half).
    app = _voice_app(tmp_path)
    with TestClient(app) as client:
        sid = client.post("/sessions").json()["id"]
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            frames = []
            for state in ("onset", "silence", "speech"):
                ws.send_text(json.dumps(
                    {"channel": "control", "type": "audio.vad", "payload": {"state": state}}))
            ws.send_text(json.dumps(
                {"channel": "chat", "type": "user_message", "payload": {"text": "hi"}}))
            end = _drive_until(
                ws, lambda f: f["channel"] == "chat" and f["type"] == "turn.end", frames)
            assert "text" in end["payload"]
            assert not any(f.get("channel") == "audio.out" for f in frames)  # no duck/unduck
