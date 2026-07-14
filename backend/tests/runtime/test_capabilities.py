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
        "embedding",
    }


def test_only_contracted_capabilities_are_registrable():
    from zygos.providers.embedding import Embedder
    from zygos.voice.contract import SpeechToText, TextToSpeech
    assert CAPABILITY_CONTRACTS == {
        Capability.LOCAL_INFERENCE: Provider,
        Capability.EMBEDDING: Embedder,
        Capability.SPEECH_TO_TEXT: SpeechToText,
        Capability.TEXT_TO_SPEECH: TextToSpeech,
    }


def test_all_providers_declare_local_inference():
    from zygos.providers.anthropic import AnthropicProvider
    from zygos.providers.fake import FakeProvider
    from zygos.providers.ollama import OllamaProvider
    from zygos.providers.openai import OpenAIProvider
    from zygos.providers.vllm import VllmProvider

    for cls in (FakeProvider, OllamaProvider, OpenAIProvider, AnthropicProvider, VllmProvider):
        assert Capability.LOCAL_INFERENCE in cls.capabilities


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


def _named(provider_name: str):
    class _P:
        name = provider_name

        async def generate(self, request):  # pragma: no cover - shape only
            ...

        def stream(self, request):  # pragma: no cover - shape only
            ...

    return _P()


def test_resolve_ranks_by_priority_and_filters_unhealthy():
    healthy = {"primary": False, "fallback": True}
    registry = CapabilityRegistry(health_of=lambda name: healthy[name])
    registry.register(Capability.LOCAL_INFERENCE, _named("primary"), priority=0)
    registry.register(Capability.LOCAL_INFERENCE, _named("fallback"), priority=1)

    resolved = registry.resolve(Capability.LOCAL_INFERENCE)

    assert [b.provider for b in resolved] == ["fallback"]  # unhealthy top-priority skipped


def test_resolve_orders_healthy_by_priority():
    registry = CapabilityRegistry(health_of=lambda name: True)
    registry.register(Capability.LOCAL_INFERENCE, _named("b"), priority=1)
    registry.register(Capability.LOCAL_INFERENCE, _named("a"), priority=0)

    assert [b.provider for b in registry.resolve(Capability.LOCAL_INFERENCE)] == ["a", "b"]


def test_resolve_holds_no_bus_dependency():
    # AC2: the registry takes no bus and holds no subscription; resolution is
    # identical regardless of any subscriber because there is no bus to attach to.
    registry = CapabilityRegistry(health_of=lambda name: True)
    registry.register(Capability.LOCAL_INFERENCE, _named("a"), priority=0)
    first = registry.resolve(Capability.LOCAL_INFERENCE)
    assert not hasattr(registry, "_bus")
    assert registry.resolve(Capability.LOCAL_INFERENCE) == first


def test_snapshot_reports_priority_and_last_known_health():
    healthy = {"a": True, "b": False}
    registry = CapabilityRegistry(health_of=lambda name: healthy[name])
    registry.register(Capability.LOCAL_INFERENCE, _named("a"), priority=0)
    registry.register(Capability.LOCAL_INFERENCE, _named("b"), priority=1)

    binds = registry.snapshot().bindings[Capability.LOCAL_INFERENCE]

    assert [(b.provider, b.priority, b.healthy) for b in binds] == [
        ("a", 0, True),
        ("b", 1, False),
    ]
