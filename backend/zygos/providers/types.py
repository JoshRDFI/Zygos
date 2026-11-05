"""Typed, immutable provider messages (RFC-0001 §7).

Stability: Experimental.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

LLAMACPP_PROVIDER = "llamacpp"

# Every generation provider declares Capability.LOCAL_INFERENCE (it is the
# "can generate" contract), so it cannot tell local from cloud. These are the
# built-in providers that run on this machine; anything else is labelled cloud,
# the label that never understates where data goes.
LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama", LLAMACPP_PROVIDER, "vllm", "fake"})


def ollama_name(model: str) -> str:
    """Ollama's own name for a model: an untagged name means ``:latest``."""
    return model if ":" in model else f"{model}:latest"


class ToolSchema(BaseModel):
    """A tool as the model sees it (RFC-0008 §1). parameters is a JSON Schema."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str
    parameters: dict[str, Any]


class ToolInvocation(BaseModel):
    """A tool call as the model requests it (RFC-0008 §1). Provider-layer; distinct
    from tools.ToolCall (the agent/ layer maps one to the other)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    arguments: dict[str, Any]


class Message(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ToolInvocation, ...] = ()   # on an assistant turn
    tool_call_id: str | None = None                # on a "tool" turn


class GenerationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # May be empty on construction; the router fills it from the chosen route.
    model: str = ""
    messages: tuple[Message, ...]
    # None = no caller-specified cap; the provider applies its class policy (ADR-0006:
    # local uncapped, cloud a generous default). An explicit int is always honored.
    max_tokens: int | None = None
    temperature: float = 0.7
    tools: tuple[ToolSchema, ...] = ()
    tool_choice: Literal["auto", "none", "required"] = "auto"
    # None = use the provider's configured default (ProviderSettings.think).
    think: bool | None = None


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: int = 0
    output_tokens: int = 0


class GenerationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    model: str
    provider: str
    usage: Usage = Usage()
    tool_calls: tuple[ToolInvocation, ...] = ()
    finish_reason: Literal["stop", "tool_calls", "length"] = "stop"
    thinking: str | None = None   # the model's native thinking text, when it produced any


class GenerationChunk(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    done: bool = False
    thinking: str | None = None


class EmbedRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Model identity for provider-backed embedders (parallels GenerationRequest.model).
    # embed_backlog fills it from the configured embedding_model.
    model: str = ""
    texts: tuple[str, ...]


class EmbedResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    vectors: tuple[tuple[float, ...], ...]  # aligned 1:1 with request.texts
    model: str
    dim: int
    usage: Usage = Usage()


PROBE_TIMEOUT_S = 5.0
"""Upper bound on a thinking-support probe (RFC-0012 §5); far below the generation timeout."""

LOAD_TIMEOUT_S = 300.0
"""Upper bound on loading a local model (RFC-0013 §8); a cold disk can take minutes."""

OLLAMA_KEEP_ALIVE = "30m"
"""keep_alive on Zygos's own load call only; Ollama's default applies otherwise."""


class ThinkingSupport(BaseModel):
    """Whether a model can think natively; ``reason`` says why not (RFC-0012 §5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    supported: bool
    reason: str | None = None


class OllamaModel(BaseModel):
    """One installed model, flattened from an ``/api/tags`` entry (RFC-0013 §2)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    size: int
    digest: str
    family: str | None = None
    parameter_size: str | None = None
    quantization_level: str | None = None
    context_length: int | None = None
    capabilities: tuple[str, ...] = ()

    @field_validator("capabilities", mode="before")
    @classmethod
    def _null_is_empty(cls, v: Any) -> Any:
        return () if v is None else v


class OllamaRunning(BaseModel):
    """One loaded model from ``/api/ps``."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    digest: str
    size: int
    size_vram: int
    context_length: int | None = None


class OllamaShow(BaseModel):
    """The parts of ``/api/show`` the picker reads."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    capabilities: tuple[str, ...] = ()
    model_info: dict[str, Any] = {}
    parameters: str | None = None
    details: dict[str, Any] = {}

    @field_validator("capabilities", "model_info", "parameters", "details", mode="before")
    @classmethod
    def _null_is_default(cls, v: Any, info: Any) -> Any:
        """An explicit JSON ``null`` means "not reported", same as absent."""
        if v is not None:
            return v
        return cls.model_fields[info.field_name].get_default(call_default_factory=True)
