"""Config loading: YAML -> env resolution -> validation (RFC-0001 §3, §8). Stability: Experimental."""

import logging
import os
from pathlib import Path

import yaml
from pydantic import ValidationError

from zygos.config.env import resolve_env_placeholders
from zygos.config.schema import ZygosConfig
from zygos.errors import ConfigError

_LOGGER = logging.getLogger("zygos.config")

# Providers that require an API key unless the credential says otherwise.
_KEYED_PROVIDERS = {"openai", "anthropic"}


def load_config(path: Path | None = None) -> ZygosConfig:
    if path is None:
        config = ZygosConfig()
        _validate_credentials(config)
        return config

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    resolved = resolve_env_placeholders(raw)
    try:
        config = ZygosConfig.model_validate(resolved)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc']) or 'root'}: {issue['msg']}"
            for issue in error.errors()
        )
        raise ConfigError(f"Configuration validation failed: {details}") from error
    _validate_credentials(config)
    return config


def _validate_credentials(config: ZygosConfig) -> None:
    """Fail fast on the primary route; warn on fallbacks (RFC-0001 §8)."""
    routes = [(config.providers.primary, True)] + [
        (route, False) for route in config.providers.fallbacks
    ]
    for route, is_primary in routes:
        credential = config.providers.credentials.get(route.provider)
        if credential is None or not credential.enabled:
            continue
        require_key = (
            credential.require_api_key
            if credential.require_api_key is not None
            else route.provider in _KEYED_PROVIDERS
        )
        env_key = f"{route.provider.upper()}_API_KEY"
        if require_key and not credential.api_key and not os.environ.get(env_key):
            if is_primary:
                raise ConfigError(
                    f"Missing api_key for primary route {route.provider}:{route.model}. "
                    f"Set providers.credentials.{route.provider}.api_key, export {env_key}, "
                    f"or set providers.credentials.{route.provider}.enabled: false."
                )
            _LOGGER.warning(
                "Missing api_key for fallback route %s:%s; this route will be "
                "skipped at runtime. Set providers.credentials.%s.api_key or %s.",
                route.provider,
                route.model,
                route.provider,
                env_key,
            )
