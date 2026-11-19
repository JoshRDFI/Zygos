"""ModelService — the RFC-0001 §2 model contract over the provider router.

classify_task is a heuristic classifier; select_model consumes it via task_routes (M3).

Stability: Experimental.
"""

from __future__ import annotations

import logging
import re
from contextlib import AbstractAsyncContextManager, aclosing
from typing import TYPE_CHECKING, AsyncIterator, Callable, Final, Literal, Mapping, Protocol, Union

from zygos.errors import ProviderError
from zygos.providers.types import LOCAL_PROVIDERS, GenerationChunk, GenerationRequest, GenerationResult
from zygos.runtime.context import ExecutionContext
from zygos.runtime.events import RouteSkipped
from zygos.services.router import ProviderRouter, RouteChoice

if TYPE_CHECKING:
    from zygos.models.default import DefaultStatus

_log = logging.getLogger("zygos.models")

TaskClassification = Literal["simple", "standard", "complex_reasoning", "code"]

_CODE_MARKERS = ("```", "def ", "import ", "function ")
_REASONING = re.compile(r"\b(why|analyze|prove|design|architecture|compare|trade-?off)\b", re.IGNORECASE)


# The task category a turn records (RFC-0013 §11). Recorded only -- nothing
# in phase 2 switches models by category.
CATEGORY_OF: dict[str, str] = {"code": "code", "complex_reasoning": "reasoning",
                               "simple": "chat", "standard": "chat"}


def classify_task(prompt: str) -> TaskClassification:
    if any(marker in prompt for marker in _CODE_MARKERS):
        return "code"
    if len(prompt) > 800 or _REASONING.search(prompt):
        return "complex_reasoning"
    if len(prompt) < 80:
        return "simple"
    return "standard"


class _ConfigOrder:
    """A turn that began with no saved default (RFC-0013 §5): use the
    router's configured order and do not look the saved default up again, so a
    default saved mid-turn applies from the next turn."""

    _instance: "_ConfigOrder | None" = None

    def __new__(cls) -> "_ConfigOrder":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "CONFIG_ORDER"


CONFIG_ORDER: Final = _ConfigOrder()

# What a turn pins for all its calls: the saved default, or CONFIG_ORDER.
# ``route=None`` (non-turn callers: memory consolidation, doctor) looks it up per call.
TurnRoute = Union[RouteChoice, _ConfigOrder]


class ResidencyLike(Protocol):
    """Keeps a local model loaded for a call (RFC-0013 §5).

    ``ensure_resident`` loads the route's model if needed (reporting it through
    ``on_loading``) and raises ``ProviderError`` when the load fails; ``turn``
    marks the model in use for the call so it is not unloaded under it; ``hold``
    does the same, synchronously, for a model the router chose itself."""

    async def ensure_resident(
        self,
        ctx: ExecutionContext,
        route: RouteChoice,
        *,
        on_loading: Callable[[RouteChoice], None] | None = None,
    ) -> None: ...

    def turn(self, route: RouteChoice) -> AbstractAsyncContextManager[None]: ...

    def hold(self, route: RouteChoice) -> Callable[[], None]:
        """Mark the route's model in use now; returns its (idempotent) release."""
        ...


class ModelService(Protocol):
    def classify_task(self, prompt: str) -> TaskClassification: ...

    def select_model(self, classification: TaskClassification | None = None, *,
                     route: TurnRoute | None = None) -> RouteChoice: ...

    def turn_route(self) -> RouteChoice | None: ...

    async def generate(
        self,
        ctx: ExecutionContext,
        request: GenerationRequest,
        *,
        route: TurnRoute | None = None,
        on_route: Callable[[RouteChoice], None] | None = None,
        on_loading: Callable[[RouteChoice], None] | None = None,
    ) -> GenerationResult: ...

    def stream(
        self,
        ctx: ExecutionContext,
        request: GenerationRequest,
        *,
        route: TurnRoute | None = None,
        on_route: Callable[[RouteChoice], None] | None = None,
        on_loading: Callable[[RouteChoice], None] | None = None,
    ) -> AsyncIterator[GenerationChunk]: ...


class DefaultModelService:
    def __init__(
        self,
        router: ProviderRouter,
        task_routes: Mapping[str, RouteChoice] | None = None,
        *,
        default_status: Callable[[], DefaultStatus] | None = None,
        residency: ResidencyLike | None = None,
    ) -> None:
        self._router = router
        self._task_routes = dict(task_routes) if task_routes else {}
        self._default_status = default_status
        self._residency = residency

    def classify_task(self, prompt: str) -> TaskClassification:
        return classify_task(prompt)

    def turn_route(self) -> RouteChoice | None:
        """The saved default when it is in effect, else None -- one store read.

        A turn calls this once and passes the result as ``route=`` to every
        call it makes, so a change made mid-turn does not affect it."""
        return self._saved_default()

    def _saved_default(self) -> RouteChoice | None:
        """The saved default when it is in effect, looked up on every call."""
        if self._default_status is None:
            return None
        status = self._default_status()
        return status.route if status.source == "saved" else None

    def _first(self, route: TurnRoute | None) -> RouteChoice | None:
        if route is CONFIG_ORDER:
            return None  # the configured order, exactly the no-default path
        return route if route is not None else self._saved_default()

    def _needs_residency(self, first: RouteChoice | None) -> bool:
        return first is not None and self._residency is not None and first.provider in LOCAL_PROVIDERS

    async def _resident_first(
        self, ctx: ExecutionContext, first: RouteChoice,
        on_loading: Callable[[RouteChoice], None] | None,
    ) -> RouteChoice | None:
        """``first`` once it is loaded; None (the router's configured order) when
        the router would not admit it now or the load failed.

        A route the router refuses (open circuit, rate limited) is not loaded, so
        a cooldown causes no load or unload. A failed load counts on the route's
        breaker, so repeated failures open the circuit like generation failures."""
        assert self._residency is not None
        refusal = self._router.refusal(first)
        if refusal is not None:
            await ctx.emit(RouteSkipped(provider=first.provider, model=first.model, reason=refusal),
                           source="models")
            return None
        try:
            await self._residency.ensure_resident(ctx, first, on_loading=on_loading)
        except ProviderError as exc:
            _log.warning("%s/%s can't be loaded (%s); falling back", first.provider, first.model, exc)
            await self._router.record_failure(ctx, first, exc)
        except Exception:  # noqa: BLE001 - a residency bug falls back, never fails the turn
            _log.exception("residency for %s/%s failed; falling back", first.provider, first.model)
        else:
            return first
        await ctx.emit(
            RouteSkipped(provider=first.provider, model=first.model, reason="load_failed"),
            source="models",
        )
        return None

    def _holding(
        self, first: RouteChoice | None, on_route: Callable[[RouteChoice], None] | None,
        holds: list[Callable[[], None]],
    ) -> Callable[[RouteChoice], None] | None:
        """Wrap ``on_route`` so a local model the router answers with -- other
        than ``first``, which ``turn()`` already holds -- is marked in use for the
        rest of the call; a preload then can't unload it mid-stream."""
        residency = self._residency
        if residency is None:
            return on_route

        def answered(route: RouteChoice) -> None:
            if route.provider in LOCAL_PROVIDERS and route != first:
                holds.append(residency.hold(route))
            if on_route is not None:
                on_route(route)

        return answered

    @staticmethod
    def _release(holds: list[Callable[[], None]]) -> None:
        while holds:
            holds.pop()()

    def select_model(self, classification: TaskClassification | None = None, *,
                     route: TurnRoute | None = None) -> RouteChoice:
        """``route`` is a turn's pinned route: a RouteChoice is returned as is;
        CONFIG_ORDER skips the saved-default lookup; None looks it up."""
        if isinstance(route, RouteChoice):
            return route
        if classification is not None and classification in self._task_routes:
            return self._task_routes[classification]
        saved = None if route is CONFIG_ORDER else self._saved_default()
        if saved is not None:
            return saved
        return self._router.first_eligible()

    async def generate(
        self,
        ctx: ExecutionContext,
        request: GenerationRequest,
        *,
        route: TurnRoute | None = None,
        on_route: Callable[[RouteChoice], None] | None = None,
        on_loading: Callable[[RouteChoice], None] | None = None,
    ) -> GenerationResult:
        first = self._first(route)
        holds: list[Callable[[], None]] = []
        if self._needs_residency(first):
            assert first is not None and self._residency is not None
            first = await self._resident_first(ctx, first, on_loading)
            if first is not None:
                async with self._residency.turn(first):
                    try:
                        return await self._router.generate(
                            ctx, request, first=first, on_route=self._holding(first, on_route, holds))
                    finally:
                        self._release(holds)
        try:
            return await self._router.generate(
                ctx, request, first=first, on_route=self._holding(None, on_route, holds))
        finally:
            self._release(holds)

    def stream(
        self,
        ctx: ExecutionContext,
        request: GenerationRequest,
        *,
        route: TurnRoute | None = None,
        on_route: Callable[[RouteChoice], None] | None = None,
        on_loading: Callable[[RouteChoice], None] | None = None,
    ) -> AsyncIterator[GenerationChunk]:
        first = self._first(route)
        if self._residency is None:
            return self._router.stream(ctx, request, first=first, on_route=on_route)
        return self._resident_stream(ctx, request, first, on_route, on_loading)

    async def _resident_stream(
        self,
        ctx: ExecutionContext,
        request: GenerationRequest,
        first: RouteChoice | None,
        on_route: Callable[[RouteChoice], None] | None,
        on_loading: Callable[[RouteChoice], None] | None,
    ) -> AsyncIterator[GenerationChunk]:
        assert self._residency is not None
        holds: list[Callable[[], None]] = []
        if self._needs_residency(first):
            assert first is not None
            first = await self._resident_first(ctx, first, on_loading)
        try:
            if first is None or not self._needs_residency(first):
                chunks = self._router.stream(ctx, request, first=first,
                                             on_route=self._holding(None, on_route, holds))
                async with aclosing(chunks):
                    async for chunk in chunks:
                        yield chunk
                return
            async with self._residency.turn(first):
                try:
                    chunks = self._router.stream(ctx, request, first=first,
                                                 on_route=self._holding(first, on_route, holds))
                    async with aclosing(chunks):
                        async for chunk in chunks:
                            yield chunk
                finally:
                    self._release(holds)
        finally:
            self._release(holds)
