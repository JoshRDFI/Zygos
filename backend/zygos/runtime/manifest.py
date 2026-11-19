"""Runtime manifest: a pure, non-secret, pull-only projection (RFC-0003 §5).

No network, no mutation. Carries a non-secret config summary by construction —
credentials never appear here. Stability: Experimental.
"""

from __future__ import annotations

import platform
import re
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from zygos.hardware.probe import HardwareSnapshot
from zygos.mcp.config import address, zygos_tool_name
from zygos.mcp.permission import trust_state
from zygos.runtime.capabilities import Capability, CapabilityBinding
from zygos.services.router import RouteChoice
from zygos.thinking.support import ThinkingSupport
from zygos.voice.contract import SttHealth, TtsHealth

if TYPE_CHECKING:
    from zygos.mcp.store import SqliteMcpStore
    from zygos.runtime.bootstrap import RuntimeAssembly
    from zygos.secrets.resolve import SecretsStatus

_ABS_PATH = re.compile(r"(?:(?<=\s)|^)(?:[A-Za-z]:\\|/)[^\s]*")


def _scrub_error(msg: str | None) -> str | None:
    if msg is None:
        return None
    return _ABS_PATH.sub("<path>", msg)[:200]


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
    tts: TtsHealth | None = None


class SecretsManifest(BaseModel):
    """Which secret store is in use. No handles, location or values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: str | None
    reason: str
    available: bool


class McpToolManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str           # the Zygos tool name
    server_tool: str    # the server's own name for it
    enabled: bool
    trust: Literal["trusted", "not_trusted", "changed"]


class McpServerManifest(BaseModel):
    """One MCP server as stored. No secret names or values, nothing from ``extra``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    transport: str
    address: str        # the URL, or a local server's command line
    enabled: bool
    status: str         # the last status recorded
    era: str | None
    tools: tuple[McpToolManifest, ...]


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
    thinking: ThinkingSupport | None = None   # primary route, from the checker cache
    hardware: HardwareSnapshot | None = None   # the last scan; the manifest never scans
    secrets: SecretsManifest | None = None
    mcp_servers: tuple[McpServerManifest, ...] = ()


def _package_version() -> str:
    try:
        return version("zygos")
    except PackageNotFoundError:  # pragma: no cover - always installed in dev
        return "unknown"


def primary_route(config) -> RouteChoice:
    """The configured primary route: the one ``Manifest.thinking`` reports on, and
    the one warm-up checks (RFC-0012 §5)."""
    return RouteChoice(provider=config.providers.primary.provider,
                       model=config.providers.primary.model)


def mcp_manifest(store: "SqliteMcpStore") -> tuple[McpServerManifest, ...]:
    """MCP servers and their last-seen tools with on/off and trust, read from the record."""
    specs = store.servers()
    if not specs:
        return ()
    off = store.off()
    trust = store.trust_entries()
    out = []
    for name in sorted(specs):
        spec, state = specs[name], store.state(name)
        tools = []
        for seen in state.tools:
            tool = zygos_tool_name(name, seen.name)
            tools.append(McpToolManifest(
                name=tool, server_tool=seen.name, enabled=f"tool:{tool}" not in off,
                trust=trust_state(tool, seen, trust),
            ))
        out.append(McpServerManifest(
            name=name, transport=spec.transport, address=address(spec),
            enabled=f"server:{name}" not in off, status=state.status, era=state.era,
            tools=tuple(tools),
        ))
    return tuple(out)


def runtime_manifest(
    runtime: "RuntimeAssembly", *, secrets_status: "SecretsStatus | None" = None,
    mcp_servers: tuple[McpServerManifest, ...] | None = None,
) -> Manifest:
    """``secrets_status`` / ``mcp_servers``: pass ones computed off the event loop (the
    keychain probe and the record read can block); by default they are read here."""
    config = runtime.config
    snapshot = runtime.capability_registry.snapshot()
    plugins = tuple(
        PluginInfo(kind=kind, name=name, module=module)
        for kind, entries in sorted(config.plugins.items())
        for name, module in sorted(entries.items())
    )
    voice = None
    if runtime.voice_service is not None:
        snap = runtime.voice_service.snapshot()
        stt = snap.stt.model_copy(update={"last_error": _scrub_error(snap.stt.last_error)}) if snap.stt else None
        tts = snap.tts.model_copy(update={"last_error": _scrub_error(snap.tts.last_error)}) if snap.tts else None
        voice = VoiceManifest(stt=stt, tts=tts)
    secrets = secrets_status if secrets_status is not None else runtime.secrets.status()
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
        thinking=runtime.thinking_support.cached(primary_route(config)),
        hardware=runtime.hardware.last(),
        secrets=SecretsManifest(
            backend=secrets.backend, reason=secrets.reason, available=secrets.available
        ),
        mcp_servers=mcp_servers if mcp_servers is not None else mcp_manifest(runtime.mcp.store),
    )
