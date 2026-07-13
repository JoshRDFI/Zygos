"""Typed, immutable provider messages (RFC-0001 §7).

Stability: Experimental.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


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


class GenerationChunk(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    done: bool = False


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
