"""End-to-end TTS output over a real fake TTS sidecar (Voice Cycle 2, Task 10)."""
from __future__ import annotations

import dataclasses
import json

import yaml
from fastapi.testclient import TestClient

from zygos.api.app import create_app
from zygos.api.frames import AUDIO_TAG_OUT
from zygos.providers.fake import FakeProvider
from zygos.runtime.bootstrap import build_runtime
from zygos.services.model import DefaultModelService
from zygos.services.router import ProviderRouter, RouteChoice


def _voice_runtime(tmp_path, script, hold=False, env=None):
    p = tmp_path / "zygos.yaml"
    p.write_text(yaml.safe_dump(
        {"voice": {"enabled": True, "stt": {"engine": "fake"}, "tts": {"engine": "fake"}},
         "tools": {"enabled": []}}))  # force the plain streaming path (no agentic loop)
    rt = build_runtime(p)
    provider = FakeProvider(script=script)
    model = DefaultModelService(ProviderRouter([RouteChoice("fake", "m")], {"fake": provider}))
    return dataclasses.replace(rt, model_service=model, memory_service=None)


def _recv_until(ws, predicate, frames, audio):
    while True:
        msg = ws.receive()
        if "text" in msg and msg["text"] is not None:
            f = json.loads(msg["text"])
            frames.append(f)
            if predicate(f):
                return f
        elif "bytes" in msg and msg["bytes"] is not None:
            audio.append(msg["bytes"])


def test_typed_turn_is_spoken_when_speak_on(tmp_path):
    rt = _voice_runtime(tmp_path, script=["One. Two."])
    app = create_app(rt)
    with TestClient(app) as client:
        sid = client.post("/sessions").json()["id"]
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            ws.send_text(json.dumps({"channel": "control", "type": "audio.output",
                                     "payload": {"enabled": True}}))
            ws.send_text(json.dumps({"channel": "chat", "type": "user_message",
                                     "payload": {"text": "hi"}}))
            frames, audio = [], []
            _recv_until(ws, lambda f: f["channel"] == "chat" and f["type"] == "turn.end", frames, audio)
            begin = _recv_until(ws, lambda f: f.get("type") == "tts.begin", frames, audio)
            assert begin["payload"]["sample_rate"] == 24000
            end = _recv_until(ws, lambda f: f.get("type") == "tts.end", frames, audio)
            assert end["payload"]["reason"] == "complete"
            assert audio and all(b[0] == AUDIO_TAG_OUT for b in audio)


def test_speak_off_emits_no_audio(tmp_path):
    # default-off: no audio.output frame => byte-identical chat path
    rt = _voice_runtime(tmp_path, script=["hello"])
    app = create_app(rt)
    with TestClient(app) as client:
        sid = client.post("/sessions").json()["id"]
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            ws.send_text(json.dumps({"channel": "chat", "type": "user_message",
                                     "payload": {"text": "hi"}}))
            frames, audio = [], []
            _recv_until(ws, lambda f: f["channel"] == "chat" and f["type"] == "turn.end", frames, audio)
            # a follow-up ping proves the turn (incl. any speaking) fully drained
            ws.send_text(json.dumps({"channel": "control", "type": "ping", "payload": {}}))
            _recv_until(ws, lambda f: f.get("type") == "pong", frames, audio)
            assert audio == []
            assert not any(f.get("type", "").startswith("tts.") for f in frames)


def test_barge_in_cancels_in_flight_speech(tmp_path):
    # HOLD mode keeps synthesis in-flight (one chunk, then wait) so the second
    # user_message demonstrably barges in on the still-speaking first turn.
    import os
    os.environ["ZYGOS_FAKE_TTS_HOLD"] = "1"
    try:
        rt = _voice_runtime(tmp_path, script=["First reply.", "Second reply."])
        app = create_app(rt)
        with TestClient(app) as client:
            sid = client.post("/sessions").json()["id"]
            with client.websocket_connect(f"/ws/session/{sid}") as ws:
                ws.send_text(json.dumps({"channel": "control", "type": "audio.output",
                                         "payload": {"enabled": True}}))
                ws.send_text(json.dumps({"channel": "chat", "type": "user_message",
                                         "payload": {"text": "one"}}))
                frames, audio = [], []
                # wait until turn 1 is speaking (tts.begin seen)
                _recv_until(ws, lambda f: f.get("type") == "tts.begin", frames, audio)
                # barge in
                ws.send_text(json.dumps({"channel": "chat", "type": "user_message",
                                         "payload": {"text": "two"}}))
                end1 = _recv_until(ws, lambda f: f.get("type") == "tts.end", frames, audio)
                assert end1["payload"]["reason"] == "cancelled"
    finally:
        os.environ.pop("ZYGOS_FAKE_TTS_HOLD", None)
