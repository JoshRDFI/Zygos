import json

import httpx

from zygos.providers.base import ProviderSettings
from zygos.providers.openai import OpenAIProvider

from .conftest import contract_request, make_client, run_error_contract

SETTINGS = ProviderSettings(base_url="https://api.openai.com/v1", api_key="sk-test")


def _make(client: httpx.AsyncClient) -> OpenAIProvider:
    return OpenAIProvider(settings=SETTINGS, client=client)


async def test_generate_parses_chat_completion():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer sk-test"
        body = json.loads(request.content)
        assert body["stream"] is False
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "pong"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    result = await _make(make_client(handler)).generate(contract_request())
    assert result.text == "pong"
    assert result.provider == "openai"
    assert result.usage.input_tokens == 5
    assert result.usage.output_tokens == 2


async def test_stream_parses_sse():
    events = [
        'data: {"choices": [{"delta": {"content": "po"}}]}',
        'data: {"choices": [{"delta": {"content": "ng"}}]}',
        'data: {"choices": [{"delta": {}}]}',
        "data: [DONE]",
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, text="\n".join(events) + "\n")

    chunks = [c async for c in _make(make_client(handler)).stream(contract_request())]
    assert [c.text for c in chunks[:-1]] == ["po", "ng"]
    assert chunks[-1].done is True


async def test_error_contract():
    await run_error_contract(_make)
