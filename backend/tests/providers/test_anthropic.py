import json

import httpx

from zygos.providers.anthropic import AnthropicProvider
from zygos.providers.base import DEFAULT_CLOUD_MAX_TOKENS, ProviderSettings
from zygos.providers.types import GenerationRequest, Message, ToolInvocation, ToolSchema

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


def _tools_request():
    return GenerationRequest(
        model="claude-x",
        messages=(Message(role="user", content="read a.txt"),),
        tools=(ToolSchema(name="read_file", description="Read a file.",
                          parameters={"type": "object", "properties": {"path": {"type": "string"}}}),),
    )


async def test_request_maps_tools_and_tool_choice():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tools"] == [{"name": "read_file", "description": "Read a file.",
                                  "input_schema": {"type": "object",
                                                   "properties": {"path": {"type": "string"}}}}]
        assert body["tool_choice"] == {"type": "auto"}
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}],
                                         "stop_reason": "end_turn", "usage": {}})

    await _make(make_client(handler)).generate(_tools_request())


async def test_parses_tool_use_blocks():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "content": [
                {"type": "text", "text": "let me read it"},
                {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "a.txt"}},
            ],
            "stop_reason": "tool_use", "usage": {},
        })

    result = await _make(make_client(handler)).generate(_tools_request())
    assert result.text == "let me read it"
    assert result.tool_calls == (ToolInvocation(id="toolu_1", name="read_file", arguments={"path": "a.txt"}),)
    assert result.finish_reason == "tool_calls"


async def test_text_only_response_unchanged():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": [{"type": "text", "text": "pong"}],
                                         "stop_reason": "end_turn", "usage": {"input_tokens": 3}})

    result = await _make(make_client(handler)).generate(contract_request())
    assert result.text == "pong"
    assert result.tool_calls == ()
    assert result.finish_reason == "stop"


async def test_serializes_assistant_tool_use_and_tool_result_as_user():
    inv = ToolInvocation(id="toolu_1", name="read_file", arguments={"path": "a.txt"})
    req = GenerationRequest(model="claude-x", messages=(
        Message(role="user", content="read a.txt"),
        Message(role="assistant", content="reading", tool_calls=(inv,)),
        Message(role="tool", tool_call_id="toolu_1", content='{"content": "hello"}'),
    ))

    def handler(request: httpx.Request) -> httpx.Response:
        msgs = json.loads(request.content)["messages"]
        assert msgs[1] == {"role": "assistant", "content": [
            {"type": "text", "text": "reading"},
            {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "a.txt"}}]}
        assert msgs[2] == {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": '{"content": "hello"}'}]}
        return httpx.Response(200, json={"content": [{"type": "text", "text": "done"}],
                                         "stop_reason": "end_turn", "usage": {}})

    await _make(make_client(handler)).generate(req)
