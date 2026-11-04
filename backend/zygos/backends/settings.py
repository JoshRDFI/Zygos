"""Backends settings record types (RFC-0014 section 2).

Stability: Experimental.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OllamaBackend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str | None = None


class LlamaCppBackend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_path: str | None = None
    models_dir: str | None = None
    default_args: str = ""
    model_args: dict[str, str] = Field(default_factory=dict)


class VllmEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "vllm"
    base_url: str


class BackendsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ollama: OllamaBackend = Field(default_factory=OllamaBackend)
    llamacpp: LlamaCppBackend = Field(default_factory=LlamaCppBackend)
    vllm: list[VllmEndpoint] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_vllm(self) -> BackendsSettings:
        if len(self.vllm) > 1:
            raise ValueError("at most one vLLM server is supported")
        if self.vllm and self.vllm[0].name != "vllm":
            raise ValueError('the vLLM entry must be named "vllm"')
        return self


def effective_args(
    settings: LlamaCppBackend, model: str
) -> tuple[str, Literal["model", "default"]]:
    """The launch text for ``model``: its own if non-blank, else the default."""
    own = settings.model_args.get(model)
    if own is not None and own.strip():
        return own.strip(), "model"
    return settings.default_args, "default"
