"""Composition root (RFC-0001 §3).

The ONLY module allowed to construct concrete service implementations.
It may only construct and connect — any logic beyond assembly is a
review-blocking smell.

Stability: Experimental.
"""

import time
import uuid
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from zygos.agent.config import ToolLoopConfig
from zygos.backends.settings import BackendsSettings
from zygos.backends.addresses import BACKEND_ADDRESSES, AddressSource, resolve_address
from zygos.backends.store import BackendsStore, SqliteBackendsStore
from zygos.config.loader import load_config
from zygos.config.schema import ZygosConfig
from zygos.errors import ConfigError
from zygos.hardware.probe import HardwareProbe
from zygos.mcp.store import SqliteMcpStore
from zygos.mcp.supervisor import McpSupervisor
from zygos.memory.retrieve import (
    Fts5RelevanceIndex, HybridRelevanceIndex, MemoryRetriever,
    RelevanceIndex, RetrievalWeights, VectorRelevanceIndex,
)
from zygos.memory.service import DefaultMemoryService, MemoryService
from zygos.memory.store import MemoryStore
from zygos.memory.vector_search import VectorSearch
from zygos.models.catalog import ModelCatalog
from zygos.models.choices import ModelChoicesStore, SqliteModelChoicesStore
from zygos.models.default import DefaultStatus, can_create, resolve_default
from zygos.models.residency import ResidencyManager
from zygos.models.store import ProfileStore
from zygos.personalization import PreferencesStore, SqlitePreferencesStore
from zygos.secrets import SecretsHandle, build_secret_store
from zygos.plugins.resolver import PluginRegistry
from zygos.providers.base import Provider, ProviderSettings
from zygos.providers.embedding import Embedder
from zygos.providers.embedding_local import DEFAULT_LOCAL_MODEL
from zygos.reasoning.service import DefaultReasoningService, ReasoningService
from zygos.runtime.capabilities import Capability, CapabilityRegistry
from zygos.runtime.context import ExecutionContext, root_context
from zygos.runtime.events import EventBus, InProcessEventBus, Subscriber
from zygos.services.model import DefaultModelService, ModelService
from zygos.services.router import ProviderRouter, RouterSnapshot, RouteChoice
from zygos.thinking.support import ThinkingSupportChecker
from zygos.tools.build import ToolBuildContext
from zygos.tools.permissions import PermissionPolicy
from zygos.tools.registry import ToolRegistry
from zygos.tools.service import ToolService
from zygos.tools.types import Tool
from zygos.voice import VoiceService, build_stt_plugin, build_tts_plugin

REGISTER_CAPABILITIES_STAGE = "register_capabilities"
LOAD_SKILLS_STAGE = "load_skills"
LOAD_MEMORY_STAGE = "load_memory"
ACCEPT_REQUESTS_STAGE = "accept_requests"


@dataclass(frozen=True)
class RuntimeAssembly:
    config: ZygosConfig
    plugins: PluginRegistry
    model_service: ModelService
    reasoning_service: ReasoningService
    reasoning_factory: Callable[[], ReasoningService]
    memory_service: MemoryService | None
    voice_service: "VoiceService | None"
    preferences: PreferencesStore
    http_client: httpx.AsyncClient
    event_bus: EventBus
    capability_registry: CapabilityRegistry
    providers: Mapping[str, Provider]
    thinking_support: ThinkingSupportChecker
    tool_service: ToolService
    tools: tuple[Tool, ...]
    tool_loop_config: ToolLoopConfig
    _router: ProviderRouter
    lifecycle_stage: str
    _memory_store: MemoryStore | None
    hardware: HardwareProbe
    profiles: ProfileStore
    model_catalog: ModelCatalog
    model_choices: ModelChoicesStore
    default_status: Callable[[], DefaultStatus]
    backends: BackendsStore
    address_sources: Mapping[str, AddressSource]
    addresses_at_start: Mapping[str, str]
    secrets: SecretsHandle
    mcp: McpSupervisor
    residency: ResidencyManager | None = None

    def new_context(self, *, session_id: str | None = None) -> ExecutionContext:
        return root_context(self.event_bus, session_id=session_id)

    def router_snapshot(self) -> RouterSnapshot:
        """Live per-route circuit snapshot (RFC-0007 §8 health surface)."""
        return self._router.snapshot()

    async def aclose(self) -> None:
        # MCP first: stopping local servers and finishing its state writes needs the rest.
        await self.mcp.aclose()
        if self.residency is not None:
            # A preload still running would fail on the closed client below.
            self.residency.cancel_preload()
            await self.residency.preload_done()
        if self._memory_store is not None:
            self._memory_store.close()
        await self.http_client.aclose()


def _resolve_address(
    config: ZygosConfig, name: str, backends: BackendsSettings | None = None
) -> tuple[str, AddressSource]:
    """Backends record, then config credential, then the built-in default (RFC-0014 section 2)."""
    return resolve_address(config, name, backends)


def _provider_settings(
    config: ZygosConfig, name: str, backends: BackendsSettings | None = None
) -> ProviderSettings:
    credential = config.providers.credentials.get(name)
    base_url, _source = _resolve_address(config, name, backends)
    return ProviderSettings(base_url=base_url, api_key=credential.api_key if credential else None,
                            think=config.providers.think)


def _provider_healthy(router: ProviderRouter, provider_name: str) -> bool:
    """A provider is healthy if any of its routes has a non-open circuit."""
    return any(
        status.circuit != "open"
        for status in router.snapshot().routes
        if status.provider == provider_name
    )


_EMBED_DEFAULT_MODEL: Mapping[str, str] = {"ollama": "nomic-embed-text"}


def _build_embedder(config, client, plugin_registry, backends=None) -> tuple[Embedder | None, str]:
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
        except Exception as error:  # extra missing OR first-run model fetch / construct failure
            warnings.warn(
                f"local embedder unavailable ({error!r}); embedding will degrade to FTS5",
                stacklevel=2,
            )
            return None, model
    model = ec.model or _EMBED_DEFAULT_MODEL.get(backend, "")
    if not model:
        raise ConfigError(
            f"embedding backend {backend!r} requires memory.embedding.model "
            f"(no universal default for a cloud embedder)"
        )
    provider_cls = plugin_registry.resolve("providers", backend)
    embedder = provider_cls(settings=_provider_settings(config, backend, backends), client=client)
    return embedder, model


def _build_tools(config: ZygosConfig, plugin_registry: PluginRegistry) -> tuple[Tool, ...]:
    """Construct config-enabled tools uniformly via from_config (mirrors provider build)."""
    workspace = Path(config.tools.workspace_root)
    built: list[Tool] = []
    for name in config.tools.enabled:
        tool_cls = plugin_registry.resolve("tools", name)
        ctx = ToolBuildContext(workspace=workspace, settings=config.tools.settings.get(name, {}))
        built.append(tool_cls.from_config(ctx))
    return tuple(built)


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
    backends = SqliteBackendsStore(Path(config.personalization.db_path))
    backends_settings = backends.get()
    plugin_registry = PluginRegistry(config.plugins)
    client = httpx.AsyncClient()

    bus = InProcessEventBus()
    for handler in subscribers:
        bus.subscribe(handler)

    routes = [
        RouteChoice(provider=route.provider, model=route.model)
        for route in [config.providers.primary, *config.providers.fallbacks]
    ]
    declared_providers = frozenset(plugin_registry.list("providers"))

    def creatable(name: str) -> bool:
        credential = config.providers.credentials.get(name)
        return can_create(name, declared=declared_providers,
                          api_key=credential.api_key if credential else None)

    def provider_factory(name: str) -> Provider | None:
        if not creatable(name):
            return None
        provider_cls = plugin_registry.resolve("providers", name)
        return provider_cls(settings=_provider_settings(config, name, backends_settings), client=client)

    providers: dict[str, Provider] = {}
    address_sources: dict[str, AddressSource] = {}
    addresses_at_start: dict[str, str] = {}
    for route in routes:
        if route.provider in providers:
            continue
        provider_cls = plugin_registry.resolve("providers", route.provider)
        provider_settings = _provider_settings(config, route.provider, backends_settings)
        providers[route.provider] = provider_cls(settings=provider_settings, client=client)
        addresses_at_start[route.provider] = provider_settings.base_url
        address_sources[route.provider] = _resolve_address(
            config, route.provider, backends_settings
        )[1]
    for name in BACKEND_ADDRESSES:  # known even when no route uses them
        addresses_at_start[name], address_sources[name] = _resolve_address(
            config, name, backends_settings
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
        provider_factory=provider_factory,
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
    model_choices = SqliteModelChoicesStore(Path(config.personalization.db_path))
    config_primary = RouteChoice(config.providers.primary.provider, config.providers.primary.model)

    assembled: list[ModelCatalog] = []  # model_catalog, once assembled below

    def installed(name: str) -> frozenset[str] | None:
        if not assembled:
            raise RuntimeError("default_status() called before the runtime was assembled")
        return assembled[0].installed(name)

    def default_status() -> DefaultStatus:
        return resolve_default(
            model_choices.get(), config_primary,
            installed=installed,
            routable=lambda name: name in providers or creatable(name),
        )

    voice_service: VoiceService | None = None
    if config.voice.enabled:
        stt_plugin = build_stt_plugin(config.voice.stt)
        tts_plugin = build_tts_plugin(config.voice.tts)
        voice_service = VoiceService(stt=stt_plugin, tts=tts_plugin)
        registry.register(Capability.SPEECH_TO_TEXT, stt_plugin, priority=0)
        registry.register(Capability.TEXT_TO_SPEECH, tts_plugin, priority=0)
        # `VoiceService.start` is intentionally NOT awaited here — build_runtime
        # is a sync composition root; the async consumer (Task 10) spawns the
        # sidecar at startup.

    hardware = HardwareProbe(models_dir=config.models.ollama_models_dir)
    profiles = ProfileStore(Path(config.models.profiles_dir))
    profiles.load_all()
    model_catalog = ModelCatalog(
        providers=providers,
        profiles=profiles,
        hardware=hardware,
        config=config,
        voice_snapshot=(voice_service.snapshot if voice_service is not None else lambda: None),
        clock=lambda: datetime.now(timezone.utc),
        backends=backends,
        client=client,
        default_status=default_status,
    )
    assembled.append(model_catalog)

    # Serialised local loads, no eviction mid-turn (RFC-0013 §8).
    residency = ResidencyManager(
        router.provider_for, model_catalog, profiles,
        clock=lambda: datetime.now(timezone.utc), context=lambda: root_context(bus),
    )
    model_service = DefaultModelService(
        router, task_routes=task_routes, default_status=default_status, residency=residency)
    reasoning_service = DefaultReasoningService(model_service, config.reasoning)

    def reasoning_factory() -> ReasoningService:
        return DefaultReasoningService(model_service, config.reasoning)

    tools = _build_tools(config, plugin_registry)
    tool_registry = ToolRegistry()
    for tool in tools:
        tool_registry.register(tool)
    tool_service = ToolService(
        tool_registry, policy=PermissionPolicy(rules=config.tools.permission_rules)
    )
    # Built after the tool service, then bound to it (the supervisor needs the service).
    secrets = build_secret_store(config)
    mcp = McpSupervisor(
        SqliteMcpStore(Path(config.personalization.db_path)), secrets, tool_service,
        rules=config.tools.permission_rules, new_context=lambda: root_context(bus),
    )
    tool_service.bind_mcp_gate(mcp.gate)
    tool_loop_config = ToolLoopConfig(
        max_iterations=config.tools.max_iterations,
        default_tool_choice=config.tools.tool_choice,
    )

    memory_service: MemoryService | None = None
    memory_store: MemoryStore | None = None
    if config.memory.enabled:
        memory_store = MemoryStore(config.memory.db_path)
        if config.memory.retrieval_mode != "fts5":
            embedder, embedding_model = _build_embedder(config, client, plugin_registry, backends_settings)
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
        reasoning_factory=reasoning_factory,
        memory_service=memory_service,
        voice_service=voice_service,
        preferences=SqlitePreferencesStore(Path(config.personalization.db_path)),
        secrets=secrets,
        mcp=mcp,
        http_client=client,
        event_bus=bus,
        capability_registry=registry,
        providers=providers,
        thinking_support=ThinkingSupportChecker(providers),
        tool_service=tool_service,
        tools=tools,
        tool_loop_config=tool_loop_config,
        _router=router,
        lifecycle_stage=REGISTER_CAPABILITIES_STAGE,
        _memory_store=memory_store,
        hardware=hardware,
        profiles=profiles,
        model_catalog=model_catalog,
        model_choices=model_choices,
        default_status=default_status,
        backends=backends,
        address_sources=address_sources,
        addresses_at_start=addresses_at_start,
        residency=residency,
    )
