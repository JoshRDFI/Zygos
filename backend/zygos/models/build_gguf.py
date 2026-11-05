"""Model profiles for llama.cpp GGUF files (RFC-0014 §3).

Built from the GGUF header only. Header facts are ``modelfile``-sourced, name
hints ``name``-sourced; anything the header does not state is not recorded.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from zygos.models.build import specialty
from zygos.models.fit import KV_BYTES_PER_ELEMENT
from zygos.models.gguf import GgufHeader
from zygos.models.gguf_scan import GgufModel
from zygos.models.profile import ModelProfile, Source, record
from zygos.providers.types import LLAMACPP_PROVIDER

# llama.cpp LLAMA_FTYPE values (general.file_type) for the common quantizations.
QUANT_NAMES: dict[int, str] = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1",
    10: "Q2_K", 11: "Q3_K_S", 12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M",
    16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K", 19: "IQ2_XXS", 20: "IQ2_XS", 21: "Q2_K_S",
    22: "IQ3_XS", 23: "IQ3_XXS", 24: "IQ1_S", 25: "IQ4_NL", 26: "IQ3_S", 27: "IQ3_M",
    28: "IQ2_S", 29: "IQ2_M", 30: "IQ4_XS", 31: "IQ1_M", 32: "BF16",
    36: "TQ1_0", 37: "TQ2_0", 38: "MXFP4_MOE",
}

_LAYER = re.compile(r"^blk\.(\d+)\.")
_EXPERT = re.compile(r"^blk\.(\d+)\.ffn_[^.]*_exps\.")


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _digest(model: GgufModel) -> str | None:
    mtimes: list[int] = []
    for f in model.files:
        try:
            mtimes.append(f.stat().st_mtime_ns)
        except OSError:
            continue
    return f"size:{model.size_bytes}:mtime:{max(mtimes)}" if mtimes else None


def gguf_digest(model: GgufModel) -> str | None:
    """Size and newest mtime of the model's files: a change means "re-read the header"."""
    return _digest(model)


def _mmproj_bytes(model: GgufModel) -> int | None:
    if model.mmproj is None:
        return None
    try:
        return model.mmproj.stat().st_size
    except OSError:
        return None


def tensor_bytes(header: GgufHeader) -> dict[str, Any]:
    """Bytes per layer (string index, for JSON), expert bytes within each layer, and the rest."""
    layers: dict[str, int] = {}
    experts: dict[str, int] = {}
    other = 0
    for t in header.tensors:
        m = _LAYER.match(t.name)
        if m is None:
            other += t.size_bytes
            continue
        i = str(int(m.group(1)))
        layers[i] = layers.get(i, 0) + t.size_bytes
        if _EXPERT.match(t.name):
            experts[i] = experts.get(i, 0) + t.size_bytes
    order = lambda d: dict(sorted(d.items(), key=lambda kv: int(kv[0])))  # noqa: E731
    return {"layers": order(layers), "experts": order(experts), "other": other}


def profile_from_gguf(model: GgufModel, header: GgufHeader, *, at: datetime) -> ModelProfile:
    meta = header.metadata
    profile = ModelProfile(provider=LLAMACPP_PROVIDER, model=model.name, names=[model.name],
                           digest=_digest(model))
    arch = meta.get("general.architecture")
    arch = arch if isinstance(arch, str) and arch else None

    def a(key: str) -> int | None:
        return None if arch is None else _int(meta.get(f"{arch}.{key}"))

    ftype = _int(meta.get("general.file_type"))
    blocks = a("block_count")
    kv_heads = a("attention.head_count_kv")
    embedding, heads = a("embedding_length"), a("attention.head_count")
    fallback = embedding // heads if embedding is not None and heads else None
    key_len = a("attention.key_length") or fallback
    value_len = a("attention.value_length") or fallback
    kv_per_token = (
        None if None in (blocks, kv_heads, key_len, value_len)
        else blocks * kv_heads * (key_len + value_len) * KV_BYTES_PER_ELEMENT
    )

    entries: list[tuple[str, Any, Source]] = [
        ("identity.family", arch, "modelfile"),
        ("identity.architecture", arch, "modelfile"),
        ("identity.parameter_count", _int(meta.get("general.parameter_count")), "modelfile"),
        ("identity.quantization", None if ftype is None else QUANT_NAMES.get(ftype), "modelfile"),
        ("identity.download_size_bytes", model.size_bytes, "modelfile"),
        ("identity.context_length_max", a("context_length"), "modelfile"),
        ("identity.block_count", blocks, "modelfile"),
        ("identity.kv_heads", kv_heads, "modelfile"),
        ("identity.key_length", key_len, "modelfile"),
        ("identity.value_length", value_len, "modelfile"),
        ("identity.kv_bytes_per_token", kv_per_token, "modelfile"),
        ("identity.tensor_bytes", tensor_bytes(header) if header.tensors else None, "modelfile"),
        ("identity.specialty", specialty(model.name) or None, "name"),
        ("identity.mmproj_bytes", _mmproj_bytes(model), "modelfile"),
        ("capabilities.vision", True if model.mmproj is not None else None, "modelfile"),
    ]
    for key, value, source in entries:
        if value is not None:
            profile = record(profile, key, value, source, at)
    return profile
