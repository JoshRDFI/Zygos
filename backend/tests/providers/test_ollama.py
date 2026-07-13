import json

import httpx

from zygos.providers.base import ProviderSettings
from zygos.providers.ollama import OllamaProvider
from zygos.providers.types import GenerationRequest, Message, ToolInvocation, ToolSchema

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
        assert "num_predict" not in body["options"]  # ADR-0006: local uncapped by default
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


async def test_generate_sets_num_predict_when_max_tokens_given():
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["options"]["num_predict"] == 256
        return httpx.Response(200, json={"message": {"content": "ok"}, "done": True})

    req = GenerationRequest(model="m", messages=(Message(role="user", content="hi"),), max_tokens=256)
    await _make(make_client(handler)).generate(req)


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


def _tools_request():
    return GenerationRequest(model="qwen3", messages=(Message(role="user", content="read a.txt"),),
                             tools=(ToolSchema(name="read_file", description="Read a file.",
                                               parameters={"type": "object"}),))


async def test_request_carries_tools():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tools"] == [{"type": "function",
                                  "function": {"name": "read_file", "description": "Read a file.",
                                               "parameters": {"type": "object"}}}]
        return httpx.Response(200, json={"message": {"content": "ok"}})

    await _make(make_client(handler)).generate(_tools_request())


async def test_serializes_assistant_tool_calls_and_tool_result():
    inv = ToolInvocation(id="call_0", name="read_file", arguments={"path": "a.txt"})
    req = GenerationRequest(model="qwen3", messages=(
        Message(role="user", content="read a.txt"),
        Message(role="assistant", content="", tool_calls=(inv,)),
        Message(role="tool", tool_call_id="call_0", content='{"content": "hello"}'),
    ))

    def handler(request: httpx.Request) -> httpx.Response:
        msgs = json.loads(request.content)["messages"]
        # arguments is a JSON OBJECT (not a stringified JSON), no id on the assistant tool_call
        assert msgs[1] == {"role": "assistant", "content": "",
                           "tool_calls": [{"function": {"name": "read_file", "arguments": {"path": "a.txt"}}}]}
        # tool message: role "tool", content only, NO id field
        assert msgs[2] == {"role": "tool", "content": '{"content": "hello"}'}
        return httpx.Response(200, json={"message": {"content": "done"}})

    await _make(make_client(handler)).generate(req)


async def test_parses_tool_calls_with_synthesized_ids():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "", "tool_calls": [
            {"function": {"name": "read_file", "arguments": {"path": "a.txt"}}},
            {"function": {"name": "read_file", "arguments": {"path": "b.txt"}}}]}})

    result = await _make(make_client(handler)).generate(_tools_request())
    assert result.tool_calls == (
        ToolInvocation(id="call_0", name="read_file", arguments={"path": "a.txt"}),
        ToolInvocation(id="call_1", name="read_file", arguments={"path": "b.txt"}),
    )
    assert result.finish_reason == "tool_calls"


async def test_text_only_response_unchanged():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "tools" not in json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": "pong"}})

    result = await _make(make_client(handler)).generate(contract_request())
    assert result.text == "pong"
    assert result.tool_calls == ()
    assert result.finish_reason == "stop"


async def test_tool_choice_none_drops_tools():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "tools" not in json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": "final"}})

    req = GenerationRequest(model="qwen3", messages=(Message(role="user", content="x"),),
                            tools=(ToolSchema(name="read_file", description="Read a file.",
                                              parameters={"type": "object"}),),
                            tool_choice="none")
    result = await _make(make_client(handler)).generate(req)
    assert result.text == "final"


async def test_embed_parses_ollama_batch():
    import httpx
    from zygos.providers.ollama import OllamaProvider
    from zygos.providers.base import ProviderSettings
    from zygos.providers.types import EmbedRequest
    from zygos.runtime.capabilities import Capability

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        assert request.url.path == "/api/embed"
        payload = json.loads(request.content)
        assert payload["model"] == "nomic-embed-text"
        assert payload["input"] == ["a", "b"]
        return httpx.Response(200, json={"model": "nomic-embed-text",
                                         "embeddings": [[1.0, 0.0], [0.0, 1.0]]})

    settings = ProviderSettings(base_url="http://localhost:11434")
    provider = OllamaProvider(settings=settings,
                              client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    result = await provider.embed(EmbedRequest(model="nomic-embed-text", texts=("a", "b")))
    assert result.vectors == ((1.0, 0.0), (0.0, 1.0))
    assert result.dim == 2
    assert Capability.EMBEDDING in OllamaProvider.capabilities
