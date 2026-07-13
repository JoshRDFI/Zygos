import pytest

from zygos.errors import ProviderUnavailable
from zygos.providers.fake import FakeProvider
from zygos.providers.types import GenerationRequest, GenerationResult, Message, ToolInvocation


def _request() -> GenerationRequest:
    return GenerationRequest(model="any", messages=(Message(role="user", content="hi"),))


async def test_fake_generates_default_text():
    provider = FakeProvider()
    result = await provider.generate(_request())
    assert result.text == "fake response"
    assert result.provider == "fake"
    assert result.model == "any"


async def test_fake_follows_script_including_errors():
    provider = FakeProvider(script=["first", ProviderUnavailable("down", provider="fake"), "third"])
    assert (await provider.generate(_request())).text == "first"
    with pytest.raises(ProviderUnavailable):
        await provider.generate(_request())
    assert (await provider.generate(_request())).text == "third"


async def test_fake_streams_words_then_done():
    provider = FakeProvider(text="alpha beta")
    chunks = [chunk async for chunk in provider.stream(_request())]
    assert [c.text for c in chunks[:-1]] == ["alpha", "beta"]
    assert chunks[-1].done is True


async def test_fake_embedder_is_deterministic():
    from zygos.providers.fake import FakeEmbedder
    from zygos.providers.types import EmbedRequest

    emb = FakeEmbedder(dim=8)
    a = await emb.embed(EmbedRequest(texts=("hello", "world")))
    b = await emb.embed(EmbedRequest(texts=("hello", "world")))
    assert a.vectors == b.vectors           # same input -> same vectors
    assert a.dim == 8 and len(a.vectors[0]) == 8
    assert a.vectors[0] != a.vectors[1]     # different text -> different vector


async def test_script_returns_generation_result_verbatim():
    scripted = GenerationResult(
        text="", model="fake-model", provider="fake",
        tool_calls=(ToolInvocation(id="c1", name="echo", arguments={"v": "x"}),),
        finish_reason="tool_calls",
    )
    fake = FakeProvider(script=[scripted, "final answer"])
    req = GenerationRequest(messages=(Message(role="user", content="hi"),))

    first = await fake.generate(req)
    assert first.tool_calls[0].name == "echo"
    assert first.finish_reason == "tool_calls"

    second = await fake.generate(req)
    assert second.text == "final answer"
    assert second.tool_calls == ()
    assert second.finish_reason == "stop"
