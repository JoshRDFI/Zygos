"""Capability model, contract map, registry (RFC-0003 §1, §3-4).

The registry holds no event bus and no subscription (RFC-0002 invariant):
resolution reads health synchronously via an injected health source.

Stability: Experimental.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from zygos.providers.base import Provider


class Capability(StrEnum):
    LOCAL_INFERENCE = "local_inference"
    VISION = "vision"
    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_TO_SPEECH = "text_to_speech"
    WEB_SEARCH = "web_search"
    IMAGE_GENERATION = "image_generation"
    SCHEDULING = "scheduling"
    FILESYSTEM_ACCESS = "filesystem_access"


# Each capability binds to the contract a satisfier must implement. Only
# capabilities whose contract type exists today appear here; the rest are
# named-but-uncontracted until their RFCs land (RFC-0003 §1). register()
# rejects any capability with no entry here.
CAPABILITY_CONTRACTS: Mapping[Capability, type] = {
    Capability.LOCAL_INFERENCE: Provider,
}


@dataclass(frozen=True)
class Binding:
    capability: Capability
    provider: str
    priority: int  # lower = preferred (config-assigned)


@dataclass(frozen=True)
class CapabilityBinding:
    provider: str
    priority: int
    healthy: bool  # last-known, from the pulled source


@dataclass(frozen=True)
class CapabilitySnapshot:
    bindings: Mapping[Capability, tuple[CapabilityBinding, ...]]


def _always_healthy(_provider_name: str) -> bool:
    return True


class CapabilityRegistry:
    """Pull-based, health-ranked capability lookup (RFC-0003 §3-4)."""

    def __init__(self, health_of: Callable[[str], bool] = _always_healthy) -> None:
        self._health_of = health_of
        self._bindings: dict[Capability, list[Binding]] = {}

    def register(self, capability: Capability, provider: object, *, priority: int) -> None:
        contract = CAPABILITY_CONTRACTS.get(capability)
        if contract is None:
            raise ValueError(
                f"Capability {capability.value!r} has no contract; it cannot be "
                f"registered until its RFC defines one."
            )
        if not isinstance(provider, contract):
            raise ValueError(
                f"Provider does not satisfy the {contract.__name__} contract required "
                f"by capability {capability.value!r}."
            )
        name = provider.name  # the contract guarantees `.name`
        self._bindings.setdefault(capability, []).append(
            Binding(capability=capability, provider=name, priority=priority)
        )

    def resolve(self, capability: Capability) -> tuple[Binding, ...]:
        ranked = sorted(self._bindings.get(capability, ()), key=lambda b: b.priority)
        return tuple(b for b in ranked if self._health_of(b.provider))

    def snapshot(self) -> CapabilitySnapshot:
        return CapabilitySnapshot(
            bindings={
                capability: tuple(
                    CapabilityBinding(
                        provider=b.provider,
                        priority=b.priority,
                        healthy=self._health_of(b.provider),
                    )
                    for b in sorted(bindings, key=lambda b: b.priority)
                )
                for capability, bindings in self._bindings.items()
            }
        )
