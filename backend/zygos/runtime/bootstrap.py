"""Composition root (RFC-0001 §3).

The ONLY module allowed to construct concrete service implementations.
It may only construct and connect — any logic beyond assembly is a
review-blocking smell.

Stability: Experimental.
"""

from dataclasses import dataclass
from pathlib import Path

import httpx

from zygos.config.loader import load_config
from zygos.config.schema import ZygosConfig
from zygos.plugins.resolver import PluginRegistry
from zygos.providers.base import DEFAULT_BASE_URLS, Provider, ProviderSettings
from zygos.services.model import DefaultModelService, ModelService
from zygos.services.router import ProviderRouter, RouteChoice


@dataclass(frozen=True)
class RuntimeAssembly:
    config: ZygosConfig
    plugins: PluginRegistry
    model_service: ModelService
    http_client: httpx.AsyncClient

    async def aclose(self) -> None:
        await self.http_client.aclose()


def _provider_settings(config: ZygosConfig, name: str) -> ProviderSettings:
    credential = config.providers.credentials.get(name)
    base_url = (credential.base_url if credential else None) or DEFAULT_BASE_URLS.get(name)
    if base_url is None:
        base_url = "http://localhost"
    return ProviderSettings(base_url=base_url, api_key=credential.api_key if credential else None)


def build_runtime(config_path: Path | None = None) -> RuntimeAssembly:
    config = load_config(config_path)
    registry = PluginRegistry(config.plugins)
    client = httpx.AsyncClient()

    routes = [
        RouteChoice(provider=route.provider, model=route.model)
        for route in [config.providers.primary, *config.providers.fallbacks]
    ]
    providers: dict[str, Provider] = {}
    for route in routes:
        if route.provider in providers:
            continue
        provider_cls = registry.resolve("providers", route.provider)
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
    return RuntimeAssembly(
        config=config,
        plugins=registry,
        model_service=DefaultModelService(router),
        http_client=client,
    )
