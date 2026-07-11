import json

import httpx

from zygos.providers.base import ProviderSettings
from zygos.providers.vllm import VllmProvider

from .conftest import contract_request, make_client, run_error_contract

# Local vLLM: keyless, localhost base_url, arbitrary local model names.
SETTINGS = ProviderSettings(base_url="http://localhost:8000/v1")


def _make(client: httpx.AsyncClient) -> VllmProvider:
    return VllmProvider(settings=SETTINGS, client=client)


async def test_generate_is_keyless_and_local():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "localhost"
        assert request.url.path == "/v1/chat/completions"
        assert "authorization" not in request.headers
        body = json.loads(request.content)
        assert body["model"] == "test-model"  # local model name passes through verbatim
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "local pong"}}], "usage": {}},
        )

    result = await _make(make_client(handler)).generate(contract_request())
    assert result.text == "local pong"
    assert result.provider == "vllm"


async def test_local_vllm_omits_max_tokens_when_none():
    # ADR-0006: vLLM is local -> uncapped by default (no max_tokens sent).
    def handler(request: httpx.Request) -> httpx.Response:
        assert "max_tokens" not in json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})

    await _make(make_client(handler)).generate(contract_request())


async def test_error_contract():
    await run_error_contract(_make)


def test_vllm_declares_embedding_and_inherits_embed():
    from zygos.providers.vllm import VllmProvider
    from zygos.runtime.capabilities import Capability

    assert Capability.EMBEDDING in VllmProvider.capabilities
    assert VllmProvider.embed is not None  # inherited from OpenAIProvider
