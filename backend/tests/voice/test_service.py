import pytest

from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.voice.contract import SpeechToText
from zygos.voice.service import VoiceService, build_stt_plugin


def _ctx():
    return root_context(InProcessEventBus(), session_id="s1")


async def test_plugin_satisfies_contract():
    plugin = build_stt_plugin("fake")
    assert isinstance(plugin, SpeechToText)
    assert plugin.name == "fake"


async def test_unknown_engine_raises():
    with pytest.raises(Exception):
        build_stt_plugin("whisper_cpp")  # no worker this cycle


async def test_transcription_partials_then_final_drives_events():
    plugin = build_stt_plugin("fake")
    svc = VoiceService(stt=plugin)
    await svc.start(_ctx())
    try:
        tr = svc.begin_transcription(_ctx())
        events = []

        async def consume():
            async for ev in tr.events():
                events.append(ev)

        import asyncio
        consumer = asyncio.create_task(consume())
        for _ in range(3):
            await tr.push(b"\x00" * 640)
        await tr.endpoint()
        await consumer
        kinds = [e.kind for e in events]
        assert "partial" in kinds and kinds[-1] == "final"
        assert events[-1].text  # non-empty transcript
    finally:
        await svc.aclose()


async def test_service_reports_unavailable_without_plugin():
    svc = VoiceService(stt=None)
    assert svc.stt_available is False
    assert svc.snapshot().stt is None
    with pytest.raises(Exception):
        svc.begin_transcription(_ctx())


async def test_voice_service_synthesizes_when_tts_present():
    from zygos.runtime.context import root_context
    from zygos.runtime.events import InProcessEventBus
    from zygos.voice.service import VoiceService, build_tts_plugin

    tts = build_tts_plugin("fake")
    svc = VoiceService(stt=None, tts=tts)
    assert svc.tts_available is True
    assert svc.tts_format.sample_rate == 24000
    ctx = root_context(InProcessEventBus())
    await svc.start(ctx)
    try:
        synth = svc.synthesize_stream(ctx, "Hi there.")
        chunks = [c async for c in synth.chunks()]
        await synth.aclose()
        assert chunks and svc.snapshot().tts.alive is True
    finally:
        await svc.aclose()


async def test_voice_service_without_tts_raises():
    from zygos.voice.errors import VoiceError
    from zygos.voice.service import VoiceService
    svc = VoiceService(stt=None, tts=None)
    assert svc.tts_available is False and svc.tts_format is None
    ctx = __import__("zygos.runtime.context", fromlist=["root_context"]).root_context(
        __import__("zygos.runtime.events", fromlist=["InProcessEventBus"]).InProcessEventBus())
    import pytest
    with pytest.raises(VoiceError):
        svc.synthesize_stream(ctx, "x")
