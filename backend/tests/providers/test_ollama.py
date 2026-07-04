import json

import httpx

from zygos.providers.base import ProviderSettings
from zygos.providers.ollama import OllamaProvider

from .conftest import contract_request, make_client, run_error_contract

SETTINGS = ProviderSettings(base_url="http://localhost:11434")


def _make(client: httpx.AsyncClient) -> OllamaProvider:
    return OllamaProvider(settings=SETTINGS, client=client)


async def test_generate_parses_ollama_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        assert body["stream"] is False
        assert body["options"]["num_predict"] == 1024
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "pong"},
                "done": True,
                "prompt_eval_count": 7,
                "eval_count": 3,
            },
        )

    result = await _make(make_client(handler)).generate(contract_request())
    assert result.text == "pong"
    assert result.provider == "ollama"
    assert result.usage.input_tokens == 7
    assert result.usage.output_tokens == 3


async def test_stream_parses_ndjson_lines():
    lines = [
        json.dumps({"message": {"content": "po"}, "done": False}),
        json.dumps({"message": {"content": "ng"}, "done": False}),
        json.dumps({"message": {"content": ""}, "done": True, "eval_count": 2}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, text="\n".join(lines) + "\n")

    chunks = [c async for c in _make(make_client(handler)).stream(contract_request())]
    assert [c.text for c in chunks[:-1]] == ["po", "ng"]
    assert chunks[-1].done is True


async def test_error_contract():
    await run_error_contract(_make)
