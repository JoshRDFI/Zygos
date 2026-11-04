"""Will a model fit? Visible estimate parts and a one-line description (RFC-0013 §3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from zygos.hardware.probe import HardwareSnapshot
from zygos.models.profile import ModelProfile, resolve

ASSUMED_CONTEXT_TOKENS = 4096
RUNTIME_OVERHEAD_BYTES = 512 * 1024**2
KOKORO_CUDA_RESERVE_BYTES = 1_400 * 1024**2
KV_BYTES_PER_ELEMENT = 2

FitLevel = Literal["gpu", "partial", "no", "unknown"]


class FitEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_bytes: int | None
    context_bytes: int | None
    context_tokens: int
    context_assumed: bool
    overhead_bytes: int
    total_bytes: int | None
    measured: bool


class Fit(BaseModel):
    model_config = ConfigDict(frozen=True)

    level: FitLevel
    needs: FitEstimate
    vram_available_bytes: int | None
    ram_available_bytes: int | None
    reason: str


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


def fit(profile: ModelProfile, hardware: HardwareSnapshot | None,
        vram: VramContext = VramContext()) -> Fit:
    needs = estimate(profile)
    vram_free = None if hardware is None else hardware.vram_free_bytes
    ram = None if hardware is None else hardware.ram_available_bytes
    available: int | None = None
    if vram_free is not None:
        available = vram_free + vram.reclaimable_bytes - vram.reserve_bytes
        if needs.measured:  # a loaded model already holds this VRAM
            available += _int(profile, "performance.vram_bytes") or 0
        available = max(0, available)

    def result(level: FitLevel, reason: str = "") -> Fit:
        return Fit(level=level, needs=needs, vram_available_bytes=available,
                   ram_available_bytes=ram, reason=reason)

    if needs.total_bytes is None:
        return result("unknown", "size unknown" if needs.model_bytes is None else "context size unknown")
    if available is None:
        return result("unknown", "GPU not detected")
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
        text = f"needs ≈{total} GB: {model} + {ctx} + {_gb(n.overhead_bytes)} GB overhead{free}"
    if f.level == "unknown" and f.reason:
        text += f" — {f.reason}"
    return text
