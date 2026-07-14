import asyncio
import dataclasses
from pathlib import Path

from zygos.plugins.resolver import PluginRegistry
from zygos.runtime.bootstrap import RuntimeAssembly, build_runtime
from zygos.runtime.capabilities import Capability


def test_build_runtime_with_defaults():
    assembly = build_runtime()
    assert assembly.config.providers.primary.provider == "ollama"
    assert isinstance(assembly.plugins, PluginRegistry)


def test_build_runtime_wires_declared_plugins(tmp_path: Path):
    file = tmp_path / "config.yaml"
    file.write_text(
        "providers:\n"
        "  primary:\n"
        "    provider: fake\n"
        "    model: demo\n"
        "tools:\n"
        "  enabled: []\n"
        "plugins:\n"
        "  providers:\n"
        "    ordered: 'collections:OrderedDict'\n"
        "    fake: 'zygos.providers.fake:FakeProvider'\n",
        encoding="utf-8",
    )
    assembly = build_runtime(file)
    from collections import OrderedDict

    assert assembly.plugins.resolve("providers", "ordered") is OrderedDict


def test_assembly_is_immutable():
    assembly = build_runtime()
    try:
        assembly.config = None  # type: ignore[misc]
        raised = False
    except dataclasses.FrozenInstanceError:
        raised = True
    assert raised, "RuntimeAssembly must be a frozen dataclass"


from zygos.providers.types import GenerationRequest, Message
from zygos.services.model import DefaultModelService


async def test_default_runtime_exposes_model_service():
    assembly = build_runtime()
    try:
        assert isinstance(assembly.model_service, DefaultModelService)
        choice = assembly.model_service.select_model()
        assert (choice.provider, choice.model) == ("ollama", "qwen3:8b")
    finally:
        await assembly.aclose()


async def test_swap_primary_to_fake_via_config_alone(tmp_path: Path):
    """RFC-0001 acceptance criterion 3: provider swap with zero code changes."""
    file = tmp_path / "config.yaml"
    file.write_text(
        "providers:\n"
        "  primary:\n"
        "    provider: fake\n"
        "    model: demo\n",
        encoding="utf-8",
    )
    assembly = build_runtime(file)
    try:
        request = GenerationRequest(messages=(Message(role="user", content="ping"),))
        result = await assembly.model_service.generate(assembly.new_context(), request)
        assert result.provider == "fake"
        assert result.model == "demo"
        assert result.text  # non-empty, produced with zero network and zero keys
    finally:
        await assembly.aclose()


from zygos.runtime.events import Event, InProcessEventBus  # noqa: E402


async def test_drop_all_subscribers_invariant(tmp_path: Path):
    file = tmp_path / "config.yaml"
    file.write_text(
        "providers:\n  primary:\n    provider: fake\n    model: demo\n",
        encoding="utf-8",
    )
    seen: list[Event] = []

    async def sub(event: Event) -> None:
        seen.append(event)

    with_sub = build_runtime(file, subscribers=[sub])
    without = build_runtime(file)
    try:
        request = GenerationRequest(messages=(Message(role="user", content="ping"),))
        r1 = await with_sub.model_service.generate(with_sub.new_context(), request)
        r2 = await without.model_service.generate(without.new_context(), request)
        # Dropping every subscriber changes nothing observable (RFC-0002 invariant).
        assert (r1.text, r1.model, r1.provider) == (r2.text, r2.model, r2.provider)
        # The attached subscriber did observe the run.
        assert any(e.type == "route.claimed" for e in seen)
        assert isinstance(with_sub.event_bus, InProcessEventBus)
    finally:
        await with_sub.aclose()
        await without.aclose()


async def test_bootstrap_exposes_reasoning_service_and_task_routes(tmp_path: Path):
    file = tmp_path / "config.yaml"
    file.write_text(
        "providers:\n"
        "  primary:\n    provider: fake\n    model: demo\n"
        "  task_routes:\n    complex_reasoning:\n      provider: fake\n      model: heavy\n"
        "reasoning:\n  enabled: true\n  profile: shallow\n",
        encoding="utf-8",
    )
    assembly = build_runtime(file)
    try:
        from zygos.reasoning.service import DefaultReasoningService
        assert isinstance(assembly.reasoning_service, DefaultReasoningService)
        assert assembly.model_service.select_model("complex_reasoning").model == "heavy"
    finally:
        await assembly.aclose()


def test_build_runtime_registers_provider_capabilities():
    runtime = build_runtime()  # default config: single ollama primary route
    try:
        resolved = runtime.capability_registry.resolve(Capability.LOCAL_INFERENCE)
        assert [b.provider for b in resolved] == ["ollama"]
        assert runtime.lifecycle_stage == "register_capabilities"
    finally:
        asyncio.run(runtime.aclose())


def test_only_routed_providers_are_bound():
    # AC4: config decides which plugins load; unrouted providers get no binding
    # even though they are declared in config.plugins.
    runtime = build_runtime()
    try:
        providers = [b.provider for b in runtime.capability_registry.resolve(Capability.LOCAL_INFERENCE)]
        assert providers == ["ollama"]  # openai/anthropic/vllm/fake declared but unrouted
    finally:
        asyncio.run(runtime.aclose())


def test_config_cannot_invent_undeclared_capability():
    # AC4: nothing registers a capability a provider does not declare.
    runtime = build_runtime()
    try:
        assert runtime.capability_registry.resolve(Capability.VISION) == ()
        assert Capability.VISION not in runtime.capability_registry.snapshot().bindings
    finally:
        asyncio.run(runtime.aclose())


def test_capability_priority_follows_route_order(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        "providers:\n"
        "  primary: {provider: ollama, model: qwen3:8b}\n"
        "  fallbacks:\n"
        "    - {provider: openai, model: gpt-4o}\n"
        "  credentials:\n"
        "    openai: {api_key: test-key}\n"
    )
    runtime = build_runtime(config)
    try:
        resolved = runtime.capability_registry.resolve(Capability.LOCAL_INFERENCE)
        assert [b.provider for b in resolved] == ["ollama", "openai"]
    finally:
        asyncio.run(runtime.aclose())


import dataclasses

from zygos.runtime.bootstrap import (
    ACCEPT_REQUESTS_STAGE,
    LOAD_MEMORY_STAGE,
    LOAD_SKILLS_STAGE,
    build_runtime,
)
from zygos.services.router import RouterSnapshot


def test_lifecycle_stage_constants_are_snake_case():
    assert LOAD_SKILLS_STAGE == "load_skills"
    assert LOAD_MEMORY_STAGE == "load_memory"
    assert ACCEPT_REQUESTS_STAGE == "accept_requests"


def test_router_snapshot_accessor_returns_live_snapshot():
    runtime = build_runtime()  # default ollama primary
    try:
        snap = runtime.router_snapshot()
        assert isinstance(snap, RouterSnapshot)
        providers = [r.provider for r in snap.routes]
        assert "ollama" in providers
    finally:
        import asyncio
        asyncio.run(runtime.aclose())


def test_dataclasses_replace_preserves_router_and_services():
    runtime = build_runtime()
    try:
        advanced = dataclasses.replace(runtime, lifecycle_stage=ACCEPT_REQUESTS_STAGE)
        assert advanced.lifecycle_stage == "accept_requests"
        # same shared instances (shallow copy), and the accessor still works
        assert advanced.model_service is runtime.model_service
        assert isinstance(advanced.router_snapshot(), RouterSnapshot)
    finally:
        import asyncio
        asyncio.run(runtime.aclose())


def test_reasoning_factory_builds_fresh_instances():
    from zygos.runtime.bootstrap import build_runtime

    runtime = build_runtime()
    try:
        a = runtime.reasoning_factory()
        b = runtime.reasoning_factory()
        assert a is not b  # fresh per call
        assert type(a) is type(runtime.reasoning_service)
    finally:
        import asyncio
        asyncio.run(runtime.aclose())
