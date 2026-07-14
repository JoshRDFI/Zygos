"""Runtime manifest: a pure, non-secret, pull-only projection (RFC-0003 §5).

No network, no mutation. Carries a non-secret config summary by construction —
credentials never appear here. Stability: Experimental.
"""

from __future__ import annotations

import platform
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from zygos.runtime.capabilities import Capability, CapabilityBinding
from zygos.voice.contract import SttHealth

if TYPE_CHECKING:
    from zygos.runtime.bootstrap import RuntimeAssembly


class PluginInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    name: str
    module: str


class RouteSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model: str


class VoiceManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stt: SttHealth | None = None


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lifecycle_stage: str
    capabilities: dict[Capability, tuple[CapabilityBinding, ...]]
    plugins: tuple[PluginInfo, ...]
    primary_route: RouteSummary
    fallback_routes: tuple[RouteSummary, ...]
    reasoning_enabled: bool
    versions: dict[str, str]
    voice: VoiceManifest | None = None


def _package_version() -> str:
    try:
        return version("zygos")
    except PackageNotFoundError:  # pragma: no cover - always installed in dev
        return "unknown"


def runtime_manifest(runtime: "RuntimeAssembly") -> Manifest:
    config = runtime.config
    snapshot = runtime.capability_registry.snapshot()
    plugins = tuple(
        PluginInfo(kind=kind, name=name, module=module)
        for kind, entries in sorted(config.plugins.items())
        for name, module in sorted(entries.items())
    )
    voice = None
    if runtime.voice_service is not None:
        voice = VoiceManifest(stt=runtime.voice_service.snapshot().stt)
    return Manifest(
        lifecycle_stage=runtime.lifecycle_stage,
        capabilities=dict(snapshot.bindings),
        plugins=plugins,
        primary_route=RouteSummary(
            provider=config.providers.primary.provider,
            model=config.providers.primary.model,
        ),
        fallback_routes=tuple(
            RouteSummary(provider=route.provider, model=route.model)
            for route in config.providers.fallbacks
        ),
        reasoning_enabled=config.reasoning.enabled,
        versions={"zygos": _package_version(), "python": platform.python_version()},
        voice=voice,
    )
