import json

import httpx

from zygos.providers.base import DEFAULT_CLOUD_MAX_TOKENS, ProviderSettings
from zygos.providers.openai import OpenAIProvider
from zygos.providers.types import GenerationRequest, Message

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


async def test_none_max_tokens_uses_cloud_default():
    # ADR-0006: a cloud provider caps generously when no caller cap is given.
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["max_tokens"] == DEFAULT_CLOUD_MAX_TOKENS
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}], "usage": {}})

    await _make(make_client(handler)).generate(contract_request())


async def test_explicit_max_tokens_preserved():
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["max_tokens"] == 128
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}], "usage": {}})

    req = GenerationRequest(model="m", messages=(Message(role="user", content="hi"),), max_tokens=128)
    await _make(make_client(handler)).generate(req)


async def test_error_contract():
    await run_error_contract(_make)


async def test_generate_omits_auth_header_without_api_key():
    keyless_settings = ProviderSettings(base_url="https://api.openai.com/v1", api_key=None)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert "authorization" not in request.headers
        body = json.loads(request.content)
        assert body["stream"] is False
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "pong"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    provider = OpenAIProvider(settings=keyless_settings, client=make_client(handler))
    result = await provider.generate(contract_request())
    assert result.text == "pong"
    assert result.provider == "openai"


from zygos.providers.types import ToolInvocation, ToolSchema


def _tools_request():
    return GenerationRequest(
        model="gpt-x",
        messages=(Message(role="user", content="read a.txt"),),
        tools=(ToolSchema(name="read_file", description="Read a file.",
                          parameters={"type": "object", "properties": {"path": {"type": "string"}}}),),
    )


async def test_request_carries_native_tools():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tools"] == [{
            "type": "function",
            "function": {"name": "read_file", "description": "Read a file.",
                         "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}},
        }]
        assert body["tool_choice"] == "auto"
        return httpx.Response(200, json={
            "choices": [{"message": {"content": None, "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "read_file", "arguments": '{"path": "a.txt"}'}}]},
                "finish_reason": "tool_calls"}],
            "usage": {},
        })

    result = await _make(make_client(handler)).generate(_tools_request())
    assert result.finish_reason == "tool_calls"
    assert result.tool_calls == (ToolInvocation(id="call_1", name="read_file", arguments={"path": "a.txt"}),)
    assert result.text == ""


async def test_text_only_request_omits_tools_key():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "tools" not in json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"},
                                                       "finish_reason": "stop"}], "usage": {}})

    result = await _make(make_client(handler)).generate(contract_request())
    assert result.text == "hi"
    assert result.tool_calls == ()
    assert result.finish_reason == "stop"


async def test_serializes_assistant_tool_calls_and_tool_result():
    inv = ToolInvocation(id="call_1", name="read_file", arguments={"path": "a.txt"})
    req = GenerationRequest(model="gpt-x", messages=(
        Message(role="user", content="read a.txt"),
        Message(role="assistant", content="", tool_calls=(inv,)),
        Message(role="tool", tool_call_id="call_1", content='{"content": "hello"}'),
    ))

    def handler(request: httpx.Request) -> httpx.Response:
        msgs = json.loads(request.content)["messages"]
        assert msgs[1] == {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "read_file", "arguments": '{"path": "a.txt"}'}}]}
        assert msgs[2] == {"role": "tool", "tool_call_id": "call_1", "content": '{"content": "hello"}'}
        return httpx.Response(200, json={"choices": [{"message": {"content": "done"},
                                                      "finish_reason": "stop"}], "usage": {}})

    await _make(make_client(handler)).generate(req)


async def test_malformed_tool_arguments_raise_protocol_error():
    import pytest
    from zygos.errors import ProviderProtocolError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{not json"}}]},
            "finish_reason": "tool_calls"}], "usage": {}})

    with pytest.raises(ProviderProtocolError):
        await _make(make_client(handler)).generate(_tools_request())


async def test_embed_parses_openai_embeddings():
    import json
    import httpx
    from zygos.providers.openai import OpenAIProvider
    from zygos.providers.base import ProviderSettings
    from zygos.providers.types import EmbedRequest
    from zygos.runtime.capabilities import Capability

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        assert request.headers["authorization"] == "Bearer sk-test"
        payload = json.loads(request.content)
        assert payload == {"model": "text-embedding-3-small", "input": ["a", "b"]}
        return httpx.Response(200, json={
            "model": "text-embedding-3-small",
            "data": [{"index": 1, "embedding": [0.0, 1.0]},
                     {"index": 0, "embedding": [1.0, 0.0]}],  # out of order on purpose
            "usage": {"prompt_tokens": 3},
        })

    provider = OpenAIProvider(
        settings=ProviderSettings(base_url="https://api.openai.com/v1", api_key="sk-test"),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await provider.embed(EmbedRequest(model="text-embedding-3-small", texts=("a", "b")))
    assert result.vectors == ((1.0, 0.0), (0.0, 1.0))  # re-sorted by index
    assert result.dim == 2
    assert result.usage.input_tokens == 3
    assert Capability.EMBEDDING in OpenAIProvider.capabilities
