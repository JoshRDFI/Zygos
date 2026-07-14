import pytest

from zygos.runtime.capabilities import CAPABILITY_CONTRACTS, Capability, CapabilityRegistry
from zygos.voice.contract import Synthesis, TextToSpeech, TtsHealth


class _StubTts:
    name = "stub"

    def synthesize(self, ctx, text):  # pragma: no cover - shape only
        raise NotImplementedError

    def health(self) -> TtsHealth:
        return TtsHealth(engine="stub", device="cpu", alive=True)


def test_text_to_speech_has_a_contract():
    assert CAPABILITY_CONTRACTS[Capability.TEXT_TO_SPEECH] is TextToSpeech


def test_stub_satisfies_protocol_and_registers():
    assert isinstance(_StubTts(), TextToSpeech)
    reg = CapabilityRegistry()
    reg.register(Capability.TEXT_TO_SPEECH, _StubTts(), priority=0)
    bindings = reg.resolve(Capability.TEXT_TO_SPEECH)
    assert bindings and bindings[0].provider == "stub"


def test_non_conforming_object_is_rejected():
    reg = CapabilityRegistry()
    with pytest.raises(ValueError):
        reg.register(Capability.TEXT_TO_SPEECH, object(), priority=0)


def test_tts_health_is_frozen():
    h = TtsHealth(engine="stub", device="cpu", alive=True)
    with pytest.raises(Exception):
        h.engine = "other"
