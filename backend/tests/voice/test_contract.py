import pytest

from zygos.runtime.capabilities import Capability, CapabilityRegistry, CAPABILITY_CONTRACTS
from zygos.voice.contract import SpeechToText, SttHealth


class _StubStt:
    name = "stub"

    def begin(self, ctx):  # pragma: no cover - shape only
        raise NotImplementedError

    def health(self) -> SttHealth:
        return SttHealth(engine="stub", device="cpu", alive=True)


def test_speech_to_text_has_a_contract():
    assert CAPABILITY_CONTRACTS[Capability.SPEECH_TO_TEXT] is SpeechToText


def test_stub_satisfies_protocol_and_registers():
    assert isinstance(_StubStt(), SpeechToText)
    reg = CapabilityRegistry()
    reg.register(Capability.SPEECH_TO_TEXT, _StubStt(), priority=0)
    bindings = reg.resolve(Capability.SPEECH_TO_TEXT)
    assert bindings and bindings[0].provider == "stub"


def test_text_to_speech_now_has_a_contract():
    # Cycle 2 adds the TTS contract; a conforming engine registers.
    from zygos.voice.contract import TextToSpeech
    assert CAPABILITY_CONTRACTS[Capability.TEXT_TO_SPEECH] is TextToSpeech


def test_stt_health_device_fields_default():
    from zygos.voice.contract import SttHealth
    h = SttHealth(engine="e", device="cpu", alive=True)
    assert h.requested_device == "cpu" and h.fallback_reason is None


def test_tts_health_carries_requested_and_reason():
    from zygos.voice.contract import TtsHealth
    h = TtsHealth(engine="kokoro", device="cpu", alive=True,
                  requested_device="cuda", fallback_reason="no venv")
    assert (h.device, h.requested_device, h.fallback_reason) == ("cpu", "cuda", "no venv")
