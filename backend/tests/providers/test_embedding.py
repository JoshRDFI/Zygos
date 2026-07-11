import pytest

from zygos.providers.embedding import Embedder
from zygos.providers.types import EmbedRequest, EmbedResult, Usage


def test_embed_request_and_result_are_frozen_and_strict():
    req = EmbedRequest(model="m", texts=("a", "b"))
    assert req.texts == ("a", "b")
    with pytest.raises(Exception):
        req.texts = ("c",)  # frozen
    with pytest.raises(Exception):
        EmbedRequest(model="m", texts=("a",), extra="x")  # extra forbidden

    res = EmbedResult(vectors=((0.1, 0.2), (0.3, 0.4)), model="m", dim=2)
    assert res.dim == 2
    assert res.usage == Usage()
    with pytest.raises(Exception):
        res.dim = 3  # frozen


def test_embedder_is_runtime_checkable():
    class Good:
        name = "good"
        async def embed(self, request: EmbedRequest) -> EmbedResult:
            return EmbedResult(vectors=(), model="m", dim=0)

    class Bad:
        name = "bad"
        async def generate(self, request):  # not an embedder
            return None

    assert isinstance(Good(), Embedder)
    assert not isinstance(Bad(), Embedder)


def test_embedding_capability_registers_and_validates():
    import httpx
    from zygos.providers.anthropic import AnthropicProvider
    from zygos.providers.base import ProviderSettings
    from zygos.runtime.capabilities import Capability, CapabilityRegistry

    class _Embedder:
        name = "e"
        async def embed(self, request: EmbedRequest) -> EmbedResult:
            return EmbedResult(vectors=(), model="e", dim=0)

    reg = CapabilityRegistry()
    reg.register(Capability.EMBEDDING, _Embedder(), priority=0)
    assert reg.resolve(Capability.EMBEDDING)[0].provider == "e"

    # A chat-only provider (no embed) is rejected for EMBEDDING.
    anthropic = AnthropicProvider(
        ProviderSettings(base_url="https://api.anthropic.com"),
        httpx.AsyncClient(),
    )
    with pytest.raises(ValueError):
        reg.register(Capability.EMBEDDING, anthropic, priority=0)
