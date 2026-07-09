import pytest

from zygos.providers.base import Provider
from zygos.runtime.capabilities import CAPABILITY_CONTRACTS, Capability, CapabilityRegistry


def test_capability_enum_is_the_closed_rfc0003_set():
    assert {c.value for c in Capability} == {
        "local_inference",
        "vision",
        "speech_to_text",
        "text_to_speech",
        "web_search",
        "image_generation",
        "scheduling",
        "filesystem_access",
    }


def test_only_local_inference_is_contracted():
    assert CAPABILITY_CONTRACTS == {Capability.LOCAL_INFERENCE: Provider}


def test_all_providers_declare_local_inference():
    from zygos.providers.anthropic import AnthropicProvider
    from zygos.providers.fake import FakeProvider
    from zygos.providers.ollama import OllamaProvider
    from zygos.providers.openai import OpenAIProvider
    from zygos.providers.vllm import VllmProvider

    for cls in (FakeProvider, OllamaProvider, OpenAIProvider, AnthropicProvider, VllmProvider):
        assert cls.capabilities == frozenset({Capability.LOCAL_INFERENCE})


class _Conforming:
    name = "conf"

    async def generate(self, request):  # pragma: no cover - shape only
        ...

    def stream(self, request):  # pragma: no cover - shape only
        ...


class _MissingGenerate:
    name = "broken"

    def stream(self, request):  # pragma: no cover - shape only
        ...


def test_register_accepts_a_conforming_provider():
    registry = CapabilityRegistry()
    registry.register(Capability.LOCAL_INFERENCE, _Conforming(), priority=0)  # no raise


def test_register_rejects_contract_mismatch():
    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="contract"):
        registry.register(Capability.LOCAL_INFERENCE, _MissingGenerate(), priority=0)


def test_register_rejects_uncontracted_capability():
    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="no contract"):
        registry.register(Capability.VISION, _Conforming(), priority=0)
