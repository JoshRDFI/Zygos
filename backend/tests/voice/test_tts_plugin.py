"""End-to-end synthesis through a real fake TTS sidecar via TtsPlugin."""
from __future__ import annotations

import pytest

from zygos.config.schema import TtsConfig
from zygos.runtime.context import CancelToken, root_context
from zygos.runtime.events import InProcessEventBus
from zygos.voice.contract import Synthesis, TextToSpeech
from zygos.voice.errors import SynthesisFailed
from zygos.voice.service import build_tts_plugin


def _ctx(cancel=None):
    ctx = root_context(InProcessEventBus())
    return ctx.child("t", cancel=cancel) if cancel else ctx


async def test_plugin_satisfies_contract_and_synthesizes():
    plugin = build_tts_plugin(TtsConfig())
    assert isinstance(plugin, TextToSpeech)
    await plugin.start()
    try:
        synth = plugin.synthesize(_ctx(), "One. Two.")
        assert isinstance(synth, Synthesis)
        chunks = [c async for c in synth.chunks()]
        await synth.aclose()
        assert len(chunks) == 2 and all(set(c) == {0} for c in chunks)
        assert plugin.output_format.sample_rate == 24000
        assert plugin.health().alive is True
    finally:
        await plugin.aclose()


async def test_cancel_stops_a_held_synthesis(monkeypatch):
    monkeypatch.setenv("ZYGOS_FAKE_TTS_HOLD", "1")
    plugin = build_tts_plugin(TtsConfig())
    await plugin.start()
    try:
        cancel = CancelToken()
        synth = plugin.synthesize(_ctx(cancel), "One. Two. Three.")
        got = []
        async for c in synth.chunks():
            got.append(c)
            cancel.trip()  # trip after the first (held) chunk
        await synth.aclose()
        assert len(got) == 1  # cooperative cancel ended the stream
    finally:
        await plugin.aclose()


async def test_synthesis_cancel_drains_stranded_frames_off_shared_connection():
    """The bug: after a barge-in mid-stream, Synthesis.cancel must consume the
    worker's in-flight PCM and terminal so the NEXT frame on the shared
    connection belongs to the next utterance, not a stale tail."""
    import asyncio
    from zygos.voice.ipc import connect, listen
    from zygos.voice.plugin import Synthesis as ConcreteSynthesis

    listener = await listen()
    client = await connect(listener.address)
    server = await listener.accept()  # plays the worker side
    try:
        synth = ConcreteSynthesis(client, _ctx(), text="hi", sample_rate=24000)
        await synth._ensure_started()            # consumer -> synthesize
        _k, body = await server.recv()
        assert body["type"] == "synthesize"
        await server.send_pcm(b"\x00\x00")       # a chunk already in flight

        async def worker_after_cancel():
            _k, b = await server.recv()
            assert b["type"] == "cancel"
            await server.send_pcm(b"\x11\x11")   # a straggler produced before stop
            await server.send_control({"type": "cancelled"})

        # barge-in: cancel must drain the in-flight pcm, the straggler, and the terminal
        await asyncio.gather(synth.cancel(), worker_after_cancel())

        # connection is clean: the next frame read is the next utterance's
        await server.send_control({"type": "sentinel"})
        kind, b = await client.recv()
        assert kind == "control" and b == {"type": "sentinel"}
    finally:
        await client.close()
        await server.close()
        await listener.close()
