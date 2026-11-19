"""Declarative configuration schema (RFC-0001 §3, §8). Stability: Experimental."""

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from zygos.config.hostnames import normalize_host_entry
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

    # None = no client-side throttle (the default). Set a cap to stay under a cloud
    # provider's quota; local inference has none, and a reasoning turn's burst of
    # calls would otherwise exhaust it and leave no eligible route.
    max_requests_per_minute: int | None = Field(default=None, ge=1)


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
    # Native model thinking (e.g. qwen3/gemma4 via Ollama). Off by default: it costs
    # seconds of time-to-first-token, which voice turns can't afford.
    think: bool | None = False

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

    engine: Literal["fake", "faster_whisper"] = "fake"
    model: str = "base.en"
    compute_type: str = "int8"
    device: str = "cpu"
    # None -> resolved to a Zygos-owned model cache dir at build time
    download_root: str | None = None
    # max wait for the worker to report health_ok (model load) at startup
    readiness_timeout_s: float = 60.0


class TtsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: Literal["fake", "kokoro"] = "fake"
    voice: str = "af_heart"          # Kokoro flagship graded voice, lang_code 'a'
    lang: str = "en-us"              # kokoro-onnx tokenizer language (espeak)
    device: Literal["cpu", "cuda"] = "cpu"   # cuda → GPU sidecar venv (RFC-0005 §2a)
    # sidecar interpreter override; None → .zygos/venvs/voice-gpu when device=cuda
    worker_python: str | None = None
    # None -> resolved to a Zygos-owned model cache dir at build time
    download_root: str | None = None
    # max wait for the worker to report health_ok (model load) at startup
    readiness_timeout_s: float = 60.0
    # suggested client playback gain while the assistant is "ducked" (barge-in stage 1)
    duck_gain: float = 0.2


class VoiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    stt: SttConfig = Field(default_factory=SttConfig)
    tts: TtsConfig = Field(default_factory=TtsConfig)
    # how long the runtime waits for a client endpoint signal before giving up
    prompt_endpoint_timeout_s: float = 30.0
    # max time the assistant stays ducked with no speech/silence resolution
    # before auto-restoring full volume (barge-in liveness backstop)
    duck_timeout_s: float = 2.0


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
    # permission-prompt timeout; reserved here, consumed by the WebSocket permission resolver
    prompt_timeout_s: float = 120.0
    # extra browser origins allowed to write/chat (loopback is always allowed)
    allowed_origins: list[str] = []
    # extra hostnames a request may name in its Host header, port ignored (loopback and
    # the hosts of allowed_origins are always allowed); e.g. a LAN IP or a proxy domain
    allowed_hosts: list[str] = []

    @field_validator("allowed_hosts")
    @classmethod
    def _parseable_hosts(cls, v: list[str]) -> list[str]:
        for entry in v:
            if normalize_host_entry(entry) is None:
                raise ValueError(
                    f"server.allowed_hosts entry {entry!r} is not a host name or address; "
                    "use e.g. 192.168.1.20, zygos.lan, zygos.lan:8443 or [fe80::1]"
                )
        return v
    # reserved for the voice-build audio handshake (RFC-0005); unused in M8
    audio_codec: str = "pcm"
    audio_sample_rate: int = 16000


class PersonalizationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    db_path: str = ".zygos/preferences.db"
    # IANA zone name for the time the model is told each turn; None = the system zone.
    time_zone: str | None = None

    @field_validator("time_zone")
    @classmethod
    def _known_zone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
            raise ValueError(f"unknown time zone {v!r}; use an IANA name such as Europe/London") from exc
        return v


class SecretsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # auto: keychain if usable, else encrypted file; sticky once the first secret
    # is saved (RFC-0015). An explicit value always wins over the recorded choice.
    backend: Literal["auto", "keyring", "encrypted_file"] = "auto"


class ModelsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profiles_dir: str = ".zygos/models/profiles"
    # Overrides the hardware probe's search for the Ollama models directory.
    ollama_models_dir: str | None = None


class ZygosConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    reasoning: ReasoningConfig = Field(default_factory=ReasoningConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    personalization: PersonalizationConfig = Field(default_factory=PersonalizationConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)
    # plugin kind -> plugin name -> "module.path:ClassName" (RFC-0001 §3)
    plugins: dict[str, dict[str, str]] = Field(default_factory=_default_plugins)
    # Capabilities a deployment requires; `zygos doctor` fails if any is unbound
    # (RFC-0003 §6). Default empty: the default doctor gate is primary-route
    # credentials, not capability coverage.
    required_capabilities: list[Capability] = Field(default_factory=list)
