"""One-line hardware text shared by doctor and ``zygos inspect`` (RFC-0013 §1).

Anything undetected renders ``unknown`` -- never a guess.
"""
from __future__ import annotations

from zygos.hardware.probe import HardwareSnapshot

_GB = 1024**3


def _gb(value: int | None) -> str:
    return "unknown" if value is None else f"{value / _GB:.1f}"


def describe_hardware(snap: HardwareSnapshot) -> str:
    if snap.gpus:
        gpu = (f"GPU {', '.join(g.name for g in snap.gpus)}: {_gb(snap.vram_total_bytes)} GB VRAM, "
               f"{_gb(snap.vram_free_bytes)} GB free")
    else:
        gpu = "GPU unknown"
    ram = f"RAM {_gb(snap.ram_available_bytes)}/{_gb(snap.ram_total_bytes)} GB"
    threads = "unknown" if snap.cpu_cores is None else str(snap.cpu_cores)
    cpu = f"CPU {snap.cpu_model or 'unknown'} ({threads} threads)"
    disk = f"disk {_gb(snap.disk_free_bytes)} GB free"
    text = f"{gpu} · {ram} · {cpu} · {disk}"
    if not snap.gpus:
        text += " — GPU not detected: model fit can't be checked"
    return text
