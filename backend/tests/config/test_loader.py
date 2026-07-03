from pathlib import Path

import pytest

from zygos.config.loader import load_config
from zygos.errors import ConfigError


def test_no_path_returns_defaults():
    config = load_config()
    assert config.providers.primary.provider == "ollama"
    assert config.learning.approval_mode == "manual"


def test_yaml_file_overrides_defaults(tmp_path: Path):
    file = tmp_path / "config.yaml"
    file.write_text(
        "providers:\n"
        "  primary:\n"
        "    provider: vllm\n"
        "    model: qwen2.5-7b\n",
        encoding="utf-8",
    )
    config = load_config(file)
    assert config.providers.primary.provider == "vllm"
    assert config.providers.primary.model == "qwen2.5-7b"
    # untouched sections keep defaults
    assert config.learning.auto_apply_low_risk is False


def test_env_placeholders_resolved(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ZYGOS_TEST_KEY", "sekrit")
    file = tmp_path / "config.yaml"
    file.write_text(
        "providers:\n"
        "  credentials:\n"
        "    openai:\n"
        "      api_key: ${ZYGOS_TEST_KEY}\n",
        encoding="utf-8",
    )
    config = load_config(file)
    assert config.providers.credentials["openai"].api_key == "sekrit"


def test_invalid_config_raises_config_error(tmp_path: Path):
    file = tmp_path / "config.yaml"
    file.write_text("providers:\n  primary:\n    provider: 42\n    model: []\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(file)
