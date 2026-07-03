import pytest
from pydantic import ValidationError

from zygos.config.schema import ZygosConfig


def test_defaults_are_local_first_and_constitution_compliant():
    config = ZygosConfig()
    assert config.providers.primary.provider == "ollama"
    assert config.providers.primary.model == "llama3.1:8b"
    # CONSTITUTION.md: self-improvement is proposal-based, never autonomous
    assert config.learning.approval_mode == "manual"
    assert config.learning.auto_apply_low_risk is False
    assert config.plugins == {}


def test_duplicate_provider_routes_rejected():
    with pytest.raises(ValidationError, match="[Dd]uplicate provider route"):
        ZygosConfig.model_validate(
            {
                "providers": {
                    "primary": {"provider": "openai", "model": "gpt-4o-mini"},
                    "fallbacks": [{"provider": "openai", "model": "gpt-4o-mini"}],
                }
            }
        )


def test_unknown_top_level_keys_rejected():
    with pytest.raises(ValidationError):
        ZygosConfig.model_validate({"providres": {}})  # typo must not pass silently
