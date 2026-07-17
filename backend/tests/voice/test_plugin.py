import sys
from pathlib import Path

import pytest

from zygos.voice.errors import VoiceError
from zygos.voice.plugin import SttPlugin, TtsPlugin
from zygos.voice.types import SttEngineSpec, TtsEngineSpec

FAKE = SttEngineSpec(name="fake", argv=(sys.executable, "-m", "zygos.voice.sidecar.fake_stt"))
_SILENT = Path(__file__).parent / "support" / "silent_worker.py"


async def test_start_completes_after_health_ok():
    p = SttPlugin(FAKE, readiness_timeout_s=5.0)
    try:
        await p.start()          # fake worker answers health immediately
        assert p.health().alive is True
    finally:
        await p.aclose()


async def test_start_times_out_when_worker_never_reports_ready():
    spec = SttEngineSpec(name="silent", argv=(sys.executable, str(_SILENT)))
    p = SttPlugin(spec, readiness_timeout_s=0.3)
    with pytest.raises(VoiceError):
        await p.start()
    await p.aclose()


async def test_tts_plugin_start_completes_health_handshake():
    spec = TtsEngineSpec(name="fake", argv=(sys.executable, "-m", "zygos.voice.sidecar.fake_tts"))
    plugin = TtsPlugin(spec, readiness_timeout_s=10.0)
    await plugin.start()
    try:
        assert plugin.health().alive is True
    finally:
        await plugin.aclose()


async def test_transcription_cancel_drains_stranded_frames_off_shared_connection():
    """Barge-in on STT: Transcription.cancel must consume the worker's in-flight
    partial and terminal so the next utterance starts clean on the shared conn."""
    import asyncio
    from zygos.voice.ipc import connect, listen
    from zygos.voice.plugin import Transcription

    listener = await listen()
    client = await connect(listener.address)
    server = await listener.accept()  # plays the worker side
    try:
        tr = Transcription(client)
        await tr._ensure_started()               # consumer -> start
        _k, body = await server.recv()
        assert body["type"] == "start"
        await server.send_control({"type": "partial", "text": "h"})  # in flight

        async def worker_after_cancel():
            _k, b = await server.recv()
            assert b["type"] == "cancel"
            await server.send_control({"type": "cancelled"})

        await asyncio.gather(tr.cancel(), worker_after_cancel())

        # connection is clean: the next frame read is the next utterance's
        await server.send_control({"type": "sentinel"})
        kind, b = await client.recv()
        assert kind == "control" and b == {"type": "sentinel"}
    finally:
        await client.close()
        await server.close()
        await listener.close()
