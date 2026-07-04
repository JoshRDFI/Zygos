import pytest

from zygos.errors import ProviderAuthFailed, ProviderUnavailable
from zygos.providers.fake import FakeProvider
from zygos.providers.types import GenerationRequest, Message
from zygos.services.router import ProviderRouter, RouteChoice


def _request() -> GenerationRequest:
    return GenerationRequest(messages=(Message(role="user", content="hi"),))


async def _noop_sleep(_s: float) -> None:
    return None


def _router(routes, providers, **kw):
    kw.setdefault("sleep", _noop_sleep)
    kw.setdefault("backoff_ms", 1)
    return ProviderRouter(routes, providers, **kw)


async def test_generate_uses_primary_and_fills_model():
    providers = {"fake": FakeProvider(text="hello")}
    router = _router([RouteChoice("fake", "model-a")], providers)
    result = await router.generate(_request())
    assert result.text == "hello"
    assert result.model == "model-a"


async def test_retryable_failure_retries_then_falls_back():
    down = ProviderUnavailable("down", provider="p1")
    providers = {
        "p1": FakeProvider(script=[down, down, down]),  # exhausts max_attempts=3
        "p2": FakeProvider(text="rescued"),
    }
    providers["p1"].name = "p1"
    providers["p2"].name = "p2"
    router = _router([RouteChoice("p1", "m1"), RouteChoice("p2", "m2")], providers)
    result = await router.generate(_request())
    assert result.text == "rescued"
    snap = router.snapshot()
    assert snap.routes[0].consecutive_failures == 3
    assert snap.routes[0].last_error_code == "provider_unavailable"


async def test_non_retryable_failure_skips_retries():
    auth = ProviderAuthFailed("bad key", provider="p1")
    providers = {"p1": FakeProvider(script=[auth, "never reached"]), "p2": FakeProvider(text="rescued")}
    router = _router([RouteChoice("p1", "m1"), RouteChoice("p2", "m2")], providers)
    result = await router.generate(_request())
    assert result.text == "rescued"
    assert router.snapshot().routes[0].consecutive_failures == 1  # one try, no retries


async def test_circuit_opens_after_threshold_and_recovers_half_open():
    clock = {"t": 0.0}
    down = ProviderUnavailable("down", provider="p1")
    providers = {"p1": FakeProvider(script=[down, down, "recovered"]), "p2": FakeProvider(text="backup")}
    router = _router(
        [RouteChoice("p1", "m1"), RouteChoice("p2", "m2")],
        providers,
        max_attempts=1,
        failure_threshold=2,
        cooldown_s=10.0,
        now=lambda: clock["t"],
    )
    assert (await router.generate(_request())).text == "backup"  # p1 fails once -> p2
    assert (await router.generate(_request())).text == "backup"  # p1 fails again -> circuit opens
    assert router.snapshot().routes[0].circuit == "open"
    assert (await router.generate(_request())).text == "backup"  # p1 skipped while open
    clock["t"] = 11.0  # past cooldown -> half-open trial allowed
    assert (await router.generate(_request())).text == "recovered"
    assert router.snapshot().routes[0].circuit == "closed"


async def test_rate_limit_skips_exhausted_provider():
    providers = {"p1": FakeProvider(text="fast"), "p2": FakeProvider(text="spill")}
    clock = {"t": 0.0}
    router = _router(
        [RouteChoice("p1", "m1"), RouteChoice("p2", "m2")],
        providers,
        max_requests_per_minute=2,
        now=lambda: clock["t"],
    )
    assert (await router.generate(_request())).text == "fast"
    assert (await router.generate(_request())).text == "fast"
    assert (await router.generate(_request())).text == "spill"  # p1 window exhausted
    clock["t"] = 61.0
    assert (await router.generate(_request())).text == "fast"  # window slid


async def test_all_routes_down_raises_last_error():
    down = ProviderUnavailable("down", provider="p1")
    router = _router([RouteChoice("p1", "m1")], {"p1": FakeProvider(script=[down, down, down])})
    with pytest.raises(ProviderUnavailable):
        await router.generate(_request())


async def test_stream_falls_back_only_before_first_chunk():
    down = ProviderUnavailable("down", provider="p1")
    providers = {"p1": FakeProvider(script=[down]), "p2": FakeProvider(text="streamed ok")}
    router = _router([RouteChoice("p1", "m1"), RouteChoice("p2", "m2")], providers)
    chunks = [c async for c in router.stream(_request())]
    assert [c.text for c in chunks[:-1]] == ["streamed", "ok"]
    assert chunks[-1].done is True


def test_unknown_route_provider_rejected_at_construction():
    with pytest.raises(ValueError, match="ghost"):
        ProviderRouter([RouteChoice("ghost", "m")], {})


def test_first_eligible_and_snapshot_shapes():
    router = _router([RouteChoice("fake", "m")], {"fake": FakeProvider()})
    choice = router.first_eligible()
    assert (choice.provider, choice.model) == ("fake", "m")
    snap = router.snapshot()
    assert snap.routes[0].circuit == "closed"
    assert snap.routes[0].requests_in_window == 0
