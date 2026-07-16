import sys

import pytest

from zygos.config.schema import SttConfig
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.voice.contract import SpeechToText
from zygos.voice.service import VoiceService, build_stt_plugin


def _ctx():
    return root_context(InProcessEventBus(), session_id="s1")


async def test_plugin_satisfies_contract():
    plugin = build_stt_plugin(SttConfig())
    assert isinstance(plugin, SpeechToText)
    assert plugin.name == "fake"


async def test_unknown_engine_raises():
    # Literal typing blocks bad values at the schema layer; bypass it with
    # model_construct to exercise build_stt_plugin's own defensive branch.
    bad_config = SttConfig.model_construct(engine="whisper_cpp")
    with pytest.raises(Exception):
        build_stt_plugin(bad_config)  # no worker this cycle


async def test_transcription_partials_then_final_drives_events():
    plugin = build_stt_plugin(SttConfig())
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


async def test_concurrent_sessions_ok_false_for_local_sidecar_engine():
    svc = VoiceService(stt=build_stt_plugin(SttConfig()))
    assert svc.concurrent_sessions_ok is False


async def test_concurrent_sessions_ok_true_when_engine_marked_safe():
    from zygos.voice.plugin import SttPlugin
    from zygos.voice.types import SttEngineSpec

    spec = SttEngineSpec(name="api", argv=("x",), concurrent_safe=True)
    svc = VoiceService(stt=SttPlugin(spec))  # no start(): reads spec only, spawns nothing
    assert svc.concurrent_sessions_ok is True


async def test_concurrent_sessions_ok_vacuously_true_without_engines():
    svc = VoiceService(stt=None)
    assert svc.concurrent_sessions_ok is True  # nothing shared -> no gate needed


def test_build_stt_plugin_fake_default():
    p = build_stt_plugin(SttConfig())
    assert p.name == "fake"


def test_build_stt_plugin_faster_whisper_env():
    p = build_stt_plugin(SttConfig(engine="faster_whisper", model="base.en",
                                   compute_type="int8", download_root="/models/fw"))
    assert p.name == "faster_whisper"
    spec = p._spec  # test reaches into impl to assert the launch vector + env
    assert spec.argv == (sys.executable, "-m", "zygos.voice.sidecar.faster_whisper")
    assert spec.env["ZYGOS_STT_MODEL"] == "base.en"
    assert spec.env["ZYGOS_STT_COMPUTE_TYPE"] == "int8"
    assert spec.env["ZYGOS_STT_DEVICE"] == "cpu"
    assert spec.env["ZYGOS_STT_DOWNLOAD_ROOT"] == "/models/fw"
