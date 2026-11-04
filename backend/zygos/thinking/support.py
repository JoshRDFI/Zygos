"""Per-model thinking-support probe and cache (RFC-0012 §5, §6).

Stability: Experimental.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from zygos.providers.base import Provider
from zygos.services.router import RouteChoice

PROBE_TIMEOUT_S = 5.0


class ThinkingSupport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    supported: bool
    reason: str | None = None


class ThinkingSupportChecker:
    """Resolves whether a route's model can think. check() never raises; only
    successful probes are cached (a failure is retried on the next check)."""

    def __init__(self, providers: Mapping[str, Provider]) -> None:
        self._providers = providers
        self._cache: dict[tuple[str, str], ThinkingSupport] = {}

    def cached(self, route: RouteChoice) -> ThinkingSupport | None:
        return self._cache.get((route.provider, route.model))

    async def check(self, route: RouteChoice) -> ThinkingSupport:
        key = (route.provider, route.model)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        provider = self._providers.get(route.provider)
        probe = getattr(provider, "thinking_support", None)
        if probe is None:
            return ThinkingSupport(
                supported=False,
                reason=f"thinking controls aren't available for {route.provider} yet",
            )
        try:
            result = await asyncio.wait_for(probe(route.model), PROBE_TIMEOUT_S)
        except Exception:
            return ThinkingSupport(supported=False, reason="couldn't check the model")
        self._cache[key] = result
        return result
