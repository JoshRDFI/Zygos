import pytest
from pydantic import ValidationError

from zygos.config.schema import (
    ZygosConfig,
    RetryConfig,
    CircuitBreakerConfig,
    RateLimitConfig,
    ReasoningConfig,
)


def test_defaults_are_local_first_and_constitution_compliant():
    config = ZygosConfig()
    assert config.providers.primary.provider == "ollama"
    assert config.providers.primary.model == "qwen3:8b"
    # CONSTITUTION.md: self-improvement is proposal-based, never autonomous
    assert config.learning.approval_mode == "manual"
    assert config.learning.auto_apply_low_risk is False
    # built-in providers are config-declared plugins (RFC-0001 §3)
    assert config.plugins["providers"]["ollama"] == "zygos.providers.ollama:OllamaProvider"
    assert config.plugins["providers"]["fake"] == "zygos.providers.fake:FakeProvider"


def test_routing_sections_have_safe_defaults():
    config = ZygosConfig()
    assert config.providers.retry.max_attempts == 3
    assert config.providers.circuit_breaker.failure_threshold == 5
    assert config.providers.rate_limit.max_requests_per_minute == 60


def test_credential_accepts_base_url():
    config = ZygosConfig.model_validate(
        {"providers": {"credentials": {"vllm": {"base_url": "http://localhost:8000/v1"}}}}
    )
    assert config.providers.credentials["vllm"].base_url == "http://localhost:8000/v1"


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


def test_retry_config_max_attempts_below_minimum_rejected():
    with pytest.raises(ValidationError):
        RetryConfig(max_attempts=0)


def test_retry_config_max_attempts_above_maximum_rejected():
    with pytest.raises(ValidationError):
        RetryConfig(max_attempts=11)


def test_retry_config_backoff_ms_negative_rejected():
    with pytest.raises(ValidationError):
        RetryConfig(backoff_ms=-1)


def test_retry_config_backoff_multiplier_below_minimum_rejected():
    with pytest.raises(ValidationError):
        RetryConfig(backoff_multiplier=0.9)


def test_circuit_breaker_config_failure_threshold_below_minimum_rejected():
    with pytest.raises(ValidationError):
        CircuitBreakerConfig(failure_threshold=0)


def test_circuit_breaker_config_cooldown_s_negative_rejected():
    with pytest.raises(ValidationError):
        CircuitBreakerConfig(cooldown_s=-1.0)


def test_rate_limit_config_max_requests_per_minute_below_minimum_rejected():
    with pytest.raises(ValidationError):
        RateLimitConfig(max_requests_per_minute=0)


def test_reasoning_defaults_off_balanced():
    cfg = ZygosConfig()
    assert cfg.reasoning.enabled is False
    assert cfg.reasoning.profile == "balanced"


def test_reasoning_rejects_unknown_profile():
    with pytest.raises(Exception):
        ReasoningConfig(profile="turbo")


def test_task_routes_default_empty_and_typed():
    cfg = ZygosConfig()
    assert cfg.providers.task_routes == {}
    cfg2 = ZygosConfig.model_validate(
        {"providers": {"task_routes": {"complex_reasoning": {"provider": "ollama", "model": "big"}}}}
    )
    assert cfg2.providers.task_routes["complex_reasoning"].model == "big"


def test_required_capabilities_defaults_empty():
    assert ZygosConfig().required_capabilities == []


def test_required_capabilities_coerces_valid_capability():
    from zygos.runtime.capabilities import Capability

    config = ZygosConfig(required_capabilities=["local_inference"])
    assert config.required_capabilities == [Capability.LOCAL_INFERENCE]


def test_required_capabilities_rejects_unknown():
    with pytest.raises(ValidationError):
        ZygosConfig(required_capabilities=["teleportation"])


def test_server_config_defaults():
    from zygos.config.schema import ServerConfig

    cfg = ServerConfig()
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8000
    assert cfg.request_timeout_s == 60.0
    assert cfg.prompt_timeout_s == 120.0
    assert cfg.audio_codec == "pcm"
    assert cfg.audio_sample_rate == 16000


def test_server_config_forbids_unknown_key():
    from zygos.config.schema import ServerConfig

    with pytest.raises(ValidationError):
        ServerConfig(nope=1)


def test_zygos_config_has_server_section_by_default():
    from zygos.config.schema import ServerConfig

    assert ZygosConfig().server == ServerConfig()
