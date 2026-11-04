"""Backends settings record types (RFC-0014 section 2).

Stability: Experimental.
"""

from __future__ import annotations

import os
import shutil
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


def resolve_path(text: str | None, *, command: bool = False) -> str | None:
    """``~`` expanded and made absolute. With ``command``, a bare name (no ``/``) is
    looked up on PATH; a name not found is kept as typed so its check says so."""
    if text is None or not text.strip():
        return None
    text = text.strip()
    if command and "/" not in text:
        found = shutil.which(text)
        return os.path.abspath(found) if found else text
    return os.path.abspath(os.path.expanduser(text))


def with_resolved_paths(settings: BackendsSettings) -> BackendsSettings:
    lc = settings.llamacpp
    return settings.model_copy(update={"llamacpp": lc.model_copy(update={
        "server_path": resolve_path(lc.server_path, command=True),
        "models_dir": resolve_path(lc.models_dir),
    })})


def address_problem(settings: BackendsSettings) -> tuple[str, str] | None:
    """``(field, message)`` for the first address that isn't http(s), else None."""
    urls = [("ollama.base_url", settings.ollama.base_url)]
    urls += [("vllm.base_url", v.base_url) for v in settings.vllm]
    for field, url in urls:
        if url is not None and not url.startswith(("http://", "https://")):
            return field, f"{field} must be an http:// or https:// address"
    return None
