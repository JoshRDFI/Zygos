"""Config loading: YAML -> env resolution -> validation (RFC-0001 §3)."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from zygos.config.env import resolve_env_placeholders
from zygos.config.schema import ZygosConfig
from zygos.errors import ConfigError


def load_config(path: Path | None = None) -> ZygosConfig:
    if path is None:
        return ZygosConfig()

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    resolved = resolve_env_placeholders(raw)
    try:
        return ZygosConfig.model_validate(resolved)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc']) or 'root'}: {issue['msg']}"
            for issue in error.errors()
        )
        raise ConfigError(f"Configuration validation failed: {details}") from error
