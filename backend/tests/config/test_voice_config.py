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
