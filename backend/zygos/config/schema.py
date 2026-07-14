"""Declarative configuration schema (RFC-0001 §3, §8). Stability: Experimental."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from zygos.runtime.capabilities import Capability
from zygos.tools.permissions import Rule


def _default_tools_enabled() -> list[str]:
    return ["read_file", "write_file", "http_fetch", "run_command"]


def _default_tool_rules() -> list[Rule]:
    # Frictionless web: the tool AUTHOR declares http_fetch = "ask"; the shipped default
    # config loosens it to "allow" via the escape hatch. Fetching a site the user asked for
    # is not a data-privacy concern on this project (privacy = the user's own data stays
    # local, not a walled system). Remove this rule to prompt before every outbound request.
    return [Rule(pattern="http_fetch", decision="allow")]


def _default_plugins() -> dict[str, dict[str, str]]:
    return {
        "providers": {
            "ollama": "zygos.providers.ollama:OllamaProvider",
            "openai": "zygos.providers.openai:OpenAIProvider",
            "anthropic": "zygos.providers.anthropic:AnthropicProvider",
            "vllm": "zygos.providers.vllm:VllmProvider",
            "fake": "zygos.providers.fake:FakeProvider",
        },
        "tools": {
            "read_file": "zygos.tools.starter.fs:ReadFileTool",
            "write_file": "zygos.tools.starter.fs:WriteFileTool",
            "http_fetch": "zygos.tools.starter.http:HttpFetchTool",
            "run_command": "zygos.tools.starter.shell:RunCommandTool",
        },
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
    task_routes: dict[str, ProviderRoute] = Field(default_factory=dict)

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


class ReasoningConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    profile: Literal["shallow", "balanced", "deep"] = "balanced"


class RetrievalWeightsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relevance: float = Field(default=0.5, ge=0)
    recency: float = Field(default=0.2, ge=0)
    importance: float = Field(default=0.3, ge=0)


class EmbeddingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Selects the embedding backend, DECOUPLED from the chat route (RFC-0006 §6).
    backend: Literal["local", "ollama", "openai", "vllm"] = "local"
    # "" -> per-backend default where one exists (local->bge-small, ollama->nomic-embed-text);
    # openai/vllm have no universal default and require an explicit model (enforced at bootstrap).
    model: str = ""


class MemoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    db_path: str = ".zygos/memory.db"
    token_budget: int = Field(default=2000, ge=1)
    consolidation_batch_size: int = Field(default=20, ge=1)
    recency_half_life_s: float = Field(default=86400.0, gt=0)
    retrieval_weights: RetrievalWeightsConfig = Field(default_factory=RetrievalWeightsConfig)
    retrieval_mode: Literal["fts5", "vector", "hybrid"] = "fts5"
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    embed_batch_size: int = Field(default=32, ge=1)


class SttConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: Literal["fake", "whisper_cpp"] = "fake"


class TtsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: Literal["fake"] = "fake"  # "kokoro" / "piper" land in Cycle 2.5


class VoiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    stt: SttConfig = Field(default_factory=SttConfig)
    tts: TtsConfig = Field(default_factory=TtsConfig)
    # how long the runtime waits for a client endpoint signal before giving up
    prompt_endpoint_timeout_s: float = 30.0


class ToolsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Tools ship ON by default (a mid-chat "go look up this site" must just work).
    enabled: list[str] = Field(default_factory=_default_tools_enabled)
    workspace_root: str = ".zygos/workspace"     # sandbox root for fs/shell tools
    settings: dict[str, dict] = Field(default_factory=dict)   # name -> per-tool kwargs
    permission_rules: list[Rule] = Field(default_factory=_default_tool_rules)  # loosen/tighten
    max_iterations: int = Field(default=8, ge=1)
    tool_choice: Literal["auto", "none", "required"] = "auto"


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"          # loopback default (RFC-0007 §11)
    port: int = 8000
    request_timeout_s: float = 60.0
    # permission-prompt timeout; reserved here, consumed by the Cycle 3 resolver
    prompt_timeout_s: float = 120.0
    # reserved for the voice-build audio handshake (RFC-0005); unused in M8
    audio_codec: str = "pcm"
    audio_sample_rate: int = 16000


class ZygosConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    reasoning: ReasoningConfig = Field(default_factory=ReasoningConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    # plugin kind -> plugin name -> "module.path:ClassName" (RFC-0001 §3)
    plugins: dict[str, dict[str, str]] = Field(default_factory=_default_plugins)
    # Capabilities a deployment requires; `zygos doctor` fails if any is unbound
    # (RFC-0003 §6). Default empty: the default doctor gate is primary-route
    # credentials, not capability coverage.
    required_capabilities: list[Capability] = Field(default_factory=list)
