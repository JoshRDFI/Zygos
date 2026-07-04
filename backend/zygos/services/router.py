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


@dataclass(frozen=True)
class RouteChoice:
    provider: str
    model: str


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

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self._now() - self._opened_at >= self._cooldown_s:
            return "half_open"
        return "open"

    def allows(self) -> bool:
        return self.state != "open"

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self._opened_at = None
        self.last_error_code = None

    def record_failure(self, code: str) -> None:
        self.consecutive_failures += 1
        self.last_error_code = code
        if self.consecutive_failures >= self._threshold:
            self._opened_at = self._now()


class _RateLimiter:
    def __init__(self, max_per_minute: int, now: Callable[[], float]) -> None:
        self._max = max_per_minute
        self._now = now
        self._timestamps: list[float] = []

    def _prune(self) -> None:
        cutoff = self._now() - 60.0
        self._timestamps = [t for t in self._timestamps if t > cutoff]

    def used(self) -> int:
        self._prune()
        return len(self._timestamps)

    def allows(self) -> bool:
        return self.used() < self._max

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
        max_requests_per_minute: int = 60,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
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

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        last_error: ProviderError | None = None
        for route in self._eligible():
            provider = self._providers[route.provider]
            routed = request.model_copy(update={"model": route.model})
            for attempt in range(1, self._max_attempts + 1):
                # Each attempt (including retries) consumes a rate-limit window
                # because each represents a real provider request.
                self._limiters[route.provider].record()
                try:
                    result = await provider.generate(routed)
                except ProviderError as error:
                    last_error = error
                    self._breakers[route].record_failure(error.code)
                    if not error.retryable or attempt == self._max_attempts:
                        break  # next route
                    await self._sleep(self._backoff_ms * (self._backoff_multiplier ** (attempt - 1)) / 1000.0)
                    continue
                self._breakers[route].record_success()
                return result
        raise last_error or ProviderUnavailable("No eligible provider routes", provider="router")

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        last_error: ProviderError | None = None
        for route in self._eligible():
            provider = self._providers[route.provider]
            routed = request.model_copy(update={"model": route.model})
            self._limiters[route.provider].record()
            started = False
            try:
                async for chunk in provider.stream(routed):
                    started = True
                    yield chunk
                self._breakers[route].record_success()
                return
            except ProviderError as error:
                self._breakers[route].record_failure(error.code)
                if started or not error.retryable:
                    raise
                last_error = error
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
                for route in self._routes
            )
        )
