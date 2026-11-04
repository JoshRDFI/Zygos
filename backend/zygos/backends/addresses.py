"""Where Zygos finds Ollama and vLLM: the one address resolution (RFC-0014 section 2).

The backends record wins, then ``providers.credentials.<name>.base_url``, then the
built-in default. Startup, the Backends page, doctor and the setup all use this.

Stability: Experimental.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from zygos.backends.settings import BackendsSettings
from zygos.config.schema import ZygosConfig
from zygos.providers.base import DEFAULT_BASE_URLS

AddressSource = Literal["backends", "config", "default"]
BACKEND_ADDRESSES: tuple[str, ...] = ("ollama", "vllm")


def record_address(settings: BackendsSettings | None, name: str) -> str | None:
    if settings is None:
        return None
    if name == "ollama":
        return settings.ollama.base_url or None
    if name == "vllm":
        return settings.vllm[0].base_url if settings.vllm else None
    return None


def resolve_address(
    config: ZygosConfig, name: str, settings: BackendsSettings | None = None
) -> tuple[str, AddressSource]:
    recorded = record_address(settings, name)
    if recorded:
        return recorded, "backends"
    credential = config.providers.credentials.get(name)
    if credential is not None and credential.base_url:
        return credential.base_url, "config"
    return DEFAULT_BASE_URLS.get(name, "http://localhost"), "default"


def routed(config: ZygosConfig) -> set[str]:
    """Providers a configured route (primary or fallback) uses."""
    p = config.providers
    return {r.provider for r in [p.primary, *p.fallbacks]}


def restart_required(
    settings: BackendsSettings, config: ZygosConfig, addresses_at_start: Mapping[str, str]
) -> bool:
    """The address Zygos would use now differs from the one in force since startup."""
    for name in BACKEND_ADDRESSES:
        start = addresses_at_start.get(name)
        if start is None:
            continue
        if resolve_address(config, name, settings)[0].rstrip("/") != start.rstrip("/"):
            return True
    return False
