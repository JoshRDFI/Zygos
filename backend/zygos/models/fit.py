"""Will a model fit? Visible estimate parts and a one-line description (RFC-0013 §3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from zygos.backends.launch import LaunchSettings
from zygos.hardware.probe import HardwareSnapshot
from zygos.models.profile import ModelProfile, resolve

ASSUMED_CONTEXT_TOKENS = 4096
RUNTIME_OVERHEAD_BYTES = 512 * 1024**2
KOKORO_CUDA_RESERVE_BYTES = 1_400 * 1024**2
KV_BYTES_PER_ELEMENT = 2
# Bytes per KV-cache element for llama.cpp's --cache-type-k/-v names.
KV_TYPE_BYTES: dict[str, float] = {
    "f32": 4.0, "f16": 2.0, "bf16": 2.0, "q8_0": 34 / 32, "q4_0": 18 / 32,
    "q4_1": 20 / 32, "q5_0": 22 / 32, "q5_1": 24 / 32, "iq4_nl": 18 / 32,
}
ASSUMED_CONTEXT_NOTE = f"context {ASSUMED_CONTEXT_TOKENS} tokens"
ASSUMED_ALL_LAYERS_NOTE = "all layers on GPU (llama-server default)"
ASSUMED_AUTO_LAYERS_NOTE = "all layers on GPU (-ngl auto)"

FitLevel = Literal["gpu", "partial", "no", "unknown"]
GPU_SIDE_REASON = "the GPU part doesn't fit in free VRAM"
RAM_SIDE_REASON = "the RAM part doesn't fit in available RAM"


class FitEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_bytes: int | None
    context_bytes: int | None
    context_tokens: int
    context_assumed: bool
    overhead_bytes: int
    total_bytes: int | None
    measured: bool
    # llama.cpp (RFC-0014 §4): where the bytes go under the launch settings.
    gpu_bytes: int | None = None
    cpu_bytes: int | None = None
    split_by: Literal["settings"] | None = None
    assumptions: tuple[str, ...] = ()
    reason: str | None = None  # why total_bytes is None, when the generic reason would mislead
    # Ollama spills what VRAM can't hold into RAM; llama.cpp puts exactly what the
    # launch settings say on the GPU, so an overflowing GPU part doesn't fit.
    spill: bool = True


class Fit(BaseModel):
    model_config = ConfigDict(frozen=True)

    level: FitLevel
    needs: FitEstimate
    vram_available_bytes: int | None
    ram_available_bytes: int | None
    reason: str
    gpu_bytes: int | None = None
    cpu_bytes: int | None = None
    split_by: Literal["settings"] | None = None


class VramContext(BaseModel):
    """VRAM adjustments outside the hardware snapshot.

    ``reclaimable_bytes``: held by other loaded Ollama models, which Ollama
    unloads to make room. ``reserve_bytes``: about to be taken but not in use
    yet (Kokoro on CUDA configured but not running).
    """

    model_config = ConfigDict(frozen=True)

    reclaimable_bytes: int = 0
    reserve_bytes: int = 0


def _int(profile: ModelProfile, key: str) -> int | None:
    s = resolve(profile, key)
    return s.value if s is not None and isinstance(s.value, int) else None


def estimate(profile: ModelProfile) -> FitEstimate:
    loaded = _int(profile, "performance.loaded_size_bytes")
    if loaded is not None:
        return FitEstimate(
            model_bytes=loaded, context_bytes=0,
            context_tokens=_int(profile, "performance.loaded_context_length") or ASSUMED_CONTEXT_TOKENS,
            context_assumed=False, overhead_bytes=0, total_bytes=loaded, measured=True)
    model_bytes = _int(profile, "identity.download_size_bytes")
    num_ctx = _int(profile, "identity.num_ctx")
    tokens = num_ctx or ASSUMED_CONTEXT_TOKENS
    kv = _int(profile, "identity.kv_bytes_per_token")
    context_bytes = None if kv is None else kv * tokens
    parts = (model_bytes, context_bytes)
    total = None if None in parts else model_bytes + context_bytes + RUNTIME_OVERHEAD_BYTES
    return FitEstimate(
        model_bytes=model_bytes, context_bytes=context_bytes, context_tokens=tokens,
        context_assumed=not num_ctx, overhead_bytes=RUNTIME_OVERHEAD_BYTES,
        total_bytes=total, measured=False)


def _by_index(table: object) -> dict[int, int] | None:
    if not isinstance(table, dict):
        return None
    out: dict[int, int] = {}
    for k, v in table.items():
        try:
            i = int(k)
        except (TypeError, ValueError):
            return None
        if not isinstance(v, int) or isinstance(v, bool):
            return None
        out[i] = v
    return out


def estimate_llamacpp(profile: ModelProfile, launch: LaunchSettings) -> FitEstimate:
    """Split estimate for a GGUF under llama-server launch settings.

    ``-ngl N`` puts the last N layers on GPU; ``--n-cpu-moe N`` keeps the expert
    tensors of the first N layers on CPU; non-layer tensors go to GPU only when
    every layer does. ``-np`` splits the context across slots, so it adds nothing.
    ``-c 0`` means the model's training context. A paired projector (Zygos
    passes ``--mmproj``) is loaded on GPU.
    """
    assumptions: list[str] = []
    context_assumed = launch.ctx_size is None
    if launch.ctx_size is None:
        tokens: int | None = ASSUMED_CONTEXT_TOKENS
        assumptions.append(ASSUMED_CONTEXT_NOTE)
    elif launch.ctx_size == 0:
        tokens = _int(profile, "identity.context_length_max")
    else:
        tokens = launch.ctx_size
    blocks = _int(profile, "identity.block_count")
    ngl = launch.n_gpu_layers
    all_on_gpu = ngl in (None, "all", "auto") or (blocks is not None and ngl >= blocks)
    if ngl is None:
        assumptions.append(ASSUMED_ALL_LAYERS_NOTE)
    elif ngl == "auto":
        assumptions.append(ASSUMED_AUTO_LAYERS_NOTE)

    def unknown(model_bytes: int | None, context_bytes: int | None = None,
                reason: str | None = None) -> FitEstimate:
        return FitEstimate(
            model_bytes=model_bytes, context_bytes=context_bytes, context_tokens=tokens or 0,
            context_assumed=context_assumed, overhead_bytes=RUNTIME_OVERHEAD_BYTES,
            total_bytes=None, measured=False, assumptions=tuple(assumptions), reason=reason,
            spill=False)

    tb = resolve(profile, "identity.tensor_bytes")
    table = tb.value if tb is not None and isinstance(tb.value, dict) else None
    layers = None if table is None else _by_index(table.get("layers"))
    experts = None if table is None else _by_index(table.get("experts", {}))
    other = None if table is None else table.get("other")
    if layers is None or experts is None or not isinstance(other, int) or isinstance(other, bool):
        return unknown(None)
    mmproj = _int(profile, "identity.mmproj_bytes") or 0
    model_bytes = sum(layers.values()) + other + mmproj
    if tokens is None:
        return unknown(model_bytes, reason="context length unknown")

    for t in (launch.cache_type_k, launch.cache_type_v):
        if t is not None and t not in KV_TYPE_BYTES:
            return unknown(model_bytes, reason=f"unknown cache type {t}")
    kv_heads = _int(profile, "identity.kv_heads")
    key_len = _int(profile, "identity.key_length")
    value_len = _int(profile, "identity.value_length")
    if None in (blocks, kv_heads, key_len, value_len):
        return unknown(model_bytes)
    k_bytes = KV_TYPE_BYTES[launch.cache_type_k or "f16"]
    v_bytes = KV_TYPE_BYTES[launch.cache_type_v or "f16"]
    kv_per_layer = kv_heads * (key_len * k_bytes + value_len * v_bytes) * tokens

    first_gpu = 0 if all_on_gpu else blocks - max(0, ngl)
    on_gpu = [i for i in layers if i >= first_gpu]
    cpu_moe = launch.n_cpu_moe or 0
    gpu_weights = sum(layers[i] for i in on_gpu)
    gpu_weights -= sum(experts.get(i, 0) for i in on_gpu if i < cpu_moe)
    if all_on_gpu:
        gpu_weights += other
    gpu_weights += mmproj
    gpu_kv_layers = 0 if launch.no_kv_offload else (blocks if all_on_gpu else min(blocks, max(0, ngl)))
    context_bytes = round(kv_per_layer * blocks)
    gpu_kv = round(kv_per_layer * gpu_kv_layers)
    gpu = gpu_weights + gpu_kv + RUNTIME_OVERHEAD_BYTES
    cpu = (model_bytes - gpu_weights) + (context_bytes - gpu_kv)
    return FitEstimate(
        model_bytes=model_bytes, context_bytes=context_bytes, context_tokens=tokens,
        context_assumed=context_assumed, overhead_bytes=RUNTIME_OVERHEAD_BYTES,
        total_bytes=gpu + cpu, measured=False, gpu_bytes=gpu, cpu_bytes=cpu,
        split_by="settings" if cpu > 0 else None, assumptions=tuple(assumptions), spill=False)


def fit(profile: ModelProfile, hardware: HardwareSnapshot | None,
        vram: VramContext = VramContext(), *, loaded: bool = False,
        needs: FitEstimate | None = None) -> Fit:
    """``loaded``: the model is in Ollama's ``/api/ps`` right now, so the VRAM it
    holds (``performance.vram_bytes``) is credited back. A profile keeps its
    measured values after the model unloads; those earn no credit.

    ``needs``: a precomputed estimate (llama.cpp's ``estimate_llamacpp``);
    defaults to ``estimate(profile)``."""
    if needs is None:
        needs = estimate(profile)
    vram_free = None if hardware is None else hardware.vram_free_bytes
    ram = None if hardware is None else hardware.ram_available_bytes
    available: int | None = None
    if vram_free is not None:
        available = vram_free + vram.reclaimable_bytes - vram.reserve_bytes
        if loaded:  # a loaded model already holds this VRAM
            available += _int(profile, "performance.vram_bytes") or 0
        available = max(0, available)

    def result(level: FitLevel, reason: str = "") -> Fit:
        return Fit(level=level, needs=needs, vram_available_bytes=available,
                   ram_available_bytes=ram, reason=reason, gpu_bytes=needs.gpu_bytes,
                   cpu_bytes=needs.cpu_bytes, split_by=needs.split_by)

    size_reason = None
    if needs.total_bytes is None:
        size_reason = needs.reason or (
            "size unknown" if needs.model_bytes is None else "context size unknown")
    if available is None:
        return result("unknown", "GPU not detected" + (f"; {size_reason}" if size_reason else ""))
    if size_reason is not None:
        return result("unknown", size_reason)
    if not needs.spill and needs.gpu_bytes is not None:
        if needs.gpu_bytes > available:
            return result("no", GPU_SIDE_REASON)
        if not needs.cpu_bytes:
            return result("gpu")
        if ram is None:
            return result("unknown", "RAM unknown")
        if needs.cpu_bytes > ram:
            return result("no", RAM_SIDE_REASON)
        return result("partial")
    if needs.total_bytes <= available:
        return result("gpu")
    if ram is None:
        return result("unknown", "RAM unknown")
    return result("partial" if needs.total_bytes <= available + ram else "no")


def _gb(n: int) -> str:
    return f"{n / 1024**3:.1f}"


def describe(f: Fit) -> str:
    n = f.needs
    free = "" if f.vram_available_bytes is None else f"; {_gb(f.vram_available_bytes)} GB free"
    if n.measured:
        text = f"uses {_gb(n.total_bytes)} GB (measured){free}"
    else:
        total = "?" if n.total_bytes is None else _gb(n.total_bytes)
        model = "size unknown" if n.model_bytes is None else f"{_gb(n.model_bytes)} GB model"
        if n.context_bytes is None:
            ctx = "context unknown"
        else:
            note = ", assumed" if n.context_assumed else ""
            ctx = f"{_gb(n.context_bytes)} GB context ({n.context_tokens} tokens{note})"
        parts = f"{model} + {ctx} + {_gb(n.overhead_bytes)} GB overhead{free}"
        if n.split_by == "settings":
            text = (f"needs ≈{_gb(n.gpu_bytes)} GB on GPU + {_gb(n.cpu_bytes)} GB in RAM"
                    f" (split by your settings): {parts}")
        else:
            text = f"needs ≈{total} GB: {parts}"
        if n.assumptions:
            text += "; assumed: " + ", ".join(n.assumptions)
    if f.level in ("unknown", "no") and f.reason:
        text += f" — {f.reason}"
    return text
