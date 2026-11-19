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

    def refusal(self, route):
        return None

    def admits(self, route):
        return True

    async def record_failure(self, ctx, route, error):
        self.calls.append({"op": "record_failure", "route": route})


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

    def hold(self, route):
        self.log.append(("hold", route))
        return lambda: self.log.append(("release", route))


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


# -- residency (the service only drives the protocol) ------


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
    assert [c["first"] for c in router.calls if c["op"] != "record_failure"] == [None, None]
    huge = RouteChoice("ollama", "huge")
    assert [c["route"] for c in router.calls if c["op"] == "record_failure"] == [huge, huge]
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



# -- residency follows the router's admission state -----------


class _Answering:
    def __init__(self, name: str, script=None) -> None:
        self.name = name
        self.asked: list[str] = []
        self._script = list(script or [])

    def _next(self, model):
        self.asked.append(model)
        if self._script:
            item = self._script.pop(0)
            if isinstance(item, BaseException):
                raise item
        return model

    async def generate(self, request):
        text = self._next(request.model)
        return GenerationResult(text=text, model=request.model, provider=self.name, usage=Usage())

    async def stream(self, request):
        text = self._next(request.model)
        yield GenerationChunk(text=text, done=True)


async def _call(svc, op, ctx, **kw):
    if op == "generate":
        return (await svc.generate(ctx, REQUEST, **kw)).text
    return "".join([c.text async for c in svc.stream(ctx, REQUEST, **kw)])


@pytest.mark.parametrize("op", ["generate", "stream"])
async def test_open_circuit_on_saved_default_means_no_load_and_config_primary_answers(op):
    down = ProviderUnavailable("down", provider="ollama")
    ollama = _Answering("ollama", script=[down])
    primary = _Answering("fake")
    router = ProviderRouter([PRIMARY], {"fake": primary, "ollama": ollama}, max_attempts=1,
                            failure_threshold=1, cooldown_s=60.0)
    residency = _Residency()
    store = _Store(DefaultModel(provider="ollama", model="big"))
    svc = DefaultModelService(router, default_status=_status_of(store), residency=residency)
    assert await _call(svc, op, _ctx()) == "primary"  # hard failure opens the circuit
    residency.log.clear()
    events = []
    assert await _call(svc, op, _ctx(events)) == "primary"
    assert [e for e in residency.log if e[0] in ("ensure", "enter")] == []  # no load, no unload
    skipped = [e.payload for e in events if isinstance(e.payload, RouteSkipped)]
    assert skipped == [RouteSkipped(provider="ollama", model="big", reason="circuit_open")]
    assert ollama.asked == ["big"]  # never asked again in the cooldown


@pytest.mark.parametrize("op", ["generate", "stream"])
async def test_repeated_load_failures_open_the_circuit_so_later_turns_neither_load_nor_wait(op):
    primary = _Answering("fake")
    router = ProviderRouter([PRIMARY], {"fake": primary, "ollama": _Answering("ollama")}, max_attempts=1,
                            failure_threshold=2, cooldown_s=60.0)
    residency = _Residency(fail=True)
    store = _Store(DefaultModel(provider="ollama", model="huge"))
    svc = DefaultModelService(router, default_status=_status_of(store), residency=residency)
    for _ in range(2):
        assert await _call(svc, op, _ctx()) == "primary"
    assert [e[0] for e in residency.log].count("ensure") == 2
    snap = {(r.provider, r.model): r.circuit for r in router.snapshot().routes}
    assert snap[("ollama", "huge")] == "open"
    residency.log.clear()
    assert await _call(svc, op, _ctx()) == "primary"
    assert [e for e in residency.log if e[0] == "ensure"] == []


class _BrokenResidency(_Residency):
    async def ensure_resident(self, ctx, route, *, on_loading=None) -> None:
        self.log.append(("ensure", route, on_loading))
        raise RuntimeError("fit() blew up")


@pytest.mark.parametrize("op", ["generate", "stream"])
async def test_a_non_provider_error_from_residency_falls_back_not_fails(op, caplog):
    router = _SpyRouter()
    store = _Store(DefaultModel(provider="ollama", model="m"))
    svc = DefaultModelService(router, default_status=_status_of(store), residency=_BrokenResidency())
    events = []
    with caplog.at_level("ERROR", logger="zygos.models"):
        assert await _call(svc, op, _ctx(events)) == "ok"
    assert [c["first"] for c in router.calls if c["op"] in ("generate", "stream")] == [None]
    assert "fit() blew up" in caplog.text
    skipped = [e.payload for e in events if isinstance(e.payload, RouteSkipped)]
    assert skipped == [RouteSkipped(provider="ollama", model="m", reason="load_failed")]
    # a bug is not a model failure: nothing is recorded on the breaker
    assert [c for c in router.calls if c["op"] == "record_failure"] == []


# -- the answering local model is held for the call ------


@pytest.mark.parametrize("op", ["generate", "stream"])
async def test_router_fallback_to_another_ollama_model_is_held_for_the_rest_of_the_call(op):
    other = RouteChoice("ollama", "fallback")
    down = ProviderUnavailable("down", provider="ollama")
    ollama = _Answering("ollama", script=[down])
    router = ProviderRouter([other], {"ollama": ollama}, max_attempts=1)
    residency = _Residency()
    store = _Store(DefaultModel(provider="ollama", model="saved"))
    svc = DefaultModelService(router, default_status=_status_of(store), residency=residency)
    assert await _call(svc, op, _ctx()) == "fallback"
    saved = RouteChoice("ollama", "saved")
    assert [e[:2] for e in residency.log] == [
        ("ensure", saved), ("enter", saved), ("hold", other), ("release", other), ("exit", saved)]


@pytest.mark.parametrize("op", ["generate", "stream"])
async def test_config_order_turn_on_an_ollama_route_is_held(op):
    configured = RouteChoice("ollama", "qwen3")
    router = ProviderRouter([configured], {"ollama": _Answering("ollama")})
    residency = _Residency()
    svc = DefaultModelService(router, default_status=_status_of(_Store()), residency=residency)
    from zygos.services.model import CONFIG_ORDER
    assert await _call(svc, op, _ctx(), route=CONFIG_ORDER) == "qwen3"
    assert residency.log == [("hold", configured), ("release", configured)]


async def test_config_order_stream_holds_until_the_stream_closes():
    configured = RouteChoice("ollama", "qwen3")
    router = ProviderRouter([configured], {"ollama": _Answering("ollama")})
    residency = _Residency()
    svc = DefaultModelService(router, default_status=_status_of(_Store()), residency=residency)
    stream = svc.stream(_ctx(), REQUEST)
    await stream.__anext__()
    assert residency.log == [("hold", configured)]
    await stream.aclose()
    assert residency.log == [("hold", configured), ("release", configured)]
