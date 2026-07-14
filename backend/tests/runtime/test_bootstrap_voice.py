from zygos.config.schema import ZygosConfig
from zygos.runtime.bootstrap import build_runtime
from zygos.runtime.capabilities import Capability


def _write_cfg(tmp_path, enabled):
    import yaml
    p = tmp_path / "zygos.yaml"
    p.write_text(yaml.safe_dump({"voice": {"enabled": enabled, "stt": {"engine": "fake"}}}))
    return p


def test_voice_off_by_default():
    rt = build_runtime()
    assert rt.voice_service is None
    assert Capability.SPEECH_TO_TEXT not in rt.capability_registry.snapshot().bindings


def test_voice_on_builds_service_and_registers_capability(tmp_path):
    rt = build_runtime(_write_cfg(tmp_path, True))
    assert rt.voice_service is not None
    assert rt.voice_service.stt_available is True
    bindings = rt.capability_registry.snapshot().bindings
    assert Capability.SPEECH_TO_TEXT in bindings
    assert bindings[Capability.SPEECH_TO_TEXT][0].provider == "fake"


def _write_cfg_tts(tmp_path):
    import yaml
    p = tmp_path / "zygos.yaml"
    p.write_text(yaml.safe_dump(
        {"voice": {"enabled": True, "stt": {"engine": "fake"}, "tts": {"engine": "fake"}}}))
    return p


def test_voice_on_builds_and_registers_tts(tmp_path):
    rt = build_runtime(_write_cfg_tts(tmp_path))
    assert rt.voice_service is not None
    assert rt.voice_service.tts_available is True
    bindings = rt.capability_registry.snapshot().bindings
    assert Capability.TEXT_TO_SPEECH in bindings
    assert bindings[Capability.TEXT_TO_SPEECH][0].provider == "fake"


def test_voice_off_has_no_tts_binding():
    rt = build_runtime()  # default config: voice off
    assert rt.voice_service is None
    assert Capability.TEXT_TO_SPEECH not in rt.capability_registry.snapshot().bindings
