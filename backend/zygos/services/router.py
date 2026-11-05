"""Provider routing with explicit, snapshotable state (RFC-0001 §4).

All routing state lives in this module's objects and is exposed via
snapshot() — nothing hides in ad-hoc maps (retires v1 finding #3). The
router knows providers only through the Provider protocol (finding #4).

Stability: Experimental.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Mapping, Sequence

from zygos.errors import ProviderError, ProviderUnavailable
from zygos.providers.base import Provider
from zygos.providers.types import GenerationChunk, GenerationRequest, GenerationResult
from zygos.runtime.context import ExecutionContext
from zygos.runtime.events import CircuitClosed, CircuitOpened, RouteClaimed, RouteSkipped


@dataclass(frozen=True)
class RouteChoice:
    provider: str
    model: str


@dataclass(frozen=True)
class RouteClaim:
    route: RouteChoice
    probe: bool


@dataclass(frozen=True)
class RouteStatus:
    provider: str
    model: str
    circuit: str  # "closed" | "open" | "half_open"
    consecutive_failures: int
    requests_in_window: int
    last_error_code: str | None


@dataclass(frozen=True)
class RouterSnapshot:
    routes: tuple[RouteStatus, ...]


class _CircuitBreaker:
    def __init__(self, threshold: int, cooldown_s: float, now: Callable[[], float]) -> None:
        self._threshold = threshold
        self._cooldown_s = cooldown_s
        self._now = now
        self.consecutive_failures = 0
        self._opened_at: float | None = None
        self.last_error_code: str | None = None
        self._probing = False

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self._now() - self._opened_at >= self._cooldown_s:
            return "half_open"
        return "open"

    def allows(self) -> bool:
        return self.state != "open"

    def admit(self) -> tuple[bool, bool]:
        """Atomically decide admission. Returns (admit, probe). No await."""
        state = self.state
        if state == "closed":
            return (True, False)
        if state == "open":
            return (False, False)
        # half_open (cooldown elapsed): admit exactly one probe.
        if self._probing:
            return (False, False)
        self._probing = True
        return (True, True)

    def clear_probe(self) -> None:
        """Finally-path escape hatch: release the half-open probe slot if the
        probe attempt died without recording an outcome (RFC-0002 §1)."""
        self._probing = False

    def record_success(self, *, probe: bool) -> bool:
        """Record a success. Returns True iff this closed an open/half-open breaker."""
        if probe:
            self._probing = False
            was_open = self._opened_at is not None
            self.consecutive_failures = 0
            self._opened_at = None
            self.last_error_code = None
            return was_open
        # Non-probe success: only meaningful when the breaker is closed. It must
        # not touch _probing (a concurrent probe may be outstanding) and must not
        # reset a breaker a concurrent failure just opened (AC5).
        if self._opened_at is None:
            self.consecutive_failures = 0
        return False

    def record_failure(self, code: str, *, probe: bool) -> bool:
        """Record a failure. Returns True iff this opened/re-opened the breaker."""
        self.last_error_code = code
        if probe:
            self._probing = False
            self._opened_at = self._now()  # failed probe re-opens with fresh cooldown
            return True  # half_open -> open transition
        # Non-probe failure: must not touch _probing.
        self.consecutive_failures += 1
        if self._opened_at is None and self.consecutive_failures >= self._threshold:
            self._opened_at = self._now()
            return True  # closed -> open transition
        return False


class _RateLimiter:
    def __init__(self, max_per_minute: int | None, now: Callable[[], float]) -> None:
        self._max = max_per_minute  # None = unthrottled (still counted for the snapshot)
        self._now = now
        self._timestamps: list[float] = []

    def _prune(self) -> None:
        cutoff = self._now() - 60.0
        self._timestamps = [t for t in self._timestamps if t > cutoff]

    def used(self) -> int:
        self._prune()
        return len(self._timestamps)

    def allows(self) -> bool:
        return self._max is None or self.used() < self._max

    def record(self) -> None:
        self._timestamps.append(self._now())


class ProviderRouter:
    def __init__(
        self,
        routes: Sequence[RouteChoice],
        providers: Mapping[str, Provider],
        *,
        max_attempts: int = 3,
        backoff_ms: int = 250,
        backoff_multiplier: float = 2.0,
        failure_threshold: int = 5,
        cooldown_s: float = 30.0,
        max_requests_per_minute: int | None = None,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        provider_factory: Callable[[str], Provider | None] | None = None,
    ) -> None:
        missing = [r.provider for r in routes if r.provider not in providers]
        if missing:
            raise ValueError(f"Routes name providers with no implementation: {missing}")
        self._routes = tuple(routes)
        self._providers = dict(providers)
        self._max_attempts = max_attempts
        self._backoff_ms = backoff_ms
        self._backoff_multiplier = backoff_multiplier
        self._sleep = sleep
        self._breakers = {r: _CircuitBreaker(failure_threshold, cooldown_s, now) for r in self._routes}
        self._limiters = {name: _RateLimiter(max_requests_per_minute, now) for name in self._providers}
        # Ad-hoc `first` routes (RFC-0013 §5): created synchronously on first use,
        # kept for the router's lifetime, listed in snapshot() after the configured ones.
        self._failure_threshold = failure_threshold
        self._cooldown_s = cooldown_s
        self._max_requests_per_minute = max_requests_per_minute
        self._now = now
        self._provider_factory = provider_factory
        self._factory_results: dict[str, Provider | None] = {}
        self._adhoc_routes: list[RouteChoice] = []

    def _provider_for(self, name: str) -> Provider | None:
        """Configured provider, else the factory's (called at most once per name,
        None cached too). Synchronous — no await between check and insert."""
        if name in self._providers:
            return self._providers[name]
        if name not in self._factory_results:
            made = self._provider_factory(name) if self._provider_factory is not None else None
            self._factory_results[name] = made
            if made is not None:
                self._limiters[name] = _RateLimiter(self._max_requests_per_minute, self._now)
        return self._factory_results[name]

    async def _order(self, ctx: ExecutionContext, first: RouteChoice | None) -> list[RouteChoice]:
        """[first] + configured routes without it. A `first` with no provider is
        reported as skipped and dropped. first=None -> configured order unchanged."""
        if first is None:
            return list(self._routes)
        rest = [r for r in self._routes if r != first]
        if self._provider_for(first.provider) is None:
            await ctx.emit(
                RouteSkipped(provider=first.provider, model=first.model, reason="no_provider"),
                source="router",
            )
            return rest
        if first not in self._breakers:
            self._breakers[first] = _CircuitBreaker(self._failure_threshold, self._cooldown_s, self._now)
            self._adhoc_routes.append(first)
        return [first, *rest]

    def _refusal(self, route: RouteChoice) -> str:
        return "rate_limited" if not self._limiters[route.provider].allows() else "circuit_open"

    def _eligible(self) -> list[RouteChoice]:
        return [
            route
            for route in self._routes
            if self._breakers[route].allows() and self._limiters[route.provider].allows()
        ]

    def first_eligible(self) -> RouteChoice:
        eligible = self._eligible()
        if not eligible:
            raise ProviderUnavailable("No eligible provider routes", provider="router")
        return eligible[0]

    def _try_claim(self, route: RouteChoice) -> RouteClaim | None:
        """Atomically decide admission AND record it. Synchronous — no await."""
        limiter = self._limiters[route.provider]
        breaker = self._breakers[route]
        if not limiter.allows():
            return None
        admit, probe = breaker.admit()
        if not admit:
            return None
        limiter.record()
        return RouteClaim(route=route, probe=probe)

    async def generate(
        self,
        ctx: ExecutionContext,
        request: GenerationRequest,
        *,
        first: RouteChoice | None = None,
        on_route: Callable[[RouteChoice], None] | None = None,
    ) -> GenerationResult:
        last_error: ProviderError | None = None
        for route in await self._order(ctx, first):
            provider = self._provider_for(route.provider)
            assert provider is not None
            routed = request.model_copy(update={"model": route.model})
            breaker = self._breakers[route]
            for attempt in range(1, self._max_attempts + 1):
                if ctx.cancelled:
                    raise ProviderUnavailable("cancelled", provider="router")
                claim = self._try_claim(route)
                if claim is None:
                    if route == first and attempt == 1:
                        await ctx.emit(
                            RouteSkipped(provider=route.provider, model=route.model,
                                         reason=self._refusal(route)),
                            source="router",
                        )
                    break  # route not admitting (rate-limited or open); next route
                settled = False
                try:
                    await ctx.emit(
                        RouteClaimed(provider=route.provider, model=route.model, probe=claim.probe),
                        source="router",
                    )
                    try:
                        result = await provider.generate(routed)  # the only await in the attempt
                    except ProviderError as error:
                        settled = True
                        last_error = error
                        if breaker.record_failure(error.code, probe=claim.probe):
                            await ctx.emit(
                                CircuitOpened(
                                    provider=route.provider, model=route.model, last_error_code=error.code
                                ),
                                source="router",
                            )
                        if not error.retryable or attempt == self._max_attempts:
                            break
                        await self._sleep(self._backoff_ms * (self._backoff_multiplier ** (attempt - 1)) / 1000.0)
                        continue
                    settled = True
                    if breaker.record_success(probe=claim.probe):
                        await ctx.emit(
                            CircuitClosed(provider=route.provider, model=route.model),
                            source="router",
                        )
                    if on_route is not None:
                        on_route(route)
                    return result
                finally:
                    if claim.probe and not settled:
                        breaker.clear_probe()
        raise last_error or ProviderUnavailable("No eligible provider routes", provider="router")

    async def stream(
        self,
        ctx: ExecutionContext,
        request: GenerationRequest,
        *,
        first: RouteChoice | None = None,
        on_route: Callable[[RouteChoice], None] | None = None,
    ) -> AsyncIterator[GenerationChunk]:
        last_error: ProviderError | None = None
        for route in await self._order(ctx, first):
            provider = self._provider_for(route.provider)
            assert provider is not None
            routed = request.model_copy(update={"model": route.model})
            breaker = self._breakers[route]
            if ctx.cancelled:
                raise ProviderUnavailable("cancelled", provider="router")
            claim = self._try_claim(route)
            if claim is None:
                if route == first:
                    await ctx.emit(
                        RouteSkipped(provider=route.provider, model=route.model,
                                     reason=self._refusal(route)),
                        source="router",
                    )
                continue
            started = False
            settled = False
            try:
                await ctx.emit(
                    RouteClaimed(provider=route.provider, model=route.model, probe=claim.probe),
                    source="router",
                )
                async for chunk in provider.stream(routed):
                    if not started:
                        started = True
                        if on_route is not None:
                            on_route(route)
                    yield chunk
                settled = True
                if not started and on_route is not None:
                    on_route(route)  # zero-chunk stream completed: it still answered
                if breaker.record_success(probe=claim.probe):
                    await ctx.emit(
                        CircuitClosed(provider=route.provider, model=route.model),
                        source="router",
                    )
                return
            except ProviderError as error:
                settled = True
                if breaker.record_failure(error.code, probe=claim.probe):
                    await ctx.emit(
                        CircuitOpened(
                            provider=route.provider, model=route.model, last_error_code=error.code
                        ),
                        source="router",
                    )
                if started or not error.retryable:
                    raise
                last_error = error
            finally:
                if claim.probe and not settled:
                    breaker.clear_probe()
        raise last_error or ProviderUnavailable("No eligible provider routes", provider="router")

    def snapshot(self) -> RouterSnapshot:
        return RouterSnapshot(
            routes=tuple(
                RouteStatus(
                    provider=route.provider,
                    model=route.model,
                    circuit=self._breakers[route].state,
                    consecutive_failures=self._breakers[route].consecutive_failures,
                    requests_in_window=self._limiters[route.provider].used(),
                    last_error_code=self._breakers[route].last_error_code,
                )
                for route in (*self._routes, *self._adhoc_routes)
            )
        )
