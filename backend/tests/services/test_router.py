import asyncio

import pytest

from zygos.errors import ProviderAuthFailed, ProviderUnavailable
from zygos.providers.fake import FakeProvider
from zygos.providers.types import GenerationChunk, GenerationRequest, GenerationResult, Message
from zygos.runtime.context import ExecutionContext, root_context
from zygos.runtime.events import Event, InProcessEventBus
from zygos.services.router import ProviderRouter, RouteChoice


def _request() -> GenerationRequest:
    return GenerationRequest(messages=(Message(role="user", content="hi"),))


def _ctx(bus: InProcessEventBus | None = None) -> ExecutionContext:
    return root_context(bus if bus is not None else InProcessEventBus())


def _recorder():
    events: list[Event] = []

    async def sub(event: Event) -> None:
        events.append(event)

    return events, sub


def _sleep_recorder() -> tuple[list[float], callable]:
    """Return a (sleeps list, sleep function) pair for recording backoff durations."""
    sleeps: list[float] = []
    async def record_sleep(duration: float) -> None:
        sleeps.append(duration)
    return sleeps, record_sleep


def _router(routes, providers, **kw):
    # Allow caller to override sleep; default to recording sleep durations
    if "sleep" not in kw:
        _, kw["sleep"] = _sleep_recorder()
    kw.setdefault("backoff_ms", 1)
    return ProviderRouter(routes, providers, **kw)


async def test_generate_uses_primary_and_fills_model():
    providers = {"fake": FakeProvider(text="hello")}
    router = _router([RouteChoice("fake", "model-a")], providers)
    result = await router.generate(_ctx(), _request())
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
    sleeps, record_sleep = _sleep_recorder()
    router = _router([RouteChoice("p1", "m1"), RouteChoice("p2", "m2")], providers, sleep=record_sleep)
    result = await router.generate(_ctx(), _request())
    assert result.text == "rescued"
    snap = router.snapshot()
    assert snap.routes[0].consecutive_failures == 3
    assert snap.routes[0].last_error_code == "provider_unavailable"
    # Assert exact exponential backoff sequence: backoff_ms=1, multiplier=2.0, max_attempts=3
    # sleep[i] = 1 * 2^(i) / 1000.0 for attempts 1, 2; no sleep on attempt 3 (last)
    expected_sleeps = [0.001, 0.002]
    assert sleeps == pytest.approx(expected_sleeps)


async def test_non_retryable_failure_skips_retries():
    auth = ProviderAuthFailed("bad key", provider="p1")
    providers = {"p1": FakeProvider(script=[auth, "never reached"]), "p2": FakeProvider(text="rescued")}
    router = _router([RouteChoice("p1", "m1"), RouteChoice("p2", "m2")], providers)
    result = await router.generate(_ctx(), _request())
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
    ctx = _ctx()
    assert (await router.generate(ctx, _request())).text == "backup"  # p1 fails once -> p2
    assert (await router.generate(ctx, _request())).text == "backup"  # p1 fails again -> circuit opens
    assert router.snapshot().routes[0].circuit == "open"
    assert (await router.generate(ctx, _request())).text == "backup"  # p1 skipped while open
    clock["t"] = 11.0  # past cooldown -> half-open trial allowed
    assert (await router.generate(ctx, _request())).text == "recovered"
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
    ctx = _ctx()
    assert (await router.generate(ctx, _request())).text == "fast"
    assert (await router.generate(ctx, _request())).text == "fast"
    assert (await router.generate(ctx, _request())).text == "spill"  # p1 window exhausted
    clock["t"] = 61.0
    assert (await router.generate(ctx, _request())).text == "fast"  # window slid


async def test_all_routes_down_raises_last_error():
    down = ProviderUnavailable("down", provider="p1")
    router = _router([RouteChoice("p1", "m1")], {"p1": FakeProvider(script=[down, down, down])})
    with pytest.raises(ProviderUnavailable):
        await router.generate(_ctx(), _request())


async def test_stream_falls_back_only_before_first_chunk():
    down = ProviderUnavailable("down", provider="p1")
    providers = {"p1": FakeProvider(script=[down]), "p2": FakeProvider(text="streamed ok")}
    router = _router([RouteChoice("p1", "m1"), RouteChoice("p2", "m2")], providers)
    chunks = [c async for c in router.stream(_ctx(), _request())]
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


class _CountingProvider:
    name = "cnt"

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        await asyncio.sleep(0)  # yield so concurrent claims interleave
        return GenerationResult(text="ok", model=request.model, provider=self.name)

    async def stream(self, request):
        yield GenerationChunk(text="ok", done=True)


class _GatedProvider:
    """Call 1 fails (to open the breaker); the probe call blocks until released."""

    name = "gated"

    def __init__(self) -> None:
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, request):
        self.calls += 1
        if self.calls == 1:
            raise ProviderUnavailable("open me", provider=self.name)
        self.entered.set()
        await self.release.wait()
        return GenerationResult(text="probe-ok", model=request.model, provider=self.name)

    async def stream(self, request):
        yield GenerationChunk(text="probe-ok", done=True)


class _SlowSuccessThenFail:
    """Call 1 blocks then succeeds; calls 2+ fail (to open the breaker)."""

    name = "mix"

    def __init__(self) -> None:
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, request):
        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            await self.release.wait()
            return GenerationResult(text="late-ok", model=request.model, provider=self.name)
        raise ProviderUnavailable("boom", provider=self.name)

    async def stream(self, request):
        yield GenerationChunk(text="x", done=True)


async def test_no_over_admission_under_concurrency():
    provider = _CountingProvider()
    router = _router([RouteChoice("cnt", "m")], {"cnt": provider}, max_requests_per_minute=2)
    ctx = _ctx()
    results = await asyncio.gather(
        *[router.generate(ctx, _request()) for _ in range(4)],
        return_exceptions=True,
    )
    ok = [r for r in results if not isinstance(r, Exception)]
    denied = [r for r in results if isinstance(r, ProviderUnavailable)]
    assert len(ok) == 2
    assert len(denied) == 2
    assert provider.calls == 2  # never over-admitted


async def test_exactly_one_half_open_probe_under_concurrency():
    clock = {"t": 0.0}
    provider = _GatedProvider()
    router = _router(
        [RouteChoice("gated", "m")], {"gated": provider},
        max_attempts=1, failure_threshold=1, cooldown_s=10.0, now=lambda: clock["t"],
    )
    ctx = _ctx()
    with pytest.raises(ProviderUnavailable):
        await router.generate(ctx, _request())  # call 1 fails -> breaker opens
    assert router.snapshot().routes[0].circuit == "open"
    clock["t"] = 11.0  # past cooldown -> half-open
    tasks = [asyncio.create_task(router.generate(ctx, _request())) for _ in range(3)]
    await provider.entered.wait()  # the single probe reached the provider
    await asyncio.sleep(0)          # let the other two run _try_claim and be denied
    done = [t for t in tasks if t.done()]
    assert len(done) == 2
    for task in done:
        with pytest.raises(ProviderUnavailable):
            task.result()
    provider.release.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    ok = [r for r in results if not isinstance(r, Exception)]
    assert len(ok) == 1 and ok[0].text == "probe-ok"
    assert provider.calls == 2  # 1 fail + exactly 1 probe
    assert router.snapshot().routes[0].circuit == "closed"


async def test_open_breaker_not_reset_by_concurrent_inflight_success():
    provider = _SlowSuccessThenFail()
    router = _router(
        [RouteChoice("mix", "m")], {"mix": provider},
        max_attempts=1, failure_threshold=2,
    )
    ctx = _ctx()
    a = asyncio.create_task(router.generate(ctx, _request()))
    await provider.entered.wait()  # A admitted while closed, now blocked
    with pytest.raises(ProviderUnavailable):
        await router.generate(ctx, _request())  # fail cf=1
    with pytest.raises(ProviderUnavailable):
        await router.generate(ctx, _request())  # fail cf=2 -> open
    assert router.snapshot().routes[0].circuit == "open"
    provider.release.set()
    result = await a
    assert result.text == "late-ok"
    assert router.snapshot().routes[0].circuit == "open"  # AC5: A's success did not reset it


async def test_route_claimed_emitted_per_attempt_including_retries():
    events, sub = _recorder()
    bus = InProcessEventBus()
    bus.subscribe(sub)
    down = ProviderUnavailable("down", provider="p1")
    router = _router([RouteChoice("p1", "m1")], {"p1": FakeProvider(script=[down, down, down])})
    with pytest.raises(ProviderUnavailable):
        await router.generate(root_context(bus), _request())
    claimed = [e for e in events if e.type == "route.claimed"]
    assert len(claimed) == 3
    assert all(e.payload.provider == "p1" and e.payload.probe is False for e in claimed)


async def test_circuit_opened_and_closed_emitted_on_transition():
    events, sub = _recorder()
    bus = InProcessEventBus()
    bus.subscribe(sub)
    clock = {"t": 0.0}
    down = ProviderUnavailable("down", provider="p1")
    router = _router(
        [RouteChoice("p1", "m1")], {"p1": FakeProvider(script=[down, down, "back"])},
        max_attempts=1, failure_threshold=2, cooldown_s=10.0, now=lambda: clock["t"],
    )
    ctx = root_context(bus)
    with pytest.raises(ProviderUnavailable):
        await router.generate(ctx, _request())  # cf=1, no transition
    with pytest.raises(ProviderUnavailable):
        await router.generate(ctx, _request())  # cf=2 -> circuit.opened
    clock["t"] = 11.0
    assert (await router.generate(ctx, _request())).text == "back"  # probe -> circuit.closed
    opened = [e for e in events if e.type == "circuit.opened"]
    closed = [e for e in events if e.type == "circuit.closed"]
    assert len(opened) == 1 and opened[0].payload.last_error_code == "provider_unavailable"
    assert len(closed) == 1 and closed[0].payload.provider == "p1"
