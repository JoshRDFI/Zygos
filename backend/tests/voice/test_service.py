import sys
from pathlib import Path

import pytest

from zygos.config.schema import SttConfig, TtsConfig
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.voice.contract import SpeechToText
from zygos.voice.device import DEFAULT_GPU_VENV, SETUP_HINT, venv_python
from zygos.voice.service import VoiceService, build_stt_plugin, build_tts_plugin


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
    from zygos.voice.service import VoiceService

    tts = build_tts_plugin(TtsConfig())
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


def test_build_tts_plugin_kokoro_spec_env():
    plugin = build_tts_plugin(TtsConfig(engine="kokoro", voice="am_adam", download_root="/models/k"))
    spec = plugin._spec
    assert spec.name == "kokoro"
    assert spec.argv[-1] == "zygos.voice.sidecar.kokoro"
    assert spec.env["ZYGOS_TTS_VOICE"] == "am_adam"
    assert spec.env["ZYGOS_TTS_LANG"] == "en-us"
    assert spec.env["ZYGOS_TTS_DOWNLOAD_ROOT"] == "/models/k"
    assert spec.concurrent_safe is False


def test_build_tts_plugin_kokoro_defaults_download_root():
    plugin = build_tts_plugin(TtsConfig(engine="kokoro"))
    assert plugin._spec.env["ZYGOS_TTS_DOWNLOAD_ROOT"].endswith("kokoro")


def test_build_tts_plugin_fake_still_works():
    assert build_tts_plugin(TtsConfig()).name == "fake"


def test_build_tts_plugin_kokoro_cpu_sets_device_env_and_no_fallback():
    plugin = build_tts_plugin(TtsConfig(engine="kokoro"))
    assert plugin._spec.env["ZYGOS_TTS_DEVICE"] == "cpu"
    assert plugin._spec.argv[0] == sys.executable
    assert plugin._fallback_spec is None
    assert plugin.health().requested_device == "cpu"


def test_build_tts_plugin_kokoro_cuda_with_venv_uses_it_and_has_cpu_fallback(tmp_path):
    py = tmp_path / "python"
    py.write_text("")
    plugin = build_tts_plugin(TtsConfig(engine="kokoro", device="cuda", worker_python=str(py)))
    assert plugin._spec.argv[0] == str(py)
    assert plugin._spec.device == "cuda" and plugin._spec.env["ZYGOS_TTS_DEVICE"] == "cuda"
    fb = plugin._fallback_spec
    assert fb.argv[0] == sys.executable and fb.device == "cpu" and fb.env["ZYGOS_TTS_DEVICE"] == "cpu"
    assert fb.env["ZYGOS_TTS_VOICE"] == plugin._spec.env["ZYGOS_TTS_VOICE"]


def test_build_tts_plugin_kokoro_cuda_without_venv_runs_cpu_with_reason(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)   # no .zygos/venvs/voice-gpu here
    plugin = build_tts_plugin(TtsConfig(engine="kokoro", device="cuda"))
    assert plugin._spec.argv[0] == sys.executable and plugin._spec.device == "cpu"
    assert plugin._fallback_spec is None
    h = plugin.health()
    assert h.requested_device == "cuda" and "setup-gpu" in h.fallback_reason


def test_build_tts_plugin_kokoro_managed_venv_cuda_sets_retry_hint(tmp_path, monkeypatch):
    # A broken/half-built managed venv fails readiness at start(); the retry
    # reason should point at the fix (setup-gpu) since this launch used the
    # managed venv (worker_python not overridden).
    monkeypatch.chdir(tmp_path)
    managed_py = Path(venv_python(DEFAULT_GPU_VENV))
    managed_py.parent.mkdir(parents=True)
    managed_py.write_text("")
    plugin = build_tts_plugin(TtsConfig(engine="kokoro", device="cuda"))
    assert plugin._spec.device == "cuda"
    assert plugin._retry_hint == SETUP_HINT


def test_build_tts_plugin_kokoro_cuda_worker_python_override_no_retry_hint(tmp_path):
    # A user-supplied worker_python isn't the managed venv setup-gpu builds, so
    # a retry hint pointing at setup-gpu would be misleading.
    py = tmp_path / "python"
    py.write_text("")
    plugin = build_tts_plugin(TtsConfig(engine="kokoro", device="cuda", worker_python=str(py)))
    assert plugin._retry_hint is None
