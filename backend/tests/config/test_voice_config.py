from zygos.config.schema import ZygosConfig, VoiceConfig


def test_voice_defaults_off():
    cfg = ZygosConfig()
    assert isinstance(cfg.voice, VoiceConfig)
    assert cfg.voice.enabled is False
    assert cfg.voice.stt.engine == "fake"


def test_voice_can_be_enabled_via_dict():
    cfg = ZygosConfig.model_validate({"voice": {"enabled": True, "stt": {"engine": "fake"}}})
    assert cfg.voice.enabled is True


def test_unknown_voice_field_rejected():
    import pytest
    with pytest.raises(Exception):
        ZygosConfig.model_validate({"voice": {"enabled": True, "bogus": 1}})


def test_voice_config_has_tts_defaulting_to_fake():
    v = VoiceConfig()
    assert v.tts.engine == "fake"


def test_voice_config_rejects_unknown_tts_engine():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        VoiceConfig(tts={"engine": "kokoro"})  # not yet a valid literal


def test_duck_config_defaults():
    v = VoiceConfig()
    assert v.tts.duck_gain == 0.2
    assert v.duck_timeout_s == 2.0


def test_duck_config_overrides():
    cfg = ZygosConfig.model_validate(
        {"voice": {"tts": {"duck_gain": 0.5}, "duck_timeout_s": 1.0}})
    assert cfg.voice.tts.duck_gain == 0.5
    assert cfg.voice.duck_timeout_s == 1.0
