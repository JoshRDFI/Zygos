"""DefaultModelService reads the saved default per call (RFC-0013 §5)."""

from contextlib import asynccontextmanager

import pytest

from zygos.errors import ProviderUnavailable
from zygos.models.choices import DefaultModel, ModelChoices
from zygos.models.default import resolve_default
from zygos.providers.types import GenerationChunk, GenerationRequest, GenerationResult, Message, Usage
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus, RouteSkipped
from zygos.services.model import DefaultModelService
from zygos.services.router import ProviderRouter, RouteChoice

PRIMARY = RouteChoice("fake", "primary")
REQUEST = GenerationRequest(messages=(Message(role="user", content="hi"),))


def _ctx(events=None):
    bus = InProcessEventBus()
    if events is not None:
        async def collect(event):
            events.append(event)
        bus.subscribe(collect)
    return root_context(bus)


class _Store:
    def __init__(self, default: DefaultModel | None = None) -> None:
        self.choices = ModelChoices(default_model=default)
        self.reads = 0

    def get(self) -> ModelChoices:
        self.reads += 1
        return self.choices


def _status_of(store: _Store, *, installed=None, routable=lambda p: True):
    return lambda: resolve_default(store.get(), PRIMARY, installed=lambda p: installed, routable=routable)


class _SpyRouter:
    """Records the kwargs the service passes; answers like the real router."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def first_eligible(self) -> RouteChoice:
        return PRIMARY

    async def generate(self, ctx, request, *, first=None, on_route=None):
        self.calls.append({"op": "generate", "first": first, "on_route": on_route})
        return GenerationResult(text="ok", model=request.model, provider="fake", usage=Usage())

    async def stream(self, ctx, request, *, first=None, on_route=None):
        self.calls.append({"op": "stream", "first": first, "on_route": on_route})
        yield GenerationChunk(text="ok", done=True)


class _Residency:
    def __init__(self, fail: bool = False) -> None:
        self.log: list[tuple] = []
        self._fail = fail

    async def ensure_resident(self, ctx, route, *, on_loading=None) -> None:
        self.log.append(("ensure", route, on_loading))
        if self._fail:
            raise ProviderUnavailable("load timed out", provider=route.provider)

    @asynccontextmanager
    async def turn(self, route):
        self.log.append(("enter", route))
        try:
            yield
        finally:
            self.log.append(("exit", route))


# -- no saved default: exactly the old behaviour --------------------------------


async def test_no_saved_default_passes_first_none():
    router = _SpyRouter()
    svc = DefaultModelService(router, default_status=_status_of(_Store()))
    await svc.generate(_ctx(), REQUEST)
    [_ async for _ in svc.stream(_ctx(), REQUEST)]
    assert [(c["op"], c["first"], c["on_route"]) for c in router.calls] == [
        ("generate", None, None), ("stream", None, None)]


async def test_no_default_status_at_all_passes_first_none():
    router = _SpyRouter()
    svc = DefaultModelService(router)
    await svc.generate(_ctx(), REQUEST)
    [_ async for _ in svc.stream(_ctx(), REQUEST)]
    assert [c["first"] for c in router.calls] == [None, None]
    assert svc.select_model() == PRIMARY


# -- saved default ---------------------------------------------------------------


async def test_saved_default_is_passed_as_first():
    router = _SpyRouter()
    store = _Store(DefaultModel(provider="ollama", model="gemma4:e4b"))
    svc = DefaultModelService(router, default_status=_status_of(store))
    seen = []
    await svc.generate(_ctx(), REQUEST, on_route=seen.append)
    [_ async for _ in svc.stream(_ctx(), REQUEST, on_route=seen.append)]
    assert [c["first"] for c in router.calls] == [RouteChoice("ollama", "gemma4:e4b")] * 2
    assert all(c["on_route"] == seen.append for c in router.calls)


async def test_ignored_saved_default_passes_first_none():
    router = _SpyRouter()
    store = _Store(DefaultModel(provider="ollama", model="gone"))
    svc = DefaultModelService(router, default_status=_status_of(store, installed=frozenset({"x"})))
    await svc.generate(_ctx(), REQUEST)
    assert router.calls[0]["first"] is None


async def test_default_is_read_per_call():
    router = _SpyRouter()
    store = _Store(DefaultModel(provider="ollama", model="a"))
    svc = DefaultModelService(router, default_status=_status_of(store))
    await svc.generate(_ctx(), REQUEST)
    store.choices = ModelChoices(default_model=DefaultModel(provider="ollama", model="b"))
    [_ async for _ in svc.stream(_ctx(), REQUEST)]
    store.choices = ModelChoices()
    await svc.generate(_ctx(), REQUEST)
    assert [c["first"] for c in router.calls] == [
        RouteChoice("ollama", "a"), RouteChoice("ollama", "b"), None]


async def test_explicit_route_beats_saved_default():
    router = _SpyRouter()
    store = _Store(DefaultModel(provider="ollama", model="a"))
    svc = DefaultModelService(router, default_status=_status_of(store))
    chosen = RouteChoice("vllm", "served")
    await svc.generate(_ctx(), REQUEST, route=chosen)
    [_ async for _ in svc.stream(_ctx(), REQUEST, route=chosen)]
    assert [c["first"] for c in router.calls] == [chosen, chosen]


def test_select_model_follows_saved_default():
    store = _Store(DefaultModel(provider="ollama", model="gemma4:e4b"))
    svc = DefaultModelService(_SpyRouter(), default_status=_status_of(store))
    assert svc.select_model() == RouteChoice("ollama", "gemma4:e4b")
    assert svc.select_model("complex_reasoning") == RouteChoice("ollama", "gemma4:e4b")
    store.choices = ModelChoices()
    assert svc.select_model() == PRIMARY


def test_task_routes_still_win_over_saved_default():
    store = _Store(DefaultModel(provider="ollama", model="gemma4:e4b"))
    svc = DefaultModelService(_SpyRouter(), task_routes={"code": RouteChoice("fake", "coder")},
                              default_status=_status_of(store))
    assert svc.select_model("code") == RouteChoice("fake", "coder")
    assert svc.select_model("simple") == RouteChoice("ollama", "gemma4:e4b")


def test_select_model_ignores_an_ignored_saved_default():
    store = _Store(DefaultModel(provider="anthropic", model="c"))
    svc = DefaultModelService(_SpyRouter(),
                              default_status=_status_of(store, routable=lambda p: p != "anthropic"))
    assert svc.select_model() == PRIMARY


# -- fallback with retry: nothing remembered as a switch ---------------------------


class _FlakyProvider:
    """Fails the first call for model 'saved' only; records every model it is asked for."""

    name = "fake"

    def __init__(self) -> None:
        self.asked: list[str] = []
        self._failed = False

    async def generate(self, request):
        self.asked.append(request.model)
        if request.model == "saved" and not self._failed:
            self._failed = True
            raise ProviderUnavailable("down", provider="fake")
        return GenerationResult(text=request.model, model=request.model, provider="fake", usage=Usage())

    async def stream(self, request):
        self.asked.append(request.model)
        if request.model == "saved" and not self._failed:
            self._failed = True
            raise ProviderUnavailable("down", provider="fake")
        yield GenerationChunk(text=request.model, done=True)


@pytest.mark.parametrize("op", ["generate", "stream"])
async def test_saved_default_failure_falls_back_and_next_call_retries_it(op):
    provider = _FlakyProvider()
    router = ProviderRouter([PRIMARY], {"fake": provider}, max_attempts=1)
    store = _Store(DefaultModel(provider="fake", model="saved"))
    svc = DefaultModelService(router, default_status=_status_of(store))

    async def call():
        answered = []
        if op == "generate":
            text = (await svc.generate(_ctx(), REQUEST, on_route=answered.append)).text
        else:
            text = "".join([c.text async for c in svc.stream(_ctx(), REQUEST, on_route=answered.append)])
        return text, answered

    assert await call() == ("primary", [PRIMARY])        # saved failed: config primary answered
    assert await call() == ("saved", [RouteChoice("fake", "saved")])  # next call tries it again
    assert provider.asked == ["saved", "primary", "saved"]
    assert store.choices.default_model == DefaultModel(provider="fake", model="saved")


# -- residency (Task 4 implements it; the service only drives the protocol) ------


async def test_local_effective_route_is_made_resident_and_held_for_the_call():
    router = _SpyRouter()
    residency = _Residency()
    store = _Store(DefaultModel(provider="ollama", model="gemma4:e4b"))
    svc = DefaultModelService(router, default_status=_status_of(store), residency=residency)
    route = RouteChoice("ollama", "gemma4:e4b")
    loading = []
    await svc.generate(_ctx(), REQUEST, on_loading=loading.append)
    assert residency.log == [("ensure", route, loading.append), ("enter", route), ("exit", route)]
    residency.log.clear()
    [_ async for _ in svc.stream(_ctx(), REQUEST, on_loading=loading.append)]
    assert residency.log == [("ensure", route, loading.append), ("enter", route), ("exit", route)]


async def test_no_effective_route_or_cloud_route_skips_residency():
    router = _SpyRouter()
    residency = _Residency()
    svc = DefaultModelService(router, default_status=_status_of(_Store()), residency=residency)
    await svc.generate(_ctx(), REQUEST)
    await svc.generate(_ctx(), REQUEST, route=RouteChoice("anthropic", "c"))
    [_ async for _ in svc.stream(_ctx(), REQUEST, route=RouteChoice("openai", "g"))]
    assert residency.log == []


async def test_a_failed_load_falls_back_through_the_router():
    router = _SpyRouter()
    residency = _Residency(fail=True)
    store = _Store(DefaultModel(provider="ollama", model="huge"))
    svc = DefaultModelService(router, default_status=_status_of(store), residency=residency)
    events = []
    await svc.generate(_ctx(events), REQUEST)
    [_ async for _ in svc.stream(_ctx(events), REQUEST)]
    assert [c["first"] for c in router.calls] == [None, None]
    assert [e[0] for e in residency.log] == ["ensure", "ensure"]  # never held
    skipped = [e.payload for e in events if isinstance(e.payload, RouteSkipped)]
    assert skipped == [RouteSkipped(provider="ollama", model="huge", reason="load_failed")] * 2



# -- turn_route: the route is pinned once per turn (a running turn is unaffected) --


def test_turn_route_is_the_saved_default_read_once():
    store = _Store(DefaultModel(provider="ollama", model="a"))
    svc = DefaultModelService(_SpyRouter(), default_status=_status_of(store))
    assert svc.turn_route() == RouteChoice("ollama", "a")
    assert store.reads == 1
    store.choices = ModelChoices()
    assert svc.turn_route() is None


def test_turn_route_none_without_a_saved_default_or_status():
    assert DefaultModelService(_SpyRouter(), default_status=_status_of(_Store())).turn_route() is None
    assert DefaultModelService(_SpyRouter()).turn_route() is None
    store = _Store(DefaultModel(provider="anthropic", model="c"))
    svc = DefaultModelService(_SpyRouter(), default_status=_status_of(store, routable=lambda p: False))
    assert svc.turn_route() is None


async def test_a_change_after_turn_route_does_not_affect_the_pinned_turn():
    router = _SpyRouter()
    store = _Store(DefaultModel(provider="ollama", model="a"))
    svc = DefaultModelService(router, default_status=_status_of(store))
    pinned = svc.turn_route()
    reads = store.reads
    store.choices = ModelChoices(default_model=DefaultModel(provider="ollama", model="b"))
    await svc.generate(_ctx(), REQUEST, route=pinned)
    [_ async for _ in svc.stream(_ctx(), REQUEST, route=pinned)]
    assert [c["first"] for c in router.calls] == [RouteChoice("ollama", "a")] * 2
    assert store.reads == reads  # an explicit route skips the lookup


# -- CONFIG_ORDER: a turn that started with no saved default stays on it ---------


async def test_config_order_never_looks_up_the_saved_default():
    from zygos.services.model import CONFIG_ORDER
    store = _Store(DefaultModel(provider="ollama", model="q"))
    router = _SpyRouter()
    residency = _Residency()
    svc = DefaultModelService(router, default_status=_status_of(store), residency=residency)
    await svc.generate(_ctx(), REQUEST, route=CONFIG_ORDER)
    [_ async for _ in svc.stream(_ctx(), REQUEST, route=CONFIG_ORDER)]
    assert [(c["op"], c["first"]) for c in router.calls] == [("generate", None), ("stream", None)]
    assert residency.log == []
    assert store.reads == 0


def test_select_model_config_order_ignores_saved_default():
    from zygos.services.model import CONFIG_ORDER
    store = _Store(DefaultModel(provider="ollama", model="q"))
    svc = DefaultModelService(_SpyRouter(), default_status=_status_of(store))
    assert svc.select_model(route=CONFIG_ORDER) == PRIMARY
    assert svc.select_model() == RouteChoice("ollama", "q")
    pinned = RouteChoice("x", "y")
    assert svc.select_model(route=pinned) == pinned
