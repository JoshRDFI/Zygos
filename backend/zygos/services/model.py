"""ModelService — the RFC-0001 §2 model contract over the provider router.

classify_task is a heuristic classifier; select_model consumes it via task_routes (M3).

Stability: Experimental.
"""

from __future__ import annotations

import logging
import re
from contextlib import AbstractAsyncContextManager, aclosing
from typing import TYPE_CHECKING, AsyncIterator, Callable, Literal, Mapping, Protocol

from zygos.errors import ProviderError
from zygos.models.catalog import LOCAL_PROVIDERS

from zygos.providers.types import GenerationChunk, GenerationRequest, GenerationResult
from zygos.runtime.context import ExecutionContext
from zygos.services.router import ProviderRouter, RouteChoice

if TYPE_CHECKING:
    from zygos.models.default import DefaultStatus

_log = logging.getLogger("zygos.models")

TaskClassification = Literal["simple", "standard", "complex_reasoning", "code"]

_CODE_MARKERS = ("```", "def ", "import ", "function ")
_REASONING = re.compile(r"\b(why|analyze|prove|design|architecture|compare|trade-?off)\b", re.IGNORECASE)


def classify_task(prompt: str) -> TaskClassification:
    if any(marker in prompt for marker in _CODE_MARKERS):
        return "code"
    if len(prompt) > 800 or _REASONING.search(prompt):
        return "complex_reasoning"
    if len(prompt) < 80:
        return "simple"
    return "standard"


class ResidencyLike(Protocol):
    """Keeps a local model loaded for a call (RFC-0013 §5; implemented in Task 4).

    ``ensure_resident`` loads the route's model if needed (reporting it through
    ``on_loading``) and raises ``ProviderError`` when the load fails; ``turn``
    marks the model in use for the call so it is not unloaded under it."""

    async def ensure_resident(
        self,
        ctx: ExecutionContext,
        route: RouteChoice,
        *,
        on_loading: Callable[[RouteChoice], None] | None = None,
    ) -> None: ...

    def turn(self, route: RouteChoice) -> AbstractAsyncContextManager[None]: ...


class ModelService(Protocol):
    def classify_task(self, prompt: str) -> TaskClassification: ...

    def select_model(self, classification: TaskClassification | None = None) -> RouteChoice: ...

    async def generate(
        self,
        ctx: ExecutionContext,
        request: GenerationRequest,
        *,
        route: RouteChoice | None = None,
        on_route: Callable[[RouteChoice], None] | None = None,
        on_loading: Callable[[RouteChoice], None] | None = None,
    ) -> GenerationResult: ...

    def stream(
        self,
        ctx: ExecutionContext,
        request: GenerationRequest,
        *,
        route: RouteChoice | None = None,
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

    def _saved_default(self) -> RouteChoice | None:
        """The saved default when it is in effect, looked up on every call."""
        if self._default_status is None:
            return None
        status = self._default_status()
        return status.route if status.source == "saved" else None

    def _first(self, route: RouteChoice | None) -> RouteChoice | None:
        return route if route is not None else self._saved_default()

    def _needs_residency(self, first: RouteChoice | None) -> bool:
        return first is not None and self._residency is not None and first.provider in LOCAL_PROVIDERS

    async def _make_resident(
        self, ctx: ExecutionContext, first: RouteChoice,
        on_loading: Callable[[RouteChoice], None] | None,
    ) -> bool:
        """Load ``first``; a failed load falls back through the router's order."""
        assert self._residency is not None
        try:
            await self._residency.ensure_resident(ctx, first, on_loading=on_loading)
        except ProviderError as exc:
            _log.warning("%s/%s can't be loaded (%s); falling back", first.provider, first.model, exc)
            return False
        return True

    def select_model(self, classification: TaskClassification | None = None) -> RouteChoice:
        if classification is not None and classification in self._task_routes:
            return self._task_routes[classification]
        saved = self._saved_default()
        if saved is not None:
            return saved
        return self._router.first_eligible()

    async def generate(
        self,
        ctx: ExecutionContext,
        request: GenerationRequest,
        *,
        route: RouteChoice | None = None,
        on_route: Callable[[RouteChoice], None] | None = None,
        on_loading: Callable[[RouteChoice], None] | None = None,
    ) -> GenerationResult:
        first = self._first(route)
        if self._needs_residency(first):
            assert first is not None and self._residency is not None
            if await self._make_resident(ctx, first, on_loading):
                async with self._residency.turn(first):
                    return await self._router.generate(ctx, request, first=first, on_route=on_route)
            first = None
        return await self._router.generate(ctx, request, first=first, on_route=on_route)

    def stream(
        self,
        ctx: ExecutionContext,
        request: GenerationRequest,
        *,
        route: RouteChoice | None = None,
        on_route: Callable[[RouteChoice], None] | None = None,
        on_loading: Callable[[RouteChoice], None] | None = None,
    ) -> AsyncIterator[GenerationChunk]:
        first = self._first(route)
        if self._needs_residency(first):
            assert first is not None
            return self._resident_stream(ctx, request, first, on_route, on_loading)
        return self._router.stream(ctx, request, first=first, on_route=on_route)

    async def _resident_stream(
        self,
        ctx: ExecutionContext,
        request: GenerationRequest,
        first: RouteChoice,
        on_route: Callable[[RouteChoice], None] | None,
        on_loading: Callable[[RouteChoice], None] | None,
    ) -> AsyncIterator[GenerationChunk]:
        assert self._residency is not None
        if not await self._make_resident(ctx, first, on_loading):
            async with aclosing(self._router.stream(ctx, request, on_route=on_route)) as chunks:
                async for chunk in chunks:
                    yield chunk
            return
        async with self._residency.turn(first):
            async with aclosing(self._router.stream(ctx, request, first=first, on_route=on_route)) as chunks:
                async for chunk in chunks:
                    yield chunk
