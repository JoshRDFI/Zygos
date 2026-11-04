"""Build and refresh model profiles from Ollama data (RFC-0013 §2).

Pure functions: no I/O. Anything Ollama does not report is simply not
recorded; nothing is guessed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from zygos.models.fit import KV_BYTES_PER_ELEMENT
from zygos.models.profile import ModelProfile, Source, record
from zygos.providers.types import OllamaModel, OllamaRunning, OllamaShow

SPECIALTY_HINTS: tuple[tuple[str, str], ...] = (
    ("coder", "coder"),
    ("instruct", "instruct"),
    ("-vl", "vision"),
    ("vision", "vision"),
    ("ocr", "ocr"),
)

_REFRESHABLE: frozenset[Source] = frozenset({"ollama", "modelfile", "name"})


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def kv_bytes_per_token(model_info: Mapping[str, Any]) -> int | None:
    arch = model_info.get("general.architecture")
    if not isinstance(arch, str):
        return None
    blocks = _int(model_info.get(f"{arch}.block_count"))
    kv_heads = _int(model_info.get(f"{arch}.attention.head_count_kv"))
    head_dim = _int(model_info.get(f"{arch}.attention.key_length"))
    if head_dim is None:
        embedding = _int(model_info.get(f"{arch}.embedding_length"))
        heads = _int(model_info.get(f"{arch}.attention.head_count"))
        if embedding is None or not heads:
            return None
        head_dim = embedding // heads
    if blocks is None or kv_heads is None:
        return None
    return 2 * blocks * kv_heads * head_dim * KV_BYTES_PER_ELEMENT


def modelfile_num_ctx(parameters: str | None) -> int | None:
    if not parameters:
        return None
    m = re.search(r"^\s*num_ctx\s+(\d+)\s*$", parameters, re.MULTILINE)
    return int(m.group(1)) if m else None


def _specialty(name: str) -> list[str]:
    lowered = name.lower()
    found: list[str] = []
    for needle, label in SPECIALTY_HINTS:
        if needle in lowered and label not in found:
            found.append(label)
    return found


def _record_ollama_values(
    profile: ModelProfile, model: OllamaModel, show: OllamaShow | None, at: datetime
) -> ModelProfile:
    info = show.model_info if show is not None else {}
    arch = info.get("general.architecture")
    ctx_max = model.context_length
    if ctx_max is None and isinstance(arch, str):
        ctx_max = _int(info.get(f"{arch}.context_length"))
    caps = show.capabilities if show is not None else model.capabilities

    entries: list[tuple[str, Any, Source]] = [
        ("identity.family", model.family, "ollama"),
        ("identity.parameter_size", model.parameter_size, "ollama"),
        ("identity.parameter_count", _int(info.get("general.parameter_count")), "ollama"),
        ("identity.quantization", model.quantization_level, "ollama"),
        ("identity.download_size_bytes", model.size, "ollama"),
        ("identity.context_length_max", ctx_max, "ollama"),
        ("identity.kv_bytes_per_token", kv_bytes_per_token(info), "ollama"),
        ("identity.num_ctx", modelfile_num_ctx(show.parameters) if show is not None else None, "modelfile"),
        ("identity.specialty", _specialty(model.name) or None, "name"),
    ]
    for cap in ("tools", "vision", "thinking", "embedding"):
        entries.append((f"capabilities.{cap}", cap in caps, "ollama"))
    for key, value, source in entries:
        if value is not None:
            profile = record(profile, key, value, source, at)
    return profile


def profile_from_ollama(model: OllamaModel, show: OllamaShow | None, *, at: datetime) -> ModelProfile:
    profile = ModelProfile(provider="ollama", model=model.name, names=[model.name], digest=model.digest)
    return _record_ollama_values(profile, model, show, at)


def apply_running(profile: ModelProfile, running: OllamaRunning, *, at: datetime) -> ModelProfile:
    profile = record(profile, "performance.vram_bytes", running.size_vram, "measured", at)
    profile = record(profile, "performance.loaded_size_bytes", running.size, "measured", at)
    if running.context_length is not None:
        profile = record(profile, "performance.loaded_context_length", running.context_length, "measured", at)
    return profile


def refresh_from_ollama(
    profile: ModelProfile, model: OllamaModel, show: OllamaShow | None, *, at: datetime
) -> ModelProfile:
    """Replace ollama/modelfile/name values; measured, eval and user are untouched."""
    values = {
        key: kept
        for key, entries in profile.values.items()
        if (kept := [s for s in entries if s.source not in _REFRESHABLE])
    }
    cleared = profile.model_copy(update={"values": values, "digest": model.digest})
    return _record_ollama_values(cleared, model, show, at)
