import httpx

from zygos.providers.base import ProviderSettings
from zygos.providers.fake import FakeProvider
from zygos.providers.ollama import OllamaProvider
from zygos.services.router import RouteChoice
from zygos.thinking.support import ThinkingSupport, ThinkingSupportChecker

OLLAMA = RouteChoice(provider="ollama", model="qwen3:8b")


def _ollama(handler) -> OllamaProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OllamaProvider(settings=ProviderSettings(base_url="http://localhost:11434"), client=client)


async def test_checker_non_ollama_unsupported():
    checker = ThinkingSupportChecker({"openai": FakeProvider()})
    result = await checker.check(RouteChoice(provider="openai", model="gpt-x"))
    assert result == ThinkingSupport(supported=False, reason="thinking controls aren't available for openai yet")


async def test_probe_failure_is_not_cached():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"capabilities": ["thinking"]})

    checker = ThinkingSupportChecker({"ollama": _ollama(handler)})
    first = await checker.check(OLLAMA)
    assert first == ThinkingSupport(supported=False, reason="couldn't check the model")
    assert checker.cached(OLLAMA) is None
    second = await checker.check(OLLAMA)
    assert second.supported is True
    assert checker.cached(OLLAMA) == second
    await checker.check(OLLAMA)
    assert len(calls) == 2


async def test_success_is_cached_per_provider_and_model():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"capabilities": ["thinking"]})

    checker = ThinkingSupportChecker({"ollama": _ollama(handler)})
    await checker.check(OLLAMA)
    await checker.check(OLLAMA)
    assert len(calls) == 1
    await checker.check(RouteChoice(provider="ollama", model="other:1b"))
    assert len(calls) == 2


async def test_fake_provider_think_capable():
    checker = ThinkingSupportChecker({
        "fake": FakeProvider(think_capable=True),
    })
    assert (await checker.check(RouteChoice(provider="fake", model="m"))).supported is True
    checker2 = ThinkingSupportChecker({"fake": FakeProvider(think_capable=False)})
    r = await checker2.check(RouteChoice(provider="fake", model="m"))
    assert r == ThinkingSupport(supported=False, reason="m can't think")


async def test_fake_provider_thinking_text():
    from zygos.providers.types import GenerationRequest, Message
    req = GenerationRequest(model="m", messages=(Message(role="user", content="x y"),))
    p = FakeProvider(thinking="pondering")
    assert (await p.generate(req)).thinking == "pondering"
    chunks = [c async for c in p.stream(req)]
    assert chunks[0].thinking == "pondering"


async def test_hung_probe_is_bounded_and_not_cached(monkeypatch):
    import asyncio
    import time

    from zygos.thinking import support

    class Hung:
        async def thinking_support(self, model):
            await asyncio.sleep(10)

    monkeypatch.setattr(support, "PROBE_TIMEOUT_S", 0.05)
    checker = ThinkingSupportChecker({"ollama": Hung()})
    start = time.monotonic()
    result = await checker.check(OLLAMA)
    assert time.monotonic() - start < 2
    assert result == ThinkingSupport(supported=False, reason="couldn't check the model")
    assert checker.cached(OLLAMA) is None


async def test_check_selected_survives_a_raising_checker():
    from zygos.thinking.support import UNCHECKED_REASON, check_selected

    class Boom:
        async def check(self, route):
            raise RuntimeError("boom")

    result = await check_selected(Boom(), lambda: OLLAMA)
    assert result == ThinkingSupport(supported=False, reason=UNCHECKED_REASON)


async def test_check_selected_without_a_checker_is_unchecked():
    from zygos.thinking.support import UNCHECKED_REASON, check_selected

    result = await check_selected(None, lambda: OLLAMA)
    assert result == ThinkingSupport(supported=False, reason=UNCHECKED_REASON)
