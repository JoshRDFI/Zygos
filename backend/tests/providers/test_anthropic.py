import json

import httpx

from zygos.providers.anthropic import AnthropicProvider
from zygos.providers.base import DEFAULT_CLOUD_MAX_TOKENS, ProviderSettings
from zygos.providers.types import GenerationRequest, Message

from .conftest import contract_request, make_client, run_error_contract

SETTINGS = ProviderSettings(base_url="https://api.anthropic.com", api_key="sk-ant-test")


def _make(client: httpx.AsyncClient) -> AnthropicProvider:
    return AnthropicProvider(settings=SETTINGS, client=client)


async def test_generate_extracts_system_and_parses_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "sk-ant-test"
        assert request.headers["anthropic-version"] == "2023-06-01"
        body = json.loads(request.content)
        assert body["system"] == "be terse"
        assert all(m["role"] != "system" for m in body["messages"])
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "pong"}],
                "usage": {"input_tokens": 9, "output_tokens": 1},
            },
        )

    request = GenerationRequest(
        model="test-model",
        messages=(
            Message(role="system", content="be terse"),
            Message(role="user", content="ping"),
        ),
    )
    result = await _make(make_client(handler)).generate(request)
    assert result.text == "pong"
    assert result.usage.input_tokens == 9


async def test_stream_parses_event_deltas():
    events = [
        'data: {"type": "message_start"}',
        'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "po"}}',
        'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ng"}}',
        'data: {"type": "message_stop"}',
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "sk-ant-test"
        assert request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(200, text="\n".join(events) + "\n")

    chunks = [c async for c in _make(make_client(handler)).stream(contract_request())]
    assert [c.text for c in chunks[:-1]] == ["po", "ng"]
    assert chunks[-1].done is True


async def test_multi_system_messages_joined_with_newline():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["system"] == "first system\nsecond system"
        assert all(m["role"] != "system" for m in body["messages"])
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "response"}],
                "usage": {"input_tokens": 10, "output_tokens": 1},
            },
        )

    request = GenerationRequest(
        model="test-model",
        messages=(
            Message(role="system", content="first system"),
            Message(role="user", content="ping"),
            Message(role="system", content="second system"),
        ),
    )
    result = await _make(make_client(handler)).generate(request)
    assert result.text == "response"


async def test_no_system_messages_omits_system_key():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "system" not in body
        assert len(body["messages"]) == 2
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "response"}],
                "usage": {"input_tokens": 5, "output_tokens": 1},
            },
        )

    request = GenerationRequest(
        model="test-model",
        messages=(
            Message(role="user", content="ping"),
            Message(role="assistant", content="pong"),
        ),
    )
    result = await _make(make_client(handler)).generate(request)
    assert result.text == "response"


async def test_missing_api_key_omits_auth_header():
    keyless_settings = ProviderSettings(base_url="https://api.anthropic.com", api_key=None)

    def handler(request: httpx.Request) -> httpx.Response:
        assert "x-api-key" not in request.headers
        assert request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "response"}],
                "usage": {"input_tokens": 5, "output_tokens": 1},
            },
        )

    provider = AnthropicProvider(settings=keyless_settings, client=make_client(handler))
    result = await provider.generate(contract_request())
    assert result.text == "response"


async def test_none_max_tokens_uses_cloud_default():
    # ADR-0006: anthropic requires max_tokens; None falls back to the generous cloud default.
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["max_tokens"] == DEFAULT_CLOUD_MAX_TOKENS
        return httpx.Response(
            200, json={"content": [{"type": "text", "text": "pong"}], "usage": {}}
        )

    await _make(make_client(handler)).generate(contract_request())


async def test_error_contract():
    await run_error_contract(_make)
