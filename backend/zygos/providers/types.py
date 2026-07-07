"""Typed, immutable provider messages (RFC-0001 §7).

Stability: Experimental.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Message(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str


class GenerationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # May be empty on construction; the router fills it from the chosen route.
    model: str = ""
    messages: tuple[Message, ...]
    # None = no caller-specified cap; the provider applies its class policy (ADR-0006:
    # local uncapped, cloud a generous default). An explicit int is always honored.
    max_tokens: int | None = None
    temperature: float = 0.7


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


class GenerationChunk(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    done: bool = False
