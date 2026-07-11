"""Composition root (RFC-0001 §3).

The ONLY module allowed to construct concrete service implementations.
It may only construct and connect — any logic beyond assembly is a
review-blocking smell.

Stability: Experimental.
"""

import time
import uuid
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from zygos.config.loader import load_config
from zygos.config.schema import ZygosConfig
from zygos.errors import ConfigError
from zygos.memory.retrieve import (
    Fts5RelevanceIndex, HybridRelevanceIndex, MemoryRetriever,
    RelevanceIndex, RetrievalWeights, VectorRelevanceIndex,
)
from zygos.memory.service import DefaultMemoryService, MemoryService
from zygos.memory.store import MemoryStore
from zygos.memory.vector_search import VectorSearch
from zygos.plugins.resolver import PluginRegistry
from zygos.providers.base import DEFAULT_BASE_URLS, Provider, ProviderSettings
from zygos.providers.embedding import Embedder
from zygos.providers.embedding_local import DEFAULT_LOCAL_MODEL
from zygos.reasoning.service import DefaultReasoningService, ReasoningService
from zygos.runtime.capabilities import Capability, CapabilityRegistry
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
    memory_service: MemoryService | None
    http_client: httpx.AsyncClient
    event_bus: EventBus
    capability_registry: CapabilityRegistry
    providers: Mapping[str, Provider]
    lifecycle_stage: str
    _memory_store: MemoryStore | None

    def new_context(self, *, session_id: str | None = None) -> ExecutionContext:
        return root_context(self.event_bus, session_id=session_id)

    async def aclose(self) -> None:
        if self._memory_store is not None:
            self._memory_store.close()
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


_EMBED_DEFAULT_MODEL: Mapping[str, str] = {"ollama": "nomic-embed-text"}


def _build_embedder(config, client, plugin_registry) -> tuple[Embedder | None, str]:
    """Construct the configured embedder, DECOUPLED from the chat route (RFC-0006 §6).
    Returns (embedder, model). Returns (None, model) when the local extra is missing
    so the caller can degrade to FTS5."""
    ec = config.memory.embedding
    backend = ec.backend
    if backend == "local":
        model = ec.model or DEFAULT_LOCAL_MODEL
        try:
            from zygos.providers.embedding_local import LocalEmbedder
            return LocalEmbedder(model=model), model
        except ImportError:
            return None, model
    model = ec.model or _EMBED_DEFAULT_MODEL.get(backend, "")
    if not model:
        raise ConfigError(
            f"embedding backend {backend!r} requires memory.embedding.model "
            f"(no universal default for a cloud embedder)"
        )
    provider_cls = plugin_registry.resolve("providers", backend)
    embedder = provider_cls(settings=_provider_settings(config, backend), client=client)
    return embedder, model


def _memory_index(mode, store, embedder, model) -> RelevanceIndex:
    """Select the RelevanceIndex for the configured mode. A non-fts5 mode with no
    resolved embedder degrades to FTS5 with ONE loud warning (RFC-0006 §5)."""
    fts = Fts5RelevanceIndex(store.connection)
    if mode == "fts5":
        return fts
    if embedder is None:
        warnings.warn(
            f"retrieval_mode={mode!r} requested but no embedder resolved; "
            f"degrading to fts5 lexical retrieval",
            stacklevel=2,
        )
        return fts
    vector_search = VectorSearch(store, model=model)
    if mode == "vector":
        return VectorRelevanceIndex(embedder, vector_search, model=model)
    return HybridRelevanceIndex(fts, vector_search, embedder, model=model)


def _register_embedding(registry: CapabilityRegistry, embedder: Embedder) -> None:
    """Register the resolved embedder's EMBEDDING binding for manifest/doctor,
    deduped by name (it may already be registered via a chat-route)."""
    existing = {b.provider for b in registry.snapshot().bindings.get(Capability.EMBEDDING, ())}
    if embedder.name not in existing:
        registry.register(Capability.EMBEDDING, embedder, priority=0)


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

    memory_service: MemoryService | None = None
    memory_store: MemoryStore | None = None
    if config.memory.enabled:
        memory_store = MemoryStore(config.memory.db_path)
        if config.memory.retrieval_mode != "fts5":
            embedder, embedding_model = _build_embedder(config, client, plugin_registry)
        else:
            embedder, embedding_model = None, ""
        relevance_index = _memory_index(
            config.memory.retrieval_mode, memory_store, embedder, embedding_model
        )
        if embedder is not None:
            _register_embedding(registry, embedder)
        retriever = MemoryRetriever(
            memory_store, relevance_index, clock=time.time,
            weights=RetrievalWeights(
                relevance=config.memory.retrieval_weights.relevance,
                recency=config.memory.retrieval_weights.recency,
                importance=config.memory.retrieval_weights.importance,
            ),
            half_life_s=config.memory.recency_half_life_s,
        )
        memory_service = DefaultMemoryService(
            store=memory_store, retriever=retriever, index=relevance_index,
            model_service=model_service, clock=time.time, new_id=lambda: uuid.uuid4().hex,
            token_budget=config.memory.token_budget,
            batch_size=config.memory.consolidation_batch_size,
            embedder=embedder, embedding_model=embedding_model,
            embed_batch_size=config.memory.embed_batch_size,
        )
        # `resume()` is intentionally NOT awaited here — build_runtime is a sync
        # composition root; the async consumer (M8) drains it at startup.

    return RuntimeAssembly(
        config=config,
        plugins=plugin_registry,
        model_service=model_service,
        reasoning_service=reasoning_service,
        memory_service=memory_service,
        http_client=client,
        event_bus=bus,
        capability_registry=registry,
        providers=providers,
        lifecycle_stage=REGISTER_CAPABILITIES_STAGE,
        _memory_store=memory_store,
    )
