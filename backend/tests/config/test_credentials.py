from pathlib import Path

import pytest

from zygos.config.loader import load_config
from zygos.errors import ConfigError


def _write(tmp_path: Path, body: str) -> Path:
    file = tmp_path / "config.yaml"
    file.write_text(body, encoding="utf-8")
    return file


def test_primary_route_missing_required_key_fails_fast(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    file = _write(
        tmp_path,
        "providers:\n"
        "  primary:\n"
        "    provider: openai\n"
        "    model: gpt-4o-mini\n"
        "  credentials:\n"
        "    openai:\n"
        "      enabled: true\n",
    )
    with pytest.raises(ConfigError, match="[Mm]issing api[_ ]?key for primary route"):
        load_config(file)


def test_primary_route_with_env_key_loads(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    file = _write(
        tmp_path,
        "providers:\n"
        "  primary:\n"
        "    provider: openai\n"
        "    model: gpt-4o-mini\n"
        "  credentials:\n"
        "    openai:\n"
        "      enabled: true\n",
    )
    config = load_config(file)
    assert config.providers.primary.provider == "openai"


def test_fallback_route_missing_key_warns_but_loads(tmp_path: Path, monkeypatch, caplog):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    file = _write(
        tmp_path,
        "providers:\n"
        "  primary:\n"
        "    provider: ollama\n"
        "    model: llama3.1:8b\n"
        "  fallbacks:\n"
        "    - provider: anthropic\n"
        "      model: claude-sonnet-4-6\n"
        "  credentials:\n"
        "    anthropic:\n"
        "      enabled: true\n",
    )
    with caplog.at_level("WARNING", logger="zygos.config"):
        config = load_config(file)
    assert len(config.providers.fallbacks) == 1
    assert any("anthropic" in record.message for record in caplog.records)


def test_keyless_local_first_defaults_load_without_any_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = load_config()
    assert config.providers.primary.provider == "ollama"
