"""Per-model thinking-support probe and cache (RFC-0012 §5, §6).

Stability: Experimental.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping

from zygos.providers.base import Provider
from zygos.providers.types import PROBE_TIMEOUT_S, ThinkingSupport
from zygos.services.router import RouteChoice

__all__ = ["PROBE_TIMEOUT_S", "UNCHECKED_REASON", "ThinkingSupport", "ThinkingSupportChecker",
           "check_selected"]

UNCHECKED_REASON = "couldn't check the model"


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
            return ThinkingSupport(supported=False, reason=UNCHECKED_REASON)
        self._cache[key] = result
        return result


async def check_selected(checker, select: Callable[[], RouteChoice]) -> ThinkingSupport:
    """Pick a route with ``select`` and check it; never raises.

    A route that cannot be picked (e.g. ``ProviderUnavailable``: every circuit
    open), a missing checker, or a checker that raises all count as unsupported
    with :data:`UNCHECKED_REASON`.
    """
    if checker is None:
        return ThinkingSupport(supported=False, reason=UNCHECKED_REASON)
    try:
        return await checker.check(select())
    except Exception:  # noqa: BLE001 - an unroutable or unprobeable model is simply unsupported
        return ThinkingSupport(supported=False, reason=UNCHECKED_REASON)
