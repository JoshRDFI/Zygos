"""End-to-end synthesis through a real fake TTS sidecar via TtsPlugin."""
from __future__ import annotations

import pytest

from zygos.runtime.context import CancelToken, root_context
from zygos.runtime.events import InProcessEventBus
from zygos.voice.contract import Synthesis, TextToSpeech
from zygos.voice.errors import SynthesisFailed
from zygos.voice.service import build_tts_plugin


def _ctx(cancel=None):
    ctx = root_context(InProcessEventBus())
    return ctx.child("t", cancel=cancel) if cancel else ctx


async def test_plugin_satisfies_contract_and_synthesizes():
    plugin = build_tts_plugin("fake")
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
    plugin = build_tts_plugin("fake")
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
