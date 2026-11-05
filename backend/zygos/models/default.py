"""The default model in effect: the saved choice, or the config primary (RFC-0013 §5).

The saved default stays the default until the user changes it. It is read on
every call (no per-session copy) and is never re-picked: a saved default that is
not installed or whose provider can't be reached is ignored -- the config
primary answers -- and reported with why, never an error.

Stability: Experimental.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from typing import Literal

from pydantic import BaseModel, ConfigDict

from zygos.models.choices import DefaultModel, ModelChoices
from zygos.providers.types import LLAMACPP_PROVIDER, ollama_name
from zygos.services.router import RouteChoice

# Providers that need an API key credential before they can answer.
CLOUD_PROVIDERS: frozenset[str] = frozenset({"anthropic", "openai"})

NOT_INSTALLED = "not installed"


class DefaultStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: Literal["saved", "config"]
    route: RouteChoice
    ignored: DefaultModel | None = None
    reason: str | None = None


def can_create(name: str, *, declared: Collection[str], api_key: str | None) -> bool:
    """Whether a provider not already routed can be created on demand.

    llama.cpp has no provider until Zygos starts llama-server (RFC-0014 phase 3);
    a cloud provider needs its API key."""
    if name == LLAMACPP_PROVIDER or name not in declared:
        return False
    return name not in CLOUD_PROVIDERS or bool(api_key)


def _is_installed(provider: str, model: str, names: frozenset[str]) -> bool:
    return model in names or (provider == "ollama" and ollama_name(model) in names)


def resolve_default(
    choices: ModelChoices,
    config_primary: RouteChoice,
    *,
    installed: Callable[[str], frozenset[str] | None],
    routable: Callable[[str], bool],
) -> DefaultStatus:
    saved = choices.default_model
    if saved is None:
        return DefaultStatus(source="config", route=config_primary)
    if not routable(saved.provider):
        reason = f"{saved.provider} isn't available"
    else:
        names = installed(saved.provider)
        if names is None or _is_installed(saved.provider, saved.model, names):
            return DefaultStatus(source="saved", route=RouteChoice(saved.provider, saved.model))
        reason = NOT_INSTALLED
    return DefaultStatus(source="config", route=config_primary, ignored=saved, reason=reason)
