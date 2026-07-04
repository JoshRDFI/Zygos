"""Declarative configuration schema (RFC-0001 §3, §8). Stability: Experimental."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _default_plugins() -> dict[str, dict[str, str]]:
    return {
        "providers": {
            "ollama": "zygos.providers.ollama:OllamaProvider",
            "openai": "zygos.providers.openai:OpenAIProvider",
            "anthropic": "zygos.providers.anthropic:AnthropicProvider",
            "vllm": "zygos.providers.vllm:VllmProvider",
            "fake": "zygos.providers.fake:FakeProvider",
        }
    }


class ProviderRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    weight: float = 1.0


class ProviderCredential(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    api_key: str | None = None
    require_api_key: bool | None = None
    base_url: str | None = None


class RetryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=3, ge=1, le=10)
    backoff_ms: int = Field(default=250, ge=0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0)


class CircuitBreakerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    failure_threshold: int = Field(default=5, ge=1)
    cooldown_s: float = Field(default=30.0, ge=0)


class RateLimitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_requests_per_minute: int = Field(default=60, ge=1)


class ProvidersConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: ProviderRoute = Field(
        default_factory=lambda: ProviderRoute(provider="ollama", model="qwen3:8b")
    )
    fallbacks: list[ProviderRoute] = Field(default_factory=list)
    credentials: dict[str, ProviderCredential] = Field(default_factory=dict)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)

    @model_validator(mode="after")
    def reject_duplicate_routes(self) -> "ProvidersConfig":
        seen: set[tuple[str, str]] = set()
        for route in [self.primary, *self.fallbacks]:
            key = (route.provider, route.model)
            if key in seen:
                raise ValueError(f"Duplicate provider route detected: {route.provider}:{route.model}")
            seen.add(key)
        return self


class LearningConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    # CONSTITUTION.md: self-improvement is proposal-based, never autonomous.
    approval_mode: Literal["manual", "auto", "optional_human"] = "manual"
    auto_apply_low_risk: bool = False


class ZygosConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    # plugin kind -> plugin name -> "module.path:ClassName" (RFC-0001 §3)
    plugins: dict[str, dict[str, str]] = Field(default_factory=_default_plugins)
