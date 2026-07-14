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


def test_text_to_speech_still_has_no_contract():
    # Cycle 1 does not add TTS; registering it must still fail.
    reg = CapabilityRegistry()
    with pytest.raises(ValueError):
        reg.register(Capability.TEXT_TO_SPEECH, _StubStt(), priority=0)
