"""Composition root (RFC-0001 §3).

The ONLY module allowed to construct concrete service implementations.
It may only construct and connect — any logic beyond assembly is a
review-blocking smell.

Stability: Experimental.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from zygos.config.loader import load_config
from zygos.config.schema import ZygosConfig
from zygos.plugins.resolver import PluginRegistry
from zygos.providers.base import DEFAULT_BASE_URLS, Provider, ProviderSettings
from zygos.reasoning.service import DefaultReasoningService, ReasoningService
from zygos.runtime.capabilities import CapabilityRegistry
from zygos.runtime.context import ExecutionContext, root_context
from zygos.runtime.events import EventBus, InProcessEventBus, Subscriber
from zygos.services.model import DefaultModelService, ModelService
from zygos.services.router import ProviderRouter, RouteChoice

REGISTER_CAPABILITIES_STAGE = "register_capabilities"


@dataclass(frozen=True)
class RuntimeAssembly:
    config: ZygosConfig
    plugins: PluginRegistry
    model_service: ModelService
    reasoning_service: ReasoningService
    http_client: httpx.AsyncClient
    event_bus: EventBus
    capability_registry: CapabilityRegistry
    providers: Mapping[str, Provider]
    lifecycle_stage: str

    def new_context(self, *, session_id: str | None = None) -> ExecutionContext:
        return root_context(self.event_bus, session_id=session_id)

    async def aclose(self) -> None:
        await self.http_client.aclose()


def _provider_settings(config: ZygosConfig, name: str) -> ProviderSettings:
    credential = config.providers.credentials.get(name)
    base_url = (credential.base_url if credential else None) or DEFAULT_BASE_URLS.get(name)
    if base_url is None:
        base_url = "http://localhost"
    return ProviderSettings(base_url=base_url, api_key=credential.api_key if credential else None)


def _provider_healthy(router: ProviderRouter, provider_name: str) -> bool:
    """A provider is healthy if any of its routes has a non-open circuit."""
    return any(
        status.circuit != "open"
        for status in router.snapshot().routes
        if status.provider == provider_name
    )


def build_runtime(
    config_path: Path | None = None, *, subscribers: Sequence[Subscriber] = ()
) -> RuntimeAssembly:
    config = load_config(config_path)
    plugin_registry = PluginRegistry(config.plugins)
    client = httpx.AsyncClient()

    bus = InProcessEventBus()
    for handler in subscribers:
        bus.subscribe(handler)

    routes = [
        RouteChoice(provider=route.provider, model=route.model)
        for route in [config.providers.primary, *config.providers.fallbacks]
    ]
    providers: dict[str, Provider] = {}
    for route in routes:
        if route.provider in providers:
            continue
        provider_cls = plugin_registry.resolve("providers", route.provider)
        providers[route.provider] = provider_cls(
            settings=_provider_settings(config, route.provider), client=client
        )

    router = ProviderRouter(
        routes,
        providers,
        max_attempts=config.providers.retry.max_attempts,
        backoff_ms=config.providers.retry.backoff_ms,
        backoff_multiplier=config.providers.retry.backoff_multiplier,
        failure_threshold=config.providers.circuit_breaker.failure_threshold,
        cooldown_s=config.providers.circuit_breaker.cooldown_s,
        max_requests_per_minute=config.providers.rate_limit.max_requests_per_minute,
    )

    registry = CapabilityRegistry(health_of=lambda name: _provider_healthy(router, name))
    seen: set[str] = set()
    for priority, route in enumerate(routes):
        if route.provider in seen:
            continue
        seen.add(route.provider)
        provider_obj = providers[route.provider]
        for capability in getattr(provider_obj, "capabilities", frozenset()):
            registry.register(capability, provider_obj, priority=priority)

    task_routes = {
        classification: RouteChoice(provider=route.provider, model=route.model)
        for classification, route in config.providers.task_routes.items()
    }
    model_service = DefaultModelService(router, task_routes=task_routes)
    reasoning_service = DefaultReasoningService(model_service, config.reasoning)
    return RuntimeAssembly(
        config=config,
        plugins=plugin_registry,
        model_service=model_service,
        reasoning_service=reasoning_service,
        http_client=client,
        event_bus=bus,
        capability_registry=registry,
        providers=providers,
        lifecycle_stage=REGISTER_CAPABILITIES_STAGE,
    )
