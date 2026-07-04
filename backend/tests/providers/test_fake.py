import pytest

from zygos.errors import ProviderUnavailable
from zygos.providers.fake import FakeProvider
from zygos.providers.types import GenerationRequest, Message


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
