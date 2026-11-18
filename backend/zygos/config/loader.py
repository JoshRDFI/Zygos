"""Config loading: YAML -> env resolution -> validation (RFC-0001 §3, §8). Stability: Experimental."""

import logging
import os
from pathlib import Path

import yaml
from pydantic import ValidationError

from zygos.config.env import resolve_env_placeholders
from zygos.config.schema import ZygosConfig
from zygos.errors import ConfigError
from zygos.home import resolve_path

_LOGGER = logging.getLogger("zygos.config")

# Providers that require an API key unless the credential says otherwise.
_KEYED_PROVIDERS = {"openai", "anthropic"}


def load_config(path: Path | None = None) -> ZygosConfig:
    if path is None:
        config = ZygosConfig()
        _validate_credentials(config)
        return _resolve_paths(config)

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
    return _resolve_paths(config)


def _resolve_paths(config: ZygosConfig) -> ZygosConfig:
    """Make data-path settings absolute against the Zygos home root.

    Creates nothing. ``models.ollama_models_dir`` is deliberately left alone.
    """
    voice = config.voice
    stt, tts = voice.stt, voice.tts
    stt_update = {}
    if stt.download_root:
        stt_update["download_root"] = resolve_path(stt.download_root)
    tts_update = {}
    if tts.download_root:
        tts_update["download_root"] = resolve_path(tts.download_root)
    if tts.worker_python and ("/" in tts.worker_python or "\\" in tts.worker_python):
        tts_update["worker_python"] = resolve_path(tts.worker_python)
    return config.model_copy(
        update={
            "memory": config.memory.model_copy(
                update={"db_path": resolve_path(config.memory.db_path)}
            ),
            "personalization": config.personalization.model_copy(
                update={"db_path": resolve_path(config.personalization.db_path)}
            ),
            "tools": config.tools.model_copy(
                update={"workspace_root": resolve_path(config.tools.workspace_root)}
            ),
            "models": config.models.model_copy(
                update={"profiles_dir": resolve_path(config.models.profiles_dir)}
            ),
            "voice": voice.model_copy(
                update={
                    "stt": stt.model_copy(update=stt_update),
                    "tts": tts.model_copy(update=tts_update),
                }
            ),
        }
    )


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


def primary_route_credentialed(config: ZygosConfig) -> bool:
    """True if the primary route is usable: keyless, or a required key is present.

    Stricter than load-time validation, which skips routes with no credential
    block; a keyed primary with no credentials at all is NOT credentialed here.
    """
    route = config.providers.primary
    credential = config.providers.credentials.get(route.provider)
    if credential is not None and not credential.enabled:
        return False
    require_key = (
        credential.require_api_key
        if credential is not None and credential.require_api_key is not None
        else route.provider in _KEYED_PROVIDERS
    )
    if not require_key:
        return True
    env_key = f"{route.provider.upper()}_API_KEY"
    return bool((credential and credential.api_key) or os.environ.get(env_key))
